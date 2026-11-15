"""A SAME-FILE HELPER THAT RAISES: its row states the halt, the call names none.

A call of a same-file function is its coordinate and edge, joined at prove
(#7757 steps 5 and 6, the owner's ruling "Edge, join at prove", #8705; the
application of a callee body at lift is deleted, #8751, and with it the
projection of a followed callee's halt and effects into its caller, #8739).
So a helper's raise is stated in one place, the helper's own contract row
(``function_universe_outcome``): a halt with its named type, its own
occurrence and its record.  At the call the lift has only the unanswered
call's complement face, whose exception type nothing at the lift decides;
prove types it from the callee's contract under the call's actuals (step 7,
#8749, ``test_handler_around_a_same_file_raise_twins``).

What a caller's ``try`` and a ``with``'s cleanup do with a named halt is
ExitSet law and is checked here on the helper row's own halt:

  - a matching handler consumes it and continues from its record
  - an unmatched handler keeps the halt, effect and record identical
  - ``NeverSuppresses`` cleanup keeps it; a wrong type never completes
  - foreign and fabricated testimony is never the halt

This suite used to read the helper's halt at the call (re-owned by
``Call``, stamped with the call frame, filtered to caller-visible values:
``call_owned``, ``at_the_call``, ``caller_visible_values``); those reads are
deleted with the mechanism.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
    NeverSuppresses,
)
from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.effect.name_error_effect import NameErrorEffect
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus


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


def _tree(source: str, *, name: str = "raise_transport.py"):
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=context,
    )
    functions = {
        node.name: node for node in tree.nodes() if isinstance(node, FunctionDef)
    }
    return tree, context, functions


def _calls_named(tree, name: str) -> list[Call]:
    return [
        node
        for node in tree.nodes()
        if isinstance(node, Call) and getattr(node.func, "id", None) == name
    ]


def _row_halt(functions, name: str) -> Halted:
    """The one halt of ``name``'s own contract row: a helper that only
    raises halts on every arm of its row, and on none completes."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    outcome = function_universe_outcome(functions[name])
    assert isinstance(outcome, ExitSet), type(outcome)
    assert not [e for e in outcome.exits if isinstance(e, Completed)], outcome
    (halted,) = outcome.halts()
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
# The helper's row states its named halt; the call names none
# ===========================================================================


def test_a_raising_helpers_row_states_its_named_halt() -> None:
    """``def raiser(): raise ValueError`` → its row's sole halt, ValueError."""
    _, _, functions = _tree(
        "def raiser():\n    raise ValueError\n\nraiser()\n",
    )
    halted = _row_halt(functions, "raiser")
    assert halted.effect.exception_name == "ValueError"
    assert halted.effect.exception_type_coordinate == _identity("ValueError")
    assert (
        halted.effect.occurrence_id is not None or halted.effect.occurrence is not None
    )
    assert halted.state is not None


def test_the_call_of_a_raising_helper_names_no_type_at_lift() -> None:
    """``raiser()`` is its coordinate and edge: its halt is the unanswered
    call's complement face.  Which exception it is, is decided at prove from
    ``raiser``'s contract (step 7, #8749); this used to be the helper's
    ``ValueError`` re-owned at the call."""
    tree, _, _ = _tree(
        "def raiser():\n    raise ValueError\n\nraiser()\n",
    )
    outcome = _calls_named(tree, "raiser")[-1].sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    assert outcome.halts()
    assert [halt.effect.exception_name for halt in outcome.halts()] == [None]


def test_a_store_indexerror_is_the_rows_halt_at_the_stores_own_site() -> None:
    """Body store halt (IndexError) at the store's own ``file:line:col``."""
    _, _, functions = _tree(
        "def raiser():\n" "    a = [0]\n" "    a[5] = 1\n" "\n" "raiser()\n",
    )
    halted = _row_halt(functions, "raiser")
    assert halted.effect.exception_name == "IndexError"
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    # ``a[5] = 1``: line 3, column 4 (``AuthenticatedRaiseLocus.of``).
    assert str(halted.effect.occurrence_id).startswith("raise_transport.py:3:4")
    assert halted.state is not None


def test_distinct_helpers_preserve_distinct_raise_occurrences() -> None:
    """Two helpers raising ValueError keep distinct body occurrences."""
    _, _, functions = _tree(
        "def alpha():\n"
        "    raise ValueError\n"
        "def beta():\n"
        "    raise ValueError\n"
        "\n"
        "alpha()\n"
        "beta()\n",
    )
    ha = _row_halt(functions, "alpha")
    hb = _row_halt(functions, "beta")
    assert ha.effect.exception_name == hb.effect.exception_name == "ValueError"
    assert str(ha.effect.occurrence) != str(hb.effect.occurrence)
    # Not the same effect object either.
    assert ha.effect is not hb.effect


# ===========================================================================
# A try consumes a named halt per the matrix laws
# ===========================================================================


