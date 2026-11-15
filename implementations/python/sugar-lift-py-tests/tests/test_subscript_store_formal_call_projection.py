"""Source-defined subscript stores discharge through authenticated callers.

A same-file call is its coordinate and edge, joined at prove (#7757 steps 5
and 6, the owner's ruling "Edge, join at prove", #8705): the helper's
``setitem`` carrier is discharged by prove's one binder with the call's
actuals, never at the call.  What the store does with a caller's actuals is
the helper's own row discharged with them; the call owes its halt, which
prove joins at the call (#8690) with the type the contract states (#8749).
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import TermValue, TupleValue
from sugar_lift_py_tests.outcome import (
    ExitSet,
    Halted,
    NativeOperationExitCarrierV1,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile


def _tree(source: str) -> SourceFile:
    return SourceFile(
        (source, "setitem_formal_call.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper_and_calls(source: str):
    tree = _tree(source)
    helper = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    calls = tuple(node for node in tree.nodes() if isinstance(node, Call))
    return helper, calls


def _one_face(outcome):
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    return outcome.exits[0]


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


class _Expected:
    def __init__(self, name: str):
        self.identity = _identity(name)

    def exception_type_identity(self):
        return self.identity


_TUPLE_CALLER = (
    "def helper(obj, key, value):\n"
    "    obj[key] = value\n\n"
    "helper((0,), 0, 9)\n"
)


def _discharged_with_the_callers_actuals(helper):
    """The helper's row discharged with what ``helper((0,), 0, 9)`` passes:
    what prove's binder binds its carrier with at that call."""
    pending = helper.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    obj_cid, key_cid, value_cid = pending.demand.operand_coordinate_cids
    return pending.discharge(
        None,
        {
            obj_cid: TupleValue((TermValue(0),)),
            key_cid: TermValue(0),
            value_cid: TermValue(9),
        },
    )


def test_helper_alone_retains_setitem_demand_in_projector_order() -> None:
    helper, _calls = _helper_and_calls(
        "def helper(obj, key, value):\n    obj[key] = value\n"
    )

    pending = helper.sugar().desugar(None)

    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"
    assert tuple(value.term.name for value in pending.operands) == (
        "obj",
        "key",
        "value",
    )
    assert pending.demand.operand_coordinate_cids == tuple(
        value.formal_coordinate.coordinate_cid for value in pending.operands
    )


# ``test_positional_keyword_and_default_callers_complete_same_store_demand``
# was deleted: it pinned the followed frame's ``source_call_frame_cid`` and
# ``formal_coordinate_cids`` on the call value and the helper's store carried
# to the caller as a write, all of which went with the body follow (#8705,
# #8739, #8751).  The three binding forms are read off the edge in
# ``test_setitem_formal_caller.test_positional_keyword_and_default_callers_complete_same_demand``.


def test_immutable_receiver_reads_but_formal_store_halts_with_named_type() -> None:
    helper, calls = _helper_and_calls(_TUPLE_CALLER)
    readable = TupleValue((TermValue(0),)).subscript(TermValue(0), "read.py:1")
    assert readable.completed_value() == TermValue(0)

    halted = _one_face(_discharged_with_the_callers_actuals(helper))

    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("TypeError")
    # The locus is the store's own ``file:line:col`` (``obj[key] = value``,
    # line 2, column 4; ``AuthenticatedRaiseLocus.of``).  It names the store,
    # never an enclosing assertion; the call it crosses is stamped where
    # prove joins it, the callee's site kept as producer (#8690).
    assert halted.effect.occurrence_id.startswith("setitem_formal_call.py:2:4")
    # The call itself owes its halt: it is the edge, two-faced.
    call_outcome = calls[-1].sugar().desugar(None)
    assert [face for face in call_outcome.exits if isinstance(face, Halted)]


def test_wrong_expected_type_leaves_setitem_exception_unconsumed() -> None:
    helper, _calls = _helper_and_calls(_TUPLE_CALLER)
    produced = _discharged_with_the_callers_actuals(helper)
    original = _one_face(produced)
    assert isinstance(original, Halted)

    routed = produced.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected("IndexError")),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )

    remaining = [
        face
        for face in routed.exits
        if isinstance(face, Halted) and face.effect is original.effect
    ]
    assert remaining == [original]
    assert remaining[0].effect.exception_type_coordinate == _identity("TypeError")
