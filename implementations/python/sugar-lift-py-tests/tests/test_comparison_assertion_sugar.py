from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


def _source_warrant_role(contract) -> str | None:
    warrant = contract.source_warrants[0]
    if isinstance(warrant, dict):
        return warrant.get("role")
    return warrant.role


def test_comparison_assertion_lifts_name_equality_fact() -> None:
    report = build_literal_call_report(
        source=("def test_column_sum(total):\n" "    assert total == 6\n"),
        filename="test_sum.py",
        memento_file="test_sum.py",
    )

    assert report is not None
    assert len(report.payload.ir) == 1
    contract = report.payload.ir[0]
    assert contract.name == "test_sum::test_column_sum::assert:2:4::assertion"
    assert contract.source_warrants[0].role == "python.comparison-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [
            {"kind": "var", "name": "total"},
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Int"},
                "value": 6,
            },
        ],
    }
    assert [row.selected for row in report.payload.factory_walk] == [
        "ComparisonAssertionSugar"
    ]
    assert report.payload.factory_walk[0].requested_role == "AssertionSurface"


def test_comparison_assertion_lifts_not_equal_fact() -> None:
    report = build_literal_call_report(
        source=("def test_column_sum(total):\n" "    assert total != 7\n"),
        filename="test_sum.py",
        memento_file="test_sum.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.comparison-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "≠",
        "args": [
            {"kind": "var", "name": "total"},
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Int"},
                "value": 7,
            },
        ],
    }


def test_comparison_assertion_lifts_non_eq_call_with_bytes() -> None:
    report = build_literal_call_report(
        source=(
            "def test_derive_key(alg):\n"
            '    assert alg.derive_key(b"raaaa") != b"raaaa"\n'
        ),
        filename="test_token_padding.py",
        memento_file="test_token_padding.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.comparison-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "≠",
        "args": [
            {
                "kind": "ctor",
                "name": "call:derive_key",
                "args": [
                    {"kind": "var", "name": "alg"},
                    {
                        "kind": "ctor",
                        "name": "python:bytes",
                        "args": [
                            {
                                "kind": "const",
                                "sort": {"kind": "primitive", "name": "String"},
                                "value": "7261616161",
                            }
                        ],
                    },
                ],
            },
            {
                "kind": "ctor",
                "name": "python:bytes",
                "args": [
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "7261616161",
                    }
                ],
            },
        ],
    }


def test_comparison_assertion_lifts_order_relation_fact() -> None:
    report = build_literal_call_report(
        source=("def test_count(count, limit):\n" "    assert count <= limit\n"),
        filename="test_count.py",
        memento_file="test_count.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.comparison-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "≤",
        "args": [
            {"kind": "var", "name": "count"},
            {"kind": "var", "name": "limit"},
        ],
    }


def test_comparison_assertion_lifts_order_relation_with_call_term() -> None:
    report = build_literal_call_report(
        source=(
            "def test_return_real(t, err):\n" "    assert abs(t(234) - 234.0) <= err\n"
        ),
        filename="test_return_real.py",
        memento_file="test_return_real.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.comparison-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "≤",
        "args": [
            {
                "kind": "ctor",
                "name": "call:abs",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "-",
                        "args": [
                            {
                                "kind": "ctor",
                                "name": "call:t",
                                "args": [
                                    {
                                        "kind": "const",
                                        "sort": {
                                            "kind": "primitive",
                                            "name": "Int",
                                        },
                                        "value": 234,
                                    }
                                ],
                            },
                            {
                                "kind": "const",
                                "sort": {
                                    "kind": "primitive",
                                    "name": "Real",
                                },
                                "value": "234.0",
                            },
                        ],
                    }
                ],
            },
            {"kind": "var", "name": "err"},
        ],
    }
    assert [row.selected for row in report.payload.factory_walk] == [
        "ComparisonAssertionSugar"
    ]


