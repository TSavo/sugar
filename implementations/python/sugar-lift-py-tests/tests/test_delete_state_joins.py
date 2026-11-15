"""DELETE × CONTEXT JOINS — state-survival matrix extended into formal delete.

Extends the seam-3 state-survival matrix into delitem / delattr_named after
#6699. Temporal state (earlier bindings / pre-delete testimony) must survive
a sole exceptional delete edge in each context below.

Seed programs:

    def helper(obj, key):
        del obj[key]

    def multi(obj, key):
        a = [0]
        a[0] = 9
        del obj[key]

    class Holder:
        def drop(self, obj, key):
            del obj[key]

Acceptance:

  (a) delete halt inside try/except — handler starts from pre-delete state
  (b) delete inside With — exit receives pre-halt state (NeverSuppresses)
  (c) earlier bindings survive delete halts in multi-statement / unpack-like
      contexts
  (d) bound-method delete (self prepended) discharges without shifting
      delitem coordinates (obj/key, not self)
  (e) lying rollback / fabricated-state twins refuse

Reds name owners by nature:

  codex-1 — carrier composition / pre_effect_state survival
  codex-3 — method-call transport / bound-method projection

MUST NOT TOUCH: production, carrier/ExitSet.
"""

from __future__ import annotations

import pytest
from frame_fresh import fresh

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
    NeverSuppresses,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import (
    DictValue,
    ListValue,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute, Call, FunctionDef
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus

CODEX1 = (
    "codex-1 carrier composition: delete halt pre_effect_state / earlier "
    "bindings must compose through try/with/multi-statement without "
    "fabricated or rolled-back state"
)
CODEX3 = (
    "codex-3 bound-method delete transport: delitem formals must remain "
    "obj/key with self prepended only at the callsite, not shifted into "
    "the delete demand"
)

DELITEM_HELPER = "def helper(obj, key):\n    del obj[key]\n"
MULTI_PRIOR_STORE = (
    "def multi(obj, key):\n" "    a = [0]\n" "    a[0] = 9\n" "    del obj[key]\n"
)
METHOD_DROP = (
    "class Holder:\n" "    def drop(self, obj, key):\n" "        del obj[key]\n"
)

# Since #8857 each seed above takes ``class:obj`` as an input (``obj`` is
# deleted from and used no other way), so its delete is the dispatched
# ``__delitem__`` edge, answered at prove by the class a caller binds (#8864):
# no ``KeyError`` is decided here, and its halt leaves the block with the
# prefix the body reached (``function_universe_sugar``'s one statement
# tail).  The carrier these discharge joins read stands for a formal whose
# class is no input: ``return obj`` reads ``obj`` bare
# (``nodes._receiver_uses``), so ``project_delitem`` mints it.
DELITEM_CARRIER = "def helper(obj, key):\n    del obj[key]\n    return obj\n"
MULTI_PRIOR_STORE_CARRIER = (
    "def multi(obj, key):\n"
    "    a = [0]\n"
    "    a[0] = 9\n"
    "    del obj[key]\n"
    "    return obj\n"
)
METHOD_DROP_CARRIER = (
    "class Holder:\n"
    "    def drop(self, obj, key):\n"
    "        del obj[key]\n"
    "        return obj\n"
)


def _tree(source: str, name: str = "delete_state_joins.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _identity(name: str):
    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


class _Expected:
    def __init__(self, name: str):
        self.identity = _identity(name)

    def exception_type_identity(self):
        return self.identity


def _route_try(exits: ExitSet, expected: str) -> ExitSet:
    return exits.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected(expected)),
            unmet=ExpectationNotMetEffect("raise", "delete-try-site"),
        ),
    )


