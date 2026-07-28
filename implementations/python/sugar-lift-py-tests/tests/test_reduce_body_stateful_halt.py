"""Reducer boundary law for state-bearing exceptional exits."""

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.outcome import ExitSet, Incomplete, true_guard
from sugar_lift_py_tests.outcome.exit_set import Halted
from sugar_lift_py_tests.sugar import function_universe_sugar


def test_reduce_body_retains_one_unconditional_stateful_halt(monkeypatch):
    effect = RaiseEffect(exception_name="AttributeError")
    pre_effect_state = object()
    exits = ExitSet((Halted(true_guard(), effect, pre_effect_state),))
    monkeypatch.setattr(
        function_universe_sugar,
        "reduce_block_to_exitset",
        lambda statements, ctx: exits,
    )

    reduced = function_universe_sugar.reduce_body(())

    assert reduced is exits
    assert reduced.exits[0].state is pre_effect_state


def test_reduce_body_still_collapses_one_unconditional_stateless_halt(monkeypatch):
    effect = RaiseEffect(exception_name="AttributeError")
    exits = ExitSet((Halted(true_guard(), effect),))
    monkeypatch.setattr(
        function_universe_sugar,
        "reduce_block_to_exitset",
        lambda statements, ctx: exits,
    )

    reduced = function_universe_sugar.reduce_body(())

    assert reduced == Incomplete(effect)

