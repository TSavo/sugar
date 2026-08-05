"""Teeth for criterion-2 tip vector: units + R_construction_panics enrollment.

Complete requires every CRITERION2 axis Measured — including
R_construction_panics from the control-effect recensus board. Four green
process floors alone are Partial (panics that resolve to typed gaps exit 0 on
those floors and are invisible there).
"""

from __future__ import annotations

import importlib.util
import json
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


CM = _load("commit_measurement", "tools/commit_measurement.py")
RA = _load("run_authority", "tools/run_authority.py")

# Every Measured now carries authenticated MANAGED run authority. These teeth
# are about units and composition, so they run under one genuine managed run:
# the declared `showcases` task, whose contract command owns this argv.
MANAGED_TESTIMONY = {
    "schema": RA.RUN_AUTHORITY_SCHEMA,
    "authority": RA.AUTHORITY_MANAGED,
    "task": "showcases",
    "image": "sha256:showcase-capability-image",
    "preflightProtocol": "managed-entrypoint/v1",
    "preconditionPlanCid": RA.plan_cid({"checks": [], "task": "showcases"}),
    "command": ["make", "test-showcases"],
}


def _measured(*args, **kwargs):
    kwargs.setdefault("run_authority", MANAGED_TESTIMONY)
    return CM.measured(*args, **kwargs)

GATE = _load("commit_measurement_gate", "tools/commit_measurement_gate.py")


def _floor_body(axis_id: str, failed: int = 0, collected: int = 100) -> dict:
    return {
        "schemaVersion": 1,
        "kind": "sole-construction-floor-axis-report",
        "axisId": axis_id,
        "measurementClass": "python-sole-construction-floors",
        "measuredCommit": "deadbeef",
        "status": "completed",
        "exitCode": 0 if failed == 0 else 1,
        "identityResolved": True,
        "measured": True,
        "totals": {"failed": failed, "collected": collected},
        "populationId": f"corpus:{axis_id}",
        "populationSize": collected,
        "runAuthority": MANAGED_TESTIMONY,
    }


def _recensus_body(panics: int = 0, files: int = 1415) -> dict:
    return {
        "schemaVersion": 1,
        "measurementClass": "control-effect-recensus",
        "measurement": "measured",
        "conservationWitness": {
            "witnessSchema": "sugar.conservation-witness.v1",
            "inputKeyManifestCid": "sha256:" + ("a" * 64),
            "inputKeyCount": files,
            "outputKeyManifestCid": "sha256:" + ("b" * 64),
            "outputKeyCount": files,
            "validatorStageId": "compose-terminal-aggregate-seal/v1",
            "validatorSourceCid": "sha256:" + ("c" * 64),
            "status": "passed",
        },
        "measuredCommit": "deadbeef",
        "runAuthority": MANAGED_TESTIMONY,
        "R_construction_panics": panics,
        "constructionPanics": [{"x": i} for i in range(panics)],
        "enrolledFiles": files,
        "populationSize": files,
    }


def _body(failed: int = 3, collected: int = 12) -> dict:
    return {
        "totals": {"failed": failed, "collected": collected},
        "failedNodeIds": ["x"] * failed,
    }


def test_scoreboard_authority_false() -> None:
    assert CM.SCOREBOARD_AUTHORITY is False


def test_criterion2_enrolls_construction_panics() -> None:
    ids = {s.identity for s in CM.CRITERION2_AXIS_SPECS}
    assert "R_construction_panics" in ids
    assert ids == {
        "silent",
        "native-crash",
        "bare-exception",
        "timeout",
        "R_construction_panics",
    }
    assert CM.TIP_AXIS_SPECS is CM.CRITERION2_AXIS_SPECS or list(
        CM.TIP_AXIS_SPECS
    ) == list(CM.CRITERION2_AXIS_SPECS)


def test_process_floor_units_are_not_the_same() -> None:
    by_id = {s.identity: s for s in CM.CRITERION2_AXIS_SPECS}
    assert by_id["silent"].unit == CM.UNIT_ASSERT_FUNCTION_LOCUS
    for aid in ("native-crash", "bare-exception", "timeout"):
        assert by_id[aid].unit == CM.UNIT_CORPUS_FILE
    assert by_id["R_construction_panics"].unit == CM.UNIT_CONSTRUCTION_PANIC
    # Silent is not comparable to native — different units.
    assert by_id["silent"].unit != by_id["native-crash"].unit


