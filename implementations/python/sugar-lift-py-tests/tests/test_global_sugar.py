"""GlobalSugar — construction gap drain (Part of #3809).

Lift-probe (before):

    def f():
        global x
        return 1
    assert f() == 1

Refuse: FactoryGap · owner=python.factory · observed=Global
· requested=statement
· fix=create sugar_lift_py_tests.sugar.global.global_sugar

Mechanism: missing AST recognizer for Global (empty STATEMENT catalog
candidates) — not a floor totalizer. Grammar-ledger membrane: declared
shared-scope mutation; cross-frame interleaving is not pinned by this body.

After: GlobalSugar → SupportValue (account for the declaration without
fabricating module-mutation semantics).

Discrimination: dual-assert unsat via witness EXECUTION (inert statement
return path).
"""

from __future__ import annotations

import ast
from pathlib import Path

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory import factory_panic
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.floor import SupportValue
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.global_sugar import GlobalSugar
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _build_global(src: str) -> GlobalSugar:
    node = ast.parse(src).body[0]
    if isinstance(node, ast.FunctionDef):
        node = next(s for s in node.body if isinstance(s, ast.Global))
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    result = build_node(node, filename="f.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert isinstance(result.sugar, GlobalSugar)
    return result.sugar


def test_global_sugar_selects_and_names() -> None:
    sugar = _build_global("def f():\n    global x, y\n    return 1\n")
    assert sugar.names == ("x", "y")


def test_global_desugars_to_support_value() -> None:
    sugar = _build_global("def f():\n    global x\n    return 1\n")
    value = complete_value(sugar.desugar(None), owner="probe")
    assert isinstance(value, SupportValue)


def test_global_in_body_dig_no_construction_gap() -> None:
    src = (
        "def f():\n"
        "    global x\n"
        "    return 1\n"
        "\n"
        "def test_a():\n"
        "    assert f() == 1\n"
    )
    try:
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
    except FactoryGap as exc:  # pragma: no cover - regression
        raise AssertionError(f"still construction gap: {exc.info}") from exc
    assert report is not None
    blob = repr(report.payload)
    assert "create sugar_lift_py_tests.sugar.global.global_sugar" not in blob
    assert "observed=Global" not in blob or "sugar-gap" not in blob
    assert report.payload.ir


def test_global_dual_assert_refutes_lie_via_witness(tmp_path: Path) -> None:
    """Dual-assert discrimination: global is support; return value refutes lie."""
    src = (
        "def A(z):\n"
        "    global x\n"
        "    return z\n"
        "\n"
        "def t_true():\n"
        "    assert A(1) == 1\n"
        "\n"
        "def t_lie():\n"
        "    assert A(1) == 2\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert "create sugar_lift_py_tests.sugar.global.global_sugar" not in repr(
        report.payload
    )

    result = run_source_through_real_solver(tmp_path / "global-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses
