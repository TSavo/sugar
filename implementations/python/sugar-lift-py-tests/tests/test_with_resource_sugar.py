"""Unit twins for resource ``WithResourceSugar`` enter/exit ExitSet laws.

Production ``open(...)`` stays ``RuntimeSelected`` until enter/exit are
constructed. These twins drive the transformation with explicit ExitSets —
constructed green faces or explicit red residuals — never invented suppress.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.ir import atomic, make_var, not_
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.with_resource_sugar import (
    WithResourceSugar,
    never_suppresses_disposition,
    open_suppression_residual,
    suppresses_named,
)


class _Pass:
    def desugar(self, ctx=None):
        del ctx
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.outcome import Complete as C

        return C(BlockValue((), can_fall_through=True))


class _Raise:
    def __init__(self, name: str):
        self.name = name

    def desugar(self, ctx=None):
        del ctx
        return Incomplete(RaiseEffect(exception_name=self.name))


def _guard(name: str):
    return atomic(name, [make_var("state")])


def test_enter_halt_skips_body_and_exit():
    body_ran = []
    exit_ran = []

    class BodyProbe:
        def desugar(self, ctx=None):
            del ctx
            body_ran.append(1)
            return _Pass().desugar()

    enter_halt = RaiseEffect(exception_name="OSError")
    sugar = WithResourceSugar(
        body=(BodyProbe(),),
        enter=lambda: ExitSet.halted(enter_halt),
        exit_call=lambda: (exit_ran.append(1) or ExitSet.completed(False)),
        suppresses=never_suppresses_disposition,
    )
    out = sugar.desugar()
    assert body_ran == []
    assert exit_ran == []
    assert isinstance(out, Complete)
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect == enter_halt


def test_never_suppresses_restores_body_halt_after_exit_completes():
    body_halt = RaiseEffect(exception_name="ValueError")
    sugar = WithResourceSugar(
        body=(_Raise("ValueError"),),
        enter=lambda: ExitSet.completed("resource"),
        exit_call=lambda: ExitSet.completed(False),
        suppresses=never_suppresses_disposition,
    )
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect.exception_name == "ValueError"


def test_exit_halt_supersedes_body_halt():
    sugar = WithResourceSugar(
        body=(_Raise("ValueError"),),
        enter=lambda: ExitSet.completed("resource"),
        exit_call=lambda: ExitSet.halted(RaiseEffect(exception_name="RuntimeError")),
        suppresses=never_suppresses_disposition,
    )
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect.exception_name == "RuntimeError"


def test_exit_true_consumes_matching_body_halt():
    sugar = WithResourceSugar(
        body=(_Raise("ValueError"),),
        enter=lambda: ExitSet.completed("resource"),
        exit_call=lambda: ExitSet.completed(True),
        suppresses=suppresses_named("ValueError"),
    )
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert reds == []


def test_exit_true_does_not_consume_wrong_type():
    sugar = WithResourceSugar(
        body=(_Raise("KeyError"),),
        enter=lambda: ExitSet.completed("resource"),
        exit_call=lambda: ExitSet.completed(True),
        suppresses=suppresses_named("ValueError"),
    )
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect.exception_name == "KeyError"


def test_open_suppression_not_guessed_even_if_exit_returns_true():
    sugar = WithResourceSugar(
        body=(_Raise("ValueError"),),
        enter=lambda: ExitSet.completed("resource"),
        exit_call=lambda: ExitSet.completed(True),
        suppresses=suppresses_named("ValueError"),
        open_suppression=open_suppression_residual,
    )
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect.exception_name == "ValueError"


def test_completed_body_survives_never_suppresses_exit():
    sugar = WithResourceSugar(
        body=(_Pass(),),
        enter=lambda: ExitSet.completed("resource"),
        exit_call=lambda: ExitSet.completed(False),
        suppresses=never_suppresses_disposition,
    )
    out = sugar.desugar()
    assert isinstance(out, Complete)
    assert not any(isinstance(e, Incomplete) for e in out.value.contribution())


def test_exit_runs_on_every_conditional_body_face():
    """Conditional body halt + completion: exit fans once; both faces decided."""
    condition = _guard("c")
    effect = RaiseEffect(exception_name="ValueError")

    class ConditionalBody:
        def desugar(self, ctx=None):
            del ctx
            # Multi-exit via Incomplete under guard is produced by if-sugar;
            # here inject the dual ExitSet by wrapping in a statement that
            # reduce_block would not dualize — use promote path via Incomplete.
            return Incomplete(effect).guarded(condition)

    seen = []

    def exit_call():
        seen.append(1)
        return ExitSet.completed(False)

    sugar = WithResourceSugar(
        body=(ConditionalBody(),),
        enter=lambda: ExitSet.completed("resource"),
        exit_call=exit_call,
        suppresses=never_suppresses_disposition,
    )
    out = sugar.desugar()
    assert len(seen) == 1
    # Guarded halt restored under c (never suppress).
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect.exception_name == "ValueError"
    assert reds[0].branch_conditions


def test_unconstructed_enter_is_explicit_red_not_dissolve():
    """Admission: missing enter stays Incomplete residual, never silent pass."""
    enter_gap = RaiseEffect(exception_name="ConstructionGapEnter")
    sugar = WithResourceSugar(
        body=(_Pass(),),
        enter=lambda: ExitSet.halted(enter_gap),
        exit_call=lambda: ExitSet.completed(False),
        suppresses=never_suppresses_disposition,
    )
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect.exception_name == "ConstructionGapEnter"
