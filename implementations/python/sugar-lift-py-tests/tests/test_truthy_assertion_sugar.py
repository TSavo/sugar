from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory import FactoryGap
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


def test_truthy_assertion_dispatches_bound_local_object_bool_dunder() -> None:
    report = build_literal_call_report(
        source=(
            "class Truthy:\n"
            "    def __bool__(self):\n"
            "        return True\n"
            "\n"
            "def test_truthy_object():\n"
            "    x = Truthy()\n"
            "    assert x\n"
        ),
        filename="test_truthy_bound_object.py",
        memento_file="test_truthy_bound_object.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.truthy-assertion-sugar"
    assert contract.inv == _bool_eq(True, True)


def test_truthy_assertion_dispatches_constructor_bound_attribute_object_bool_dunder() -> (
    None
):
    report = build_literal_call_report(
        source=(
            "class Flag:\n"
            "    def __bool__(self):\n"
            "        return True\n"
            "\n"
            "class Box:\n"
            "    def __init__(self, flag):\n"
            "        self.flag = flag\n"
            "\n"
            "def test_box_flag_truthy():\n"
            "    x = Box(Flag())\n"
            "    assert x.flag\n"
        ),
        filename="test_truthy_attribute_object.py",
        memento_file="test_truthy_attribute_object.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == _bool_eq(True, True)


def test_truthy_assertion_uses_len_fallback_after_missing_bool_dunder() -> None:
    sat = build_literal_call_report(
        source=_sized_truthiness_source(size=1),
        filename="test_truthy_len_sat.py",
        memento_file="test_truthy_len_sat.py",
    )
    unsat = build_literal_call_report(
        source=_sized_truthiness_source(size=0),
        filename="test_truthy_len_unsat.py",
        memento_file="test_truthy_len_unsat.py",
    )

    assert sat is not None
    assert unsat is not None
    sat_inv = sat.payload.ir[0].inv
    unsat_inv = unsat.payload.ir[0].inv
    assert sat_inv == _int_ne(1, 0)
    assert unsat_inv == _int_ne(0, 0)
    assert _truth_formula_status(sat_inv) == "sat"
    assert _truth_formula_status(unsat_inv) == "unsat"


def test_truthy_assertion_keeps_external_call_truth_as_symbolic_py_truthy() -> None:
    report = build_literal_call_report(
        source=("def test_external(value):\n" "    assert external_call(value)\n"),
        filename="test_truthy_external_call.py",
        memento_file="test_truthy_external_call.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "py.truthy",
        "args": [
            {
                "kind": "ctor",
                "name": "call:external_call",
                "args": [{"kind": "var", "name": "value"}],
            }
        ],
    }


def test_truthy_assertion_without_bool_or_len_is_a_named_floor_gap() -> None:
    with pytest.raises(FactoryGap) as raised:
        build_literal_call_report(
            source=(
                "class Empty:\n"
                "    pass\n"
                "\n"
                "def test_empty():\n"
                "    x = Empty()\n"
                "    assert x\n"
            ),
            filename="test_truthy_missing_dunders.py",
            memento_file="test_truthy_missing_dunders.py",
        )

    assert raised.value.info == {
        "owner": "TruthyAssertionSugar",
        "blame": "test_truthy_missing_dunders.py:6:4",
        "observed": "Empty.__len__",
        "requested": "constructor-bound method",
        "fix": ("define `__len__` on `Empty` or add the floor that owns this method"),
    }


def _sized_truthiness_source(*, size: int) -> str:
    return (
        "class Sized:\n"
        "    def __init__(self, n):\n"
        "        self.n = n\n"
        "\n"
        "    def __len__(self):\n"
        "        return self.n\n"
        "\n"
        "def test_sized_truthy():\n"
        f"    x = Sized({size})\n"
        "    assert x\n"
    )


def _bool_eq(actual: bool, expected: bool) -> dict:
    return {
        "kind": "atomic",
        "name": "=",
        "args": [_bool_const(actual), _bool_const(expected)],
    }


def _bool_const(value: bool) -> dict:
    return {
        "kind": "const",
        "sort": {"kind": "primitive", "name": "Bool"},
        "value": value,
    }


def _int_ne(actual: int, expected: int) -> dict:
    return {
        "kind": "atomic",
        "name": "≠",
        "args": [_int_const(actual), _int_const(expected)],
    }


def _int_const(value: int) -> dict:
    return {
        "kind": "const",
        "sort": {"kind": "primitive", "name": "Int"},
        "value": value,
    }


def _truth_formula_status(formula: dict) -> str:
    assert formula["kind"] == "atomic"
    left, right = formula["args"]
    if formula["name"] == "=":
        return "sat" if left == right else "unsat"
    if formula["name"] == "≠":
        return "sat" if left != right else "unsat"
    raise AssertionError(f"unexpected truth formula {formula!r}")
