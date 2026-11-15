"""Sole-construction floors: static axes bound, enrollment roll call honest.

Completeness is enrollment roll call (tools/sole_construction_floor_enrollment.py).
A missing axis is UNMEASURED.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
ENROLL = ROOT / "tools" / "sole_construction_floor_enrollment.py"
STATIC = ROOT / "tools" / "run_static_sole_construction_floors.sh"
FLOOR_SET = ROOT / "tools" / "run_sole_construction_floors.sh"

STATIC_SCRIPTS = {
    "R_ownership = 0": "factory_ownership_law.py",
    "R_construction_panic_catches_outside_membrane = 0": (
        "construction_panic_catch_law.py"
    ),
    "R_vendor_special_case = 0": "vendor_special_case_law.py",
    "R_factory_walk_unclassified = 0": "factory_walk_unclassified_law.py",
    "R_finite_cap_opaque_completions = 0": "finite_cap_opaque_completion_law.py",
    "R_finite_unfold_compact_gaps = 0": "finite_unfold_compact_projection_law.py",
    "R_source_via_execution = 0": "source_via_execution_law.py",
    "R_no_sugar_in_desugar = 0": "no_sugar_in_desugar_law.py",
    "R_construction_side_doors = 0": "construction_side_door_law.py",
}


def _enroll_mod():
    spec = importlib.util.spec_from_file_location(
        "sole_construction_floor_enrollment", ENROLL
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _witness():
    from sugar_lift_py_tests.conservation_mint import ConservedBody, seal_after_validation

    outcome = seal_after_validation(
        measured_payload={"kind": "test-source-body"},
        input_key_manifest=[{"key": "same"}],
        output_key_manifest=[{"key": "same"}],
        validator_stage_id="test-floor-validator/v1",
        validator_source_path=Path(__file__),
        validate=lambda: None,
    )
    assert isinstance(outcome, ConservedBody)
    return outcome.witness


def test_static_job_binds_every_static_axis() -> None:
    static = STATIC.read_text()
    for axis, command in STATIC_SCRIPTS.items():
        assert f'axis "{axis}"' in static or f"axis '{axis}'" in static
        axis_start = static.find(f'axis "{axis}"')
        if axis_start < 0:
            axis_start = static.find(f"axis '{axis}'")
        axis_end = static.find("\naxis ", axis_start + 1)
        step = static[axis_start : axis_end if axis_end >= 0 else None]
        assert command in step
        if axis == "R_factory_walk_unclassified = 0":
            assert "--live-root" in step


def test_enrollment_missing_axis_is_unmeasured(tmp_path: Path) -> None:
    mod = _enroll_mod()
    # Only one of five enrolled axes present.
    report = mod.mint_axis_report(
        axis_id="silent-s00",
        display="R_silent[s00]",
        commit_sha="deadbeef",
        exit_code=0,
        kind="process",
        residual_count=0,
        conservation_witness=_witness(),
    )
    path = tmp_path / "floor-axis-silent-s00" / mod.REPORT_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(report), encoding="utf-8")
    code, summary = mod.check_attendance(tmp_path, require_commit="deadbeef")
    assert code == 1
    assert summary["status"] == "UNMEASURED"
    assert "native-crash-s00" in summary["missing"]
    assert "silent-s00" in summary["attended"]


def test_enrollment_complete_with_all_axes(tmp_path: Path) -> None:
    mod = _enroll_mod()
    for axis in mod.ENROLLED:  # process LPT seats + static
        is_timeout = axis.axis_id.startswith("timeout-")
        report = mod.mint_axis_report(
            axis_id=axis.axis_id,
            display=axis.display,
            commit_sha="abc123",
            exit_code=0 if not is_timeout else 1,
            kind=axis.kind,
            # Magnitude from floor summary identity — not invented from exit.
            residual_count=3 if is_timeout else 0,
            conservation_witness=_witness(),
        )
        path = tmp_path / f"floor-axis-{axis.axis_id}" / mod.REPORT_FILENAME
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(report), encoding="utf-8")
    code, summary = mod.check_attendance(tmp_path, require_commit="abc123")
    assert code == 0
    assert summary["status"] == "complete"
    assert summary["residualRed"] == [f"timeout-s{i:02d}" for i in range(8)]


def test_local_monolith_still_lists_process_axes_for_workstation() -> None:
    """Local serial script lists every process axis."""
    floors = FLOOR_SET.read_text()
    for name in (
        'axis "R_silent"',
        'axis "R_native_crashes"',
        'axis "R_bare_exceptions"',
        'axis "R_timeouts"',
    ):
        assert name in floors
    assert "authenticated_pandas_corpus" in floors
