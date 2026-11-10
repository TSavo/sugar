"""contextlib.suppress over an ExceptionGroup body raise.

suppress.__exit__ splits the group with ExceptionGroup.split and re-raises the
residual group (https://docs.python.org/3/library/contextlib.html#contextlib.suppress,
https://docs.python.org/3/library/exceptions.html#BaseExceptionGroup.split).
"""

from __future__ import annotations

from sugar_lift_py_tests.effect import GroupedRaiseEffect, RaiseEffect
from sugar_lift_py_tests.outcome import Halted

from test_contextlib_suppress_source_exit_faces import _halts, _suppress


def test_suppress_consumes_a_group_of_only_matching_leaves(tmp_path):
    exits = _suppress(
        tmp_path,
        "ValueError",
        "raise ExceptionGroup('g', [ValueError('a'), ValueError('b')])",
    )
    assert _halts(exits) == []


def test_suppress_reraises_the_residual_group(tmp_path):
    exits = _suppress(
        tmp_path,
        "ValueError",
        "raise ExceptionGroup('g', [ValueError('a'), TypeError('b')])",
    )
    (halt,) = _halts(exits)
    assert isinstance(halt.effect, GroupedRaiseEffect)
    (leaf,) = halt.effect.children
    assert isinstance(leaf, RaiseEffect)
    assert leaf.exception_name == "TypeError"


def test_residual_keeps_the_original_group_occurrence(tmp_path):
    exits = _suppress(
        tmp_path,
        "ValueError",
        "raise ExceptionGroup('g', [ValueError('a'), TypeError('b')])",
    )
    (halt,) = _halts(exits)
    assert halt.effect.occurrence is not None
    assert halt.effect.exception_type_coordinate is not None


def test_nested_group_splits_recursively_without_flattening(tmp_path):
    exits = _suppress(
        tmp_path,
        "ValueError",
        "raise ExceptionGroup('g', [ValueError('a'),"
        " ExceptionGroup('h', [TypeError('b'), ValueError('c')])])",
    )
    (halt,) = _halts(exits)
    (inner,) = halt.effect.children
    assert isinstance(inner, GroupedRaiseEffect)
    (leaf,) = inner.children
    assert leaf.exception_name == "TypeError"


def test_a_handler_matching_the_group_class_consumes_the_whole_group(tmp_path):
    exits = _suppress(
        tmp_path,
        "Exception",
        "raise ExceptionGroup('g', [TypeError('b')])",
    )
    assert _halts(exits) == []


def test_base_exception_group_body_stays_loud(tmp_path):
    import pytest

    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic, match="builtins.ExceptionGroup"):
        _suppress(
            tmp_path,
            "ValueError",
            "raise BaseExceptionGroup('g', [TypeError('b')])",
        )
