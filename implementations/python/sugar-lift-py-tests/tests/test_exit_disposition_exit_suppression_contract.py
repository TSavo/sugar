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
from sugar_source_tree.panic import SugarNotWritten


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
        Halted(_guard(), effect, "state"),
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
        Halted(_guard(), lying, "state"),
    )
    assert restored is lying


def test_missing_effect_coordinate_throws() -> None:
    effect = RaiseEffect.for_builtin("ValueError", occurrence="exit_suppression.py:2:0")
    with pytest.raises(SugarNotWritten) as caught:
        exit_disposition_effect(
            ExitSuppressionContract.suppresses(("ValueError",)),
            Halted(_guard(), effect, "state"),
        )
    assert "exception_type_coordinate" in caught.value.observed


def test_never_suppresses_restores_even_with_coordinate() -> None:
    effect = _value_error()
    restored = exit_disposition_effect(
        ExitSuppressionContract.never_suppresses(),
        Halted(_guard(), effect, "state"),
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
