from __future__ import annotations

import ast

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, make_var, num


@pytest.mark.parametrize("source", ["2 ** 53", "10 ** -2", "(-2) ** 3"])
def test_concrete_power_folds_exactly_like_python(source: str) -> None:
    value = reduce_value(source)

    assert value == TermValue(eval(source))


def test_symbolic_power_uses_the_native_operator_coordinate() -> None:
    value = reduce_value("base ** exponent", {
        "base": SymbolicValue(make_var("base")),
        "exponent": SymbolicValue(make_var("exponent")),
    })

    assert value == SymbolicValue(
        ctor("**", [make_var("base"), make_var("exponent")])
    )


def test_concrete_base_with_symbolic_exponent_uses_the_same_coordinate() -> None:
    value = reduce_value(
        "2 ** exponent", {"exponent": SymbolicValue(make_var("exponent"))}
    )

    assert value == SymbolicValue(ctor("**", [num(2), make_var("exponent")]))


def test_power_owner_selects_only_pow_binop() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    pow_result = build_node(
        ast.parse("2 ** 3", mode="eval").body,
        filename="t.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )

    assert pow_result.audit_row.selected == "PowerOpSugar"
    with pytest.raises(FactoryPanic, match="observed=BinOp requested=term"):
        build_node(
            ast.parse("2 | 3", mode="eval").body,
            filename="t.py",
            role=SugarRole.TERM,
            ctx=ctx,
        )
