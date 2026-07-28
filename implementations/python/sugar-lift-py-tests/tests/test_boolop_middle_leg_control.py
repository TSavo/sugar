"""A three-leg BoolOp keeps middle-leg control and occurrence identity."""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import RaiseValue
from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import BoolOp, Call, Compare
from sugar_source_tree.tree import SourceFile


def _tree(source: str) -> SourceFile:
    return SourceFile(
        (source, "boolop-middle-leg.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _expression(expression: str):
    tree = _tree(f"result = {expression}\n")
    boolop = next(node for node in tree.nodes() if isinstance(node, BoolOp))
    comparisons = tuple(node for node in tree.nodes() if isinstance(node, Compare))
    assert len(comparisons) == 3
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


def _caller_outcomes(calls: str):
    source = (
        "def choose(a, b, c, d, e, f):\n"
        "    return a < b and c < d and e in f\n"
        f"\n{calls}"
    )
    tree = _tree(source)
    comparisons = tuple(node for node in tree.nodes() if isinstance(node, Compare))
    outcomes = tuple(
        node.sugar().desugar(None)
        for node in tree.nodes()
        if isinstance(node, Call)
    )
    assert len(comparisons) == 3
    return outcomes, comparisons


def _only_halted(outcome) -> Halted:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    return halted


def _occurrence(compare: Compare) -> str:
    return str(compare.sugar().site)


def test_first_false_returns_exact_operand_and_skips_both_later_legs() -> None:
    outcome, comparisons = _expression("2 < 1 and None < 1 and None in 3")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, FalseBoolLiteralSugar)
    assert str(outcome.value.site) == _occurrence(comparisons[0])
    assert str(outcome.value.site) not in {
        _occurrence(comparisons[1]),
        _occurrence(comparisons[2]),
    }


def test_middle_false_returns_exact_operand_and_skips_membership() -> None:
    outcome, comparisons = _expression("1 < 2 and 3 < 2 and None in 3")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, FalseBoolLiteralSugar)
    assert str(outcome.value.site) == _occurrence(comparisons[1])
    assert str(outcome.value.site) != _occurrence(comparisons[2])


def test_successful_three_leg_chain_returns_exact_last_operand() -> None:
    outcome, comparisons = _expression("1 < 2 and 2 < 3 and 1 in [1]")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)
    assert str(outcome.value.site) == _occurrence(comparisons[2])


def test_middle_typeerror_blocks_toxic_and_safe_membership_with_exact_state() -> None:
    (toxic, safe), comparisons = _caller_outcomes(
        "choose(1, 2, None, 1, None, 3)\n"
        "choose(1, 2, None, 1, 1, [1])\n"
    )
    toxic_halt = _only_halted(toxic)
    safe_halt = _only_halted(safe)

    middle_occurrence = _occurrence(comparisons[1])
    assert toxic_halt.effect.occurrence_id == middle_occurrence
    assert safe_halt.effect.occurrence_id == middle_occurrence
    assert toxic_halt.effect.occurrence_id != _occurrence(comparisons[2])
    assert toxic_halt.state is not None
    assert safe_halt.state is not None
    assert toxic_halt.state == safe_halt.state


def test_first_typeerror_blocks_distinct_middle_and_membership_twins() -> None:
    (toxic, safe), comparisons = _caller_outcomes(
        "choose(None, 2, None, 1, None, 3)\n"
        "choose(None, 2, 1, 2, 1, [1])\n"
    )
    toxic_halt = _only_halted(toxic)
    safe_halt = _only_halted(safe)

    first_occurrence = _occurrence(comparisons[0])
    assert toxic_halt.effect.occurrence_id == first_occurrence
    assert safe_halt.effect.occurrence_id == first_occurrence
    assert toxic_halt.effect.occurrence_id not in {
        _occurrence(comparisons[1]),
        _occurrence(comparisons[2]),
    }
    assert toxic_halt.state is not None
    assert safe_halt.state is not None
    assert toxic_halt.state == safe_halt.state


def test_third_leg_membership_halt_retains_its_occurrence_and_state() -> None:
    (outcome,), comparisons = _caller_outcomes("choose(1, 2, 2, 3, None, 3)\n")
    halted = _only_halted(outcome)

    assert halted.effect.occurrence_id == _occurrence(comparisons[2])
    assert halted.effect.occurrence_id not in {
        _occurrence(comparisons[0]),
        _occurrence(comparisons[1]),
    }
    assert halted.state is not None
