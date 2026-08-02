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

    Raiser().boom()

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
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute, Call
from sugar_source_tree.tree import SourceFile

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
    constructed = calls[-1].sugar().desugar(None)
    assert isinstance(constructed, Complete), (
        f"{CODEX3}: bound-method Call must construct Complete(CallSiteValue), "
        f"got {type(constructed).__name__}"
    )
    assert isinstance(constructed.value, CallSiteValue), constructed.value
    site = constructed.value
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
    return (
        "class Raiser:\n"
        f"    def boom(self):\n"
        f"        raise {exception}\n"
    )


# ===========================================================================
# Named exceptional edge crosses the bound-method call boundary
# ===========================================================================


def test_bound_method_raise_publishes_named_halt_at_call() -> None:
    """``Raiser().boom()`` body ``raise ValueError`` → sole Halted ValueError."""
    source = _raise_body() + "\nRaiser().boom()\n"
    site = _method_callsite(source)
    assert site.arg_values[0].class_name == "Raiser"
    halted = _method_halt(source)
    assert halted.effect.exception_name == "ValueError"
    assert halted.effect.exception_type_coordinate == _identity("ValueError")
    assert (
        halted.effect.occurrence_id is not None
        or halted.effect.occurrence is not None
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
        "        a[5] = 1\n"
        "\n"
        "Raiser().boom()\n"
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
        "        raise ValueError\n"
        "\n"
        "Raiser().alpha()\n"
        "Raiser().beta()\n"
    )
    ha = _method_halt(source, "alpha")
    hb = _method_halt(source, "beta")
    assert ha.effect.exception_name == hb.effect.exception_name == "ValueError"
    assert str(ha.effect.occurrence) != str(hb.effect.occurrence), (
        f"{CODEX3}: distinct methods must not share occurrence "
        f"{ha.effect.occurrence!r}"
    )
    assert ha.effect is not hb.effect


def test_prior_store_survives_in_pre_effect_state_across_method_call() -> None:
    """Earlier binding/store in the method body is present on the call halt state.

    ``a[0]=9`` then ``raise ValueError`` → halt state carries ListValue([9]).
    """
    source = (
        "class Raiser:\n"
        "    def boom(self):\n"
        "        a = [0]\n"
        "        a[0] = 9\n"
        "        raise ValueError\n"
        "\n"
        "Raiser().boom()\n"
    )
    halted = _method_halt(source)
    assert halted.state is not None, f"{CODEX1}: halt dropped pre-effect state"
    lists = [e for e in halted.state.entries if isinstance(e, ListValue)]
    assert lists == [ListValue((TermValue(9),))], (
        f"{CODEX1}: earlier store not in halt state entries={halted.state.entries!r}"
    )


# ===========================================================================
# Caller-side try consumes per matrix laws
# ===========================================================================


def test_caller_try_matching_consumes_method_halt_with_pre_effect_state() -> None:
    """Matching except: handler Completed.value is the exact pre-halt state."""
    source = _raise_body() + "\nRaiser().boom()\n"
    halted = _method_halt(source)
    assert halted.state is not None
    routed = _route_try(ExitSet((halted,)), "ValueError")
    assert len(routed.exits) == 1
    handler = routed.exits[0]
    assert isinstance(handler, Completed)
    assert handler.value is halted.state


def test_caller_try_wrong_exception_retains_identical_method_halt() -> None:
    """Unmatched except: effect and state object identity survive."""
    source = _raise_body() + "\nRaiser().boom()\n"
    halted = _method_halt(source)
    routed = _route_try(ExitSet((halted,)), "TypeError")
    retained = routed.exits[0]
    assert isinstance(retained, Halted)
    assert retained.effect is halted.effect
    assert retained.state is halted.state


