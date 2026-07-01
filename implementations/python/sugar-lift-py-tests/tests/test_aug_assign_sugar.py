"""`x <op>= v` is sugar for `x = x <op> v`. AugAssignSugar is a pure recognizer that owns
no operator knowledge: it rewrites to a plain assign over the synthesized `x <op> v`
binop and hands it downstream, so each operator dispatches to its OWN binop sugar -- or
the factory panics naming the gap.

Every augmented operator composes over the COLLAPSED Number (one value type: Int embeds
in Real losslessly, so 3 and 3.0 are the same number and 3.0 == 3 is reflexively true).
True division `/=` lifts too. And `x /= 0` is not a value -- it raises -- so it is an
`Incomplete(DivByZero)` EFFECT: the line after it is unreachable, the account cannot be
completed, and every sugar bubbles that Incomplete upward unchanged, doing no work past
it (the Outcome short-circuit).
"""

from __future__ import annotations

from factory_reduce import compose_block
from sugar_lift_py_tests.outcome import Incomplete


def _block(src: str):
    return compose_block(src, {})


# --- GREEN: the binop exists, so the sugar composes -------------------------------------


def test_self_referential_assign_closes_over_the_old_value_and_does_not_loop():
    # The canary's first find: a lazy BoundVar recomposing against the NEW binding loops.
    # A let closes over its definition scope, so the new x is (old x) + 1, and it folds.
    assert _block("    x = 5\n    x = x + 1\n    return x\n") == _block(
        "    return 6\n"
    )


def test_aug_add_assign_is_the_plain_assign_of_the_sum():
    assert _block("    x = 5\n    x += 1\n    return x\n") == _block("    return 6\n")


def test_aug_assign_carries_the_old_value_not_just_the_rhs():
    # discrimination: `x += 1` is NOT `x = 1` -- it carries the old x.
    assert _block("    x = 5\n    x += 1\n    return x\n") != _block(
        "    x = 5\n    x = 1\n    return x\n"
    )


def test_aug_sub_assign_equals_the_difference():
    assert _block("    x = 5\n    x -= 2\n    return x\n") == _block("    return 3\n")


def test_aug_mult_assign_equals_the_product():
    assert _block("    x = 5\n    x *= 2\n    return x\n") == _block("    return 10\n")


def test_aug_div_assign_lifts_via_the_collapsed_number():
    # `/` is true division (6/2 == 3.0). The numeric type is COLLAPSED -- Int embeds in
    # Real losslessly -- so 3.0 == 3 and this lifts. No residual, no false distinctness.
    assert _block("    x = 6\n    x /= 2\n    return x\n") == _block("    return 3\n")


# --- the collapsed Number: float and int are one value (Int embeds in Real losslessly),
# --- so 3.0 == 3 is REFLEXIVELY true -- nothing to assert, nothing to refuse.


def test_float_literal_collapses_three_point_zero_equals_three():
    assert _block("    return 3.0\n") == _block("    return 3\n")


# --- divide-by-zero is an EFFECT (Incomplete), not a value: the line after it never runs,
# --- so the account cannot be completed and the unreachable work is never done.


def test_divide_by_zero_is_an_incomplete_effect_that_halts_propagation():
    # `x = 1 // 0` binds lazily; the effect surfaces when x is USED -- the reference
    # reduces the source to Incomplete, which bubbles through return and halts the block.
    halted = _block("    x = 1 // 0\n    return x\n")
    assert isinstance(halted, Incomplete)
    assert "zero" in halted.reason


def test_aug_floordiv_assign_equals_the_floor_quotient():
    assert _block("    x = 7\n    x //= 2\n    return x\n") == _block("    return 3\n")


def test_aug_mod_assign_equals_the_remainder():
    assert _block("    x = 7\n    x %= 3\n    return x\n") == _block("    return 1\n")


def test_aug_pow_assign_equals_the_power():
    assert _block("    x = 2\n    x **= 3\n    return x\n") == _block("    return 8\n")
