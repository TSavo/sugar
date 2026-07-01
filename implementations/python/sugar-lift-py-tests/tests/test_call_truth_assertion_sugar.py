from __future__ import annotations

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
    assert (
        contract.name
        == "test_exception::test_exception_subclass::assert:2:4::assertion"
    )
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


def test_call_truth_assertion_emits_external_bridge_edge_for_import_without_source() -> (
    None
):
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


def test_call_truth_assertion_lifts_binop_call_argument() -> None:
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "def test_w(k, w):\n"
            "    assert np.allclose(k, w + 1)\n"
        ),
        filename="test_crackfortran.py",
        memento_file="test_crackfortran.py",
    )

    assert report is not None
    assert _call_term(report) == {
        "kind": "ctor",
        "name": "call:numpy.allclose",
        "args": [
            {"kind": "var", "name": "k"},
            {
                "kind": "ctor",
                "name": "+",
                "args": [
                    {"kind": "var", "name": "w"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 1,
                    },
                ],
            },
        ],
    }


def test_call_truth_assertion_lifts_fstring_call_argument() -> None:
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "def test_can_cast(floating, string):\n"
            "    assert np.can_cast(floating, f'{string}100')\n"
        ),
        filename="test_casting_unittests.py",
        memento_file="test_casting_unittests.py",
    )

    assert report is not None
    assert _call_term(report) == {
        "kind": "ctor",
        "name": "call:numpy.can_cast",
        "args": [
            {"kind": "var", "name": "floating"},
            {
                "kind": "ctor",
                "name": "py.fstring",
                "args": [
                    {"kind": "var", "name": "string"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "100",
                    },
                ],
            },
        ],
    }


def test_call_truth_assertion_lifts_method_receiver_call() -> None:
    report = build_literal_call_report(
        source=(
            "def test_message(exc, name):\n"
            "    assert exc.args[0].startswith(f'{name}()')\n"
        ),
        filename="test_overrides.py",
        memento_file="test_overrides.py",
    )

    assert report is not None
    assert _call_term(report) == {
        "kind": "ctor",
        "name": "call:startswith",
        "args": [
            {
                "kind": "ctor",
                "name": "py.subscript",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "py.attr",
                        "args": [
                            {"kind": "var", "name": "exc"},
                            {
                                "kind": "const",
                                "sort": {"kind": "primitive", "name": "String"},
                                "value": "args",
                            },
                        ],
                    },
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 0,
                    },
                ],
            },
            {
                "kind": "ctor",
                "name": "py.fstring",
                "args": [
                    {"kind": "var", "name": "name"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "()",
                    },
                ],
            },
        ],
    }


def test_call_truth_assertion_lifts_call_receiver_method() -> None:
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "def test_out(out):\n"
            "    assert np.isnan(out).all()\n"
        ),
        filename="test_nanfunctions.py",
        memento_file="test_nanfunctions.py",
    )

    assert report is not None
    assert _call_term(report) == {
        "kind": "ctor",
        "name": "call:all",
        "args": [
            {
                "kind": "ctor",
                "name": "call:numpy.isnan",
                "args": [{"kind": "var", "name": "out"}],
            }
        ],
    }


