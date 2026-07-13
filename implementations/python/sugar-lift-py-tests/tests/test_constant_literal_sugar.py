from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.ir import ctor, real_lit
from sugar_lift_py_tests.outcome import Complete


def _build(node: ast.AST):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    return build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar, ctx


def test_ellipsis_constant_constructs_as_native_singleton_coordinate() -> None:
    sugar, ctx = _build(ast.parse("...", mode="eval").body)

    assert type(sugar).__name__ == "EllipsisLiteralSugar"
    assert sugar.desugar(ctx) == Complete(SymbolicValue(ctor("py.ellipsis", [])))


def test_complex_constant_constructs_with_real_and_imaginary_coordinates() -> None:
    sugar, ctx = _build(ast.parse("2+3j", mode="eval").body.right)

    assert type(sugar).__name__ == "ComplexLiteralSugar"
    assert sugar.desugar(ctx) == Complete(
        SymbolicValue(ctor("py.complex", [real_lit("0.0"), real_lit("3.0")]))
    )


def test_fractional_complex_parts_preserve_real_terms() -> None:
    sugar, ctx = _build(ast.Constant(value=complex(1.5, -2.25)))

    assert sugar.desugar(ctx) == Complete(
        SymbolicValue(ctor("py.complex", [real_lit("1.5"), real_lit("-2.25")]))
    )


def test_unowned_constant_kind_stays_a_loud_factory_gap() -> None:
    with pytest.raises(FactoryPanic, match="observed=Constant requested=term"):
        _build(ast.Constant(value=frozenset({1})))
