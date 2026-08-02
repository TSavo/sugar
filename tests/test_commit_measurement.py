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

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


CM = _load("commit_measurement", "tools/commit_measurement.py")
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
    }


def _recensus_body(panics: int = 0, files: int = 1415) -> dict:
    return {
        "schemaVersion": 1,
        "measurementClass": "control-effect-recensus",
        "measuredCommit": "deadbeef",
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
    m = CM.measured(
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
        CM.measured(
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
    m = CM.measured(
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
    m = CM.measured(
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


def test_measured_requires_body_matching_value() -> None:
    with pytest.raises(CM.CommitMeasurementError, match="parsed body|NoReport"):
        CM.measured(
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
        CM.measured(
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
            "a": CM.measured(
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
