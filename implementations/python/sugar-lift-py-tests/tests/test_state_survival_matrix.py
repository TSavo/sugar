"""STATE-SURVIVAL MATRIX — seam 3 generalization completion (tests-only).

Temporal state (earlier bindings) must provably survive a sole exceptional
edge in EACH context below. Rows that cannot go green name the exact missing
producer — that list is the seam-3 residual for T.

Shared store seed (unpack Name × setitem on a decided list):

    def f(p):
        a = [0]
        x, a[5] = p, 9
        return x

The store is the one item mutation (``store_effect_sugar.item_mutation``,
#7757 step 7) on a receiver the lift decided, so it is the list's own store:
invalid index → sole Halted face, the named ``IndexError``, carrying the
block's record the reducer gives it (``halts_at_statement_head``). Earlier
Name ``x←p`` is not rolled into a Completed return.

No item store waits on a caller's actual, so the former seed -- the same
unpack on a formal, ``b = a; x, b[i] = p, q``, discharged with a caller's
list -- has no carrier left to discharge: ``a``'s class is no input there
(``b = a`` reads ``a`` bare), so its store is the undecided mutation, owed on
both faces, its undetermined halt kept with the block's state
(``test_formal_seed_is_the_undecided_store_with_its_state``).  Without
``b = a``, ``a`` takes ``class:a`` (#8925) and the store is the dispatched
``__setitem__`` edge, as row R2's helper below states for ``a[i] = q``.

Matrix rows:

  (a) store halt inside try/except routing — handler begins from the
      routed edge's state
  (b) resource With — ``__exit__`` path receives correct pre-halt state
  (d) nested stores — later halt does not roll back prior bindings
  (e) composition of at least two of the above

Row (c), the assertion boundary's observation binding, went with the
effect-boundary sugar that had no producer (#7757).

Lying twins per row (refuse):

  - fabricated post-halt state
  - rolled-back binding (halt misread as Completed body)

MUST NOT TOUCH: carrier/ExitSet, reducer, producers, routing.

Seam-3 residual list (rows that pin a weaker or incomplete surface):

  R2. CLOSED by #6685 (codex-1): Try composes over deferred native exits.
      The helper's store is now the dispatched ``__setitem__`` edge (#8857),
      owed with its halt routed by the ``try`` and its state kept; a source
      call is its coordinate, joined at prove (#7757 step 5). Pinned in
      matrix row ``r2_source_try_*`` below.
"""

from __future__ import annotations

import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
    NeverSuppresses,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import ListValue, TermValue
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import true_guard
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# The unpack's store on a list the frame built: the list's own store, the
# named ``IndexError`` at index 5; its in-range twin completes.
UNPACK_SETITEM = "def f(p):\n    a = [0]\n    x, a[5] = p, 9\n    return x\n"
UNPACK_SETITEM_OK = "def f(p):\n    a = [0]\n    x, a[0] = p, 9\n    return x\n"

# The former seed: the same unpack on a formal whose class is no input
# (``b = a`` hands ``a`` on bare), the undecided mutation.
UNPACK_SETITEM_FORMAL = (
    "def f(a, i, p, q):\n    b = a\n    x, b[i] = p, q\n    return x\n"
)


def _tree(source: str, name: str = "state_survival_matrix.py") -> SourceFile:
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


def _desugared(source: str, name: str):
    tree = _tree(source, name)
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function.sugar().desugar(None)


def _unpack_store_halt() -> tuple[ExitSet, Halted]:
    """Sole exceptional edge: unpack Name+setitem IndexError halt, carrying
    the block's record."""
    exits = _desugared(UNPACK_SETITEM, "unpack_store_seed.py")
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.state is not None
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert halted.effect.producer_node_owner == "ground_index_error"
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    return exits, halted


def _route_try_except(exits: ExitSet, expected: str) -> ExitSet:
    """try/except-shaped consumption: AuthenticatedRaiseMatcher + unmet residual."""
    return exits.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected(expected)),
            unmet=ExpectationNotMetEffect("raise", "try-except-site"),
        ),
    )


# ===========================================================================
# (a) try/except — handler begins from the routed edge's state
# ===========================================================================


def test_a_store_halt_try_except_handler_begins_from_routed_edge_state() -> None:
    """Matching except consumes the store halt; handler value IS pre-halt state."""
    _, halted = _unpack_store_halt()
    assert halted.state is not None

    routed = _route_try_except(ExitSet((halted,)), "IndexError")
    assert len(routed.exits) == 1
    handler = routed.exits[0]
    assert isinstance(handler, Completed)
    # Handler begins from the routed edge's state — exact object identity.
    assert handler.value is halted.state


def test_a_wrong_except_type_retains_identical_halt_state() -> None:
    """Unmatched except does not fabricate a handler; state object survives."""
    _, halted = _unpack_store_halt()
    routed = _route_try_except(ExitSet((halted,)), "ValueError")
    retained = routed.exits[0]
    assert isinstance(retained, Halted)
    assert retained.effect is halted.effect
    assert retained.state is halted.state


