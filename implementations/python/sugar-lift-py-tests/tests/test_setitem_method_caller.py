"""Wave 3: ``setitem`` on a formal through a bound-method receiver binding.

Concrete program:

    class Holder:
        def store(self, obj, key, value):
            obj[key] = value

    Holder().store([0], 0, 9)

Python law: a bound method call supplies ``self`` first. That binding must not
shift ``obj`` / ``key`` / ``value`` in the store: it is
``type(obj).__setitem__(obj, key, value)``; ``self`` is the method binder's
slot, not a store operand.

Every item store is the one item mutation (``store_effect_sugar.
item_mutation``, #7757 step 7), never a carrier waiting on a caller's
actuals.  ``obj`` above is stored into and used no other way, so its class is
an input of ``store``'s contract and the store is the dispatched
``__setitem__`` edge (#8857), answered at prove by the class each caller binds
(``list.__setitem__``'s law, #8864).  Where ``obj``'s class is no input
(``METHOD_UNDECIDED``: ``return obj`` reads it bare) the store is the
undecided mutation, owed with its halt kept.  What the store does with a list
a caller built is the floor's own store on that decided list, through the
same door (``_stored``).

Acceptance (each with a discrimination twin where noted):

  1. Bound ``self`` does not shift obj/key/value.
  2. Mutable store completes.
  3. Invalid index yields named IndexError, its state kept.
  4. Off-by-one binding twin fails (self-as-obj is not the truthful store).
"""

from __future__ import annotations

from frame_fresh import fresh
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import ListValue, TermValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile

METHOD_BODY = (
    "class Holder:\n"
    "    def store(self, obj, key, value):\n"
    "        obj[key] = value\n"
)

METHOD_DEFAULTS = (
    "class Holder:\n"
    "    def store(self, obj, key=0, value=9):\n"
    "        obj[key] = value\n"
)

# The same store on a formal whose class is no input of ``store``'s contract:
# ``return obj`` reads ``obj`` bare (``nodes._receiver_uses``: blocked).
METHOD_UNDECIDED = (
    "class Holder:\n"
    "    def store(self, obj, key, value):\n"
    "        obj[key] = value\n"
    "        return obj\n"
)

# A store whose receiver the method's own frame builds: its type is decided,
# so the store is the floor's own, and ``held[4]`` on ``[0]`` halts.
METHOD_DECIDED_HALT = (
    "class Holder:\n"
    "    def store(self, value):\n"
    "        held = [0]\n"
    "        held[4] = value\n"
)


def _tree(source: str, name: str = "setitem_method_caller.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _method_definition(source: str = METHOD_BODY):
    tree = _tree(source, "method_alone.py")
    method = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "store"
    )
    return method, method.sugar().desugar(None)


def _stored(receiver, key, value):
    """``obj[key] = value`` at ``store``'s statement with only ``obj``,
    ``key`` and ``value`` (``self`` is no operand), ``obj`` a list a caller
    built: the one item mutation (``item_mutation``) on a receiver whose type
    the lift decides is the floor's own store, every face of it kept (#7757
    step 7)."""
    from sugar_lift_py_tests.sugar.store_effect_sugar import item_mutation

    method, _outcome = _method_definition()
    site = method.body[0].fragment
    return item_mutation("__setitem__", receiver, (key, value), site, None, unit=None)


def _dispatched_halt(outcome, method: str = "__setitem__"):
    """The halt the dispatched item operation's edge owes in a function's
    own proof, under the owner every unanswered call's halt names, with its
    member ``python:dispatch:<method>`` owed."""
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
    return halts[0]


def _dispatched_call(outcome, method: str = "__setitem__"):
    """``call:dispatch:<method>(<receiver>, <operands>..., py.class("0",
    class:<receiver>))``, read off the halt its edge owes (``python:raised(
    <call term>, <occurrence>)``)."""
    from sugar_lift_py_tests.call_symbol import call_symbol

    raised = _dispatched_halt(outcome, method).effect.raised_by_call
    assert raised.name == "python:raised", raised
    call = raised.args[0]
    assert call.name == call_symbol(f"dispatch:{method}"), call
    return call


def _undecided_store(outcome) -> Halted:
    """The undecided item mutation (``undecided_item_mutation_faces``) in a
    method's own proof: no carrier and no dispatched edge, one
    ``UndeterminedRaiseEffect`` halt owned by ``UndecidedSetitem`` kept
    with the state the store began from, and every completed face and the
    halt owing the undecided member at the store's site."""
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


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def _stored_list(completed_face) -> ListValue:
    """The store's post-state list: the floor's own post, or a function
    universe's."""
    assert isinstance(completed_face, Completed)
    if isinstance(completed_face.value, ListValue):
        return completed_face.value
    record = getattr(completed_face.value, "record", None)
    assert record is not None
    lists = [s for s in record.statements if isinstance(s, ListValue)]
    assert len(lists) == 1, lists
    return lists[0]


# ---------------------------------------------------------------------------
# 1. Bound self does not shift obj/key/value
# ---------------------------------------------------------------------------


