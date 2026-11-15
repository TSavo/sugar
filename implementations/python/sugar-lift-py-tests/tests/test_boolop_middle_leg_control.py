"""A three-leg BoolOp keeps middle-leg control and occurrence identity."""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.outcome import ExitSet, Halted
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import BoolOp, Call, Compare
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.effect import RaiseEffect


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
    assert isinstance(outcome, ExitSet)
    halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
    assert len(halted) == 1
    if len(outcome.exits) == 1:
        # A sole halt is the raise itself.
        assert isinstance(halted[0].effect, RaiseEffect)
    assert (
        isinstance(halted[0].effect.occurrence_id, str)
        and ":" in halted[0].effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted[0].effect.occurrence_id!r}"
    )
    return halted[0].effect.occurrence_id


def _occurrence(compare: Compare) -> str:
    return str(compare.sugar().site)


def test_first_false_returns_exact_operand_and_skips_both_later_legs() -> None:
    outcome, comparisons = _expression("2 < 1 and None < 1 and None in 3")

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), FalseBoolLiteralSugar)
    assert str(outcome.completed_value().site) == _occurrence(comparisons[0])
    assert str(outcome.completed_value().site) not in {
        _occurrence(comparisons[1]),
        _occurrence(comparisons[2]),
    }


def test_middle_false_returns_exact_operand_and_skips_membership() -> None:
    outcome, comparisons = _expression("1 < 2 and 3 < 2 and None in 3")

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), FalseBoolLiteralSugar)
    assert str(outcome.completed_value().site) == _occurrence(comparisons[1])
    assert str(outcome.completed_value().site) != _occurrence(comparisons[2])


def test_successful_three_leg_chain_returns_exact_last_operand() -> None:
    outcome, comparisons = _expression("1 < 2 and 2 < 3 and 1 in [1]")

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), TrueBoolLiteralSugar)
    assert str(outcome.completed_value().site) == _occurrence(comparisons[2])



def test_a_call_of_choose_is_its_coordinate_and_edge() -> None:
    """#7757 step 5 (#8705, "Edge, join at prove"): each call of ``choose`` is
    its coordinate and edge, the one unanswered call (completes under its
    ``python:unknown_callee_call.completes`` atom, halts under the complement
    naming nothing), never ``choose``'s body applied to the actuals.  Which leg
    raises for which actuals is stated by ``choose``'s contract over its
    formals and decided at prove; the leg control itself is the literal tests
    above.

    Replaces ``test_middle_typeerror_blocks_toxic_and_safe_membership_with_
    exact_state``, ``test_first_typeerror_blocks_distinct_middle_and_
    membership_twins`` and ``test_third_leg_membership_halt_retains_its_
    occurrence_and_state``, which read the leg's halt and the callee's state
    off the body applied at the call: the mechanism #8705 deleted."""
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.effect.authenticated_raise_locus import (
        AuthenticatedRaiseLocus,
    )

    tree = _tree(
        "def choose(a, b, c, d, e, f):\n"
        "    return a < b and c < d and e in f\n"
        "\n"
        "choose(1, 2, None, 1, None, 3)\n"
        "choose(None, 2, 1, 2, 1, [1])\n"
        "choose(1, 2, 2, 3, None, 3)\n"
    )
    comparisons = tuple(node for node in tree.nodes() if isinstance(node, Compare))
    assert len(comparisons) == 3
    legs = {
        AuthenticatedRaiseLocus.of(compare.sugar().site).value
        for compare in comparisons
    }
    outcomes = tuple(
        node.sugar().desugar(None) for node in tree.nodes() if isinstance(node, Call)
    )
    assert len(outcomes) == 3
    for outcome in outcomes:
        assert isinstance(outcome, ExitSet)
        assert len(outcome.exits) == 2
        (halted,) = outcome.halts()
        assert isinstance(halted, Halted)
        assert type(halted.effect) is UndeterminedRaiseEffect
        assert halted.effect.exception_name is None
        raised_at = str(halted.effect.occurrence_id)
        assert not any(raised_at.startswith(leg) for leg in legs)
