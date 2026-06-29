"""IfSugar composes a test plus a then-block and an else-block (the model: an if gets
two child blocks). Each branch's returns become GUARDED returns -- the then branch
under the test, the else branch under its negation. Control flow is composition of
child blocks, not a walker."""
from __future__ import annotations

from factory_reduce import compose_block

from sugar_lift_py_tests.floor import (
    BlockValue,
    GuardedReturn,
    StringValue,
    SymbolicValue,
)
from sugar_lift_py_tests.ir import eq, make_var, not_, num


def test_if_else_composes_then_and_else_into_guarded_returns():
    bv = compose_block(
        '    if x == 0:\n        return "a"\n    else:\n        return "b"\n',
        {"x": SymbolicValue(make_var("x"))},
    )
    guard = eq(make_var("x"), num(0))
    assert bv == BlockValue(
        (
            GuardedReturn((guard,), StringValue("a")),
            GuardedReturn((not_(guard),), StringValue("b")),
        )
    )


def test_comment_before_an_if_is_absorbed():
    bv = compose_block(
        '    "doc"\n    if x == 0:\n        return "a"\n    else:\n        return "b"\n',
        {"x": SymbolicValue(make_var("x"))},
    )
    assert len(bv.statements) == 2
