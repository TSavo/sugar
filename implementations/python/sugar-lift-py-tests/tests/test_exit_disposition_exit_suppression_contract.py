"""ExitSuppressionContract matches by type coordinate, never exception_name.

Sin residual after cluster-5 Suppresses fix: this arm still did
``getattr(effect, "exception_name")`` + ``suppresses_exception(name)``.
One door now mints coordinates at construction; match throws without a
coordinate on the halt.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.call_site_value import ExitSuppressionContract
from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity
from sugar_lift_py_tests.ir import atomic, ctor, str_const
from sugar_lift_py_tests.outcome.exit_disposition import exit_disposition_effect
from sugar_lift_py_tests.outcome.exit_set import Halted
from sugar_lift_py_tests.sugar.function_universe_sugar import halt_record


def _guard():
    return atomic("true", [])


def _value_error(*, coordinate=None, mro=None, name="ValueError"):
    if coordinate is None and mro is None:
        coordinate, mro = _builtin_exception_identity("ValueError")
    return RaiseEffect(
        exception_type_coordinate=coordinate,
        occurrence=AuthenticatedRaiseLocus.of("exit_suppression.py:1:0"),
        exception_name=name,
        exception_type_mro=mro,
    )


def test_truthful_contract_suppresses_matching_coordinate() -> None:
    effect = _value_error()
    verdict = exit_disposition_effect(
        ExitSuppressionContract.suppresses(("ValueError",)),
        Halted(_guard(), effect, halt_record(None)),
    )
    assert verdict is None


def test_lying_twin_same_spelling_foreign_coordinate_restores() -> None:
    truthful = _value_error()
    foreign = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("KeyError")],
    )
    lying = replace(
        truthful,
        exception_type_coordinate=foreign,
        exception_type_mro=(foreign,),
    )
    assert lying.exception_name == "ValueError"
    restored = exit_disposition_effect(
        ExitSuppressionContract.suppresses(("ValueError",)),
        Halted(_guard(), lying, halt_record(None)),
    )
    assert restored is lying


def test_missing_effect_coordinate_throws() -> None:
    # A halt with no type coordinate never reaches the contract: the one
    # door refuses it at construction (``RaiseEffect.__post_init__``), and
    # ``for_builtin`` always mints the coordinate the contract matches on.
    with pytest.raises(TypeError, match="exception_type_coordinate=None"):
        RaiseEffect(
            exception_type_coordinate=None,
            occurrence=AuthenticatedRaiseLocus.of("exit_suppression.py:2:0"),
            exception_name="ValueError",
        )
    minted = RaiseEffect.for_builtin("ValueError", occurrence="exit_suppression.py:2:0")
    identity, _mro = _builtin_exception_identity("ValueError")
    assert minted.exception_type_coordinate == identity


def test_never_suppresses_restores_even_with_coordinate() -> None:
    effect = _value_error()
    restored = exit_disposition_effect(
        ExitSuppressionContract.never_suppresses(),
        Halted(_guard(), effect, halt_record(None)),
    )
    assert restored is effect


def test_contract_door_stores_coordinates_not_names() -> None:
    contract = ExitSuppressionContract.suppresses(("ValueError",))
    identity, _ = _builtin_exception_identity("ValueError")
    assert identity in contract.exception_type_coordinates
    assert not hasattr(contract, "exception_names")
    assert not hasattr(contract, "suppresses_exception")
    assert contract.suppresses_coordinate(identity) is True


def test_suppresses_door_rejects_unknown_builtin_name() -> None:
    with pytest.raises(ValueError, match="no builtin type coordinate"):
        ExitSuppressionContract.suppresses(("NotARealExceptionType",))
