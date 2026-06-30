"""`x <op>= v` is sugar for `x = x <op> v`. AugAssignSugar is a pure recognizer that owns
no operator knowledge: it rewrites to a plain assign over the synthesized `x <op> v`
binop and hands it downstream, so each operator dispatches to its OWN binop sugar -- or
the factory panics naming the gap.

So the spec writes itself, one row per Python augmented operator. The INTEGER ops (`+=`,
`-=`, `*=`, `//=`, `%=`, `**=`) compose over Int-sorted TermValue. True division (`/=`)
and any float literal are RESIDUAL -- floats are not modeled (see literal_encoding.rs:
`3.0 == 3` is Python-true, so asserting `float != int` is a false distinctness that would
manufacture a false refusal), so they are refused loudly, which is correct, not a rung.
"""
from __future__ import annotations

import pytest

from factory_reduce import compose_block
from sugar_lift_py_tests.factory import FactoryGap


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
    # true division yields a float (6/2 == 3.0), and floats are RESIDUAL -- so it is
    # correctly REFUSED, not modeled. The factory panics; that is the right behavior, not
    # a worklist rung. (Modeling it would risk the false distinctness below.)
    with pytest.raises(FactoryGap):
        _block("    x = 6\n    x /= 2\n    return x\n")


# --- floats are RESIDUAL, by the soundness principle in literal_encoding.rs: `3.0 == 3`
# --- is Python-TRUE, so asserting `float != int` is a FALSE distinctness that would
# --- manufacture a false refusal. So we do NOT model floats -- a float literal is refused
# --- loudly, never folded into Int (which would lie) nor split off as Real (also a lie).

def test_float_literal_is_residual_and_is_refused_loudly():
    with pytest.raises(FactoryGap):
        _block("    return 3.0\n")


def test_aug_floordiv_assign_equals_the_floor_quotient():
    assert _block("    x = 7\n    x //= 2\n    return x\n") == _block("    return 3\n")


def test_aug_mod_assign_equals_the_remainder():
    assert _block("    x = 7\n    x %= 3\n    return x\n") == _block("    return 1\n")


def test_aug_pow_assign_equals_the_power():
    assert _block("    x = 2\n    x **= 3\n    return x\n") == _block("    return 8\n")
