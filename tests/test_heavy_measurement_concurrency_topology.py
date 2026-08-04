"""GitHub retains every run; there is no machine-wide measurement lease.

Jobs run in parallel. A global mutex is not a resource model. Attendance is
keyed off identity-bound measurement bodies, not lease grabs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
LEASE_WRAPPER = "tools/heavy_measurement_lease.py"
GATE = "tools/heavy_measurement_lease_gate.py"

# Heavy measurement classes: workflow -> roster key (measurementClass).
HEAVY_WORKFLOWS = {
    "python-package-suite.yml": "python-package-suite",
    "factory-zero-tolerance.yml": "python-sole-construction-floors",
    "numpy-wall.yml": "numpy-wall",
    "pandas-wall.yml": "pandas-wall",
    "restored-suite-scoreboard.yml": "restored-suite-scoreboard",
    "control-effect-recensus.yml": "control-effect-recensus",
}

RETIRED_GROUPS = ("sugar-python-heavy-measurement", "sugar-python-package-suite")
STANDALONE_FLOOR_WORKFLOWS = (
    "bare-exception-zero-tolerance.yml",
    "timeout-zero-tolerance.yml",
    "native-crash-zero-tolerance.yml",
)


def _text(name):
    return (WORKFLOWS / name).read_text()


def _attendance_module():
    from importlib import util

    spec = util.spec_from_file_location(
        "heavy_measurement_attendance",
        ROOT / "tools" / "heavy_measurement_attendance.py",
    )
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("workflow", sorted(HEAVY_WORKFLOWS))
def test_heavy_workflows_declare_no_concurrency_group(workflow):
    text = _text(workflow)
    assert not re.search(r"^concurrency:", text, re.MULTILINE), (
        f"{workflow} declares a GitHub concurrency group"
    )
    for group in RETIRED_GROUPS:
        assert group not in text


@pytest.mark.parametrize("workflow", sorted(HEAVY_WORKFLOWS))
def test_no_workflow_uses_the_deleted_machine_wide_lease(workflow):
    text = _text(workflow)
    assert LEASE_WRAPPER not in text, (
        f"{workflow} still wraps work in {LEASE_WRAPPER}; the machine-wide "
        f"lease is deleted — jobs run in parallel"
    )
    assert GATE not in text, f"{workflow} still calls the deleted lease gate"
    assert "lease-record.json" not in text


def test_lease_tools_are_deleted():
    assert not (ROOT / LEASE_WRAPPER).exists()
    assert not (ROOT / GATE).exists()
    assert not (ROOT / "tools/heavy_measurement_lease_record.py").exists()


def test_no_heavy_workflow_cancels_a_superseded_run():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text()
        assert "cancel-in-progress: true" not in text, path.name


def test_no_workflow_shares_a_concurrency_group_across_commits():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text()
        match = re.search(r"^concurrency:\n(?:[ \t]+.*\n?)+", text, re.MULTILINE)
        if match is None:
            continue
        assert "github.sha" in match.group(0), path.name


def test_attendance_roster_matches_the_heavy_workflows():
    module = _attendance_module()
    assert set(module.HEAVY_ROSTER) == set(HEAVY_WORKFLOWS.values())
    for workflow, lease_class in HEAVY_WORKFLOWS.items():
        name = (
            re.search(r"^name:\s*(.+)$", _text(workflow), re.MULTILINE)
            .group(1)
            .strip()
        )
        assert module.HEAVY_ROSTER[lease_class] == name


def test_standalone_floor_workflows_stay_discrimination_only():
    for name in STANDALONE_FLOOR_WORKFLOWS:
        text = _text(name)
        for group in RETIRED_GROUPS:
            assert group not in text


def test_orchestrator_still_runs_the_corpus_floors():
    """Process axes are matrix jobs; static laws a sibling job; enrollment roll call."""
    text = _text("factory-zero-tolerance.yml")
    assert "run_one_process_floor_axis.sh" in text
    assert "run_static_sole_construction_floors.sh" in text
    assert "sole_construction_floor_enrollment.py" in text
    assert "matrix:" in text
    # Local serial convenience still lists the corpus instruments.
    floors = (ROOT / "tools" / "run_sole_construction_floors.sh").read_text()
    static = (ROOT / "tools" / "run_static_sole_construction_floors.sh").read_text()
    for script in (
        "native_crash_zero_tolerance.py",
        "bare_exception_zero_tolerance.py",
        "timeout_zero_tolerance.py",
        "silent_zero_tolerance.py",
    ):
        assert script in floors, script
        assert script in text, script
    for script in (
        "factory_ownership_law.py",
        "construction_side_door_law.py",
    ):
        assert script in static, script


def test_roster_cadence_matches_each_workflow_trigger():
    module = _attendance_module()
    for workflow, lease_class in HEAVY_WORKFLOWS.items():
        text = _text(workflow)
        on_block = re.split(r"^[a-zA-Z]", text.split("on:", 1)[1], maxsplit=1)[0]
        cadence = module.HEAVY_CADENCE[lease_class]
        if cadence == module.PER_COMMIT:
            assert "push:" in on_block and "main" in on_block, lease_class
        else:
            assert "schedule:" in on_block, lease_class


def test_the_two_cadences_are_never_summed():
    module = _attendance_module()
    source = Path(module.__file__).read_text()
    assert "R_attendance_commit" in source and "R_attendance_nightly" in source
    assert "len(HEAVY_ROSTER)" not in source


def test_the_authoritative_scoreboard_is_on_the_roster():
    module = _attendance_module()
    # Sole seal door (serial seal retired from the walk script).
    authority = (
        ROOT
        / "implementations/python/sugar-lift-py-tests/scripts/compose_control_effect_board.py"
    )
    worker = (
        ROOT
        / "implementations/python/sugar-lift-py-tests/scripts/control_effect_recensus.py"
    )
    assert "SCOREBOARD_AUTHORITY = True" in authority.read_text()
    assert "SCOREBOARD_AUTHORITY = False" in worker.read_text()
    assert "control-effect-recensus" in module.HEAVY_ROSTER
    assert module.HEAVY_CADENCE["control-effect-recensus"] == module.NIGHTLY_WINDOW


def test_attendance_keys_off_measurement_body_not_lease(tmp_path):
    module = _attendance_module()
    body = {
        "schemaVersion": 1,
        "measurementClass": "python-sole-construction-floors",
        "measuredCommit": "abc",
        "totals": {"failed": 0},
    }
    path = tmp_path / "floor-measurement.json"
    path.write_text(__import__("json").dumps(body), encoding="utf-8")
    attended, _ = module.receipts_attendance(tmp_path)
    assert "python-sole-construction-floors" in attended


def test_floor_workflow_is_parallel_matrix_with_enrollment():
    """Process axes must not serialize inside one job after lease deletion."""
    text = _text("factory-zero-tolerance.yml")
    assert "matrix:" in text
    assert "floor-enrollment" in text or "floor-enrollment:" in text
    assert "run_one_process_floor_axis.sh" in text
    assert "run_static_sole_construction_floors.sh" in text
    assert "run_sole_construction_floors.sh" not in text
    assert LEASE_WRAPPER not in text


def test_roll_call_composes_under_the_declared_python_environment():
    """CommitMeasurement imports package code and must not use ambient python3."""
    text = _text("heavy-measurement-attendance.yml")
    assert "uses: ./.github/actions/python-test-environment" in text
    assert "id: roll-call-env" in text
    managed_python = '"${{ steps.roll-call-env.outputs.python }}"'
    assert f"{managed_python} -u tools/heavy_measurement_attendance.py" in text
    assert f"{managed_python} -u - <<'PY'" in text
    assert f"{managed_python} -u tools/commit_measurement_gate.py" in text
    assert "python3 -u tools/heavy_measurement_attendance.py" not in text
    assert "python3 -u tools/commit_measurement_gate.py" not in text


def test_process_floor_matrix_restores_and_saves_ca_terminal_shelf():
    """Parallel jobs must not each cold-lift: fleet-wide actions/cache over the CA shelf.

    HOME alone only shares same-host matrix landings. restore/save keyed by tip
    makes the shelf available across runners; MeasurementKey still binds corpus
    and file content so wrong population cannot hit.
    """
    text = _text("factory-zero-tolerance.yml")
    assert "actions/cache/restore@v4" in text
    assert "actions/cache/save@v4" in text
    assert "process-floor-term-${{ github.sha }}" in text
    assert "process-floor-terminals" in text
    assert "SUGAR_PROCESS_FLOOR_CACHE_DIR" in text


def test_smoke_body_under_path_hint_does_not_attend_control_effect_recensus(tmp_path):
    """False-enrollment spoof: smoke under PATH_HINTS path must not attend the board.

    measurementClass recensus-path-smoke is not on HEAVY_ROSTER, so classification
    used to fall through to PATH_HINTS. A path containing 'pandas-control-effect'
    then marked control-effect-recensus ATTENDED from a 0.7s path seal.
    """
    module = _attendance_module()
    # Plant under a path that carries the authoritative PATH_HINT fragment.
    spoof = tmp_path / "pandas-control-effect" / "smoke_seal.json"
    spoof.parent.mkdir(parents=True)
    body = {
        "schemaVersion": 1,
        "kind": "recensus-path-smoke-verdict",
        "measurementClass": "recensus-path-smoke",
        "pathVerdict": "PATH_OK",
        "measuredCommit": "deadbeef",
        # Even with identity-bound markers, smoke must not attend.
        "environmentIdentityHash": "blake3-512_fake",
        "totals": {"failed": 0},
    }
    spoof.write_text(__import__("json").dumps(body), encoding="utf-8")
    attended, testimony = module.receipts_attendance(tmp_path)
    assert "control-effect-recensus" not in attended, (
        f"smoke under PATH_HINT path attended the board: {attended}"
    )
    assert module._class_from_payload(spoof, body) is None
    # Kind alone under spoof path is also refused.
    body_kind_only = {
        "kind": "recensus-path-smoke-verdict",
        "measuredCommit": "deadbeef",
        "totals": {"failed": 0},
    }
    spoof2 = tmp_path / "control-effect-recensus" / "kind_only.json"
    spoof2.parent.mkdir(parents=True, exist_ok=True)
    spoof2.write_text(__import__("json").dumps(body_kind_only), encoding="utf-8")
    attended2, _ = module.receipts_attendance(tmp_path)
    assert "control-effect-recensus" not in attended2


def test_smoke_workflow_artifact_path_avoids_path_hints():
    """Defense in depth: smoke seals live under recensus-path-smoke/ only."""
    text = _text("recensus-path-smoke.yml")
    assert "recensus-path-smoke" in text
    # Must not write smoke under PATH_HINTS fragments for the board.
    assert "pandas-control-effect" not in text
    # control-effect-recensus as class name in comments is ok; artifact path is not.
    assert ".sugar/recensus-path-smoke" in text or "RECENSUS_PATH_SMOKE_OUT" in text