def test_a_handler_not_fabricated_post_halt_state_twin() -> None:
    """Bite: handler value must be the pre-halt state, not a fresh empty block."""
    _, halted = _unpack_store_halt()
    routed = _route_try_except(ExitSet((halted,)), "IndexError")
    handler = routed.exits[0]
    assert isinstance(handler, Completed)
    fabricated = _ReducedBlock((), True, ())
    with pytest.raises(AssertionError):
        assert handler.value is fabricated
    with pytest.raises(AssertionError):
        assert handler.value is not halted.state


# ===========================================================================
# (b) resource With — __exit__ receives correct pre-halt state
# ===========================================================================


def test_b_resource_with_exit_receives_pre_halt_state() -> None:
    """NeverSuppresses cleanup: surviving halt carries the exact body state.

    ``and_exit`` is the resource algebra: every body edge (including the store
    halt) is handed to the disposition. Pre-halt state must not be dropped.
    """
    _, halted = _unpack_store_halt()
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


def test_b_falsy_exit_truthiness_preserves_exact_pre_halt_state() -> None:
    """Source ``__exit__`` returning False restores the same state object."""
    _, halted = _unpack_store_halt()
    routed = ExitSet((halted,)).and_exit_truthiness(
        ExitSet.completed(TermValue(False)),
        site="resource-exit-site",
    )
    surviving = routed.exits[0]
    assert isinstance(surviving, Halted)
    assert surviving.effect is halted.effect
    assert surviving.state is halted.state


def test_b_exit_does_not_fabricate_completed_from_store_halt_twin() -> None:
    """Bite: NeverSuppresses must not turn the store halt into Completed."""
    _, halted = _unpack_store_halt()
    after = ExitSet((halted,)).and_exit(
        ExitSet.completed(TermValue(0)),
        disposition=NeverSuppresses(),
    )
    with pytest.raises(AssertionError):
        assert isinstance(after.exits[0], Completed)
    with pytest.raises(AssertionError):
        assert after.exits[0].state is None


# ===========================================================================
# (d) nested stores — later halt does not roll back prior bindings
# ===========================================================================


def test_d_unpack_name_binding_survives_later_store_halt() -> None:
    """Earlier Name ``x←p`` seam: halt keeps the block's state, not Completed."""
    _, halted = _unpack_store_halt()
    assert halted.state is not None
    assert not isinstance(halted, Completed)
    assert not isinstance(getattr(halted, "value", None), UniverseValue)
    # Success twin: when store completes, return carries formal p (x survived).
    succeeded = _desugared(UNPACK_SETITEM_OK, "unpack_store_ok.py")
    assert isinstance(succeeded, ExitSet)
    assert len(succeeded.exits) == 1
    success = succeeded.exits[0]
    assert isinstance(success, Completed)
    assert isinstance(success.value, UniverseValue)
    returns = [
        s for s in success.value.record.statements if type(s).__name__ == "ReturnValue"
    ]
    assert len(returns) == 1
    assert returns[0].value.term.name == "p"
    # Halt must not present that completed return face.
    with pytest.raises(AssertionError):
        assert isinstance(halted, Completed)


def test_d_rolled_back_binding_twin_refuses() -> None:
    """Bite: later store halt is not a Completed body and does not drop state."""
    _, halted = _unpack_store_halt()
    with pytest.raises(AssertionError):
        assert isinstance(halted, Completed), "later store halt completed the body"
    with pytest.raises(AssertionError):
        assert halted.state is None, "halt dropped earlier-binding state"
    with pytest.raises(AssertionError):
        assert halted.state is _ReducedBlock((), True, ()), "fabricated state"


def test_d_free_dual_store_later_halt_retains_prior_store_in_state() -> None:
    """Free multi-store body: first store mutates; second halt keeps that state.

    Program::

        def f():
            a = [0]
            b = (1,)
            a[0], b[0] = 2, 3
            return a

    First store writes ``a[0]=2``; second store TypeErrors on the tuple.
    Sole face is Halted; state is present and carries the prior list store
    (not rolled back to ``[0]``, not fabricated Completed return of ``a``).
    """
    source = (
        "def f():\n"
        "    a = [0]\n"
        "    b = (1,)\n"
        "    a[0], b[0] = 2, 3\n"
        "    return a\n"
    )
    tree = _tree(source, "free_dual_store.py")
    fn = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    outcome = fn.sugar().desugar(None)
    halted = [e for e in outcome.exits if isinstance(e, Halted)]
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    assert len(halted) == 1
    assert len(completed) == 0
    assert halted[0].effect.exception_name == "TypeError"
    assert halted[0].effect.producer_node_owner == "TupleValue.setitem"
    assert halted[0].state is not None
    # Prior binding / store survived: list shows first-store write.
    lists = [e for e in halted[0].state.entries if isinstance(e, ListValue)]
    assert lists == [fresh(ListValue, (TermValue(2),))]
    # Not fabricated completion of the return.
    with pytest.raises(AssertionError):
        assert isinstance(halted[0], Completed)


# ===========================================================================
# (e) composition of at least two contexts
# ===========================================================================


