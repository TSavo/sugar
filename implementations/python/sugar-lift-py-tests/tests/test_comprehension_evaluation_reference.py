"""A comprehension's element and conditions read a target name by reference.

Temporal choice 1 (#7661), row-7 map item 5 (#7757): substitution rewrites a
read of a comprehension target name to ``EvaluationRef(<coordinate>)``, the
coordinate ``ComprehensionSugar`` binds each member under, never to the name
looked up by spelling.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.comprehension_sugar import (
    ComprehensionSugar,
    ComprehensionTargetSugar,
    _leaf_projections,
    _projection,
)
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import (
    BinOp,
    Compare,
    EvaluationRef,
    FunctionDef,
    ListComp,
    Return,
)
from sugar_source_tree.tree import SourceFile


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "comprehension_reference.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _comprehension(source: str) -> ListComp:
    rewritten = _function(source).substitute({})
    (ret,) = rewritten.body
    assert isinstance(ret, Return)
    assert isinstance(ret.value, ListComp)
    return ret.value


def test_element_and_condition_read_the_generator_coordinate() -> None:
    comp = _comprehension("def f(xs):\n    return [x + 1 for x in xs if x > 0]\n")
    coordinate = ListComp._generator_binding_coordinate(comp, 0, comp.generators[0])
    assert isinstance(comp.elt, BinOp)
    assert isinstance(comp.elt.left, EvaluationRef)
    assert comp.elt.left.evaluation == coordinate
    assert comp.elt.left.name == "x"
    (condition,) = comp.generators[0].ifs
    assert isinstance(condition, Compare)
    assert isinstance(condition.left, EvaluationRef)
    assert condition.left.evaluation == coordinate


def test_a_reference_sits_at_the_read_not_the_target() -> None:
    comp = _comprehension("def f(xs):\n    return [x + 1 for x in xs if x > 0]\n")
    target = comp.generators[0].target
    (condition,) = comp.generators[0].ifs
    assert comp.elt.left.span != target.span
    assert condition.left.span != target.span
    assert comp.elt.left.span.end < target.span.start
    assert target.span.end < condition.left.span.start


def test_a_chained_condition_still_constructs() -> None:
    comp = _comprehension("def f(xs):\n    return [x for x in xs if 0 < x < 5]\n")
    assert isinstance(comp.sugar(), ComprehensionSugar)


def test_the_sugar_binds_the_coordinate_the_reference_reads() -> None:
    comp = _comprehension("def f(xs):\n    return [x for x in xs]\n")
    sugar = comp.sugar()
    assert isinstance(sugar, ComprehensionSugar)
    assert isinstance(comp.elt, EvaluationRef)
    assert sugar.generators[0].binding_coordinate_cid == comp.elt.evaluation


def test_the_iterable_does_not_read_its_own_target() -> None:
    comp = _comprehension("def f(x):\n    return [x for x in x]\n")
    assert isinstance(comp.elt, EvaluationRef)
    assert not isinstance(comp.generators[0].iter, EvaluationRef)


def test_a_later_generator_reads_an_earlier_target() -> None:
    comp = _comprehension("def f(xs):\n    return [y for x in xs for y in x]\n")
    first = ListComp._generator_binding_coordinate(comp, 0, comp.generators[0])
    second = ListComp._generator_binding_coordinate(comp, 1, comp.generators[1])
    assert first != second
    assert isinstance(comp.generators[1].iter, EvaluationRef)
    assert comp.generators[1].iter.evaluation == first
    assert isinstance(comp.elt, EvaluationRef)
    assert comp.elt.evaluation == second


def test_a_later_target_ends_the_earlier_reference() -> None:
    comp = _comprehension("def f(xs):\n    return [x for x in xs for x in x]\n")
    second = ListComp._generator_binding_coordinate(comp, 1, comp.generators[1])
    assert isinstance(comp.elt, EvaluationRef)
    assert comp.elt.evaluation == second


def test_a_destructuring_target_reads_each_leaf_coordinate() -> None:
    comp = _comprehension("def f(ps):\n    return [a - b for a, b in ps]\n")
    pattern = comp.unit.require_target_pattern_for_target(comp.generators[0].target)
    a, b = (coordinate.cid for coordinate in pattern.target_coordinates)
    assert isinstance(comp.elt, BinOp)
    assert isinstance(comp.elt.left, EvaluationRef)
    assert isinstance(comp.elt.right, EvaluationRef)
    assert (comp.elt.left.evaluation, comp.elt.left.name) == (a, "a")
    assert (comp.elt.right.evaluation, comp.elt.right.name) == (b, "b")
    sugar = comp.sugar()
    assert isinstance(sugar, ComprehensionSugar)
    assert tuple(c.cid for c in sugar.generators[0].target_coordinates) == (a, b)


def test_the_same_source_gives_the_same_coordinates() -> None:
    source = "def f(xs):\n    return [x for x in xs]\n"
    assert _comprehension(source).elt.evaluation == _comprehension(source).elt.evaluation


def test_a_member_binds_the_coordinate_last() -> None:
    comp = _comprehension("def f(xs):\n    return [x for x in xs]\n")
    sugar = comp.sugar()
    generator = sugar.generators[0]
    ctx = ReduceContext.root(owner="comprehension-ref")
    inner = sugar._member_ctx(generator, TermValue(3), ctx)
    latest = inner.temporal.latest(generator.binding_coordinate_cid, "x")
    assert latest is not None
    assert latest.name == generator.binding_coordinate_cid
    reference = EvaluationRefSugar(
        evaluation=generator.binding_coordinate_cid, name="x", site=None
    )
    assert reference.desugar(inner) == ExitSet.completed(TermValue(3))


# #7757 item 7: every member binds its coordinate before any read, and a
# member reference reads that coordinate only -- never the name.


def _bound(ctx: ReduceContext, name: str, value) -> ReduceContext:
    return ctx.with_temporal(ctx.temporal.bind_value(name, value))


def test_every_comprehension_reference_is_a_member_reference() -> None:
    comp = _comprehension("def f(xs):\n    return [x + 1 for x in xs if x > 0]\n")
    (condition,) = comp.generators[0].ifs
    for reference in (comp.elt.left, condition.left):
        assert isinstance(reference, EvaluationRef)
        assert reference.member is True
        sugar = reference.sugar()
        assert isinstance(sugar, EvaluationRefSugar)
        assert sugar.member is True
    pairs = _comprehension("def f(ps):\n    return [a - b for a, b in ps]\n")
    assert pairs.elt.left.member is True
    assert pairs.elt.right.member is True


def test_a_member_reference_never_reads_the_name() -> None:
    ctx = ReduceContext.root(owner="comprehension-member")
    ctx = _bound(ctx, "coordinate", TermValue(3))
    # An enclosing statement's runtime binding of the same spelling, bound
    # after the member: it may not leak into the read.
    ctx = _bound(ctx, "x", TermValue(99))
    member = EvaluationRefSugar(
        evaluation="coordinate", name="x", site=None, member=True
    )
    assert member.desugar(ctx) == ExitSet.completed(TermValue(3))


def test_an_unbound_member_reference_refuses() -> None:
    ctx = _bound(ReduceContext.root(owner="comprehension-member"), "x", TermValue(99))
    member = EvaluationRefSugar(
        evaluation="coordinate", name="x", site=None, member=True
    )
    with pytest.raises(ConstructionPanic):
        member.desugar(ctx)
    with pytest.raises(ConstructionPanic):
        member.desugar(None)


def test_a_symbolic_member_is_bound_before_the_element_reads_it() -> None:
    comp = _comprehension("def f(xs):\n    return [x for x in xs]\n")
    sugar = comp.sugar()
    generator = sugar.generators[0]
    coordinate = generator.binding_coordinate_cid
    ctx = _bound(ReduceContext.root(owner="comprehension-member"), "x", TermValue(99))
    inner = sugar._symbolic_member_ctx(generator, ctx)
    member = SymbolicValue(make_var(coordinate))
    assert inner.temporal.value_if_bound(coordinate) == member
    assert sugar.element.desugar(inner) == ExitSet.completed(member)


def test_a_symbolic_member_binds_without_a_context() -> None:
    comp = _comprehension("def f(xs):\n    return [x for x in xs]\n")
    sugar = comp.sugar()
    generator = sugar.generators[0]
    inner = sugar._symbolic_member_ctx(generator, None)
    member = SymbolicValue(make_var(generator.binding_coordinate_cid))
    assert inner.temporal.value_if_bound(generator.binding_coordinate_cid) == member


def test_a_symbolic_destructuring_member_binds_each_leaf_projection() -> None:
    comp = _comprehension("def f(ps):\n    return [a - b for a, b in ps]\n")
    sugar = comp.sugar()
    generator = sugar.generators[0]
    element = make_var(generator.binding_coordinate_cid)
    inner = sugar._symbolic_member_ctx(
        generator, ReduceContext.root(owner="comprehension-member")
    )
    a, b = (coordinate.cid for coordinate in generator.target_coordinates)
    assert inner.temporal.value_if_bound(a) == SymbolicValue(_projection(element, 0, 2))
    assert inner.temporal.value_if_bound(b) == SymbolicValue(_projection(element, 1, 2))


def test_leaf_projections_nest_as_the_source_nests() -> None:
    target = ComprehensionTargetSugar(
        coordinates=(
            ComprehensionTargetSugar(source_name="a"),
            ComprehensionTargetSugar(
                coordinates=(
                    ComprehensionTargetSugar(source_name="b"),
                    ComprehensionTargetSugar(source_name="c"),
                )
            ),
        )
    )
    element = make_var("member")
    inner = _projection(element, 1, 2)
    assert _leaf_projections(target, element) == (
        _projection(element, 0, 2),
        _projection(inner, 0, 2),
        _projection(inner, 1, 2),
    )
    leaf = ComprehensionTargetSugar(source_name="x")
    assert _leaf_projections(leaf, element) == (element,)
