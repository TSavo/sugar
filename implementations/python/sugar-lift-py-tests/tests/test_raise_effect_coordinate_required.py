"""Constructor law: RaiseEffect refuses nameless authenticated exits.

Shell deleted: presence-only ``assert effect.exception_type_coordinate is not None``
teeth on successful RaiseEffect paths — the type carries the law now.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import (
    RaiseEffect,
    UndeterminedRaiseEffect,
)


def test_raise_effect_refuses_none_coordinate() -> None:
    with pytest.raises(TypeError, match="refuses exception_type_coordinate=None"):
        RaiseEffect(exception_type_coordinate=None, occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_raise_effect_coordinate_required.py:19:0'))  # type: ignore[arg-type]


def test_raise_effect_requires_coordinate_argument() -> None:
    with pytest.raises(TypeError):
        RaiseEffect(occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_raise_effect_coordinate_required.py:24:0'), exception_name='ValueError')  # type: ignore[call-arg]


def test_for_builtin_mints_authenticated_coordinate() -> None:
    effect = RaiseEffect.for_builtin('ValueError', blame='t.py:1:0', occurrence='t.py:1:0')
    assert effect.exception_name == "ValueError"
    assert effect.exception_type_coordinate is not None
    assert effect.exception_type_mro is not None


def test_undetermined_cannot_impersonate_raise_effect() -> None:
    undetermined = UndeterminedRaiseEffect(blame="t.py:1:0")
    assert undetermined.exception_type_coordinate is None
    assert not isinstance(undetermined, RaiseEffect)
    assert type(undetermined) is UndeterminedRaiseEffect


def test_for_builtin_unknown_name_throws() -> None:
    with pytest.raises(TypeError, match="no language-owned"):
        RaiseEffect.for_builtin('NotARealExceptionType123', occurrence='implementations/python/sugar-lift-py-tests/tests/test_raise_effect_coordinate_required.py:43:0')
