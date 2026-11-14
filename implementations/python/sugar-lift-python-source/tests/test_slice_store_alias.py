"""A slice store or delete changes the list, seen through every alias.

``r = [1, 2, 3]; r[1:] = [9]; return r`` lifted as ``[1, 2, 3]``, and so did
``del r[:1]``: a subscript store or delete whose key is a slice was left out of
the #7603 mutation (only plain keys were threaded), so the list stayed as it
was -- a false claim.

``r[lo:hi:st] = it`` and ``del r[lo:hi:st]`` are now ``list.__setitem__``/
``list.__delitem__`` with the slice as the key, through the same alias-visible
path as ``r[k] = v``: CPython's semantics over ground bounds (extended-slice
length mismatch is ``ValueError``, a non-iterable RHS is ``TypeError``, the RHS
is materialized before the write so ``r[1:] = r`` reads the old list). Bounds
the lift does not decide leave the list unknown after the store; a decided
non-index bound (``r[1:"a"]``) is ``TypeError`` and a zero step ``ValueError``. An iterable
RHS whose members are not testified (a generator, an iterator) is an undecided
store -- never ``TypeError``.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import ListValue, StringValue, TermValue

from frame_fresh import fresh
from test_builtin_container_mutation import _halt_names, _only_return, _returns


def _list(*values):
    return fresh(
        ListValue,
        tuple(StringValue(v) if isinstance(v, str) else TermValue(v) for v in values),
    )


def _run(tmp_path, body, sig=""):
    return f"def f({sig}):\n    r = [1, 2, 3]\n    {body}\n    return r\n"


@pytest.mark.parametrize(
    "body, expected",
    [
        ("r[1:] = [9]", (1, 9)),
        ("del r[:1]", (2, 3)),
        ("r[::2] = [7, 8]", (7, 2, 8)),
        ("del r[::2]", (2,)),
        ("r[1:] = r", (1, 1, 2, 3)),
        ("r[5:] = [4]", (1, 2, 3, 4)),
        ("r[-1:] = []", (1, 2)),
        ("r[0:0] = 'ab'", ("a", "b", 1, 2, 3)),
        ("a = r\n    r[1:] = [9]\n    r = a", (1, 9)),
        ("a = r\n    del r[1:]\n    r = a", (1,)),
        ("r[::-1] = [4, 5, 6]", (6, 5, 4)),
        ("del r[::-1]", ()),
        ("r[None:1] = [9]", (9, 2, 3)),
        ("del r[:None]", ()),
    ],
)
def test_a_slice_store_or_delete_changes_the_list(tmp_path, body, expected):
    assert _only_return(tmp_path, _run(tmp_path, body)) == _list(*expected)


@pytest.mark.parametrize(
    "body, name",
    [
        ("r[::2] = [7]", "ValueError"),
        ("r[1:2] = 5", "TypeError"),
        ("r[::0] = []", "ValueError"),
        ("del r[::0]", "ValueError"),
        # ``slice indices must be integers or None or have an __index__ method``
        ("r[1:'a'] = []", "TypeError"),
        ("del r[1.5:]", "TypeError"),
    ],
)
def test_a_decided_slice_store_error_raises_at_the_store(tmp_path, body, name):
    returns, halts = _returns(tmp_path, _run(tmp_path, body))
    assert returns == []
    assert _halt_names(halts) == [name]


@pytest.mark.parametrize("body", ["r[i:] = [9]", "del r[:i]"])
def test_undecided_bounds_never_keep_the_old_list(tmp_path, body):
    # ``i`` may not be an index (``TypeError``): the store is two-faced, and
    # its completed face leaves the list unknown.
    (value,), _halts = _returns(tmp_path, _run(tmp_path, body, sig="i"))
    assert type(value) is not ListValue


def test_a_generator_rhs_is_never_a_type_error(tmp_path):
    returns, halts = _returns(tmp_path, _run(tmp_path, "r[1:2] = (x for x in [5, 6])"))
    assert "TypeError" not in _halt_names(halts)
    assert all(value != _list(1, 2, 3) for value in returns)
