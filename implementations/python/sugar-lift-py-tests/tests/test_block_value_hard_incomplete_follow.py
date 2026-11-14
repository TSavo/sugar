"""A block keeps the halt as an arm: unguarded it stops, guarded it keeps the tail.

A block record holds no halt (#7826), so the halt this pinned on a
``BlockValue`` entry is the ``Halted`` arm of the block's ``ExitSet``.
"""

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import BlockValue, TermValue
from sugar_lift_py_tests.ir import atomic, make_var, not_
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset


class _Fixed:
    def __init__(self, outcome, log=None):
        self.outcome = outcome
        self.log = log

    def desugar(self, ctx=None):
        del ctx
        if self.log is not None:
            self.log.append("tail")
        return self.outcome


def _tail(log):
    return _Fixed(
        ExitSet.completed(BlockValue((TermValue(1),), can_fall_through=True)), log
    )


def test_unguarded_incomplete_raise_stops_block_fallthrough():
    effect = RaiseEffect.for_builtin(
        "OSError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_block_value_hard_incomplete_follow.py:19:0",
    )
    log: list[str] = []

    exits = reduce_block_to_exitset((_Fixed(ExitSet.halted(effect)), _tail(log)))

    # Nothing falls through: every arm halts, and the tail never runs.
    assert len(exits.exits) == 1 and exits.halts() == exits.exits
    assert [h.effect for h in exits.halts()] == [effect]
    assert log == []


def test_guarded_incomplete_raise_preserves_the_complementary_tail():
    condition = atomic("condition", [make_var("state")])
    effect = RaiseEffect.for_builtin(
        "OSError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_block_value_hard_incomplete_follow.py:10:0",
    )
    log: list[str] = []

    exits = reduce_block_to_exitset(
        (_Fixed(ExitSet.halted(effect).guarded(condition)), _tail(log))
    )

    # The tail continues on the complementary face.
    assert log == ["tail"]
    assert any(
        isinstance(exit_, Halted) and exit_.guard == condition and exit_.effect == effect
        for exit_ in exits.exits
    )
    assert any(
        isinstance(exit_, Completed) and exit_.guard == not_(condition)
        for exit_ in exits.exits
    )
