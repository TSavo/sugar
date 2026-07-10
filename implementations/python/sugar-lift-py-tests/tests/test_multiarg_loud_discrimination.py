"""Multi-arg loud discrimination bad-twins for vendor methods.

Handoff E (2026-07-09 rev 4): surfaces #3986 did not cover — multi-arg vendor
methods where a positional *other* / multi-kw payload is part of the euf key.

Three surfaces (same dual-assert discipline as #3982 / #3986):

1. **Lying merge (pos + kw)** — ``df.merge(other, on=...)`` true vs wrong shape;
   positional other and ``kw:on`` both live in the shared #euf# key.
2. **Lying pivot_table (multi-kw)** — ``.pivot_table(values=..., index=...,
   aggfunc=...)`` true vs wrong; multi-kw identity pinned loud.
3. **Arg-identity guards** — distinct euf keys when:
   - ``on=`` alone vs ``on=`` + ``how=``
   - different positional *other* frames
   - pivot with vs without ``aggfunc``
   - bare positional merge (no kw) dual-assert still refutes

No speculative production change — measure that current membrane already
discriminates multi-arg call: coordinates; pin so regression is red.
"""

from __future__ import annotations

import re
from pathlib import Path

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

# ---------------------------------------------------------------------------
# Fixtures — inline constructors (match #3986 style; no free-name temporals)
# ---------------------------------------------------------------------------

_MERGE_POS_KW = (
    "import pandas as pd\n"
    "def t_true():\n"
    '    assert pd.DataFrame({"k": [1, 2], "a": [10, 20]}).merge('
    'pd.DataFrame({"k": [1, 2], "b": [100, 200]}), on="k").shape == (2, 3)\n'
    "def t_lie():\n"
    '    assert pd.DataFrame({"k": [1, 2], "a": [10, 20]}).merge('
    'pd.DataFrame({"k": [1, 2], "b": [100, 200]}), on="k").shape == (0, 0)\n'
)

_PIVOT_MULTI_KW = (
    "import pandas as pd\n"
    "def t_true():\n"
    '    assert pd.DataFrame({"A": ["x", "x", "y"], "C": [10, 20, 30]}).pivot_table('
    'values="C", index="A", aggfunc="sum").shape == (2, 1)\n'
    "def t_lie():\n"
    '    assert pd.DataFrame({"A": ["x", "x", "y"], "C": [10, 20, 30]}).pivot_table('
    'values="C", index="A", aggfunc="sum").shape == (0, 0)\n'
)

_MERGE_POS_ONLY = (
    "import pandas as pd\n"
    "def t_true():\n"
    '    assert pd.DataFrame({"k": [1], "a": [10]}).merge('
    'pd.DataFrame({"k": [1], "b": [100]})).shape == (1, 3)\n'
    "def t_lie():\n"
    '    assert pd.DataFrame({"k": [1], "a": [10]}).merge('
    'pd.DataFrame({"k": [1], "b": [100]})).shape == (0, 0)\n'
)

_MERGE_ON_VS_ON_HOW = (
    "import pandas as pd\n"
    "def t_on():\n"
    '    assert pd.DataFrame({"k": [1], "a": [10]}).merge('
    'pd.DataFrame({"k": [1], "b": [100]}), on="k").shape == (1, 3)\n'
    "def t_how():\n"
    '    assert pd.DataFrame({"k": [1], "a": [10]}).merge('
    'pd.DataFrame({"k": [1], "b": [100]}), on="k", how="inner").shape == (1, 3)\n'
)

_MERGE_OTHER_IDENTITY = (
    "import pandas as pd\n"
    "def t_right_a():\n"
    '    assert pd.DataFrame({"k": [1], "a": [10]}).merge('
    'pd.DataFrame({"k": [1], "b": [100]}), on="k").shape == (1, 3)\n'
    "def t_right_b():\n"
    '    assert pd.DataFrame({"k": [1], "a": [10]}).merge('
    'pd.DataFrame({"k": [1], "b": [999]}), on="k").shape == (1, 3)\n'
)

_PIVOT_WITH_VS_WITHOUT_AGGFUNC = (
    "import pandas as pd\n"
    "def t_full():\n"
    '    assert pd.DataFrame({"A": ["x"], "C": [10]}).pivot_table('
    'values="C", index="A", aggfunc="sum").shape == (1, 1)\n'
    "def t_no_agg():\n"
    '    assert pd.DataFrame({"A": ["x"], "C": [10]}).pivot_table('
    'values="C", index="A").shape == (1, 1)\n'
)


def _euf_names(report) -> list[str]:
    return [row.name or "" for row in report.payload.ir if "#euf#" in (row.name or "")]


