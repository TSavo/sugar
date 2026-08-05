"""Teeth for run-authority/v1: what a sugarbin run proves it consumed.

The defect these teeth hold shut: `bin/brun --env docker:... -- bash -lc
'<script>'` with no `--task` matched no registered task command prefix, so the
shell wrapper HID the showcase ownership. The run selected the ordinary
capability image, installed no managed precondition plan, enrolled no profiled
closure artifacts, died mid-initialization on `FileNotFoundError: git`, and its
0/6 result was banked as though it were a measurement.

Nothing here forbids that command. What it forbids is banking the result.

Three states, three distinct names, never two — plus the lying arm, which is
the one that matters. Each tooth asserts the SPECIFIC refusal name, because a
tooth satisfied by a neighbouring refusal survives its own guard's removal and
proves nothing.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


RA = _load("run_authority", "tools/run_authority.py")
CM = _load("commit_measurement", "tools/commit_measurement.py")

# The exact entrance from issue #7340: a showcase producer loop wrapped in
# `bash -lc`, dispatched with no --task.
ADHOC_ARGV = ["bash", "-lc", "for s in federation base20 base64; do make showcase-$s; done"]

DECLARED_COMMANDS = {
    "showcases": ["make", "test-showcases"],
    "rust-unit": ["cargo", "test", "--manifest-path", "implementations/rust/Cargo.toml"],
}


def _resolver(task: str):
    return DECLARED_COMMANDS.get(task)


def _managed(**overrides) -> dict:
    testimony = {
        "schema": RA.RUN_AUTHORITY_SCHEMA,
        "authority": RA.AUTHORITY_MANAGED,
        "task": "showcases",
        "image": "sha256:showcase-capability-image",
        "preflightProtocol": "managed-entrypoint/v1",
        "preconditionPlanCid": RA.plan_cid({"checks": [], "task": "showcases"}),
        "command": ["make", "test-showcases"],
    }
    testimony.update(overrides)
    return testimony


def _unmanaged(**overrides) -> dict:
    testimony = {
        "schema": RA.RUN_AUTHORITY_SCHEMA,
        "authority": RA.AUTHORITY_UNMANAGED,
        "task": None,
        "image": "sha256:ordinary-capability-image",
        "preflightProtocol": None,
        "preconditionPlanCid": None,
        "command": list(ADHOC_ARGV),
    }
    testimony.update(overrides)
    return testimony


# ---------------------------------------------------------------------------
# Three states are three states. Absent is not unmanaged is not mismatched.
# ---------------------------------------------------------------------------


def test_absent_unmanaged_and_managed_are_three_distinct_readings() -> None:
    absent = pytest.raises(
        RA.RunAuthorityRefusal, match=RA.REFUSAL_ABSENT
    )
    with absent:
        RA.authenticate_run_authority(None, task_command_resolver=_resolver)

    ad_hoc = RA.authenticate_run_authority(_unmanaged(), task_command_resolver=_resolver)
    assert isinstance(ad_hoc, RA.UnmanagedRunAuthority)
    assert ad_hoc.is_managed() is False
    assert ad_hoc.command == tuple(ADHOC_ARGV)

    owned = RA.authenticate_run_authority(_managed(), task_command_resolver=_resolver)
    assert isinstance(owned, RA.ManagedRunAuthority)
    assert owned.is_managed() is True
    assert owned.task == "showcases"
    assert owned.image == "sha256:showcase-capability-image"
    assert owned.preflight_protocol == "managed-entrypoint/v1"

    # Distinct types, not one type with a flag: no reading can be silently
    # substituted for another.
    assert type(ad_hoc) is not type(owned)


def test_absence_has_its_own_refusal_name() -> None:
    with pytest.raises(RA.RunAuthorityRefusal) as caught:
        RA.authenticate_run_authority(None, task_command_resolver=_resolver)
    text = str(caught.value)
    assert RA.REFUSAL_ABSENT in text, text
    # Absence must NOT be reported as any neighbouring state.
    assert RA.REFUSAL_MALFORMED not in text
    assert RA.REFUSAL_UNOWNED_COMMAND not in text
    assert "unmanaged" not in text.lower().split(":")[0]


# ---------------------------------------------------------------------------
# THE LYING ARM. A genuinely ad-hoc run recorded as managed must refuse.
# ---------------------------------------------------------------------------


def test_adhoc_run_claiming_managed_authority_refuses_as_unowned_command() -> None:
    """The dangerous arm: a confident false claim, not an absent one.

    The testimony is complete, well-formed, names a real declared task, a real
    showcase image and a real plan cid. Everything about it *spells* managed.
    The only thing wrong is that the task does not own the command that ran.
    """
    lying = _managed(command=list(ADHOC_ARGV))
    with pytest.raises(RA.RunAuthorityRefusal) as caught:
        RA.authenticate_run_authority(lying, task_command_resolver=_resolver)
    text = str(caught.value)
    assert RA.REFUSAL_UNOWNED_COMMAND in text, text
    # It must not be satisfied by a neighbouring refusal.
    assert RA.REFUSAL_ABSENT not in text
    assert RA.REFUSAL_MALFORMED not in text
    assert RA.REFUSAL_UNDECLARED_TASK not in text
    # The refusal must name the specific divergence, not merely that one exists.
    assert "showcases" in text
    assert "bash" in text
    assert "make" in text


def test_lying_claim_cannot_borrow_a_bash_prefixed_task() -> None:
    """A wrapper that merely starts with the same interpreter is still unowned."""
    resolver = {"scoreboard": ["bash", "scripts/test-3809-dod-scoreboard.sh"]}.get
    lying = _managed(task="scoreboard", command=list(ADHOC_ARGV))
    with pytest.raises(RA.RunAuthorityRefusal) as caught:
        RA.authenticate_run_authority(lying, task_command_resolver=resolver)
    assert RA.REFUSAL_UNOWNED_COMMAND in str(caught.value)


def test_managed_claim_naming_an_undeclared_task_has_its_own_name() -> None:
    lying = _managed(task="showcases-but-not-really")
    with pytest.raises(RA.RunAuthorityRefusal) as caught:
        RA.authenticate_run_authority(lying, task_command_resolver=_resolver)
    text = str(caught.value)
    assert RA.REFUSAL_UNDECLARED_TASK in text, text
    assert RA.REFUSAL_UNOWNED_COMMAND not in text
    assert RA.REFUSAL_MALFORMED not in text


# ---------------------------------------------------------------------------
# Malformed / conflicting testimony is its own refusal, not a coerced state.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation,why",
    [
        ({"schema": "run-authority/v2"}, "unsupported schema"),
        ({"schema": None}, "missing schema"),
        ({"authority": "partially-managed"}, "invented authority"),
        ({"authority": None}, "absent authority field"),
        ({"image": ""}, "image not named"),
        ({"command": []}, "no argv recorded"),
        ({"command": "make test-showcases"}, "argv is not an array"),
        ({"preflightProtocol": None}, "managed without preflight"),
        ({"preconditionPlanCid": ""}, "plan cid present but empty"),
        ({"preconditionPlanCid": 7}, "plan cid is not a string"),
    ],
)
def test_malformed_managed_testimony_refuses_as_malformed(mutation, why) -> None:
    with pytest.raises(RA.RunAuthorityRefusal) as caught:
        RA.authenticate_run_authority(
            _managed(**mutation), task_command_resolver=_resolver
        )
    assert RA.REFUSAL_MALFORMED in str(caught.value), f"{why}: {caught.value}"


def test_unmanaged_testimony_carrying_managed_fields_is_conflicting() -> None:
    """Half-managed is not a state. Conflicting testimony is refused, not coerced."""
    for key, value in (
        ("task", "showcases"),
        ("preflightProtocol", "managed-entrypoint/v1"),
        ("preconditionPlanCid", "blake2b-256:" + "0" * 64),
    ):
        with pytest.raises(RA.RunAuthorityRefusal) as caught:
            RA.authenticate_run_authority(
                _unmanaged(**{key: value}), task_command_resolver=_resolver
            )
        text = str(caught.value)
        assert RA.REFUSAL_MALFORMED in text, text
        assert key in text


def test_non_object_testimony_is_malformed_not_absent() -> None:
    for junk in (17, [1, 2, 3]):
        with pytest.raises(RA.RunAuthorityRefusal) as caught:
            RA.authenticate_run_authority(junk, task_command_resolver=_resolver)
        text = str(caught.value)
        assert RA.REFUSAL_MALFORMED in text, text
        assert RA.REFUSAL_ABSENT not in text
        assert "must be an object" in text, text


def test_undecodable_json_transport_refuses_on_the_decode_arm() -> None:
    """Named by the same refusal, but reached down its own path.

    Asserting only that something MALFORMED was raised would leave this
    satisfied by the non-object guard downstream, so the decode arm could be
    deleted with this tooth still green. The detail is what discriminates.
    """
    for junk in ("{not json", b'{"schema": '):
        with pytest.raises(RA.RunAuthorityRefusal) as caught:
            RA.authenticate_run_authority(junk, task_command_resolver=_resolver)
        text = str(caught.value)
        assert RA.REFUSAL_MALFORMED in text, text
        assert "is not JSON" in text, text
        assert "must be an object" not in text, text


def test_testimony_survives_json_string_transport() -> None:
    """The transport hands it over as an env string; the reading is the same."""
    authority = RA.authenticate_run_authority(
        json.dumps(_managed()), task_command_resolver=_resolver
    )
    assert isinstance(authority, RA.ManagedRunAuthority)


# ---------------------------------------------------------------------------
# The wrong state is unrepresentable, not guarded.
# ---------------------------------------------------------------------------


def test_managed_authority_cannot_be_spelled_without_authentication() -> None:
    with pytest.raises(RA.RunAuthorityRefusal, match=RA.REFUSAL_MALFORMED):
        RA.ManagedRunAuthority(
            "showcases", "sha256:x", "managed-entrypoint/v1", "cid", ("make",), object()
        )
    with pytest.raises(RA.RunAuthorityRefusal, match=RA.REFUSAL_MALFORMED):
        RA.UnmanagedRunAuthority(("bash",), "sha256:x", object())


# ---------------------------------------------------------------------------
# UNMEASURED BY CONSTRUCTION. Not flagged — unconstructible.
# ---------------------------------------------------------------------------


def _body(failed: int = 3, collected: int = 12) -> dict:
    return {
        "schemaVersion": 1,
        "kind": "sole-construction-floor-axis-report",
        "totals": {"failed": failed, "collected": collected},
    }


def _mint(run_authority):
    return CM.measured(
        3,
        identity="native-crash",
        unit=CM.UNIT_CORPUS_FILE,
        population_id="pop:corpus",
        population_size=12,
        body=_body(),
        value_field_path="totals.failed",
        exit_code=1,
        run_authority=run_authority,
        task_command_resolver=_resolver,
    )


def test_measurement_from_an_unmanaged_run_is_unconstructible() -> None:
    with pytest.raises(CM.CommitMeasurementError) as caught:
        _mint(_unmanaged())
    text = str(caught.value)
    assert RA.REFUSAL_UNMEASURED_BY_CONSTRUCTION in text, text
    # Specifically NOT the absence refusal: the run testified honestly, and the
    # honest testimony is what makes the measurement unbankable.
    assert RA.REFUSAL_ABSENT not in text


def test_measurement_from_a_lying_managed_claim_is_unconstructible() -> None:
    with pytest.raises(CM.CommitMeasurementError) as caught:
        _mint(_managed(command=list(ADHOC_ARGV)))
    assert RA.REFUSAL_UNOWNED_COMMAND in str(caught.value)


def test_a_declared_task_with_no_closure_is_owned_but_still_unbankable() -> None:
    """The fifth state, surfaced by bin/bpytest's own wrapper task.

    `authenticated-python-lift` is a genuinely declared, genuinely owned task
    that declares no command closure, so no precondition plan is installed. The
    transport records that honestly rather than fabricating a plan; the
    measurement door refuses it under its own name, distinct from both the
    ad-hoc reading and the lying one.
    """
    owned_but_unplanned = _managed(preconditionPlanCid=None)
    authority = RA.authenticate_run_authority(
        owned_but_unplanned, task_command_resolver=_resolver
    )
    assert isinstance(authority, RA.ManagedRunAuthority)
    assert authority.precondition_plan_cid is None

    with pytest.raises(CM.CommitMeasurementError) as caught:
        _mint(owned_but_unplanned)
    text = str(caught.value)
    assert RA.REFUSAL_UNPLANNED_TASK in text, text
    assert RA.REFUSAL_UNMEASURED_BY_CONSTRUCTION not in text
    assert RA.REFUSAL_UNOWNED_COMMAND not in text
    assert RA.REFUSAL_ABSENT not in text


def test_measurement_with_no_run_authority_at_all_is_unconstructible() -> None:
    with pytest.raises(CM.CommitMeasurementError) as caught:
        _mint(None)
    assert RA.REFUSAL_ABSENT in str(caught.value)


def test_sealing_an_unmanaged_authority_into_measured_refuses_by_name() -> None:
    """The last line of defence, reached only by a caller holding the seal.

    Through the public `measured(...)` door this is unreachable:
    `require_managed_run_authority` refuses first and always hands the
    constructor a ManagedRunAuthority. So this tooth constructs Measured
    directly WITH the seal — the position a future edit inside the module
    would occupy — and proves the type still will not admit an unmanaged run.

    Without this, the isinstance check in Measured.__post_init__ is dead
    weight: it can be deleted with nothing observable changing.
    """
    ad_hoc = RA.authenticate_run_authority(_unmanaged(), task_command_resolver=_resolver)
    assert isinstance(ad_hoc, RA.UnmanagedRunAuthority)

    with pytest.raises(CM.CommitMeasurementError) as caught:
        CM.Measured(
            3,
            "native-crash",
            CM.UNIT_CORPUS_FILE,
            "pop:corpus",
            12,
            "blake2b-256:" + "0" * 64,
            "totals.failed",
            1,
            ad_hoc,
            CM._MEASURED_SEAL,
        )
    text = str(caught.value)
    assert "ManagedRunAuthority" in text, text
    assert "UnmanagedRunAuthority" in text, text
    assert "THE ARTIFACT MUST PROVE WHAT IT CONSUMED" in text, text

    # And the same position with a genuine managed authority does construct,
    # so the tooth is discriminating rather than refusing everything.
    managed = RA.authenticate_run_authority(_managed(), task_command_resolver=_resolver)
    sealed = CM.Measured(
        3,
        "native-crash",
        CM.UNIT_CORPUS_FILE,
        "pop:corpus",
        12,
        "blake2b-256:" + "0" * 64,
        "totals.failed",
        1,
        managed,
        CM._MEASURED_SEAL,
    )
    assert sealed.run_authority.task == "showcases"


def test_measurement_from_a_managed_run_constructs_and_carries_its_authority() -> None:
    reading = _mint(_managed())
    assert reading.is_measured() is True
    assert reading.run_authority.task == "showcases"
    assert reading.run_authority.image == "sha256:showcase-capability-image"


def test_body_carried_authority_reaches_the_durable_composition() -> None:
    """Carried in the receipt, not merely logged."""
    body = dict(_body())
    body["runAuthority"] = _managed()
    reading = CM.measured_from_body(
        identity="native-crash",
        unit=CM.UNIT_CORPUS_FILE,
        population_id="pop:corpus",
        population_size=12,
        body=body,
        value_field_path="totals.failed",
        exit_code=1,
        task_command_resolver=_resolver,
    )
    assert reading.is_measured(), reading
    projected = CM._measured_json(reading)["runAuthority"]
    assert projected["schema"] == RA.RUN_AUTHORITY_SCHEMA
    assert projected["authority"] == RA.AUTHORITY_MANAGED
    assert projected["task"] == "showcases"
    assert projected["preconditionPlanCid"] == _managed()["preconditionPlanCid"]


def test_body_carrying_unmanaged_authority_reads_unmeasured_not_measured() -> None:
    body = dict(_body())
    body["runAuthority"] = _unmanaged()
    reading = CM.measured_from_body(
        identity="native-crash",
        unit=CM.UNIT_CORPUS_FILE,
        population_id="pop:corpus",
        population_size=12,
        body=body,
        value_field_path="totals.failed",
        exit_code=1,
        task_command_resolver=_resolver,
    )
    assert reading.is_measured() is False
    assert RA.REFUSAL_UNMEASURED_BY_CONSTRUCTION in reading.reason
    assert not isinstance(reading, CM.Measured)


# ---------------------------------------------------------------------------
# The producer end: the real reproduction, through the real contract CLI.
# ---------------------------------------------------------------------------


def _contract(*args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/sugar-build/contract.py"), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_the_reported_entrance_still_matches_no_task() -> None:
    """The measured defect, unchanged: recognition by spelling sees nothing."""
    assert _contract("match-command", "--", *ADHOC_ARGV) == {"task": None}


def test_the_reported_entrance_now_carries_explicit_unmanaged_testimony() -> None:
    """Same command, still permitted — but no longer silent about its authority."""
    testimony = _contract(
        "run-authority", "--image", "sha256:ordinary-capability-image", "--", *ADHOC_ARGV
    )
    assert testimony["authority"] == RA.AUTHORITY_UNMANAGED
    assert testimony["task"] is None
    assert testimony["preconditionPlanCid"] is None
    assert testimony["command"] == ADHOC_ARGV
    # And it is durable testimony, not a log line: it authenticates.
    authority = RA.authenticate_run_authority(testimony, task_command_resolver=_resolver)
    assert isinstance(authority, RA.UnmanagedRunAuthority)


def test_a_named_task_produces_managed_testimony_that_authenticates() -> None:
    testimony = _contract(
        "run-authority",
        "--image",
        "sha256:showcase-capability-image",
        "--task",
        "showcases",
        "--preflight",
        "managed-entrypoint/v1",
        "--plan-json",
        json.dumps({"checks": [], "task": "showcases"}),
        "--",
        "make",
        "test-showcases",
    )
    assert testimony["authority"] == RA.AUTHORITY_MANAGED
    authority = RA.authenticate_run_authority(testimony)
    assert isinstance(authority, RA.ManagedRunAuthority)
    assert authority.task == "showcases"


def test_producer_stamp_door_round_trips_the_transport_env() -> None:
    """One carrier name, stamped through one door, read by one authenticator."""
    body = RA.stamp_run_authority(
        {"totals": {"failed": 0}}, {RA.RUN_AUTHORITY_ENV: json.dumps(_managed())}
    )
    authority = RA.authenticate_run_authority(
        body["runAuthority"], task_command_resolver=_resolver
    )
    assert isinstance(authority, RA.ManagedRunAuthority)

    # No transport testimony means the body carries none, and the consumer
    # reads absence rather than inventing a permissive default.
    bare = RA.stamp_run_authority({"totals": {"failed": 0}}, {})
    assert "runAuthority" not in bare
    with pytest.raises(RA.RunAuthorityRefusal, match=RA.REFUSAL_ABSENT):
        RA.authenticate_run_authority(bare.get("runAuthority"))


def test_producer_refuses_to_emit_half_evidenced_managed_testimony() -> None:
    """A managed claim cannot be constructed without its image and its preflight."""
    with pytest.raises(RA.RunAuthorityRefusal, match=RA.REFUSAL_MALFORMED):
        RA.build_run_authority(
            ["make", "test-showcases"],
            image="sha256:x",
            task="showcases",
            preflight_protocol=None,
            precondition_plan={"checks": []},
        )
    with pytest.raises(RA.RunAuthorityRefusal, match=RA.REFUSAL_MALFORMED):
        RA.build_run_authority(ADHOC_ARGV, image="")
    with pytest.raises(RA.RunAuthorityRefusal, match=RA.REFUSAL_MALFORMED):
        RA.build_run_authority([], image="sha256:x")

    # A closureless task is emitted honestly rather than fabricated into a plan.
    unplanned = RA.build_run_authority(
        ["python", "-m", "sugar_lift_py_tests.authenticated_pytest"],
        image="sha256:x",
        task="authenticated-python-lift",
        preflight_protocol="workspace-wrapper/v1",
        precondition_plan=None,
    )
    assert unplanned["preconditionPlanCid"] is None
    assert unplanned["authority"] == RA.AUTHORITY_MANAGED
