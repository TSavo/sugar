"""Tuple classinfo at the shared Try/With exception-matching boundary.

Vendor law: Python isinstance/issubclass accepts any classinfo tuple member;
pytest RaisesExc uses isinstance(exception, self.expected_exceptions).
No tuple-shaped adt.is_python_type atom is needed to rediscover this law.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.authenticated_exception_matching import (
    MatchDecided,
    MatchRetained,
    matches_raise_effect,
    raise_effect_message_verdict,
)
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus
from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
    AuthenticatedExceptionTypeValue,
)
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.tuple_value import TupleValue
from sugar_lift_py_tests.ir import ctor, str_const, make_var, atomic, or_


def _identity(name):
    return ctor(
        "python:exception_type_identity", [str_const("builtins"), str_const(name)]
    )


def _expected(*names):
    return TupleValue(
        tuple(
            AuthenticatedExceptionTypeValue(TermValue(name), _identity(name))
            for name in names
        )
    )


def _raised(name="ValueError", *, ancestors=()):
    return RaiseEffect(
        occurrence=AuthenticatedRaiseLocus.of("tuple-classinfo.py:1:0"),
        exception_name=name,
        exception_type_coordinate=_identity(name),
        exception_type_mro=tuple(_identity(n) for n in (name, *ancestors)),
        raised_value=CallSiteValue(
            name, (StringValue("needle"),), ("message",), ctor("call", []), None
        ),
        blame="tuple-classinfo:raise",
    )


@pytest.mark.parametrize(
    ("raised", "types", "answer"),
    [
        ("ValueError", ("ValueError", "TypeError"), True),
        ("TypeError", ("ValueError", "TypeError"), True),
        ("KeyError", ("ValueError", "TypeError"), False),
        ("ValueError", (), False),
    ],
)
def test_tuple_classinfo_decides_ground_members(raised, types, answer):
    assert matches_raise_effect(_raised(raised), _expected(*types)) == MatchDecided(
        answer
    )


def test_tuple_classinfo_accepts_authenticated_ancestor():
    effect = _raised("UnicodeError", ancestors=("ValueError", "Exception"))
    assert matches_raise_effect(
        effect, _expected("TypeError", "ValueError")
    ) == MatchDecided(True)


def test_tuple_classinfo_retains_unknown_members_as_disjunction():
    effect = _raised()
    x, y = make_var("x"), make_var("y")
    expected = TupleValue(
        (SymbolicValue(x), SymbolicValue(y), *_expected("KeyError").elements)
    )
    verdict = matches_raise_effect(effect, expected)
    assert verdict == MatchRetained(
        or_(
            [
                atomic("adt.is_python_type", [_identity("ValueError"), x]),
                atomic("adt.is_python_type", [_identity("ValueError"), y]),
            ]
        )
    )


def test_tuple_classinfo_known_match_discharges_unknown_disjunct():
    expected = TupleValue(
        (SymbolicValue(make_var("unknown")), *_expected("ValueError").elements)
    )
    assert matches_raise_effect(_raised(), expected) == MatchDecided(True)


@pytest.mark.parametrize(("pattern", "answer"), [("needle", True), ("other", False)])
def test_tuple_classinfo_does_not_drop_message_predicate(pattern, answer):
    assert raise_effect_message_verdict(
        _raised(), _expected("TypeError", "ValueError"), StringValue(pattern)
    ) == MatchDecided(answer)
