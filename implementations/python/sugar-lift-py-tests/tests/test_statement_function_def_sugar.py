from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    DictValue,
    TermValue,
    TupleValue,
    UniverseValue,
)
from sugar_lift_py_tests.ir import ctor, num
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


def test_nested_callable_binds_an_omitted_trailing_default_without_rekeying_callsite() -> (
    None
):
    universe = _root_universe(
        "def outer():\n"
        "    def inner(y, increment=4):\n"
        "        return y + increment\n"
        "    return inner(5)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("y", "increment")
    assert callsite.arg_values == (TermValue(5), TermValue(4))
    # Identity belongs to the consumer spelling, not to the expanded binding.
    assert callsite.term == ctor("call:inner", [num(5)])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="nested default regression", project_callsite=False
    ) == TermValue(9)


def test_nested_callable_binds_multiple_omitted_trailing_defaults_in_formal_order() -> (
    None
):
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, first=4, second=6):\n"
        "        return required + first + second\n"
        "    return inner(5)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("required", "first", "second")
    assert callsite.arg_values == (TermValue(5), TermValue(4), TermValue(6))
    assert callsite.term == ctor("call:inner", [num(5)])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="multiple default alignment", project_callsite=False
    ) == TermValue(15)


def test_nested_callable_supplied_positional_overrides_only_its_aligned_default() -> (
    None
):
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, first=4, second=6):\n"
        "        return required + first + second\n"
        "    return inner(5, 10)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.arg_values == (TermValue(5), TermValue(10), TermValue(6))
    assert callsite.term == ctor("call:inner", [num(5), num(10)])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="supplied default override", project_callsite=False
    ) == TermValue(21)


def test_nested_callable_default_is_assigned_once_at_its_temporal_coordinate() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    x = 5\n"
        "    def inner(value=x):\n"
        "        return value\n"
        "    x = 9\n"
        "    return inner()\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.arg_values == (TermValue(5),)
    assert callsite.term == ctor("call:inner", [])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="nested default assignment", project_callsite=False
    ) == TermValue(5)


def test_nested_callable_missing_required_positional_stays_a_signature_gap() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _root_universe(
            "def outer(x):\n"
            "    def inner(required, optional=4):\n"
            "        return required + optional\n"
            "    return inner()\n"
        )

    assert raised.value.info.owner == "FunctionCallable"
    assert raised.value.info.requested == "bind call arguments to a function signature"
    assert raised.value.info.observed == ("positional", "positional")


def test_nested_callable_extra_positional_stays_a_signature_gap() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _root_universe(
            "def outer(x):\n"
            "    def inner(required, optional=4):\n"
            "        return required + optional\n"
            "    return inner(x, 6, 7)\n"
        )

    assert raised.value.info.owner == "FunctionCallable"
    assert raised.value.info.requested == "bind call arguments to a function signature"
    assert raised.value.info.observed == ("positional", "positional")


def test_nested_callable_binds_empty_variadic_parameters_without_rekeying_callsite() -> (
    None
):
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, /, *extras, **options):\n"
        "        return extras\n"
        "    return inner(5)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("required", "extras", "options")
    assert callsite.arg_values == (TermValue(5), TupleValue(()), DictValue(()))
    assert callsite.term == ctor("call:inner", [num(5)])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="empty variadic binding", project_callsite=False
    ) == TupleValue(())


def test_nested_callable_collects_surplus_positionals_in_source_order_without_rekeying_callsite() -> (
    None
):
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, /, *extras, **options):\n"
        "        return extras\n"
        "    return inner(5, 6, 7, 8)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("required", "extras", "options")
    assert callsite.arg_values == (
        TermValue(5),
        TupleValue((TermValue(6), TermValue(7), TermValue(8))),
        DictValue(()),
    )
    assert callsite.term == ctor("call:inner", [num(5), num(6), num(7), num(8)])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="surplus positional binding", project_callsite=False
    ) == TupleValue((TermValue(6), TermValue(7), TermValue(8)))


