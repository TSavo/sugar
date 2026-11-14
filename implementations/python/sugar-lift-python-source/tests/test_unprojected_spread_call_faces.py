"""``g(*a, **k)`` with no source frame projected here is the one unanswered call.

A spread call whose callee no frame projected (an unknown name, a module
member, a builtin, a source function the frame did not bind) used to complete
totally with a bodiless ``CallSiteValue``: a silent claim that the callee
never raises.  It is the one unanswered call (``UnknownCalleeCallV1``, #7757):
it completes only under
``python:unknown_callee_call.completes(python:unknown_callee_call(<callee>,
<occurrence>))`` with the value ``python:call_result(<call term>,
<occurrence>)``, halts with an ``UndeterminedRaiseEffect`` (owner
``UnknownCallee:<callee>``) under the complement -- the #7585 law -- and both
faces owe the call.  Reproducer: numpy's ``printoptions``
(``token = _set_printoptions(*args, **kwargs)``).
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Halted
from sugar_lift_py_tests.unanswered_calls import owed_calls

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
        ("def g(*x):\n    return x\ndef f(*a):\n    return g(*a)\n", "g"),
        ("def f():\n    return print(*(1,))\n", "print"),
    ],
    ids=["unknown", "unframed-source", "builtin"],
)
def test_an_unprojected_spread_call_may_raise(tmp_path, source, callee):
    exits = _exits(tmp_path, source)
    assert f"UnknownCallee:{callee}" in _owners(exits)
    completed = [face for face in exits.exits if not isinstance(face, Halted)]
    assert completed and all(
        "python:unknown_callee_call.completes" in str(face.guard)
        for face in completed
    )
    assert not any("python:spread_call" in str(face.guard) for face in exits.exits)


def test_an_unanswered_spread_call_is_two_faced_and_owes_one_call(tmp_path):
    # #7757: ``h(*a)`` with ``h`` bound nowhere has no body to apply.  It is
    # the one unanswered form: one completed face, one undetermined raise,
    # and one unanswered call owed -- never a completion that drops the raise.
    exits = _exits(tmp_path, "def f(*a):\n    return h(*a)\n")
    completed = [face for face in exits.exits if not isinstance(face, Halted)]
    assert len(completed) == 1
    assert _owners(exits) == ["UnknownCallee:h"]
    assert len(owed_calls(exits)) == 1


def test_two_spread_calls_are_two_unknowns(tmp_path):
    exits = _exits(tmp_path, "def f(*a):\n    h(*a)\n    h(*a)\n    return 1\n")
    halts = [
        face.effect
        for face in exits.exits
        if isinstance(face, Halted)
        and face.effect.producer_node_owner == "UnknownCallee:h"
    ]
    assert len({effect.occurrence for effect in halts}) == 2
