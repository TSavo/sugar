"""Loop exhaustion dispatches on authenticated StopIteration coordinate.

Truthful twin: kit-minted StopIteration type identity finishes the iterator.
Lying twin: same ``exception_name`` spelling under a foreign coordinate is not
exhaustion. Missing coordinate is SugarNotWritten — never a name fallback.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.sugar.loop_recurrence_sugar import (
    _is_authenticated_stop_iteration,
)
from sugar_source_tree.panic import SugarNotWritten


def _stop_identity():
    identity, mro = _builtin_exception_identity("StopIteration")
    return identity, mro


def test_truthful_stop_iteration_coordinate_is_exhaustion() -> None:
    identity, mro = _stop_identity()
    effect = RaiseEffect.for_builtin(
        "StopIteration",
        exception_type_mro=mro,
        occurrence="loop.py:1:0",
        producer_node_owner="project_next",
    )
    assert effect.exception_type_coordinate == identity
    assert _is_authenticated_stop_iteration(effect) is True


def test_lying_twin_same_spelling_foreign_coordinate_is_not_exhaustion() -> None:
    identity, mro = _stop_identity()
    truthful = RaiseEffect.for_builtin(
        "StopIteration",
        exception_type_mro=mro,
        occurrence="loop.py:1:0",
    )
    foreign_type = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("ValueError")],
    )
    lying = replace(
        truthful,
        exception_type_coordinate=foreign_type,
        exception_type_mro=(foreign_type,),
    )
    assert lying.exception_name == "StopIteration"
    assert lying.exception_type_coordinate != identity
    assert _is_authenticated_stop_iteration(lying) is False


def test_missing_coordinate_throws_named_not_name_fallback() -> None:
    effect = SimpleNamespace(
        exception_name="StopIteration",
        exception_type_coordinate=None,
    )
    with pytest.raises(SugarNotWritten) as caught:
        _is_authenticated_stop_iteration(effect)
    assert "exception_type_coordinate" in caught.value.observed
    assert "exception_name" in caught.value.fix
