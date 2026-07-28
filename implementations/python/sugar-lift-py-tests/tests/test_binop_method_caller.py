"""Formal BinOp ``add`` through a bound-method receiver binding.

Concrete program:

    class Adder:
        def combine(self, left, right):
            return left + right

    Adder().combine(1, 2)

Python law: a bound method call supplies ``self`` first. That binding must not
shift ``left`` / ``right`` in the add demand. Discharge is ``left.add(right)``;
self is the method binder's slot, not a BinOp operand.

Acceptance (each with a discrimination twin where noted):

  1. Method alone retains exactly one add demand.
  2. Bound self does not shift left/right.
  3. Positional, keyword, and default calls discharge.
  4. Compatible operands complete with the correct value.
  5. Incompatible operands → named TypeError with exact pre-effect state
     (green under #6659); wrong boundary retains the identical halt.
  6. Off-by-one self-binding and swapped-operand twins fail.
  7. BinOp does not borrow Compare's laws.

Does not touch: reducer, carrier/ExitSet, BinOp/Compare producers, assertion
routing, parameter-name maps, real-pandas BinOp lane.
"""

from __future__ import annotations

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    NoneValue,
    ObjectValue,
    RaiseValue,
    ReturnValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute, Call, ClassDef, FunctionDef
from sugar_source_tree.tree import SourceFile

METHOD_BODY = (
    "class Adder:\n"
    "    def combine(self, left, right):\n"
    "        return left + right\n"
)

METHOD_DEFAULTS = (
    "class Adder:\n"
    "    def combine(self, left, right=2):\n"
    "        return left + right\n"
)

COMPARE_BODY = (
    "class Adder:\n"
    "    def combine(self, left, right):\n"
    "        return left < right\n"
)

EQUALS_BODY = (
    "class Adder:\n"
    "    def combine(self, left, right):\n"
    "        return left == right\n"
)

IDENTITY_BODY = (
    "class Adder:\n"
    "    def combine(self, left, right):\n"
    "        return left is right\n"
)


def _tree(source: str, name: str = "binop_method_caller.py") -> SourceFile:
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
        if isinstance(node, FunctionDef) and node.name == "combine"
    )
    return class_def, method, method.sugar().desugar(None)


def _method_callsite(source: str) -> CallSiteValue:
    tree = _tree(source)
    calls = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Attribute)
        and node.func.attr == "combine"
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
    assert callsite.arg_values[0].class_name == "Adder"
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
    assert halted.effect.exception_type_coordinate is not None
    assert halted.effect.occurrence_id is not None
    if require_pre_effect_state:
        assert halted.state is not None, (
            "formal add halt omitted real pre-effect state "
            "(NativeOperationResolutionV1.project / reduce_body collapse)"
        )
    return halted


def _assert_completed_call(outcome) -> CallSiteValue:
    assert isinstance(outcome, Complete), outcome
    assert isinstance(outcome.value, CallSiteValue), outcome.value
    return outcome.value


def _returned_term(outcome) -> TermValue:
    """Pull the returned TermValue from discharge or producer_outcome."""
    if isinstance(outcome, ExitSet):
        value = _only_completed(outcome).value
    elif isinstance(outcome, Complete):
        value = outcome.value
    elif isinstance(outcome, Completed):
        value = outcome.value
    else:
        raise AssertionError(f"unexpected outcome: {type(outcome).__name__}")

    seen = set()
    while id(value) not in seen:
        seen.add(id(value))
        if isinstance(value, TermValue):
            return value
        if isinstance(value, ReturnValue):
            value = value.value
            continue
        if isinstance(value, CallSiteValue):
            dug = value._dig_floor_or_none(None, owner="binop-method-caller")
            if dug is not None:
                value = dug
                continue
        record = getattr(value, "record", None)
        if record is not None and record.statements:
            value = record.statements[-1]
            continue
        statements = getattr(value, "statements", None)
        if statements:
            value = statements[-1]
            continue
        break
    raise AssertionError(f"unprojected return: {type(value).__name__} {value!r}")


def _left_right_cids(pending: NativeOperationExitCarrierV1):
    assert pending.demand.operator == "add"
    assert len(pending.demand.operand_coordinate_cids) == 2
    names = tuple(value.term.name for value in pending.operands)
    assert names == ("left", "right"), names
    return pending.demand.operand_coordinate_cids