def test_nested_callable_aligns_positional_default_before_collecting_surplus() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, optional=4, *extras, **options):\n"
        "        return extras\n"
        "    return inner(5, 10, 11, 12)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("required", "optional", "extras", "options")
    assert callsite.arg_values == (
        TermValue(5),
        TermValue(10),
        TupleValue((TermValue(11), TermValue(12))),
        DictValue(()),
    )
    assert callsite.term == ctor("call:inner", [num(5), num(10), num(11), num(12)])


def test_nested_callable_omitted_positional_default_precedes_empty_variadics() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, optional=4, *extras, **options):\n"
        "        return optional\n"
        "    return inner(5)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.arg_values == (
        TermValue(5),
        TermValue(4),
        TupleValue(()),
        DictValue(()),
    )
    assert callsite.term == ctor("call:inner", [num(5)])


def test_nested_callable_exact_fixed_positional_control_stays_unchanged() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required):\n"
        "        return required\n"
        "    return inner(5)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("required",)
    assert callsite.arg_values == (TermValue(5),)
    assert callsite.term == ctor("call:inner", [num(5)])


def test_nested_callable_binds_one_omitted_keyword_only_default() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, *, increment=4):\n"
        "        return required + increment\n"
        "    return inner(5)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("required", "increment")
    assert callsite.arg_values == (TermValue(5), TermValue(4))
    assert callsite.term == ctor("call:inner", [num(5)])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="keyword-only default omission", project_callsite=False
    ) == TermValue(9)


def test_nested_callable_binds_multiple_keyword_only_defaults_in_exact_order() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(*, first=4, second=6):\n"
        "        return first * 10 + second\n"
        "    return inner()\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("first", "second")
    assert callsite.arg_values == (TermValue(4), TermValue(6))
    assert callsite.term == ctor("call:inner", [])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="keyword-only default order", project_callsite=False
    ) == TermValue(46)


def test_nested_callable_separates_positional_and_keyword_only_defaults() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(positional=3, *, keyword_only=7):\n"
        "        return positional * 10 + keyword_only\n"
        "    return inner()\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("positional", "keyword_only")
    assert callsite.arg_values == (TermValue(3), TermValue(7))
    assert callsite.term == ctor("call:inner", [])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="separate default alignment", project_callsite=False
    ) == TermValue(37)


def test_nested_callable_keyword_only_default_is_captured_at_definition_time() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    captured = 5\n"
        "    def inner(*, value=captured):\n"
        "        return value\n"
        "    captured = 9\n"
        "    return inner()\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.arg_values == (TermValue(5),)
    assert callsite.term == ctor("call:inner", [])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="keyword-only default capture", project_callsite=False
    ) == TermValue(5)


def test_nested_callable_missing_required_keyword_only_stays_a_signature_gap() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _root_universe(
            "def outer():\n"
            "    def inner(*, required):\n"
            "        return required\n"
            "    return inner()\n"
        )

    assert raised.value.info.owner == "FunctionCallable"
    assert raised.value.info.requested == "bind call arguments to a function signature"
    assert raised.value.info.observed == ("keyword-only",)


def test_nested_callable_keyword_only_boundary_is_not_filled_by_surplus_positionals() -> (
    None
):
    with pytest.raises(FactoryPanic) as raised:
        _root_universe(
            "def outer():\n"
            "    def inner(required, /, *extras, flag, **options):\n"
            "        return extras\n"
            "    return inner(5, 6, 7)\n"
        )

    assert raised.value.info.owner == "FunctionCallable"
    assert raised.value.info.requested == "bind call arguments to a function signature"
    assert raised.value.info.observed == (
        "positional-only",
        "var-positional",
        "keyword-only",
        "var-keyword",
    )


def test_nested_callable_empty_variadics_do_not_hide_missing_required_positional() -> (
    None
):
    with pytest.raises(FactoryPanic) as raised:
        _root_universe(
            "def outer():\n"
            "    def inner(required, *extras, **options):\n"
            "        return required\n"
            "    return inner()\n"
        )

    assert raised.value.info.owner == "FunctionCallable"
    assert raised.value.info.requested == "bind call arguments to a function signature"
    assert raised.value.info.observed == (
        "positional",
        "var-positional",
        "var-keyword",
    )


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
