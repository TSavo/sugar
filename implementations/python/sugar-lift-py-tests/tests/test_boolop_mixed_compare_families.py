"""A BoolOp composes comparison families without lending laws between them."""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import RaiseValue
from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import BoolOp, Compare
from sugar_source_tree.tree import SourceFile


def _expression(source_expression: str):
    source = f"def mixed(a, b, c, d):\n    return {source_expression}\n"
    tree = SourceFile(
        (source, "boolop-mixed-families.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    boolop = next(node for node in tree.nodes() if isinstance(node, BoolOp))
    comparisons = tuple(node for node in tree.nodes() if isinstance(node, Compare))
    assert len(comparisons) == 2
    return boolop.sugar().desugar(None), comparisons


def _raise_occurrence(outcome) -> str:
    if isinstance(outcome, Complete):
        assert isinstance(outcome.value, RaiseValue)
        assert outcome.value.effect.occurrence_id is not None
        return outcome.value.effect.occurrence_id
    assert isinstance(outcome, ExitSet)
    halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
    assert len(halted) == 1
    assert halted[0].effect.occurrence_id is not None
    return halted[0].effect.occurrence_id


def test_false_ordering_short_circuits_membership_and_returns_first_operand() -> None:
    outcome, comparisons = _expression("2 < 1 and None in 3")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, FalseBoolLiteralSugar)
    assert str(outcome.value.site) == str(comparisons[0].sugar().site)
    assert str(outcome.value.site) != str(comparisons[1].sugar().site)


def test_truthful_ordering_evaluates_membership_exception_at_second_site() -> None:
    outcome, comparisons = _expression("1 < 2 and None in 3")

    assert _raise_occurrence(outcome) == str(comparisons[1].sugar().site)
    assert _raise_occurrence(outcome) != str(comparisons[0].sugar().site)


def test_ordering_exception_bypasses_membership_and_keeps_first_site() -> None:
    outcome, comparisons = _expression("None < 1 and 1 in [1]")

    assert _raise_occurrence(outcome) == str(comparisons[0].sugar().site)
    assert _raise_occurrence(outcome) != str(comparisons[1].sugar().site)


def _atom_names(formula) -> set[str]:
    name = getattr(formula, "name", None)
    found = {name} if isinstance(name, str) else set()
    for operand in getattr(formula, "operands", ()):
        found.update(_atom_names(operand))
    return found


def test_symbolic_mixed_boolop_retains_each_family_law_and_occurrence() -> None:
    outcome, comparisons = _expression("a < b and c in d")

    assert isinstance(outcome, ExitSet)
    halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
    assert len(halted) == 2
    assert {
        name
        for exit_ in halted
        for name in _atom_names(exit_.guard)
        if name.endswith("dispatch_raises")
    } == {"python.lt_dispatch_raises", "python.contains_dispatch_raises"}
    assert {exit_.effect.occurrence_id for exit_ in halted} == {
        str(compare.sugar().site) for compare in comparisons
    }


def test_swapping_families_swaps_laws_without_collapsing_occurrences() -> None:
    outcome, comparisons = _expression("a in b and c < d")

    assert isinstance(outcome, ExitSet)
    halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
    assert len(halted) == 2
    assert {
        name
        for exit_ in halted
        for name in _atom_names(exit_.guard)
        if name.endswith("dispatch_raises")
    } == {"python.contains_dispatch_raises", "python.lt_dispatch_raises"}
    assert {exit_.effect.occurrence_id for exit_ in halted} == {
        str(compare.sugar().site) for compare in comparisons
    }
