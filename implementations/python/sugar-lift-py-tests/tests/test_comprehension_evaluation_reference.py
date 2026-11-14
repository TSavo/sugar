"""A comprehension's element and conditions read a target name by reference.

Temporal choice 1 (#7661), row-7 map item 5 (#7757): substitution rewrites a
read of a comprehension target name to ``EvaluationRef(<coordinate>)``, the
coordinate ``ComprehensionSugar`` binds each member under, never to the name
looked up by spelling.
"""

from __future__ import annotations

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.comprehension_sugar import ComprehensionSugar
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
