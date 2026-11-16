"""Vertical completion: a ``setitem`` on a formal through the one item mutation.

Python semantic law made constructible:

  For ``helper(obj, key, value)`` whose body is ``obj[key] = value``, the store
  dispatches ``__setitem__`` — a different method and obligation from the load
  path.  Helper alone stays owed.  An ordinary source caller (positional,
  keyword, or default) supplies authenticated actuals; the store on what the
  caller passes projects Completed field stores or named exceptional faces
  whose origin is Floor ``setitem``, never an enclosing boundary type.

Every item store is the one item mutation (``store_effect_sugar.
item_mutation``, #7757 step 7), never a carrier waiting on a caller's
actuals:

  - ``obj`` above is stored into and used no other way, so its class is an
    input of ``helper``'s contract (#8857) and the store is the dispatched
    ``__setitem__`` edge, ``type(obj).__setitem__(obj, key, value)``,
    answered at prove by the class each caller binds (``list.__setitem__``'s
    law, #8864); a caller supplies ``py.class("0", python:builtin("list"))``
    for a list it built.
  - Where ``obj``'s class is no input (``UNDECIDED_SOURCE``: ``return obj``
    reads it bare) nothing decides ``type(obj).__setitem__``: the store is
    the undecided mutation, completing under its own atom or raising
    something undetermined, both faces owing it.
  - On a receiver whose type the lift decides (the list a caller built) it
    is the floor's own store, every face kept; the floor tests below read it
    through the same door (``_stored``).

Source evaluation order is independent of the store's operand order:

  Python evaluates RHS, then receiver, then index.
  The store reads receiver, index, value.
"""

from __future__ import annotations

from dataclasses import dataclass

from frame_fresh import fresh
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import ListValue, TermValue, TupleValue
from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.store_effect_sugar import SubscriptStoreEffectSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile

# The store on a formal whose class is no input of ``helper``'s contract:
# ``return obj`` reads ``obj`` bare (``nodes._receiver_uses``: blocked).
UNDECIDED_SOURCE = (
    "def helper(obj, key, value):\n    obj[key] = value\n    return obj\n"
)


