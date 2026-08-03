"""Suppresses arm matches by exception_type_coordinate, never name equality.

The old arm compared ``name == matcher.name`` with no None-guard: a
coordinate-authenticated but name-less effect equaled a name-less matcher and
was suppressed. ExitSuppressionContract shares the same coordinate door
(see test_exit_disposition_exit_suppression_contract).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_py_tests.context_manager_contract import EffectMatcher, Suppresses
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity
from sugar_lift_py_tests.ir import atomic, ctor, str_const
from sugar_lift_py_tests.outcome.exit_disposition import exit_disposition_effect
from sugar_lift_py_tests.outcome.exit_set import Halted
from sugar_source_tree.panic import SugarNotWritten


def _guard():
    return atomic("true", [])


def _key_error(*, coordinate=None, mro=None, name="KeyError"):
    if coordinate is None and mro is None:
        coordinate, mro = _builtin_exception_identity("KeyError")
    return RaiseEffect(
        exception_type_coordinate=coordinate,
        occurrence=AuthenticatedRaiseLocus.of("suppress.py:1:0"),
        exception_name=name,
        exception_type_mro=mro,
    )


def test_truthful_suppresses_matching_coordinate() -> None:
    effect = _key_error()
    verdict = exit_disposition_effect(
        Suppresses(EffectMatcher(kind="raise", name="KeyError")),
        Halted(_guard(), effect, "state"),
    )
    assert verdict is None  # consumed


def test_lying_twin_same_spelling_foreign_coordinate_restores() -> None:
    truthful = _key_error()
    foreign = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("ValueError")],
    )
    lying = replace(
        truthful,
        exception_type_coordinate=foreign,
        exception_type_mro=(foreign,),
    )
    assert lying.exception_name == "KeyError"
    restored = exit_disposition_effect(
        Suppresses(EffectMatcher(kind="raise", name="KeyError")),
        Halted(_guard(), lying, "state"),
    )
    assert restored is lying


def test_name_less_matcher_throws_not_suppress() -> None:
    effect = _key_error()
    with pytest.raises(SugarNotWritten) as caught:
        exit_disposition_effect(
            Suppresses(EffectMatcher(kind="raise", name=None)),  # type: ignore[arg-type]
            Halted(_guard(), effect, "state"),
        )
    assert "name-less" in caught.value.observed


def test_name_less_effect_with_coordinate_does_not_equal_name_less_matcher() -> None:
    """THE historical bug: None == None suppressed a coordinate-authenticated halt."""
    coordinate, mro = _builtin_exception_identity("KeyError")
    effect = RaiseEffect(
        exception_type_coordinate=coordinate,
        occurrence=AuthenticatedRaiseLocus.of("suppress.py:2:0"),
        exception_name=None,
        exception_type_mro=mro,
    )
    with pytest.raises(SugarNotWritten):
        exit_disposition_effect(
            Suppresses(EffectMatcher(kind="raise", name=None)),  # type: ignore[arg-type]
            Halted(_guard(), effect, "state"),
        )


def test_missing_effect_coordinate_throws() -> None:
    effect = RaiseEffect.for_builtin("KeyError", occurrence="suppress.py:3:0")
    with pytest.raises(SugarNotWritten) as caught:
        exit_disposition_effect(
            Suppresses(EffectMatcher(kind="raise", name="KeyError")),
            Halted(_guard(), effect, "state"),
        )
    assert "exception_type_coordinate" in caught.value.observed
