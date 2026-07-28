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
  (c) assertion boundary — observation binding refers to the real
      occurrence's effect (same object)
  (d) nested stores — later halt does not roll back prior bindings
  (e) composition of at least two of the above

Lying twins per row (refuse):

  - fabricated post-halt state at carrier enrollment
  - rolled-back binding (halt misread as Completed body)
  - wrong-occurrence observation (binding claims a foreign effect)

MUST NOT TOUCH: carrier/ExitSet, reducer, producers, routing.

Seam-3 residual list (rows that pin a weaker or incomplete surface):

  R1. WithEffectBoundarySugar *unmatched* residual re-seats an *equal*
      ReducedBlock rather than retaining ``state is pre_halt`` object
      identity (try/except ``and_exit`` and NeverSuppresses *do* retain
      ``is``). Effect object identity is still exact. Owner: unmatched
      residual path inside WithEffectBoundarySugar / observation attach —
      not a missing store producer.
  R2. Source ``try: a[i]=q except IndexError`` leaves an undischarged
      NativeOperationExitCarrier at helper desugar; the green try path is
      formal discharge then ``and_exit`` routing (row a). Closing R2 is
      composition of TrySugar with undischarged native store carriers,
      not a second binder.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    ReducerPreEffectStateV1,
)
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    CallParameterV1,
    EffectBoundaryDisposition,
    EffectBoundarySemanticsV1,
    ExceptionInfoBindingV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    ImportSignatureV2,
    NeverSuppresses,
    NoDefaultV1,
    NoMessagePatternV1,
    PositionalOrKeywordV1,
    RaiseEffectKindV1,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.effect_router import ObservedEffectBinding
from sugar_lift_py_tests.floor import ListValue, TermValue
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, str_const
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset, true_guard
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
    WithEffectBoundarySugar,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
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
        {
            a_cid: ListValue((TermValue(0),)),
            i_cid: TermValue(5),
            q_cid: TermValue(9),
        }
    )
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.state is pending.pre_effect_state.state
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert halted.effect.occurrence_id is not None
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


class _FixedSugar(Sugar):
    def __init__(self, outcome):
        self.outcome = outcome

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    @classmethod
    def witnesses(cls):
        return ()


def _assertion_boundary(
    body: ExitSet,
    *,
    expected: _Expected,
    observation_slot_id: str | None = "excinfo",
) -> WithEffectBoundarySugar:
    parameters = [
        CallParameterV1(
            "expected",
            PrimitiveSort("Value"),
            PositionalOrKeywordV1(),
            True,
            NoDefaultV1(),
        )
    ]
    manager_value = CallSiteValue(
        target_name="expect",
        arg_values=(expected,),
        parameters=("expected",),
        term=ctor("call:expect", []),
        body=None,
        keyword_names=(),
    )
    return WithEffectBoundarySugar(
        manager=_FixedSugar(Complete(manager_value)),
        body=(_FixedSugar(body),),
        semantics=EffectBoundarySemanticsV1(
            ExpectsModeV1(),
            RaiseEffectKindV1(),
            FormalArgumentProjectionV1(0),
            NoMessagePatternV1(),
            ExceptionInfoBindingV1(),
        ),
        contract_ref=SimpleNamespace(
            import_signature=ImportSignatureV2(tuple(parameters))
        ),
        context_manager_edge=None,
        observation_slot_id=observation_slot_id,
        site="state-survival-matrix-assertion",
    )


