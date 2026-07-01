from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


def _literal_chain_status(contract) -> str:
    inv = contract.inv
    assert inv["kind"] == "and"
    values = []
    for item in inv["operands"]:
        assert item["kind"] == "atomic"
        left, right = item["args"]
        assert left["kind"] == "const"
        assert right["kind"] == "const"
        values.append((item["name"], left["value"], right["value"]))

    def holds(name: str, left, right) -> bool:
        if name == "=":
            return left == right
        if name == "≠":
            return left != right
        if name == "<":
            return left < right
        if name == "≤":
            return left <= right
        if name == ">":
            return left > right
        if name == "≥":
            return left >= right
        raise AssertionError(f"unexpected operator {name!r}")

    return (
        "sat"
        if all(holds(name, left, right) for name, left, right in values)
        else "unsat"
    )


def test_chained_equality_assertion_emits_sat_and_unsat_twins() -> None:
    good = build_literal_call_report(
        source=(
            "def test_device():\n"
            "    assert 'cpu' == 'cpu' == 'cpu'\n"
        ),
        filename="test_device.py",
        memento_file="test_device.py",
    )
    bad = build_literal_call_report(
        source=(
            "def test_device():\n"
            "    assert 'cpu' == 'cpu' == 'gpu'\n"
        ),
        filename="test_device.py",
        memento_file="test_device.py",
    )

    assert good is not None
    assert bad is not None
    assert _literal_chain_status(good.payload.ir[0]) == "sat"
    assert _literal_chain_status(bad.payload.ir[0]) == "unsat"
    assert good.payload.ir[0].source_warrants[0].role == (
        "python.chained-comparison-assertion-sugar"
    )
    assert [row.selected for row in good.payload.factory_walk] == [
        "ChainedComparisonAssertionSugar"
    ]


def test_chained_order_assertion_lowers_adjacent_pairs() -> None:
    report = build_literal_call_report(
        source=(
            "def test_order():\n"
            "    assert 1 < 2 <= 3\n"
        ),
        filename="test_order.py",
        memento_file="test_order.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.inv == {
        "kind": "and",
        "operands": [
            {
                "kind": "atomic",
                "name": "<",
                "args": [
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 1,
                    },
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 2,
                    },
                ],
            },
            {
                "kind": "atomic",
                "name": "≤",
                "args": [
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 2,
                    },
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 3,
                    },
                ],
            },
        ],
    }


def test_chained_assertion_keeps_call_and_attribute_terms_symbolic() -> None:
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "\n"
            "def test_default_device(info):\n"
            "    assert info.default_device() == 'cpu' == np.asarray(0).device\n"
        ),
        filename="test_array_api_info.py",
        memento_file="test_array_api_info.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == (
        "python.chained-comparison-assertion-sugar"
    )
    assert contract.inv == {
        "kind": "and",
        "operands": [
            {
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "ctor", "name": "call:default_device", "args": []},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "cpu",
                    },
                ],
            },
            {
                "kind": "atomic",
                "name": "=",
                "args": [
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "cpu",
                    },
                    {
                        "kind": "ctor",
                        "name": "py.attr",
                        "args": [
                            {
                                "kind": "ctor",
                                "name": "call:numpy.asarray",
                                "args": [
                                    {
                                        "kind": "const",
                                        "sort": {"kind": "primitive", "name": "Int"},
                                        "value": 0,
                                    }
                                ],
                            },
                            {
                                "kind": "const",
                                "sort": {"kind": "primitive", "name": "String"},
                                "value": "device",
                            },
                        ],
                    },
                ],
            },
        ],
    }
    assert [row.selected for row in report.payload.factory_walk] == [
        "ChainedComparisonAssertionSugar"
    ]
    assert report.payload.call_edges == [
        {
            "kind": "call-edge",
            "schemaVersion": "1",
            "sourceContract": contract.name,
            "targetSymbol": "call:numpy.asarray",
            "targetContract": None,
            "targetContractCid": None,
            "callSiteLocus": {
                "file": "test_array_api_info.py",
                "line": 4,
                "column": 45,
            },
        }
    ]
