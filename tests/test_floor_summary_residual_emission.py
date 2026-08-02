"""Emission: residual mass must land even when full floor_summary conservation fails."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "implementations/python/sugar-lift-py-tests/scripts"
TOOLS = ROOT / "tools"


def _load(name: str, path: Path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_conservation_failure_still_emits_residual_v1(tmp_path: Path) -> None:
    pfs = _load("pandas_floor_summary", SCRIPTS / "pandas_floor_summary.py")
    out = tmp_path / "floor-summary.json"
    # rows missing a file → conservation fails
    mode = pfs.write_floor_summary_or_residual(
        out,
        floor="native-crash",
        residual_key="R_native_crashes",
        residual_count=47,
        files=["a.py", "b.py"],
        rows=[{"file": "a.py", "category": "native-crash"}],
        totals={"R_native_crashes": 47},
        measured=True,
    )
    assert mode == "residual-only"
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["kind"] == "floor-residual-v1"
    assert body["residualKey"] == "R_native_crashes"
    assert body["residualCount"] == 47
    assert "emissionFallback" in body

    enr = _load(
        "sole_construction_floor_enrollment",
        TOOLS / "sole_construction_floor_enrollment.py",
    )
    assert (
        enr.load_residual_count_from_floor_summary(
            out, residual_key="R_native_crashes"
        )
        == 47
    )


def test_full_summary_when_conservation_holds(tmp_path: Path) -> None:
    pfs = _load("pandas_floor_summary", SCRIPTS / "pandas_floor_summary.py")
    out = tmp_path / "floor-summary.json"
    mode = pfs.write_floor_summary_or_residual(
        out,
        floor="timeout",
        residual_key="R_timeouts",
        residual_count=2,
        files=["a.py", "b.py"],
        rows=[
            {"file": "a.py", "category": "timeout"},
            {"file": "b.py", "category": "completed"},
        ],
        totals={"R_timeouts": 2, "completed": 1},
        measured=True,
    )
    assert mode == "full"
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["kind"] == "pandas-floor-summary-v1"
    assert body["totals"]["R_timeouts"] == 2
