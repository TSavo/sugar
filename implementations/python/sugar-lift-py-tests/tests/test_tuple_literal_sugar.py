"""TupleLiteralSugar reduces a Python tuple literal to the `tuple` ctor."""

from __future__ import annotations

import ast

import pytest

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.claim import SugarCatalog, SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.floor import ArrayLiteral, TermValue
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.ir import ctor, num
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.list_literal_sugar import LIST_LITERAL_CLAIM
from sugar_lift_py_tests.sugar.primitive_literal_sugar import PRIMITIVE_LITERAL_CLAIM
from sugar_lift_py_tests.sugar.sugar_base import registered_claims
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.sugar.tuple_literal_sugar import (
    TupleLiteralSugar,
)  # noqa: F401
from sugar_lift_py_tests.temporal import TemporalContext


def _claim(name: str):
    return next(claim for claim in registered_claims() if claim.name == name)


def _reduce_with_log(expr: str):
    build_ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    body = build_ctx.build_body(ast.parse(expr, mode="eval").body, SugarRole.TERM)
    reduce_ctx = ReduceContext(temporal=TemporalContext.empty())
    value = complete_value(body.reduce(reduce_ctx), owner="tuple literal dispatch")
    return value, reduce_ctx.operation_log


def _reduce_with_catalog_and_log(expr: str, catalog: SugarCatalog):
    build_ctx = FactoryBuildContext(filename="t.py", catalog=catalog)
    body = build_ctx.build_body(ast.parse(expr, mode="eval").body, SugarRole.TERM)
    reduce_ctx = ReduceContext(temporal=TemporalContext.empty())
    value = complete_value(body.reduce(reduce_ctx), owner="sequence literal dispatch")
    return value, reduce_ctx.operation_log


def test_tuple_reduces_to_tuple_ctor() -> None:
    assert fol(reduce_term("(1, 1)")) == fol(ctor("tuple", [num(1), num(1)]))


def test_singleton_tuple_reduces_to_tuple_ctor() -> None:
    assert fol(reduce_term("(1,)")) == fol(ctor("tuple", [num(1)]))


def test_tuple_literal_constructs_through_floor_operation_log() -> None:
    value, operation_log = _reduce_with_log("(1, 2)")

    assert fol(floor_to_term(value, owner="tuple literal dispatch")) == fol(
        ctor("tuple", [num(1), num(2)])
    )
    assert operation_log == [
        (
            "TupleLiteralSugar",
            "construct_sequence_with",
            "SequenceConstructionOperation",
        )
    ]


def test_list_literal_constructs_through_floor_operation_when_selected() -> None:
    value, operation_log = _reduce_with_catalog_and_log(
        "[1, 2]",
        SugarCatalog([LIST_LITERAL_CLAIM, PRIMITIVE_LITERAL_CLAIM]),
    )

    assert value == ArrayLiteral((TermValue(1), TermValue(2)))
    assert operation_log == [
        ("ListLiteralSugar", "construct_sequence_with", "SequenceConstructionOperation")
    ]


def test_list_literal_accepts_tuple_elements_through_floor_operation() -> None:
    value, operation_log = _reduce_with_catalog_and_log(
        "[(1, 2)]",
        SugarCatalog(
            [LIST_LITERAL_CLAIM, _claim("TupleLiteralSugar"), PRIMITIVE_LITERAL_CLAIM]
        ),
    )

    assert value == ArrayLiteral((TupleLiteralValue((TermValue(1), TermValue(2))),))
    assert operation_log == [
        (
            "TupleLiteralSugar",
            "construct_sequence_with",
            "SequenceConstructionOperation",
        ),
        (
            "ListLiteralSugar",
            "construct_sequence_with",
            "SequenceConstructionOperation",
        ),
    ]


def test_list_literal_bad_element_floor_is_named_by_sequence_operation() -> None:
    with pytest.raises(FactoryGap) as raised:
        _reduce_with_catalog_and_log(
            "[1, 'x']",
            SugarCatalog([LIST_LITERAL_CLAIM, PRIMITIVE_LITERAL_CLAIM]),
        )

    assert raised.value.info == {
        "owner": "ListLiteralSugar",
        "blame": "t.py:1:0",
        "observed": "ListLiteralSugar element StringValue",
        "requested": "list element floor",
        "fix": "add ListLiteralSugar construction support for StringValue",
        "gap_kind": "Floor",
        "gap_locus": "Construction",
    }
