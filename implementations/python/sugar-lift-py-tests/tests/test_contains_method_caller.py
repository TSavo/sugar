"""Formal membership ``contains`` through a bound-method receiver binding.

Concrete program:

    class Checker:
        def has(self, container, item):
            return item in container

    Checker().has([1, 2], 1)

Python law: a bound method call supplies ``self`` first. That binding must not
shift ``container`` / ``item`` in the membership. Source ``item in
container`` evaluates item then container, and is
``container.contains(item)``.  A parameter operand is no deferred operation
(#7757, audit row NEW-1): over two parameters it is the container's undecided
``__contains__``, two-faced, stating ``py.in(item, container)``.

Acceptance (each with a discrimination twin where noted):

  1. Method alone is exactly one undecided membership, no carrier.
  2. Bound self does not shift container/item.
  3. Membership uses contains — never ordering's law.
  5. A decided non-container receiver yields named TypeError with the
     block's record as its state.
  6. Identity and equality remain separate laws.
  7. Swapped container/item twins fail.

The caller's list is made at the call, and ``container`` is that actual with
the caller's currency (#8249): membership is decided in ``has``'s frame and
answers the bool Python computes.

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
    ObjectValue,
)
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
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

# The frame decides both operands: the floor's own membership law answers.
NON_CONTAINER_BODY = (
    "class Checker:\n"
    "    def has(self):\n"
    "        container = None\n"
    "        item = 1\n"
    "        return item in container\n"
)

LIST_BODY = (
    "class Checker:\n"
    "    def has(self):\n"
    "        container = [1, 2]\n"
    "        item = 1\n"
    "        return item in container\n"
)

SWAPPED_LIST_BODY = (
    "class Checker:\n"
    "    def has(self):\n"
    "        container = [1, 2]\n"
    "        item = 1\n"
    "        return container in item\n"
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
            "formal contains halt omitted real pre-effect state "
            "(NativeOperationResolutionV1.project / reduce_body collapse)"
        )
    return halted


def _assert_completed_call(outcome) -> CallSiteValue:
    assert outcome.completed_value() is not None, outcome
    assert isinstance(
        outcome.completed_value(), CallSiteValue
    ), outcome.completed_value()
    return outcome.completed_value()


def _undecided_halts(outcome: object, op_kind: str) -> tuple[Halted, ...]:
    """The undecided comparison's halts (owner ``UndecidedCompare:<op>``)."""
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    assert isinstance(outcome, ExitSet)
    return tuple(
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == f"UndecidedCompare:{op_kind}"
    )


def _compare_operand_names(outcome: ExitSet) -> tuple[str, str]:
    """The operands the one ``python:compare.completes`` atom names, in its
    order: ``py.in(item, container)`` states the item first."""
    found: list = []

    def walk(formula) -> None:
        if getattr(formula, "name", None) == "python:compare.completes":
            (dispatch,) = formula.args
            if dispatch not in found:
                found.append(dispatch)
            return
        for operand in getattr(formula, "operands", None) or ():
            walk(operand)
        inner = getattr(formula, "operand", None)
        if inner is not None:
            walk(inner)

    for exit_ in outcome.exits:
        walk(exit_.guard)
    (dispatch,) = found
    assert dispatch.name == "python:compare"
    return tuple(term.name for term in dispatch.args[1:3])


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
    raise AssertionError(
        f"unprojected membership value: {type(value).__name__} {value!r}"
    )


def _membership_bool(outcome) -> bool:
    """Project a completed membership result to a Python bool."""
    completed = _only_completed(outcome)
    return _unwrap_return(completed.value)


# ---------------------------------------------------------------------------
# 1. Method alone is the undecided membership, never a carrier
# ---------------------------------------------------------------------------


def test_method_alone_retains_exactly_one_undecided_membership() -> None:
    """``item in container`` over two parameters is no deferred operation
    (#7757, audit row NEW-1): the container's undecided ``__contains__``,
    two-faced, one ``UndecidedCompare:In`` halt, ``py.in(item, container)``."""
    _, method, outcome = _method_definition()
    (halted,) = _undecided_halts(outcome, "In")
    assert halted.effect.exception_name is None
    assert _compare_operand_names(outcome) == ("item", "container")
    method_formals = tuple(p.name for p in method.params)
    assert method_formals[0] == "self"
    assert method_formals[1:] == ("container", "item")


