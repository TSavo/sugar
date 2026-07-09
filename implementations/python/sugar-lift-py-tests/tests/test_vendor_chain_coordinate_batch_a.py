"""Batch A — chained vendor-op coordinates (Part of #3809).

Locator (lift-probed, not assumed): nested ``call:<outer>(call:<inner>(...))``.
Each call node wraps once; value is a derived companion when foldable, never a
substitution. Method chains use the ``call:`` locator (not ``method:``).

Coverage map (Batch A):

| surface | direct nested coords | formal body dig | dual-assert unsat |
|---------|----------------------|-----------------|-------------------|
| groupby().sum() | yes | yes ``out==call:sum(call:groupby(df,k))`` | via ``len(...)`` |
| dropna().mean() | yes | yes ``out==call:mean(call:dropna(s))`` | yes |
| reshape().sum() | yes (#3920) | yes (#3920) | yes (#3920) |
| dropna().shape | yes (#3920) | yes (#3920) | tuple sat* |

*tuple RHS dual-assert remains sat under z3 (known injectivity gap).

Formal body dig requires formals temporally bound at *build* time so
MethodCallStrategy qualifies Name receivers (``df.groupby``). Opaque
discrimination is dual-assert witness execution (not solver-only fold).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_NESTED_GROUPBY = ("call:pandas.DataFrame", "call:groupby", "call:sum")
_NESTED_DROPNA_MEAN = ("call:pandas.Series", "call:dropna", "call:mean")


def _coords(report) -> set[str]:
    return set(re.findall(r"call:[A-Za-z_][A-Za-z0-9_.]*", repr(report.payload.ir)))


def _callable_post(report) -> str:
    row = next(r for r in report.payload.ir if (r.name or "").endswith("::callable"))
    return repr(row.post)


def _dig_refuses_for(report, callee: str) -> list[str]:
    return [
        d.get("reason", "")
        for d in (report.payload.diagnostics or [])
        if isinstance(d, dict)
        and d.get("kind") == "dig-boundary"
        and d.get("callee") == callee
        and "function universe body walker refused" in (d.get("reason") or "")
    ]


# ---------------------------------------------------------------------------
# Lift-probed nested shape: direct chains (outer wraps inner)
# ---------------------------------------------------------------------------


def test_direct_groupby_sum_shape_emits_nested_call_coordinates() -> None:
    """Direct: call:shape(call:sum(call:groupby(call:pandas.DataFrame(...), k)))."""
    src = (
        "import pandas as pd\n"
        "def t():\n"
        '    assert pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]})'
        '.groupby("k").sum().shape == (2, 1)\n'
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert set(_NESTED_GROUPBY) | {"call:shape"} <= _coords(report)
    name = report.payload.ir[0].name or ""
    # One wrap per call node — nest order sum(groupby(DataFrame))
    assert "call:sum(c:call:groupby(c:call:pandas.DataFrame" in name, name


def test_direct_dropna_mean_emits_nested_call_coordinates() -> None:
    """Direct: call:mean(call:dropna(call:pandas.Series(...)))."""
    src = (
        "import pandas as pd\n"
        "def t():\n"
        "    assert pd.Series([1.0, None, 3.0]).dropna().mean() == 2.0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert set(_NESTED_DROPNA_MEAN) <= _coords(report)
    name = report.payload.ir[0].name or ""
    assert "call:mean(c:call:dropna(c:call:pandas.Series" in name, name


# ---------------------------------------------------------------------------
# Formal body dig: def A(df): return df.groupby(...).sum()
# ---------------------------------------------------------------------------


def test_formal_groupby_sum_body_dig_emits_nested_coordinate() -> None:
    """Universe post: out == call:sum(call:groupby(df, 'k')) — no collapse."""
    src = (
        "import pandas as pd\n"
        "def A(df):\n"
        '    return df.groupby("k").sum()\n'
        "def test_a():\n"
        '    assert A(pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]}))'
        ' == A(pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]}))\n'
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert any((r.name or "").endswith("::callable") for r in report.payload.ir)
    assert not _dig_refuses_for(report, "A"), _dig_refuses_for(report, "A")
    assert {"call:groupby", "call:sum"} <= _coords(report)
    post = _callable_post(report)
    assert "call:groupby" in post and "call:sum" in post, post
    # Nest: sum wraps groupby — inner ctor appears inside sum's args in the post tree
    assert "'name': 'call:sum'" in post and "'name': 'call:groupby'" in post, post


def test_formal_dropna_mean_body_dig_emits_nested_coordinate() -> None:
    src = (
        "import pandas as pd\n"
        "def A(s):\n"
        "    return s.dropna().mean()\n"
        "def test_a():\n"
        "    assert A(pd.Series([1.0, None, 3.0])) == 2.0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert any((r.name or "").endswith("::callable") for r in report.payload.ir)
    assert not _dig_refuses_for(report, "A"), _dig_refuses_for(report, "A")
    post = _callable_post(report)
    assert "call:mean" in post and "call:dropna" in post, post


def test_formal_method_sum_body_dig_emits_call_sum() -> None:
    """Single method on formal: out == call:sum(s)."""
    src = (
        "import pandas as pd\n"
        "def A(s):\n"
        "    return s.sum()\n"
        "def test_a():\n"
        "    assert A(pd.Series([1.0, 2.0, 3.0])) == 6.0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert any((r.name or "").endswith("::callable") for r in report.payload.ir)
    assert not _dig_refuses_for(report, "A")
    post = _callable_post(report)
    assert "call:sum" in post, post


# ---------------------------------------------------------------------------
# Dual-assert discrimination (witness execution) — 3 chain seeds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "src"),
    [
        (
            "dropna_mean",
            (
                "import pandas as pd\n"
                "def t_true():\n"
                "    assert pd.Series([1.0, None, 3.0]).dropna().mean() == 2.0\n"
                "def t_lie():\n"
                "    assert pd.Series([1.0, None, 3.0]).dropna().mean() == 0.0\n"
            ),
        ),
        (
            "groupby_len",
            (
                "import pandas as pd\n"
                "def t_true():\n"
                '    assert len(pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]})'
                '.groupby("k").sum()) == 2\n'
                "def t_lie():\n"
                '    assert len(pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]})'
                '.groupby("k").sum()) == 9\n'
            ),
        ),
        (
            "reshape_sum",
            (
                "import numpy as np\n"
                "def t_true():\n"
                "    assert np.array([1, 2, 3, 4]).reshape(2, 2).sum() == 10\n"
                "def t_lie():\n"
                "    assert np.array([1, 2, 3, 4]).reshape(2, 2).sum() == 0\n"
            ),
        ),
    ],
)
def test_chain_dual_assert_refutes_lie_via_witness(
    tmp_path: Path, label: str, src: str
) -> None:
    """Opaque chain discrimination: dual-assert witness → unsat (not solver-only)."""
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    # Nested coords present on the direct surface
    coords = _coords(report)
    assert any(c.startswith("call:") for c in coords), coords

    result = run_source_through_real_solver(tmp_path / label, src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (label, result.verdict, statuses)


def test_formal_dropna_mean_dual_assert_refutes_lie(tmp_path: Path) -> None:
    """Formal body dig + dual-assert: shared call:A euf key → unsat."""
    src = (
        "import pandas as pd\n"
        "def A(s):\n"
        "    return s.dropna().mean()\n"
        "def t_true():\n"
        "    assert A(pd.Series([1.0, None, 3.0])) == 2.0\n"
        "def t_lie():\n"
        "    assert A(pd.Series([1.0, None, 3.0])) == 0.0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert {"call:mean", "call:dropna"} <= _coords(report)
    assert not _dig_refuses_for(report, "A")

    result = run_source_through_real_solver(tmp_path / "formal-dropna-mean", src)
    assert result.verdict == "unsat", (
        result.verdict,
        [row.get("status") for row in result.prove_doc.get("rows", [])],
    )


def test_formal_groupby_sum_value_eq_truthful_sat(tmp_path: Path) -> None:
    """Opaque DF chain: solo value-equality sat; nested coords in lift IR."""
    src = (
        "import pandas as pd\n"
        "def A(df):\n"
        '    return df.groupby("k").sum()\n'
        "def test_a():\n"
        '    assert A(pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]}))'
        ' == A(pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]}))\n'
    )
    result = run_source_through_real_solver(tmp_path / "formal-gb-true", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "sat", (result.verdict, statuses)
    assert "refused" not in statuses
    blob = repr(result.lift_doc.get("ir", []))
    assert "call:groupby" in blob and "call:sum" in blob, blob
