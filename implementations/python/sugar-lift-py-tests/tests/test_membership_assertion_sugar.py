from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


TRUE_CONST = {
    "kind": "const",
    "sort": {"kind": "primitive", "name": "Bool"},
    "value": True,
}


def test_membership_assertion_uses_string_floor_contains() -> None:
    report = build_literal_call_report(
        source=(
            "def test_string_membership():\n"
            "    assert 'mp' in 'numpy'\n"
        ),
        filename="test_contains.py",
        memento_file="test_contains.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.membership-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [TRUE_CONST, TRUE_CONST],
    }
    assert [row.selected for row in report.payload.factory_walk] == [
        "MembershipAssertionSugar"
    ]


def test_membership_assertion_uses_array_floor_contains() -> None:
    report = build_literal_call_report(
        source=(
            "def test_array_membership():\n"
            "    assert 2 in [1, 2, 3]\n"
        ),
        filename="test_contains.py",
        memento_file="test_contains.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [TRUE_CONST, TRUE_CONST],
    }


def test_membership_assertion_negates_not_in_after_floor_contains() -> None:
    report = build_literal_call_report(
        source=(
            "def test_not_in():\n"
            "    assert 9 not in [1, 2, 3]\n"
        ),
        filename="test_contains.py",
        memento_file="test_contains.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [TRUE_CONST, TRUE_CONST],
    }


def test_membership_assertion_projects_constructor_bound_string_field() -> None:
    report = build_literal_call_report(
        source=(
            "class Record:\n"
            "    def __init__(self):\n"
            "        self.filename = 'test_random.py'\n"
            "\n"
            "def test_constructor_field_membership():\n"
            "    rec = Record()\n"
            "    assert 'test_random' in rec.filename\n"
        ),
        filename="test_record.py",
        memento_file="test_record.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.membership-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [TRUE_CONST, TRUE_CONST],
    }


def test_membership_assertion_preserves_constructor_argument_gap() -> None:
    with pytest.raises(FactoryGap) as exc:
        build_literal_call_report(
            source=(
                "class Record:\n"
                "    def __init__(self, filename):\n"
                "        self.filename = filename\n"
                "\n"
                "def test_constructor_field_membership():\n"
                "    rec = Record('test_random.py')\n"
                "    assert 'test_random' in rec.filename\n"
            ),
            filename="test_record.py",
            memento_file="test_record.py",
        )

    assert exc.value.info["requested"] == "zero-arg constructor"
    assert "constructor argument binding sugar" in exc.value.info["fix"]


def test_membership_assertion_ignores_unused_prior_assignment() -> None:
    report = build_literal_call_report(
        source=(
            "def test_unused_setup_membership():\n"
            "    scratch = {}\n"
            "    assert 'mp' in 'numpy'\n"
        ),
        filename="test_contains.py",
        memento_file="test_contains.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "=",
        "args": [TRUE_CONST, TRUE_CONST],
    }


def test_membership_assertion_panics_when_receiver_floor_cannot_contains() -> None:
    with pytest.raises(FactoryGap) as exc:
        build_literal_call_report(
            source=(
                "def test_bad_membership():\n"
                "    assert 1 in 3\n"
            ),
            filename="test_contains.py",
            memento_file="test_contains.py",
        )

    assert exc.value.info["observed"] == "TermValue"
    assert exc.value.info["requested"] == "contains_with"
