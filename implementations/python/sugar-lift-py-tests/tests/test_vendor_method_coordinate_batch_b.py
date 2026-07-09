"""Batch B — Series/DataFrame METHOD coordinates (Part of #3809).

Lift-probed dual identity (do not collapse these):

| layer | locator | example |
|-------|---------|---------|
| FOL / OpaqueOpCallsite | ``call:<name>`` | ``call:mean(call:pandas.Series(...))`` |
| callEdges.targetSymbol (method-locus) | ``method:<name>`` | ``method:mean`` |

`lift_rpc` documents this split explicitly: method calls are ``method:`` on the
edge even when FOL uses ``call:``. Re-stamping FOL as ``method:`` would break
congruence with the call: coordinate family (len/str/chains).

Coverage map (Batch B, main tip):

| method | FOL | edge method-locus | direct dual unsat | body dig (df[col].m) |
|--------|-----|-------------------|-------------------|----------------------|
| mean | call:mean | method:mean | yes | yes |
| max | call:max | method:max | yes | yes |
| min | call:min | method:min | yes | yes |
| count | call:count | method:count | yes | yes |
| sum | call:sum | method:sum | yes | yes |
| astype | call:astype | (outer edge; nest in FOL) | via .sum() dual | partial* |

\\* ``s.astype`` on a bare Name formal refuses dig on main (needs Batch A formal
build-time binds). ``df[\"col\"].mean()`` body dig works because the method
receiver is a constructed Subscript.

No production change in this batch — coordinates already correct; instruments pin
locator + discrimination receipts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

# (method, truthful RHS, lying RHS) — Series([1.0, 2.0, 3.0])
_SERIES_AGGS = (
    ("mean", "2.0", "0.0"),
    ("max", "3.0", "0.0"),
    ("min", "1.0", "9.0"),
    ("count", "3", "0"),
    ("sum", "6.0", "0.0"),
)


def _fol_calls(report) -> set[str]:
    return set(re.findall(r"call:[A-Za-z_][A-Za-z0-9_.]*", repr(report.payload.ir)))


def _edge_methods(report) -> set[str]:
    out: set[str] = set()
    for edge in report.payload.call_edges or []:
        if isinstance(edge, dict):
            sym = edge.get("targetSymbol")
        else:
            sym = getattr(edge, "target_symbol", None) or getattr(
                edge, "targetSymbol", None
            )
        if isinstance(sym, str) and sym.startswith("method:"):
            out.add(sym)
    return out


def _callable_post(report) -> str:
    row = next(r for r in report.payload.ir if (r.name or "").endswith("::callable"))
    return repr(row.post)


def _dig_body_refuse(report, callee: str = "A") -> list[str]:
    return [
        d.get("reason", "")
        for d in (report.payload.diagnostics or [])
        if isinstance(d, dict)
        and d.get("kind") == "dig-boundary"
        and d.get("callee") == callee
        and "function universe body walker refused" in (d.get("reason") or "")
    ]


# ---------------------------------------------------------------------------
# Lift-probed dual locator: FOL call: + edge method:
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method, _truth, _lie", _SERIES_AGGS)
def test_series_method_dual_locator_fol_call_and_edge_method(
    method: str, _truth: str, _lie: str
) -> None:
    """Direct Series.m(): FOL call:m + callEdges method:m."""
    src = (
        "import pandas as pd\n"
        "def t():\n"
        f"    assert pd.Series([1.0, 2.0, 3.0]).{method}() == 0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert f"call:{method}" in _fol_calls(report), _fol_calls(report)
    assert f"method:{method}" in _edge_methods(report), _edge_methods(report)
    # EUF name carries the call: coordinate (not method:)
    name = report.payload.ir[0].name or ""
    assert f"call:{method}" in name, name
    assert f"method:{method}" not in name, name


def test_series_astype_fol_is_call_astype_nested_under_sum() -> None:
    """astype lives in FOL as call:astype; outer method edge is method:sum."""
    src = (
        "import pandas as pd\n"
        "def t():\n"
        '    assert pd.Series([1, 2, 3]).astype("float64").sum() == 6.0\n'
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    calls = _fol_calls(report)
    assert "call:astype" in calls and "call:sum" in calls, calls
    # Outermost method on the assertion surface owns the edge.
    assert "method:sum" in _edge_methods(report), _edge_methods(report)
    name = report.payload.ir[0].name or ""
    assert "call:astype" in name and "call:sum" in name, name


# ---------------------------------------------------------------------------
# Body dig: def A(df): return df["col"].mean()  (subscript receiver — works on main)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["mean", "max", "min", "count", "sum"])
def test_formal_df_col_method_body_dig_emits_call_coordinate(method: str) -> None:
    """Universe post carries call:<method>(py.subscript(df, col))."""
    src = (
        "import pandas as pd\n"
        "def A(df):\n"
        f'    return df["col"].{method}()\n'
        "def test_a():\n"
        '    assert A(pd.DataFrame({"col": [1.0, 2.0, 3.0]})) == 0.0\n'
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert any((r.name or "").endswith("::callable") for r in report.payload.ir)
    assert not _dig_body_refuse(report), _dig_body_refuse(report)
    post = _callable_post(report)
    assert f"'name': 'call:{method}'" in post or f"call:{method}" in post, post
    assert "py.subscript" in post or "subscript" in post, post


def test_formal_bare_name_mean_body_dig_gap_documented() -> None:
    """Residual on main: bare Name formal s.mean() refuses dig (Batch A binds).

    Batch B does not rebase on #3929; this pins the honest residual.
    """
    src = (
        "import pandas as pd\n"
        "def A(s):\n"
        "    return s.mean()\n"
        "def test_a():\n"
        "    assert A(pd.Series([1.0, 2.0, 3.0])) == 2.0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    refuses = _dig_body_refuse(report)
    # On main without Batch A: refuse. If Batch A lands first, this may flip —
    # either refuse or nested call:mean is acceptable; document both.
    if refuses:
        assert any("call-method:mean" in r or "mean" in r for r in refuses), refuses
    else:
        post = _callable_post(report)
        assert "call:mean" in post, post


# ---------------------------------------------------------------------------
# Dual-assert discrimination (witness execution)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method, truth, lie", _SERIES_AGGS)
def test_series_method_dual_assert_refutes_lie_via_witness(
    tmp_path: Path, method: str, truth: str, lie: str
) -> None:
    src = (
        "import pandas as pd\n"
        "def t_true():\n"
        f"    assert pd.Series([1.0, 2.0, 3.0]).{method}() == {truth}\n"
        "def t_lie():\n"
        f"    assert pd.Series([1.0, 2.0, 3.0]).{method}() == {lie}\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert f"method:{method}" in _edge_methods(report)
    assert f"call:{method}" in _fol_calls(report)

    result = run_source_through_real_solver(tmp_path / f"series-{method}", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (method, result.verdict, statuses)


def test_astype_sum_dual_assert_refutes_lie_via_witness(tmp_path: Path) -> None:
    src = (
        "import pandas as pd\n"
        "def t_true():\n"
        '    assert pd.Series([1, 2, 3]).astype("float64").sum() == 6.0\n'
        "def t_lie():\n"
        '    assert pd.Series([1, 2, 3]).astype("float64").sum() == 0.0\n'
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert "call:astype" in _fol_calls(report)

    result = run_source_through_real_solver(tmp_path / "astype-sum", src)
    assert result.verdict == "unsat", (
        result.verdict,
        [row.get("status") for row in result.prove_doc.get("rows", [])],
    )


@pytest.mark.parametrize(
    ("method", "truth", "lie"),
    [
        ("mean", "2.0", "0.0"),
        ("count", "3", "0"),
        ("sum", "6.0", "0.0"),
    ],
)
def test_formal_df_col_method_dual_assert_refutes_lie(
    tmp_path: Path, method: str, truth: str, lie: str
) -> None:
    """Body dig + dual-assert: shared call:A euf → unsat via witness."""
    src = (
        "import pandas as pd\n"
        "def A(df):\n"
        f'    return df["col"].{method}()\n'
        "def t_true():\n"
        f'    assert A(pd.DataFrame({{"col": [1.0, 2.0, 3.0]}})) == {truth}\n'
        "def t_lie():\n"
        f'    assert A(pd.DataFrame({{"col": [1.0, 2.0, 3.0]}})) == {lie}\n'
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert not _dig_body_refuse(report)
    assert f"call:{method}" in _fol_calls(report)

    result = run_source_through_real_solver(tmp_path / f"formal-{method}", src)
    assert result.verdict == "unsat", (
        method,
        result.verdict,
        [row.get("status") for row in result.prove_doc.get("rows", [])],
    )