def test_measured_requires_unit() -> None:
    m = _measured(
        3,
        identity="native-crash",
        unit=CM.UNIT_CORPUS_FILE,
        population_id="pop:corpus",
        population_size=12,
        body=_body(3, 12),
        value_field_path="totals.failed",
        exit_code=1,
    )
    assert m.unit == CM.UNIT_CORPUS_FILE
    assert m.identity == "native-crash"
    assert not hasattr(m, "receipt_cid")
    with pytest.raises(CM.CommitMeasurementError, match="unit"):
        _measured(
            3,
            identity="native-crash",
            unit="made-up-unit",
            population_id="p",
            population_size=12,
            body=_body(3, 12),
            value_field_path="totals.failed",
            exit_code=1,
        )


def test_measured_json_carries_unit() -> None:
    m = _measured(
        0,
        identity="silent",
        unit=CM.UNIT_ASSERT_FUNCTION_LOCUS,
        population_id="p",
        population_size=10,
        body=_body(0, 10),
        value_field_path="totals.failed",
        exit_code=0,
    )
    # Partial with one other Unmeasured so we can serialize via vector
    v = CM.commit_measurement(
        "sha",
        "roster",
        {"silent": m, "R_construction_panics": CM.unmeasured("NoReport")},
    )
    payload = v.to_json()
    assert payload["axes"]["silent"]["unit"] == CM.UNIT_ASSERT_FUNCTION_LOCUS
    assert payload["axes"]["silent"]["value"] == 0


def test_empty_artifacts_partial_includes_panics_axis(tmp_path: Path) -> None:
    empty = tmp_path / "arts"
    empty.mkdir()
    v = CM.compose_tip_from_artifacts_dir("deadbeef", empty)
    assert isinstance(v, CM.PartialVector)
    assert "R_construction_panics" in v.unmeasured_axes()
    for aid in CM.CRITERION2_ENROLLED_IDENTITIES:
        assert aid in v.axes
        assert isinstance(v.axes[aid], CM.Unmeasured)
    path = tmp_path / "cm.json"
    path.write_text(json.dumps(v.to_json()), encoding="utf-8")
    assert GATE.main(["--composition", str(path), "--require-complete"]) == 1


def test_enrollment_unmeasured_body_is_not_measured(tmp_path: Path) -> None:
    """#7034: crash mint banks UNMEASURED — compose must not cite totals.failed."""
    body = {
        "schemaVersion": 1,
        "kind": "sole-construction-floor-axis-report",
        "axisId": "native-crash",
        "measurementClass": "python-sole-construction-floors",
        "measuredCommit": "deadbeef",
        "status": "unmeasured",
        "exitCode": 2,
        "identityResolved": True,
        "measured": False,
        "floorExitGreen": False,
        "unmeasuredReason": (
            "scan did not complete (exit=2); infrastructure/auth/init/crash "
            "— not a residual reading"
        ),
        "totals": {"failed": 1, "unmeasured": 1},
    }
    (tmp_path / "native" / "floor-axis-report.json").parent.mkdir()
    (tmp_path / "native" / "floor-axis-report.json").write_text(
        json.dumps(body), encoding="utf-8"
    )
    # silent completed green so vector is partial on native + panics etc.
    (tmp_path / "silent" / "floor-axis-report.json").parent.mkdir()
    (tmp_path / "silent" / "floor-axis-report.json").write_text(
        json.dumps(_floor_body("silent", failed=0)), encoding="utf-8"
    )
    v = CM.compose_tip_from_artifacts_dir("deadbeef", tmp_path)
    assert isinstance(v, CM.PartialVector)
    assert isinstance(v.axes["silent"], CM.Measured)
    assert v.axes["silent"].value == 0
    native = v.axes["native-crash"]
    assert isinstance(native, CM.Unmeasured)
    assert "scan did not complete" in native.reason
    assert "not a residual" in native.reason
    # Must not bank totals.failed=1 as Measured residual
    assert not isinstance(native, CM.Measured)


def test_no_total_while_any_axis_unmeasured() -> None:
    v = CM.commit_measurement(
        "sha",
        "roster",
        {
            "silent": _measured(
                0,
                identity="silent",
                unit=CM.UNIT_ASSERT_FUNCTION_LOCUS,
                population_id="p",
                population_size=1,
                body=_body(0, 1),
                value_field_path="totals.failed",
                exit_code=0,
            ),
            "native-crash": CM.unmeasured("NeverFired: tip floors queued"),
            "bare-exception": CM.unmeasured(
                "EnrollmentUnmeasured: scan did not complete"
            ),
            "timeout": CM.unmeasured("WorkerRefusal: supervised-enum"),
            "R_construction_panics": CM.unmeasured(
                "NoBoard: recensus board absent"
            ),
        },
    )
    assert isinstance(v, CM.PartialVector)
    with pytest.raises(AttributeError):
        _ = v.total  # type: ignore[attr-defined]
    payload = v.to_json()
    assert "total" not in payload
    reasons = {
        name: payload["axes"][name]["reason"]
        for name in payload["unmeasuredAxes"]
    }
    assert "NeverFired" in reasons["native-crash"]
    assert "EnrollmentUnmeasured" in reasons["bare-exception"]
    assert "WorkerRefusal" in reasons["timeout"]
    assert "NoBoard" in reasons["R_construction_panics"]
    # Four absences must not flatten to one identical string
    assert len(set(reasons.values())) == 4


