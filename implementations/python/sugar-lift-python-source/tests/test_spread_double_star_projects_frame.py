"""``g(**k)`` to a module function is the call's coordinate and edge.

#7644 gave a ``*`` spread call the callee's own lexical source frame, and a
``**`` call followed.  That frame is gone (#7757 step 6, the owner
2026-11-15: a same-file call is a coordinate and an edge joined at prove):
the mapping's entries are the call's operands (expanded by the one ``**``
reader), and the call is the one unanswered call, its halt kept and owed.
That is numpy's ``_set_printoptions(*args, **kwargs)`` →
``_make_options_dict`` chain under ``np.printoptions(precision=3)``: never a
completion decided by reading the callee's body.
"""

from __future__ import annotations

from test_spread_decided_tuple_projects_frame import the_call_is_owed_and_both_arms_stay
from test_undetermined_raise_except_matching import _exits

_G = "def g(p=None, legacy=None):\n    if legacy is None:\n        return p\n    raise ValueError\n"


def test_a_constructed_mapping_is_the_call_owed(tmp_path):
    exits = _exits(
        tmp_path,
        _G + "def f():\n    if g(**{'p': 3}) == 3:\n        return 7\n    raise ValueError\n",
    )
    the_call_is_owed_and_both_arms_stay(exits, "e.g")


def test_a_forwarded_kwargs_call_is_the_outer_call_owed(tmp_path):
    exits = _exits(
        tmp_path,
        _G
        + "def h(**kwargs):\n    return g(**kwargs)\n"
        + "def f():\n    if h(p=3) == 3:\n        return 7\n    raise ValueError\n",
    )
    # ``f`` calls ``h`` alone; neither ``h``'s body nor ``g``'s is read.
    the_call_is_owed_and_both_arms_stay(exits, "e.h")
