"""Discrimination teeth for sealed showcase terminal identities and joins."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
sys.path.insert(0, str(ROOT / "tools"))

import showcase_scope  # noqa: E402

OLD_TERMINAL = {
    "schemaVersion": 1,
    "kind": "construction-panic",
    "owner": "SubscriptOperation.subscript_symbolic",
    "coordinate": "fixture.py:7:12",
    "observed": "OpaqueValue",
    "requested": "TermFloor",
    "entrance": "sugar.enumerate:facts:auditFrontier",
}
MOVED_TERMINAL = {
    "schemaVersion": 1,
    "kind": "construction-panic",
    "owner": "BinaryOperationExceptionFloor",
    "coordinate": "fixture.py:7:17",
    "observed": "CallSiteValue >> TermValue",
    "requested": "BinaryOperationEffect",
    "entrance": "binary-operation-exception-floor",
}


def _counts(outcomes: list[dict[str, object]]) -> dict[str, int]:
    return {
        "enrolled": len(outcomes),
        "executed": sum(row["outcome"] != "retired" for row in outcomes),
        "retired": sum(row["outcome"] == "retired" for row in outcomes),
        "passed": sum(row["outcome"] == "passed" for row in outcomes),
        "failed": sum(row["outcome"] == "failed" for row in outcomes),
        "unmeasured": sum(row["outcome"] == "unmeasured" for row in outcomes),
    }


def _body(commit: str, outcomes: list[dict[str, object]]) -> dict[str, object]:
    counts = _counts(outcomes)
    return {
        "schemaVersion": 2,
        "measurementClass": "test-showcases",
        "shardIndex": 0,
        "shardCount": 1,
        "measuredCommit": commit,
        "status": "unmeasured" if counts["unmeasured"] else "completed",
        "exitCode": 1 if counts["failed"] or counts["unmeasured"] else 0,
        "showcaseCounts": counts,
        "showcaseOutcomes": outcomes,
    }


def _failed(path: str, terminal: dict[str, object]) -> dict[str, object]:
    return {
        "path": path,
        "outcome": "failed",
        "exitCode": 1,
        "terminalIdentity": terminal,
    }


def _passed(path: str) -> dict[str, object]:
    return {
        "path": path,
        "outcome": "passed",
        "exitCode": 0,
        "subjectWitness": {"schemaVersion": 1, "subjectId": path},
    }


def _write_manifest(path: Path) -> None:
    path.write_text(
        json.dumps({"schemaVersion": 1, "retirements": []}) + "\n",
        encoding="utf-8",
    )


def _write_failing_script(
    path: Path,
    *,
    terminal: dict[str, object] | None,
) -> None:
    testimony = ""
    if terminal is not None:
        testimony = (
            "printf '%s\\n' "
            + json.dumps(json.dumps(terminal, separators=(",", ":")))
            + ' > "${SHOWCASE_TERMINAL_WITNESS:?}"\n'
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/usr/bin/env sh\nset -eu\n" + testimony + "exit 7\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_failed_body_without_raw_terminal_identity_refuses() -> None:
    path = "examples/failing/run.sh"
    body = _body(
        "before",
        [{"path": path, "outcome": "failed", "exitCode": 1}],
    )

    with pytest.raises(
        showcase_scope.ScopeRefusal,
        match="failed showcase lacks authenticated terminal identity",
    ):
        showcase_scope.validate_shard_body(body)


def test_nonzero_without_terminal_witness_is_unmeasured_not_failed(
    tmp_path: Path,
) -> None:
    script = "examples/failing/run.sh"
    _write_failing_script(tmp_path / script, terminal=None)
    manifest = tmp_path / "retirements.json"
    _write_manifest(manifest)
    receipt = tmp_path / "scope.json"

    assert (
        showcase_scope.run_shard(
            repo_root=tmp_path,
            manifest_path=manifest,
            enrolled=[script],
            shard_count=1,
            shard_index=0,
            attr_dir=tmp_path / "logs",
            receipt_path=receipt,
        )
        != 0
    )
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["counts"]["failed"] == 0
    assert payload["counts"]["unmeasured"] == 1
    assert payload["outcomes"] == [
        {
            "path": script,
            "outcome": "unmeasured",
            "exitCode": 7,
            "reason": "terminal-witness-absent",
        }
    ]


def test_raw_terminal_identity_is_sealed_into_failed_body(tmp_path: Path) -> None:
    script = "examples/failing/run.sh"
    _write_failing_script(tmp_path / script, terminal=OLD_TERMINAL)
    manifest = tmp_path / "retirements.json"
    _write_manifest(manifest)
    scope_path = tmp_path / "scope.json"

    assert (
        showcase_scope.run_shard(
            repo_root=tmp_path,
            manifest_path=manifest,
            enrolled=[script],
            shard_count=1,
            shard_index=0,
            attr_dir=tmp_path / "logs",
            receipt_path=scope_path,
        )
        != 0
    )
    scope_receipt = json.loads(scope_path.read_text(encoding="utf-8"))
    body_path = tmp_path / "body.json"
    body = showcase_scope.seal_shard_body(
        scope_receipt,
        measured_commit="abc",
        exit_code=1,
        output_path=body_path,
    )

    assert body["showcaseOutcomes"][0]["terminalIdentity"] == OLD_TERMINAL
    assert json.loads(body_path.read_text(encoding="utf-8")) == body


def test_malformed_terminal_witness_is_unmeasured_not_failed(tmp_path: Path) -> None:
    script = "examples/failing/run.sh"
    malformed = dict(OLD_TERMINAL)
    malformed["owner"] = ""
    _write_failing_script(tmp_path / script, terminal=malformed)
    manifest = tmp_path / "retirements.json"
    _write_manifest(manifest)
    receipt = tmp_path / "scope.json"

    assert (
        showcase_scope.run_shard(
            repo_root=tmp_path,
            manifest_path=manifest,
            enrolled=[script],
            shard_count=1,
            shard_index=0,
            attr_dir=tmp_path / "logs",
            receipt_path=receipt,
        )
        != 0
    )
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["counts"]["failed"] == 0
    assert payload["counts"]["unmeasured"] == 1
    assert payload["outcomes"][0]["reason"] == "terminal-witness-malformed"
    assert "terminalIdentity" not in payload["outcomes"][0]


def test_join_distinguishes_cleared_same_and_moved_terminals() -> None:
    cleared = "examples/cleared/run.sh"
    same = "examples/same/run.sh"
    moved = "examples/moved/run.sh"
    before = _body(
        "before",
        [
            _failed(cleared, OLD_TERMINAL),
            _failed(same, OLD_TERMINAL),
            _failed(moved, OLD_TERMINAL),
        ],
    )
    after = _body(
        "after",
        [
            _passed(cleared),
            _failed(same, OLD_TERMINAL),
            _failed(moved, MOVED_TERMINAL),
        ],
    )

    joined = showcase_scope.join_terminal_bodies([before], [after])

    assert joined["status"] == "completed"
    assert joined["counts"] == {
        "inputFailures": 3,
        "cleared": 1,
        "stillFailingSameTerminal": 1,
        "movedToNamedTerminal": 1,
    }
    rows = {row["path"]: row for row in joined["rows"]}
    assert rows[cleared]["transition"] == "cleared"
    assert rows[same]["transition"] == "still-failing-same-terminal"
    assert rows[moved] == {
        "path": moved,
        "transition": "moved-to-named-terminal",
        "beforeTerminalIdentity": OLD_TERMINAL,
        "afterTerminalIdentity": MOVED_TERMINAL,
    }


def test_join_refuses_unknown_terminal_instead_of_treating_it_as_no_terminal() -> None:
    path = "examples/unknown/run.sh"
    before = _body("before", [_failed(path, OLD_TERMINAL)])
    after = _body(
        "after",
        [
            {
                "path": path,
                "outcome": "unmeasured",
                "exitCode": 1,
                "reason": "terminal-witness-absent",
            }
        ],
    )

    with pytest.raises(
        showcase_scope.ScopeRefusal,
        match="terminal join cannot classify unmeasured row",
    ):
        showcase_scope.join_terminal_bodies([before], [after])
