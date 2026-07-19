"""The binding Python construction job must invoke every permanent R axis."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "factory-zero-tolerance.yml"

AXIS_COMMANDS = {
    "R_behavior_side_doors = 0": "factory_zero_tolerance.py",
    "R_ownership = 0": "factory_ownership_law.py",
    "R_factory_panic_catches_outside_audit = 0": "factory_panic_catch_law.py",
    "R_silent = 0": "silent_zero_tolerance.py",
    "R_native_crashes = 0": "native_crash_zero_tolerance.py",
    "R_bare_exceptions = 0": "bare_exception_zero_tolerance.py",
    "R_timeouts = 0": "timeout_zero_tolerance.py",
    "R_vendor_special_case = 0": "vendor_special_case_law.py",
    "R_factory_walk_unclassified = 0": "factory_walk_unclassified_law.py",
    "R_finite_cap_opaque_completions = 0": (
        "finite_cap_opaque_completion_law.py"
    ),
}


def test_binding_job_invokes_every_permanent_axis() -> None:
    workflow = WORKFLOW.read_text()

    assert "python-sole-construction-floors:" in workflow
    for axis, command in AXIS_COMMANDS.items():
        step_start = workflow.find(f"- name: {axis}")
        assert step_start >= 0, f"{axis} is not bound to merge CI"
        step_end = workflow.find("\n      - name:", step_start + 1)
        step = workflow[step_start : step_end if step_end >= 0 else None]
        assert command in step, f"{axis} does not invoke {command}"
        if axis == "R_factory_walk_unclassified = 0":
            assert "--live-root" in step, (
                "R_factory_walk_unclassified only runs a fixture/discrimination; "
                "binding CI must census the checked-in production surface"
            )
        if axis != "R_behavior_side_doors = 0":
            assert "if: always()" in step, (
                f"{axis} would be skipped after an earlier honest-red axis"
            )
