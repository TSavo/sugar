"""`x <op>= v` is sugar for `x = x <op> v`. AugAssignSugar is a pure recognizer that owns
no operator knowledge: it rewrites to a plain assign over the synthesized `x <op> v`
binop and hands it downstream, so each operator dispatches to its OWN binop sugar -- or
the factory panics naming the gap.

So the spec writes itself, one row per Python augmented operator:
  * `+=` is GREEN -- the Add binop exists, so it composes (and reuses AssignSugar's bind,
    which closes over its definition scope so the rebind reads the old x).
  * `-=`, `*=`, `/=`, `//=`, `%=`, `**=` are RED -- their binops are not written yet, so
    they panic. The red is the worklist: each failing row names the exact binop atom to
    write next, and flips green the day it lands. We keep them red on purpose.
"""
from __future__ import annotations

from factory_reduce import compose_block


def _block(src: str):
    return compose_block(src, {})


# --- GREEN: the binop exists, so the sugar composes -------------------------------------

def test_self_referential_assign_closes_over_the_old_value_and_does_not_loop():
    # The canary's first find: a lazy BoundVar recomposing against the NEW binding loops.
    # A let closes over its definition scope, so the new x is (old x) + 1, and it folds.
    assert _block("    x = 5\n    x = x + 1\n    return x\n") == _block("    return 6\n")


def test_aug_add_assign_is_the_plain_assign_of_the_sum():
    assert _block("    x = 5\n    x += 1\n    return x\n") == _block("    return 6\n")


def test_aug_assign_carries_the_old_value_not_just_the_rhs():
    # discrimination: `x += 1` is NOT `x = 1` -- it carries the old x.
    assert _block("    x = 5\n    x += 1\n    return x\n") != _block(
        "    x = 5\n    x = 1\n    return x\n"
    )


# --- RED: the binop atom is unwritten, so the row names what to write next ---------------

def test_aug_sub_assign_equals_the_difference():
    assert _block("    x = 5\n    x -= 2\n    return x\n") == _block("    return 3\n")


def test_aug_mult_assign_equals_the_product():
    assert _block("    x = 5\n    x *= 2\n    return x\n") == _block("    return 10\n")


def test_aug_div_assign_equals_the_quotient():
    # RED: true division is REAL, not Int -- 6/2 == 3.0. A real result is a canonical-
    # decimal RealValue with possibly non-terminating division (1/3); that is the Real-
    # arithmetic / tolerance rung (mirror the decimal-tolerance lift), not a float fold.
    assert _block("    x = 6\n    x /= 2\n    return x\n") == _block("    return 3.0\n")


# --- GREEN now: the typed Real landed. float lifts to a RealValue (canonical decimal),
# --- distinct from the Int-sorted TermValue, so 3.0 and 3 are no longer conflated.

def test_float_is_a_real_distinct_from_the_int():
    # 3.0 is Real-sorted (RealValue), 3 is Int-sorted (TermValue) -- distinct Floor
    # values, never conflated. This is the sort discipline the z3 compiler enforces.
    assert _block("    return 3.0\n") != _block("    return 3\n")


def test_aug_floordiv_assign_equals_the_floor_quotient():
    assert _block("    x = 7\n    x //= 2\n    return x\n") == _block("    return 3\n")


def test_aug_mod_assign_equals_the_remainder():
    assert _block("    x = 7\n    x %= 3\n    return x\n") == _block("    return 1\n")


def test_aug_pow_assign_equals_the_power():
    assert _block("    x = 2\n    x **= 3\n    return x\n") == _block("    return 8\n")
