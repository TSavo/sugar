"""Ground method-coordinate body dig on bare formal receivers (Part of #3809).

Mechanism (lift-probed):

- Universe dig (`build_control_flow_body_sugar`) already bound formals at build
  time (Batch A) → ``out == call:mean(s)``.
- Callsite force_floor used ``build_bridge_body``'s single-return *shortcut*,
  which built ``s.mean()`` with an empty temporal → CallSugar emitted
  FactoryGap(``call-method:mean``) instead of MethodCallStrategy.
- Working cases: ``len(s)`` is BuiltinCallSugar (free call, not method);
  ``df[\"col\"].mean()`` has a constructed Subscript receiver.

Fix: bind formals in ``build_bridge_body`` the same way as universe dig
(``_ctx_with_formal_binds``). Opaque method: computed=None; discrimination is
dual-assert witness execution.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _fol_calls(report) -> set[str]:
    return set(re.findall(r"call:[A-Za-z_][A-Za-z0-9_.]*", repr(report.payload.ir)))


def _callable_post(report) -> str:
    row = next(r for r in report.payload.ir if (r.name or "").endswith("::callable"))
    return repr(row.post)


def _dig_refuses_for_a(report) -> list[str]:
    return [
        d.get("reason", "")
        for d in (report.payload.diagnostics or [])
        if isinstance(d, dict)
        and d.get("kind") == "dig-boundary"
        and d.get("callee") == "A"
    ]


def _floor_refuse(report) -> list[str]:
    return [
        r
        for r in _dig_refuses_for_a(report)
        if "callsite floor projection refused" in r or "call-method:" in r
    ]


# ---------------------------------------------------------------------------
# Structure: universe post + no force_floor refuse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["mean", "max", "min", "sum", "count"])
def test_bare_formal_method_body_dig_emits_call_coordinate(method: str) -> None:
    """def A(s): return s.<method>() → out == call:<method>(s); no floor refuse."""
    src = (
        "import pandas as pd\n"
        "def A(s):\n"
        f"    return s.{method}()\n"
        "def test_a():\n"
        "    assert A(pd.Series([1.0, 2.0, 3.0])) == 0.0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert any((r.name or "").endswith("::callable") for r in report.payload.ir)
    post = _callable_post(report)
    assert f"'name': 'call:{method}'" in post or f"call:{method}" in post, post
    assert f"call:{method}" in _fol_calls(report)
    assert not _floor_refuse(report), _floor_refuse(report)
    # Must not be the old gap spelling
    for reason in _dig_refuses_for_a(report):
        assert "call-method:" not in reason, reason


def test_bare_formal_mean_contrast_with_len_and_subscript() -> None:
    """len(s) and df[col].mean already worked; bare s.mean now joins them."""
    bare = (
        "import pandas as pd\n"
        "def A(s):\n"
        "    return s.mean()\n"
        "def test_a():\n"
        "    assert A(pd.Series([1.0, 2.0, 3.0])) == 2.0\n"
    )
    sub = (
        "import pandas as pd\n"
        "def A(df):\n"
        '    return df["col"].mean()\n'
        "def test_a():\n"
        '    assert A(pd.DataFrame({"col": [1.0, 2.0, 3.0]})) == 2.0\n'
    )
    leng = (
        "def A(s):\n"
        "    return len(s)\n"
        "def test_a():\n"
        "    assert A([1, 2, 3]) == 3\n"
    )
    for label, src, coord in (
        ("bare", bare, "call:mean"),
        ("sub", sub, "call:mean"),
        ("len", leng, "call:len"),
    ):
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None, label
        assert coord in _fol_calls(report), (label, _fol_calls(report))
        assert not _floor_refuse(report), (label, _floor_refuse(report))


# ---------------------------------------------------------------------------
# Dual-assert discrimination (witness EXECUTION)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "truth", "lie"),
    [
        ("mean", "2.0", "0.0"),
        ("max", "3.0", "0.0"),
        ("sum", "6.0", "0.0"),
        ("count", "3", "0"),
    ],
)
def test_bare_formal_method_dual_assert_refutes_lie_via_witness(
    tmp_path: Path, method: str, truth: str, lie: str
) -> None:
    src = (
        "import pandas as pd\n"
        "def A(s):\n"
        f"    return s.{method}()\n"
        "def t_true():\n"
        f"    assert A(pd.Series([1.0, 2.0, 3.0])) == {truth}\n"
        "def t_lie():\n"
        f"    assert A(pd.Series([1.0, 2.0, 3.0])) == {lie}\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert not _floor_refuse(report), _floor_refuse(report)
    assert f"call:{method}" in _fol_calls(report)

    result = run_source_through_real_solver(tmp_path / f"formal-{method}", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (method, result.verdict, statuses)


def test_bare_formal_mean_truthful_sat_no_refuse(tmp_path: Path) -> None:
    """Solo opaque method body dig: sat, no refuse, call:mean in IR."""
    src = (
        "import pandas as pd\n"
        "def A(s):\n"
        "    return s.mean()\n"
        "def test_a():\n"
        "    assert A(pd.Series([1.0, 2.0, 3.0])) == 2.0\n"
    )
    result = run_source_through_real_solver(tmp_path / "mean-true", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "sat", (result.verdict, statuses)
    assert "refused" not in statuses
    assert "call:mean" in repr(result.lift_doc.get("ir", []))
