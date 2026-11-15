from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_static_residual_is_witnessed() -> None:
    mint = _load("static_floor_residual_report", ROOT / "tools/static_floor_residual_report.py")
    body, code = mint.mint_static_residual(
        input_axes=["a", "b"], green_axes=["a"], red_axes=["b"]
    )
    assert code == 0
    assert body["measurement"] == "measured"
    assert body["residualCount"] == 1
    assert body["conservationWitness"]["status"] == "passed"


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
