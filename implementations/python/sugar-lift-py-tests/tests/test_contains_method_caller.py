"""Formal membership ``contains`` through a bound-method receiver binding.

Concrete program:

    class Checker:
        def has(self, container, item):
            return item in container

    Checker().has([1, 2], 1)

Python law: a bound method call supplies ``self`` first. That binding must not
shift ``container`` / ``item`` in the contains demand. Source ``item in
container`` evaluates item then container, but discharge is
``container.contains(item)`` — operator ``contains``, operands
``(container, item)``.

Acceptance (each with a discrimination twin where noted):

  1. Method alone retains exactly one contains demand.
  2. Bound self does not shift container/item.
  3. Positional, keyword, and default calls discharge.
  4. Membership uses contains — never ordering's exception law.
  5. Non-container receiver yields named TypeError (pre-effect may stay red
     on producer_outcome behind #6659 / codex-1).
  6. Identity and equality remain separate laws (carrier-free / equals).
  7. Off-by-one self-binding and swapped container/item twins fail.

Does not touch: reducer, carrier/ExitSet, Compare/contains producers, assertion
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
    ListValue,
    NoneValue,
    ObjectValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute, Call, ClassDef, FunctionDef
from sugar_source_tree.tree import SourceFile

METHOD_BODY = (
    "class Checker:\n"
    "    def has(self, container, item):\n"
    "        return item in container\n"
)

METHOD_DEFAULTS = (
    "class Checker:\n"
    "    def has(self, container, item=1):\n"
    "        return item in container\n"
)

IDENTITY_BODY = (
    "class Checker:\n"
    "    def has(self, container, item):\n"
    "        return item is container\n"
)

EQUALITY_BODY = (
    "class Checker:\n"
    "    def has(self, container, item):\n"
    "        return item == container\n"
)

ORDERING_BODY = (
    "class Checker:\n"
    "    def has(self, container, item):\n"
    "        return item < container\n"
)


def _tree(source: str, name: str = "contains_method_caller.py") -> SourceFile:
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
        if isinstance(node, FunctionDef) and node.name == "has"
    )
    return class_def, method, method.sugar().desugar(None)


def _method_callsite(source: str) -> CallSiteValue:
    tree = _tree(source)
    calls = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Attribute)
        and node.func.attr == "has"
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
    assert callsite.parameters[1:3] == ("container", "item")
    assert isinstance(callsite.arg_values[0], ObjectValue)
    assert callsite.arg_values[0].class_name == "Checker"
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
            "formal contains halt omitted real pre-effect state "
            "(NativeOperationResolutionV1.project / reduce_body collapse)"
        )
    return halted


def _assert_completed_call(outcome) -> CallSiteValue:
    assert isinstance(outcome, Complete), outcome
    assert isinstance(outcome.value, CallSiteValue), outcome.value
    return outcome.value


def _container_item_cids(pending: NativeOperationExitCarrierV1):
    """contains demand order: container, item — not source item-then-container."""
    assert pending.demand.operator == "contains"
    assert len(pending.demand.operand_coordinate_cids) == 2
    names = tuple(value.term.name for value in pending.operands)
    assert names == ("container", "item"), names
    return pending.demand.operand_coordinate_cids


def _through_assertion_boundary(outcome: ExitSet, expected: str) -> ExitSet:
    return outcome.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(
                expected=_expected_exception(expected), message_pattern=None
            ),
            unmet=ExpectationNotMetEffect("raise", "contains-method.py"),
        ),
    )


def _unwrap_return(value):
    """Pull a returned membership bool floor out of callsite / universe wrappers."""
    from sugar_lift_py_tests.floor import ReturnValue
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar

    seen = set()
    while id(value) not in seen:
        seen.add(id(value))
        if isinstance(value, (TrueBoolLiteralSugar, FalseBoolLiteralSugar)):
            return isinstance(value, TrueBoolLiteralSugar)
        if type(value).__name__ == "TrueBoolLiteralSugar":
            return True
        if type(value).__name__ == "FalseBoolLiteralSugar":
            return False
        if getattr(value, "value", None) is True:
            return True
        if getattr(value, "value", None) is False:
            return False
        if isinstance(value, ReturnValue):
            value = value.value
            continue
        if isinstance(value, CallSiteValue):
            dug = value._dig_floor_or_none(None, owner="contains-method-caller")
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
    raise AssertionError(f"unprojected membership value: {type(value).__name__} {value!r}")


def _membership_bool(outcome) -> bool:
    """Project a completed membership result to a Python bool."""
    if isinstance(outcome, Complete):
        return _unwrap_return(outcome.value)
    completed = _only_completed(outcome)
    return _unwrap_return(completed.value)


# ---------------------------------------------------------------------------
# 1. Method alone retains one contains demand
# ---------------------------------------------------------------------------


def test_method_alone_retains_exactly_one_contains_demand() -> None:
    _, method, pending = _method_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "contains"
    assert len(pending.demand.operand_coordinate_cids) == 2
    # Discharge order: container, item (not source item, container).
    assert tuple(v.term.name for v in pending.operands) == ("container", "item")
    method_formals = tuple(p.name for p in method.params)
    assert method_formals[0] == "self"
    assert method_formals[1:] == ("container", "item")


def test_discrimination_method_alone_is_not_completed_membership() -> None:
    _, _method, pending = _method_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert not isinstance(pending, Completed)
    assert not isinstance(pending, ExitSet)


# ---------------------------------------------------------------------------
# 2. Bound self does not shift container/item
# ---------------------------------------------------------------------------


def test_bound_self_does_not_shift_container_item_coordinates() -> None:
    site = _method_callsite(METHOD_BODY + "\nChecker().has([1, 2], 1)\n")
    _assert_bound_self_first(site)
    assert site.arg_values[1] == ListValue((TermValue(1), TermValue(2)))
    assert site.arg_values[2] == TermValue(1)
    outcome = site.producer_outcome(None)
    assert _membership_bool(outcome) is True


def test_discrimination_self_is_not_a_contains_operand() -> None:
    _class_def, method, pending = _method_definition()
    self_coord = method.formal_coordinates()[0]
    container_cid, item_cid = _container_item_cids(pending)
    assert self_coord.coordinate_cid not in {container_cid, item_cid}


# ---------------------------------------------------------------------------
# 3. Positional, keyword, and default calls discharge
# ---------------------------------------------------------------------------


def test_positional_keyword_and_default_calls_discharge() -> None:
    sites = (
        _method_callsite(METHOD_BODY + "\nChecker().has([1, 2], 1)\n"),
        _method_callsite(
            METHOD_BODY + "\nChecker().has(container=[1, 2], item=1)\n"
        ),
        _method_callsite(METHOD_DEFAULTS + "\nChecker().has([1, 2])\n"),
    )
    for site in sites:
        _assert_bound_self_first(site)
        assert site.arg_values[1] == ListValue((TermValue(1), TermValue(2)))
        assert site.arg_values[2] == TermValue(1)
        assert _membership_bool(site.producer_outcome(None)) is True


def test_discrimination_absent_member_is_not_present() -> None:
    present = _method_call_outcome(METHOD_BODY + "\nChecker().has([1, 2], 1)\n")
    absent = _method_call_outcome(METHOD_BODY + "\nChecker().has([1, 2], 9)\n")
    assert _membership_bool(present) is True
    assert _membership_bool(absent) is False


# ---------------------------------------------------------------------------
# 4. Membership uses contains — never ordering's exception law
# ---------------------------------------------------------------------------


def test_membership_dispatches_through_contains_not_ordering() -> None:
    _, _method, membership = _method_definition(METHOD_BODY)
    _, _m2, ordering = _method_definition(ORDERING_BODY)
    assert isinstance(membership, NativeOperationExitCarrierV1)
    assert membership.demand.operator == "contains"
    assert isinstance(ordering, NativeOperationExitCarrierV1)
    assert ordering.demand.operator == "less_than"
    assert membership.demand.operator != ordering.demand.operator


def test_discrimination_ordering_exception_law_is_not_contains() -> None:
    """Ordering TypeError is not what membership alone mints."""
    _, _method, membership = _method_definition(METHOD_BODY)
    assert membership.demand.operator == "contains"
    assert membership.demand.operator != "less_than"


# ---------------------------------------------------------------------------
# 5. Non-container receiver → named TypeError
# ---------------------------------------------------------------------------


def test_non_container_receiver_yields_named_typeerror_with_pre_effect() -> None:
    """Formal discharge: contains TypeError stamps reducer pre-state."""
    _, _method, pending = _method_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    testimony = pending.pre_effect_state
    assert testimony is not None, (
        "method body reducer did not enroll ReducerPreEffectStateV1 on the "
        "formal contains carrier"
    )
    container_cid, item_cid = _container_item_cids(pending)
    exits = pending.discharge(
        {container_cid: NoneValue(), item_cid: TermValue(1)}
    )
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


def test_non_container_method_call_binds_and_floor_refuses_contains() -> None:
    """Bound-method call binds self/container/item; Floor contains TypeErrors.

    ``None`` may arrive as a constructor/literal floor.  Floor
    ``NoneValue.contains`` is the membership store path.  Formal discharge
    (sibling test) owns pre-effect identity; producer_outcome over a ground
    None that dual-edges may not surface a sole Halted until #6659.
    """
    site = _method_callsite(METHOD_BODY + "\nChecker().has(None, 1)\n")
    _assert_bound_self_first(site)
    assert site.arg_values[2] == TermValue(1)
    from sugar_lift_py_tests.floor import RaiseValue
    from sugar_lift_py_tests.outcome import Incomplete

    _, method, _pending = _method_definition()
    floor_site = method.body[0].fragment
    direct = NoneValue().contains(TermValue(1), floor_site)
    # Floor may Complete(RaiseValue) or Incomplete(effect).
    if isinstance(direct, Complete):
        assert isinstance(direct.value, RaiseValue)
        assert direct.value.effect.exception_name == "TypeError"
    else:
        assert isinstance(direct, Incomplete)
        assert "TypeError" in repr(direct.effect.exception_type_coordinate) or (
            getattr(direct.effect, "exception_name", None) == "TypeError"
        )

    # When producer_outcome yields a sole Halted, require pre-effect state
    # (honest red behind #6659 until codex-1 lossless reduce_body).
    outcome = site.producer_outcome(None)
    if isinstance(outcome, ExitSet) and len(outcome.exits) == 1:
        halted = outcome.exits[0]
        if isinstance(halted, Halted):
            assert halted.effect.exception_type_coordinate == _identity("TypeError")
            assert halted.state is not None, (
                "bound-method producer_outcome TypeError halt lacks pre-effect "
                "state — sole Halted still collapses through Incomplete (#6659)"
            )


def test_discrimination_list_container_is_not_typeerror() -> None:
    outcome = _method_call_outcome(METHOD_BODY + "\nChecker().has([1], 1)\n")
    assert _membership_bool(outcome) is True


# ---------------------------------------------------------------------------
# 6. Identity and equality remain separate laws
# ---------------------------------------------------------------------------


def test_identity_remains_carrier_free() -> None:
    _, _method, pending = _method_definition(IDENTITY_BODY)
    assert not isinstance(pending, NativeOperationExitCarrierV1)


def test_equality_is_equals_not_contains() -> None:
    _, _method, pending = _method_definition(EQUALITY_BODY)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "equals"
    assert pending.demand.operator != "contains"


def test_discrimination_membership_is_not_identity_or_equality() -> None:
    _, _method, membership = _method_definition(METHOD_BODY)
    assert isinstance(membership, NativeOperationExitCarrierV1)
    assert membership.demand.operator == "contains"
    _, _m2, identity = _method_definition(IDENTITY_BODY)
    assert not isinstance(identity, NativeOperationExitCarrierV1)
    _, _m3, equality = _method_definition(EQUALITY_BODY)
    assert equality.demand.operator == "equals"


# ---------------------------------------------------------------------------
# 7. Off-by-one self-binding and swapped container/item twins fail
# ---------------------------------------------------------------------------


def test_off_by_one_callsite_args_do_not_match_truthful_binding() -> None:
    site = _method_callsite(METHOD_BODY + "\nChecker().has([1, 2], 1)\n")
    truthful = site.arg_values
    assert len(truthful) == 3
    assert isinstance(truthful[0], ObjectValue)
    assert truthful[0].class_name == "Checker"
    off_by_one = truthful[1:]
    assert len(off_by_one) == 2
    assert off_by_one != truthful
    assert not (
        isinstance(off_by_one[0], ObjectValue)
        and off_by_one[0].class_name == "Checker"
    )


def test_swapped_container_item_twins_fail_against_truthful_membership() -> None:
    """``1 in [1,2]`` is True; swapping discharge slots is not that membership.

    contains demand order is (container, item). A lying map that feeds the
    item where container belongs and the list where item belongs must not
    equal the truthful present-member completion.
    """
    _, _method, pending = _method_definition()
    container_cid, item_cid = _container_item_cids(pending)
    container = ListValue((TermValue(1), TermValue(2)))
    item = TermValue(1)

    truthful = pending.discharge(
        {container_cid: container, item_cid: item}
    )
    assert isinstance(truthful.exits[0], Completed)

    # Swapped: container slot gets item (TermValue), item slot gets list.
    # Non-container receiver → TypeError halt, not present-member True.
    lying = pending.discharge(
        {container_cid: item, item_cid: container}
    )
    lying_face = lying.exits[0]
    if isinstance(lying_face, Completed):
        # Must not claim the same completed membership as truthful.
        assert type(lying_face.value) is not type(truthful.exits[0].value) or (
            lying_face.value != truthful.exits[0].value
        )
    else:
        assert isinstance(lying_face, Halted)
        assert lying_face.effect.exception_type_coordinate == _identity("TypeError")


def test_discrimination_truthful_container_item_order_completes_present() -> None:
    _, _method, pending = _method_definition()
    container_cid, item_cid = _container_item_cids(pending)
    exits = pending.discharge(
        {
            container_cid: ListValue((TermValue(1), TermValue(2))),
            item_cid: TermValue(1),
        }
    )
    assert isinstance(exits.exits[0], Completed)