def _observed_binding(face):
    record = face.value if isinstance(face, Completed) else face.state
    if record is None or not hasattr(record, "entries"):
        return None
    return next(
        (e for e in record.entries if isinstance(e, ObservedEffectBinding)),
        None,
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
# (c) assertion boundary — observation refers to real occurrence's state
# ===========================================================================


def test_c_assertion_observation_binds_real_occurrence_effect() -> None:
    """Consumed store halt: ObservedEffectBinding.effect is the sole halt effect."""
    _, halted = _unpack_store_halt()
    routed = _assertion_boundary(
        ExitSet((halted,)),
        expected=_Expected("IndexError"),
        observation_slot_id="excinfo",
    ).desugar()
    assert isinstance(routed, ExitSet)
    assert len(routed.exits) == 1
    face = routed.exits[0]
    assert isinstance(face, Completed)
    binding = _observed_binding(face)
    assert binding is not None
    assert binding.slot_id == "excinfo"
    # Real occurrence: same effect object, not a reconstructed foreign raise.
    assert binding.effect is halted.effect
    assert binding.effect.occurrence == halted.effect.occurrence
    assert binding.effect.exception_type_coordinate == _identity("IndexError")


def test_c_wrong_occurrence_observation_refuses_twin() -> None:
    """Bite: binding must not claim a foreign occurrence / effect object."""
    _, halted = _unpack_store_halt()
    foreign = RaiseEffect(
        exception_name="IndexError",
        blame="foreign.py:1:0",
        occurrence="foreign.py:1:0",
        exception_type_coordinate=_identity("IndexError"),
        exception_type_mro=(_identity("IndexError"),),
    )
    routed = _assertion_boundary(
        ExitSet((halted,)),
        expected=_Expected("IndexError"),
    ).desugar()
    binding = _observed_binding(routed.exits[0])
    assert binding is not None
    with pytest.raises(AssertionError):
        assert binding.effect is foreign
    with pytest.raises(AssertionError):
        assert binding.effect.occurrence == foreign.occurrence


def test_c_unmatched_assertion_keeps_halt_effect_no_observation() -> None:
    """Wrong expected type: halt retained; no observation binding on the face.

    Effect object identity is preserved (same raise occurrence). State remains
    present and equal to the pre-halt testimony; WithEffectBoundarySugar may
    re-seat an equal ReducedBlock (not ``is``) on the unmet residual path —
    that is weaker than try/except ``and_exit`` identity and is not fabricated
    completion.
    """
    pending, halted = _unpack_store_halt()
    routed = _assertion_boundary(
        ExitSet((halted,)),
        expected=_Expected("ValueError"),
    ).desugar()
    face = routed.exits[0]
    assert isinstance(face, Halted)
    assert face.effect is halted.effect
    assert face.state is not None
    assert face.state == pending.pre_effect_state.state
    assert _observed_binding(face) is None
    # Not completed; not rolled back into a return face.
    assert not isinstance(face, Completed)


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
        {
            a_cid: ListValue((TermValue(0),)),
            i_cid: TermValue(0),
            q_cid: TermValue(9),
        }
    ).exits[0]
    assert isinstance(success, Completed)
    assert isinstance(success.value, UniverseValue)
    returns = [
        s
        for s in success.value.record.statements
        if type(s).__name__ == "ReturnValue"
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
    outcome = outcome_to_exitset(fn.sugar().desugar(None))
    halted = [e for e in outcome.exits if isinstance(e, Halted)]
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    assert len(halted) == 1
    assert len(completed) == 0
    assert halted[0].effect.exception_name == "TypeError"
    assert halted[0].effect.producer_node_owner == "TupleValue.setitem"
    assert halted[0].state is not None
    # Prior binding / store survived: list shows first-store write.
    lists = [
        e
        for e in halted[0].state.entries
        if isinstance(e, ListValue)
    ]
    assert lists == [ListValue((TermValue(2),))]
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


def test_e_assertion_then_wrong_type_does_not_fabricate_twin() -> None:
    """Compose (c) residual: wrong assertion type after store halt keeps effect."""
    pending, halted = _unpack_store_halt()
    routed = _assertion_boundary(
        ExitSet((halted,)),
        expected=_Expected("TypeError"),
    ).desugar()
    face = routed.exits[0]
    assert isinstance(face, Halted)
    assert face.effect is halted.effect
    assert face.state is not None
    assert face.state == pending.pre_effect_state.state
    with pytest.raises(AssertionError):
        assert isinstance(face, Completed)


def test_e_with_then_assertion_observation_still_real_occurrence() -> None:
    """Compose (b)+(c): after NeverSuppresses, observation still binds real effect."""
    _, halted = _unpack_store_halt()
    after_with = ExitSet((halted,)).and_exit(
        ExitSet.completed(TermValue(0)),
        disposition=NeverSuppresses(),
    )
    surviving = after_with.exits[0]
    assert isinstance(surviving, Halted)
    assert surviving.effect is halted.effect

    routed = _assertion_boundary(
        after_with,
        expected=_Expected("IndexError"),
    ).desugar()
    face = routed.exits[0]
    assert isinstance(face, Completed)
    binding = _observed_binding(face)
    assert binding is not None
    assert binding.effect is halted.effect
    assert binding.effect.occurrence == halted.effect.occurrence


# ===========================================================================
# Cross-row lying twins: fabricated enrollment / rolled-back / wrong occurrence
# ===========================================================================


def test_fabricated_post_halt_state_refused_at_carrier_enrollment() -> None:
    """Cross-row: raw/fabricated state cannot enroll as reducer testimony."""
    pending, _ = _unpack_store_halt()
    fabricated = _ReducedBlock((TermValue(99),), True, ())
    with pytest.raises(TypeError, match="reducer-issued testimony"):
        pending.and_then(
            lambda value: Complete(value),
            pre_effect_state=fabricated,
        )


def test_conflicting_second_state_enrollment_panics() -> None:
    pending, _ = _unpack_store_halt()
    conflicting = ReducerPreEffectStateV1._from_reducer(
        _ReducedBlock((TermValue(1),), True, ())
    )
    with pytest.raises(ConstructionPanic, match="second conflicting"):
        pending.and_then(
            lambda value: Complete(value),
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
