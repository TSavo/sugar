"""Formal ordering comparisons retain their one carrier through ``IfSugar``."""

from __future__ import annotations

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.effect import ExpectationNotMetEffect
from sugar_lift_py_tests.floor import CallSiteValue, GuardedReturn, ReturnValue, TermValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile


HELPER = (
    "def helper(left, right):\n"
    "    if left < right:\n"
    "        return 1\n"
    "    return 0\n"
)


def _tree(calls: str = "") -> SourceFile:
    source = f"{HELPER}\n{calls}"
    return SourceFile(
        (source, "compare-through-if.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _function_outcome():
    function = next(
        node for node in _tree().nodes() if isinstance(node, FunctionDef)
    )
    return function.sugar().desugar(None)


def _call_outcomes(calls: str):
    return tuple(
        node.sugar().desugar(None)
        for node in _tree(calls).nodes()
        if isinstance(node, Call)
    )


def _only_completed(outcome: object) -> Completed:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    completed = outcome.exits[0]
    assert isinstance(completed, Completed)
    return completed


def _only_halted(outcome: object) -> Halted:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    return halted


def _expected_exception(name: str):
    """Resolve builtin type identity through the lexical floor, never spelling dispatch."""
    from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

    return TemporalContext.empty().value_for(name)


def _through_assertion_boundary(outcome: ExitSet, expected: str) -> ExitSet:
    return outcome.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(
                expected=_expected_exception(expected), message_pattern=None
            ),
            unmet=ExpectationNotMetEffect("raise", "compare-through-if.py"),
        ),
    )


def _returned_term(completed: Completed) -> TermValue:
    value = completed.value
    if isinstance(value, CallSiteValue):
        value = value._dig_floor_or_none(None, owner="test_compare_through_if_sugar")
        assert value is not None
        returns = tuple(
            entry
            for entry in value.statements
            if isinstance(entry, (ReturnValue, GuardedReturn))
        )
        assert len(returns) == 1
        value = returns[0]
    if isinstance(value, GuardedReturn):
        value = value.value
    if isinstance(value, ReturnValue):
        value = value.value
    assert isinstance(value, TermValue)
    return value


def test_formal_ordering_condition_creates_exactly_one_carrier() -> None:
    pending = _function_outcome()

    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "less_than"
    assert len(pending.demand.operand_coordinate_cids) == 2


def test_caller_actuals_discharge_the_condition_carrier() -> None:
    (outcome,) = _call_outcomes("helper(1, 2)\n")

    completed = _only_completed(outcome)
    assert _returned_term(completed).value == 1


def test_completed_predicate_selects_the_correct_branch() -> None:
    truthful, lying = _call_outcomes("helper(1, 2)\nhelper(2, 1)\n")

    assert _returned_term(_only_completed(truthful)).value == 1
    assert _returned_term(_only_completed(lying)).value == 0


def test_exceptional_condition_bypasses_both_bodies() -> None:
    (outcome,) = _call_outcomes("helper(None, 2)\n")

    halted = _only_halted(outcome)
    assert (
        halted.effect.exception_type_coordinate
        == _expected_exception("TypeError").exception_type_identity()
    )
    assert isinstance(halted.effect.occurrence_id, str) and ":" in halted.effect.occurrence_id, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )


def test_matching_assertion_boundary_consumes_and_preserves_pre_effect_state() -> None:
    """Join #6631 + #6627: the formal condition halt reaches its boundary.

    RED until ``caller_parameter_contract.py`` threads the reducer's real
    pre-effect state into ``NativeOperationResolutionV1.project``.  The
    assertion boundary correctly refuses a matching halt with ``state=None``;
    never fabricate that state in this test or in the boundary consumer.
    """
    (produced,) = _call_outcomes("helper(None, 2)\n")
    original = _only_halted(produced)
    assert original.state is not None, (
        "caller_parameter_contract.py NativeOperationResolutionV1.project "
        "omitted the formal ordering halt's real pre-effect state"
    )

    routed = _through_assertion_boundary(produced, "TypeError")

    completed = _only_completed(routed)
    assert completed.value is original.state


def test_wrong_expected_type_retains_the_same_formal_ordering_halt() -> None:
    (produced,) = _call_outcomes("helper(None, 2)\n")
    original = _only_halted(produced)

    routed = _through_assertion_boundary(produced, "ValueError")

    remaining = _only_halted(routed)
    assert remaining.effect is original.effect
    assert remaining.state is original.state


def test_symbolic_if_branches_keep_complementary_guards() -> None:
    pending = _function_outcome()
    assert isinstance(pending, NativeOperationExitCarrierV1)

    left, right = pending.coordinates
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var

    exits = pending.discharge(
        {
            left.coordinate_cid: SymbolicValue(make_var("actual_left")),
            right.coordinate_cid: SymbolicValue(make_var("actual_right")),
        }
    )
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    record = exits.exits[0].value.record
    returns = tuple(
        value for value in record.statements if isinstance(value, GuardedReturn)
    )
    assert len(returns) == 2
    then_return, else_return = returns
    assert then_return.value == TermValue(1)
    assert else_return.value == TermValue(0)
    assert then_return.guards[0].args[0].name == "python:branch_result"
    assert else_return.guards[0].kind == "not"
    assert else_return.guards[0].operands[0] == then_return.guards[0]


def test_identity_condition_never_acquires_a_carrier() -> None:
    source = HELPER.replace("left < right", "left is right")
    tree = SourceFile(
        (source, "identity-through-if.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))

    assert not isinstance(
        function.sugar().desugar(None), NativeOperationExitCarrierV1
    )
