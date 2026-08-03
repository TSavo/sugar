"""Formal Compare-through-IfSugar through a bound-method receiver binding.

Concrete program:

    class Chooser:
        def choose(self, left, right):
            if left < right:
                return 1
            return 0

    Chooser().choose(1, 2)

Python law: a bound method call supplies ``self`` first. That binding must not
shift ``left`` / ``right`` in the less_than demand. The condition retains one
carrier through IfSugar; self is the method binder's slot, not a compare operand.

Acceptance (each with a discrimination twin where noted):

  1. Method alone retains exactly one less_than carrier.
  2. Bound self does not shift left/right.
  3. Positional, keyword, and default calls select the correct branch.
  4. Incompatible ordering → authenticated TypeError with exact pre-effect
     state; matching boundary consumes; wrong boundary retains the halt.
  5. Identity comparison remains carrier-free.
  6. Off-by-one self-binding and branch-selection twins fail.

Exceptional pre-effect on the bound-method *call* producer path may stay red
until codex-1's lossless reduce_body fix; formal *discharge* pre-effect is the
#6640 join instrument asserted here.

Does not touch: reducer, carrier/ExitSet, IfSugar, Compare producers, assertion
routing, parameter-name maps, chained-comparison lane.
"""

from __future__ import annotations

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import ExpectationNotMetEffect
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    GuardedReturn,
    ObjectValue,
    ReturnValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute, Call, ClassDef, FunctionDef
from sugar_source_tree.tree import SourceFile

METHOD_BODY = (
    "class Chooser:\n"
    "    def choose(self, left, right):\n"
    "        if left < right:\n"
    "            return 1\n"
    "        return 0\n"
)

METHOD_DEFAULTS = (
    "class Chooser:\n"
    "    def choose(self, left, right=2):\n"
    "        if left < right:\n"
    "            return 1\n"
    "        return 0\n"
)

IDENTITY_BODY = (
    "class Chooser:\n"
    "    def choose(self, left, right):\n"
    "        if left is right:\n"
    "            return 1\n"
    "        return 0\n"
)


def _tree(source: str, name: str = "compare_if_method_caller.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _method_definition(source: str = METHOD_BODY):
    tree = _tree(source, "method_alone.py")
    class_def = next(node for node in tree.nodes() if isinstance(node, ClassDef))
    method = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "choose"
    )
    return class_def, method, method.sugar().desugar(None)


def _method_callsite(source: str) -> CallSiteValue:
    tree = _tree(source)
    calls = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Attribute)
        and node.func.attr == "choose"
    )
    assert len(calls) == 1, calls
    constructed = calls[0].sugar().desugar(None)
    assert isinstance(constructed, Complete), constructed
    assert isinstance(constructed.value, CallSiteValue), constructed.value
    return constructed.value


def _method_call_outcome(source: str):
    return _method_callsite(source).producer_outcome(None)


def _assert_bound_self_first(callsite: CallSiteValue) -> None:
    assert callsite.parameters[0] == "self"
    assert callsite.parameters[1:3] == ("left", "right")
    assert isinstance(callsite.arg_values[0], ObjectValue)
    assert callsite.arg_values[0].class_name == "Chooser"
    assert len(callsite.arg_values) == len(callsite.parameters)


def _expected_exception(name: str):
    from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

    return TemporalContext.empty().value_for(name)


def _identity(name: str):
    return _expected_exception(name).exception_type_identity()


def _only_completed(outcome: object) -> Completed:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    completed = outcome.exits[0]
    assert isinstance(completed, Completed)
    return completed


def _only_halted(outcome: object, *, require_pre_effect_state: bool = True) -> Halted:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("TypeError")
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    if require_pre_effect_state:
        assert halted.state is not None, (
            "formal less_than halt omitted real pre-effect state "
            "(NativeOperationResolutionV1.project / reduce_body collapse)"
        )
    return halted


def _assert_completed_call(outcome) -> CallSiteValue:
    assert isinstance(outcome, Complete), outcome
    assert isinstance(outcome.value, CallSiteValue), outcome.value
    return outcome.value