def test_four_green_floors_without_panics_is_partial_not_complete(
    tmp_path: Path,
) -> None:
    """mr_blue: panics→typed-gap exit 0 on floors; board never ran ⇒ Unmeasured."""
    for aid in ("silent", "native-crash", "bare-exception", "timeout"):
        d = tmp_path / aid
        d.mkdir()
        (d / "floor-axis-report.json").write_text(
            json.dumps(_floor_body(aid, failed=0)), encoding="utf-8"
        )
    v = CM.compose_tip_from_artifacts_dir("deadbeef", tmp_path)
    assert isinstance(v, CM.PartialVector), (
        "four green floors must not be Complete without R_construction_panics"
    )
    assert "R_construction_panics" in v.unmeasured_axes()
    reason = v.axes["R_construction_panics"].reason  # type: ignore[union-attr]
    assert "control-effect recensus" in reason or "NoReport" in reason
    for aid in ("silent", "native-crash", "bare-exception", "timeout"):
        axis = v.axes[aid]
        assert isinstance(axis, CM.Measured)
        assert axis.value == 0
    # Units preserved on green floors
    assert v.axes["silent"].unit == CM.UNIT_ASSERT_FUNCTION_LOCUS  # type: ignore[union-attr]
    assert v.axes["native-crash"].unit == CM.UNIT_CORPUS_FILE  # type: ignore[union-attr]
    path = tmp_path / "cm.json"
    path.write_text(json.dumps(v.to_json()), encoding="utf-8")
    assert GATE.main(["--composition", str(path), "--require-complete"]) == 1


def test_all_criterion2_bodies_yield_complete(tmp_path: Path) -> None:
    for aid in ("silent", "native-crash", "bare-exception", "timeout"):
        d = tmp_path / aid
        d.mkdir()
        (d / "floor-axis-report.json").write_text(
            json.dumps(_floor_body(aid, failed=0)), encoding="utf-8"
        )
    (tmp_path / "recensus-board.json").write_text(
        json.dumps(_recensus_body(panics=0)), encoding="utf-8"
    )
    v = CM.compose_tip_from_artifacts_dir("deadbeef", tmp_path)
    assert isinstance(v, CM.CompleteVector)
    assert set(v.axes) == CM.CRITERION2_ENROLLED_IDENTITIES
    assert all(isinstance(r, CM.Measured) for r in v.axes.values())
    assert v.axes["R_construction_panics"].value == 0
    assert v.axes["R_construction_panics"].unit == CM.UNIT_CONSTRUCTION_PANIC
    # No scalar total across mixed units
    with pytest.raises(CM.CommitMeasurementError, match="no scalar total|units"):
        _ = v.total
    payload = v.to_json()
    assert payload["status"] == "complete"
    assert payload["total"] is None
    assert "assert-function-locus" in payload["valuesByUnit"]
    assert "corpus-file" in payload["valuesByUnit"]
    assert "construction-panic" in payload["valuesByUnit"]
    path = tmp_path / "cm.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert GATE.main(["--composition", str(path), "--require-complete"]) == 0


def test_floor_axis_reports_do_not_collapse_to_one_reading(tmp_path: Path) -> None:
    """Each axisId is its own Measured; first-match campaign collapse is gone."""
    (tmp_path / "silent.json").write_text(
        json.dumps(_floor_body("silent", failed=0)), encoding="utf-8"
    )
    (tmp_path / "native.json").write_text(
        json.dumps(_floor_body("native-crash", failed=1)), encoding="utf-8"
    )
    (tmp_path / "bare.json").write_text(
        json.dumps(_floor_body("bare-exception", failed=1)), encoding="utf-8"
    )
    (tmp_path / "timeout.json").write_text(
        json.dumps(_floor_body("timeout", failed=1)), encoding="utf-8"
    )
    v = CM.compose_tip_from_artifacts_dir("deadbeef", tmp_path)
    assert isinstance(v, CM.PartialVector)
    assert isinstance(v.axes["silent"], CM.Measured)
    assert v.axes["silent"].value == 0
    assert isinstance(v.axes["native-crash"], CM.Measured)
    assert v.axes["native-crash"].value == 1
    assert isinstance(v.axes["bare-exception"], CM.Measured)
    assert v.axes["bare-exception"].value == 1
    assert isinstance(v.axes["timeout"], CM.Measured)
    assert v.axes["timeout"].value == 1