def test_a_matching_try_consumes_the_halt_with_its_record() -> None:
    """Matching except: handler Completed.value is the exact pre-halt record."""
    _, _, functions = _tree(
        "def raiser():\n    raise ValueError\n\nraiser()\n",
    )
    halted = _row_halt(functions, "raiser")
    assert halted.state is not None
    routed = _route_try(ExitSet((halted,)), "ValueError")
    assert len(routed.exits) == 1
    handler = routed.exits[0]
    assert isinstance(handler, Completed)
    assert handler.value is halted.state


def test_caller_try_wrong_exception_retains_identical_halt() -> None:
    """Unmatched except: effect and state object identity survive."""
    _, _, functions = _tree(
        "def raiser():\n    raise ValueError\n\nraiser()\n",
    )
    halted = _row_halt(functions, "raiser")
    routed = _route_try(ExitSet((halted,)), "TypeError")
    retained = routed.exits[0]
    assert isinstance(retained, Halted)
    assert retained.effect is halted.effect
    assert retained.state is halted.state


def test_caller_try_does_not_fabricate_completed_on_wrong_type_twin() -> None:
    _, _, functions = _tree(
        "def raiser():\n    raise IndexError\n\nraiser()\n",
    )
    halted = _row_halt(functions, "raiser")
    routed = _route_try(ExitSet((halted,)), "ValueError")
    with pytest.raises(AssertionError):
        assert isinstance(routed.exits[0], Completed)
    with pytest.raises(AssertionError):
        assert routed.exits[0].state is None


# ===========================================================================
# An actual nothing binds
# ===========================================================================


def test_an_actual_nothing_binds_raises_before_the_helper_is_entered() -> None:
    """``maybe(x)`` where nothing binds ``x``: ``NameError`` at the actual.

    A name nothing binds is no undecided flag: Python evaluates the actual
    before the call, the read raises ``NameError`` (``NameSugar.desugar``),
    and ``maybe`` is never entered. So the call is that one halt: no
    ``ValueError`` arm from the helper's ``if flag: raise``, and no completed
    arm.
    """
    tree, _, _ = _tree(
        "def maybe(flag):\n"
        "    if flag:\n"
        "        raise ValueError\n"
        "    return 0\n"
        "\n"
        "maybe(x)\n",
    )
    call = _calls_named(tree, "maybe")[0]
    outcome = call.sugar().desugar(None)
    assert isinstance(
        outcome, ExitSet
    ), f"unbound actual expected ExitSet, got {type(outcome).__name__}"
    assert len(outcome.exits) == 1, outcome.exits
    halt = outcome.exits[0]
    assert isinstance(halt, Halted), outcome.exits
    assert isinstance(halt.effect, NameErrorEffect), halt.effect
    assert halt.effect.exception_name == "NameError"
    assert halt.effect.name == "x"


# ===========================================================================
# A with's cleanup over a named halt
# ===========================================================================


def test_never_suppresses_cleanup_keeps_the_halt_and_its_record() -> None:
    """NeverSuppresses cleanup: surviving halt keeps exact record and effect."""
    _, _, functions = _tree(
        "def raiser():\n"
        "    a = [0]\n"
        "    a[0] = 7\n"
        "    raise ValueError\n"
        "\n"
        "raiser()\n",
    )
    halted = _row_halt(functions, "raiser")
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


def test_helper_raise_through_with_does_not_fabricate_completed_twin() -> None:
    _, _, functions = _tree(
        "def raiser():\n    raise ValueError\n\nraiser()\n",
    )
    halted = _row_halt(functions, "raiser")
    after = ExitSet((halted,)).and_exit(
        ExitSet.completed(TermValue(0)),
        disposition=NeverSuppresses(),
    )
    with pytest.raises(AssertionError):
        assert isinstance(after.exits[0], Completed)
    with pytest.raises(AssertionError):
        assert after.exits[0].state is None


def test_with_then_try_composition_on_a_named_halt() -> None:
    """Cleanup then a matching try: the handler continues from the record."""
    _, _, functions = _tree(
        "def raiser():\n    raise IndexError\n\nraiser()\n",
    )
    halted = _row_halt(functions, "raiser")
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
    """Bite: a foreign RaiseEffect is not the helper's halt."""
    _, _, functions = _tree(
        "def raiser():\n    raise ValueError\n\nraiser()\n",
    )
    halted = _row_halt(functions, "raiser")
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


def test_handler_value_is_not_fabricated_fresh_block_twin() -> None:
    """Matching try handler must be the halt record object, not a fresh empty."""
    _, _, functions = _tree(
        "def raiser():\n    raise ValueError\n\nraiser()\n",
    )
    halted = _row_halt(functions, "raiser")
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
    )
    call = _calls_named(tree, "raiser")[0]
    outcome = call.sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    assert all(isinstance(e, Halted) for e in outcome.exits) or (
        sum(isinstance(e, Halted) for e in outcome.exits) == 1
    )
    with pytest.raises(AssertionError):
        assert all(isinstance(e, Completed) for e in outcome.exits)