def _returned_term(completed: Completed) -> TermValue:
    value = completed.value
    if isinstance(value, CallSiteValue):
        value = value._dig_floor_or_none(None, owner="test_compare_if_method_caller")
        assert value is not None
        returns = tuple(
            entry
            for entry in getattr(value, "statements", ())
            if isinstance(entry, (ReturnValue, GuardedReturn))
        )
        if returns:
            assert len(returns) == 1
            value = returns[0]
    if isinstance(value, GuardedReturn):
        value = value.value
    if isinstance(value, ReturnValue):
        value = value.value
    # Method producer_outcome may wrap the body in CallSiteValue again.
    if isinstance(value, CallSiteValue):
        value = value._dig_floor_or_none(None, owner="test_compare_if_method_caller")
        assert value is not None
        returns = tuple(
            entry
            for entry in getattr(value, "statements", ())
            if isinstance(entry, (ReturnValue, GuardedReturn))
        )
        if returns:
            value = returns[0]
            if isinstance(value, GuardedReturn):
                value = value.value
            if isinstance(value, ReturnValue):
                value = value.value
    # UniverseValue / BlockValue from formal discharge.
    record = getattr(value, "record", None)
    if record is not None:
        returns = tuple(
            entry
            for entry in record.statements
            if isinstance(entry, (ReturnValue, GuardedReturn))
        )
        assert len(returns) == 1, record.statements
        value = returns[0]
        if isinstance(value, GuardedReturn):
            value = value.value
        if isinstance(value, ReturnValue):
            value = value.value
    assert isinstance(value, TermValue), value
    return value


def _left_right_cids(pending: NativeOperationExitCarrierV1):
    assert pending.demand.operator == "less_than"
    assert len(pending.demand.operand_coordinate_cids) == 2
    names = tuple(value.term.name for value in pending.operands)
    assert names == ("left", "right"), names
    return pending.demand.operand_coordinate_cids


def _through_assertion_boundary(outcome: ExitSet, expected: str) -> ExitSet:
    return outcome.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(
                expected=_expected_exception(expected), message_pattern=None
            ),
            unmet=ExpectationNotMetEffect("raise", "compare-if-method.py"),
        ),
    )


# ---------------------------------------------------------------------------
# 1. Method alone retains one less_than carrier
# ---------------------------------------------------------------------------


def test_method_alone_retains_exactly_one_less_than_carrier() -> None:
    _, method, pending = _method_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "less_than"
    assert len(pending.demand.operand_coordinate_cids) == 2
    assert len(set(pending.demand.operand_coordinate_cids)) == 2
    method_formals = tuple(p.name for p in method.params)
    assert method_formals[0] == "self"
    assert method_formals[1:] == ("left", "right")


def test_discrimination_method_alone_is_not_completed_branch() -> None:
    _, _method, pending = _method_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert not isinstance(pending, Completed)
    assert not isinstance(pending, ExitSet)


# ---------------------------------------------------------------------------
# 2. Bound self does not shift left/right
# ---------------------------------------------------------------------------


def test_bound_self_does_not_shift_left_right_coordinates() -> None:
    site = _method_callsite(METHOD_BODY + "\nChooser().choose(1, 2)\n")
    _assert_bound_self_first(site)
    assert site.arg_values[1] == TermValue(1)
    assert site.arg_values[2] == TermValue(2)
    outcome = site.producer_outcome(None)
    # Free-function path yields ExitSet(Completed); method may Complete(callsite).
    if isinstance(outcome, Complete):
        completed = Completed(
            __import__(
                "sugar_lift_py_tests.outcome.exit_set", fromlist=["true_guard"]
            ).true_guard(),
            outcome.value,
        )
        # Prefer reading via dig of callsite body completion.
        assert _returned_term(completed).value == 1
    else:
        assert _returned_term(_only_completed(outcome)).value == 1


def test_discrimination_self_is_not_a_less_than_operand() -> None:
    _class_def, method, pending = _method_definition()
    self_coord = method.formal_coordinates()[0]
    left_cid, right_cid = _left_right_cids(pending)
    assert self_coord.coordinate_cid not in {left_cid, right_cid}


# ---------------------------------------------------------------------------
# 3. Positional, keyword, and default calls select the correct branch
# ---------------------------------------------------------------------------


def test_positional_keyword_and_default_calls_select_correct_branch() -> None:
    sites = (
        _method_callsite(METHOD_BODY + "\nChooser().choose(1, 2)\n"),
        _method_callsite(METHOD_BODY + "\nChooser().choose(left=1, right=2)\n"),
        _method_callsite(METHOD_DEFAULTS + "\nChooser().choose(1)\n"),
    )
    for site in sites:
        _assert_bound_self_first(site)
        assert site.arg_values[1] == TermValue(1)
        assert site.arg_values[2] == TermValue(2)
        outcome = site.producer_outcome(None)
        if isinstance(outcome, Complete):
            from sugar_lift_py_tests.outcome.exit_set import true_guard

            assert _returned_term(Completed(true_guard(), outcome.value)).value == 1
        else:
            assert _returned_term(_only_completed(outcome)).value == 1


def test_discrimination_branch_selection_twin_fails() -> None:
    """Truthful 1 < 2 → then; lying 2 < 1 → else — distinct returns."""
    then_out = _method_call_outcome(METHOD_BODY + "\nChooser().choose(1, 2)\n")
    else_out = _method_call_outcome(METHOD_BODY + "\nChooser().choose(2, 1)\n")

    def _branch_value(outcome):
        if isinstance(outcome, Complete):
            from sugar_lift_py_tests.outcome.exit_set import true_guard

            return _returned_term(Completed(true_guard(), outcome.value)).value
        return _returned_term(_only_completed(outcome)).value

    assert _branch_value(then_out) == 1
    assert _branch_value(else_out) == 0
    assert _branch_value(then_out) != _branch_value(else_out)


