from __future__ import annotations

from sugar_lift_py_tests.effect import RuntimeEffect
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
    assert (
        contract.source_warrants[0].role == "python.projected-equality-assertion-sugar"
    )
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
                        "name": "call:numpy.any",
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
        source=("def test_shape(arr):\n" "    assert arr.shape == (1, 1)\n"),
        filename="test_shape.py",
        memento_file="test_shape.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert (
        contract.source_warrants[0].role == "python.projected-equality-assertion-sugar"
    )
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


def test_projected_equality_keeps_non_constructor_bound_attribute_symbolic() -> None:
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "def test_dtype():\n"
            "    arr = np.array(['a'])\n"
            "    assert arr.dtype == np.str_\n"
        ),
        filename="test_dtype.py",
        memento_file="test_dtype.py",
    )

    assert report is not None
    left = report.payload.ir[0].inv["args"][0]
    assert left["kind"] == "ctor"
    assert left["name"] == "py.attr"
    assert left["args"][0]["kind"] == "var"
    assert left["args"][0]["name"] == "arr"
    assert left["args"][1]["value"] == "dtype"


def test_projected_equality_emits_external_bridge_edge_for_import_without_source() -> (
    None
):
    report = build_literal_call_report(
        source=(
            "import math\n"
            "def test_sqrt(actual):\n"
            "    assert actual.value == math.sqrt(4)\n"
        ),
        filename="test_sqrt.py",
        memento_file="test_sqrt.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [
            {
                "kind": "ctor",
                "name": "py.attr",
                "args": [
                    {"kind": "var", "name": "actual"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "value",
                    },
                ],
            },
            {
                "kind": "ctor",
                "name": "call:math.sqrt",
                "args": [
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 4,
                    }
                ],
            },
        ],
    }
    assert report.payload.call_edges == [
        {
            "kind": "call-edge",
            "schemaVersion": "1",
            "sourceContract": contract.name,
            "targetSymbol": "call:math.sqrt",
            "targetContract": None,
            "targetContractCid": None,
            "callSiteLocus": {
                "file": "test_sqrt.py",
                "line": 3,
                "column": 27,
            },
        }
    ]


def test_projected_equality_external_bridge_edge_uses_dependency_binding() -> None:
    report = build_literal_call_report(
        source=(
            "import math\n"
            "def test_sqrt(actual):\n"
            "    assert actual.value == math.sqrt(4)\n"
        ),
        filename="test_sqrt.py",
        memento_file="test_sqrt.py",
        contract_bindings=[
            {
                "name": "native::sqrt::callable",
                "contract_cid": "blake3-512:math-sqrt-contract",
                "target_proof_cid": "blake3-512:math-proof",
                "bridgeSourceSymbol": "call:math.sqrt",
            }
        ],
    )

    assert report is not None
    edge = report.payload.call_edges[0]
    assert edge["targetSymbol"] == "call:math.sqrt"
    assert edge["targetContract"] == "native::sqrt::callable"
    assert edge["targetContractCid"] == "blake3-512:math-sqrt-contract"
    assert edge["targetProofCid"] == "blake3-512:math-proof"


def test_projected_equality_lifts_fstring_rhs_attribute() -> None:
    report = build_literal_call_report(
        source=(
            "def test_dtype(arr, dt):\n"
            "    assert arr.dtype == dtype(f'{dt}1').itemsize\n"
        ),
        filename="test_dtype.py",
        memento_file="test_dtype.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
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
                        "value": "dtype",
                    },
                ],
            },
            {
                "kind": "ctor",
                "name": "py.attr",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "call:dtype",
                        "args": [
                            {
                                "kind": "ctor",
                                "name": "py.fstring",
                                "args": [
                                    {"kind": "var", "name": "dt"},
                                    {
                                        "kind": "const",
                                        "sort": {
                                            "kind": "primitive",
                                            "name": "String",
                                        },
                                        "value": "1",
                                    },
                                ],
                            }
                        ],
                    },
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "itemsize",
                    },
                ],
            },
        ],
    }


def test_projected_equality_rhs_runtime_effect_stays_typed_effect() -> None:
    report = build_literal_call_report(
        source=(
            "def test_values(arr, xs):\n"
            "    assert arr.values == [x for x in xs]\n"
        ),
        filename="test_values.py",
        memento_file="test_values.py",
    )

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    effect = report.payload.effects[0]
    assert isinstance(effect.effect, RuntimeEffect)
    assert "list comprehension runtime boundary" in effect.effect.reason
    assert "runtime iterable `Name`" in effect.effect.reason
    assert [row.selected for row in report.payload.factory_walk] == [
        "ProjectedEqualityAssertionSugar"
    ]
