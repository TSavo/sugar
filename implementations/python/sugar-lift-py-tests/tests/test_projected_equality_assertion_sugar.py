from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


def test_projected_equality_lifts_call_result_attribute_fact() -> None:
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "def test_dtype(arr):\n"
            "    assert np.any(arr).dtype == np.bool\n"
        ),
        filename="test_dtype.py",
        memento_file="test_dtype.py",
    )

    assert report is not None
    assert len(report.payload.ir) == 1
    contract = report.payload.ir[0]
    assert contract.name == "test_dtype::test_dtype::assert:3:4::assertion"
    assert contract.source_warrants[0].role == "python.projected-equality-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [
            {
                "kind": "ctor",
                "name": "py.attr",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "call:any",
                        "args": [{"kind": "var", "name": "arr"}],
                    },
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "dtype",
                    },
                ],
            },
            {
                "kind": "ctor",
                "name": "py.attr",
                "args": [
                    {"kind": "var", "name": "np"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "bool",
                    },
                ],
            },
        ],
    }
    assert [row.selected for row in report.payload.factory_walk] == [
        "ProjectedEqualityAssertionSugar"
    ]
    assert report.payload.factory_walk[0].requested_role == "AssertionSurface"


def test_projected_equality_lifts_attribute_to_attribute_fact() -> None:
    report = build_literal_call_report(
        source=(
            "def test_dtype(actual, expected):\n"
            "    assert actual.dtype == expected.dtype\n"
        ),
        filename="test_dtype.py",
        memento_file="test_dtype.py",
    )

    assert report is not None
    fact = report.payload.ir[0].inv
    assert fact["name"] == "="
    assert fact["args"] == [
        {
            "kind": "ctor",
            "name": "py.attr",
            "args": [
                {"kind": "var", "name": "actual"},
                {
                    "kind": "const",
                    "sort": {"kind": "primitive", "name": "String"},
                    "value": "dtype",
                },
            ],
        },
        {
            "kind": "ctor",
            "name": "py.attr",
            "args": [
                {"kind": "var", "name": "expected"},
                {
                    "kind": "const",
                    "sort": {"kind": "primitive", "name": "String"},
                    "value": "dtype",
                },
            ],
        },
    ]


def test_projected_equality_lifts_attribute_to_tuple_fact() -> None:
    report = build_literal_call_report(
        source=(
            "def test_shape(arr):\n"
            "    assert arr.shape == (1, 1)\n"
        ),
        filename="test_shape.py",
        memento_file="test_shape.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.projected-equality-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [
            {
                "kind": "ctor",
                "name": "py.attr",
                "args": [
                    {"kind": "var", "name": "arr"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "shape",
                    },
                ],
            },
            {
                "kind": "ctor",
                "name": "tuple",
                "args": [
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 1,
                    },
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 1,
                    },
                ],
            },
        ],
    }
    assert [row.selected for row in report.payload.factory_walk] == [
        "ProjectedEqualityAssertionSugar"
    ]


def test_projected_equality_leaves_unsupported_rhs_to_factory_gap() -> None:
    with pytest.raises(FactoryGap) as exc:
        build_literal_call_report(
            source=(
                "def test_dtype(arr, dt):\n"
                "    assert arr.dtype == dtype(f'{dt}1').itemsize\n"
            ),
            filename="test_dtype.py",
            memento_file="test_dtype.py",
        )

    assert exc.value.info["observed"] == "Attribute"
    assert exc.value.info["requested"] == "term"
