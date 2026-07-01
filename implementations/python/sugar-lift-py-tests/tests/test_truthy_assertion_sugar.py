from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


def test_truthy_assertion_lifts_name_fact() -> None:
    report = build_literal_call_report(
        source=("def test_flag(flag):\n" "    assert flag\n"),
        filename="test_truthy.py",
        memento_file="test_truthy.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.truthy-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "py.truthy",
        "args": [{"kind": "var", "name": "flag"}],
    }
    assert [row.selected for row in report.payload.factory_walk] == [
        "TruthyAssertionSugar"
    ]
    assert report.payload.factory_walk[0].requested_role == "AssertionSurface"


def test_truthy_assertion_lifts_attribute_fact() -> None:
    report = build_literal_call_report(
        source=("def test_shape(arr):\n" "    assert arr.shape\n"),
        filename="test_truthy.py",
        memento_file="test_truthy.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "py.truthy",
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
            }
        ],
    }


def test_truthy_assertion_lifts_subscript_fact() -> None:
    report = build_literal_call_report(
        source=("def test_first(values):\n" "    assert values[0]\n"),
        filename="test_truthy.py",
        memento_file="test_truthy.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "py.truthy",
        "args": [
            {
                "kind": "ctor",
                "name": "py.subscript",
                "args": [
                    {"kind": "var", "name": "values"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 0,
                    },
                ],
            }
        ],
    }


def test_truthy_assertion_lifts_binop_fact() -> None:
    report = build_literal_call_report(
        source=("def test_total(total):\n" "    assert total + 1\n"),
        filename="test_truthy.py",
        memento_file="test_truthy.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "py.truthy",
        "args": [
            {
                "kind": "ctor",
                "name": "+",
                "args": [
                    {"kind": "var", "name": "total"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 1,
                    },
                ],
            }
        ],
    }


def test_truthy_assertion_lifts_xor_binop_fact() -> None:
    report = build_literal_call_report(
        source=(
            "def test_dtype(native_repr, native_dtype, typelessdata):\n"
            "    assert ('dtype' in native_repr) ^ (native_dtype in typelessdata)\n"
        ),
        filename="test_arrayprint.py",
        memento_file="test_arrayprint.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "py.truthy",
        "args": [
            {
                "kind": "ctor",
                "name": "^",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "py.compare:In",
                        "args": [
                            {
                                "kind": "const",
                                "sort": {
                                    "kind": "primitive",
                                    "name": "String",
                                },
                                "value": "dtype",
                            },
                            {"kind": "var", "name": "native_repr"},
                        ],
                    },
                    {
                        "kind": "ctor",
                        "name": "py.compare:In",
                        "args": [
                            {"kind": "var", "name": "native_dtype"},
                            {"kind": "var", "name": "typelessdata"},
                        ],
                    },
                ],
            }
        ],
    }
