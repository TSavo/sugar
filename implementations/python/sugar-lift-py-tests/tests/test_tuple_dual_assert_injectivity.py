"""Tuple dual-assert injectivity — component lie refutes on shared euf key.

Probe (pre-fix): `df.shape == (0,0)` and `df.shape == (1,1)` shared the
shape#euf key but structural consistency only treated primitive consts as
values, so the dual stayed sat under z3 (tuple injectivity gap).

Fix (sugar-verifier): ground data constructors (`tuple(…)`, nested) count as
structural values; distinct JCS keys of tuple(0,0) vs tuple(1,1) fire
`equals both` pre-SMT. No fabricated shape value; discrimination is still
dual-assert over the shared coordinate.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_SHAPE_DUAL = (
    "import pandas as pd\n"
    "def t_true():\n"
    "    assert pd.DataFrame().shape == (0, 0)\n"
    "def t_lie():\n"
    "    assert pd.DataFrame().shape == (1, 1)\n"
)

_SHAPE_EUF = "shape#euf#c:call:shape(c:call:pandas.DataFrame())::assertion"

_EMPTY_DUAL = (
    "import pandas as pd\n"
    "def t_true():\n"
    "    assert pd.DataFrame().empty == True\n"
    "def t_lie():\n"
    "    assert pd.DataFrame().empty == False\n"
)


def test_shape_dual_shares_euf_key_with_distinct_tuple_rhs() -> None:
    report = build_literal_call_report(
        source=_SHAPE_DUAL,
        filename="t.py",
        memento_file="t.py",
    )
    assert report is not None
    names = [row.name for row in report.payload.ir if "#euf#" in (row.name or "")]
    assert names == [_SHAPE_EUF, _SHAPE_EUF]
    # RHS first components differ: 0 vs 1 (tuple injectivity material).
    first_components = [
        row.inv["args"][1]["args"][0]["value"] for row in report.payload.ir
    ]
    assert sorted(first_components) == [0, 1]


def test_shape_dual_assert_refutes_tuple_component_lie(tmp_path: Path) -> None:
    """Core DoD: shared shape euf + distinct ground tuples → unsat structural."""
    result = run_source_through_real_solver(tmp_path / "shape-dual", _SHAPE_DUAL)
    assert result.verdict == "unsat", (
        result.verdict,
        [row.get("status") for row in result.prove_doc.get("rows", [])],
        [row.get("reason") for row in result.prove_doc.get("rows", [])],
    )
    reason = result.prove_doc.get("rows", [{}])[0].get("reason", "")
    assert "contradictory" in reason
    assert "structural" in reason
    assert "equals both" in reason


def test_empty_dual_still_refutes(tmp_path: Path) -> None:
    """Regression: primitive bool dual-assert still structural-unsat."""
    result = run_source_through_real_solver(tmp_path / "empty-dual", _EMPTY_DUAL)
    assert result.verdict == "unsat"
    reason = result.prove_doc.get("rows", [{}])[0].get("reason", "")
    assert "structural" in reason