def _dispatched_halt(source: str):
    """The seed's own proof: the dispatched ``__delitem__`` edge's one halt
    (``call:dispatch:__delitem__(obj, key, py.class("0", class:obj))``,
    owed), and the call it names."""
    from sugar_lift_py_tests.call_symbol import call_symbol
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    tree = _tree(source, "delitem_dispatched.py")
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name in {"helper", "multi", "drop"}
    )
    outcome = function.sugar().desugar(None)
    assert isinstance(outcome, ExitSet), type(outcome)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UnknownCallee:dispatch:__delitem__"
    ]
    assert len(halts) == 1, outcome
    assert "python:dispatch:__delitem__" in {c.symbol for c in owed_calls(outcome)}
    call = halts[0].effect.raised_by_call.args[0]
    assert call.name == call_symbol("dispatch:__delitem__"), call
    return function, halts[0], call


def test_dispatched_delete_halt_keeps_the_earlier_store_in_its_state() -> None:
    """(c) on the dispatched edge: the halt leaves ``multi`` with the record
    the body reached, ``a[0] = 9`` in it -- never an empty, rolled-back
    state.  The edge names no exception (prove types it)."""
    _function, halt, call = _dispatched_halt(MULTI_PRIOR_STORE)
    assert [arg.name for arg in call.args[:2]] == ["obj", "key"]
    assert halt.effect.exception_type_coordinate is None
    assert halt.state is not None, f"{CODEX1}: dispatched delete halt dropped state"
    assert any(
        isinstance(entry, ListValue) and entry == fresh(ListValue, (TermValue(9),))
        for entry in halt.state.entries
    ), f"{CODEX1}: earlier store absent from entries={halt.state.entries!r}"


def _delitem_keyerror_halt(
    source: str = DELITEM_CARRIER,
) -> tuple[NativeOperationExitCarrierV1, Halted]:
    """Sole exceptional edge: formal delitem missing-key KeyError."""
    tree = _tree(source, "delitem_seed.py")
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name in {"helper", "multi", "drop"}
    )
    pending = function.sugar().desugar(None)
    assert isinstance(
        pending, NativeOperationExitCarrierV1
    ), f"{CODEX1}: expected delitem carrier, got {type(pending).__name__}"
    assert pending.demand.operator == "delitem"
    assert (
        pending.pre_effect_state is not None
    ), f"{CODEX1}: reducer did not enroll pre_effect_state on delitem carrier"
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        None,
        {
            obj_cid: fresh(DictValue, ((StringValue("a"), TermValue(1)),)),
            key_cid: StringValue("missing"),
        },
    )
    assert isinstance(exits, ExitSet) and len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted), halted
    assert halted.effect.exception_type_coordinate == _identity("KeyError")
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    assert (
        halted.state is pending.pre_effect_state.state
    ), f"{CODEX1}: halt.state is not enrolled pre-effect state identity"
    return pending, halted


# ===========================================================================
# (a) Delete halt inside try/except
# ===========================================================================


def test_delete_halt_inside_try_handler_starts_from_pre_delete_state() -> None:
    """Matching except: handler Completed.value is the exact pre-delete state."""
    pending, halted = _delitem_keyerror_halt()
    routed = _route_try(ExitSet((halted,)), "KeyError")
    assert len(routed.exits) == 1
    handler = routed.exits[0]
    assert isinstance(handler, Completed)
    assert handler.value is halted.state
    assert handler.value is pending.pre_effect_state.state


def test_delete_halt_wrong_exception_retains_identical_pre_delete_state() -> None:
    """Unmatched except: effect and state object identity survive."""
    pending, halted = _delitem_keyerror_halt()
    routed = _route_try(ExitSet((halted,)), "ValueError")
    retained = routed.exits[0]
    assert isinstance(retained, Halted)
    assert retained.effect is halted.effect
    assert retained.state is halted.state
    assert retained.state is pending.pre_effect_state.state


# ===========================================================================
# (b) Delete inside With — exit receives pre-halt state
# ===========================================================================


def test_delete_halt_inside_with_never_suppresses_receives_pre_halt_state() -> None:
    """NeverSuppresses cleanup: surviving halt keeps exact pre-delete state."""
    pending, halted = _delitem_keyerror_halt()
    after = ExitSet((halted,)).and_exit(
        ExitSet.completed(TermValue(0)),
        disposition=NeverSuppresses(),
    )
    assert len(after.exits) == 1
    surviving = after.exits[0]
    assert isinstance(surviving, Halted)
    assert surviving.effect is halted.effect
    assert surviving.state is halted.state
    assert surviving.state is pending.pre_effect_state.state


