"""Formal BinOp ``add`` through a bound-method receiver binding.

Concrete program:

    class Adder:
        def combine(self, left, right):
            return left + right

    Adder().combine(1, 2)

Python law: a bound method call supplies ``self`` first. That binding must not
shift ``left`` / ``right`` in the addition; self is the method binder's slot,
not a BinOp operand.

A parameter operand is not deferred to a caller (#7757, audit row NEW-1): a
binary operator is a protocol with a fallback (``__add__``, then the
reflected ``__radd__``), which no one dispatched method states, so ``left +
right`` over two parameters is the one undecided binary law's two faces.

Acceptance (each with a discrimination twin where noted):

  1. Method alone is the undecided binary two faces, never a carrier.
  2. Bound self does not shift left/right in the undecided result.
  3. Operands the frame decides complete with the correct value.
  4. Incompatible decided operands → named TypeError with the block's
     record as its state; wrong boundary retains the identical halt.
  5. Swapped-operand twins fail.
  6. BinOp does not borrow Compare's laws.

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

# The frame decides both operands: the floor's own addition answers.
DECIDED_SUM_BODY = (
    "class Adder:\n"
    "    def combine(self):\n"
    "        left = 10\n"
    "        right = 5\n"
    "        return left + right\n"
)

DECIDED_TYPEERROR_BODY = (
    "class Adder:\n"
    "    def combine(self):\n"
    "        left = None\n"
    "        right = 2\n"
    "        return left + right\n"
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
            "the add halt omitted the block's record as its state "
            "(reduce_body collapse)"
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


def _undetermined_owners(outcome) -> tuple[str, ...]:
    """The owners of the undetermined halts ``outcome`` keeps."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    assert isinstance(outcome, ExitSet), outcome
    return tuple(
        face.effect.producer_node_owner
        for face in outcome.halts()
        if type(face.effect) is UndeterminedRaiseEffect
    )


def _binary_results(root) -> list:
    """Every ``python:binary_result`` term reachable from ``root``."""
    import dataclasses

    from sugar_lift_py_tests.ir import _Ctor

    found: list = []
    seen: set[int] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, _Ctor) and node.name == "python:binary_result":
            found.append(node)
        if isinstance(node, (tuple, list)):
            stack.extend(node)
        elif dataclasses.is_dataclass(node) and not isinstance(node, type):
            stack.extend(
                getattr(node, field.name, None) for field in dataclasses.fields(node)
            )
    return found


def _undecided_addition(outcome):
    """The one undecided ``left + right`` the method alone states: its
    completed arm under its own atom, its undetermined halt, its result."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    assert not isinstance(outcome, NativeOperationExitCarrierV1), outcome
    assert isinstance(outcome, ExitSet), outcome
    (done,) = [face for face in outcome.exits if isinstance(face, Completed)]
    (halt,) = outcome.halts()
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.effect.producer_node_owner == "UndecidedBinary:+"
    assert "python:binary_op.completes" in repr(done.guard)
    # Both faces owe the undecided member: the operation was not decided.
    assert done.owed and halt.owed
    (result,) = {term for term in _binary_results(done.guard)}
    assert result.args[0].value == "+"
    return done, halt, result


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
# 1. Method alone is the undecided binary two faces
# ---------------------------------------------------------------------------


def test_method_alone_is_the_undecided_binary_two_faces() -> None:
    _, method, outcome = _method_definition()
    _done, _halt, result = _undecided_addition(outcome)
    assert tuple(term.name for term in result.args[1:3]) == ("left", "right")
    method_formals = tuple(p.name for p in method.params)
    assert method_formals[0] == "self"
    assert method_formals[1:] == ("left", "right")


def test_discrimination_method_alone_is_not_sole_completion() -> None:
    """The deleted carrier is not minted, and the two faces never collapse
    to a sole completion: the addition may raise."""
    _, _method, outcome = _method_definition()
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    assert isinstance(outcome, ExitSet)
    assert outcome.completed_value() is None
    assert outcome.halts()


# ---------------------------------------------------------------------------
# 2. Bound self does not shift left/right
# ---------------------------------------------------------------------------


def test_discrimination_self_is_not_an_add_operand() -> None:
    _class_def, _method, outcome = _method_definition()
    _done, _halt, result = _undecided_addition(outcome)
    assert "self" not in {getattr(term, "name", None) for term in result.args[1:3]}


# ---------------------------------------------------------------------------
# 3. Operands the frame decides: the floor's own addition
# ---------------------------------------------------------------------------


def test_compatible_operands_complete_with_correct_value() -> None:
    _, _method, exits = _method_definition(DECIDED_SUM_BODY)
    assert isinstance(exits.exits[0], Completed)
    assert _returned_term(exits).value == 15


def test_incompatible_operands_typeerror_with_the_block_record() -> None:
    """``None + 2``: the floor's named TypeError, leaving with the block's
    record as its state (#6659)."""
    _, _method, exits = _method_definition(DECIDED_TYPEERROR_BODY)
    halted = _only_halted(exits, require_pre_effect_state=True)
    assert halted.effect.exception_type_coordinate == _identity("TypeError")

    # Matching boundary restores the same pre-effect state.
    routed = _through_assertion_boundary(exits, "TypeError")
    completed = _only_completed(routed)
    assert completed.value is halted.state

    # Wrong boundary retains the identical effect and pre-effect state.
    retained = _through_assertion_boundary(exits, "ValueError")
    remaining = _only_halted(retained, require_pre_effect_state=True)
    assert remaining.effect is halted.effect
    assert remaining.state is halted.state


def test_swapped_operand_twins_fail_against_truthful_sum() -> None:
    """``10 + 5 == 15``; ``None + 2`` must not claim the same answer.

    The lying twin TypeErrors (or, were it to complete, not with 15).
    """
    _, _method, truthful = _method_definition(DECIDED_SUM_BODY)
    assert isinstance(truthful.exits[0], Completed)
    assert _returned_term(truthful).value == 15

    _, _m2, lying = _method_definition(DECIDED_TYPEERROR_BODY)
    lying_face = lying.exits[0]
    if isinstance(lying_face, Completed):
        assert _returned_term(lying).value != 15
    else:
        assert isinstance(lying_face, Halted)
        assert lying_face.effect.exception_type_coordinate == _identity("TypeError")


def test_binop_does_not_borrow_compare_laws() -> None:
    _, _method, add_outcome = _method_definition(METHOD_BODY)
    _, _m2, lt_outcome = _method_definition(COMPARE_BODY)
    _, _m3, eq_outcome = _method_definition(EQUALS_BODY)
    _, _m4, id_outcome = _method_definition(IDENTITY_BODY)

    for outcome in (add_outcome, lt_outcome, eq_outcome, id_outcome):
        assert not isinstance(outcome, NativeOperationExitCarrierV1)

    assert _undetermined_owners(add_outcome) == ("UndecidedBinary:+",)
    assert _undetermined_owners(lt_outcome) == ("UndecidedCompare:Lt",)
    assert _undetermined_owners(eq_outcome) == ("UndecidedCompare:Eq",)
    # Identity runs no user code: no undetermined dispatch halt.
    assert not any(
        owner.startswith(("UndecidedBinary:", "UndecidedCompare:"))
        for owner in _undetermined_owners(id_outcome)
    )


def test_discrimination_add_typeerror_is_not_less_than_halt() -> None:
    _, _method, add_outcome = _method_definition(METHOD_BODY)
    _, _m2, lt_outcome = _method_definition(COMPARE_BODY)
    # Same undecided shape, different operators — the halts are distinct.
    assert _undetermined_owners(add_outcome) != _undetermined_owners(lt_outcome)
