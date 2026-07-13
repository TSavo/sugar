from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import CallSiteValue, TermValue, UniverseValue
from sugar_lift_py_tests.outcome import complete_value


def _root_universe(source: str) -> UniverseValue:
    node = ast.parse(source).body[0]
    catalog = default_catalog()
    ctx = FactoryBuildContext(filename="nested.py", catalog=catalog)
    result = build_node(
        node,
        filename="nested.py",
        role=SugarRole("definition"),
        ctx=ctx,
    )
    value = complete_value(result.sugar.desugar(ctx), owner="nested def regression")
    assert isinstance(value, UniverseValue)
    return value


def test_nested_def_binds_named_callable_and_later_call_digs_body() -> None:
    universe = _root_universe(
        "def outer(x):\n"
        "    def inner(y):\n"
        "        return y + 1\n"
        "    return inner(x)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    dug = callsite.force_floor(
        ctx, owner="nested def regression", project_callsite=False
    )
    assert isinstance(dug, TermValue)
    assert dug.value == 6
    assert "inner" in repr(universe.record)


def test_nested_callable_captures_lexical_bindings_and_overlays_actuals() -> None:
    universe = _root_universe(
        "def outer(x):\n"
        "    offset = 4\n"
        "    def inner(y):\n"
        "        adjusted = y + offset\n"
        "        return adjusted\n"
        "    return inner(x)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    dug = callsite.force_floor(
        ctx, owner="nested closure regression", project_callsite=False
    )
    assert dug == TermValue(9)


def test_decorated_statement_def_stays_loud() -> None:
    node = (
        ast.parse(
            "def outer(x):\n"
            "    @decorate\n"
            "    def inner(y):\n"
            "        return y\n"
            "    return inner(x)\n"
        )
        .body[0]
        .body[0]
    )
    catalog = default_catalog()
    ctx = FactoryBuildContext(filename="decorated.py", catalog=catalog)

    result = build_node(
        node,
        filename="decorated.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )
    with pytest.raises(FactoryPanic) as raised:
        result.sugar.desugar(ctx)

    assert raised.value.info.observed == "decorate"
    assert raised.value.info.requested == "value"
    assert "bind `decorate`" in raised.value.info.fix


def test_definition_and_statement_roles_have_distinct_registered_owners() -> None:
    claims = {claim.name: claim for claim in default_catalog().claims}

    assert claims["FunctionDefSugar"].role.value == "definition"
    assert claims["TestFunctionDefSugar"].role.value == "definition"
    assert claims["StatementFunctionDefSugar"].role is SugarRole.STATEMENT
