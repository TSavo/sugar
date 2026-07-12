"""A full first-axis slice plus integer column is one tuple index coordinate."""

from __future__ import annotations

import ast

import pytest
from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.lift_rpc import audit_lift_file

NONE = ctor("None", [])


def _site(expr: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(expr, mode="eval").body, "vendor.py")


def test_full_slice_integer_column_uses_tuple_index_coordinate() -> None:
    value = reduce_value(
        "values[:, 0]",
        {"values": SymbolicValue(make_var("values"))},
    )

    assert isinstance(value, CallSiteValue)
    assert value.term == ctor(
        "py.subscript",
        [
            make_var("values"),
            ctor(
                "tuple",
                [ctor("py.slice", [NONE, NONE, NONE]), num(0)],
            ),
        ],
    )


def test_other_multiaxis_index_partitions_stay_loud() -> None:
    for expression in ("values[:, 1:]", "values[:, [0]]", "values[1:, 0]"):
        with pytest.raises(FactoryPanic):
            build_node(
                ast.parse(expression, mode="eval").body,
                filename="vendor.py",
                role=SugarRole.TERM,
            )


def test_owner_is_exactly_full_slice_integer_column_partition() -> None:
    catalog = default_catalog()
    assert [
        candidate.name
        for candidate in catalog.candidates_for(SugarRole.TERM, _site("values[:, 0]"))
    ] == ["FullSliceColumnSubscriptSugar"]
    assert not list(catalog.candidates_for(SugarRole.TERM, _site("values[:, 1:]")))


def test_real_frame_file_shape_has_no_subscript_factory_panic() -> None:
    source = """
def first_column(value):
    return value.iloc[:, 0]
"""
    recovered = audit_lift_file(source, "core/frame.py", recover_panics=True)
    assert all(panic.gap["observed"] != "Subscript" for panic in recovered.panics)