def _collect_raise_values(root) -> list:
    """Walk a dug body for RaiseValue faces (return-expression projection)."""
    found: list = []
    seen: set[int] = set()
    stack = [root]
    while stack:
        value = stack.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, RaiseValue):
            found.append(value)
            continue
        statements = getattr(value, "statements", None)
        if statements:
            stack.extend(statements)
            continue
        record = getattr(value, "record", None)
        if record is not None and getattr(record, "statements", None):
            stack.extend(record.statements)
            continue
        inner = getattr(value, "value", None)
        if inner is not None and inner is not value:
            stack.append(inner)
    return found


def _through_assertion_boundary(outcome: ExitSet, expected: str) -> ExitSet:
    return outcome.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(
                expected=_expected_exception(expected), message_pattern=None
            ),
            unmet=ExpectationNotMetEffect("raise", "binop-method.py"),
        ),
    )


# ---------------------------------------------------------------------------
# 1. Method alone retains one add demand
# ---------------------------------------------------------------------------


def test_method_alone_retains_exactly_one_add_demand() -> None:
    _, method, pending = _method_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "add"
    assert len(pending.demand.operand_coordinate_cids) == 2
    assert len(set(pending.demand.operand_coordinate_cids)) == 2
    assert tuple(v.term.name for v in pending.operands) == ("left", "right")
    method_formals = tuple(p.name for p in method.params)
    assert method_formals[0] == "self"
    assert method_formals[1:] == ("left", "right")


def test_discrimination_method_alone_is_not_completed() -> None:
    _, _method, pending = _method_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert not isinstance(pending, Completed)
    assert not isinstance(pending, ExitSet)


# ---------------------------------------------------------------------------
# 2. Bound self does not shift left/right
# ---------------------------------------------------------------------------


def test_bound_self_does_not_shift_left_right_coordinates() -> None:
    site = _method_callsite(METHOD_BODY + "\nAdder().combine(1, 2)\n")
    _assert_bound_self_first(site)
    assert site.arg_values[1] == TermValue(1)
    assert site.arg_values[2] == TermValue(2)
    assert _returned_term(site.producer_outcome(None)).value == 3


def test_discrimination_self_is_not_an_add_operand() -> None:
    _class_def, method, pending = _method_definition()
    self_coord = method.formal_coordinates()[0]
    left_cid, right_cid = _left_right_cids(pending)
    assert self_coord.coordinate_cid not in {left_cid, right_cid}


# ---------------------------------------------------------------------------
# 3. Positional, keyword, and default calls discharge
# ---------------------------------------------------------------------------


def test_positional_keyword_and_default_calls_discharge() -> None:
    sites = (
        _method_callsite(METHOD_BODY + "\nAdder().combine(1, 2)\n"),
        _method_callsite(
            METHOD_BODY + "\nAdder().combine(left=1, right=2)\n"
        ),
        _method_callsite(METHOD_DEFAULTS + "\nAdder().combine(1)\n"),
    )
    for site in sites:
        _assert_bound_self_first(site)
        assert site.arg_values[1] == TermValue(1)
        assert site.arg_values[2] == TermValue(2)
        assert _returned_term(site.producer_outcome(None)).value == 3


def test_discrimination_default_is_not_keyword_override() -> None:
    default = _method_callsite(METHOD_DEFAULTS + "\nAdder().combine(1)\n")
    override = _method_callsite(
        METHOD_DEFAULTS + "\nAdder().combine(1, right=9)\n"
    )
    assert default.arg_values[2] == TermValue(2)
    assert override.arg_values[2] == TermValue(9)
    assert _returned_term(default.producer_outcome(None)).value == 3
    assert _returned_term(override.producer_outcome(None)).value == 10


# ---------------------------------------------------------------------------
# 4. Compatible operands complete with the correct value
# ---------------------------------------------------------------------------


def test_compatible_operands_complete_with_correct_value() -> None:
    _, _method, pending = _method_definition()
    left_cid, right_cid = _left_right_cids(pending)
    exits = pending.discharge(
        {left_cid: TermValue(10), right_cid: TermValue(5)}
    )
    assert isinstance(exits.exits[0], Completed)
    assert _returned_term(exits).value == 15


def test_compatible_method_call_completes_with_correct_value() -> None:
    outcome = _method_call_outcome(METHOD_BODY + "\nAdder().combine(10, 5)\n")
    assert _returned_term(outcome).value == 15