def test_comparison_assertion_lifts_order_relation_with_branch_bound_limit() -> None:
    report = build_literal_call_report(
        source=(
            "def test_return_real(t, tname):\n"
            "    if tname == 't0':\n"
            "        err = 1e-5\n"
            "    else:\n"
            "        err = 0.0\n"
            "    assert abs(t(234) - 234.0) <= err\n"
        ),
        filename="test_return_real.py",
        memento_file="test_return_real.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.comparison-assertion-sugar"
    assert contract.inv["name"] == "≤"
    assert contract.inv["args"][1] == {"kind": "var", "name": "err"}
    assert [row.selected for row in report.payload.factory_walk] == [
        "ComparisonAssertionSugar"
    ]


def test_comparison_assertion_lifts_order_relation_with_negative_call_argument() -> (
    None
):
    report = build_literal_call_report(
        source=(
            "def test_return_real(t, err):\n" "    assert abs(t(-234) + 234) <= err\n"
        ),
        filename="test_return_real.py",
        memento_file="test_return_real.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.comparison-assertion-sugar"
    assert contract.inv["name"] == "≤"
    assert contract.inv["args"][0]["args"][0]["args"][0]["args"] == [
        {
            "kind": "const",
            "sort": {"kind": "primitive", "name": "Int"},
            "value": -234,
        }
    ]
    assert [row.selected for row in report.payload.factory_walk] == [
        "ComparisonAssertionSugar"
    ]


def test_comparison_assertion_lifts_order_relation_with_tuple_call_argument() -> None:
    report = build_literal_call_report(
        source=(
            "def test_return_real(t, err):\n"
            "    assert abs(t((234,)) - 234.0) <= err\n"
        ),
        filename="test_return_real.py",
        memento_file="test_return_real.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.comparison-assertion-sugar"
    assert contract.inv["name"] == "≤"
    assert contract.inv["args"][0]["args"][0]["args"][0]["args"] == [
        {
            "kind": "ctor",
            "name": "tuple",
            "args": [
                {
                    "kind": "const",
                    "sort": {"kind": "primitive", "name": "Int"},
                    "value": 234,
                }
            ],
        }
    ]
    assert [row.selected for row in report.payload.factory_walk] == [
        "ComparisonAssertionSugar"
    ]


def test_comparison_assertion_does_not_steal_callsite_equality_dig() -> None:
    report = build_literal_call_report(
        source=(
            "def f(x):\n"
            "    return x\n"
            "\n"
            "def test_f():\n"
            "    assert f(1) == 1\n"
        ),
        filename="test_f.py",
        memento_file="test_f.py",
    )

    assert report is not None
    assert [row.selected for row in report.payload.factory_walk] == [
        "ReturnSugar",
        "CallSugar",
    ]
    assert report.payload.factory_walk[1].reason == "derived from callsite floor"
    assert [
        warrant["kind"]
        for warrant in report.payload.ir[1].proofir_provenance["warrants"]
    ] == ["Derived", "Stated"]
    assert all(
        _source_warrant_role(contract) != "python.comparison-assertion-sugar"
        for contract in report.payload.ir
    )


def test_comparison_assertion_does_not_treat_bound_local_as_vendor_fact() -> None:
    report = build_literal_call_report(
        source=(
            "def f(x):\n"
            "    return x\n"
            "\n"
            "def test_f():\n"
            "    y = f(5)\n"
            "    assert y == 5\n"
        ),
        filename="test_bound.py",
        memento_file="test_bound.py",
    )

    assert report is not None
    assert [row.selected for row in report.payload.factory_walk] == [
        "ReturnSugar",
        "CallSugar",
    ]
    assert report.payload.factory_walk[1].reason == "derived from callsite floor"
    assert [
        warrant["kind"]
        for warrant in report.payload.ir[1].proofir_provenance["warrants"]
    ] == ["Derived", "Stated"]
    assert all(
        _source_warrant_role(contract) != "python.comparison-assertion-sugar"
        for contract in report.payload.ir
    )


def test_bound_name_equality_emits_typed_runtime_effect() -> None:
    report = build_literal_call_report(
        source=("def test_counter():\n" "    count = 0\n" "    assert count == 0\n"),
        filename="test_counter.py",
        memento_file="test_counter.py",
    )

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    assert (
        "bound-name equality runtime boundary"
        in report.payload.effects[0].effect.reason
    )
    assert report.payload.factory_walk[0].status == "runtime-effect"


def test_callsite_expected_predicate_emits_typed_runtime_effect() -> None:
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "def test_casting(casting):\n"
            '    expected = casting == "unsafe"\n'
            '    assert np.can_cast("V4", "V4", casting=casting) == expected\n'
        ),
        filename="test_casting.py",
        memento_file="test_casting.py",
    )

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    assert (
        "callsite expected runtime boundary" in report.payload.effects[0].effect.reason
    )
    assert "PredicateValue" in report.payload.effects[0].effect.reason
    assert report.payload.factory_walk[0].status == "runtime-effect"


def test_unsupported_is_comparison_assertion_emits_typed_runtime_effect() -> None:
    report = build_literal_call_report(
        source=("def test_type(expected):\n" "    assert {1} is expected\n"),
        filename="test_type.py",
        memento_file="test_type.py",
    )

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    assert "assertion runtime boundary" in report.payload.effects[0].effect.reason
    assert "assert-compare-op:Is" in report.payload.effects[0].effect.reason
    assert report.payload.factory_walk[0].status == "runtime-effect"


def test_boolop_assertion_with_unowned_child_emits_typed_runtime_effect() -> None:
    report = build_literal_call_report(
        source=(
            "def test_body(mod):\n"
            '    assert "body" in mod and len(mod["body"]) == 9\n'
        ),
        filename="test_body.py",
        memento_file="test_body.py",
    )

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    assert "assertion runtime boundary" in report.payload.effects[0].effect.reason
    assert "BoolOpAssertionSugar" in report.payload.effects[0].effect.reason
    assert report.payload.factory_walk[0].status == "runtime-effect"


def test_not_assertion_with_unowned_child_emits_typed_runtime_effect() -> None:
    report = build_literal_call_report(
        source=("def test_mask(out, where):\n" "    assert not out[~where].any()\n"),
        filename="test_mask.py",
        memento_file="test_mask.py",
    )

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    assert "assertion runtime boundary" in report.payload.effects[0].effect.reason
    assert "NotSugar" in report.payload.effects[0].effect.reason
    assert report.payload.factory_walk[0].status == "runtime-effect"
