"""ClassValue.python_isinstance dispatches on type_term, not type_name spelling.

Truthful: authenticated ``python:type("tuple")`` decides False for a class object.
Lying: type_name spelling ``tuple`` with a foreign type_term must not decide False.
Missing type_term coordinate throws — never falls back to the display string.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.class_value import ClassValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_source_tree.panic import SugarNotWritten


def _class():
    return ClassValue("Exception", (), BlockValue(()))


def _type_term(name: str):
    return ctor("python:type", [str_const(name)])


def test_truthful_type_coordinate_is_true() -> None:
    outcome = _class().python_isinstance("type", _type_term("type"), "site")
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_truthful_tuple_coordinate_is_false() -> None:
    outcome = _class().python_isinstance("tuple", _type_term("tuple"), "site")
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, FalseBoolLiteralSugar)


def test_lying_twin_spelling_tuple_foreign_coordinate_throws() -> None:
    """Builtin shadowing: display says tuple, coordinate is not python:type."""
    foreign = ctor("python:shadowed_type", [str_const("tuple")])
    with pytest.raises(SugarNotWritten) as caught:
        _class().python_isinstance("tuple", foreign, "site")
    assert "python:type" in caught.value.requested
    assert "type_name" in caught.value.fix


def test_lying_twin_spelling_does_not_override_authenticated_type() -> None:
    """If coordinate says type, spelling 'tuple' must not force False."""
    outcome = _class().python_isinstance("tuple", _type_term("type"), "site")
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_missing_type_term_throws() -> None:
    with pytest.raises(SugarNotWritten) as caught:
        _class().python_isinstance("tuple", None, "site")
    assert (
        "type_term" in caught.value.observed or "python:type" in caught.value.requested
    )
