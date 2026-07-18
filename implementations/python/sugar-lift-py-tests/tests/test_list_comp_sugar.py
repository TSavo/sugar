"""ListCompSugar: [elt for target in iter if conds] is py.listcomp(...).

Single-generator simple-Name target. Symbolic/opaque iterables carry elt +
iter (+ conditions) on the comprehension coordinate — never invent members.
Finite ListValue/TupleValue iterables construct each member (set/dict comps
already do). Multi-generator and tuple-target stay loud FactoryPanic gaps.
"""

from __future__ import annotations

import ast

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    ComprehensionValue,
    ListValue,
    NoneValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.idd.sugar_witness_instruments import evaluate_seed_witnesses
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.list_comp_sugar import ListCompSugar


def _site(expr: str):
    node = ast.parse(expr, mode="eval").body
    return SourceFragment.from_node(node, "t.py")


def _xs():
    return {"xs": SymbolicValue(make_var("xs"))}


def _ys():
    return {"ys": SymbolicValue(make_var("ys"))}


# ---------------------------------------------------------------------------
# (1) positive: elt + iter ride the comprehension coordinate
# ---------------------------------------------------------------------------


def test_list_comp_reduces_to_comprehension_coordinate() -> None:
    """[x for x in xs] -> SymbolicValue(py.listcomp(py.iter_elem(xs), xs))."""
    value = reduce_value("[x for x in xs]", binds=_xs())
    assert isinstance(value, ComprehensionValue)
    elem = ctor("py.iter_elem", [make_var("xs")])
    assert value.term == ctor("py.listcomp", [elem, make_var("xs")])


# ---------------------------------------------------------------------------
# (2) discrimination: elt, iter, and conditions are carried (not dropped)
# ---------------------------------------------------------------------------


def test_elt_discriminates_the_coordinate() -> None:
    """Different elt produces a different term."""
    plain = reduce_value("[x for x in xs]", binds=_xs())
    doubled = reduce_value("[x * 2 for x in xs]", binds=_xs())
    elem = ctor("py.iter_elem", [make_var("xs")])
    assert plain.term == ctor("py.listcomp", [elem, make_var("xs")])
    assert doubled.term == ctor(
        "py.listcomp", [ctor("*", [elem, num(2)]), make_var("xs")]
    )
    assert plain.term != doubled.term


def test_iter_discriminates_the_coordinate() -> None:
    """Different iter produces a different term."""
    from_xs = reduce_value("[x for x in xs]", binds=_xs())
    from_ys = reduce_value("[x for x in ys]", binds=_ys())
    assert from_xs.term != from_ys.term
    assert from_xs.term == ctor(
        "py.listcomp",
        [ctor("py.iter_elem", [make_var("xs")]), make_var("xs")],
    )
    assert from_ys.term == ctor(
        "py.listcomp",
        [ctor("py.iter_elem", [make_var("ys")]), make_var("ys")],
    )


def test_condition_rides_the_coordinate() -> None:
    """[x for x in xs if x > 0] carries the condition term (not dropped)."""
    value = reduce_value("[x for x in xs if x > 0]", binds=_xs())
    elem = ctor("py.iter_elem", [make_var("xs")])
    cond = ctor("py.gt", [elem, num(0)])
    assert value.term == ctor("py.listcomp", [elem, make_var("xs"), cond])


def test_finite_list_comprehension_constructs_each_conditional_element() -> None:
    """#5147 pandas/numpy shape: row[i] truth inside a finite listcomp."""
    value = reduce_value(
        '[row[1] if row[1] else None for row in [[1, "date"], [2, None]]]'
    )

    assert value == ListValue((StringValue("date"), NoneValue()))


def test_deep_finite_list_comprehension_collects_without_python_recursion() -> None:
    """A finite member spine is heap-bounded, not Python-stack-bounded."""
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    result = build_node(
        ast.parse("[x for x in xs]", mode="eval").body,
        filename="t.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )
    assert isinstance(result.sugar, ListCompSugar)
    elements = tuple(TermValue(index) for index in range(5_000))

    outcome = result.sugar._collect_finite(elements, (), ctx)

    assert outcome == Complete(ListValue(elements))


def test_finite_list_comprehension_witness_truthful_sat_lying_unsat(
    tmp_path,
) -> None:
    witness = next(
        pair
        for pair in ListCompSugar.witnesses()
        if pair.name == "list_comp_finite_conditional"
    )

    assert evaluate_seed_witnesses((witness,), tmp_path).is_zero


# ---------------------------------------------------------------------------
# (3) structural: owns single-gen Name target; not multi/tuple/other kinds
# ---------------------------------------------------------------------------


def test_owns_supported_list_comprehension_clauses() -> None:
    assert ListCompSugar.owns(_site("[x for x in xs]")) is True
    assert ListCompSugar.owns(_site("[x for x in xs if x]")) is True
    assert ListCompSugar.owns(_site("[x * 2 for x in xs]")) is True
    assert ListCompSugar.owns(_site("[(a, b) for a in A for b in B]")) is True
    assert ListCompSugar.owns(_site("[x for (x, y) in pairs]")) is True
    # Other observed kinds.
    assert ListCompSugar.owns(_site("{x for x in xs}")) is False  # SetComp
    assert ListCompSugar.owns(_site("{x: x for x in xs}")) is False  # DictComp
    assert ListCompSugar.owns(_site("(x for x in xs)")) is False  # GeneratorExp
    assert ListCompSugar.owns(_site("[1, 2, 3]")) is False  # List literal

    catalog = default_catalog()
    single = [
        c.name for c in catalog.candidates_for(SugarRole.TERM, _site("[x for x in xs]"))
    ]
    multi = [
        c.name
        for c in catalog.candidates_for(
            SugarRole.TERM, _site("[x for a in A for b in B]")
        )
    ]
    literal = [
        c.name for c in catalog.candidates_for(SugarRole.TERM, _site("[1, 2, 3]"))
    ]
    assert "ListCompSugar" in single
    assert "ListCompSugar" in multi
    assert "ListCompSugar" not in literal
    assert "ListLiteralSugar" in literal


def test_multi_generator_is_a_citable_coordinate() -> None:
    value = reduce_value(
        "[(a, b) for a in A for b in B]",
        {"A": SymbolicValue(make_var("A")), "B": SymbolicValue(make_var("B"))},
    )
    assert value.term.name == "py.listcomp"


def test_tuple_target_is_a_citable_coordinate() -> None:
    value = reduce_value(
        "[(x, y) for (x, y) in pairs]",
        {"pairs": SymbolicValue(make_var("pairs"))},
    )
    assert value.term.name == "py.listcomp"


def test_nested_list_comprehension_is_a_citable_coordinate() -> None:
    value = reduce_value(
        "[[y for y in row] for row in rows]",
        {"rows": SymbolicValue(make_var("rows"))},
    )
    assert value.term.name == "py.listcomp"
    assert value.term.args[0].name == "py.listcomp"


def test_async_list_comprehension_stays_loud() -> None:
    function = ast.parse("async def f(xs):\n    return [x async for x in xs]\n").body[0]
    site = SourceFragment.from_node(function.body[0].value, "t.py")

    assert ListCompSugar.owns(site) is False
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    with pytest.raises(FactoryPanic) as raised:
        build_node(site, filename="t.py", role=SugarRole.TERM, ctx=ctx)
    assert raised.value.info.observed == "ListComp"