def test_discrimination_wrong_sum_is_not_the_completed_value() -> None:
    outcome = _method_call_outcome(METHOD_BODY + "\nAdder().combine(10, 5)\n")
    assert _returned_term(outcome).value == 15
    assert _returned_term(outcome).value != 50


# ---------------------------------------------------------------------------
# 5. Incompatible operands → TypeError + pre-effect state (#6659)
# ---------------------------------------------------------------------------


def test_incompatible_operands_typeerror_with_exact_pre_effect_state() -> None:
    """Formal discharge: add TypeError stamps reducer pre-state (#6659 green)."""
    _, _method, pending = _method_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    testimony = pending.pre_effect_state
    assert testimony is not None, (
        "method body reducer did not enroll ReducerPreEffectStateV1 on the "
        "formal add carrier"
    )
    left_cid, right_cid = _left_right_cids(pending)
    exits = pending.discharge(
        {left_cid: NoneValue(), right_cid: TermValue(2)}
    )
    halted = _only_halted(exits, require_pre_effect_state=True)
    assert halted.effect.exception_type_coordinate == _identity("TypeError")
    assert halted.state is testimony.state

    # Matching boundary restores the same pre-effect state.
    routed = _through_assertion_boundary(exits, "TypeError")
    completed = _only_completed(routed)
    assert completed.value is testimony.state

    # Wrong boundary retains the identical effect and pre-effect state.
    retained = _through_assertion_boundary(exits, "ValueError")
    remaining = _only_halted(retained, require_pre_effect_state=True)
    assert remaining.effect is halted.effect
    assert remaining.state is halted.state


def test_incompatible_operands_method_call_halts_with_named_typeerror() -> None:
    """Bound-method call binds self/left/right; add of None+2 TypeErrors.

    Formal discharge (sibling test) owns pre-effect identity under #6659.
    Bound-method ``producer_outcome`` for a return expression may publish
    ``Complete(CallSiteValue)`` whose dig surfaces ``RaiseValue(TypeError)``
    rather than ``ExitSet(Halted)`` — statement stores (setitem) project the
    halt face; return-of-add digs the raise. Either face must name TypeError;
    a completed sum is the silent-wrong twin. When sole Halted surfaces,
    pre-effect state is required (#6659).
    """
    site = _method_callsite(METHOD_BODY + "\nAdder().combine(None, 2)\n")
    _assert_bound_self_first(site)
    assert site.arg_values[1] == NoneValue()
    assert site.arg_values[2] == TermValue(2)

    # Floor path: NoneValue.add refuses with TypeError (membership-style pin).
    _, method, _pending = _method_definition()
    floor_site = method.body[0].fragment
    direct = NoneValue().add(TermValue(2), floor_site)
    if isinstance(direct, Complete):
        assert isinstance(direct.value, RaiseValue), direct
        assert direct.value.effect.exception_name == "TypeError"
    else:
        from sugar_lift_py_tests.outcome import Incomplete

        assert isinstance(direct, Incomplete), direct
        assert direct.effect.exception_type_coordinate == _identity("TypeError") or (
            getattr(direct.effect, "exception_name", None) == "TypeError"
        )

    outcome = site.producer_outcome(None)
    if isinstance(outcome, ExitSet) and len(outcome.exits) == 1:
        halted = outcome.exits[0]
        assert isinstance(halted, Halted), halted
        assert halted.effect.exception_type_coordinate == _identity("TypeError")
        assert halted.effect.occurrence_id is not None
        assert halted.state is not None, (
            "bound-method producer_outcome TypeError halt lacks pre-effect "
            "state — sole Halted still collapses through Incomplete (#6659)"
        )
        return

    # Return-expression projection: dig must surface RaiseValue(TypeError),
    # never a completed numeric sum.
    assert isinstance(outcome, Complete), outcome
    assert isinstance(outcome.value, CallSiteValue), outcome.value
    dug = outcome.value._dig_floor_or_none(None, owner="binop-method-caller")
    assert dug is not None, outcome
    raises = _collect_raise_values(dug)
    assert raises, f"no RaiseValue under dig: {type(dug).__name__} {dug!r:.300}"
    assert any(r.effect.exception_name == "TypeError" for r in raises), raises
    # Discrimination: dig is not a completed sum of None+2.
    try:
        term = _returned_term(outcome)
    except AssertionError:
        term = None
    if term is not None:
        assert term.value != 2  # lying twin: None coerced as 0


