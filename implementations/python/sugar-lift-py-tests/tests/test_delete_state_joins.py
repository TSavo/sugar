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
    CallSiteValue,
    DictValue,
    ListValue,
    ObjectValue,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
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
    "def multi(obj, key):\n"
    "    a = [0]\n"
    "    a[0] = 9\n"
    "    del obj[key]\n"
)
METHOD_DROP = (
    "class Holder:\n"
    "    def drop(self, obj, key):\n"
    "        del obj[key]\n"
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


def _delitem_keyerror_halt(
    source: str = DELITEM_HELPER,
) -> tuple[NativeOperationExitCarrierV1, Halted]:
    """Sole exceptional edge: formal delitem missing-key KeyError."""
    tree = _tree(source, "delitem_seed.py")
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef)
        and node.name in {"helper", "multi", "drop"}
    )
    pending = function.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1), (
        f"{CODEX1}: expected delitem carrier, got {type(pending).__name__}"
    )
    assert pending.demand.operator == "delitem"
    assert pending.pre_effect_state is not None, (
        f"{CODEX1}: reducer did not enroll pre_effect_state on delitem carrier"
    )
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: DictValue(((StringValue("a"), TermValue(1)),)),
            key_cid: StringValue("missing"),
        }
    )
    assert isinstance(exits, ExitSet) and len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted), halted
    assert halted.effect.exception_type_coordinate == _identity("KeyError")
    assert isinstance(halted.effect.occurrence_id, str) and ":" in halted.effect.occurrence_id, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    assert halted.state is pending.pre_effect_state.state, (
        f"{CODEX1}: halt.state is not enrolled pre-effect state identity"
    )
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
    pending, halted = _delitem_keyerror_halt(MULTI_PRIOR_STORE)
    assert halted.state is not None, f"{CODEX1}: multi-statement halt dropped state"
    lists = [e for e in halted.state.entries if isinstance(e, ListValue)]
    assert lists == [ListValue((TermValue(9),))], (
        f"{CODEX1}: earlier store not in halt state entries={halted.state.entries!r}"
    )
    assert halted.state is pending.pre_effect_state.state


def test_discrimination_completed_return_is_not_the_delete_keyerror_halt() -> None:
    """Positive twin: in-range delete completes; not a KeyError halt face."""
    tree = _tree(DELITEM_HELPER, "complete_delete.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    pending = function.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: DictValue(((StringValue("a"), TermValue(1)),)),
            key_cid: StringValue("a"),
        }
    )
    assert isinstance(exits.exits[0], Completed)
    assert not isinstance(exits.exits[0], Halted)


# ===========================================================================
# (d) Bound-method delete without shifting coordinates
# ===========================================================================


def test_bound_method_delete_retains_obj_key_demand_not_self() -> None:
    """Method alone: delitem formals are obj/key — self is binder, not demand."""
    tree = _tree(METHOD_DROP, "method_drop_alone.py")
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
    assert names == ("obj", "key"), (
        f"{CODEX3}: delitem formals shifted by self: {names}"
    )
    method_formals = tuple(p.name for p in method.params)
    assert method_formals[0] == "self"
    assert method_formals[1:] == ("obj", "key")
    # Self formal coordinate is not a delitem operand.
    self_coord = method.formal_coordinates()[0]
    assert self_coord.coordinate_cid not in set(
        pending.demand.operand_coordinate_cids
    )


def test_bound_method_delete_callsite_prepends_self_without_shifting_args() -> None:
    """Callsite: self first; obj/key actuals retain discharge order."""
    source = METHOD_DROP + "\nHolder().drop({'a': 1}, 'missing')\n"
    tree = _tree(source)
    calls = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Attribute)
        and node.func.attr == "drop"
    )
    assert len(calls) == 1
    constructed = calls[0].sugar().desugar(None)
    assert isinstance(constructed, Complete), (
        f"{CODEX3}: expected Complete(CallSiteValue), got {type(constructed).__name__}"
    )
    site = constructed.value
    assert isinstance(site, CallSiteValue)
    assert site.parameters == ("self", "obj", "key")
    assert isinstance(site.arg_values[0], ObjectValue)
    assert site.arg_values[0].class_name == "Holder"
    assert len(site.arg_values) == 3
    # Off-by-one twin: dropping self is not the truthful binding.
    off_by_one = site.arg_values[1:]
    assert len(off_by_one) == 2
    assert not (
        isinstance(off_by_one[0], ObjectValue) and off_by_one[0].class_name == "Holder"
    )


def test_bound_method_delete_producer_outcome_halts_with_named_keyerror() -> None:
    """Bound-method producer_outcome publishes KeyError with pre-effect state."""
    source = METHOD_DROP + "\nHolder().drop({'a': 1}, 'missing')\n"
    tree = _tree(source)
    calls = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Attribute)
        and node.func.attr == "drop"
    )
    site = calls[0].sugar().desugar(None).value
    assert isinstance(site, CallSiteValue)
    outcome = site.producer_outcome(None)
    assert isinstance(outcome, ExitSet), (
        f"{CODEX3}: expected ExitSet halt, got {type(outcome).__name__}"
    )
    halted = next((e for e in outcome.exits if isinstance(e, Halted)), None)
    assert halted is not None, f"{CODEX3}: no Halted face in {outcome.exits!r}"
    assert halted.effect.exception_name == "KeyError" or (
        halted.effect.exception_type_coordinate == _identity("KeyError")
    )
    assert halted.effect.occurrence_id is not None or halted.effect.occurrence is not None
    assert halted.state is not None, (
        f"{CODEX1}: bound-method delete halt dropped pre-effect state"
    )


# ===========================================================================
# (e) Lying rollback / fabricated-state twins refuse
# ===========================================================================


def test_fabricated_empty_state_is_not_pre_delete_when_store_preceded() -> None:
    """Bite: multi-statement halt state is not an empty fabricated block."""
    pending, halted = _delitem_keyerror_halt(MULTI_PRIOR_STORE)
    fabricated = _ReducedBlock((), True, ())
    assert halted.state is not None
    assert halted.state is pending.pre_effect_state.state
    with pytest.raises(AssertionError):
        assert halted.state is fabricated
    assert any(isinstance(e, ListValue) for e in halted.state.entries), (
        f"{CODEX1}: prior store absent from entries={halted.state.entries!r}"
    )


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
        assert str(halted.effect.occurrence) == foreign.occurrence


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
