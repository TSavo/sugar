from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_static_residual_is_witnessed_and_consumer_accepted(tmp_path: Path) -> None:
    mint = _load("static_floor_residual_report", ROOT / "tools/static_floor_residual_report.py")
    body, code = mint.mint_static_residual(
        input_axes=["a", "b"], green_axes=["a"], red_axes=["b"]
    )
    assert code == 0
    assert body["measurement"] == "measured"
    assert body["residualCount"] == 1
    assert body["conservationWitness"]["status"] == "passed"
    path = tmp_path / "floor-static-residual.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    enrollment = _load(
        "static_floor_enrollment_reader",
        ROOT / "tools/sole_construction_floor_enrollment.py",
    )
    reading = enrollment.load_floor_measurement_from_summary(
        path, residual_key="R_static_sole_construction"
    )
    assert reading.residual_count == 1
    assert reading.conservation_witness is not None


def test_static_partition_failure_emits_no_magnitude() -> None:
    mint = _load(
        "static_floor_residual_report_failure",
        ROOT / "tools/static_floor_residual_report.py",
    )
    body, code = mint.mint_static_residual(
        input_axes=["a", "b"], green_axes=["a"], red_axes=[]
    )
    assert code == 1
    assert body["measurement"] == "unmeasured"
    assert body["residualCount"] is None
    assert "conservationFailure" in body
    assert "totals" not in body
