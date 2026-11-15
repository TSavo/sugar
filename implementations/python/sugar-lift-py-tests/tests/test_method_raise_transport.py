"""EXCEPTIONAL BOUND-METHOD RAISE TRANSPORT — raise-path mirror of method returns.

A bound method that RAISES (instead of returning) feeds callers:

  - the named exceptional edge crosses the method-call boundary with its own
    occurrence and exact pre-effect state
  - caller-side try consumes it per the merged state-survival matrix laws
  - a method raising under a guard keeps the guard
  - method-raises-inside-with runs ``__exit__`` over the halted edge
  - wrong-exception and fabricated-state twins refuse

Concrete program:

    class Raiser:
        def boom(self):
            raise ValueError

    def caller():
        Raiser().boom()

The call stands in a function, called after import, never in the module body:
the receiver ``Raiser()`` is read as every read of a module class's name is,
through the class statement's key in the module's one run (#7757 item 21).  A
module body whose last statement raises completes on no arm, so no import
completes and that read is the run's halts (``module_run_halts``), never a
class: the method call under test would have no receiver.

Transport door (tests only — no production/binder/carrier/ExitSet edits):

  Bound-method ``CallSiteValue.producer_outcome`` publishes the body halt as
  ``ExitSet(Halted(...))`` with ``producer_node_owner == "Call"``.

Reds route by owner:

  codex-3 — method-return/raise *transport* dig/projection gaps
  codex-1 — carrier / pre_effect composition gaps

When a face cannot go green, the failure message names which owner.
"""

from __future__ import annotations

import pytest

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
from sugar_lift_py_tests.floor import CallSiteValue, ListValue, ObjectValue, TermValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute, Call
from sugar_source_tree.tree import SourceFile
from test_method_call_application_twins import bound_method_call_at

CODEX3 = (
    "codex-3 exceptional method-raise transport: named halt must cross the "
    "bound-method call boundary with its own occurrence and pre-effect state"
)
CODEX1 = (
    "codex-1 carrier composition: halt pre_effect_state / earlier-binding "
    "testimony must compose through method Call publication without "
    "fabricated state"
)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


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


def _tree(source: str, name: str = "method_raise_transport.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _method_callsite(source: str, attr: str = "boom") -> CallSiteValue:
    tree = _tree(source)
    calls = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Attribute)
        and node.func.attr == attr
    )
    assert len(calls) >= 1, (attr, source)
    # #7756: the Call applies the method body itself; the binding under test
    # is that call as bound, before the application.
    site = bound_method_call_at(calls[-1])
    assert site.parameters[0] == "self"
    assert isinstance(site.arg_values[0], ObjectValue)
    return site


def _method_halt(source: str, attr: str = "boom") -> Halted:
    site = _method_callsite(source, attr)
    outcome = site.producer_outcome(None)
    assert isinstance(outcome, ExitSet), (
        f"{CODEX3}: expected ExitSet from bound-method raise, "
        f"got {type(outcome).__name__}"
    )
    halted = next((e for e in outcome.exits if isinstance(e, Halted)), None)
    assert halted is not None, f"{CODEX3}: no Halted face in {outcome.exits!r}"
    return halted


def _method_outcome(source: str, attr: str = "boom"):
    return _method_callsite(source, attr).producer_outcome(None)


def _route_try(exits: ExitSet, expected: str) -> ExitSet:
    return exits.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected(expected)),
            unmet=ExpectationNotMetEffect("raise", "caller-try-site"),
        ),
    )


def _raise_body(exception: str = "ValueError") -> str:
    return "class Raiser:\n" f"    def boom(self):\n" f"        raise {exception}\n"


def _caller(*calls: str, formals: str = "") -> str:
    """``calls`` as the body of a function called after import, so the
    module's one run completes and binds every class it defines (see the
    module docstring)."""
    return f"\n\ndef caller({formals}):\n" + "".join(f"    {call}\n" for call in calls)


# ===========================================================================
# Named exceptional edge crosses the bound-method call boundary
# ===========================================================================


