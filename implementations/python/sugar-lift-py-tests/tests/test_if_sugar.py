"""IfSugar composes a test plus a then-block and an else-block (the model: an if gets
two child blocks). Each branch's returns become GUARDED returns -- the then branch
under the test, the else branch under its negation. Control flow is composition of
child blocks, not a walker."""

from __future__ import annotations

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.floor import (
    BlockValue,
    GuardedReturn,
    StringValue,
    SymbolicValue,
)
from sugar_lift_py_tests.ir import (
    ctor,
    eq,
    gte,
    identity,
    lt,
    make_var,
    not_,
    num,
    real_lit,
)


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


def test_if_guard_accepts_collapsed_number_float_literal():
    bv = compose_block(
        '    if x < 1.5:\n        return "a"\n    else:\n        return "b"\n',
        {"x": SymbolicValue(make_var("x"))},
    )
    guard = lt(make_var("x"), real_lit("1.5"))
    assert bv == BlockValue(
        (
            GuardedReturn((guard,), StringValue("a")),
            GuardedReturn((not_(guard),), StringValue("b")),
        )
    )


def test_if_guard_accepts_identity_none_literal():
    bv = compose_block(
        '    if x is not None:\n        return "a"\n    else:\n        return "b"\n',
        {"x": SymbolicValue(make_var("x"))},
    )
    guard = not_(identity(make_var("x"), ctor("None", [])))
    assert bv == BlockValue(
        (
            GuardedReturn((guard,), StringValue("a")),
            GuardedReturn((not_(guard),), StringValue("b")),
        )
    )


def test_if_guard_accepts_greater_equal_compare():
    bv = compose_block(
        '    if x >= y:\n        return "a"\n    else:\n        return "b"\n',
        {"x": SymbolicValue(make_var("x")), "y": SymbolicValue(make_var("y"))},
    )
    guard = gte(make_var("x"), make_var("y"))
    assert bv == BlockValue(
        (
            GuardedReturn((guard,), StringValue("a")),
            GuardedReturn((not_(guard),), StringValue("b")),
        )
    )


def test_if_guard_accepts_tuple_literal_operand():
    bv = compose_block(
        '    if version == (1, 0):\n        return "a"\n    else:\n        return "b"\n',
        {"version": SymbolicValue(make_var("version"))},
    )
    guard = eq(make_var("version"), ctor("tuple", [num(1), num(0)]))
    assert bv == BlockValue(
        (
            GuardedReturn((guard,), StringValue("a")),
            GuardedReturn((not_(guard),), StringValue("b")),
        )
    )


def test_if_guard_membership_gap_is_structured():
    with pytest.raises(TypeError) as exc:
        compose_block(
            '    if encoding not in ("ASCII", "latin1"):\n'
            '        return "a"\n'
            "    else:\n"
            '        return "b"\n',
            {"encoding": SymbolicValue(make_var("encoding"))},
        )

    assert str(exc.value) == (
        "write more Sugar for control-flow guard: owner=IfSugar "
        "blame=f.py:2:7 observed=Compare:NotIn requested=control-flow guard "
        "fix=add IfSugar lowering for Compare:NotIn"
    )