def test_call_truth_assertion_lifts_compare_call_argument() -> None:
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "def test_shape(a):\n"
            "    assert np.all(a == [[2, 2, 2], [1, 1, 1]])\n"
        ),
        filename="test_shape_base.py",
        memento_file="test_shape_base.py",
    )

    assert report is not None
    assert _call_term(report) == {
        "kind": "ctor",
        "name": "call:numpy.all",
        "args": [
            {
                "kind": "ctor",
                "name": "py.compare:Eq",
                "args": [
                    {"kind": "var", "name": "a"},
                    {
                        "kind": "ctor",
                        "name": "array",
                        "args": [
                            {
                                "kind": "ctor",
                                "name": "array",
                                "args": [
                                    {
                                        "kind": "const",
                                        "sort": {
                                            "kind": "primitive",
                                            "name": "Int",
                                        },
                                        "value": 2,
                                    },
                                    {
                                        "kind": "const",
                                        "sort": {
                                            "kind": "primitive",
                                            "name": "Int",
                                        },
                                        "value": 2,
                                    },
                                    {
                                        "kind": "const",
                                        "sort": {
                                            "kind": "primitive",
                                            "name": "Int",
                                        },
                                        "value": 2,
                                    },
                                ],
                            },
                            {
                                "kind": "ctor",
                                "name": "array",
                                "args": [
                                    {
                                        "kind": "const",
                                        "sort": {
                                            "kind": "primitive",
                                            "name": "Int",
                                        },
                                        "value": 1,
                                    },
                                    {
                                        "kind": "const",
                                        "sort": {
                                            "kind": "primitive",
                                            "name": "Int",
                                        },
                                        "value": 1,
                                    },
                                    {
                                        "kind": "const",
                                        "sort": {
                                            "kind": "primitive",
                                            "name": "Int",
                                        },
                                        "value": 1,
                                    },
                                ],
                            },
                        ],
                    },
                ],
            }
        ],
    }


def test_call_truth_assertion_lifts_generator_method_predicate() -> None:
    report = build_literal_call_report(
        source=(
            "def test_indices(output_indices1):\n"
            "    assert all(c.isupper() for c in output_indices1)\n"
        ),
        filename="test_indices.py",
        memento_file="test_indices.py",
    )

    assert report is not None
    assert _call_term(report) == {
        "kind": "ctor",
        "name": "call:all",
        "args": [
            {
                "kind": "ctor",
                "name": "py.generator",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "call:isupper",
                        "args": [{"kind": "var", "name": "c"}],
                    },
                    {
                        "kind": "ctor",
                        "name": "py.comprehension",
                        "args": [
                            {"kind": "var", "name": "c"},
                            {"kind": "var", "name": "output_indices1"},
                        ],
                    },
                ],
            }
        ],
    }


def test_call_truth_assertion_lifts_generator_identity_predicate() -> None:
    report = build_literal_call_report(
        source=(
            "def test_results(results, val1):\n"
            "    assert all(r is val1 for r in results)\n"
        ),
        filename="test_hashtable.py",
        memento_file="test_hashtable.py",
    )

    assert report is not None
    assert _call_term(report) == {
        "kind": "ctor",
        "name": "call:all",
        "args": [
            {
                "kind": "ctor",
                "name": "py.generator",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "py.compare:Is",
                        "args": [
                            {"kind": "var", "name": "r"},
                            {"kind": "var", "name": "val1"},
                        ],
                    },
                    {
                        "kind": "ctor",
                        "name": "py.comprehension",
                        "args": [
                            {"kind": "var", "name": "r"},
                            {"kind": "var", "name": "results"},
                        ],
                    },
                ],
            }
        ],
    }


def test_call_truth_assertion_lifts_generator_membership_predicate() -> None:
    report = build_literal_call_report(
        source=(
            "def test_config(self, config):\n"
            "    assert all(key in config for key in self.REQUIRED_CONFIG_KEYS)\n"
        ),
        filename="test_numpy_config.py",
        memento_file="test_numpy_config.py",
    )

    assert report is not None
    assert _call_term(report) == {
        "kind": "ctor",
        "name": "call:all",
        "args": [
            {
                "kind": "ctor",
                "name": "py.generator",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "py.compare:In",
                        "args": [
                            {"kind": "var", "name": "key"},
                            {"kind": "var", "name": "config"},
                        ],
                    },
                    {
                        "kind": "ctor",
                        "name": "py.comprehension",
                        "args": [
                            {"kind": "var", "name": "key"},
                            {
                                "kind": "ctor",
                                "name": "py.attr",
                                "args": [
                                    {"kind": "var", "name": "self"},
                                    {
                                        "kind": "const",
                                        "sort": {
                                            "kind": "primitive",
                                            "name": "String",
                                        },
                                        "value": "REQUIRED_CONFIG_KEYS",
                                    },
                                ],
                            },
                        ],
                    },
                ],
            }
        ],
    }


def _call_term(report):
    return report.payload.ir[0].inv["args"][0]
