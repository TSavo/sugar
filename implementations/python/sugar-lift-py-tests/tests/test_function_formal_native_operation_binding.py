"""Formal native operations use the one Python call binder.

#7757 step 5 (#8705, the owner's ruling "Edge, join at prove"): a call of a
same-file def is its coordinate and edge, never the callee's body applied to
its actuals.  ``helper``'s contract states its one undecided ``left +
right`` over its formals (two faces, #7757 audit row NEW-1); each call carries its binding in its call term exactly as
prove's one binder (``consistency::bind_call_arguments``) binds that
contract: a positional actual as written, a keyword as ``py.kwarg``, an
omitted defaulted formal as ``py.default`` with the value its ``def``
statement bound.  Whether ``None + 2`` raises ``TypeError`` is decided at
prove, where the join binds the actuals; nothing of it is named at the call.

Deleted with the body-following application (#8705), which they measured:
``test_wrong_boundary_type_leaves_named_binary_exception_unconsumed`` (a
``TypeError`` named at the call reaching a ``ValueError`` boundary) and
``test_keyword_and_default_calls_can_complete_from_the_existing_floor`` (a
completion decided at the call).
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.ir import str_const
from sugar_lift_py_tests.outcome import (
    ExitSet,
    Halted,
)
from sugar_lift_py_tests.unanswered_calls import owed_calls
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile


def _tree(source: str) -> SourceFile:
    return SourceFile(
        (source, "formal_binding.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _call_outcome(signature: str, actuals: str):
    (outcome,) = _call_outcomes(signature, actuals)
    return outcome


def _call_outcomes(signature: str, *actuals: str):
    """Each ``helper(<actuals>)`` reduced where it runs: in ``caller``'s
    body, so after import. A default is evaluated once, by the ``def``
    statement (#8031): a call reads the value the module run bound under
    its key (``with_module_final_globals``, ``DefaultValueSugar``). A
    module-level call reduced alone is no part of any module run -- no
    statement bound the key -- and is refused by name; it was the deleted
    call-time evaluation of the default that let it complete."""
    calls = "".join(f"    helper({value})\n" for value in actuals)
    source = (
        f"def helper({signature}):\n"
        "    return left + right\n\n\n"
        f"def caller():\n{calls}"
    )
    tree = _tree(source)
    nodes = tuple(node for node in tree.nodes() if isinstance(node, Call))
    return tuple(node.sugar().desugar(None) for node in nodes)


def _call_term(outcome):
    """The call's coordinate ``call:<target>(<arguments>)``: the one
    unanswered call, completing under its ``python:unknown_callee_call.
    completes`` atom and halting under the complement naming nothing."""
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 2
    (halted,) = outcome.halts()
    assert isinstance(halted, Halted)
    assert halted.effect.exception_name is None
    assert halted.effect.exception_type_coordinate is None
    (completed,) = (face for face in outcome.exits if face is not halted)
    assert completed.guard.name == "python:unknown_callee_call.completes"
    result = completed.value.term
    assert result.name == "python:call_result"
    call = result.args[0]
    assert call.name.startswith("call:")
    return call


def _int_class(key: str):
    """``py.class(<key>, python:builtin("int"))``: the class of an ``int``
    actual the caller decides, keyed by the argument it is, after the
    actuals (#8857, ``receiver_dispatch.class_arguments``).  ``None`` and a
    default supply none."""
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.receiver_dispatch import (
        CLASS_ARGUMENT,
        builtin_class_term,
    )

    return ctor(CLASS_ARGUMENT, [str_const(key), builtin_class_term("int")])


def test_positional_actuals_discharge_through_python_binder() -> None:
    call = _call_term(_call_outcome("left, right", "None, 2"))
    assert len(call.args) == 3
    actuals = call.args[:2]
    assert not any(str(getattr(arg, "name", "")).startswith("py.") for arg in actuals)
    assert call.args[2] == _int_class("1")


def test_keyword_actuals_discharge_through_python_binder() -> None:
    call = _call_term(_call_outcome("left, right", "left=None, right=2"))
    assert [arg.name for arg in call.args] == ["py.kwarg", "py.kwarg", "py.class"]
    assert [arg.args[0] for arg in call.args[:2]] == [
        str_const("left"),
        str_const("right"),
    ]
    assert call.args[2] == _int_class("right")


def test_default_actual_is_keyed_to_its_formal_coordinate() -> None:
    call = _call_term(_call_outcome("left, right=2", "None"))
    _actual, default = call.args
    assert default.name == "py.default"
    assert default.args[0] == str_const("right")


def test_helper_alone_is_the_undecided_binary_two_faces() -> None:
    """``left + right`` over two parameters waits on no caller (#7757, audit
    row NEW-1): ``__add__`` then the reflected ``__radd__`` is no one
    dispatched method, so it is the one undecided binary law's two faces,
    over the formals' own terms."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    source = "def helper(left, right=2):\n    return left + right\n"
    function = next(
        node for node in _tree(source).nodes() if isinstance(node, FunctionDef)
    )
    outcome = function.sugar().desugar(None)

    assert isinstance(outcome, ExitSet)
    (halted,) = outcome.halts()
    assert type(halted.effect) is UndeterminedRaiseEffect
    assert halted.effect.producer_node_owner == "UndecidedBinary:+"
    (completed,) = (face for face in outcome.exits if face is not halted)
    assert "python:binary_op.completes" in repr(completed.guard)
    assert "python:binary_result" in repr(completed.guard)


def test_positional_keyword_and_default_calls_reach_the_same_binary_demand() -> None:
    """Three calls, one callee: the same target, ``right`` bound by
    position, by keyword and by its default, each call its own coordinate."""
    positional, keyword, default = (
        _call_term(outcome)
        for outcome in _call_outcomes(
            "left, right=2", "None, 2", "None, right=2", "None"
        )
    )

    assert len({positional.name, keyword.name, default.name}) == 1
    none_actual, two_actual, two_class = positional.args
    assert two_class == _int_class("1")
    assert keyword.args[0] == none_actual == default.args[0]
    assert keyword.args[1].name == "py.kwarg"
    assert keyword.args[1].args[1] == two_actual
    assert keyword.args[2] == _int_class("right")
    assert len(keyword.args) == 3
    # A default's value is the ``def`` statement's; no class rides for it.
    assert len(default.args) == 2
    assert default.args[1].name == "py.default"


def test_helper_alone_owes_the_undecided_member_and_never_completes_alone() -> None:
    """No actual answers the operation in the helper's own proof: it owes
    the undecided member on both faces and is never a sole completion."""
    source = "def helper(left, right):\n    return left + right\n"
    function = next(
        node for node in _tree(source).nodes() if isinstance(node, FunctionDef)
    )
    outcome = function.sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    assert owed_calls(outcome)
    assert all(face.owed for face in outcome.exits)
    assert outcome.completed_value() is None
