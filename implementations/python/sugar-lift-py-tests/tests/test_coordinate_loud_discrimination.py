"""Loud discrimination bad-twins for the vendor-op coordinate lane.

Handoff B (2026-07-09 rev 3): coordinates work, but discrimination must be
pinned with teeth — dual-assert witness (or structural unsat) when a lie shares
the same #euf# key as a truth.

Three surfaces (same discipline as #3977 / #3982):

1. **Lying kwarg** — ``.sum(axis=0)`` true vs wrong value; kw is in the euf key.
2. **Lying chain** — ``.dropna().mean()`` true vs wrong; nested call: coords.
3. **Method vs attribute** — ``.sum()`` method and ``.empty`` attribute both
   refute lies; kw-less ``.sum()`` and ``.sum(axis=0)`` must not share one key.

No speculative production change — measure that current membrane already
discriminates; pin so regression is red.
"""

from __future__ import annotations

import re
from pathlib import Path

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_LYING_KWARG = (
    "import pandas as pd\n"
    "def t_true():\n"
    "    assert pd.Series([1.0, 2.0, 3.0]).sum(axis=0) == 6.0\n"
    "def t_lie():\n"
    "    assert pd.Series([1.0, 2.0, 3.0]).sum(axis=0) == 0.0\n"
)

_LYING_CHAIN = (
    "import pandas as pd\n"
    "def t_true():\n"
    "    assert pd.Series([1.0, None, 3.0]).dropna().mean() == 2.0\n"
    "def t_lie():\n"
    "    assert pd.Series([1.0, None, 3.0]).dropna().mean() == 0.0\n"
)

_METHOD_LIE = (
    "import pandas as pd\n"
    "def t_true():\n"
    "    assert pd.Series([1.0, 2.0, 3.0]).sum() == 6.0\n"
    "def t_lie():\n"
    "    assert pd.Series([1.0, 2.0, 3.0]).sum() == 0.0\n"
)

_ATTR_LIE = (
    "import pandas as pd\n"
    "def t_true():\n"
    "    assert pd.DataFrame().empty == True\n"
    "def t_lie():\n"
    "    assert pd.DataFrame().empty == False\n"
)

_SUM_KW_VS_NO_KW = (
    "import pandas as pd\n"
    "def t_no_kw():\n"
    "    assert pd.Series([1.0, 2.0, 3.0]).sum() == 6.0\n"
    "def t_kw():\n"
    "    assert pd.Series([1.0, 2.0, 3.0]).sum(axis=0) == 6.0\n"
)


def _euf_names(report) -> list[str]:
    return [row.name or "" for row in report.payload.ir if "#euf#" in (row.name or "")]


def _coords(report) -> set[str]:
    return set(re.findall(r"call:[A-Za-z_][A-Za-z0-9_.]*|kw:[A-Za-z_][A-Za-z0-9_]*", repr(report.payload.ir)))


# ---------------------------------------------------------------------------
# 1. Lying kwarg
# ---------------------------------------------------------------------------


def test_lying_kwarg_shares_euf_key_with_kw_axis_in_locator() -> None:
    report = build_literal_call_report(
        source=_LYING_KWARG, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    names = _euf_names(report)
    assert len(names) == 2
    assert names[0] == names[1]
    assert "call:sum" in names[0] and "kw:axis" in names[0]
    assert {"call:sum", "kw:axis", "call:pandas.Series"} <= _coords(report)


def test_lying_kwarg_dual_assert_refutes_via_witness(tmp_path: Path) -> None:
    result = run_source_through_real_solver(tmp_path / "lying-kwarg", _LYING_KWARG)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses
    reason = (result.prove_doc.get("rows") or [{}])[0].get("reason", "")
    assert "contradictory" in reason or "unsatisfied" in statuses


# ---------------------------------------------------------------------------
# 2. Lying chain
# ---------------------------------------------------------------------------


def test_lying_chain_emits_nested_mean_dropna_coordinates() -> None:
    report = build_literal_call_report(
        source=_LYING_CHAIN, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    names = _euf_names(report)
    assert len(names) == 2 and names[0] == names[1]
    assert "call:mean" in names[0] and "call:dropna" in names[0]
    assert {"call:mean", "call:dropna", "call:pandas.Series"} <= _coords(report)


def test_lying_chain_dual_assert_refutes_via_witness(tmp_path: Path) -> None:
    result = run_source_through_real_solver(tmp_path / "lying-chain", _LYING_CHAIN)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


# ---------------------------------------------------------------------------
# 3. Method vs attribute (+ kw identity of method)
# ---------------------------------------------------------------------------


def test_method_sum_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """Method surface: call:sum without kw."""
    report = build_literal_call_report(
        source=_METHOD_LIE, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    name = _euf_names(report)[0]
    assert "call:sum" in name
    assert "kw:axis" not in name

    result = run_source_through_real_solver(tmp_path / "method-sum", _METHOD_LIE)
    assert result.verdict == "unsat", (
        result.verdict,
        [row.get("status") for row in result.prove_doc.get("rows", [])],
    )


def test_attribute_empty_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """Attribute surface: call:empty — different locator family than call:sum."""
    report = build_literal_call_report(
        source=_ATTR_LIE, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    name = _euf_names(report)[0]
    assert "call:empty" in name
    assert "call:sum" not in name

    result = run_source_through_real_solver(tmp_path / "attr-empty", _ATTR_LIE)
    assert result.verdict == "unsat", (
        result.verdict,
        [row.get("status") for row in result.prove_doc.get("rows", [])],
    )


def test_method_sum_with_and_without_kw_are_distinct_euf_keys() -> None:
    """Confusion guard: axis kw is part of identity — not interchangeable with bare sum."""
    report = build_literal_call_report(
        source=_SUM_KW_VS_NO_KW, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    names = _euf_names(report)
    assert len(names) == 2
    assert names[0] != names[1], names
    bare, with_kw = sorted(names, key=len)
    assert "kw:axis" not in bare
    assert "kw:axis" in with_kw
