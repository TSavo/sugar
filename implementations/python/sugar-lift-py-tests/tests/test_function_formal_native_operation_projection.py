"""Ordinary source calls discharge formal native-operation demands."""

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
    source = (
        f"def compare(left, right):\n    return left < right\n\ncompare({actuals})\n"
    )
    tree = SourceFile(
        (source, "formal_call.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def _call_outcomes(*actuals: str):
    calls = "".join(f"compare({value})\n" for value in actuals)
    source = f"def compare(left, right):\n    return left < right\n\n{calls}"
    tree = SourceFile(
        (source, "formal_calls.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    nodes = tuple(node for node in tree.nodes() if isinstance(node, Call))
    return tuple(node.sugar().desugar(None) for node in nodes)


def test_function_definition_preserves_formal_demand_until_caller_discharge() -> None:
    source = "def compare(left, right):\n    return left < right\n"
    tree = SourceFile(
        (source, "formal_definition.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))

    assert isinstance(function.sugar().desugar(None), NativeOperationExitCarrierV1)


def test_ordinary_function_call_discharge_can_complete() -> None:
    outcome = _call_outcome("1, 2")

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    assert isinstance(outcome.exits[0], Completed)


def test_ordinary_function_call_discharge_can_halt_with_named_identity() -> None:
    from sugar_lift_py_tests.ir import ctor, str_const

    outcome = _call_outcome("None, 2")

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    # Pin the positive identity — `is not None` is a weak tooth under a name
    # that promises TypeError from None < int.
    type_error = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("TypeError")],
    )
    assert halted.effect.exception_type_coordinate == type_error
    assert halted.effect.exception_name == "TypeError"
    assert isinstance(halted.effect.occurrence_id, str) and ":" in halted.effect.occurrence_id, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )


def test_swapped_actuals_retain_the_operation_coordinate() -> None:
    forward, swapped = _call_outcomes("None, 2", "2, None")

    forward_halt = forward.exits[0]
    swapped_halt = swapped.exits[0]
    assert isinstance(forward_halt, Halted)
    assert isinstance(swapped_halt, Halted)
    assert forward_halt.effect.occurrence_id == swapped_halt.effect.occurrence_id


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
    assert not isinstance(outcome, ExitSet)
