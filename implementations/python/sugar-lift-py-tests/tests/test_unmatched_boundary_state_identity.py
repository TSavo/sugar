"""R1 as law: unmatched assertion residual retains IDENTICAL pre-halt state.

Seam-3 residual R1 (#6672): WithEffectBoundarySugar *unmatched* residual
re-seats an equal ``ReducedBlock`` (``==``) rather than retaining
``halted.state is pre_halt_state`` object identity. try/except ``and_exit``
and NeverSuppresses *do* retain ``is``.

This module pins R1 as an executable law:

  LAW (honorably red until the owner climbs):
    On an unmatched assertion residual, the retained Halted face's state
    object is the IDENTICAL ReducedBlock that rode the store halt
    (``face.state is halted.state``), not a re-seated equal copy.

  TWIN (green witness of the current crime):
    Today's residual is observably a *distinct* object that is ``==``-equal
    but not ``is``: identity probe fails, and mutating one reference is not
    the same cell as the other would be if they were aliases.

Owner of the red:
  WithEffectBoundarySugar unmatched residual path (observation attach /
  unmet residual re-seat) — not a store producer, not carrier mint, not
  ExitSet algebra for try/except matching. Replacement: retain the incoming
  Halted.state reference on unmatched residual the same way
  AuthenticatedRaiseMatcher unmet / NeverSuppresses do.

Tests-only. No production edits.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
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
from sugar_lift_py_tests.floor import ListValue, TermValue
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, str_const
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
    WithEffectBoundarySugar,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile

UNPACK_SETITEM = "def f(a, i, p, q):\n    x, a[i] = p, q\n    return x\n"


def _tree(source: str, name: str = "r1_state_identity.py") -> SourceFile:
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


class _FixedSugar(Sugar):
    def __init__(self, outcome):
        self.outcome = outcome

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    @classmethod
    def witnesses(cls):
        return ()


def _unpack_store_halt() -> tuple[NativeOperationExitCarrierV1, Halted]:
    tree = _tree(UNPACK_SETITEM, "unpack_store_seed.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    pending = function.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.pre_effect_state is not None
    a_cid, i_cid, q_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            a_cid: ListValue((TermValue(0),)),
            i_cid: TermValue(5),
            q_cid: TermValue(9),
        }
    )
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.state is pending.pre_effect_state.state
    return pending, halted


def _assertion_boundary_unmatched(body: ExitSet) -> ExitSet:
    """Assertion boundary whose expected type does not match IndexError."""
    parameters = [
        CallParameterV1(
            "expected",
            PrimitiveSort("Value"),
            PositionalOrKeywordV1(),
            True,
            NoDefaultV1(),
        )
    ]
    expected = _Expected("ValueError")
    manager_value = CallSiteValue(
        target_name="expect",
        arg_values=(expected,),
        parameters=("expected",),
        term=ctor("call:expect", []),
        body=None,
        keyword_names=(),
    )
    sugar = WithEffectBoundarySugar(
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
        observation_slot_id="excinfo",
        site="r1-unmatched-boundary-identity",
    )
    routed = sugar.desugar()
    assert isinstance(routed, ExitSet)
    return routed


# ---------------------------------------------------------------------------
# Control faces: try/except and NeverSuppresses already retain ``is``
# ---------------------------------------------------------------------------


def test_control_try_except_unmatched_retains_identical_state() -> None:
    """Control: AuthenticatedRaiseMatcher unmet keeps ``state is`` body halt."""
    _, halted = _unpack_store_halt()
    routed = ExitSet((halted,)).and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected("ValueError")),
            unmet=ExpectationNotMetEffect("raise", "try-except-site"),
        ),
    )
    retained = routed.exits[0]
    assert isinstance(retained, Halted)
    assert retained.effect is halted.effect
    assert retained.state is halted.state


def test_control_never_suppresses_retains_identical_state() -> None:
    """Control: resource NeverSuppresses keeps ``state is`` body halt."""
    _, halted = _unpack_store_halt()
    after = ExitSet((halted,)).and_exit(
        ExitSet.completed(TermValue(0)),
        disposition=NeverSuppresses(),
    )
    surviving = after.exits[0]
    assert isinstance(surviving, Halted)
    assert surviving.state is halted.state


# ---------------------------------------------------------------------------
# TWIN (green): current ==-equal re-seat is observably distinct
# ---------------------------------------------------------------------------


def test_r1_twin_unmatched_boundary_reseats_equal_but_not_identical_state() -> None:
    """Green witness of the current crime: equal copy, not the same object.

    Identity probe: ``face.state is halted.state`` is False while
    ``face.state == halted.state`` is True. That is the R1 gap made loud as a
    measurable twin — two references, one equal value, not one cell.
    """
    pending, halted = _unpack_store_halt()
    pre = pending.pre_effect_state.state
    assert halted.state is pre

    face = _assertion_boundary_unmatched(ExitSet((halted,))).exits[0]
    assert isinstance(face, Halted)
    assert face.effect is halted.effect
    assert face.state is not None

    # Equal value (today's residual is not a fabricated empty/foreign state).
    assert face.state == halted.state
    assert face.state == pre

    # Observably distinct objects: not the same ReducedBlock cell.
    assert face.state is not halted.state, (
        "if this fails green, R1 is closed — unmatched residual already "
        "retains identical state; retire this twin and the red law below"
    )
    assert face.state is not pre
    assert id(face.state) != id(halted.state)

    # Alias probe: if they were the same cell, identity would hold both ways.
    # Distinct ids prove a re-seat, not a shared reference.
    assert id(face.state) != id(pre)


# ---------------------------------------------------------------------------
# LAW (honorably red): unmatched residual must retain IDENTICAL state
# ---------------------------------------------------------------------------


def test_r1_law_unmatched_boundary_retains_identical_pre_halt_state() -> None:
    """LAW: unmatched assertion residual keeps ``face.state is halted.state``.

    HONORABLY RED until WithEffectBoundarySugar's unmatched residual path
    retains the incoming Halted.state reference (same object identity as
    try/except ``and_exit`` unmet and NeverSuppresses).

    Owner:
      WithEffectBoundarySugar unmatched residual / observation-attach re-seat
      (not store producer, not carrier mint, not ExitSet try/except algebra).

    Replacement architecture:
      On unmatched residual, emit Halted(guard, effect, incoming.state) with
      the same state object the store halt carried — do not construct a new
      equal ReducedBlock. When green, ``is`` holds and the twin above
      retires (its ``is not`` assertion flips).
    """
    pending, halted = _unpack_store_halt()
    pre = pending.pre_effect_state.state
    assert halted.state is pre

    face = _assertion_boundary_unmatched(ExitSet((halted,))).exits[0]
    assert isinstance(face, Halted)
    assert not isinstance(face, Completed)
    assert face.effect is halted.effect

    # THE LAW — currently red: residual re-seats equal copy instead of identity.
    assert face.state is halted.state, (
        "R1 SEAM3: unmatched WithEffectBoundarySugar residual re-seated an "
        "equal ReducedBlock instead of retaining the identical pre-halt "
        "state. owner=WithEffectBoundarySugar unmatched residual path "
        "fix=emit Halted(..., state=incoming.state) without re-seat; "
        f"observed face.state id={id(face.state)} "
        f"halted.state id={id(halted.state)} "
        f"equal={face.state == halted.state}"
    )
    assert face.state is pre
