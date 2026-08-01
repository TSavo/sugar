"""Constructor law: RaiseEffect refuses nameless authenticated exits.

Shell deleted: presence-only ``assert effect.exception_type_coordinate is not None``
(and mro presence) teeth — the type / for_builtin door carry the law; pin identity.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus
from sugar_lift_py_tests.effect.raise_effect import (
    RaiseEffect,
    UndeterminedRaiseEffect,
)


def test_raise_effect_refuses_none_coordinate() -> None:
    with pytest.raises(TypeError, match="refuses exception_type_coordinate=None"):
        RaiseEffect(  # type: ignore[arg-type]
            exception_type_coordinate=None,
            occurrence=AuthenticatedRaiseLocus.of(
                "implementations/python/sugar-lift-py-tests/tests/"
                "test_raise_effect_coordinate_required.py:refuses_none"
            ),
        )


def test_raise_effect_requires_coordinate_argument() -> None:
    with pytest.raises(TypeError):
        RaiseEffect(  # type: ignore[call-arg]
            occurrence=AuthenticatedRaiseLocus.of(
                "implementations/python/sugar-lift-py-tests/tests/"
                "test_raise_effect_coordinate_required.py:requires_coord"
            ),
            exception_name="ValueError",
        )


def test_for_builtin_mints_authenticated_coordinate() -> None:
    """Value pin — not presence. Constructor already forbids None coordinate."""
    from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity

    expected_coord, expected_mro = _builtin_exception_identity("ValueError")
    effect = RaiseEffect.for_builtin(
        "ValueError", blame="t.py:1:0", occurrence="t.py:1:0"
    )
    assert effect.exception_name == "ValueError"
    assert effect.exception_type_coordinate == expected_coord
    # for_builtin one door always mints MRO with the type coordinate; pin it.
    assert effect.exception_type_mro == expected_mro
    assert effect.occurrence.value == "t.py:1:0"


def test_undetermined_cannot_impersonate_raise_effect() -> None:
    undetermined = UndeterminedRaiseEffect(blame="t.py:1:0")
    assert undetermined.exception_type_coordinate is None
    assert not isinstance(undetermined, RaiseEffect)
    assert type(undetermined) is UndeterminedRaiseEffect


def test_for_builtin_unknown_name_throws() -> None:
    with pytest.raises(TypeError, match="no language-owned"):
        RaiseEffect.for_builtin(
            "NotARealExceptionType123",
            occurrence=(
                "implementations/python/sugar-lift-py-tests/tests/"
                "test_raise_effect_coordinate_required.py:unknown"
            ),
        )
