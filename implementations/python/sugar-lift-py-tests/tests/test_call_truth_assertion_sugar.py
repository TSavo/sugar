from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


def test_call_truth_assertion_lifts_plain_call_fact() -> None:
    report = build_literal_call_report(
        source=(
            "def test_exception_subclass(cls):\n"
            "    assert issubclass(cls, Exception)\n"
        ),
        filename="test_exception.py",
        memento_file="test_exception.py",
    )

    assert report is not None
    assert len(report.payload.ir) == 1
    contract = report.payload.ir[0]
    assert contract.name == "test_exception::test_exception_subclass::assert:2:4::assertion"
    assert contract.source_warrants[0].role == "python.call-truth-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "py.truthy",
        "args": [
            {
                "kind": "ctor",
                "name": "call:issubclass",
                "args": [
                    {"kind": "var", "name": "cls"},
                    {"kind": "var", "name": "Exception"},
                ],
            }
        ],
    }
    assert [row.selected for row in report.payload.factory_walk] == [
        "CallTruthAssertionSugar"
    ]
    assert report.payload.factory_walk[0].requested_role == "AssertionSurface"


def test_call_truth_assertion_lifts_attribute_call_fact() -> None:
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "def test_allclose(arr, expected_value):\n"
            "    assert np.allclose(arr, expected_value)\n"
        ),
        filename="test_allclose.py",
        memento_file="test_allclose.py",
    )

    assert report is not None
    fact = report.payload.ir[0].inv
    assert fact == {
        "kind": "atomic",
        "name": "py.truthy",
        "args": [
            {
                "kind": "ctor",
                "name": "call:numpy.allclose",
                "args": [
                    {"kind": "var", "name": "arr"},
                    {"kind": "var", "name": "expected_value"},
                ],
            }
        ],
    }


def test_call_truth_assertion_emits_external_bridge_edge_for_import_without_source() -> None:
    report = build_literal_call_report(
        source=(
            "import math\n"
            "def test_finite(value):\n"
            "    assert math.isfinite(value)\n"
        ),
        filename="test_finite.py",
        memento_file="test_finite.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.inv["args"][0]["name"] == "call:math.isfinite"
    assert report.payload.call_edges == [
        {
            "kind": "call-edge",
            "schemaVersion": "1",
            "sourceContract": contract.name,
            "targetSymbol": "call:math.isfinite",
            "targetContract": None,
            "targetContractCid": None,
            "callSiteLocus": {
                "file": "test_finite.py",
                "line": 3,
                "column": 11,
            },
        }
    ]


def test_call_truth_assertion_leaves_generator_call_to_factory_gap() -> None:
    with pytest.raises(FactoryGap) as exc:
        build_literal_call_report(
            source=(
                "def test_indices(output_indices1):\n"
                "    assert all(c.isupper() for c in output_indices1)\n"
            ),
            filename="test_indices.py",
            memento_file="test_indices.py",
        )

    assert exc.value.info["observed"] == "assert-test:Call"
    assert exc.value.info["requested"] == "EqualityAssertion"