def _coords(report) -> set[str]:
    return set(
        re.findall(
            r"call:[A-Za-z_][A-Za-z0-9_.]*|kw:[A-Za-z_][A-Za-z0-9_]*",
            repr(report.payload.ir),
        )
    )


# ---------------------------------------------------------------------------
# 1. Lying merge — positional other + kw:on
# ---------------------------------------------------------------------------


def test_merge_pos_kw_shares_euf_key_with_call_merge_and_kw_on() -> None:
    report = build_literal_call_report(
        source=_MERGE_POS_KW, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    names = _euf_names(report)
    assert len(names) == 2
    assert names[0] == names[1]
    assert "call:merge" in names[0] and "kw:on" in names[0]
    # Outer observation is shape; multi-arg payload nests under call:merge.
    assert "call:shape" in names[0]
    assert {
        "call:merge",
        "kw:on",
        "call:shape",
        "call:pandas.DataFrame",
    } <= _coords(report)


def test_merge_pos_kw_dual_assert_refutes_via_witness(tmp_path: Path) -> None:
    result = run_source_through_real_solver(tmp_path / "merge-pos-kw", _MERGE_POS_KW)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses
    reason = (result.prove_doc.get("rows") or [{}])[0].get("reason", "")
    assert "contradictory" in reason or "unsatisfied" in statuses


# ---------------------------------------------------------------------------
# 2. Lying pivot_table — multi-kw values/index/aggfunc
# ---------------------------------------------------------------------------


def test_pivot_table_multi_kw_shares_euf_key_with_all_kws() -> None:
    report = build_literal_call_report(
        source=_PIVOT_MULTI_KW, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    names = _euf_names(report)
    assert len(names) == 2 and names[0] == names[1]
    assert "call:pivot_table" in names[0]
    assert "kw:values" in names[0] and "kw:index" in names[0] and "kw:aggfunc" in names[0]
    assert {
        "call:pivot_table",
        "kw:values",
        "kw:index",
        "kw:aggfunc",
        "call:shape",
        "call:pandas.DataFrame",
    } <= _coords(report)


def test_pivot_table_multi_kw_dual_assert_refutes_via_witness(tmp_path: Path) -> None:
    result = run_source_through_real_solver(
        tmp_path / "pivot-multi-kw", _PIVOT_MULTI_KW
    )
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


# ---------------------------------------------------------------------------
# 3. Positional-only merge (no kw) + identity guards
# ---------------------------------------------------------------------------


def test_merge_pos_only_dual_assert_refutes_via_witness(tmp_path: Path) -> None:
    """Positional other alone is still multi-arg — no kw needed for discrimination."""
    report = build_literal_call_report(
        source=_MERGE_POS_ONLY, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    names = _euf_names(report)
    assert len(names) == 2 and names[0] == names[1]
    assert "call:merge" in names[0]
    assert "kw:on" not in names[0]
    assert "call:pandas.DataFrame" in _coords(report)

    result = run_source_through_real_solver(tmp_path / "merge-pos-only", _MERGE_POS_ONLY)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)


def test_merge_on_vs_on_how_are_distinct_euf_keys() -> None:
    """Confusion guard: how= is part of identity — not interchangeable with bare on=."""
    report = build_literal_call_report(
        source=_MERGE_ON_VS_ON_HOW, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    names = _euf_names(report)
    assert len(names) == 2
    assert names[0] != names[1], names
    bare, with_how = sorted(names, key=len)
    assert "kw:on" in bare and "kw:how" not in bare
    assert "kw:on" in with_how and "kw:how" in with_how


def test_merge_different_positional_other_are_distinct_euf_keys() -> None:
    """Lying-arg surface: the positional *other* frame is in the euf key."""
    report = build_literal_call_report(
        source=_MERGE_OTHER_IDENTITY, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    names = _euf_names(report)
    assert len(names) == 2
    assert names[0] != names[1], names
    # Both are merge+on; only the nested right-hand DataFrame payload differs.
    for name in names:
        assert "call:merge" in name and "kw:on" in name


def test_pivot_with_vs_without_aggfunc_are_distinct_euf_keys() -> None:
    """Multi-kw identity: omitting aggfunc is a different callsite than including it."""
    report = build_literal_call_report(
        source=_PIVOT_WITH_VS_WITHOUT_AGGFUNC, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    names = _euf_names(report)
    assert len(names) == 2
    assert names[0] != names[1], names
    with_agg = next(n for n in names if "kw:aggfunc" in n)
    without_agg = next(n for n in names if "kw:aggfunc" not in n)
    assert "kw:values" in with_agg and "kw:index" in with_agg
    assert "kw:values" in without_agg and "kw:index" in without_agg
    assert "call:pivot_table" in with_agg and "call:pivot_table" in without_agg
