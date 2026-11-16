"""Source-defined subscript stores through authenticated callers.

A same-file call is its coordinate and edge, joined at prove (#7757 steps 5
and 6, the owner's ruling "Edge, join at prove", #8705).  The helper's store
is the one item mutation (``store_effect_sugar.item_mutation``, #7757 step
7), never a carrier waiting on the call's actuals: on a formal whose class is
an input of the helper's contract it is the dispatched ``__setitem__`` edge,
on one whose class is no input the undecided mutation (owed, its halt kept).
What the store does with a caller's actuals is the floor's own store on the
decided value the caller passes; the call owes its halt, which prove joins at
the call (#8690) with the type the contract states (#8749).
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import TermValue, TupleValue
from sugar_lift_py_tests.outcome import (
    Completed,
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

# The same store on a formal whose class is no input of ``helper``'s
# contract: ``return obj`` reads ``obj`` bare (``nodes._receiver_uses``:
# blocked), so nothing here decides ``type(obj).__setitem__``.
_UNDECIDED_HELPER = (
    "def helper(obj, key, value):\n    obj[key] = value\n    return obj\n"
)


def _stored_with_the_callers_actuals(helper):
    """``obj[key] = value`` at ``helper``'s store with what ``helper((0,),
    0, 9)`` passes: the one item mutation (``item_mutation``) on a receiver
    whose type the lift decides is the floor's own store, every face of it
    kept (#7757 step 7)."""
    from sugar_lift_py_tests.sugar.store_effect_sugar import item_mutation

    site = helper.body[0].fragment
    receiver = TupleValue((TermValue(0),))
    operands = (TermValue(0), TermValue(9))
    return item_mutation("__setitem__", receiver, operands, site, None, unit=None)


def _dispatched_call(outcome, method: str = "__setitem__"):
    """The dispatched item operation's coordinate in a helper's own proof:
    ``call:dispatch:<method>(<receiver>, <operands>..., py.class("0",
    class:<receiver>))``, read off the halt its edge owes (``python:raised(
    <call term>, <occurrence>)``)."""
    from sugar_lift_py_tests.call_symbol import call_symbol
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    assert isinstance(outcome, ExitSet), type(outcome)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == f"UnknownCallee:dispatch:{method}"
    ]
    assert len(halts) == 1, outcome
    assert f"python:dispatch:{method}" in {
        call.symbol for call in owed_calls(outcome)
    }
    raised = halts[0].effect.raised_by_call
    assert raised.name == "python:raised", raised
    call = raised.args[0]
    assert call.name == call_symbol(f"dispatch:{method}"), call
    return call


def _undecided_store(outcome) -> Halted:
    """The undecided item mutation (``undecided_item_mutation_faces``) in a
    helper's own proof: no carrier and no dispatched edge, one
    ``UndeterminedRaiseEffect`` halt owned by ``UndecidedSetitem`` kept
    with the state the store began from, and every completed face and the
    halt owing the undecided member at the store's site."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls, unanswered_call

    assert isinstance(outcome, ExitSet), type(outcome)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UndecidedSetitem"
    ]
    assert len(halts) == 1, outcome
    (halt,) = halts
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.state is not None
    assert not [
        face
        for face in outcome.halts()
        if str(face.effect.producer_node_owner).startswith("UnknownCallee:dispatch:")
    ]
    owed = unanswered_call(None, halt.effect.site)
    assert owed in owed_calls(outcome)
    assert owed in halt.owed
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    assert all(owed in face.owed for face in completed)
    assert outcome.completed_value() is None
    return halt


def test_helper_alone_retains_setitem_demand_in_projector_order() -> None:
    # Expected shape changed (#8857): ``obj``'s class is an input of
    # ``helper``'s contract, so its store is the dispatched ``__setitem__``
    # edge in the order ``type(obj).__setitem__(obj, key, value)`` takes,
    # then ``py.class("0", class:obj)``.  Expected shape changed (#7757 step
    # 7): where the class is no input the store is no carrier but the
    # undecided mutation, owed with its halt kept.
    from sugar_lift_py_tests.ir import str_const

    helper, _calls = _helper_and_calls(
        "def helper(obj, key, value):\n    obj[key] = value\n"
    )

    call = _dispatched_call(helper.sugar().desugar(None))
    assert [arg.name for arg in call.args[:3]] == ["obj", "key", "value"]
    rides = call.args[3]
    assert rides.name == "py.class"
    assert rides.args[0] == str_const("0")
    assert rides.args[1].name == "class:obj"
    assert len(call.args) == 4

    undecided, _calls = _helper_and_calls(_UNDECIDED_HELPER)
    _undecided_store(undecided.sugar().desugar(None))


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

    halted = _one_face(_stored_with_the_callers_actuals(helper))

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
    produced = _stored_with_the_callers_actuals(helper)
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
