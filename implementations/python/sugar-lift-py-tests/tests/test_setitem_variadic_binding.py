"""*args/**kwargs binding through formal setitem.

Concrete signatures:

    def helper(obj, key, *values):
        obj[key] = values

    def helper(obj, key, **values):
        obj[key] = values

Binding (SourceCallFrame.bind_actuals only — no second binder):

  - remaining positionals pack into authenticated ``TupleValue`` on the
    variadic-positional formal; setitem stores that tuple as the value
  - extra keywords pack into authenticated ``DictValue`` on the
    variadic-keyword formal; setitem stores that mapping as the value
  - empty * / ** are honest empty TupleValue / DictValue (never fabricated
    None or omitted)
  - invalid index: named IndexError; the helper's own halt keeps the state
    the store began from
  - with no actual the store stays owed; a reordered variadic twin fails
    (lying store ≠ truthful store)

Helper alone is the dispatched ``__setitem__`` edge since #8857 (``obj``'s
class is an input of its contract), over ``(obj, key, values)``; a caller
supplies each formal by name and the class of each decided value
(``py.class``).  The same store on an ``obj`` whose class is no input (the
body also returns it bare) is the undecided item mutation: two faces, both
owing the undecided member, never a carrier waiting on a caller's actual
(#7757).  The Floor store a caller's list takes (the pack stored, the named
``IndexError``) is read through the one item mutation
(``store_effect_sugar.item_mutation``) on that list.
Does not touch ExitSet, the store producer or the Floor.
"""

from __future__ import annotations

import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    DictValue,
    ListValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile

HELPER_STAR = "def helper(obj, key, *values):\n    obj[key] = values\n"
HELPER_KW = "def helper(obj, key, **values):\n    obj[key] = values\n"
# The same stores on an ``obj`` whose class is no input of ``helper``'s
# contract: ``return obj`` reads it bare (``nodes._receiver_uses``: blocked).
UNDECIDED_STAR = HELPER_STAR + "    return obj\n"
UNDECIDED_KW = HELPER_KW + "    return obj\n"


