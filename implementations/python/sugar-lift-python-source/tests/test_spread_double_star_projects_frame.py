"""``g(**k)`` names a module function the lexical scope resolves: its frame.

#7644 gave a ``*`` spread call the callee's own lexical source frame. A
``**``-only call to the same function went without one, so ``g(**{'p': 3})``
and ``def h(**kw): return g(**kw)`` stayed two-faced
(an unanswered call, ``UnknownCallee:g``) even though the mapping was a constructed
DictValue that ``bind_actuals`` merges onto the formals.  Now the ``**`` call
gets the same lexical frame, and its keys bind by name, the rest by default.
That is numpy's ``_set_printoptions(*args, **kwargs)`` → ``_make_options_dict``
chain under ``np.printoptions(precision=3)``.
"""

from __future__ import annotations

from sugar_lift_py_tests.outcome import Halted

from test_spread_decided_tuple_projects_frame import _returns, _spread_halts
from test_undetermined_raise_except_matching import _exits

_G = "def g(p=None, legacy=None):\n    if legacy is None:\n        return p\n    raise ValueError\n"


def test_a_constructed_mapping_binds_by_name_through_the_callee_body(tmp_path):
    exits = _exits(
        tmp_path,
        _G + "def f():\n    if g(**{'p': 3}) == 3:\n        return 7\n    raise ValueError\n",
    )
    assert _spread_halts(exits) == []
    assert [value.value for value in _returns(exits)] == [7]
    assert not any(isinstance(face, Halted) for face in exits.exits)


def test_a_forwarded_kwargs_mapping_binds_through_two_frames(tmp_path):
    exits = _exits(
        tmp_path,
        _G
        + "def h(**kwargs):\n    return g(**kwargs)\n"
        + "def f():\n    if h(p=3) == 3:\n        return 7\n    raise ValueError\n",
    )
    assert _spread_halts(exits) == []
    assert [value.value for value in _returns(exits)] == [7]
    assert not any(isinstance(face, Halted) for face in exits.exits)
