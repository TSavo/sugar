"""STATE-SURVIVAL MATRIX — seam 3 generalization completion (tests-only).

Temporal state (earlier bindings) must provably survive a sole exceptional
edge in EACH context below. Rows that cannot go green name the exact missing
producer — that list is the seam-3 residual for T.

Shared store seed (formal unpack × setitem, post-#6644):

    def f(a, i, p, q):
        x, a[i] = p, q
        return x

Invalid index → sole Halted face; ``pending.pre_effect_state.state is
halted.state``. Earlier Name ``x←p`` is not rolled into a Completed return.

Matrix rows:

  (a) store halt inside try/except routing — handler begins from the
      routed edge's state
  (b) resource With — ``__exit__`` path receives correct pre-halt state
  (d) nested stores — later halt does not roll back prior bindings
  (e) composition of at least two of the above

Row (c), the assertion boundary's observation binding, went with the
effect-boundary sugar that had no producer (#7757).

Lying twins per row (refuse):

  - fabricated post-halt state at carrier enrollment
  - rolled-back binding (halt misread as Completed body)

MUST NOT TOUCH: carrier/ExitSet, reducer, producers, routing.

Seam-3 residual list (rows that pin a weaker or incomplete surface):

  R2. CLOSED by #6685 (codex-1): Try composes over deferred native exits.
      Helper alone still retains one undischarged setitem carrier (deferred
      formal — correct). Authenticated source call discharges through Try:
      IndexError routes to handler; success bypasses handler. Pinned green
      in test_try_native_store_carrier.py and matrix row ``r2_source_try_*``
      below. Residual half that remains is intentional deferral at helper
      desugar, not a missing Try×carrier composition.
"""

from __future__ import annotations

import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    ReducerPreEffectStateV1,
)
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
from sugar_lift_py_tests.gap.panic import ConstructionPanic
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

UNPACK_SETITEM = "def f(a, i, p, q):\n    x, a[i] = p, q\n    return x\n"


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


def _unpack_store_halt() -> tuple[NativeOperationExitCarrierV1, Halted]:
    """Sole exceptional edge: formal unpack Name+setitem IndexError halt."""
    tree = _tree(UNPACK_SETITEM, "unpack_store_seed.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    pending = function.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"
    assert pending.pre_effect_state is not None
    a_cid, i_cid, q_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        None,
        {
            a_cid: fresh(ListValue, (TermValue(0),)),
            i_cid: TermValue(5),
            q_cid: TermValue(9),
        },
    )
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.state is pending.pre_effect_state.state
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    return pending, halted


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
    pending, halted = _unpack_store_halt()
    testimony = pending.pre_effect_state
    assert testimony is not None
    assert halted.state is testimony.state

    routed = _route_try_except(ExitSet((halted,)), "IndexError")
    assert len(routed.exits) == 1
    handler = routed.exits[0]
    assert isinstance(handler, Completed)
    # Handler begins from the routed edge's state — exact object identity.
    assert handler.value is testimony.state
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
    pending, halted = _unpack_store_halt()
    routed = _route_try_except(ExitSet((halted,)), "IndexError")
    handler = routed.exits[0]
    assert isinstance(handler, Completed)
    fabricated = _ReducedBlock((), True, ())
    with pytest.raises(AssertionError):
        assert handler.value is fabricated
    with pytest.raises(AssertionError):
        assert handler.value is not pending.pre_effect_state.state


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
    """Earlier Name ``x←p`` seam: halt state is pre_effect_state, not Completed."""
    pending, halted = _unpack_store_halt()
    assert pending.pre_effect_state is not None
    assert halted.state is pending.pre_effect_state.state
    assert not isinstance(halted, Completed)
    assert not isinstance(getattr(halted, "value", None), UniverseValue)
    # Success twin: when store completes, return carries formal p (x survived).
    a_cid, i_cid, q_cid = pending.demand.operand_coordinate_cids
    success = pending.discharge(
        None,
        {
            a_cid: fresh(ListValue, (TermValue(0),)),
            i_cid: TermValue(0),
            q_cid: TermValue(9),
        },
    ).exits[0]
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
    pending, halted = _unpack_store_halt()
    with pytest.raises(AssertionError):
        assert isinstance(halted, Completed), "later store halt completed the body"
    with pytest.raises(AssertionError):
        assert halted.state is None, "halt dropped earlier-binding state"
    with pytest.raises(AssertionError):
        assert halted.state is not pending.pre_effect_state.state


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
    pending, halted = _unpack_store_halt()
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
    assert handler.value is pending.pre_effect_state.state
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
    """#6685: helper desugar remains one undischarged setitem carrier (correct)."""
    tree = _tree(_SOURCE_TRY_SETITEM, "r2_try_helper.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    pending = function.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"
    assert pending.pre_effect_state is not None


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
# Cross-row lying twins: fabricated enrollment / rolled-back / wrong occurrence
# ===========================================================================


def test_fabricated_post_halt_state_refused_at_carrier_enrollment() -> None:
    """Cross-row: raw/fabricated state cannot enroll as reducer testimony."""
    pending, _ = _unpack_store_halt()
    fabricated = _ReducedBlock((TermValue(99),), True, ())
    with pytest.raises(TypeError, match="reducer-issued testimony"):
        pending.and_then(
            lambda value: ExitSet.completed(value),
            pre_effect_state=fabricated,
        )


def test_conflicting_second_state_enrollment_panics() -> None:
    pending, _ = _unpack_store_halt()
    conflicting = ReducerPreEffectStateV1._from_reducer(
        _ReducedBlock((TermValue(1),), True, ())
    )
    with pytest.raises(ConstructionPanic, match="second conflicting"):
        pending.and_then(
            lambda value: ExitSet.completed(value),
            pre_effect_state=conflicting,
        )


def test_matrix_seed_is_sole_exceptional_edge() -> None:
    """Seed contract: exactly one Halted face; no parallel Completed store."""
    _, halted = _unpack_store_halt()
    exits = ExitSet((halted,))
    assert len(exits.exits) == 1
    assert all(isinstance(face, Halted) for face in exits.exits)
    with pytest.raises(AssertionError):
        assert any(isinstance(face, Completed) for face in exits.exits)
