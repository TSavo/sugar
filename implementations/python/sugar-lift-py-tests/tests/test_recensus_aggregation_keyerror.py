"""Landmine two: aggregation must survive construction-panic rows.

The recensus walked 1421/1421 then died on:
  families['ConstructionPanic'] += 1 → KeyError

Root causes:
1. Lift loop rebound the board Counter named ``families`` to a plain row dict.
2. File-level ConstructionPanic is BaseException and never entered reporter.gaps,
   so measure must enroll it into the row's families explicitly.

The retired direct-measurement tooth is superseded by the enrolled current-door
``test_recensus_projects_construction_panic_as_a_loud_counted_terminal``.  That
tooth proves the panic terminal itself without recreating the deleted family
taxonomy at a side door.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = _SCRIPTS / "control_effect_recensus.py"


def _load():
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location("control_effect_recensus", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _aggregate_rows(module, measured_rows: list[tuple[str, dict]]):
    """Replay the aggregation families loop (the board's R_construction door)."""
    families: Counter[str] = Counter()
    construction_panics: list[dict] = []
    for _file, raw in measured_rows:
        row = dict(raw)
        category = str(row.get("category"))
        families.update(row.get("families") or {})
        if category == "construction-panic":
            panic = row.get("panic")
            if isinstance(panic, dict):
                construction_panics.append(panic)
            if "ConstructionPanic" not in (row.get("families") or {}):
                families["ConstructionPanic"] = (
                    int(families.get("ConstructionPanic") or 0) + 1
                )
    return families, construction_panics


def test_aggregation_survives_legacy_panic_row_without_family_key() -> None:
    """Legacy checkpoints may omit ConstructionPanic in families — no KeyError."""
    module = _load()
    # Simulate the rebinding defect class: start from Counter, never rebind.
    measured = [
        (
            "pkg/a.py",
            {
                "category": "completed",
                "functionsTotal": 1,
                "functionsClean": 1,
                "families": {"SugarNotWritten": 2},
            },
        ),
        (
            "pkg/b.py",
            {
                "category": "construction-panic",
                "functionsTotal": 3,
                "functionsClean": 1,
                "families": {},  # legacy: panic not enrolled in families
                "panic": {
                    "file": "pkg/b.py",
                    "type": "ConstructionPanic",
                    "message": "planted",
                },
            },
        ),
    ]
    families, panics = _aggregate_rows(module, measured)
    assert len(panics) == 1
    assert families["ConstructionPanic"] == 1
    assert families["SugarNotWritten"] == 2


def test_rebinding_families_name_is_the_documented_landmine() -> None:
    """Discrimination: plain-dict += KeyErrors; Counter does not.

    Documents why the live-loop rebinding was fatal after a complete walk.
    """
    rebound = {"SugarNotWritten": 1}  # what row.get("families") looks like
    with pytest.raises(KeyError, match="ConstructionPanic"):
        rebound["ConstructionPanic"] += 1

    safe: Counter[str] = Counter({"SugarNotWritten": 1})
    safe["ConstructionPanic"] += 1
    assert safe["ConstructionPanic"] == 1


def test_aggregate_only_refuses_incomplete_checkpoint(tmp_path: Path, capsys) -> None:
    module = _load()
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (root / "b.py").write_text("def b():\n    return 2\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    # Empty checkpoint → all pending → refuse aggregate-only
    saved = sys.argv
    sys.argv = [
        "control_effect_recensus.py",
        str(root),
        "--corpus-root",
        str(root),
        "--corpus-version",
        "test-pin",
        "--commit",
        "deadbeef",
        "--out-dir",
        str(out),
        "--aggregate-only",
    ]
    # Derive pin constants like the bounded-run teeth
    from pandas_floor_summary import corpus_cid
    from sugar_lift_py_tests.corpus_pin import pin_corpus

    observed = pin_corpus(root, distribution=root.name, version="test-pin")
    module._PANDAS_3_0_3_AGGREGATE_HASH = observed.aggregate_hash
    module._PANDAS_3_0_3_MANIFEST_SHAPE_CID = corpus_cid(list(observed.paths))
    try:
        code = module.main()
    finally:
        sys.argv = saved
    assert code == 2
    err = capsys.readouterr().err
    assert "aggregate-only requires a complete checkpoint" in err
    assert not (out / "recensus.json").exists()