def test_bound_method_raise_publishes_named_halt_at_call() -> None:
    """``Raiser().boom()`` body ``raise ValueError`` → sole Halted ValueError."""
    source = _raise_body() + _caller("Raiser().boom()")
    site = _method_callsite(source)
    assert site.arg_values[0].class_name == "Raiser"
    halted = _method_halt(source)
    assert halted.effect.exception_name == "ValueError"
    assert halted.effect.exception_type_coordinate == _identity("ValueError")
    assert (
        halted.effect.occurrence_id is not None or halted.effect.occurrence is not None
    ), f"{CODEX3}: halt missing occurrence"
    # Call boundary re-owns the published edge.
    assert halted.effect.producer_node_owner == "Call"
    assert halted.state is not None, f"{CODEX1}: halt dropped pre-effect state"


def test_method_store_indexerror_carries_named_type_and_occurrence() -> None:
    """Body store halt (IndexError) published at method call with occurrence."""
    source = (
        "class Raiser:\n"
        "    def boom(self):\n"
        "        a = [0]\n"
        "        a[5] = 1\n" + _caller("Raiser().boom()")
    )
    halted = _method_halt(source)
    assert halted.effect.exception_name == "IndexError"
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert halted.effect.producer_node_owner == "Call"
    assert halted.state is not None, f"{CODEX1}: IndexError halt dropped state"


def test_distinct_methods_preserve_distinct_raise_occurrences() -> None:
    """Two methods raising ValueError keep distinct body occurrences."""
    source = (
        "class Raiser:\n"
        "    def alpha(self):\n"
        "        raise ValueError\n"
        "    def beta(self):\n"
        "        raise ValueError\n" + _caller("Raiser().alpha()", "Raiser().beta()")
    )
    ha = _method_halt(source, "alpha")
    hb = _method_halt(source, "beta")
    assert ha.effect.exception_name == hb.effect.exception_name == "ValueError"
    assert str(ha.effect.occurrence) != str(hb.effect.occurrence), (
        f"{CODEX3}: distinct methods must not share occurrence "
        f"{ha.effect.occurrence!r}"
    )
    assert ha.effect is not hb.effect


def test_a_callee_local_store_stays_behind_at_the_method_call() -> None:
    """The halt's record at the call is the caller's, never the callee's.

    ``a = [0]; a[0] = 9; raise ValueError``: ``a`` is the method's own local.
    A halt raised in a callee reaches its caller at the call
    (``call_site_value.at_the_call``), carrying only what the callee did to
    objects the caller can see (``caller_visible_values``, #8136, #8257);
    the callee's locals and keys stay behind. The list was never the
    caller's, so the record at the call holds no ``ListValue`` -- the
    callee's ``[9]`` on it was the callee frame leaking into the caller.
    """
    source = (
        "class Raiser:\n"
        "    def boom(self):\n"
        "        a = [0]\n"
        "        a[0] = 9\n"
        "        raise ValueError\n" + _caller("Raiser().boom()")
    )
    halted = _method_halt(source)
    assert halted.state is not None, f"{CODEX1}: halt dropped pre-effect state"
    lists = [e for e in halted.state.entries if isinstance(e, ListValue)]
    assert lists == [], (
        f"{CODEX1}: a callee local reached the caller's record "
        f"entries={halted.state.entries!r}"
    )


# ===========================================================================
# Caller-side try consumes per matrix laws
# ===========================================================================


def test_caller_try_matching_consumes_method_halt_with_pre_effect_state() -> None:
    """Matching except: handler Completed.value is the exact pre-halt state."""
    source = _raise_body() + _caller("Raiser().boom()")
    halted = _method_halt(source)
    assert halted.state is not None
    routed = _route_try(ExitSet((halted,)), "ValueError")
    assert len(routed.exits) == 1
    handler = routed.exits[0]
    assert isinstance(handler, Completed)
    assert handler.value is halted.state


def test_caller_try_wrong_exception_retains_identical_method_halt() -> None:
    """Unmatched except: effect and state object identity survive."""
    source = _raise_body() + _caller("Raiser().boom()")
    halted = _method_halt(source)
    routed = _route_try(ExitSet((halted,)), "TypeError")
    retained = routed.exits[0]
    assert isinstance(retained, Halted)
    assert retained.effect is halted.effect
    assert retained.state is halted.state


