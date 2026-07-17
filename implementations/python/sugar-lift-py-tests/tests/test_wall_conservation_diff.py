"""#4263 wall conservation vector + unexplained-movement instrument."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[4]
_DIFF_TOOL = _ROOT / "tools" / "wall_conservation_diff.py"
_TEL_TOOL = _ROOT / "tools" / "wall_frontier_telemetry.py"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_DIFF = _load(_DIFF_TOOL)
_TEL = _load(_TEL_TOOL)


def _frontier(
    *,
    status: str = "failed",
    files: int = 2,
    leaves: int = 4,
    panics: list | None = None,
    suppressed: list | None = None,
    effects: list | None = None,
) -> dict:
    if panics is None:
        panics = [
            {
                "kind": "FactoryPanic",
                "status": "mandatory-panic",
                "locus": "a.py:1:0",
                "demandedSource": "definition:a",
                "demandedBody": {"path": "a.py", "line": 1},
            },
            {
                "kind": "FactoryPanic",
                "status": "mandatory-panic",
                "locus": "b.py:1:0",
                "demandedSource": "definition:b",
                "demandedBody": {"path": "b.py", "line": 1},
            },
        ]
    return {
        "kind": "recovered-construction-audit",
        "recoveryOverride": True,
        "status": status,
        "census": {
            "kind": "recovered-frontier-census",
            "sourceFilesEnumerated": files,
            "sourceBodiesDemanded": files,
            "auditLeavesCompleted": leaves,
        },
        "panics": panics,
        "suppressedDescendants": suppressed if suppressed is not None else [{}],
        "effects": effects if effects is not None else [{}, {}, {}],
    }


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_vector_carries_all_five_buckets(tmp_path: Path) -> None:
    path = _write(tmp_path / "frontier.json", _frontier())
    vector = _DIFF.conservation_vector(path)
    assert vector["mandatory_panics"] == 2
    assert vector["suppressed_descendants"] == 1
    assert vector["typed_effects"] == 3
    assert vector["silent"] == 0
    # 4 leaves, 2 distinct panicked bodies → 2 constructed.
    assert vector["constructed"] == 2
    assert vector["audit_leaves_completed"] == 4


def test_summary_cross_check_and_silent_floor(tmp_path: Path) -> None:
    frontier = _write(tmp_path / "frontier.json", _frontier())
    summary = _write(
        tmp_path / "summary.json",
        {
            "mode": "frontier",
            "frontier": {
                "independentPanicCount": 2,
                "suppressedDescendantCount": 1,
                "effectCount": 3,
            },
            "gapsByBucket": {"Conservation": 2},
        },
    )
    vector = _DIFF.conservation_vector(frontier, summary)
    assert vector["silent"] == 2

    bad = _write(
        tmp_path / "bad-summary.json",
        {
            "frontier": {
                "independentPanicCount": 99,
                "suppressedDescendantCount": 1,
                "effectCount": 3,
            }
        },
    )
    with pytest.raises(ValueError, match="summary/frontier mismatch"):
        _DIFF.conservation_vector(frontier, bad)


def test_suppression_shift_is_unexplained_without_ownership(tmp_path: Path) -> None:
    before = _write(
        tmp_path / "before.json",
        _frontier(
            panics=[
                {
                    "locus": "a.py:1:0",
                    "demandedSource": "definition:a",
                    "demandedBody": {"path": "a.py"},
                },
                {
                    "locus": "b.py:1:0",
                    "demandedSource": "definition:b",
                    "demandedBody": {"path": "b.py"},
                },
            ],
            suppressed=[{}, {}],
            effects=[],
            leaves=4,
        ),
    )
    # Panic drop, suppressed rise: classic false progress.
    after = _write(
        tmp_path / "after.json",
        _frontier(
            panics=[
                {
                    "locus": "a.py:1:0",
                    "demandedSource": "definition:a",
                    "demandedBody": {"path": "a.py"},
                }
            ],
            suppressed=[{}, {}, {}, {}, {}],
            effects=[],
            leaves=4,
        ),
    )
    b = _DIFF.conservation_vector(before)
    a = _DIFF.conservation_vector(after)
    findings = _DIFF.detect_unexplained(b, a, explanations={})
    assert any("suppression shift" in f for f in findings)

    owned = _DIFF.detect_unexplained(
        b,
        a,
        explanations={
            "mandatory_panics": "retired CallSugar import-alias panics via exact resolve",
            "suppressed_descendants": "descendant inventory under remaining parent grew",
        },
    )
    assert not any("suppression shift" in f for f in owned)


def test_real_construction_panic_drop_is_clean(tmp_path: Path) -> None:
    before = _write(
        tmp_path / "before.json",
        _frontier(
            panics=[
                {
                    "locus": "a.py:1:0",
                    "demandedSource": "definition:a",
                    "demandedBody": {"path": "a.py"},
                },
                {
                    "locus": "b.py:1:0",
                    "demandedSource": "definition:b",
                    "demandedBody": {"path": "b.py"},
                },
            ],
            suppressed=[{}, {}],
            effects=[],
            leaves=4,
        ),
    )
    after = _write(
        tmp_path / "after.json",
        _frontier(
            panics=[
                {
                    "locus": "a.py:1:0",
                    "demandedSource": "definition:a",
                    "demandedBody": {"path": "a.py"},
                }
            ],
            suppressed=[{}],
            effects=[],
            leaves=4,
        ),
    )
    findings = _DIFF.detect_unexplained(
        _DIFF.conservation_vector(before),
        _DIFF.conservation_vector(after),
        explanations={
            "mandatory_panics": "StatementFunctionDefSugar binds remaining defs",
            "suppressed_descendants": "child inventory under fixed parents fell",
            "constructed": "one more leaf completes clean",
        },
    )
    assert findings == []


def test_discovery_narrowing_is_loud(tmp_path: Path) -> None:
    before = _write(tmp_path / "before.json", _frontier(files=10, leaves=10))
    after = _write(
        tmp_path / "after.json",
        _frontier(
            files=2,
            leaves=2,
            panics=[
                {
                    "locus": "a.py:1:0",
                    "demandedSource": "definition:a",
                    "demandedBody": {"path": "a.py"},
                }
            ],
            suppressed=[],
            effects=[],
        ),
    )
    findings = _DIFF.detect_unexplained(
        _DIFF.conservation_vector(before),
        _DIFF.conservation_vector(after),
        explanations={},
    )
    assert any("discovery narrowing" in f for f in findings)


def test_cli_advisory_exits_zero_with_findings(tmp_path: Path) -> None:
    before = _write(tmp_path / "before.json", _frontier())
    after = _write(
        tmp_path / "after.json",
        _frontier(
            panics=[
                {
                    "locus": "a.py:1:0",
                    "demandedSource": "definition:a",
                    "demandedBody": {"path": "a.py"},
                }
            ],
            suppressed=[{}, {}, {}, {}],
            effects=[],
        ),
    )
    rc = _DIFF.main(
        [
            "--before-frontier",
            str(before),
            "--after-frontier",
            str(after),
            "--wall",
            "pandas",
            "--advisory",
            "--json-out",
            str(tmp_path / "delta.json"),
        ]
    )
    assert rc == 0
    payload = json.loads((tmp_path / "delta.json").read_text(encoding="utf-8"))
    assert payload["unexplained_count"] > 0
    assert payload["schema"] == _DIFF.SCHEMA


def test_cli_ratchet_exits_one_on_unexplained(tmp_path: Path) -> None:
    before = _write(tmp_path / "before.json", _frontier())
    after = _write(
        tmp_path / "after.json",
        _frontier(
            panics=[
                {
                    "locus": "a.py:1:0",
                    "demandedSource": "definition:a",
                    "demandedBody": {"path": "a.py"},
                }
            ],
            suppressed=[{}, {}, {}, {}],
            effects=[],
        ),
    )
    rc = _DIFF.main(
        [
            "--before-frontier",
            str(before),
            "--after-frontier",
            str(after),
            "--wall",
            "pandas",
        ]
    )
    assert rc == 1


def test_telemetry_markdown_embeds_machine_vector(tmp_path: Path) -> None:
    path = _write(tmp_path / "frontier.json", _frontier())
    vector = _TEL.conservation_vector(path)
    body = _TEL.conservation_markdown("pandas", "https://run/1", vector)
    assert "mandatory_panics: 2" in body
    assert "silent: 0" in body
    parsed = _TEL.parse_ledger_vector(body, "pandas")
    assert parsed == vector
    assert _TEL.parse_ledger_vector(body, "numpy") is None
    # Legacy three-lane tuple still renders for dual-read callers.
    legacy = _TEL.markdown("pandas", "https://run/1", (2, 1, 3))
    assert "independent: 2" in legacy


def test_legacy_frontier_vector_tuple(tmp_path: Path) -> None:
    path = _write(tmp_path / "frontier.json", _frontier())
    assert _TEL.frontier_vector(path) == (2, 1, 3)