def test_with_then_try_composition_on_delete_halt() -> None:
    """Compose with cleanup then matching try — handler value is pre-delete state."""
    pending, halted = _delitem_keyerror_halt()
    after_with = ExitSet((halted,)).and_exit(
        ExitSet.completed(TermValue(0)),
        disposition=NeverSuppresses(),
    )
    surviving = after_with.exits[0]
    assert isinstance(surviving, Halted)
    handler_set = _route_try(after_with, "KeyError")
    handler = handler_set.exits[0]
    assert isinstance(handler, Completed)
    assert handler.value is halted.state
    assert handler.value is pending.pre_effect_state.state


# ===========================================================================
# (c) Earlier bindings survive delete halts (multi-statement)
# ===========================================================================


def test_earlier_bindings_survive_delete_halt_in_multi_statement_body() -> None:
    """Prior ``a[0]=9`` remains in pre-effect state when later delitem KeyErrors."""
    pending, halted = _delitem_keyerror_halt(MULTI_PRIOR_STORE_CARRIER)
    assert halted.state is not None, f"{CODEX1}: multi-statement halt dropped state"
    lists = [e for e in halted.state.entries if isinstance(e, ListValue)]
    assert lists == [
        fresh(ListValue, (TermValue(9),))
    ], f"{CODEX1}: earlier store not in halt state entries={halted.state.entries!r}"
    assert halted.state is pending.pre_effect_state.state


def test_discrimination_completed_return_is_not_the_delete_keyerror_halt() -> None:
    """Positive twin: in-range delete completes; not a KeyError halt face."""
    tree = _tree(DELITEM_CARRIER, "complete_delete.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    pending = function.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        None,
        {
            obj_cid: fresh(DictValue, ((StringValue("a"), TermValue(1)),)),
            key_cid: StringValue("a"),
        },
    )
    assert isinstance(exits.exits[0], Completed)
    assert not isinstance(exits.exits[0], Halted)


# ===========================================================================
# (d) Bound-method delete without shifting coordinates
# ===========================================================================


def test_bound_method_delete_retains_obj_key_demand_not_self() -> None:
    """Method alone: delitem formals are obj/key — self is binder, not demand."""
    # The dispatched edge (#8857): ``type(obj).__delitem__(obj, key)``, its
    # receiver ``obj`` -- never ``self`` -- with ``obj``'s class input.
    _method, _halt, call = _dispatched_halt(METHOD_DROP)
    assert [arg.name for arg in call.args[:2]] == [
        "obj",
        "key",
    ], f"{CODEX3}: dispatched delete shifted by self: {call.args!r}"
    assert call.args[2].name == "py.class"
    assert call.args[2].args[1].name == "class:obj"
    assert len(call.args) == 3

    # The carrier, where ``obj``'s class is no input.
    tree = _tree(METHOD_DROP_CARRIER, "method_drop_alone.py")
    method = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "drop"
    )
    pending = method.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1), (
        f"{CODEX3}: method body must mint delitem carrier, "
        f"got {type(pending).__name__}"
    )
    assert pending.demand.operator == "delitem"
    names = tuple(value.term.name for value in pending.operands)
    assert names == (
        "obj",
        "key",
    ), f"{CODEX3}: delitem formals shifted by self: {names}"
    method_formals = tuple(p.name for p in method.params)
    assert method_formals[0] == "self"
    assert method_formals[1:] == ("obj", "key")
    # Self formal coordinate is not a delitem operand.
    self_coord = method.formal_coordinates()[0]
    assert self_coord.coordinate_cid not in set(pending.demand.operand_coordinate_cids)