def test_caller_try_does_not_fabricate_completed_on_wrong_type_twin() -> None:
    source = _raise_body("IndexError") + _caller("Raiser().boom()")
    halted = _method_halt(source)
    routed = _route_try(ExitSet((halted,)), "ValueError")
    with pytest.raises(AssertionError):
        assert isinstance(routed.exits[0], Completed)
    with pytest.raises(AssertionError):
        assert routed.exits[0].state is None


# ===========================================================================
# Guarded raise retains guard
# ===========================================================================


def test_method_raise_under_guard_keeps_guard_on_halt_face() -> None:
    """``if flag: raise ValueError`` with undecided flag → factored guarded halt."""
    source = (
        "class Raiser:\n"
        "    def boom(self, flag):\n"
        "        if flag:\n"
        "            raise ValueError\n"
        "        return 0\n" + _caller("Raiser().boom(x)", formals="x")
    )
    outcome = _method_outcome(source)
    assert isinstance(outcome, ExitSet), (
        f"{CODEX3}: guarded method raise expected ExitSet, "
        f"got {type(outcome).__name__}"
    )
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect

    halted = [e for e in outcome.exits if isinstance(e, Halted)]
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    # ``if flag:`` tests the truth of an undecided ``x``: ``bool(x)`` runs the
    # value's own ``__bool__``/``__len__``, which may raise.  That face is the
    # test's, carried beside the raise: an undetermined raise at the ``if``,
    # under the truth test not completing, never dropped.
    named = [e for e in halted if not isinstance(e.effect, UndeterminedRaiseEffect)]
    truth = [e for e in halted if isinstance(e.effect, UndeterminedRaiseEffect)]
    assert len(named) == 1, f"{CODEX3}: need one named halt arm, got {outcome.exits!r}"
    assert len(truth) == 1, f"{CODEX3}: the truth test's own face, got {outcome.exits!r}"
    assert truth[0].effect.producer_node_owner == "IfSugar.test"
    assert "python:truth.completes" in str(truth[0].guard)
    assert len(completed) == 1, f"{CODEX3}: need one completed arm under not(guard)"
    halt = named[0]
    assert halt.effect.exception_name == "ValueError"
    guard_s = str(halt.guard)
    assert (
        "py.truthy" in guard_s or "truthy" in guard_s or "branch" in guard_s
    ), f"{CODEX3}: guard dropped on method raise face: {halt.guard!r}"
    assert "not" in str(completed[0].guard).lower() or str(completed[0].guard) != str(
        halt.guard
    )


def test_method_raise_under_true_guard_collapses_to_sole_halt() -> None:
    """Ground True branch: sole Halted face (guard may be tautology)."""
    source = (
        "class Raiser:\n"
        "    def boom(self, flag):\n"
        "        if flag:\n"
        "            raise ValueError\n"
        "        return 0\n" + _caller("Raiser().boom(True)")
    )
    halted = _method_halt(source)
    assert halted.effect.exception_name == "ValueError"
    assert halted.state is not None, f"{CODEX1}: sole True-guard halt dropped state"


# ===========================================================================
# Method-raises-inside-with: exit over the halted edge
# ===========================================================================


def test_method_raise_through_with_never_suppresses_preserves_state() -> None:
    """NeverSuppresses cleanup: surviving halt keeps exact body state and effect."""
    source = (
        "class Raiser:\n"
        "    def boom(self):\n"
        "        a = [0]\n"
        "        a[0] = 7\n"
        "        raise ValueError\n" + _caller("Raiser().boom()")
    )
    halted = _method_halt(source)
    assert halted.state is not None
    after = ExitSet((halted,)).and_exit(
        ExitSet.completed(TermValue(0)),
        disposition=NeverSuppresses(),
    )
    assert len(after.exits) == 1
    surviving = after.exits[0]
    assert isinstance(surviving, Halted)
    assert surviving.effect is halted.effect
    assert surviving.state is halted.state
    # ``a`` is the method's local: the record at the call never holds it
    # (``at_the_call``; see the callee-local twin above).
    lists = [e for e in surviving.state.entries if isinstance(e, ListValue)]
    assert lists == []


