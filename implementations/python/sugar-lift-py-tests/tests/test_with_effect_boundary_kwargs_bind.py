"""Leftover keywords fill a unique **kwargs formal; leftover positionals do not."""

from sugar_lift_py_tests.context_manager_contract import (
    CallParameterV1,
    ContextManagerContractError,
    ImportSignatureV2,
    LiteralDefaultV1,
    NoDefaultV1,
    PositionalOrKeywordV1,
    PrimitiveSort,
    VariadicKeywordEntryProjectionV1,
    VariadicKeywordV1,
    VariadicPositionalV1,
    project_formal_selector_v1,
)
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import _bind_real_actuals
import pytest


def _signature():
    value = PrimitiveSort("Value")
    none = LiteralDefaultV1({"kind": "ctor", "name": "None", "args": []})
    return ImportSignatureV2(
        (
            CallParameterV1(
                "expected_exception",
                value,
                PositionalOrKeywordV1(),
                False,
                none,
            ),
            CallParameterV1(
                "func",
                value,
                PositionalOrKeywordV1(),
                False,
                none,
            ),
            CallParameterV1(
                "args",
                value,
                VariadicPositionalV1(),
                False,
                NoDefaultV1(),
            ),
            CallParameterV1(
                "kwargs",
                value,
                VariadicKeywordV1(),
                False,
                NoDefaultV1(),
            ),
        )
    )


def _call(*positionals, **keywords):
    names = tuple(keywords)
    return CallSiteValue(
        target_name="pytest.raises",
        arg_values=(*positionals, *keywords.values()),
        parameters=(),
        term=ctor("python:call", ()),
        body=None,
        keyword_names=names,
    )


def test_leftover_match_keyword_fills_the_unique_kwargs_formal():
    expected = StringValue("ValueError")
    boom = StringValue("boom")
    fixed, keywords = _bind_real_actuals(
        _signature(),
        _call(expected, match=boom),
    )
    assert fixed[0] is expected
    assert 1 not in fixed
    pack = keywords[3]
    assert pack.formal_index == 3
    assert project_formal_selector_v1(
        VariadicKeywordEntryProjectionV1(3, "match"),
        fixed_actuals=fixed,
        variadic_positional_actuals={},
        variadic_keyword_actuals=keywords,
    ) is boom


def test_leftover_positionals_still_do_not_fit_the_signature():
    expected = StringValue("ValueError")
    func = StringValue("int")
    argument = StringValue("bad")
    with pytest.raises(
        ContextManagerContractError,
        match="call actual does not fit authenticated signature",
    ):
        _bind_real_actuals(_signature(), _call(expected, func, argument))