def test_e_with_then_try_except_preserves_store_halt_state() -> None:
    """Compose (b)+(a): resource cleanup then try/except handler.

    Store halt → NeverSuppresses ``__exit__`` path → matching except handler.
    Handler value remains the original pre-halt state object.
    """
    _, halted = _unpack_store_halt()
    after_with = ExitSet((halted,)).and_exit(
        ExitSet.completed(TermValue(0)),
        disposition=NeverSuppresses(),
    )
    surviving = after_with.exits[0]
    assert isinstance(surviving, Halted)
    assert surviving.state is halted.state

    handler_set = _route_try_except(after_with, "IndexError")
    handler = handler_set.exits[0]
    assert isinstance(handler, Completed)
    assert handler.value is halted.state


# ===========================================================================
# R2 confirmation after #6685 — source try × deferred formal setitem
# ===========================================================================

_SOURCE_TRY_SETITEM = (
    "def helper(a, i, q):\n"
    "    try:\n"
    "        a[i] = q\n"
    "    except IndexError:\n"
    "        return 1\n"
    "    return 0\n"
)


def test_r2_source_try_helper_alone_still_defers_as_setitem_carrier() -> None:
    """#6685: the helper's store is owed, never decided in its own proof.

    Expected shape changed (#8857): ``a``'s class is an input of
    ``helper``'s contract, so ``a[i] = q`` is the dispatched ``__setitem__``
    edge, not a deferred carrier.  Its halt is owed as the member
    ``python:dispatch:__setitem__``; the ``try`` routes it to ``return 1``
    under the type test and keeps it under the complement, leaving with the
    state the store began from (never a fabricated empty one)."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    tree = _tree(_SOURCE_TRY_SETITEM, "r2_try_helper.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    outcome = function.sugar().desugar(None)
    assert isinstance(outcome, ExitSet), type(outcome)
    assert "python:dispatch:__setitem__" in {
        call.symbol for call in owed_calls(outcome)
    }
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UnknownCallee:dispatch:__setitem__"
    ]
    assert halts, outcome
    assert all(halt.state is not None for halt in halts)


@pytest.mark.parametrize("index", (4, 0))
def test_r2_a_source_call_is_its_coordinate_never_the_helper_s_body(
    index: int,
) -> None:
    """#7757 step 5: ``helper([0], i, 9)`` is the call's coordinate, joined at
    prove as an imported call is; the helper's body (its ``try`` routing the
    store's ``IndexError`` to ``return 1``) is never applied at the call.
    Before step 5 the out-of-range call was decided here as ``1`` and the
    in-range one as ``0`` with the list changed: both read off the body.  It
    is the one unanswered call: it completes under its ``completes`` atom and
    halts under the complement."""
    source = _SOURCE_TRY_SETITEM + f"\nhelper([0], {index}, 9)\n"
    tree = _tree(source, f"r2_try_{index}.py")
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    outcome = call.sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    assert sum(isinstance(face, Completed) for face in outcome.exits) == 1
    assert sum(isinstance(face, Halted) for face in outcome.exits) == 1
    (face,) = [face for face in outcome.exits if isinstance(face, Completed)]
    _carried, value = peel_walrus_binds(face.value)
    assert not (isinstance(value, CallSiteValue) and value.body is not None)


# ===========================================================================
# Cross-row: the formal seed's store, and the seed's sole exceptional edge
# ===========================================================================


def test_formal_seed_is_the_undecided_store_with_its_state() -> None:
    """The former seed, ``b = a; x, b[i] = p, q``: no carrier waits on a
    caller's list (#7757 step 7).  ``a``'s class is no input, so the store is
    the undecided mutation (``undecided_item_mutation_faces``): it completes
    only under its own ``python:setitem.completes`` atom, with ``x`` bound to
    ``p``, or halts with an undetermined raise kept with the block's state;
    both faces owe the undecided member."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    outcome = _desugared(UNPACK_SETITEM_FORMAL, "unpack_store_formal.py")
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
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    for face in (halt, *completed):
        assert None in {call.symbol for call in owed_calls(ExitSet((face,)))}
    for face in completed:
        assert "python:setitem.completes" in str(face.guard)
        assert isinstance(face.value, UniverseValue), face.value
        returns = [
            s for s in face.value.record.statements if type(s).__name__ == "ReturnValue"
        ]
        assert len(returns) == 1
        assert returns[0].value.term.name == "p"
    assert outcome.completed_value() is None
    # Bite: the undecided store's halt is neither dropped nor stateless.
    with pytest.raises(AssertionError):
        assert not outcome.halts(), "the undecided store dropped its halt"
    with pytest.raises(AssertionError):
        assert halt.state is None, "halt dropped earlier-binding state"


def test_matrix_seed_is_sole_exceptional_edge() -> None:
    """Seed contract: exactly one Halted face; no parallel Completed store."""
    exits, _ = _unpack_store_halt()
    assert len(exits.exits) == 1
    assert all(isinstance(face, Halted) for face in exits.exits)
    with pytest.raises(AssertionError):
        assert any(isinstance(face, Completed) for face in exits.exits)
