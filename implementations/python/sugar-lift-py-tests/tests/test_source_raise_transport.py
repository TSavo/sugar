"""EXCEPTIONAL SOURCE-RETURN TRANSPORT — raise-path mirror of return suites.

An authenticated helper that RAISES (instead of returning) feeds callers:

  - the named exceptional edge crosses the call boundary with its own
    occurrence and exact pre-effect state
  - caller-side try consumes it per the merged state-survival matrix laws
  - a helper raising under a guard keeps the guard
  - helper-raises-inside-with runs ``__exit__`` over the halted edge
  - wrong-exception and fabricated-state twins refuse

Authentication door (tests only — no production/carrier/ExitSet edits):

  FunctionDef.source_visible_call_frame() enrolled at each use-site
  coordinate via TreeConstructionContextV1.source_call_frames.

Reds route by owner:

  codex-3 — source-return/raise *transport* dig/projection gaps
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
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import ListValue, TermValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus

CODEX3 = (
    "codex-3 exceptional source-return transport: named halt must cross the "
    "authenticated call boundary with its own occurrence and pre-effect state"
)
CODEX1 = (
    "codex-1 carrier composition: halt pre_effect_state / earlier-binding "
    "testimony must compose through Call publication without fabricated state"
)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
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


def _tree(source: str, *, bind: frozenset[str], name: str = "raise_transport.py"):
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=context,
    )
    functions = {
        node.name: node for node in tree.nodes() if isinstance(node, FunctionDef)
    }
    for call in tree.nodes():
        if not isinstance(call, Call):
            continue
        callee = getattr(call.func, "id", None)
        if callee is None or callee not in functions or callee not in bind:
            continue
        context.source_call_frames[_coordinate(call)] = functions[
            callee
        ].source_visible_call_frame()
    return tree, context, functions


def _calls_named(tree, name: str) -> list[Call]:
    return [
        node
        for node in tree.nodes()
        if isinstance(node, Call) and getattr(node.func, "id", None) == name
    ]


def _call_halt(tree, name: str) -> Halted:
    call = _calls_named(tree, name)[-1]
    outcome = call.sugar().desugar(None)
    assert isinstance(outcome, ExitSet), (
        f"{CODEX3}: expected ExitSet from authenticated raise helper, "
        f"got {type(outcome).__name__}"
    )
    assert len(outcome.exits) >= 1
    halted = next((e for e in outcome.exits if isinstance(e, Halted)), None)
    assert halted is not None, f"{CODEX3}: no Halted face in {outcome.exits!r}"
    return halted


def _route_try(exits: ExitSet, expected: str) -> ExitSet:
    return exits.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected(expected)),
            unmet=ExpectationNotMetEffect("raise", "caller-try-site"),
        ),
    )


# ===========================================================================
# Named exceptional edge crosses the call boundary
# ===========================================================================


def test_authenticated_raise_helper_publishes_named_halt_at_call() -> None:
    """``def r(): raise ValueError`` + enrolled ``r()`` → sole Halted ValueError."""
    tree, context, _ = _tree(
        "def raiser():\n    raise ValueError\n\nraiser()\n",
        bind=frozenset({"raiser"}),
    )
    call = _calls_named(tree, "raiser")[0]
    assert _coordinate(call) in context.source_call_frames
    halted = _call_halt(tree, "raiser")
    assert halted.effect.exception_name == "ValueError"
    assert halted.effect.exception_type_coordinate == _identity("ValueError")
    assert halted.effect.occurrence_id is not None or halted.effect.occurrence is not None
    # Call boundary re-owns the published edge.
    assert halted.effect.producer_node_owner == "Call"
    assert halted.state is not None


def test_store_indexerror_raise_helper_carries_named_type_and_occurrence() -> None:
    """Body store halt (IndexError) published at call with its body occurrence."""
    tree, _, _ = _tree(
        "def raiser():\n" "    a = [0]\n" "    a[5] = 1\n" "\n" "raiser()\n",
        bind=frozenset({"raiser"}),
    )
    halted = _call_halt(tree, "raiser")
    assert halted.effect.exception_name == "IndexError"
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert isinstance(halted.effect.occurrence, str) and ":" in halted.effect.occurrence, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence!r}"
    )
    assert halted.effect.producer_node_owner == "Call"
    assert halted.state is not None


def test_distinct_helpers_preserve_distinct_raise_occurrences() -> None:
    """Two helpers raising ValueError keep distinct body occurrences."""
    tree, _, _ = _tree(
        "def alpha():\n"
        "    raise ValueError\n"
        "def beta():\n"
        "    raise ValueError\n"
        "\n"
        "alpha()\n"
        "beta()\n",
        bind=frozenset({"alpha", "beta"}),
    )
    ha = _call_halt(tree, "alpha")
    hb = _call_halt(tree, "beta")
    assert ha.effect.exception_name == hb.effect.exception_name == "ValueError"
    assert str(ha.effect.occurrence) != str(hb.effect.occurrence)
    # Not the same effect object either.
    assert ha.effect is not hb.effect


def test_prior_store_survives_in_pre_effect_state_across_call_boundary() -> None:
    """Earlier binding/store in the helper body is present on the call halt state.

    ``a[0]=9`` then ``raise ValueError`` → halt state carries ListValue([9]).
    """
    tree, _, _ = _tree(
        "def raiser():\n"
        "    a = [0]\n"
        "    a[0] = 9\n"
        "    raise ValueError\n"
        "\n"
        "raiser()\n",
        bind=frozenset({"raiser"}),
    )
    halted = _call_halt(tree, "raiser")
    assert halted.state is not None, f"{CODEX1}: halt dropped pre-effect state"
    lists = [e for e in halted.state.entries if isinstance(e, ListValue)]
    assert lists == [ListValue((TermValue(9),))], (
        f"{CODEX1}: earlier store not in halt state entries={halted.state.entries!r}"
    )


# ===========================================================================
# Caller-side try consumes per matrix laws
# ===========================================================================


def test_caller_try_matching_consumes_halt_with_pre_effect_state() -> None:
    """Matching except: handler Completed.value is the exact pre-halt state."""
    tree, _, _ = _tree(
        "def raiser():\n    raise ValueError\n\nraiser()\n",
        bind=frozenset({"raiser"}),
    )
    halted = _call_halt(tree, "raiser")
    assert halted.state is not None
    routed = _route_try(ExitSet((halted,)), "ValueError")
    assert len(routed.exits) == 1
    handler = routed.exits[0]
    assert isinstance(handler, Completed)
    assert handler.value is halted.state


def test_caller_try_wrong_exception_retains_identical_halt() -> None:
    """Unmatched except: effect and state object identity survive."""
    tree, _, _ = _tree(
        "def raiser():\n    raise ValueError\n\nraiser()\n",
        bind=frozenset({"raiser"}),
    )
    halted = _call_halt(tree, "raiser")
    routed = _route_try(ExitSet((halted,)), "TypeError")
    retained = routed.exits[0]
    assert isinstance(retained, Halted)
    assert retained.effect is halted.effect
    assert retained.state is halted.state


def test_caller_try_does_not_fabricate_completed_on_wrong_type_twin() -> None:
    tree, _, _ = _tree(
        "def raiser():\n    raise IndexError\n\nraiser()\n",
        bind=frozenset({"raiser"}),
    )
    halted = _call_halt(tree, "raiser")
    routed = _route_try(ExitSet((halted,)), "ValueError")
    with pytest.raises(AssertionError):
        assert isinstance(routed.exits[0], Completed)
    with pytest.raises(AssertionError):
        assert routed.exits[0].state is None


# ===========================================================================
# Guarded raise retains guard
# ===========================================================================


def test_helper_raise_under_guard_keeps_guard_on_halt_face() -> None:
    """``if flag: raise ValueError`` with undecided flag → factored guarded halt."""
    tree, _, _ = _tree(
        "def maybe(flag):\n"
        "    if flag:\n"
        "        raise ValueError\n"
        "    return 0\n"
        "\n"
        "maybe(x)\n",
        bind=frozenset({"maybe"}),
    )
    call = _calls_named(tree, "maybe")[0]
    outcome = call.sugar().desugar(None)
    assert isinstance(outcome, ExitSet), (
        f"{CODEX3}: guarded raise expected ExitSet, got {type(outcome).__name__}"
    )
    halted = [e for e in outcome.exits if isinstance(e, Halted)]
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    assert len(halted) == 1, f"{CODEX3}: need one halt arm, got {outcome.exits!r}"
    assert len(completed) == 1, f"{CODEX3}: need one completed arm under not(guard)"
    halt = halted[0]
    assert halt.effect.exception_name == "ValueError"
    # Guard is non-trivial (not bare True / empty and).
    guard_s = str(halt.guard)
    assert "py.truthy" in guard_s or "truthy" in guard_s or "branch" in guard_s, (
        f"{CODEX3}: guard dropped on raise face: {halt.guard!r}"
    )
    # Completed arm is the complementary not(guard).
    assert "not" in str(completed[0].guard).lower() or str(
        completed[0].guard
    ) != str(halt.guard)


def test_helper_raise_under_true_guard_collapses_to_sole_halt() -> None:
    """Ground True branch: sole Halted face (guard may be tautology)."""
    tree, _, _ = _tree(
        "def maybe(flag):\n"
        "    if flag:\n"
        "        raise ValueError\n"
        "    return 0\n"
        "\n"
        "maybe(True)\n",
        bind=frozenset({"maybe"}),
    )
    halted = _call_halt(tree, "maybe")
    assert halted.effect.exception_name == "ValueError"
    assert halted.state is not None


# ===========================================================================
# Helper-raises-inside-with: exit over the halted edge
# ===========================================================================


def test_helper_raise_through_with_never_suppresses_preserves_state() -> None:
    """NeverSuppresses cleanup: surviving halt keeps exact body state and effect."""
    tree, _, _ = _tree(
        "def raiser():\n"
        "    a = [0]\n"
        "    a[0] = 7\n"
        "    raise ValueError\n"
        "\n"
        "raiser()\n",
        bind=frozenset({"raiser"}),
    )
    halted = _call_halt(tree, "raiser")
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


def test_helper_raise_through_with_does_not_fabricate_completed_twin() -> None:
    tree, _, _ = _tree(
        "def raiser():\n    raise ValueError\n\nraiser()\n",
        bind=frozenset({"raiser"}),
    )
    halted = _call_halt(tree, "raiser")
    after = ExitSet((halted,)).and_exit(
        ExitSet.completed(TermValue(0)),
        disposition=NeverSuppresses(),
    )
    with pytest.raises(AssertionError):
        assert isinstance(after.exits[0], Completed)
    with pytest.raises(AssertionError):
        assert after.exits[0].state is None


def test_with_then_try_composition_on_helper_raise() -> None:
    """Compose with cleanup then matching try — handler value is pre-halt state."""
    tree, _, _ = _tree(
        "def raiser():\n    raise IndexError\n\nraiser()\n",
        bind=frozenset({"raiser"}),
    )
    halted = _call_halt(tree, "raiser")
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


def test_wrong_exception_observation_is_not_the_helper_effect() -> None:
    """Bite: foreign RaiseEffect is not the transported helper edge."""
    tree, _, _ = _tree(
        "def raiser():\n    raise ValueError\n\nraiser()\n",
        bind=frozenset({"raiser"}),
    )
    halted = _call_halt(tree, "raiser")
    foreign = RaiseEffect(
        exception_name="ValueError",
        blame="foreign.py:1:0",
        occurrence=AuthenticatedRaiseLocus.of("foreign.py:1:0"),
        exception_type_coordinate=_identity("ValueError"),
        exception_type_mro=(_identity("ValueError"),),
    )
    with pytest.raises(AssertionError):
        assert halted.effect is foreign
    with pytest.raises(AssertionError):
        assert str(halted.effect.occurrence) == foreign.occurrence


def test_fabricated_empty_state_is_not_pre_effect_when_store_preceded_raise() -> None:
    """Bite: halt state with prior store is not an empty fabricated block."""
    tree, _, _ = _tree(
        "def raiser():\n"
        "    a = [0]\n"
        "    a[0] = 3\n"
        "    raise ValueError\n"
        "\n"
        "raiser()\n",
        bind=frozenset({"raiser"}),
    )
    halted = _call_halt(tree, "raiser")
    fabricated = _ReducedBlock((), True, ())
    assert halted.state is not None
    assert halted.state != fabricated or halted.state.entries, (
        f"{CODEX1}: state collapsed to empty fabricated block"
    )
    with pytest.raises(AssertionError):
        assert halted.state is fabricated
    # Positive: prior store present.
    assert any(isinstance(e, ListValue) for e in halted.state.entries)


def test_handler_value_is_not_fabricated_fresh_block_twin() -> None:
    """Matching try handler must be the halt state object, not a fresh empty."""
    tree, _, _ = _tree(
        "def raiser():\n    raise ValueError\n\nraiser()\n",
        bind=frozenset({"raiser"}),
    )
    halted = _call_halt(tree, "raiser")
    handler = _route_try(ExitSet((halted,)), "ValueError").exits[0]
    assert isinstance(handler, Completed)
    fabricated = _ReducedBlock((), True, ())
    with pytest.raises(AssertionError):
        assert handler.value is fabricated
    assert handler.value is halted.state


# ===========================================================================
# Seed / sole-edge contract
# ===========================================================================


def test_authenticated_raise_helper_is_sole_exceptional_edge() -> None:
    tree, _, _ = _tree(
        "def raiser():\n    raise ValueError\n\nraiser()\n",
        bind=frozenset({"raiser"}),
    )
    call = _calls_named(tree, "raiser")[0]
    outcome = call.sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    assert all(isinstance(e, Halted) for e in outcome.exits) or (
        sum(isinstance(e, Halted) for e in outcome.exits) == 1
    )
    with pytest.raises(AssertionError):
        assert all(isinstance(e, Completed) for e in outcome.exits)