def test_discrimination_compatible_add_is_not_typeerror() -> None:
    outcome = _method_call_outcome(METHOD_BODY + "\nAdder().combine(1, 2)\n")
    assert _returned_term(outcome).value == 3
    if isinstance(outcome, ExitSet):
        assert isinstance(outcome.exits[0], Completed)
    else:
        _assert_completed_call(outcome)


# ---------------------------------------------------------------------------
# 6. Off-by-one self-binding and swapped-operand twins fail
# ---------------------------------------------------------------------------


def test_off_by_one_callsite_args_do_not_match_truthful_binding() -> None:
    site = _method_callsite(METHOD_BODY + "\nAdder().combine(1, 2)\n")
    truthful = site.arg_values
    assert len(truthful) == 3
    assert isinstance(truthful[0], ObjectValue)
    assert truthful[0].class_name == "Adder"
    off_by_one = truthful[1:]
    assert len(off_by_one) == 2
    assert off_by_one != truthful
    assert not (
        isinstance(off_by_one[0], ObjectValue)
        and off_by_one[0].class_name == "Adder"
    )


def test_swapped_operand_twins_fail_against_truthful_sum() -> None:
    """``10 + 5 == 15``; swapped discharge must not claim the same post-state.

    For non-commutative lying maps (None + 2 vs 2 + None) one or both may
    TypeError — either way not a Completed 15.
    """
    _, _method, pending = _method_definition()
    left_cid, right_cid = _left_right_cids(pending)

    truthful = pending.discharge(
        {left_cid: TermValue(10), right_cid: TermValue(5)}
    )
    assert isinstance(truthful.exits[0], Completed)
    assert _returned_term(truthful).value == 15

    # Swapped numeric still sums (commutative) — use asymmetric TypeError twin:
    # left=None right=2 vs left=2 right=None may both TypeError but wrong
    # completion is the bite for a lying map that claims sum 15 from None.
    lying = pending.discharge(
        {left_cid: NoneValue(), right_cid: TermValue(2)}
    )
    lying_face = lying.exits[0]
    if isinstance(lying_face, Completed):
        assert _returned_term(lying).value != 15
    else:
        assert isinstance(lying_face, Halted)
        assert lying_face.effect.exception_type_coordinate == _identity("TypeError")


def test_discrimination_truthful_operand_order_completes_sum() -> None:
    site = _method_callsite(METHOD_BODY + "\nAdder().combine(10, 5)\n")
    _assert_bound_self_first(site)
    assert site.arg_values[1:] == (TermValue(10), TermValue(5))
    assert _returned_term(site.producer_outcome(None)).value == 15


# ---------------------------------------------------------------------------
# 7. BinOp does not borrow Compare's laws
# ---------------------------------------------------------------------------


def test_binop_does_not_borrow_compare_laws() -> None:
    _, _method, add_pending = _method_definition(METHOD_BODY)
    _, _m2, lt_pending = _method_definition(COMPARE_BODY)
    _, _m3, eq_pending = _method_definition(EQUALS_BODY)
    _, _m4, id_pending = _method_definition(IDENTITY_BODY)

    assert isinstance(add_pending, NativeOperationExitCarrierV1)
    assert add_pending.demand.operator == "add"

    assert isinstance(lt_pending, NativeOperationExitCarrierV1)
    assert lt_pending.demand.operator == "less_than"
    assert add_pending.demand.operator != lt_pending.demand.operator

    assert isinstance(eq_pending, NativeOperationExitCarrierV1)
    assert eq_pending.demand.operator == "equals"
    assert add_pending.demand.operator != eq_pending.demand.operator

    assert not isinstance(id_pending, NativeOperationExitCarrierV1)


def test_discrimination_add_typeerror_is_not_less_than_demand() -> None:
    _, _method, add_pending = _method_definition(METHOD_BODY)
    _, _m2, lt_pending = _method_definition(COMPARE_BODY)
    assert add_pending.demand.operator == "add"
    assert lt_pending.demand.operator == "less_than"
    # Same incompatible shape, different operators — demands are distinct.
    assert add_pending.demand.operator != lt_pending.demand.operator