def test_caller_try_does_not_fabricate_completed_on_wrong_type_twin() -> None:
    source = _raise_body("IndexError") + "\nRaiser().boom()\n"
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
        "        return 0\n"
        "\n"
        "Raiser().boom(x)\n"
    )
    outcome = _method_outcome(source)
    assert isinstance(outcome, ExitSet), (
        f"{CODEX3}: guarded method raise expected ExitSet, "
        f"got {type(outcome).__name__}"
    )
    halted = [e for e in outcome.exits if isinstance(e, Halted)]
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    assert len(halted) == 1, f"{CODEX3}: need one halt arm, got {outcome.exits!r}"
    assert len(completed) == 1, f"{CODEX3}: need one completed arm under not(guard)"
    halt = halted[0]
    assert halt.effect.exception_name == "ValueError"
    guard_s = str(halt.guard)
    assert "py.truthy" in guard_s or "truthy" in guard_s or "branch" in guard_s, (
        f"{CODEX3}: guard dropped on method raise face: {halt.guard!r}"
    )
    assert "not" in str(completed[0].guard).lower() or str(
        completed[0].guard
    ) != str(halt.guard)


def test_method_raise_under_true_guard_collapses_to_sole_halt() -> None:
    """Ground True branch: sole Halted face (guard may be tautology)."""
    source = (
        "class Raiser:\n"
        "    def boom(self, flag):\n"
        "        if flag:\n"
        "            raise ValueError\n"
        "        return 0\n"
        "\n"
        "Raiser().boom(True)\n"
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
        "        raise ValueError\n"
        "\n"
        "Raiser().boom()\n"
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
    lists = [e for e in surviving.state.entries if isinstance(e, ListValue)]
    assert lists == [ListValue((TermValue(7),))]


def test_method_raise_through_with_does_not_fabricate_completed_twin() -> None:
    source = _raise_body() + "\nRaiser().boom()\n"
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
    source = _raise_body("IndexError") + "\nRaiser().boom()\n"
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
    source = _raise_body() + "\nRaiser().boom()\n"
    halted = _method_halt(source)
    foreign = RaiseEffect.for_builtin("ValueError",
        
        blame="foreign.py:1:0",
        occurrence="foreign.py:1:0",
        exception_type_mro=(_identity("ValueError"),),
    )
    with pytest.raises(AssertionError):
        assert halted.effect is foreign
    with pytest.raises(AssertionError):
        assert str(halted.effect.occurrence) == foreign.occurrence


def test_fabricated_empty_state_is_not_pre_effect_when_store_preceded_raise() -> None:
    """Bite: halt state with prior store is not an empty fabricated block."""
    source = (
        "class Raiser:\n"
        "    def boom(self):\n"
        "        a = [0]\n"
        "        a[0] = 3\n"
        "        raise ValueError\n"
        "\n"
        "Raiser().boom()\n"
    )
    halted = _method_halt(source)
    fabricated = _ReducedBlock((), True, ())
    assert halted.state is not None, f"{CODEX1}: missing pre-effect state"
    assert halted.state != fabricated or halted.state.entries, (
        f"{CODEX1}: state collapsed to empty fabricated block"
    )
    with pytest.raises(AssertionError):
        assert halted.state is fabricated
    assert any(isinstance(e, ListValue) for e in halted.state.entries), (
        f"{CODEX1}: prior store absent from entries={halted.state.entries!r}"
    )


def test_handler_value_is_not_fabricated_fresh_block_twin() -> None:
    """Matching try handler must be the halt state object, not a fresh empty."""
    source = _raise_body() + "\nRaiser().boom()\n"
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
        "        return 7\n"
        "\n"
        "Raiser().boom()\n"
    )
    site = _method_callsite(source)
    outcome = site.producer_outcome(None)
    if isinstance(outcome, ExitSet):
        assert not any(
            isinstance(e, Halted) and e.effect.exception_name == "ValueError"
            for e in outcome.exits
        ), f"{CODEX3}: completed method must not publish ValueError halt"
    else:
        assert isinstance(outcome, Complete)


# ===========================================================================
# Self binding does not invent the exceptional edge
# ===========================================================================


def test_self_binding_is_present_but_not_the_exception_identity() -> None:
    """Bound self is prepended; exception identity is ValueError, not the receiver."""
    source = _raise_body() + "\nRaiser().boom()\n"
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
    source = _raise_body() + "\nRaiser().boom()\n"
    outcome = _method_outcome(source)
    assert isinstance(outcome, ExitSet)
    assert sum(isinstance(e, Halted) for e in outcome.exits) == 1, (
        f"{CODEX3}: expected sole Halted edge, got {outcome.exits!r}"
    )
    with pytest.raises(AssertionError):
        assert all(isinstance(e, Completed) for e in outcome.exits)
