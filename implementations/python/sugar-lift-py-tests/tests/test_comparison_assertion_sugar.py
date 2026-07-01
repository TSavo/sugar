from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


def test_comparison_assertion_lifts_name_equality_fact() -> None:
    report = build_literal_call_report(
        source=(
            "def test_column_sum(total):\n"
            "    assert total == 6\n"
        ),
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
        source=(
            "def test_column_sum(total):\n"
            "    assert total != 7\n"
        ),
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


def test_comparison_assertion_lifts_order_relation_fact() -> None:
    report = build_literal_call_report(
        source=(
            "def test_count(count, limit):\n"
            "    assert count <= limit\n"
        ),
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
        "CallSugar",
    ]
    assert all(
        contract.source_warrants[0].role != "python.comparison-assertion-sugar"
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
        "CallSugar",
    ]
    assert all(
        contract.source_warrants[0].role != "python.comparison-assertion-sugar"
        for contract in report.payload.ir
    )
