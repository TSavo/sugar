"""``g(*a, **k)`` with no source frame projected here is two-faced.

A spread call whose callee no frame projected (an unknown name, a module
member, a builtin, a source function the frame did not bind) used to complete
totally with a bodiless ``CallSiteValue``: a silent claim that the callee
never raises.  It now completes only under
``python:spread_call.completes(python:spread_call(<callee>, <occurrence>))``
with the value ``python:call_result(<call term>, <occurrence>)`` and halts
with an ``UndeterminedRaiseEffect`` (owner ``UnprojectedSpreadCall:<callee>``)
under the complement -- the #7585 law.  Reproducer: numpy's
``printoptions`` (``token = _set_printoptions(*args, **kwargs)``).
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Halted

from test_undetermined_raise_except_matching import _exits


def _owners(exits):
    return [
        face.effect.producer_node_owner
        for face in exits.exits
        if isinstance(face, Halted) and isinstance(face.effect, UndeterminedRaiseEffect)
    ]


@pytest.mark.parametrize(
    "source, callee",
    [
        ("def f(*a, **k):\n    h(*a, **k)\n    return 1\n", "h"),
        ("def g(x):\n    return x\ndef f():\n    return g(*(1,))\n", "g"),
        ("def f():\n    return print(*(1,))\n", "print"),
    ],
    ids=["unknown", "unframed-source", "builtin"],
)
def test_an_unprojected_spread_call_may_raise(tmp_path, source, callee):
    exits = _exits(tmp_path, source)
    assert f"UnprojectedSpreadCall:{callee}" in _owners(exits)
    completed = [face for face in exits.exits if not isinstance(face, Halted)]
    assert completed and all(
        "python:spread_call.completes" in str(face.guard) for face in completed
    )


def test_two_spread_calls_are_two_unknowns(tmp_path):
    exits = _exits(tmp_path, "def f(*a):\n    h(*a)\n    h(*a)\n    return 1\n")
    halts = [
        face.effect
        for face in exits.exits
        if isinstance(face, Halted)
        and face.effect.producer_node_owner == "UnprojectedSpreadCall:h"
    ]
    assert len({effect.occurrence for effect in halts}) == 2