def _tree(source: str, name: str = "setitem_variadic.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper(program: str):
    """``helper`` alone and its own proof's reduction.

    ``obj`` is stored into and used no other way, so its class is an input
    of ``helper``'s contract (``nodes._receiver_class_parameters``; the
    variadic ``values`` never is one) and ``obj[key] = values`` is
    ``type(obj).__setitem__(obj, key, values)``: the dispatched edge
    (``receiver_dispatch.dispatch_edge_call``, #8857), owed as it stands,
    resolved at prove at the class each caller binds (``list.__setitem__``'s
    law, #8864).  It is no carrier."""
    tree = _tree(program, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _dispatched_halt(outcome, method: str = "__setitem__"):
    """The one halt the dispatched item operation's edge owes in a helper's
    own proof, under the owner every unanswered call's halt names, its
    member ``python:dispatch:<method>`` owed."""
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
    return halts[0]


def _dispatched_call(outcome, method: str = "__setitem__"):
    """The dispatched item operation's coordinate ``call:dispatch:<method>(
    <receiver>, <operands>..., py.class("0", class:<receiver>))``, read off
    the halt its edge owes (``python:raised(<call term>, <occurrence>)``)."""
    from sugar_lift_py_tests.call_symbol import call_symbol

    raised = _dispatched_halt(outcome, method).effect.raised_by_call
    assert raised.name == "python:raised", raised
    call = raised.args[0]
    assert call.name == call_symbol(f"dispatch:{method}"), call
    return call


def _class_input(rides, receiver: str) -> None:
    """``py.class("0", class:<receiver>)``: the dispatched call's receiver
    class, the class input of the receiver's parameter."""
    from sugar_lift_py_tests.ir import str_const

    assert rides.name == "py.class", rides
    assert rides.args[0] == str_const("0")
    assert rides.args[1].name == f"class:{receiver}", rides


def _undecided_halt(program: str):
    """``program`` alone, its ``obj`` read bare (``return obj``), so
    ``obj``'s class is no input of its contract and nothing here decides
    ``type(obj).__setitem__``: the store is the undecided item mutation
    (``store_effect_sugar.undecided_item_mutation_faces``).  It completes
    under ``python:setitem.completes(python:setitem(<occurrence>))`` or
    raises something undetermined (``UndecidedSetitem``) under the
    complement, both faces owing the undecided member, the halt kept with
    the state the store began from.  No carrier: no store waits on a
    caller's actual (#7757)."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.unanswered_calls import unanswered_call

    _function, outcome = _helper(program)
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
    owed = unanswered_call(None, halt.effect.site)
    assert owed in halt.owed
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    for face in completed:
        assert "python:setitem.completes" in str(face.guard)
        assert owed in face.owed
    assert outcome.completed_value() is None
    return halt


def _store(program: str, obj, key, values) -> ExitSet:
    """``obj[key] = values`` with a caller's decided actuals, at ``program``'s
    store statement: the one item mutation (``item_mutation``) on the list
    the caller built is its Floor's own store (``ListValue.setitem``), every
    face of it kept.  The helper's own store is the dispatched edge,
    answered at prove by ``list.__setitem__``'s law (#8864); this is the
    store that law states."""
    from sugar_lift_py_tests.sugar.store_effect_sugar import item_mutation

    function, _outcome = _helper(program)
    return item_mutation(
        "__setitem__", obj, (key, values), function.body[0].fragment, None, unit=None
    )


def _class(key: str, name: str):
    """``py.class(<key>, python:builtin("<name>"))``: the class of an actual
    the caller decides, after the actuals (#8857).  For a signature that
    packs, every formal is keyed by its name (``definition_edge_call``)."""
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.receiver_dispatch import (
        CLASS_ARGUMENT,
        builtin_class_term,
    )

    return ctor(CLASS_ARGUMENT, [str_const(key), builtin_class_term(name)])


def _call(program: str, actuals: str):
    """``helper({actuals})`` in a caller's body, reduced alone.

    The call sits in a function body so its callee name reads ``helper``'s
    ``def`` (``SourceUnit.function_definition_for_read``): a call the module
    body runs is answered as the module-level read is, not at all, the
    unanswered call (#9007 decision 1), and binds no actual to a formal."""
    tree = _tree(program + f"\ndef caller():\n    return helper({actuals})\n")
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def _edge(program: str, actuals: str):
    """The call's value on its completed face: a same-file call is its
    coordinate and edge, joined at prove (#7757 steps 5 and 6, #8705).  Its
    ``arg_values`` are the actuals as written; what the one binder packs
    into ``*values`` / ``**values`` is on its term, every formal by name
    (``py.kwarg``, the variadic ``py.packed``), as prove's binder binds
    the helper's contract."""
    from sugar_lift_py_tests.floor import CallSiteValue

    completed = [
        face
        for face in _call(program, actuals).exits
        if isinstance(face, Completed)
    ]
    assert len(completed) == 1, completed
    edge = completed[0].value
    assert isinstance(edge, CallSiteValue), type(edge)
    return edge


def _coordinate(edge):
    """The call's coordinate ``call:<target>(<arguments>)`` the edge's value
    names: the completed face of the one unanswered call returns
    ``python:call_result(<call term>, <occurrence>)`` (#7757 steps 5 and 6,
    #8705), so the formals the one binder packs are the call term's
    arguments, never the result's."""
    result = edge.term
    assert result.name == "python:call_result", result
    call = result.args[0]
    assert call.name.startswith("call:"), call
    return call


def _formal(edge, name: str, value):
    """The formal ``name`` bound to ``value``: ``py.kwarg(name, value)`` for
    a parameter, ``py.packed(name, value)`` for the helper's variadic
    ``values`` (a keyword naming it would go into ``**kwargs``, never bind
    it)."""
    from sugar_lift_py_tests.ir import ctor, str_const

    form = "py.packed" if name == "values" else "py.kwarg"
    return ctor(form, [str_const(name), value.to_term(owner=str(edge.site))])


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def _stored_list(completed_face) -> ListValue:
    """The store's post-state list: the Floor's own store completes with the
    receiver as the operation left it."""
    assert isinstance(completed_face, Completed)
    assert isinstance(completed_face.value, ListValue), completed_face.value
    return completed_face.value


# ---------------------------------------------------------------------------
# Helper alone → the one item mutation over variadic formals
# ---------------------------------------------------------------------------


def test_helper_star_alone_is_undischarged_setitem_with_variadic_positional() -> None:
    # Expected shape changed (#8857): ``obj``'s class is an input, so the
    # store is the dispatched ``__setitem__`` edge over ``obj, key, values``
    # in Python's order, owed, its halt kept with the state the store began
    # from.  Where the class is no input the store is the undecided item
    # mutation (``_undecided_halt``), never a carrier: no store waits on a
    # caller's actual, and the ``setitem`` carrier projector is gone (#7757).
    function, outcome = _helper(HELPER_STAR)
    call = _dispatched_call(outcome)
    assert [arg.name for arg in call.args[:3]] == ["obj", "key", "values"]
    _class_input(call.args[3], "obj")
    assert _dispatched_halt(outcome).state is not None
    assert [face for face in outcome.exits if isinstance(face, Completed)]
    kinds = tuple(c.parameter_kind for c in function.sugar().formal_coordinates)
    assert kinds == (
        "positional-or-keyword",
        "positional-or-keyword",
        "variadic-positional",
    )

    _undecided_halt(UNDECIDED_STAR)
    assert "setitem" not in _NATIVE_OPERATION_PROJECTORS


def test_helper_kw_alone_is_undischarged_setitem_with_variadic_keyword() -> None:
    # Expected shape changed (#8857): the dispatched edge, as above; the
    # undecided item mutation where ``obj``'s class is no input (#7757).
    function, outcome = _helper(HELPER_KW)
    call = _dispatched_call(outcome)
    assert [arg.name for arg in call.args[:3]] == ["obj", "key", "values"]
    _class_input(call.args[3], "obj")
    kinds = tuple(c.parameter_kind for c in function.sugar().formal_coordinates)
    assert kinds == (
        "positional-or-keyword",
        "positional-or-keyword",
        "variadic-keyword",
    )
    _undecided_halt(UNDECIDED_KW)


def test_helper_alone_is_not_completed_discrimination() -> None:
    _, pending = _helper(HELPER_STAR)
    with pytest.raises(AssertionError):
        assert isinstance(pending, Completed)


# ---------------------------------------------------------------------------
# Remaining positionals → authenticated TupleValue stored by setitem
# ---------------------------------------------------------------------------


def test_remaining_positionals_become_authenticated_tuple_store_value() -> None:
    """``helper([0], 0, 1, 2, 3)`` — *values packs (1,2,3) as stored value.
    The edge carries the pack on the formal ``values`` (#8705); the call
    value no longer names the frame's parameters."""
    edge = _edge(HELPER_STAR, "[0], 0, 1, 2, 3")
    assert edge.arg_values == (
        fresh(ListValue, (TermValue(0),)),
        TermValue(0),
        TermValue(1),
        TermValue(2),
        TermValue(3),
    )
    # After the formals ride the classes the caller decides, each keyed by
    # its formal's name where the signature packs (#8857,
    # ``definition_edge_call``): the ``[0]`` it built a ``list`` (what
    # ``class:obj`` binds at prove), the key an ``int``, the pack a
    # ``tuple``.
    assert list(_coordinate(edge).args[1:]) == [
        _formal(edge, "key", TermValue(0)),
        _formal(
            edge, "values", TupleValue((TermValue(1), TermValue(2), TermValue(3)))
        ),
        _class("obj", "list"),
        _class("key", "int"),
        _class("values", "tuple"),
    ]


def test_star_values_store_stores_tuple_at_index() -> None:
    exits = _store(
        HELPER_STAR,
        fresh(ListValue, (TermValue(0),)),
        TermValue(0),
        TupleValue((TermValue(1), TermValue(2))),
    )
    assert isinstance(exits, ExitSet)
    assert isinstance(exits.exits[0], Completed)
    assert _stored_list(exits.exits[0]) == fresh(
        ListValue, (TupleValue((TermValue(1), TermValue(2))),)
    )


# ---------------------------------------------------------------------------
# Extra keywords → authenticated DictValue stored by setitem
# ---------------------------------------------------------------------------


def test_extra_keywords_become_authenticated_mapping_store_value() -> None:
    """``helper([0], 0, a=1, b=2)`` — **values packs mapping as stored value,
    carried on the edge on the formal ``values`` (#8705)."""
    edge = _edge(HELPER_KW, "[0], 0, a=1, b=2")
    assert edge.arg_values == (
        fresh(ListValue, (TermValue(0),)),
        TermValue(0),
        TermValue(1),
        TermValue(2),
    )
    assert list(_coordinate(edge).args[1:]) == [
        _formal(edge, "key", TermValue(0)),
        _formal(
            edge,
            "values",
            fresh(
                DictValue,
                (
                    (StringValue("a"), TermValue(1)),
                    (StringValue("b"), TermValue(2)),
                ),
            ),
        ),
        _class("obj", "list"),
        _class("key", "int"),
        _class("values", "dict"),
    ]


def test_kw_values_store_stores_dict_at_index() -> None:
    mapping = fresh(DictValue, ((StringValue("a"), TermValue(1)),))
    exits = _store(HELPER_KW, fresh(ListValue, (TermValue(0),)), TermValue(0), mapping)
    assert isinstance(exits.exits[0], Completed)
    assert _stored_list(exits.exits[0]) == fresh(ListValue, (mapping,))


# ---------------------------------------------------------------------------
# Empty variadics are honest empty values
# ---------------------------------------------------------------------------


def test_empty_star_is_honest_empty_tuple() -> None:
    """``helper([0], 0)`` with *values — empty pack, not None / omitted."""
    edge = _edge(HELPER_STAR, "[0], 0")
    assert _coordinate(edge).args[2] == _formal(edge, "values", TupleValue(()))


def test_empty_kw_is_honest_empty_dict() -> None:
    """``helper([0], 0)`` with **values — empty mapping, not None / omitted."""
    edge = _edge(HELPER_KW, "[0], 0")
    assert _coordinate(edge).args[2] == _formal(edge, "values", fresh(DictValue, ()))


def test_empty_star_store_stores_empty_tuple() -> None:
    exits = _store(
        HELPER_STAR, fresh(ListValue, (TermValue(0),)), TermValue(0), TupleValue(())
    )
    assert isinstance(exits.exits[0], Completed)
    assert _stored_list(exits.exits[0]) == fresh(ListValue, (TupleValue(()),))


# ---------------------------------------------------------------------------
# Invalid index retains exact pre-effect state
# ---------------------------------------------------------------------------


def test_invalid_index_named_indexerror_with_exact_pre_effect_state() -> None:
    # Expected shape changed (#8857, #7757): the helper's own store is the
    # dispatched edge, whose halt leaves with the state the store began
    # from (the block reducer's one record, ``_halt_state``); the named
    # IndexError is ``list.__setitem__``'s law at prove (#8864), the Floor's
    # own store on the caller's list, read below through the one item
    # mutation; and a store on a list the frame itself built halts with it
    # there, its state kept.
    _, outcome = _helper(HELPER_STAR)
    assert _dispatched_halt(outcome).state is not None
    exits = _store(
        HELPER_STAR,
        fresh(ListValue, (TermValue(0),)),
        TermValue(1),
        TupleValue((TermValue(9),)),
    )
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert not isinstance(halted, Completed)
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    assert not isinstance(getattr(halted, "value", None), UniverseValue)
    _, built = _helper("def helper(*values):\n    obj = [0]\n    obj[1] = values\n")
    index_error = _identity("IndexError")
    (frame_halt,) = [
        face
        for face in built.halts()
        if getattr(face.effect, "exception_type_coordinate", None) == index_error
    ]
    assert frame_halt.state is not None


def test_source_caller_invalid_index_preserves_state() -> None:
    # Expected verdict changed (#7757 steps 5 and 6, #8705): the source call
    # is its edge and owes its halt; the named IndexError with its state is
    # ``list.__setitem__``'s law at the class the caller binds, the Floor
    # store pinned by
    # ``test_invalid_index_named_indexerror_with_exact_pre_effect_state``,
    # joined at the call by prove (#8690, #8749, #8864).
    outcome = _call(HELPER_STAR, "[0], 1, 9")
    assert [face for face in outcome.exits if isinstance(face, Halted)], outcome
    edge = _edge(HELPER_STAR, "[0], 1, 9")
    assert list(_coordinate(edge).args[1:]) == [
        _formal(edge, "key", TermValue(1)),
        _formal(edge, "values", TupleValue((TermValue(9),))),
        _class("obj", "list"),
        _class("key", "int"),
        _class("values", "tuple"),
    ]


def test_invalid_index_discrimination_not_completed() -> None:
    exits = _store(
        HELPER_STAR,
        fresh(ListValue, (TermValue(0),)),
        TermValue(1),
        TupleValue((TermValue(9),)),
    )
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Completed)
    # The helper's own halt is never stateless: it leaves with the state the
    # store began from.
    _, outcome = _helper(HELPER_STAR)
    with pytest.raises(AssertionError):
        assert _dispatched_halt(outcome).state is None


# ---------------------------------------------------------------------------
# Dropped / reordered variadic twins fail
# ---------------------------------------------------------------------------


def test_no_actual_leaves_the_store_owed_never_completed() -> None:
    """With no caller's actual the store stays loud, no green store: the
    dispatched edge owes ``python:dispatch:__setitem__`` and the undecided
    item mutation owes its member (#7825), neither an unconditional
    completion.  No store waits on an actual (#7757), so there is no
    discharge to drop the *values formal from."""
    _, outcome = _helper(HELPER_STAR)
    _dispatched_halt(outcome)
    assert outcome.completed_value() is None
    _undecided_halt(UNDECIDED_STAR)


def test_reordered_variadic_twin_fails() -> None:
    """A lying store with the key and value swapped is not the truthful
    *store.

    The dispatched edge takes ``obj, key, values`` in that order.  On the
    caller's list the truthful store puts the TupleValue pack at the
    TermValue key; the swapped one hands the pack as the key -- the Floor
    refuses a ground tuple index (ConstructionPanic) or yields a
    non-matching face.  Never equals truthful.
    """
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    _, outcome = _helper(HELPER_STAR)
    call = _dispatched_call(outcome)
    assert [arg.name for arg in call.args[:3]] == ["obj", "key", "values"]
    pack = TupleValue((TermValue(9), TermValue(8)))
    receiver = fresh(ListValue, (TermValue(0), TermValue(1), TermValue(2)))
    t_face = _store(HELPER_STAR, receiver, TermValue(1), pack).exits[0]
    assert isinstance(t_face, Completed)
    t_list = _stored_list(t_face)
    assert t_list == fresh(ListValue, (TermValue(0), pack, TermValue(2)))
    try:
        l_face = _store(HELPER_STAR, receiver, pack, TermValue(1)).exits[0]
    except ConstructionPanic:
        return  # lying index is the packed tuple — not a lawful setitem index
    if isinstance(l_face, Completed):
        assert l_face.value != t_list
    else:
        assert isinstance(l_face, Halted)


def test_star_vs_kw_kinds_are_not_interchangeable_discrimination() -> None:
    """Bite: *values pack is TupleValue; **values pack is DictValue."""
    star = _edge(HELPER_STAR, "[0], 0, 1")
    kw = _edge(HELPER_KW, "[0], 0, a=1")
    assert _coordinate(star).args[2] == _formal(
        star, "values", TupleValue((TermValue(1),))
    )
    assert _coordinate(kw).args[2] == _formal(
        kw, "values", fresh(DictValue, ((StringValue("a"), TermValue(1)),))
    )
    with pytest.raises(AssertionError):
        assert _coordinate(star).args[2] == _coordinate(kw).args[2]