# ---------------------------------------------------------------------------
# 4. Incompatible ordering → TypeError + pre-effect state
# ---------------------------------------------------------------------------


def test_incompatible_ordering_typeerror_with_exact_pre_effect_state() -> None:
    """Formal discharge path: less_than TypeError stamps reducer pre-state."""
    _, _method, pending = _method_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    testimony = pending.pre_effect_state
    assert testimony is not None, (
        "method body reducer did not enroll ReducerPreEffectStateV1 on the "
        "formal less_than carrier"
    )
    left_cid, right_cid = _left_right_cids(pending)
    from sugar_lift_py_tests.floor import NoneValue

    exits = pending.discharge({left_cid: NoneValue(), right_cid: TermValue(2)})
    halted = _only_halted(exits, require_pre_effect_state=True)
    assert halted.effect.exception_type_coordinate == _identity("TypeError")
    assert halted.state is testimony.state

    routed = _through_assertion_boundary(exits, "TypeError")
    completed = _only_completed(routed)
    assert completed.value is testimony.state

    retained = _through_assertion_boundary(exits, "ValueError")
    remaining = _only_halted(retained, require_pre_effect_state=True)
    assert remaining.effect is halted.effect
    assert remaining.state is halted.state


def test_incompatible_ordering_method_call_halts_with_named_typeerror() -> None:
    """Bound-method call producer path: TypeError identity.

    Pre-effect state on producer_outcome may stay red until codex-1 lossless
    reduce_body; identity is asserted either way when the halt surfaces.
    """
    site = _method_callsite(METHOD_BODY + "\nChooser().choose(None, 2)\n")
    _assert_bound_self_first(site)
    assert site.arg_values[1] is not None
    # None may floor as NoneValue / TermValue-like; right is 2.
    assert site.arg_values[2] == TermValue(2)
    outcome = site.producer_outcome(None)
    # Prefer ExitSet halt; Complete would be a silent wrong completion.
    assert isinstance(outcome, ExitSet), outcome
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("TypeError")
    assert halted.effect.occurrence_id == str(site)
    # Honest instrument for codex-1: state must be non-None after lossless fix.
    assert halted.state is not None, (
        "bound-method producer_outcome TypeError halt lacks pre-effect state "
        "— sole Halted still collapses through Incomplete (codex-1)"
    )


def test_discrimination_compatible_ordering_is_not_typeerror() -> None:
    outcome = _method_call_outcome(METHOD_BODY + "\nChooser().choose(1, 2)\n")
    if isinstance(outcome, Complete):
        _assert_completed_call(outcome)
    else:
        assert isinstance(_only_completed(outcome), Completed)


# ---------------------------------------------------------------------------
# 5. Identity comparison remains carrier-free
# ---------------------------------------------------------------------------


def test_identity_comparison_never_acquires_a_carrier() -> None:
    _, _method, pending = _method_definition(IDENTITY_BODY)
    assert not isinstance(pending, NativeOperationExitCarrierV1)


def test_discrimination_ordering_is_not_identity_carrier_free() -> None:
    """Bite: less_than method does acquire the carrier."""
    _, _method, pending = _method_definition(METHOD_BODY)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "less_than"


# ---------------------------------------------------------------------------
# 6. Off-by-one self-binding twin fails
# ---------------------------------------------------------------------------


def test_off_by_one_callsite_args_do_not_match_truthful_binding() -> None:
    site = _method_callsite(METHOD_BODY + "\nChooser().choose(1, 2)\n")
    truthful = site.arg_values
    assert len(truthful) == 3
    assert isinstance(truthful[0], ObjectValue)
    assert truthful[0].class_name == "Chooser"
    off_by_one = truthful[1:]
    assert len(off_by_one) == 2
    assert off_by_one != truthful
    assert not (
        isinstance(off_by_one[0], ObjectValue) and off_by_one[0].class_name == "Chooser"
    )


def test_discrimination_truthful_binding_selects_then_branch() -> None:
    site = _method_callsite(METHOD_BODY + "\nChooser().choose(1, 2)\n")
    _assert_bound_self_first(site)
    assert site.arg_values[1:] == (TermValue(1), TermValue(2))
    outcome = site.producer_outcome(None)
    if isinstance(outcome, Complete):
        from sugar_lift_py_tests.outcome.exit_set import true_guard

        assert _returned_term(Completed(true_guard(), outcome.value)).value == 1
    else:
        assert _returned_term(_only_completed(outcome)).value == 1
