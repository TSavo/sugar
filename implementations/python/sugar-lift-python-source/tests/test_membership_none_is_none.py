"""``None`` is its own member: ``None in [None]`` is True.

``member_equal`` compared two ``NoneValue``\\s as two decided builtin values of
different kinds and answered False, so ``None in ['a', None]`` lifted as
False and numpy's ``_make_options_dict`` (``if floatmode not in modes +
[None]: raise ValueError``) raised on every call with the default
``floatmode=None``.  ``None`` is a singleton, so CPython's ``is``-or-``==``
lookup matches it by identity.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

from test_builtin_container_mutation import _only_return


def _value(tmp_path, expression):
    return _only_return(tmp_path, f"def f(x):\n    return {expression}\n")


@pytest.mark.parametrize(
    "expression",
    [
        "None in [None]",
        "None in ['a', None]",
        "None in ('a', None)",
        "None in {None}",
        "None in {None: 1}",
        "None not in ['a']",
        "(1, None) in [(1, None)]",
    ],
)
def test_none_matches_none(tmp_path, expression):
    assert type(_value(tmp_path, expression)) is TrueBoolLiteralSugar


@pytest.mark.parametrize("expression", ["None not in [None]", "None in ['a', 0]"])
def test_none_is_absent_only_where_no_member_is_none(tmp_path, expression):
    assert type(_value(tmp_path, expression)) is FalseBoolLiteralSugar


def test_a_default_none_passes_a_none_admitting_guard(tmp_path):
    from test_undetermined_raise_except_matching import _exits
    from sugar_lift_py_tests.outcome import Halted

    exits = _exits(
        tmp_path,
        "def h(floatmode=None):\n"
        "    modes = ['fixed', 'unique']\n"
        "    if floatmode not in modes + [None]:\n"
        "        raise ValueError('x')\n"
        "    return 1\n"
        "def f():\n    return h()\n",
    )
    assert not any(isinstance(face, Halted) for face in exits.exits)
