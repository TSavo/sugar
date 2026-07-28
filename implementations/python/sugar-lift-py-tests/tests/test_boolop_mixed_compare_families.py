"""A BoolOp composes comparison families without lending laws between them."""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import RaiseValue
from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import BoolOp, Call, Compare
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


def _caller_outcomes(calls: str):
    source = (
        "def mixed(a, b, c, d):\n"
        "    return a < b and c in d\n"
        f"\n{calls}"
    )
    tree = SourceFile(
        (source, "boolop-mixed-caller.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    comparisons = tuple(node for node in tree.nodes() if isinstance(node, Compare))
    outcomes = tuple(
        node.sugar().desugar(None)
        for node in tree.nodes()
        if isinstance(node, Call)
    )
    assert len(comparisons) == 2
    return outcomes, comparisons


def _only_halted(outcome) -> Halted:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    return halted


def _formal_occurrence(compare: Compare) -> str:
    return str(compare.sugar().site)


def test_first_leg_halt_blocks_toxic_and_safe_membership_with_exact_state() -> None:
    (toxic, safe), comparisons = _caller_outcomes(
        "mixed(None, 1, None, 3)\n"
        "mixed(None, 1, 1, [1])\n"
    )
    toxic_halt = _only_halted(toxic)
    safe_halt = _only_halted(safe)

    first_occurrence = str(comparisons[0].sugar().site)
    assert toxic_halt.effect.occurrence_id == first_occurrence
    assert safe_halt.effect.occurrence_id == first_occurrence
    assert toxic_halt.effect.occurrence_id != _formal_occurrence(comparisons[1])
    assert toxic_halt.state is not None
    assert safe_halt.state is not None
    assert toxic_halt.state == safe_halt.state


def test_truthful_first_leg_routes_membership_halt_to_second_occurrence_and_state() -> None:
    (outcome,), comparisons = _caller_outcomes("mixed(1, 2, None, 3)\n")
    halted = _only_halted(outcome)

    assert halted.effect.occurrence_id == _formal_occurrence(comparisons[1])
    assert halted.effect.occurrence_id != _formal_occurrence(comparisons[0])
    assert halted.state is not None
