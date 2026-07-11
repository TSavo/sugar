"""The guards ruling: a symbolic condition cannot pick a face, so it GUARDS
both. The then-face's entries ride under the guard, the continuation rides
under its negation when the then-face exits, and the universe emits guarded
implications -- the dig shape: `if x == "ccc": return "yyy"` yields
`implies(eq(x, "ccc"), eq(out, "yyy"))`. Vacuous off the guard, forced on it."""

from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import UniverseValue
from sugar_lift_py_tests.ir import and_, eq, implies, lt, make_var, not_, num, str_const
from sugar_lift_py_tests.outcome import complete_value


def _universe(source: str) -> UniverseValue:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    result = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    value = complete_value(result.sugar.desugar(ctx), owner="test")
    assert isinstance(value, UniverseValue)
    return value


def test_the_dig_shape_emits_the_guarded_implication() -> None:
    universe = _universe(
        'def enc(x):\n    if x == "ccc":\n        return "yyy"\n    return x\n'
    )
    guard = eq(make_var("x"), str_const("ccc"))
    assert universe.post() == and_(
        [
            implies(guard, eq(make_var("out"), str_const("yyy"))),
            implies(not_(guard), eq(make_var("out"), make_var("x"))),
        ]
    )


def test_an_inv_stated_under_a_guard_is_an_implication() -> None:
    universe = _universe(
        "def A(z):\n"
        "    if z == 1:\n"
        "        assert z < 2\n"
        "    return z\n"
    )
    guard = eq(make_var("z"), num(1))
    assert universe.invs() == (
        implies(guard, lt(make_var("z"), num(2))),
    )
    # the then-face states but does not exit: the continuation is unconditional
    assert universe.post() == eq(make_var("out"), make_var("z"))


def test_a_ground_condition_still_picks_its_face() -> None:
    universe = _universe(
        "def A(z):\n    if 1 == 1:\n        return z\n    return 0\n"
    )
    assert universe.post() == eq(make_var("out"), make_var("z"))
