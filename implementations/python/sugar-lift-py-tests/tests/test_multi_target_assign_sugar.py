"""MultiTargetAssignSugar — construction gap drain (Part of #3809).

Lift-probe (before):

    system, node, release, version, machine = infos = os.uname()

Refuse: FactoryGap · owner=python.factory · observed=Assign
· requested=statement
· fix=create sugar_lift_py_tests.sugar.assign.assign_sugar
(empty STATEMENT catalog — multi-target chain; AssignSugar owns only
single-Name targets)

Mechanism: missing AST recognizer for multi-target Assign — not a floor
totalizer. Residual locus surfaces via pandas show_versions dig into
platform/os.uname chain.

After: MultiTargetAssignSugar binds Name targets and fixed Tuple/List of
Names against one RHS source (left-to-right), never fabricating values.
"""

from __future__ import annotations

import ast

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory import factory_panic
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import BlockValue, BoundVar, ReturnValue, TermValue
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.multi_target_assign_sugar import MultiTargetAssignSugar
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver
from pathlib import Path


def test_multi_target_name_chain_selects_sugar() -> None:
    node = ast.parse("a = b = 1").body[0]
    site = SourceFragment.from_node(node, "f.py")
    names = {
        c.name for c in default_catalog().candidates_for(SugarRole.STATEMENT, site)
    }
    assert "MultiTargetAssignSugar" in names
    assert "AssignSugar" not in names

    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    result = build_node(node, filename="f.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert isinstance(result.sugar, MultiTargetAssignSugar)
    assert {name for name, _path in result.sugar.bindings} == {"a", "b"}


def test_tuple_then_name_chain_binds_like_os_uname_residual() -> None:
    """Residual shape: `system, node, … = infos = os.uname()`."""
    node = ast.parse("a, b = pair = (1, 2)").body[0]
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    result = build_node(node, filename="f.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert isinstance(result.sugar, MultiTargetAssignSugar)
    names = [name for name, _path in result.sugar.bindings]
    assert names == ["a", "b", "pair"]


def test_name_chain_resolves_through_return() -> None:
    assert compose_block("    a = b = 5\n    return a\n") == BlockValue(
        (ReturnValue(TermValue(5)),)
    )


def test_tuple_name_chain_resolves_through_return() -> None:
    assert compose_block("    a, b = pair = (1, 2)\n    return a\n") == BlockValue(
        (ReturnValue(TermValue(1)),)
    )


def test_single_name_assign_still_owned_by_assign_sugar() -> None:
    node = ast.parse("a = 1").body[0]
    site = SourceFragment.from_node(node, "f.py")
    names = {
        c.name for c in default_catalog().candidates_for(SugarRole.STATEMENT, site)
    }
    assert "AssignSugar" in names
    assert "MultiTargetAssignSugar" not in names


def test_multi_target_body_dig_no_construction_gap() -> None:
    src = (
        "def f():\n"
        "    a, b = pair = (1, 2)\n"
        "    return a\n"
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
    assert "create sugar_lift_py_tests.sugar.assign.assign_sugar" not in blob


def test_multi_target_dual_assert_refutes_lie_via_witness(tmp_path: Path) -> None:
    src = (
        "def A(z):\n"
        "    a, b = pair = (z, 2)\n"
        "    return a\n"
        "\n"
        "def t_true():\n"
        "    assert A(1) == 1\n"
        "\n"
        "def t_lie():\n"
        "    assert A(1) == 2\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None

    result = run_source_through_real_solver(tmp_path / "multi-target-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses
