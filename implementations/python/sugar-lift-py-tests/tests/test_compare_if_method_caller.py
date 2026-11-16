"""Formal Compare-through-IfSugar through a bound-method receiver binding.

Concrete program:

    class Chooser:
        def choose(self, left, right):
            if left < right:
                return 1
            return 0

    Chooser().choose(1, 2)

Python law: a bound method call supplies ``self`` first. That binding must not
shift ``left`` / ``right`` in the ordering. A parameter operand is no deferred
operation (#7757, audit row NEW-1): ``left < right`` is the undecided
ordering's two faces through IfSugar; self is the method binder's slot, not a
compare operand.

Acceptance (each with a discrimination twin where noted):

  1. Method alone is the undecided ordering: one ``UndecidedCompare:Lt``
     halt, no carrier.
  2. Bound self does not shift left/right in the completes atom.
  3. Incompatible decided ordering → authenticated TypeError with the
     block's record as its state; matching boundary consumes; wrong boundary
     retains the halt.
  4. Identity comparison remains carrier-free and dual-edge-free.

Does not touch: reducer, carrier/ExitSet, IfSugar, Compare producers, assertion
routing, parameter-name maps, chained-comparison lane.
"""

from __future__ import annotations

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

DECIDED_BODY = (
    "class Chooser:\n"
    "    def choose(self):\n"
    "        left = None\n"
    "        right = 2\n"
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
            "(reduce_body collapse)"
        )
    return halted


def _assert_completed_call(outcome) -> CallSiteValue:
    assert outcome.completed_value() is not None, outcome
    assert isinstance(
        outcome.completed_value(), CallSiteValue
    ), outcome.completed_value()
    return outcome.completed_value()


def _ordering_halts(outcome: ExitSet) -> tuple[Halted, ...]:
    return tuple(
        exit_
        for exit_ in outcome.exits
        if isinstance(exit_, Halted)
        and exit_.effect.producer_node_owner == "UndecidedCompare:Lt"
    )


def _compare_dispatches(outcome: ExitSet) -> list:
    """Every ``python:compare(...)`` a ``python:compare.completes`` atom in
    the outcome's guards names."""
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
    return found


def _left_right_names(outcome: ExitSet) -> tuple[str, str]:
    (dispatch,) = _compare_dispatches(outcome)
    assert dispatch.name == "python:compare"
    assert dispatch.args[0].value == "Lt"
    names = tuple(term.name for term in dispatch.args[1:3])
    assert names == ("left", "right"), names
    return names


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
# 1. Method alone is the undecided ordering, never a carrier
# ---------------------------------------------------------------------------


def test_method_alone_is_the_undecided_ordering_not_a_carrier() -> None:
    """``left < right`` over two parameters is no deferred operation (#7757,
    audit row NEW-1): it completes under its own ``python:compare.completes``
    atom or raises something undetermined, one halt."""
    _, method, outcome = _method_definition()
    assert isinstance(outcome, ExitSet)
    (halted,) = _ordering_halts(outcome)
    assert halted.effect.exception_name is None
    assert _left_right_names(outcome) == ("left", "right")
    method_formals = tuple(p.name for p in method.params)
    assert method_formals[0] == "self"
    assert method_formals[1:] == ("left", "right")


def test_discrimination_method_alone_is_not_completed_branch() -> None:
    _, _method, outcome = _method_definition()
    assert isinstance(outcome, ExitSet)
    assert outcome.completed_value() is None
    assert any(isinstance(exit_, Completed) for exit_ in outcome.exits)
    assert _ordering_halts(outcome)


# ---------------------------------------------------------------------------
# 2. Bound self does not shift left/right
# ---------------------------------------------------------------------------


def test_discrimination_self_is_not_a_less_than_operand() -> None:
    _class_def, _method, outcome = _method_definition()
    (dispatch,) = _compare_dispatches(outcome)
    assert "self" not in {term.name for term in dispatch.args[1:3]}
    assert _left_right_names(outcome) == ("left", "right")


# ---------------------------------------------------------------------------
# 3. A decided incompatible ordering halts with its TypeError
# ---------------------------------------------------------------------------


def test_incompatible_ordering_typeerror_with_the_block_record_state() -> None:
    """``None < 2``, decided by the frame: the floor's TypeError, leaving
    with the block's record as its state."""
    _, _method, exits = _method_definition(DECIDED_BODY)
    halted = _only_halted(exits, require_pre_effect_state=True)
    assert halted.effect.exception_type_coordinate == _identity("TypeError")

    routed = _through_assertion_boundary(exits, "TypeError")
    completed = _only_completed(routed)
    assert completed.value is halted.state

    retained = _through_assertion_boundary(exits, "ValueError")
    remaining = _only_halted(retained, require_pre_effect_state=True)
    assert remaining.effect is halted.effect
    assert remaining.state is halted.state


def test_discrimination_ordering_is_not_identity_dual_edge_free() -> None:
    """Bite: the ordering method acquires the undecided ordering's halt; the
    identity method does not."""
    _, _method, ordering = _method_definition(METHOD_BODY)
    _, _method, identity = _method_definition(IDENTITY_BODY)
    assert _ordering_halts(ordering)
    assert not _ordering_halts(identity)


# ---------------------------------------------------------------------------
# 6. Off-by-one self-binding twin fails
# ---------------------------------------------------------------------------


