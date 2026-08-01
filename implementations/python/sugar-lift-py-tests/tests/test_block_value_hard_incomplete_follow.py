"""BlockValue preserves the halt encoded by ExitSet's linear adapter."""

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import BlockValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Incomplete


def test_unguarded_incomplete_raise_stops_block_fallthrough():
    block = BlockValue((Incomplete(RaiseEffect.for_builtin('OSError', occurrence='implementations/python/sugar-lift-py-tests/tests/test_block_value_hard_incomplete_follow.py:19:0')),))

    assert not block.follow_rest().continues


def test_guarded_incomplete_raise_preserves_the_complementary_tail():
    block = BlockValue(
        (
            Incomplete(
                RaiseEffect.for_builtin('OSError', occurrence='implementations/python/sugar-lift-py-tests/tests/test_block_value_hard_incomplete_follow.py:10:0'),
                branch_conditions=(make_var("condition"),),
            ),
        )
    )

    assert block.follow_rest().continues
