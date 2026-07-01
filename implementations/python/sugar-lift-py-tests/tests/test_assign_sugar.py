"""AssignSugar is a statement sugar. `name = <rhs>` is a BoundVar: the name is an
ALIAS for the rhs expression, not a snapshot of its value. The binding carries the
SOURCE (recoverable + recomposable) -- a reference recomposes it, and a later pass
(map element, curried arg, temporal rewrite) can recover the original expression. The
block threads the bound var; a comment never disturbs it."""

from __future__ import annotations

import ast
from dataclasses import replace

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import (
    BlockValue,
    BoundVar,
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.tuple_assign_sugar import TupleAssignSugar


def _desugar_assign(src: str):
    node = ast.parse(src).body[0]
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    sugar = build_node(node, filename="f.py", role=SugarRole.STATEMENT, ctx=ctx).sugar
    return complete_value(sugar.desugar(ctx), owner="assign"), ctx


def test_assign_is_a_bound_var_that_preserves_its_source():
    # `b = x` does NOT collapse to x's value -- it aliases b to the expression `x`,
    # keeping the source recoverable (what map / curry / temporal-rewrite need).
    bound, ctx = _desugar_assign("b = x")
    assert isinstance(bound, BoundVar)
    assert bound.name == "b"
    # the source is the rhs, recomposable: under a binding for x it recovers x.
    scoped = replace(
        ctx, temporal=ctx.temporal.bind_value("x", SymbolicValue(make_var("x")))
    )
    assert complete_value(bound.source.reduce(scoped), owner="src") == SymbolicValue(
        make_var("x")
    )


def test_assign_binds_a_name_resolved_by_a_later_return():
    # y = 5; return y -> the return recomposes the alias y to 5.
    assert compose_block("    y = 5\n    return y\n") == BlockValue(
        (ReturnValue(TermValue(5)),)
    )


def test_tuple_assign_binds_each_name_resolved_by_later_return():
    assert compose_block("    x, y = 1, 2\n    return y\n") == BlockValue(
        (ReturnValue(TermValue(2)),)
    )


def test_tuple_assign_selects_tuple_assign_sugar():
    result = build_node(
        ast.parse("x, y = 1, 2").body[0],
        filename="f.py",
        role=SugarRole.STATEMENT,
    )
    assert isinstance(result.sugar, TupleAssignSugar)


def test_comment_then_assign_then_return():
    assert compose_block('    "doc"\n    y = 5\n    return y\n') == BlockValue(
        (ReturnValue(TermValue(5)),)
    )


def test_assign_with_no_later_use_is_a_scope_only_block():
    # a block of just a binding has no return outcome -- the binding is scope-local.
    assert compose_block("    y = 5\n") == BlockValue(())
