"""Source try/except composes over a deferred formal native store."""

from __future__ import annotations

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import CallSiteValue, ListValue, ReturnValue, TermValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile


HELPER = (
    "def helper(a, i, q):\n"
    "    try:\n"
    "        a[i] = q\n"
    "    except IndexError:\n"
    "        return 1\n"
    "    return 0\n"
)

PLAIN_STORE = "def helper(a, i, q):\n    a[i] = q\n"


def _tree(calls: str = "", helper: str = HELPER) -> SourceFile:
    source = f"{helper}\n{calls}"
    return SourceFile(
        (source, "try-native-store.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper_outcome(helper: str = HELPER):
    function = next(
        node for node in _tree(helper=helper).nodes() if isinstance(node, FunctionDef)
    )
    return function.sugar().desugar(None)


def _call_outcome(call: str):
    tree = _tree(call)
    node = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return node.sugar().desugar(None)


def _returned(outcome) -> TermValue:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    face = outcome.exits[0]
    assert isinstance(face, Completed)
    value = face.value
    if isinstance(value, CallSiteValue):
        value = value._dig_floor_or_none(None, owner="test_try_native_store_carrier")
    returns = tuple(entry for entry in value.statements if isinstance(entry, ReturnValue))
    assert len(returns) == 1
    assert isinstance(returns[0].value, TermValue)
    return returns[0].value


def test_try_body_retains_formal_store_as_one_deferred_carrier() -> None:
    pending = _helper_outcome()

    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"


def test_try_store_completion_bypasses_handler() -> None:
    outcome = _call_outcome("helper([0], 0, 9)\n")

    assert _returned(outcome).value == 0


def test_try_store_indexerror_routes_to_handler_without_fabricated_state() -> None:
    pending = _helper_outcome()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    testimony = pending.pre_effect_state
    assert testimony is not None

    outcome = _call_outcome("helper([0], 4, 9)\n")

    assert _returned(outcome).value == 1
    empty_state = type(testimony.state)((), True, ())
    assert testimony.state is not None
    assert testimony.state is not empty_state
    assert testimony.state != ListValue((TermValue(0),))
    assert testimony.state != ListValue((TermValue(9),))


def test_exitset_consumer_observes_authentic_store_occurrence_and_state() -> None:
    pending = _helper_outcome(PLAIN_STORE)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    a_cid, i_cid, q_cid = pending.demand.operand_coordinate_cids
    observed = []

    def observe(exits):
        halted = next(exit_ for exit_ in exits.exits if isinstance(exit_, Halted))
        observed.append((halted.effect, halted.state))
        return exits

    retained = pending.after_discharge(observe).discharge(
        {
            a_cid: ListValue((TermValue(0),)),
            i_cid: TermValue(4),
            q_cid: TermValue(9),
        }
    )

    assert any(isinstance(exit_, Halted) for exit_ in retained.exits), retained
    halted = next(exit_ for exit_ in retained.exits if isinstance(exit_, Halted))
    assert pending.pre_effect_state is not None
    assert halted.state is pending.pre_effect_state.state
    assert isinstance(halted.effect.occurrence_id, str) and ":" in halted.effect.occurrence_id, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    assert observed == [(halted.effect, halted.state)]
    foreign = _helper_outcome("\n" + PLAIN_STORE)
    assert isinstance(foreign, NativeOperationExitCarrierV1)
    foreign_a, foreign_i, foreign_q = foreign.demand.operand_coordinate_cids
    foreign_halt = next(
        exit_
        for exit_ in foreign.discharge(
            {
                foreign_a: ListValue((TermValue(0),)),
                foreign_i: TermValue(4),
                foreign_q: TermValue(9),
            }
        ).exits
        if isinstance(exit_, Halted)
    )
    assert halted.effect.occurrence_id != foreign_halt.effect.occurrence_id