def _tree(source: str, name: str = "setitem_caller.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper_definition():
    """``helper`` alone and its own proof's reduction.

    ``obj`` is stored into and used no other way, so its class is an input
    of ``helper``'s contract (``nodes._receiver_class_parameters``) and
    ``obj[key] = value`` is ``type(obj).__setitem__(obj, key, value)``: the
    dispatched edge (``receiver_dispatch.dispatch_edge_call``, #8857), owed
    as it stands, resolved at prove at the class each caller binds (a
    builtin ``list`` takes its law, ``consistency::builtin_dispatch_answer``,
    #8864)."""
    source = "def helper(obj, key, value):\n    obj[key] = value\n"
    tree = _tree(source, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _undecided_definition():
    """``UNDECIDED_SOURCE`` alone and its own proof's reduction: the store on
    a formal whose class is no input is the undecided mutation."""
    tree = _tree(UNDECIDED_SOURCE, "helper_undecided.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _dispatched_call(outcome, method: str = "__setitem__"):
    """The dispatched item operation's coordinate in a helper's own proof:
    ``call:dispatch:<method>(<receiver>, <operands>..., py.class("0",
    class:<receiver>))``, read off the halt its edge owes (``python:raised(
    <call term>, <occurrence>)``), under the owner every unanswered call's
    halt names."""
    from sugar_lift_py_tests.call_symbol import call_symbol
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    assert isinstance(outcome, ExitSet), type(outcome)
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
    halt owing the undecided member at the store's site -- owed, never a
    completion."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls, unanswered_call

    assert isinstance(outcome, ExitSet), type(outcome)
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


def _class_input(call, receiver: str) -> None:
    """The dispatched call's receiver class rides last, as the class input
    of the receiver's parameter: ``py.class("0", class:<receiver>)``."""
    from sugar_lift_py_tests.ir import str_const

    rides = call.args[-1]
    assert rides.name == "py.class", rides
    assert rides.args[0] == str_const("0")
    assert rides.args[1].name == f"class:{receiver}", rides


def _caller_edge(signature: str, actuals: str):
    """``helper({actuals})`` in a caller's body, read off the caller's
    contract row (``function_universe_outcome``).

    A same-file call is its coordinate and edge, joined at prove (#7757
    steps 5 and 6, #8705): the helper's store never waits on the call's
    actuals.  The call completes under its ``completes`` atom and halts
    under the complement (the halts the helper's contract states reach the
    caller at prove, #8690, #8749).  Returns the call value the row's one
    completed face returns."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    source = (
        f"def helper({signature}):\n"
        "    obj[key] = value\n\n"
        f"def caller():\n    return helper({actuals})\n"
    )
    tree = _tree(source)
    caller = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "caller"
    )
    outcome = function_universe_outcome(caller)
    assert [face for face in outcome.exits if isinstance(face, Halted)], outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    returns = [
        s for s in completed[0].value.record.statements if isinstance(s, ReturnValue)
    ]
    assert returns, completed[0].value
    edge = returns[-1].value
    assert isinstance(edge, CallSiteValue), type(edge)
    return edge


def _coordinate(edge):
    """The call's coordinate ``call:<target>(<arguments>)`` the edge's value
    names: the completed face of the one unanswered call returns
    ``python:call_result(<call term>, <occurrence>)`` (#7757 steps 5 and 6,
    #8705), so the arguments prove's binder binds are the call term's,
    never the result's."""
    result = edge.term
    assert result.name == "python:call_result", result
    call = result.args[0]
    assert call.name.startswith("call:"), call
    return call


def _int(edge, value: int):
    return TermValue(value).to_term(owner=str(edge.site))


def _named(edge, kind: str, name: str, value: int):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(kind, [str_const(name), _int(edge, value)])


def _class(key: str, name: str):
    """``py.class(<key>, python:builtin("<name>"))``: the class of an actual
    the caller decides, after the actuals (#8857)."""
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.receiver_dispatch import (
        CLASS_ARGUMENT,
        builtin_class_term,
    )

    return ctor(CLASS_ARGUMENT, [str_const(key), builtin_class_term(name)])


def _stored(receiver, key, value):
    """``obj[key] = value`` at ``helper``'s store with ``receiver``, ``key``
    and ``value`` a caller passes: the one item mutation (``item_mutation``)
    on a receiver whose type the lift decides is the floor's own store,
    every face of it kept (#7757 step 7)."""
    from sugar_lift_py_tests.sugar.store_effect_sugar import item_mutation

    function, _outcome = _helper_definition()
    site = function.body[0].fragment
    return item_mutation("__setitem__", receiver, (key, value), site, None, unit=None)


def _assert_named_halt(outcome, name: str) -> Halted:
    """The store is one halt, raising the builtin ``name``."""
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity(name)
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    return halted


def _stored_list(completed_face) -> ListValue:
    """Pull the store post-state list out of a completion: the floor's own
    post, or a function universe's."""
    assert isinstance(completed_face, Completed)
    if isinstance(completed_face.value, ListValue):
        return completed_face.value
    record = getattr(completed_face.value, "record", None)
    assert record is not None
    lists = [s for s in record.statements if isinstance(s, ListValue)]
    assert len(lists) == 1, lists
    return lists[0]


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


# ---------------------------------------------------------------------------
# Helper alone → owed, never completed
# ---------------------------------------------------------------------------


def test_helper_alone_is_undischarged_setitem_carrier() -> None:
    # Expected shape changed (#8857): the store on a formal whose class is an
    # input is the dispatched ``__setitem__`` edge, owed (never completed
    # here) with its halt kept.  Expected shape changed (#7757 step 7):
    # where the class is no input the store is no carrier but the undecided
    # mutation, owed with its halt kept.
    _, outcome = _helper_definition()
    call = _dispatched_call(outcome)
    assert [arg.name for arg in call.args[:3]] == ["obj", "key", "value"]
    _class_input(call, "obj")
    assert len(call.args) == 4
    # The edge completes under its own ``completes`` atom and halts under
    # the complement: both faces stand, neither is chosen here.
    assert [face for face in outcome.exits if isinstance(face, Completed)]

    _, undecided = _undecided_definition()
    _undecided_store(undecided)


def test_missing_caller_actual_is_undischarged_not_completed() -> None:
    """With no caller's actual the store is owed, never a fabricated
    completion: the dispatched edge owes its member, the undecided mutation
    its own (#7825)."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    _, outcome = _helper_definition()
    _dispatched_call(outcome)
    assert owed_calls(outcome)
    assert outcome.completed_value() is None

    _, undecided = _undecided_definition()
    _undecided_store(undecided)


def test_partial_caller_actual_is_undischarged_discrimination() -> None:
    """Positive twin: the store on all three of a caller's actuals completes;
    discrimination: the store whose receiver nothing decides stays owed."""
    completed = _stored(fresh(ListValue, (TermValue(0),)), TermValue(0), TermValue(9))
    assert isinstance(completed.exits[0], Completed)

    _, undecided = _undecided_definition()
    _undecided_store(undecided)


# ---------------------------------------------------------------------------
# No carrier: the store's operand order is the dispatched call's
# ---------------------------------------------------------------------------


def test_item_store_mints_no_setitem_carrier() -> None:
    """The ``setitem`` carrier, its mint and its projector are gone (#7757
    step 7): an item store is the one item mutation, whatever its operands
    are.  The dispatched edge takes ``type(obj).__setitem__(obj, key,
    value)``'s order, the receiver first as a plain function bound to an
    instance takes it."""

    assert not hasattr(SubscriptStoreEffectSugar, "mint_setitem_carrier")
    assert not hasattr(SubscriptStoreEffectSugar, "project_setitem")
    _, outcome = _helper_definition()
    call = _dispatched_call(outcome)
    assert [arg.name for arg in call.args[:3]] == ["obj", "key", "value"]


# ``test_mint_setitem_carrier_producer_contract`` and
# ``test_mint_setitem_carrier_rejects_no_formal_coordinate`` were deleted:
# their only subject was ``SubscriptStoreEffectSugar.mint_setitem_carrier``,
# deleted with the carrier (#7757 step 7); the deletion is pinned by
# ``test_item_store_mints_no_setitem_carrier``.


# ---------------------------------------------------------------------------
# Mutable receiver → Completed (positive + discrimination)
# ---------------------------------------------------------------------------


def test_mutable_receiver_completes_store_via_setitem() -> None:
    exits = _stored(
        fresh(ListValue, (TermValue(0), TermValue(1))), TermValue(0), TermValue(9)
    )
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    assert _stored_list(exits.exits[0]) == fresh(
        ListValue, (TermValue(9), TermValue(1))
    )


def test_positional_keyword_and_default_callers_complete_same_demand() -> None:
    # Expected value changed (#7757 steps 5 and 6, #8705): the call no
    # longer carries what the followed helper did to the caller's list; it is
    # its coordinate and edge, and each form carries the same binding in the
    # form prove's one binder reads it in.
    positional = _caller_edge("obj, key, value", "[0], 0, 9")
    keyword = _caller_edge("obj, key, value", "obj=[0], key=0, value=9")
    default = _caller_edge("obj, key=0, value=9", "[0]")
    for edge in (positional, keyword, default):
        _binds, receiver = peel_walrus_binds(edge.arg_values[0])
        assert isinstance(receiver, ListValue), receiver
        assert receiver.elements == (TermValue(0),)
    # After the actuals ride the classes the caller decides (#8857): the
    # ``[0]`` it built is a ``list`` -- what ``helper``'s ``class:obj`` binds
    # at prove, so the builtin ``list.__setitem__`` law answers the
    # dispatched store (#8864) -- and each supplied ``int`` an ``int``; a
    # default supplies none.
    assert list(_coordinate(positional).args[1:]) == [
        _int(positional, 0),
        _int(positional, 9),
        _class("0", "list"),
        _class("1", "int"),
        _class("2", "int"),
    ]
    assert list(_coordinate(keyword).args[1:]) == [
        _named(keyword, "py.kwarg", "key", 0),
        _named(keyword, "py.kwarg", "value", 9),
        _class("obj", "list"),
        _class("key", "int"),
        _class("value", "int"),
    ]
    assert list(_coordinate(default).args[1:]) == [
        _named(default, "py.default", "key", 0),
        _named(default, "py.default", "value", 9),
        _class("0", "list"),
    ]


def test_discrimination_wrong_cell_is_not_the_completed_store() -> None:
    """Positive stores at key 0; discrimination at key 1 must not match."""
    base = fresh(ListValue, (TermValue(0), TermValue(1)))
    positive = _stored(base, TermValue(0), TermValue(9))
    other = _stored(base, TermValue(1), TermValue(9))
    assert isinstance(positive.exits[0], Completed)
    assert isinstance(other.exits[0], Completed)
    pos_list = _stored_list(positive.exits[0])
    other_list = _stored_list(other.exits[0])
    assert pos_list != other_list
    assert pos_list == fresh(ListValue, (TermValue(9), TermValue(1)))
    assert other_list == fresh(ListValue, (TermValue(0), TermValue(9)))


# ---------------------------------------------------------------------------
# Invalid index / immutable receiver → named exceptional exit
# ---------------------------------------------------------------------------


def test_invalid_index_halts_with_named_indexerror() -> None:
    exits = _stored(fresh(ListValue, (TermValue(0),)), TermValue(4), TermValue(9))
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )


def test_discrimination_valid_index_is_not_indexerror() -> None:
    """Positive twin of IndexError: in-range store completes."""
    exits = _stored(fresh(ListValue, (TermValue(0),)), TermValue(0), TermValue(9))
    assert isinstance(exits.exits[0], Completed)
    assert not isinstance(exits.exits[0], Halted)


def test_immutable_receiver_halts_with_named_typeerror() -> None:
    # Readable but not settable.
    readable = TupleValue((TermValue(0),)).subscript(TermValue(0), "read.py:1")
    assert readable.completed_value() == TermValue(0)

    # The store on the tuple a caller passes halts with the named TypeError;
    # at a call that halt is the helper's panic locus, joined at prove
    # (#7757 steps 5 and 6, #8690).
    halted = _assert_named_halt(
        _stored(TupleValue((TermValue(0),)), TermValue(0), TermValue(9)),
        "TypeError",
    )
    assert "assertion" not in halted.effect.occurrence_id


def test_discrimination_list_receiver_is_not_typeerror() -> None:
    """Positive twin of immutable TypeError: list completes."""
    face = _stored(
        fresh(ListValue, (TermValue(0),)), TermValue(0), TermValue(9)
    ).exits[0]
    assert isinstance(face, Completed)
    assert not isinstance(face, Halted)


def test_source_caller_indexerror_halts_with_named_identity() -> None:
    # ``[0][4] = 9`` raises IndexError: the store on what the source caller
    # passes.  The call itself is the edge carrying ``[0], 4, 9`` and owes
    # its halt (#8705); prove joins the IndexError.
    _assert_named_halt(
        _stored(fresh(ListValue, (TermValue(0),)), TermValue(4), TermValue(9)),
        "IndexError",
    )
    edge = _caller_edge("obj, key, value", "[0], 4, 9")
    assert list(_coordinate(edge).args[1:]) == [
        _int(edge, 4),
        _int(edge, 9),
        _class("0", "list"),
        _class("1", "int"),
        _class("2", "int"),
    ]


# ---------------------------------------------------------------------------
# Swapped key/value operands rejected
# ---------------------------------------------------------------------------


def test_swapped_key_value_coordinates_rejected_against_truthful_store() -> None:
    """A lying store (index/value swapped) must not equal the truthful
    post-state.

    A generic splat would hide this: both orders invoke ``setitem`` without
    TypeError.  The store's explicit operand order makes the lying face
    distinguishable.
    """
    base = fresh(ListValue, (TermValue(0), TermValue(1), TermValue(2)))
    truthful_exits = _stored(base, TermValue(1), TermValue(99))
    # LYING store: index and value swapped relative to ``obj[key] = value``.
    lying_exits = _stored(base, TermValue(99), TermValue(1))

    assert isinstance(truthful_exits.exits[0], Completed)
    truthful_list = _stored_list(truthful_exits.exits[0])
    assert truthful_list == fresh(
        ListValue, (TermValue(0), TermValue(99), TermValue(2))
    )
    lying_face = lying_exits.exits[0]
    if isinstance(lying_face, Completed):
        # Compare the ListValue post-state when completed, else accept a
        # named halt.
        lying_value = lying_face.value
        if isinstance(lying_value, ListValue):
            assert lying_value != truthful_list
        else:
            assert _stored_list(lying_face) != truthful_list
    else:
        assert isinstance(lying_face, Halted)


def test_discrimination_truthful_order_completes_at_correct_cell() -> None:
    """Positive twin of the swapped lying arm."""
    exits = _stored(
        fresh(ListValue, (TermValue(0), TermValue(1), TermValue(2))),
        TermValue(1),
        TermValue(99),
    )
    assert isinstance(exits.exits[0], Completed)
    assert _stored_list(exits.exits[0]) == fresh(
        ListValue, (TermValue(0), TermValue(99), TermValue(2))
    )


# ---------------------------------------------------------------------------
# Source evaluation order ≠ the store's operand order
# ---------------------------------------------------------------------------


def test_source_evaluation_order_independent_of_discharge_order() -> None:
    """Python eval (value, receiver, index) is not the setitem call order.

    Source producers evaluate value first, then the target's receiver, then
    the index.  The store still reads ``receiver, index, value`` because the
    method is ``type(receiver).__setitem__(receiver, index, value)``.
    """
    order: list[str] = []

    @dataclass(frozen=True)
    class _Probe(Sugar):
        label: str
        payload: object

        def desugar(self, ctx=None):
            del ctx
            order.append(self.label)
            return ExitSet.completed(self.payload)

        @classmethod
        def witnesses(cls):
            return ()

    function, outcome = _helper_definition()
    site = function.body[0].fragment
    stored = SubscriptStoreEffectSugar(
        receiver=_Probe("receiver", fresh(ListValue, (TermValue(0),))),
        index=_Probe("index", TermValue(0)),
        value=_Probe("value", TermValue(9)),
        site=site,
    ).desugar()

    assert order == ["value", "receiver", "index"]
    assert stored.completed_value() == fresh(ListValue, (TermValue(9),))

    operands = [arg.name for arg in _dispatched_call(outcome).args[:3]]
    assert operands == ["obj", "key", "value"]
    assert operands != ["value", "obj", "key"]


def test_discrimination_discharge_order_is_not_source_order() -> None:
    """The store's operand order must not collapse to the source eval order."""
    _, outcome = _helper_definition()
    operands = [arg.name for arg in _dispatched_call(outcome).args[:3]]
    assert operands == ["obj", "key", "value"]
    assert operands != ["value", "obj", "key"]


# ---------------------------------------------------------------------------
# Wrong boundary type: exceptional edge remains unconsumed
# ---------------------------------------------------------------------------


def test_wrong_expected_type_leaves_setitem_exception_unconsumed() -> None:
    """Boundary verifies; it cannot create. Wrong T leaves the edge unconsumed."""
    from sugar_lift_py_tests.context_manager_contract import (
        AuthenticatedRaiseMatcher,
        EffectBoundaryDisposition,
    )
    from sugar_lift_py_tests.effect.expectation_not_met_effect import (
        ExpectationNotMetEffect,
    )

    produced = _stored(TupleValue((TermValue(0),)), TermValue(0), TermValue(9))
    original = produced.exits[0]
    assert isinstance(original, Halted)
    assert original.effect.exception_type_coordinate == _identity("TypeError")

    class _Expected:
        def __init__(self, name: str):
            self.identity = _identity(name)

        def exception_type_identity(self):
            return self.identity

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
