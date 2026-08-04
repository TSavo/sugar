"""Dormant three-state contract for showcase terminal testimony."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
sys.path.insert(0, str(ROOT / "tools"))

import showcase_scope  # noqa: E402
import showcase_terminal_identity  # noqa: E402


IDENTITY = {
    "schemaVersion": 1,
    "kind": "ConstructionPanic",
    "owner": "ComparisonOpSugar.Eq",
    "coordinate": "fixture.py:4:11",
    "observed": "undecided binary compare",
    "requested": "authenticated exception coordinate",
    "entrance": "sugar.enumerate:facts:auditFrontier",
}


def witnessed() -> dict[str, object]:
    return showcase_terminal_identity.witnessed_terminal_state(IDENTITY)


def no_owner_possible() -> dict[str, object]:
    return showcase_terminal_identity.no_owner_possible_terminal_state(
        producer_contract="ownerless-rpc-terminal/v1",
        entrance="sugar.verify",
        reason="producer-contract-has-no-owner",
    )


def construct_missing() -> dict[str, object]:
    return showcase_terminal_identity.terminal_construct_missing_state(
        expected_contract="SHOWCASE_TERMINAL_WITNESS/v1",
        reason="terminal-state-absent",
    )


def failed(path: str, state: dict[str, object]) -> dict[str, object]:
    outcome = "failed" if state["state"] == "witnessed" else "unmeasured"
    row: dict[str, object] = {
        "path": path,
        "outcome": outcome,
        "exitCode": 7,
        "terminalState": state,
    }
    if outcome == "unmeasured":
        row["reason"] = state["state"]
    return row


def passed(path: str) -> dict[str, object]:
    return {
        "path": path,
        "outcome": "passed",
        "exitCode": 0,
        "subjectWitness": {"schemaVersion": 1, "subjectId": path},
    }


def test_existing_identity_publishes_as_witnessed_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "terminal.json"
    monkeypatch.setenv("SHOWCASE_TERMINAL_WITNESS", str(output))

    assert showcase_terminal_identity.write_from_environment(IDENTITY) is True
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "schemaVersion": 1,
        "state": "witnessed",
        "terminalIdentity": IDENTITY,
    }


def test_closed_state_shapes_preserve_negative_and_missing_as_distinct() -> None:
    assert no_owner_possible() == {
        "schemaVersion": 1,
        "state": "no-owner-possible",
        "producerContract": "ownerless-rpc-terminal/v1",
        "entrance": "sugar.verify",
        "reason": "producer-contract-has-no-owner",
        "disposition": "pending-ruling",
    }
    assert construct_missing() == {
        "schemaVersion": 1,
        "state": "terminal-construct-missing",
        "expectedContract": "SHOWCASE_TERMINAL_WITNESS/v1",
        "reason": "terminal-state-absent",
    }
    assert "terminalIdentity" not in no_owner_possible()
    assert "terminalIdentity" not in construct_missing()
    assert "exemption" not in construct_missing()


def test_one_envelope_cannot_claim_two_states() -> None:
    overlapped = witnessed()
    overlapped.update(
        {
            "producerContract": "ownerless-rpc-terminal/v1",
            "entrance": "sugar.verify",
            "reason": "producer-contract-has-no-owner",
            "disposition": "pending-ruling",
        }
    )

    with pytest.raises(
        showcase_terminal_identity.TerminalIdentityRefusal,
        match="witnessed terminal state fields",
    ):
        showcase_terminal_identity.validate_showcase_terminal_state(overlapped)


def test_malformed_terminal_state_becomes_scope_refusal_not_a_fourth_state() -> None:
    malformed = witnessed()
    malformed["terminalIdentity"] = {"schemaVersion": 1, "kind": "gap"}
    rows = [failed("examples/malformed/run.sh", malformed)]

    with pytest.raises(showcase_scope.ScopeRefusal, match="terminal state malformed"):
        showcase_scope.validate_terminal_state_conservation(
            rows,
            {
                "terminalWitnessed": 1,
                "noOwnerPossible": 0,
                "terminalConstructMissing": 0,
            },
        )


def test_terminal_state_conservation_closes_exactly() -> None:
    rows = [
        failed("examples/witnessed/run.sh", witnessed()),
        failed("examples/no-owner/run.sh", no_owner_possible()),
        failed("examples/missing/run.sh", construct_missing()),
        passed("examples/passed/run.sh"),
    ]

    assert showcase_scope.validate_terminal_state_conservation(
        rows,
        {
            "terminalWitnessed": 1,
            "noOwnerPossible": 1,
            "terminalConstructMissing": 1,
        },
    ) == {
        "terminalWitnessed": 1,
        "noOwnerPossible": 1,
        "terminalConstructMissing": 1,
    }


def test_nonzero_row_in_no_state_refuses_conservation() -> None:
    rows = [{"path": "examples/missing/run.sh", "outcome": "failed", "exitCode": 7}]

    with pytest.raises(
        showcase_scope.ScopeRefusal,
        match="nonzero executed showcase lacks terminal state",
    ):
        showcase_scope.validate_terminal_state_conservation(
            rows,
            {
                "terminalWitnessed": 0,
                "noOwnerPossible": 0,
                "terminalConstructMissing": 0,
            },
        )


def test_row_in_two_states_refuses_before_balanced_counts_can_hide_it() -> None:
    overlapped = witnessed()
    overlapped["expectedContract"] = "SHOWCASE_TERMINAL_WITNESS/v1"
    overlapped["reason"] = "terminal-state-absent"

    with pytest.raises(showcase_scope.ScopeRefusal, match="terminal state malformed"):
        showcase_scope.validate_terminal_state_conservation(
            [failed("examples/overlap/run.sh", overlapped)],
            {
                "terminalWitnessed": 1,
                "noOwnerPossible": 0,
                "terminalConstructMissing": 0,
            },
        )


def test_join_distinguishes_cleared_same_and_moved_witnesses() -> None:
    moved_identity = dict(IDENTITY)
    moved_identity["owner"] = "ReceiverFieldStoreStateSugar"
    moved_identity["coordinate"] = "fixture.py:8:4"

    before = failed("examples/demo/run.sh", witnessed())
    assert showcase_scope.classify_terminal_transition(
        before,
        passed("examples/demo/run.sh"),
    )["transition"] == "cleared"
    assert showcase_scope.classify_terminal_transition(
        before,
        failed("examples/demo/run.sh", witnessed()),
    )["transition"] == "still-failing-same-terminal"
    moved = showcase_scope.classify_terminal_transition(
        before,
        failed(
            "examples/demo/run.sh",
            showcase_terminal_identity.witnessed_terminal_state(moved_identity),
        ),
    )
    assert moved["transition"] == "moved-to-named-terminal"
    assert moved["beforeTerminalIdentity"] == IDENTITY
    assert moved["afterTerminalIdentity"] == moved_identity


@pytest.mark.parametrize("state_name", ["no-owner-possible", "construct-missing"])
def test_join_keeps_nonwitness_state_explicitly_unmeasured(
    state_name: str,
) -> None:
    state = (
        no_owner_possible()
        if state_name == "no-owner-possible"
        else construct_missing()
    )
    joined = showcase_scope.classify_terminal_transition(
        failed("examples/demo/run.sh", witnessed()),
        failed("examples/demo/run.sh", state),
    )

    assert joined["transition"] == "unmeasured"
    assert joined["afterTerminalState"] == state
    assert "afterTerminalIdentity" not in joined
