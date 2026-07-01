from __future__ import annotations

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryGap, build_node
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.sugar.call_truth_assertion_sugar import CallTruthAssertionSugar
from sugar_lift_py_tests.sugar.identity_assertion_sugar import IdentityAssertionSugar
from sugar_lift_py_tests.sugar.not_sugar import NotSugar


def _only_assert(source: str):
    root = SourceFragment.from_source(source, "test_not.py")
    return next(frag for frag in root.walk() if frag.observed == "Assert")


def test_is_not_builds_identity_assertion_with_not_marker() -> None:
    result = build_node(
        _only_assert("def test_returns_value(ret):\n    assert ret is not None\n"),
        filename="test_not.py",
        role=SugarRole.ASSERTION,
    )

    assert result.audit_row.selected == "IdentityAssertionSugar"
    assert isinstance(result.sugar, IdentityAssertionSugar)
    assert isinstance(result.sugar.polarity, NotSugar)


def test_unary_not_builds_child_assertion_body() -> None:
    result = build_node(
        _only_assert("def test_not_truth(checks):\n    assert not checks.is_td64(1)\n"),
        filename="test_not.py",
        role=SugarRole.ASSERTION,
    )

    assert result.audit_row.selected == "NotSugar"
    assert isinstance(result.sugar, NotSugar)
    assert result.sugar.body is not None
    assert isinstance(result.sugar.body.sugar, CallTruthAssertionSugar)


def test_is_not_lifts_as_not_identity_fact() -> None:
    report = build_literal_call_report(
        source=("def test_returns_value(ret):\n" "    assert ret is not None\n"),
        filename="test_not.py",
        memento_file="test_not.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.identity-assertion-sugar"
    assert contract.inv == {
        "kind": "not",
        "operands": [
            {
                "kind": "atomic",
                "name": "identity",
                "args": [
                    {"kind": "var", "name": "ret"},
                    {"kind": "ctor", "name": "None", "args": []},
                ],
            }
        ],
    }
    assert [row.selected for row in report.payload.factory_walk] == [
        "IdentityAssertionSugar"
    ]


def test_unary_not_lifts_as_not_wrapped_child_fact() -> None:
    report = build_literal_call_report(
        source=("def test_not_truth(checks):\n" "    assert not checks.is_td64(1)\n"),
        filename="test_not.py",
        memento_file="test_not.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.not-sugar"
    assert contract.inv == {
        "kind": "not",
        "operands": [
            {
                "kind": "atomic",
                "name": "py.truthy",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "call:is_td64",
                        "args": [
                            {
                                "kind": "const",
                                "sort": {"kind": "primitive", "name": "Int"},
                                "value": 1,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    assert [row.selected for row in report.payload.factory_walk] == ["NotSugar"]


def test_is_not_leaves_unsupported_rhs_to_factory_gap() -> None:
    with pytest.raises(FactoryGap) as exc:
        build_literal_call_report(
            source=("def test_label(x, label):\n" "    assert x is not f'{label}'\n"),
            filename="test_label.py",
            memento_file="test_label.py",
        )

    assert exc.value.info["observed"] == "assert-compare-op:IsNot"
    assert exc.value.info["requested"] == "EqualityAssertion"
