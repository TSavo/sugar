from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


def test_identity_assertion_lifts_none_singleton_fact() -> None:
    report = build_literal_call_report(
        source=("def test_returns_none(ret):\n" "    assert ret is None\n"),
        filename="test_none.py",
        memento_file="test_none.py",
    )

    assert report is not None
    assert len(report.payload.ir) == 1
    contract = report.payload.ir[0]
    assert contract.name == "test_none::test_returns_none::assert:2:4::assertion"
    assert contract.source_warrants[0].role == "python.identity-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "identity",
        "args": [
            {"kind": "var", "name": "ret"},
            {"kind": "ctor", "name": "None", "args": []},
        ],
    }
    assert [row.selected for row in report.payload.factory_walk] == [
        "IdentityAssertionSugar"
    ]
    assert report.payload.factory_walk[0].requested_role == "AssertionSurface"


def test_identity_assertion_lifts_subscript_boolean_fact() -> None:
    report = build_literal_call_report(
        source=(
            "def test_caps(caps):\n" '    assert caps["boolean indexing"] is True\n'
        ),
        filename="test_caps.py",
        memento_file="test_caps.py",
    )

    assert report is not None
    fact = report.payload.ir[0].inv
    assert fact == {
        "kind": "atomic",
        "name": "identity",
        "args": [
            {
                "kind": "ctor",
                "name": "py.subscript",
                "args": [
                    {"kind": "var", "name": "caps"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "boolean indexing",
                    },
                ],
            },
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Bool"},
                "value": True,
            },
        ],
    }


def test_identity_assertion_lifts_call_to_call_fact() -> None:
    report = build_literal_call_report(
        source=(
            "def test_exception_type(exc, exc2):\n"
            "    assert type(exc) is type(exc2)\n"
        ),
        filename="test_exception.py",
        memento_file="test_exception.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "identity",
        "args": [
            {
                "kind": "ctor",
                "name": "call:type",
                "args": [{"kind": "var", "name": "exc"}],
            },
            {
                "kind": "ctor",
                "name": "call:type",
                "args": [{"kind": "var", "name": "exc2"}],
            },
        ],
    }


def test_identity_assertion_leaves_unsupported_rhs_to_factory_gap() -> None:
    with pytest.raises(FactoryGap) as exc:
        build_literal_call_report(
            source=("def test_label(x, label):\n" "    assert x is f'{label}'\n"),
            filename="test_label.py",
            memento_file="test_label.py",
        )

    assert exc.value.info["observed"] == "assert-compare-op:Is"
    assert exc.value.info["requested"] == "EqualityAssertion"
