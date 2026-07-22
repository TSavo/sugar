"""Unit twins for resource ``WithResourceSugar`` — sugars + typed disposition.

No Python callbacks for enter/exit/suppress. Production ``open(...)`` stays
``RuntimeSelected`` until a typed disposition is enrolled with constructed
enter/exit method-coordinate sugars.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_contract import (
    NeverSuppresses,
    RuntimeSelected,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.call_site_value import ExitSuppressionContract
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar


class _FixedSugar(Sugar):
    """Test sugar: desugars to a fixed Outcome (tree door stand-in)."""

    def __init__(self, outcome, *, probe=None):
        self._outcome = outcome
        self._probe = probe

    def desugar(self, ctx=None):
        del ctx
        if self._probe is not None:
            self._probe.append(1)
        return self._outcome

    @classmethod
    def witnesses(cls):
        return ()


class _Pass(_FixedSugar):
    def __init__(self, probe=None):
        super().__init__(
            Complete(BlockValue((), can_fall_through=True)), probe=probe
        )


class _Raise(_FixedSugar):
    def __init__(self, name: str, probe=None):
        super().__init__(
            Incomplete(RaiseEffect(exception_name=name)), probe=probe
        )


def _guard(name: str):
    return atomic(name, [make_var("state")])


def test_enter_halt_skips_body_and_exit():
    body_ran = []
    exit_ran = []
    enter_halt = RaiseEffect(exception_name="OSError")
    sugar = WithResourceSugar(
        enter=_FixedSugar(Incomplete(enter_halt)),
        exit=_FixedSugar(
            Complete(BlockValue((), can_fall_through=True)), probe=exit_ran
        ),
        body=(_Pass(probe=body_ran),),
        disposition=NeverSuppresses(),
    )
    out = sugar.desugar()
    assert body_ran == []
    assert exit_ran == []
    assert isinstance(out, Complete)
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect == enter_halt


def test_never_suppresses_restores_body_halt_after_exit_completes():
    sugar = WithResourceSugar(
        enter=_Pass(),
        exit=_Pass(),
        body=(_Raise("ValueError"),),
        disposition=NeverSuppresses(),
    )
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect.exception_name == "ValueError"


def test_exit_halt_supersedes_body_halt():
    sugar = WithResourceSugar(
        enter=_Pass(),
        exit=_Raise("RuntimeError"),
        body=(_Raise("ValueError"),),
        disposition=NeverSuppresses(),
    )
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect.exception_name == "RuntimeError"


def test_proven_contract_consumes_matching_body_halt():
    sugar = WithResourceSugar(
        enter=_Pass(),
        exit=_Pass(),
        body=(_Raise("ValueError"),),
        disposition=ExitSuppressionContract.suppresses(("ValueError",)),
    )
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert reds == []


def test_proven_contract_does_not_consume_wrong_type():
    sugar = WithResourceSugar(
        enter=_Pass(),
        exit=_Pass(),
        body=(_Raise("KeyError"),),
        disposition=ExitSuppressionContract.suppresses(("ValueError",)),
    )
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect.exception_name == "KeyError"


def test_runtime_selected_not_guessed_even_if_exit_completes():
    sugar = WithResourceSugar(
        enter=_Pass(),
        exit=_Pass(),
        body=(_Raise("ValueError"),),
        disposition=RuntimeSelected(),
    )
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect.exception_name == "ValueError"


def test_completed_body_survives_never_suppresses_exit():
    sugar = WithResourceSugar(
        enter=_Pass(),
        exit=_Pass(),
        body=(_Pass(),),
        disposition=NeverSuppresses(),
    )
    out = sugar.desugar()
    assert isinstance(out, Complete)
    assert not any(isinstance(e, Incomplete) for e in out.value.contribution())


def test_exit_sugar_desugars_once_across_conditional_body_faces():
    condition = _guard("c")
    effect = RaiseEffect(exception_name="ValueError")

    class ConditionalBody(Sugar):
        def desugar(self, ctx=None):
            del ctx
            return Incomplete(effect).guarded(condition)

        @classmethod
        def witnesses(cls):
            return ()

    exit_ran = []
    sugar = WithResourceSugar(
        enter=_Pass(),
        exit=_Pass(probe=exit_ran),
        body=(ConditionalBody(),),
        disposition=NeverSuppresses(),
    )
    out = sugar.desugar()
    assert len(exit_ran) == 1
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect.exception_name == "ValueError"
    assert reds[0].branch_conditions


def test_unconstructed_enter_is_explicit_red_not_dissolve():
    enter_gap = RaiseEffect(exception_name="ConstructionGapEnter")
    sugar = WithResourceSugar(
        enter=_FixedSugar(Incomplete(enter_gap)),
        exit=_Pass(),
        body=(_Pass(),),
        disposition=NeverSuppresses(),
    )
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect.exception_name == "ConstructionGapEnter"


def test_suppresses_named_is_not_exported():
    """Callback side door must not exist on the resource sugar module."""
    import sugar_lift_py_tests.sugar.with_resource_sugar as mod

    assert not hasattr(mod, "suppresses_named")
    assert not hasattr(mod, "never_suppresses_disposition")
    assert not hasattr(mod, "open_suppression_residual")
