"""``None == x`` is False for every decided builtin value but ``None``.

``NoneType`` has no ``__eq__`` of its own, and no builtin ``__eq__`` answers
``None``, so CPython falls back to identity: ``None == False``, ``None == b''``
and ``None == {}`` are all False, from either side.  ``None == False`` used to
stay undecided, so numpy's ``_make_options_dict`` (``elif legacy == False:
warnings.warn(...)``) reached the warning under the default ``legacy=None``.
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
        "None == False",
        "None == True",
        "False == None",
        "True == None",
        "None == b''",
        "None == {}",
        "{} == None",
        "None == 0",
        "None == ''",
    ],
)
def test_none_equals_no_other_decided_builtin(tmp_path, expression):
    assert type(_value(tmp_path, expression)) is FalseBoolLiteralSugar


@pytest.mark.parametrize("expression", ["None != False", "False != None"])
def test_none_differs_from_every_other_decided_builtin(tmp_path, expression):
    assert type(_value(tmp_path, expression)) is TrueBoolLiteralSugar


def test_a_default_none_is_not_equal_to_false(tmp_path):
    from sugar_lift_py_tests.outcome import Halted

    from test_undetermined_raise_except_matching import _exits

    exits = _exits(
        tmp_path,
        "def h(legacy=None):\n    if legacy == False:\n        raise ValueError('x')\n"
        "    return 1\ndef f():\n    return h()\n",
    )
    assert not any(isinstance(face, Halted) for face in exits.exits)
