"""A comparison over parameters, and the source calls of its function."""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.outcome import (
    Completed,
    ExitSet,
    Halted,
    NativeOperationExitCarrierV1,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile


def _call_outcome(actuals: str):
    """``compare({actuals})`` in a caller's body, reduced alone.  The call
    sits in a function body so its callee name reads ``compare``'s ``def``
    (``SourceUnit.function_definition_for_read``): a call the module body
    runs is answered as the module-level read is, not at all, the
    unanswered call (#9007 decision 1)."""
    source = (
        "def compare(left, right):\n    return left < right\n\n"
        f"def caller():\n    return compare({actuals})\n"
    )
    tree = SourceFile(
        (source, "formal_call.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def _call_outcomes(*actuals: str):
    """Each ``compare(<actuals>)`` in its own caller's body (``_call_outcome``),
    each call reduced alone."""
    calls = "".join(
        f"def caller_{index}():\n    return compare({value})\n"
        for index, value in enumerate(actuals)
    )
    source = f"def compare(left, right):\n    return left < right\n\n{calls}"
    tree = SourceFile(
        (source, "formal_calls.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    nodes = tuple(node for node in tree.nodes() if isinstance(node, Call))
    return tuple(node.sugar().desugar(None) for node in nodes)


def test_function_definition_is_the_undecided_ordering_two_faces() -> None:
    """``left < right`` over two parameters waits on no caller (#7757, audit
    row NEW-1): the rich method then its reflection is no one dispatched
    method, so the definition states the undecided ordering's two faces."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    source = "def compare(left, right):\n    return left < right\n"
    tree = SourceFile(
        (source, "formal_definition.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))

    outcome = function.sugar().desugar(None)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    assert isinstance(outcome, ExitSet)
    (halted,) = outcome.halts()
    assert type(halted.effect) is UndeterminedRaiseEffect
    assert halted.effect.producer_node_owner == "UndecidedCompare:Lt"
    (completed,) = (exit_ for exit_ in outcome.exits if isinstance(exit_, Completed))
    assert "python:compare.completes" in repr(completed.guard)
    assert "TypeError" not in repr(outcome)


def _edge(outcome):
    """#7757 step 5 (#8705, "Edge, join at prove"): a call of a same-file def
    is its coordinate and edge, the one unanswered call -- it completes under
    its ``python:unknown_callee_call.completes`` atom and halts under the
    complement naming nothing -- never ``compare``'s body applied to the
    actuals.  ``compare``'s undecided ordering over its formals (its
    contract) is what prove joins; whether ``None < 2`` raises ``TypeError`` is decided there.
    Before #8705 these tests read the completion and the named ``TypeError``
    off the body applied at the call."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 2
    (completed,) = (exit_ for exit_ in outcome.exits if isinstance(exit_, Completed))
    (halted,) = outcome.halts()
    assert isinstance(halted, Halted)
    assert completed.guard.name == "python:unknown_callee_call.completes"
    assert type(halted.effect) is UndeterminedRaiseEffect
    assert halted.effect.exception_name is None
    assert "TypeError" not in repr(outcome)
    call = completed.value.term.args[0]
    assert call.name.startswith("call:")
    return call, halted


def test_a_call_python_completes_is_its_coordinate_and_edge() -> None:
    _edge(_call_outcome("1, 2"))


def test_a_call_python_raises_at_is_its_coordinate_and_edge() -> None:
    _edge(_call_outcome("None, 2"))


def test_swapped_actuals_are_carried_in_order_by_each_call() -> None:
    forward, swapped = _call_outcomes("None, 2", "2, None")

    forward_call, forward_halt = _edge(forward)
    swapped_call, swapped_halt = _edge(swapped)
    # Each call is its own coordinate: the swapped actuals are carried in
    # order, and each call is its own occurrence.
    assert forward_call.name == swapped_call.name
    # The two actuals, then the class of the ``int`` actual keyed by its
    # position (#8857, ``receiver_dispatch.class_arguments``): ``None``
    # supplies none.
    assert len(forward_call.args) == len(swapped_call.args) == 3
    assert tuple(forward_call.args[:2]) == tuple(reversed(tuple(swapped_call.args[:2])))
    assert forward_call.args[2] == _int_class("1")
    assert swapped_call.args[2] == _int_class("0")
    assert forward_halt.effect.occurrence_id != swapped_halt.effect.occurrence_id


def _int_class(key: str):
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.receiver_dispatch import (
        CLASS_ARGUMENT,
        builtin_class_term,
    )

    return ctor(CLASS_ARGUMENT, [str_const(key), builtin_class_term("int")])


def test_shadowed_function_name_does_not_borrow_module_definition() -> None:
    source = (
        "def compare(left, right):\n"
        "    return left < right\n\n"
        "def caller(compare):\n"
        "    return compare(None, 2)\n"
    )
    tree = SourceFile(
        (source, "shadowed_caller.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]

    outcome = call.sugar().desugar(None)
    # ``compare`` here is ``caller``'s formal: what it calls is not decided
    # in this frame.  The call is the one undecided call -- it completes or
    # raises something undetermined -- and nothing of the module's
    # ``compare`` is read: no ``TypeError`` from ``None < 2`` is named.
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    assert isinstance(outcome, ExitSet)
    (completed,) = (exit_ for exit_ in outcome.exits if isinstance(exit_, Completed))
    (halted,) = outcome.halts()
    assert len(outcome.exits) == 2
    assert "python:unknown_callee_call.completes" in repr(completed.guard)
    assert type(halted.effect) is UndeterminedRaiseEffect
    assert halted.effect.producer_node_owner == "UnknownCallee:compare"
    assert halted.effect.exception_name is None
    assert "TypeError" not in repr(outcome)
