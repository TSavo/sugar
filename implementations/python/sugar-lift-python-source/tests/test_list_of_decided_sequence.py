"""``list(xs)`` over a decided sequence is a list of exactly those members.

The builtin ``list`` builds a new list of its iterable's members in
iteration order, and never raises for a decided tuple, list, dict, or finite
comprehension (``builtin_call_total`` already says so).  The call used to
complete as an opaque ``list(...)`` coordinate, so ``len(list((1, 2))) == 2``
stayed an UndecidedCompare, and a comprehension over ``list(d.items())``
could not see its members.  A set's order depends on hashing, so it is not
decided, and neither is an unknown operand; a rebound ``list`` is not the
builtin.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
from sugar_lift_py_tests.outcome.exit_set import Halted

from test_undetermined_raise_except_matching import _exits


def _returns(tmp_path, source):
    exits = _exits(tmp_path, source).exits
    return sorted(
        entry.value.value
        for face in exits
        if not isinstance(face, Halted)
        for entry in face.value.record.statements
        if isinstance(entry, GuardedReturn)
    ), exits


@pytest.mark.parametrize(
    "operand", ["(1, 2)", "[1, 2]", "{'a': 1, 'b': 2}", "{'a': 1, 'b': 2}.items()"]
)
def test_the_new_list_has_the_members(tmp_path, operand):
    returned, exits = _returns(
        tmp_path,
        f"def f():\n    o = list({operand})\n    if len(o) == 2:\n        return 7\n"
        "    return 8\n",
    )
    assert returned == [7]
    assert not any(isinstance(face, Halted) for face in exits)


def test_dict_keys_keep_insertion_order(tmp_path):
    returned, _ = _returns(
        tmp_path,
        "def f():\n    o = list({'b': 1, 'a': 2})\n    if o[0] == 'b':\n"
        "        return 7\n    return 8\n",
    )
    assert returned == [7]


def test_a_rebound_list_is_not_the_builtin(tmp_path):
    returned, _ = _returns(
        tmp_path,
        "def list(x):\n    return x\n"
        "def f():\n    o = list((1, 2))\n    if len(o) == 2:\n        return 7\n"
        "    return 8\n",
    )
    assert returned == [7]
