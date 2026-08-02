"""Emission: failed floor conservation must stay explicitly UNMEASURED."""

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


def test_conservation_failure_emits_unmeasured_without_residual_mass(
    tmp_path: Path,
) -> None:
    pfs = _load("pandas_floor_summary", SCRIPTS / "pandas_floor_summary.py")
    out = tmp_path / "floor-summary.json"
    # rows missing a file → conservation fails
    mode = pfs.write_floor_summary_or_unmeasured(
        out,
        floor="native-crash",
        residual_key="R_native_crashes",
        residual_count=47,
        files=["a.py", "b.py"],
        rows=[{"file": "a.py", "category": "native-crash"}],
        totals={"R_native_crashes": 47},
        measured=True,
    )
    assert mode == "unmeasured"
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["kind"] == "floor-unmeasured-v1"
    assert body["measurement"] == "unmeasured"
    assert body["residualKey"] == "R_native_crashes"
    assert body["residualCount"] is None
    assert "totals" not in body
    [reason] = body["unmeasurableReasons"]
    assert "floor rows must account for every corpus file exactly once" in reason
    assert "expectedRows=2 observedRows=1" in reason
    assert "missing=1 extra=0 duplicateKeys=0" in reason
    assert "missingSample=['b.py']" in reason

    enr = _load(
        "sole_construction_floor_enrollment",
        TOOLS / "sole_construction_floor_enrollment.py",
    )
    reading = enr.load_floor_measurement_from_summary(
        out, residual_key="R_native_crashes"
    )
    assert reading.residual_count is None
    assert reading.unmeasured_reason.startswith(
        "floor summary conservation failed: ValueError: floor rows must account "
        "for every corpus file exactly once"
    )
    assert "expectedRows=2 observedRows=1" in reading.unmeasured_reason


def test_legacy_fallback_residual_is_rejected_not_resealed(tmp_path: Path) -> None:
    """#7051 fallback bodies carried unverified mass; readers fail them closed."""
    out = tmp_path / "floor-summary.json"
    out.write_text(
        json.dumps(
            {
                "kind": "floor-residual-v1",
                "floor": "native-crash",
                "residualKey": "R_native_crashes",
                "residualCount": 47,
                "emissionFallback": (
                    "ValueError: floor rows must account for every corpus file "
                    "exactly once"
                ),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    enr = _load(
        "sole_construction_floor_enrollment_legacy_refusal",
        TOOLS / "sole_construction_floor_enrollment.py",
    )
    reading = enr.load_floor_measurement_from_summary(
        out, residual_key="R_native_crashes"
    )
    assert reading.residual_count is None
    assert "unconserved #7051 fallback" in reading.unmeasured_reason


def test_full_summary_when_conservation_holds(tmp_path: Path) -> None:
    pfs = _load("pandas_floor_summary", SCRIPTS / "pandas_floor_summary.py")
    out = tmp_path / "floor-summary.json"
    mode = pfs.write_floor_summary_or_unmeasured(
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
    witness = body["conservationWitness"]
    assert witness["witnessSchema"] == "sugar.conservation-witness.v1"
    assert witness["status"] == "passed"
    assert witness["validatorStageId"] == (
        "pandas-floor-summary.rows-account-for-corpus/v1"
    )
    assert witness["inputKeyManifestCid"] == witness["outputKeyManifestCid"]
    assert witness["inputKeyCount"] == witness["outputKeyCount"] == 2


def test_measured_floor_body_without_conservation_witness_is_unmeasured(
    tmp_path: Path,
) -> None:
    pfs = _load("pandas_floor_summary_missing_witness", SCRIPTS / "pandas_floor_summary.py")
    out = tmp_path / "floor-summary.json"
    body = pfs.floor_summary(
        floor="timeout",
        files=["a.py"],
        rows=[{"file": "a.py", "category": "completed"}],
        totals={"R_timeouts": 0},
        measured=True,
    )
    body.pop("conservationWitness")
    out.write_text(json.dumps(body) + "\n", encoding="utf-8")
    enr = _load(
        "sole_construction_floor_enrollment_missing_witness",
        TOOLS / "sole_construction_floor_enrollment.py",
    )
    reading = enr.load_floor_measurement_from_summary(
        out, residual_key="R_timeouts"
    )
    assert reading.residual_count is None
    assert "lacks conservationWitness" in reading.unmeasured_reason
