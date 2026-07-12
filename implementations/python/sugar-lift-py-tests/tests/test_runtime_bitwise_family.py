from __future__ import annotations

import ast

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import Bv32Value, CallSiteValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, make_var, num


@pytest.mark.parametrize(
    ("source", "expected"),
    [("6 & 3", 6 & 3), ("6 ^ 3", 6 ^ 3), ("3 << 4", 3 << 4), ("17 >> 2", 17 >> 2)],
)
def test_concrete_integer_bitwise_folds_like_python(source: str, expected: int) -> None:
    assert reduce_value(source) == TermValue(expected)


@pytest.mark.parametrize(
    ("source", "operator"),
    [("x & 3", "&"), ("x ^ 3", "^"), ("x << 3", "<<"), ("x >> 3", ">>")],
)
def test_symbolic_bitwise_uses_native_operator_coordinate(
    source: str, operator: str
) -> None:
    assert reduce_value(source, {"x": SymbolicValue(make_var("x"))}) == SymbolicValue(
        ctor(operator, [make_var("x"), num(3)])
    )


@pytest.mark.parametrize(
    ("source", "operator"),
    [("x & 15", "bv32.and"), ("x ^ 3", "bv32.xor"), ("x << 2", "bv32.shl"), ("x >> 2", "bv32.lshr")],
)
def test_bv32_bitwise_uses_existing_bv32_vocabulary(
    source: str, operator: str
) -> None:
    assert reduce_value(source, {"x": Bv32Value(make_var("x"))}) == Bv32Value(
        ctor(operator, [make_var("x"), num(int(source.rsplit(" ", 1)[1]))])
    )


def test_callsite_invert_uses_existing_symbolic_invert_coordinate() -> None:
    call = CallSiteValue("opaque", (), (), make_var("call"), None)

    assert reduce_value("~x", {"x": call}) == SymbolicValue(
        ctor("py.invert", [make_var("call")])
    )


def test_runtime_owner_excludes_bit_or_annotation_ambiguity() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    owned = build_node(
        ast.parse("x & y", mode="eval").body,
        filename="t.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )

    assert owned.audit_row.selected == "RuntimeBitwiseOpSugar"
    with pytest.raises(FactoryPanic, match="observed=BinOp requested=term"):
        build_node(
            ast.parse("int | str", mode="eval").body,
            filename="t.py",
            role=SugarRole.TERM,
            ctx=ctx,
        )


def test_bv32_invert_stays_loud_without_a_native_vocabulary_term() -> None:
    with pytest.raises(FactoryPanic, match="observed=Bv32Value"):
        reduce_value("~x", {"x": Bv32Value(make_var("x"))})