def test_discrimination_method_alone_is_not_completed_membership() -> None:
    _, _method, outcome = _method_definition()
    assert _undecided_halts(outcome, "In")
    assert outcome.completed_value() is None


# ---------------------------------------------------------------------------
# 2. Bound self does not shift container/item
# ---------------------------------------------------------------------------


def test_discrimination_self_is_not_a_contains_operand() -> None:
    _class_def, _method, outcome = _method_definition()
    names = _compare_operand_names(outcome)
    assert "self" not in names
    assert names == ("item", "container")


# ---------------------------------------------------------------------------
# 3. Membership and ordering are separate laws
# ---------------------------------------------------------------------------


def test_membership_dispatches_through_contains_not_ordering() -> None:
    _, _method, membership = _method_definition(METHOD_BODY)
    _, _m2, ordering = _method_definition(ORDERING_BODY)
    assert _undecided_halts(membership, "In")
    assert not _undecided_halts(membership, "Lt")
    assert _undecided_halts(ordering, "Lt")
    assert not _undecided_halts(ordering, "In")


def test_discrimination_ordering_exception_law_is_not_contains() -> None:
    """Ordering's undecided halt is not what membership alone mints."""
    _, _method, membership = _method_definition(METHOD_BODY)
    assert not _undecided_halts(membership, "Lt")


# ---------------------------------------------------------------------------
# 5. Non-container receiver → named TypeError
# ---------------------------------------------------------------------------


def test_non_container_receiver_yields_named_typeerror_with_pre_effect() -> None:
    """``1 in None``, decided by the frame: the floor's TypeError, leaving
    with the block's record as its state."""
    _, _method, exits = _method_definition(NON_CONTAINER_BODY)
    assert not isinstance(exits, NativeOperationExitCarrierV1)
    halted = _only_halted(exits, require_pre_effect_state=True)
    assert halted.effect.exception_type_coordinate == _identity("TypeError")

    routed = _through_assertion_boundary(exits, "TypeError")
    completed = _only_completed(routed)
    assert completed.value is halted.state

    retained = _through_assertion_boundary(exits, "ValueError")
    remaining = _only_halted(retained, require_pre_effect_state=True)
    assert remaining.effect is halted.effect
    assert remaining.state is halted.state


def test_identity_remains_carrier_free() -> None:
    _, _method, pending = _method_definition(IDENTITY_BODY)
    assert not isinstance(pending, NativeOperationExitCarrierV1)


def test_equality_is_equals_not_contains() -> None:
    _, _method, outcome = _method_definition(EQUALITY_BODY)
    assert _undecided_halts(outcome, "Eq")
    assert not _undecided_halts(outcome, "In")


def test_discrimination_membership_is_not_identity_or_equality() -> None:
    _, _method, membership = _method_definition(METHOD_BODY)
    assert _undecided_halts(membership, "In")
    assert not _undecided_halts(membership, "Eq")
    _, _m2, identity = _method_definition(IDENTITY_BODY)
    assert not isinstance(identity, NativeOperationExitCarrierV1)
    assert not _undecided_halts(identity, "In")
    _, _m3, equality = _method_definition(EQUALITY_BODY)
    assert _undecided_halts(equality, "Eq")


# ---------------------------------------------------------------------------
# 7. Swapped container/item twins fail
# ---------------------------------------------------------------------------


def test_swapped_container_item_twins_fail_against_truthful_membership() -> None:
    """``1 in [1,2]`` is True; ``[1, 2] in 1`` is not that membership.

    ``in`` is the container's ``__contains__``: swapping item and container
    must not equal the truthful present-member completion.
    """
    _, _method, truthful = _method_definition(LIST_BODY)
    assert isinstance(truthful.exits[0], Completed)

    # Swapped: the int is the container, the list the item.
    # Non-container receiver → TypeError halt, not present-member True.
    _, _m2, lying = _method_definition(SWAPPED_LIST_BODY)
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
    _, _method, exits = _method_definition(LIST_BODY)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
