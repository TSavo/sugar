"""Keyword / multi-arg method coordinate body dig (Part of #3809).

Direct asserts already mint ``call:<m>(receiver, …, kw:…)`` via symbolic_term.
Body dig went through CallSugar, which gated MethodCallStrategy on
``not call_has_keywords()`` → refuse ``call-method:mean`` / ``call-builtin:sum``.

Fix: MethodCallStrategy carries keywords as ``kw:<name>(value)`` extras;
CallSiteValue opaque residual allows non-empty arguments as extra_args.
Opaque: computed=None; discrimination is dual-assert witness EXECUTION.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _fol_calls(report) -> set[str]:
    return set(re.findall(r"call:[A-Za-z_][A-Za-z0-9_.]*", repr(report.payload.ir)))


def _kw_coords(report) -> set[str]:
    return set(re.findall(r"kw:[A-Za-z_][A-Za-z0-9_]*", repr(report.payload.ir)))


def _callable_post(report) -> str:
    row = next(r for r in report.payload.ir if (r.name or "").endswith("::callable"))
    return repr(row.post)


def _dig_body_refuses(report, callee: str = "A") -> list[str]:
    return [
        d.get("reason", "")
        for d in (report.payload.diagnostics or [])
        if isinstance(d, dict)
        and d.get("kind") == "dig-boundary"
        and d.get("callee") == callee
        and "function universe body walker refused" in (d.get("reason") or "")
    ]


def _floor_refuse(report, callee: str = "A") -> list[str]:
    return [
        d.get("reason", "")
        for d in (report.payload.diagnostics or [])
        if isinstance(d, dict)
        and d.get("kind") == "dig-boundary"
        and d.get("callee") == callee
        and (
            "callsite floor projection refused" in (d.get("reason") or "")
            or "call-method:" in (d.get("reason") or "")
            or "call-builtin:" in (d.get("reason") or "")
        )
    ]


# ---------------------------------------------------------------------------
# Structure: body dig emits call: + kw: matching direct
# ---------------------------------------------------------------------------


def test_formal_sum_axis_body_dig_emits_call_sum_kw_axis() -> None:
    """def A(s): return s.sum(axis=0) → out == call:sum(s, kw:axis(0))."""
    src = (
        "import pandas as pd\n"
        "def A(s):\n"
        "    return s.sum(axis=0)\n"
        "def test_a():\n"
        "    assert A(pd.Series([1.0, 2.0, 3.0])) == 6.0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert any((r.name or "").endswith("::callable") for r in report.payload.ir)
    post = _callable_post(report)
    assert "call:sum" in post, post
    assert "kw:axis" in post, post
    assert "kw:axis" in _kw_coords(report)
    assert not _dig_body_refuses(report), _dig_body_refuses(report)
    for reason in _dig_body_refuses(report) + _floor_refuse(report):
        assert "call-method:" not in reason, reason
        assert "call-builtin:sum" not in reason, reason


def test_formal_mean_axis_body_dig_emits_call_mean_kw_axis() -> None:
    src = (
        "import pandas as pd\n"
        "def A(s):\n"
        "    return s.mean(axis=0)\n"
        "def test_a():\n"
        "    assert A(pd.Series([1.0, 2.0, 3.0])) == 2.0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    post = _callable_post(report)
    assert "call:mean" in post, post
    assert "kw:axis" in post, post
    assert not _dig_body_refuses(report), _dig_body_refuses(report)


def test_constructed_sum_axis_body_dig_emits_call_sum_kw_axis() -> None:
    """def A(): return Series(…).sum(axis=0) — constructed + kwargs."""
    src = (
        "import pandas as pd\n"
        "def A():\n"
        "    return pd.Series([1.0, 2.0, 3.0]).sum(axis=0)\n"
        "def test_a():\n"
        "    assert A() == 6.0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert any((r.name or "").endswith("::callable") for r in report.payload.ir)
    post = _callable_post(report)
    assert "call:sum" in post, post
    assert "kw:axis" in post, post
    assert "call:pandas.Series" in post or "call:pandas.Series" in _fol_calls(report)
    assert not _dig_body_refuses(report), _dig_body_refuses(report)


def test_formal_dropna_how_body_dig_emits_kw_how() -> None:
    # Value-eq dig surface (is-not-None does not force universe dig).
    src = (
        "import pandas as pd\n"
        "def A(df):\n"
        '    return df.dropna(how="all")\n'
        "def test_a():\n"
        '    DF = pd.DataFrame({"a": [1, None], "b": [None, None]})\n'
        "    assert A(DF) == A(DF)\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert any((r.name or "").endswith("::callable") for r in report.payload.ir)
    post = _callable_post(report)
    assert "call:dropna" in post, post
    assert "kw:how" in post, post
    assert not _dig_body_refuses(report), _dig_body_refuses(report)


def test_formal_merge_multi_arg_still_emits_both_formals() -> None:
    """Multi-arg positional still grounds (regression pin)."""
    src = (
        "import pandas as pd\n"
        "def A(left, right):\n"
        "    return left.merge(right)\n"
        "def test_a():\n"
        '    L = pd.DataFrame({"k": [1], "a": [1]})\n'
        '    R = pd.DataFrame({"k": [1], "b": [2]})\n'
        "    assert A(L, R) == A(L, R)\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    post = _callable_post(report)
    assert "call:merge" in post, post
    assert "left" in post and "right" in post, post
    assert not _dig_body_refuses(report), _dig_body_refuses(report)


def test_direct_sum_axis_still_euf_kw_axis() -> None:
    """Direct path unchanged: call:sum(…, kw:axis) + method:sum edge."""
    src = (
        "import pandas as pd\n"
        "def t():\n"
        "    assert pd.Series([1.0, 2.0, 3.0]).sum(axis=0) == 6.0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    name = report.payload.ir[0].name or ""
    assert "call:sum" in name and "kw:axis" in name, name
    assert "kw:axis" in _kw_coords(report)


# ---------------------------------------------------------------------------
# Discrimination: dual-assert unsat via witness EXECUTION
# ---------------------------------------------------------------------------


def test_formal_sum_axis_dual_assert_refutes_lie_via_witness(tmp_path: Path) -> None:
    src = (
        "import pandas as pd\n"
        "def A(s):\n"
        "    return s.sum(axis=0)\n"
        "def t_true():\n"
        "    assert A(pd.Series([1.0, 2.0, 3.0])) == 6.0\n"
        "def t_lie():\n"
        "    assert A(pd.Series([1.0, 2.0, 3.0])) == 0.0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert "call:sum" in _fol_calls(report)
    assert "kw:axis" in _kw_coords(report)
    assert not _dig_body_refuses(report), _dig_body_refuses(report)

    result = run_source_through_real_solver(tmp_path / "sum-axis-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


def test_constructed_sum_axis_dual_assert_refutes_lie_via_witness(
    tmp_path: Path,
) -> None:
    src = (
        "import pandas as pd\n"
        "def A():\n"
        "    return pd.Series([1.0, 2.0, 3.0]).sum(axis=0)\n"
        "def t_true():\n"
        "    assert A() == 6.0\n"
        "def t_lie():\n"
        "    assert A() == 0.0\n"
    )
    result = run_source_through_real_solver(tmp_path / "sum-axis-ctor-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


def test_formal_sum_axis_solo_truthful_sat_no_refuse(tmp_path: Path) -> None:
    """Opaque-ish body dig: solo truthful sat; no refuse; call:sum+kw in IR."""
    src = (
        "import pandas as pd\n"
        "def A(s):\n"
        "    return s.sum(axis=0)\n"
        "def test_a():\n"
        "    assert A(pd.Series([1.0, 2.0, 3.0])) == 6.0\n"
    )
    result = run_source_through_real_solver(tmp_path / "sum-axis-true", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "sat", (result.verdict, statuses)
    assert "refused" not in statuses
    ir = repr(result.lift_doc.get("ir", []))
    assert "call:sum" in ir
    assert "kw:axis" in ir


def test_direct_sum_axis_dual_assert_still_unsat(tmp_path: Path) -> None:
    src = (
        "import pandas as pd\n"
        "def t_true():\n"
        "    assert pd.Series([1.0, 2.0, 3.0]).sum(axis=0) == 6.0\n"
        "def t_lie():\n"
        "    assert pd.Series([1.0, 2.0, 3.0]).sum(axis=0) == 0.0\n"
    )
    result = run_source_through_real_solver(tmp_path / "direct-sum-axis-dual", src)
    assert result.verdict == "unsat", (
        result.verdict,
        [row.get("status") for row in result.prove_doc.get("rows", [])],
    )
