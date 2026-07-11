"""The if/else join: exits decide what the continuation rides. Both faces exit
-- the tail is unreachable (raw). Exactly one face exits -- the tail rides
under the OTHER face's polarity. Neither exits -- the tail is unconditional."""

from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import UniverseValue
from sugar_lift_py_tests.ir import (
    and_,
    eq,
    implies,
    make_var,
    not_,
    num,
    py_eq,
    py_lt,
    str_const,
)
from sugar_lift_py_tests.outcome import complete_value


def _universe(source: str) -> UniverseValue:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    result = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    value = complete_value(result.sugar.desugar(ctx), owner="test")
    assert isinstance(value, UniverseValue)
    return value


def test_exhaustive_if_else_emits_both_guarded_exits() -> None:
    universe = _universe(
        'def enc(x):\n'
        '    if x == "ccc":\n'
        '        return "yyy"\n'
        '    else:\n'
        '        return x\n'
    )
    guard = py_eq(make_var("x"), str_const("ccc"))
    assert universe.post() == and_(
        [
            implies(guard, eq(make_var("out"), str_const("yyy"))),
            implies(not_(guard), eq(make_var("out"), make_var("x"))),
        ]
    )


def test_dead_code_after_exhaustive_if_else_stays_raw() -> None:
    universe = _universe(
        'def enc(x):\n'
        '    if x == "ccc":\n'
        '        return "yyy"\n'
        '    else:\n'
        '        return x\n'
        '    return 0\n'
    )
    guard = py_eq(make_var("x"), str_const("ccc"))
    assert universe.post() == and_(
        [
            implies(guard, eq(make_var("out"), str_const("yyy"))),
            implies(not_(guard), eq(make_var("out"), make_var("x"))),
        ]
    )
    # no unconditional eq(out, 0) from the dead return
    post = universe.post()
    assert eq(make_var("out"), num(0)) not in getattr(post, "operands", ())


def test_only_else_exits_tail_rides_then_polarity() -> None:
    universe = _universe(
        "def A(z):\n"
        "    if z == 1:\n"
        "        assert z < 2\n"
        "    else:\n"
        "        return 0\n"
        "    return z\n"
    )
    guard = py_eq(make_var("z"), num(1))
    assert universe.post() == and_(
        [
            implies(not_(guard), eq(make_var("out"), num(0))),
            implies(guard, eq(make_var("out"), make_var("z"))),
        ]
    )
    assert universe.invs() == (implies(guard, py_lt(make_var("z"), num(2))),)


def test_neither_face_exits_tail_is_unconditional() -> None:
    universe = _universe(
        "def A(z):\n"
        "    if z == 1:\n"
        "        assert z < 2\n"
        "    else:\n"
        "        assert z < 3\n"
        "    return z\n"
    )
    guard = py_eq(make_var("z"), num(1))
    assert universe.invs() == (
        implies(guard, py_lt(make_var("z"), num(2))),
        implies(not_(guard), py_lt(make_var("z"), num(3))),
    )
    assert universe.post() == eq(make_var("out"), make_var("z"))
