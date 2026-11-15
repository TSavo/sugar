"""Source try/except composes over a deferred formal native store."""

from __future__ import annotations

from frame_fresh import fresh
from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import CallSiteValue, ListValue, TermValue
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


def _returned(pending, a, i, q) -> TermValue:
    """The value the helper's row returns, discharged with ``a``, ``i`` and
    ``q``: what prove's one binder binds its carrier with at a call
    ``helper(a, i, q)``.

    A same-file call is its coordinate and edge, joined at prove (#7757
    steps 5 and 6, #8705): the call no longer digs to the floor the
    followed body returned, so the try's composition over the deferred store
    is read off the helper's own row."""
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    a_cid, i_cid, q_cid = pending.demand.operand_coordinate_cids
    outcome = pending.discharge(None, {a_cid: a, i_cid: i, q_cid: q})
    assert isinstance(outcome, ExitSet)
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    returns = [
        s for s in completed[0].value.record.statements if isinstance(s, ReturnValue)
    ]
    assert returns, completed[0].value
    returned = returns[-1].value
    assert isinstance(returned, TermValue), returned
    return returned


def _the_call(call: str) -> CallSiteValue:
    """The source call's value on its completed face: the edge, which owes
    its halt under the complement of its ``completes`` atom."""
    outcome = _call_outcome(call)
    assert [face for face in outcome.exits if isinstance(face, Halted)], outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    assert isinstance(completed[0].value, CallSiteValue), completed[0].value
    return completed[0].value


def test_try_body_retains_formal_store_as_one_deferred_carrier() -> None:
    pending = _helper_outcome()

    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"


def test_try_store_completion_bypasses_handler() -> None:
    pending = _helper_outcome()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    _the_call("helper([0], 0, 9)\n")

    returned = _returned(
        pending, fresh(ListValue, (TermValue(0),)), TermValue(0), TermValue(9)
    )
    assert returned.value == 0


def test_try_store_indexerror_routes_to_handler_without_fabricated_state() -> None:
    pending = _helper_outcome()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    testimony = pending.pre_effect_state
    assert testimony is not None
    _the_call("helper([0], 4, 9)\n")

    returned = _returned(
        pending, fresh(ListValue, (TermValue(0),)), TermValue(4), TermValue(9)
    )
    assert returned.value == 1
    empty_state = type(testimony.state)((), True, ())
    assert testimony.state is not None
    assert testimony.state is not empty_state
    assert testimony.state != fresh(ListValue, (TermValue(0),))
    assert testimony.state != fresh(ListValue, (TermValue(9),))


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
        None,
        {
            a_cid: fresh(ListValue, (TermValue(0),)),
            i_cid: TermValue(4),
            q_cid: TermValue(9),
        },
    )

    assert any(isinstance(exit_, Halted) for exit_ in retained.exits), retained
    halted = next(exit_ for exit_ in retained.exits if isinstance(exit_, Halted))
    assert pending.pre_effect_state is not None
    assert halted.state is pending.pre_effect_state.state
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
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
            None,
            {
                foreign_a: fresh(ListValue, (TermValue(0),)),
                foreign_i: TermValue(4),
                foreign_q: TermValue(9),
            },
        ).exits
        if isinstance(exit_, Halted)
    )
    assert halted.effect.occurrence_id != foreign_halt.effect.occurrence_id