def test_method_alone_mints_setitem_over_obj_key_value_not_self() -> None:
    """Method body ``obj[key] = value`` -- the store's operands exclude
    ``self``.

    Expected shape changed (#8857): ``obj``'s class is an input of
    ``store``'s contract, so the store is the dispatched ``__setitem__``
    edge over ``obj, key, value`` and ``py.class("0", class:obj)``; ``self``
    is no operand of it and takes no class input (it is never used).
    Expected shape changed (#7757 step 7): where ``obj``'s class is no input
    the store is no carrier but the undecided mutation, owed with its halt
    kept."""
    from sugar_lift_py_tests.ir import str_const

    method, outcome = _method_definition()
    call = _dispatched_call(outcome)
    assert [arg.name for arg in call.args[:3]] == ["obj", "key", "value"]
    assert "self" not in [getattr(arg, "name", None) for arg in call.args]
    assert call.args[3].name == "py.class"
    assert call.args[3].args[0] == str_const("0")
    assert call.args[3].args[1].name == "class:obj"
    assert len(call.args) == 4
    # Method formals include self; the store does not absorb it as obj.
    method_formals = tuple(p.name for p in method.params)
    assert method_formals[0] == "self"
    assert method_formals[1:] == ("obj", "key", "value")

    _undecided_store(_method_definition(METHOD_UNDECIDED)[1])


def test_discrimination_self_is_not_the_setitem_receiver_slot() -> None:
    """Bite: the store's receiver and the class it dispatches on are
    ``obj``'s, never the method's ``self``."""
    _method, outcome = _method_definition()
    call = _dispatched_call(outcome)
    assert call.args[0].name == "obj"
    assert call.args[0].name != "self"
    assert call.args[-1].args[1].name == "class:obj"
    assert call.args[-1].args[1].name != "class:self"


# ---------------------------------------------------------------------------
# 2. Mutable store completes
# ---------------------------------------------------------------------------


def test_mutable_method_store_completes() -> None:
    # Only obj/key/value reach the store (no self).
    exits = _stored(
        fresh(ListValue, (TermValue(0), TermValue(1))), TermValue(0), TermValue(9)
    )
    assert isinstance(exits.exits[0], Completed)
    assert _stored_list(exits.exits[0]) == fresh(
        ListValue, (TermValue(9), TermValue(1))
    )


# ---------------------------------------------------------------------------
# 3. Invalid index: named IndexError, state kept
# ---------------------------------------------------------------------------


def test_invalid_index_discharge_shares_reducer_pre_effect_state() -> None:
    """#6640 join: bound-method setitem halts carry their pre-state.

    Expected shape changed (#8857): the method's store is the dispatched
    ``__setitem__`` edge; the edge's halt is a statement halt, and the
    block's one seam (``function_universe_sugar._halt_state``) leaves it with
    the block's pre-statement state, never a fabricated empty one.  Where
    ``obj``'s class is no input the undecided mutation's halt is kept with
    its state the same way (#7757 step 7).

    The IndexError itself is the floor's store on a list a caller built
    (``_stored``): a wrong boundary keeps the halt's own effect and state by
    identity.  In a frame that builds the list itself the store's receiver
    is decided, and its IndexError leaves with the block's state
    (``METHOD_DECIDED_HALT``).
    """
    _method, outcome = _method_definition()
    dispatched = _dispatched_halt(outcome)
    assert dispatched.state is not None, (
        "the dispatched setitem halt left the method's block with no "
        "pre-effect state"
    )
    _undecided_store(_method_definition(METHOD_UNDECIDED)[1])

    _method, decided = _method_definition(METHOD_DECIDED_HALT)
    index_error = _identity("IndexError")
    index_errors = [
        face
        for face in decided.halts()
        if getattr(face.effect, "exception_type_coordinate", None) == index_error
    ]
    assert len(index_errors) == 1, decided
    assert index_errors[0].state is not None, (
        "the decided store's IndexError left the method's block with no "
        "pre-effect state"
    )

    exits = _stored(fresh(ListValue, (TermValue(0),)), TermValue(4), TermValue(9))
    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert ":" in halted.effect.occurrence_id

    class _Expected:
        def __init__(self, name: str):
            self.identity = _identity(name)

        def exception_type_identity(self):
            return self.identity

    # Wrong boundary retains the identical effect and pre-effect state.
    retained = exits.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected("ValueError")),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )
    assert len(retained.exits) == 1
    face = retained.exits[0]
    assert isinstance(face, Halted)
    assert face.effect is halted.effect
    assert face.state is halted.state


# ---------------------------------------------------------------------------
# 4. Off-by-one binding twin
# ---------------------------------------------------------------------------


def test_off_by_one_binding_twin_fails_against_truthful_store() -> None:
    """If self were shifted into the obj slot, store actuals would misalign.

    The truthful store reads obj/key/value.  An off-by-one map that slides
    the call actuals left (list under key, index under value, value dropped
    into a non-list receiver) cannot produce the truthful post-state of
    ``[0,1][0] = 9``.
    """
    base = fresh(ListValue, (TermValue(0), TermValue(1)))
    truthful = _stored(base, TermValue(0), TermValue(9))
    assert isinstance(truthful.exits[0], Completed)
    assert _stored_list(truthful.exits[0]) == fresh(
        ListValue, (TermValue(9), TermValue(1))
    )

    # Off-by-one: list lands under key, index under value — receiver is still
    # a list so the floor store runs, but at the wrong index / value.
    # (Putting a TermValue in the receiver slot is a Floor gap, not a binding
    # twin — keep the receiver a ListValue so the bite is the binding shift.)
    lying = _stored(
        fresh(ListValue, (TermValue(0), TermValue(1), TermValue(2))),
        TermValue(1),  # shifted: was value slot in a self-steal map
        TermValue(0),  # shifted index
    )
    lying_face = lying.exits[0]
    if isinstance(lying_face, Completed):
        assert _stored_list(lying_face) != fresh(
            ListValue, (TermValue(9), TermValue(1))
        )
        # Explicit: not the truthful store-at-0-with-9 face either.
        assert _stored_list(lying_face) != _stored_list(truthful.exits[0])
    else:
        assert isinstance(lying_face, Halted)
