from __future__ import annotations

import ast
from dataclasses import replace

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import DictLiteralValue, SetLiteralValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var, num
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_literal_dict_comp_reduces_finite_domain() -> None:
    value = reduce_value("{x: x + 1 for x in [1, 2, 3]}")

    assert value == DictLiteralValue(
        (
            (num(1), num(2)),
            (num(2), num(3)),
            (num(3), num(4)),
        )
    )


def test_literal_dict_comp_guard_filters_domain() -> None:
    value = reduce_value("{x: x for x in [1, 2, 3] if x != 2}")

    assert value == DictLiteralValue(((num(1), num(1)), (num(3), num(3))))


def test_literal_set_comp_reduces_and_deduplicates() -> None:
    value = reduce_value("{x for x in [1, 1, 2, 3] if x != 3}")

    assert value == SetLiteralValue((num(1), num(2)))


def test_literal_set_reduces_and_deduplicates() -> None:
    value = reduce_value("{1, 1, 2}")

    assert value == SetLiteralValue((num(1), num(2)))


def test_comprehension_cardinality_bad_twins_refute(tmp_path) -> None:
    dict_truth = run_source_through_real_solver(
        tmp_path / "dict-truth",
        "def A():\n"
        "    return len({x: x for x in [1, 2]})\n"
        "\n"
        "def test_a():\n"
        "    assert A() == 2\n",
    )
    dict_lie = run_source_through_real_solver(
        tmp_path / "dict-lie",
        "def A():\n"
        "    return len({x: x for x in [1, 2]})\n"
        "\n"
        "def test_a():\n"
        "    assert A() == 3\n",
    )
    set_truth = run_source_through_real_solver(
        tmp_path / "set-truth",
        "def A():\n"
        "    return len({x for x in [1, 1, 2]})\n"
        "\n"
        "def test_a():\n"
        "    assert A() == 2\n",
    )
    set_lie = run_source_through_real_solver(
        tmp_path / "set-lie",
        "def A():\n"
        "    return len({x for x in [1, 1, 2]})\n"
        "\n"
        "def test_a():\n"
        "    assert A() == 3\n",
    )
    set_literal_truth = run_source_through_real_solver(
        tmp_path / "set-literal-truth",
        "def A():\n"
        "    return len({1, 1, 2})\n"
        "\n"
        "def test_a():\n"
        "    assert A() == 2\n",
    )
    set_literal_lie = run_source_through_real_solver(
        tmp_path / "set-literal-lie",
        "def A():\n"
        "    return len({1, 1, 2})\n"
        "\n"
        "def test_a():\n"
        "    assert A() == 3\n",
    )

    assert dict_truth.verdict == "sat"
    assert dict_lie.verdict == "unsat"
    assert set_truth.verdict == "sat"
    assert set_lie.verdict == "unsat"
    assert set_literal_truth.verdict == "sat"
    assert set_literal_lie.verdict == "unsat"
    assert "DictCompSugar" in dict_truth.selected_sugars
    assert "DictCompSugar" in dict_lie.selected_sugars
    assert "SetCompSugar" in set_truth.selected_sugars
    assert "SetCompSugar" in set_lie.selected_sugars
    assert "SetSugar" in set_literal_truth.selected_sugars
    assert "SetSugar" in set_literal_lie.selected_sugars


def test_comprehension_runtime_iterables_are_typed_runtime_effects() -> None:
    reduce_ctx = ReduceContext.root(owner="comprehension-test")
    reduce_ctx = replace(
        reduce_ctx,
        temporal=TemporalContext.empty().bind_value(
            "items", SymbolicValue(make_var("items"))
        ),
    )

    for source, label in (
        ("{x: x for x in items}", "dict comprehension runtime boundary"),
        ("{x for x in items}", "set comprehension runtime boundary"),
    ):
        ctx = FactoryBuildContext(
            filename="comprehension.py", catalog=default_catalog()
        )
        body = ctx.build_body(ast.parse(source, mode="eval").body, SugarRole.TERM)

        outcome = body.reduce(reduce_ctx)

        assert isinstance(outcome, Incomplete)
        assert isinstance(outcome.effect, RuntimeEffect)
        assert label in outcome.effect.reason
        assert "runtime iterable `Name`" in outcome.effect.reason
        assert "typed red" in outcome.effect.reason
        assert "blame=" in outcome.effect.reason


def test_comprehension_factory_selects_shape_recognizers() -> None:
    ctx = FactoryBuildContext(filename="comprehension.py", catalog=default_catalog())

    dict_result = build_node(
        ast.parse("{x: x for x in [1]}", mode="eval").body,
        filename="comprehension.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )
    set_result = build_node(
        ast.parse("{x for x in [1]}", mode="eval").body,
        filename="comprehension.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )
    set_literal_result = build_node(
        ast.parse("{1}", mode="eval").body,
        filename="comprehension.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )

    assert dict_result.audit_row.selected == "DictCompSugar"
    assert set_result.audit_row.selected == "SetCompSugar"
    assert set_literal_result.audit_row.selected == "SetSugar"
