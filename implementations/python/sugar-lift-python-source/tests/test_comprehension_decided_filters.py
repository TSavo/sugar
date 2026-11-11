"""A comprehension over a known sequence whose ``if`` filters are decided.

Python evaluates a member's filters in order, stops at the first false one,
and keeps the member only if all are true.  The finite map already projected
a filterless comprehension over a decided tuple or list member by member.
With any ``if`` it stayed a symbolic ComprehensionValue, so
``{k: v for k, v in [('p', 3), ('l', None)] if v is not None}`` could not
answer ``'l' in o``.  When every filter reached reduces to a plain decided
bool, the surviving members are fixed and the map projects over exactly
those.  A symbolic filter keeps the comprehension symbolic, as before.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
from sugar_lift_py_tests.outcome.exit_set import Halted

from test_undetermined_raise_except_matching import _exits


def _returns(tmp_path, source):
    exits = _exits(tmp_path, source).exits
    assert not any(isinstance(face, Halted) for face in exits)
    return [
        entry.value.value
        for face in exits
        for entry in face.value.record.statements
        if isinstance(entry, GuardedReturn)
    ]


def test_a_dict_comprehension_drops_what_its_filter_rejects(tmp_path):
    source = (
        "def f():\n"
        "    o = {k: v for k, v in [('p', 3), ('l', None)] if v is not None}\n"
        "    if 'l' in o:\n        return 7\n    if 'p' in o:\n        return 8\n"
        "    return 9\n"
    )
    assert _returns(tmp_path, source) == [8]


def test_filters_over_a_frame_s_actuals_decide_through_the_call(tmp_path):
    source = (
        "def g(p=None, l=None):\n"
        "    return {k: v for k, v in [('p', p), ('l', l)] if v is not None}\n"
        "def f():\n    o = g(3)\n    if 'l' in o:\n        return 7\n    return 8\n"
    )
    assert _returns(tmp_path, source) == [8]


def test_a_list_comprehension_keeps_only_members_all_filters_pass(tmp_path):
    source = (
        "def f():\n    o = [x for x in (1, None, 2) if x is not None if x != 2]\n"
        "    if 2 in o:\n        return 7\n    if 1 in o:\n        return 8\n"
        "    return 9\n"
    )
    assert _returns(tmp_path, source) == [8]


def test_a_symbolic_filter_keeps_the_comprehension_symbolic(tmp_path):
    exits = _exits(
        tmp_path,
        "import os\ndef f():\n"
        "    o = [x for x in (1, 2) if os.getpid() == x]\n"
        "    if 1 in o:\n        return 7\n    return 8\n",
    ).exits
    returned = sorted(
        entry.value.value
        for face in exits
        if not isinstance(face, Halted)
        for entry in face.value.record.statements
        if isinstance(entry, GuardedReturn)
    )
    assert returned == [7, 8]
