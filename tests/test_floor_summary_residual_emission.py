"""Emission: failed floor conservation must stay explicitly UNMEASURED."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
SCRIPTS = ROOT / "implementations/python/sugar-lift-py-tests/scripts"


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