def test_method_raise_through_with_does_not_fabricate_completed_twin() -> None:
    source = _raise_body() + _caller("Raiser().boom()")
    halted = _method_halt(source)
    after = ExitSet((halted,)).and_exit(
        ExitSet.completed(TermValue(0)),
        disposition=NeverSuppresses(),
    )
    with pytest.raises(AssertionError):
        assert isinstance(after.exits[0], Completed)
    with pytest.raises(AssertionError):
        assert after.exits[0].state is None


def test_with_then_try_composition_on_method_raise() -> None:
    """Compose with cleanup then matching try — handler value is pre-halt state."""
    source = _raise_body("IndexError") + _caller("Raiser().boom()")
    halted = _method_halt(source)
    after_with = ExitSet((halted,)).and_exit(
        ExitSet.completed(TermValue(0)),
        disposition=NeverSuppresses(),
    )
    surviving = after_with.exits[0]
    assert isinstance(surviving, Halted)
    assert surviving.state is halted.state
    handler_set = _route_try(after_with, "IndexError")
    handler = handler_set.exits[0]
    assert isinstance(handler, Completed)
    assert handler.value is halted.state


# ===========================================================================
# Wrong-exception and fabricated-state twins
# ===========================================================================


def test_wrong_exception_observation_is_not_the_method_effect() -> None:
    """Bite: foreign RaiseEffect is not the transported method edge."""
    source = _raise_body() + _caller("Raiser().boom()")
    halted = _method_halt(source)
    foreign = RaiseEffect.for_builtin(
        "ValueError",
        blame="foreign.py:1:0",
        occurrence="foreign.py:1:0",
        exception_type_mro=(_identity("ValueError"),),
    )
    with pytest.raises(AssertionError):
        assert halted.effect is foreign
    with pytest.raises(AssertionError):
        assert str(halted.effect.occurrence) == foreign.occurrence


def test_handler_value_is_not_fabricated_fresh_block_twin() -> None:
    """Matching try handler must be the halt state object, not a fresh empty."""
    source = _raise_body() + _caller("Raiser().boom()")
    halted = _method_halt(source)
    handler = _route_try(ExitSet((halted,)), "ValueError").exits[0]
    assert isinstance(handler, Completed)
    fabricated = _ReducedBlock((), True, ())
    with pytest.raises(AssertionError):
        assert handler.value is fabricated
    assert handler.value is halted.state


def test_discrimination_completed_return_is_not_valueerror_halt() -> None:
    """Positive twin returns; must not be a ValueError halt."""
    source = (
        "class Raiser:\n"
        "    def boom(self):\n"
        "        return 7\n" + _caller("Raiser().boom()")
    )
    site = _method_callsite(source)
    outcome = site.producer_outcome(None)
    assert isinstance(outcome, ExitSet), outcome
    assert not any(
        isinstance(e, Halted) and e.effect.exception_name == "ValueError"
        for e in outcome.exits
    ), f"{CODEX3}: completed method must not publish ValueError halt"


# ===========================================================================
# Self binding does not invent the exceptional edge
# ===========================================================================


def test_self_binding_is_present_but_not_the_exception_identity() -> None:
    """Bound self is prepended; exception identity is ValueError, not the receiver."""
    source = _raise_body() + _caller("Raiser().boom()")
    site = _method_callsite(source)
    assert site.parameters[0] == "self"
    assert isinstance(site.arg_values[0], ObjectValue)
    assert site.arg_values[0].class_name == "Raiser"
    halted = _method_halt(source)
    assert halted.effect.exception_type_coordinate == _identity("ValueError")
    assert halted.effect.exception_name != "Raiser"


# ===========================================================================
# Seed / sole-edge contract
# ===========================================================================


def test_bound_method_raise_is_sole_exceptional_edge() -> None:
    source = _raise_body() + _caller("Raiser().boom()")
    outcome = _method_outcome(source)
    assert isinstance(outcome, ExitSet)
    assert (
        sum(isinstance(e, Halted) for e in outcome.exits) == 1
    ), f"{CODEX3}: expected sole Halted edge, got {outcome.exits!r}"
    with pytest.raises(AssertionError):
        assert all(isinstance(e, Completed) for e in outcome.exits)