def _drop_call_outcome(actuals: str) -> ExitSet:
    """The one ``Holder().drop(<actuals>)`` call, reduced."""
    source = METHOD_DROP + f"\nHolder().drop({actuals})\n"
    tree = _tree(source)
    calls = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Attribute)
        and node.func.attr == "drop"
    )
    assert len(calls) == 1
    return calls[0].sugar().desugar(None)


@pytest.mark.parametrize(
    "actuals",
    ["{'a': 1}, 'missing'", "{'a': 1}, 'a'"],
    ids=["missing-key", "present-key"],
)
def test_bound_method_delete_on_a_class_call_result_is_undecided_at_the_call(
    actuals: str,
) -> None:
    """#7757 step 6 (#8738, #8751): ``Holder().drop(...)`` is a method of a
    class call's result.  The method is not dispatched at the reduction, so
    neither the missing key's ``KeyError`` nor the present key's completion is
    decided at the call: both are the undecided faces (a completed face under
    an undecided read's guard, every halt an undetermined raise naming no
    exception).  The ``KeyError`` is stated by ``drop``'s own reduction over
    ``obj``/``key`` (``test_bound_method_delete_retains_obj_key_demand_not_self``)
    and reaches a caller at prove once a method of a call result is
    dispatched there (step 8).  Before step 6 the call applied the body here
    and named the ``KeyError``; that application is deleted."""
    from test_method_call_application_twins import _undecided_faces

    _undecided_faces(_drop_call_outcome(actuals))


# ===========================================================================
# (e) Lying rollback / fabricated-state twins refuse
# ===========================================================================


def test_fabricated_empty_state_is_not_pre_delete_when_store_preceded() -> None:
    """Bite: multi-statement halt state is not an empty fabricated block."""
    pending, halted = _delitem_keyerror_halt(MULTI_PRIOR_STORE_CARRIER)
    fabricated = _ReducedBlock((), True, ())
    assert halted.state is not None
    assert halted.state is pending.pre_effect_state.state
    with pytest.raises(AssertionError):
        assert halted.state is fabricated
    assert any(
        isinstance(e, ListValue) for e in halted.state.entries
    ), f"{CODEX1}: prior store absent from entries={halted.state.entries!r}"


def test_handler_value_is_not_fabricated_fresh_block_twin() -> None:
    """Matching try handler must be the halt state object, not a fresh empty."""
    pending, halted = _delitem_keyerror_halt()
    handler = _route_try(ExitSet((halted,)), "KeyError").exits[0]
    assert isinstance(handler, Completed)
    fabricated = _ReducedBlock((), True, ())
    with pytest.raises(AssertionError):
        assert handler.value is fabricated
    assert handler.value is halted.state
    assert handler.value is pending.pre_effect_state.state


def test_lying_rollback_misreads_halt_as_completed_body() -> None:
    """Discrimination: KeyError delete halt is not a Completed empty return."""
    _, halted = _delitem_keyerror_halt()
    with pytest.raises(AssertionError):
        assert isinstance(halted, Completed)
    with pytest.raises(AssertionError):
        assert halted.state is None


def test_wrong_exception_observation_is_not_the_delete_effect() -> None:
    """Bite: foreign RaiseEffect is not the transported delete edge."""
    _, halted = _delitem_keyerror_halt()
    foreign = RaiseEffect(
        exception_name="KeyError",
        blame="foreign.py:1:0",
        occurrence=AuthenticatedRaiseLocus.of("foreign.py:1:0"),
        exception_type_coordinate=_identity("KeyError"),
        exception_type_mro=(_identity("KeyError"),),
    )
    with pytest.raises(AssertionError):
        assert halted.effect is foreign
    with pytest.raises(AssertionError):
        assert halted.effect.occurrence == foreign.occurrence


def test_with_does_not_fabricate_completed_on_delete_halt_twin() -> None:
    _, halted = _delitem_keyerror_halt()
    after = ExitSet((halted,)).and_exit(
        ExitSet.completed(TermValue(0)),
        disposition=NeverSuppresses(),
    )
    with pytest.raises(AssertionError):
        assert isinstance(after.exits[0], Completed)
    with pytest.raises(AssertionError):
        assert after.exits[0].state is None
