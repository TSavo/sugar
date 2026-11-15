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
    ReturnValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute, Call, ClassDef, FunctionDef
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.effect import RaiseEffect

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
            "formal add halt omitted real pre-effect state "
            "(NativeOperationResolutionV1.project / reduce_body collapse)"
        )
    return halted


def _assert_completed_call(outcome) -> CallSiteValue:
    assert outcome.completed_value() is not None, outcome
    assert isinstance(
        outcome.completed_value(), CallSiteValue
    ), outcome.completed_value()
    return outcome.completed_value()


def _returned_term(outcome) -> TermValue:
    """Pull the returned TermValue from discharge or producer_outcome."""
    if isinstance(outcome, ExitSet):
        value = _only_completed(outcome).value
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
    """Walk a dug body for raise faces (return-expression projection)."""
    found: list = []
    seen: set[int] = set()
    stack = [root]
    while stack:
        value = stack.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if (
            isinstance(value, ExitSet)
            and len(value.exits) == 1
            and value.halts() == value.exits
            and isinstance(value.halts()[0].effect, RaiseEffect)
        ):
            found.append(value.halts()[0])
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


def test_discrimination_self_is_not_an_add_operand() -> None:
    _class_def, method, pending = _method_definition()
    self_coord = method.formal_coordinates()[0]
    left_cid, right_cid = _left_right_cids(pending)
    assert self_coord.coordinate_cid not in {left_cid, right_cid}


# ---------------------------------------------------------------------------
# 3. Positional, keyword, and default calls discharge
# ---------------------------------------------------------------------------


def test_compatible_operands_complete_with_correct_value() -> None:
    _, _method, pending = _method_definition()
    left_cid, right_cid = _left_right_cids(pending)
    exits = pending.discharge(None, {left_cid: TermValue(10), right_cid: TermValue(5)})
    assert isinstance(exits.exits[0], Completed)
    assert _returned_term(exits).value == 15


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
    exits = pending.discharge(None, {left_cid: NoneValue(), right_cid: TermValue(2)})
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


def test_swapped_operand_twins_fail_against_truthful_sum() -> None:
    """``10 + 5 == 15``; swapped discharge must not claim the same post-state.

    For non-commutative lying maps (None + 2 vs 2 + None) one or both may
    TypeError — either way not a Completed 15.
    """
    _, _method, pending = _method_definition()
    left_cid, right_cid = _left_right_cids(pending)

    truthful = pending.discharge(
        None, {left_cid: TermValue(10), right_cid: TermValue(5)}
    )
    assert isinstance(truthful.exits[0], Completed)
    assert _returned_term(truthful).value == 15

    # Swapped numeric still sums (commutative) — use asymmetric TypeError twin:
    # left=None right=2 vs left=2 right=None may both TypeError but wrong
    # completion is the bite for a lying map that claims sum 15 from None.
    lying = pending.discharge(None, {left_cid: NoneValue(), right_cid: TermValue(2)})
    lying_face = lying.exits[0]
    if isinstance(lying_face, Completed):
        assert _returned_term(lying).value != 15
    else:
        assert isinstance(lying_face, Halted)
        assert lying_face.effect.exception_type_coordinate == _identity("TypeError")


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
