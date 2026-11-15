"""Source-return operands flow through Compare and guarded control."""

from __future__ import annotations

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    GuardedReturn,
    ReturnValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile

SOURCE = (
    "def lower():\n"
    "    return 1\n"
    "def upper():\n"
    "    return 3\n"
    "def absent():\n"
    "    return None\n"
    "def choose(value):\n"
    "    if lower() < value:\n"
    "        return upper()\n"
    "    return lower()\n"
    "def exceptional(value):\n"
    "    if absent() < value:\n"
    "        return upper()\n"
    "    return lower()\n"
    "def identity_control(value):\n"
    "    if absent() is value:\n"
    "        return upper()\n"
    "    return lower()\n"
)


def _tree(calls: str = ""):
    context = TreeConstructionContextV1.for_source_call_construction()
    source = f"{SOURCE}\n{calls}"
    tree = SourceFile(
        (source, "source-return-compare-control.py", blake3_512_of(source.encode())),
        construction_context=context,
    )
    functions = {
        node.name: node for node in tree.nodes() if isinstance(node, FunctionDef)
    }
    return tree, context, functions


def _calls(tree, name: str):
    return tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Call) and getattr(node.func, "id", None) == name
    )


def _only_exit(outcome, kind):
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1, (
        "codex-3 source-return Compare projection left multiple control faces: "
        f"{outcome.exits!r}"
    )
    exit_ = outcome.exits[0]
    assert isinstance(exit_, kind)
    return exit_


def _return_value(outcome) -> TermValue:
    value = _only_exit(outcome, Completed).value
    if isinstance(value, CallSiteValue):
        value = value._dig_floor_or_none(None, owner="source-return-compare-control")
        assert value is not None
        entries = tuple(
            entry
            for entry in getattr(value, "statements", ())
            if isinstance(entry, (ReturnValue, GuardedReturn))
        )
        if entries:
            assert len(entries) == 1
            value = entries[0]
    while True:
        if isinstance(value, GuardedReturn):
            value = value.value
            continue
        if isinstance(value, ReturnValue):
            value = value.value
            continue
        if isinstance(value, CallSiteValue):
            projected = value._dig_floor_or_none(
                None, owner="source-return-compare-control nested return"
            )
            assert projected is not None
            value = projected
            continue
        break
    assert isinstance(value, TermValue)
    return value


def _type_error_identity():
    from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

    return TemporalContext.empty().value_for("TypeError").exception_type_identity()


def test_unrelated_source_returns_select_both_compare_branches() -> None:
    tree, _, _ = _tree("choose(2)\nchoose(0)\n")
    truthful, lying = (call.sugar().desugar(None) for call in _calls(tree, "choose"))

    assert _return_value(truthful) == TermValue(3)
    assert _return_value(lying) == TermValue(1)


def test_named_exceptional_source_return_bypasses_both_bodies_with_state() -> None:
    tree, _, _ = _tree("exceptional(2)\n")
    (call,) = _calls(tree, "exceptional")

    halted = _only_exit(call.sugar().desugar(None), Halted)
    assert halted.effect.exception_type_coordinate == _type_error_identity()
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    assert halted.state is not None


def test_symbolic_source_return_control_preserves_complementary_guards() -> None:
    tree, _, functions = _tree()
    pending = functions["choose"].sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1)

    left, right = pending.coordinates
    assert left is None
    assert right is not None
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var

    exits = pending.discharge(
        None,
        {
            right.coordinate_cid: SymbolicValue(make_var("actual_value")),
        },
    )
    # ``lower() < actual_value`` over an undecided actual is two-faced
    # (#7585): the comparison's rich method is code nobody looked at, so the
    # control completes only under ``python:compare.completes`` and halts,
    # undetermined, under the complement.  Neither face is dropped.
    from sugar_lift_py_tests.outcome.exit_set import complement_guard

    assert isinstance(exits, ExitSet)
    (completed,) = [exit_ for exit_ in exits.exits if isinstance(exit_, Completed)]
    (halted,) = exits.halts()
    assert len(exits.exits) == 2
    assert completed.guard.name == "python:compare.completes"
    assert halted.guard == complement_guard(completed.guard)
    assert halted.effect.producer_node_owner == "UndecidedCompare:Lt"
    assert halted.effect.exception_name is None
    returns = tuple(
        entry
        for entry in completed.value.record.statements
        if isinstance(entry, GuardedReturn)
    )
    assert len(returns) == 2
    assert returns[0].guards[0] == returns[1].guards[0].operands[0]


def test_identity_over_source_return_remains_carrier_free_and_total() -> None:
    _, _, functions = _tree()
    outcome = functions["identity_control"].sugar().desugar(None)

    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    assert not (
        isinstance(outcome, ExitSet)
        and any(isinstance(exit_, Halted) for exit_ in outcome.exits)
    )