def test_enrolled_panics_axis_not_forbidden() -> None:
    """R_construction_panics is cite-enrolled; free R_construction still blocked."""
    body = _recensus_body(2)
    m = _measured(
        2,
        identity="R_construction_panics",
        unit=CM.UNIT_CONSTRUCTION_PANIC,
        population_id="board",
        population_size=1415,
        body=body,
        value_field_path="R_construction_panics",
        exit_code=1,
    )
    v = CM.commit_measurement(
        "sha",
        "roster",
        {
            "R_construction_panics": m,
            "silent": CM.unmeasured("x"),
        },
    )
    assert isinstance(v, CM.PartialVector)
    with pytest.raises(CM.CommitMeasurementError, match="corpus-board residual|SCOREBOARD"):
        CM.commit_measurement(
            "sha",
            "roster",
            {
                "R_construction": CM.unmeasured("invented"),
            },
        )


def test_legacy_recensus_body_without_conservation_witness_is_refused() -> None:
    body = _recensus_body(2)
    body.pop("conservationWitness")
    with pytest.raises(CM.CommitMeasurementError, match="conservationWitness"):
        _measured(
            2,
            identity="R_construction_panics",
            unit=CM.UNIT_CONSTRUCTION_PANIC,
            population_id="board",
            population_size=1415,
            body=body,
            value_field_path="R_construction_panics",
            exit_code=1,
        )


def test_measured_requires_body_matching_value() -> None:
    with pytest.raises(CM.CommitMeasurementError, match="parsed body|NoReport"):
        _measured(
            3,
            identity="x",
            unit=CM.UNIT_CORPUS_FILE,
            population_id="p",
            population_size=1,
            body=None,  # type: ignore[arg-type]
            value_field_path="totals.failed",
            exit_code=1,
        )
    with pytest.raises(CM.CommitMeasurementError, match="does not match"):
        _measured(
            99,
            identity="x",
            unit=CM.UNIT_CORPUS_FILE,
            population_id="p",
            population_size=12,
            body=_body(3, 12),
            value_field_path="totals.failed",
            exit_code=1,
        )


def test_partial_has_no_total() -> None:
    partial = CM.commit_measurement(
        "sha",
        "roster",
        {
            "a": _measured(
                1,
                identity="a",
                unit=CM.UNIT_CORPUS_FILE,
                population_id="p",
                population_size=2,
                body=_body(1, 2),
                value_field_path="totals.failed",
                exit_code=1,
            ),
            "b": CM.unmeasured("NoReport"),
        },
    )
    assert isinstance(partial, CM.PartialVector)
    with pytest.raises(AttributeError):
        _ = partial.total  # type: ignore[attr-defined]


def test_smoke_body_with_forbidden_product_key_does_not_measure_panics(tmp_path):
    """Smoke seal carrying R_construction_panics must not Measure panics.

    _is_candidate_body already refuses smoke class/kind. _body_matches_spec must
    also refuse before match_field short-circuit so a stripped/malformed smoke
    body that still has the board field cannot compose as Measured.
    """
    smoke = {
        "schemaVersion": 1,
        "kind": "recensus-path-smoke-verdict",
        "measurementClass": "recensus-path-smoke",
        "pathVerdict": "PATH_OK",
        # Forbidden product key — if present, still must not Measure panics.
        "R_construction_panics": 0,
        "measuredCommit": "deadbeef",
    }
    # Four green floors so only panics would complete the vector.
    for axis in ("silent", "native-crash", "bare-exception", "timeout"):
        (tmp_path / f"floor-{axis}.json").write_text(
            json.dumps(_floor_body(axis, failed=0)), encoding="utf-8"
        )
    # Spoof path carries PATH_HINTS fragment for attendance class of bug.
    spoof_dir = tmp_path / "pandas-control-effect"
    spoof_dir.mkdir()
    (spoof_dir / "smoke.json").write_text(json.dumps(smoke), encoding="utf-8")

    panics_spec = next(
        s for s in CM.TIP_AXIS_SPECS if s.identity == "R_construction_panics"
    )
    assert CM._body_matches_spec(smoke, panics_spec) is False
    assert CM._is_candidate_body(smoke) is False

    v = CM.compose_tip_from_artifacts_dir("deadbeef", tmp_path)
    assert "R_construction_panics" in v.unmeasured_axes(), (
        f"smoke with product key Measured panics: {v.axes!r}"
    )
    reading = v.axes["R_construction_panics"]
    assert not isinstance(reading, CM.Measured), reading
