"""A ``with`` halt face carries its bindings on its own record.

``with`` binds its manager, enter-result and exit-face slots before control
can leave by a raise.  Those facts ride on the halted face's pre-effect state,
where a handler or the function's halt row reads them.  They used to ride as a
companion ``Completed`` under the halt's own guard: the function was claimed
to complete (returning nothing) on exactly the path where ``__exit__`` raises.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import InvValue, TermValue
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_lift_py_tests.outcome.exit_set import ExitSet
from sugar_lift_py_tests.outcome.resource_bindings import prepend_facts_to_exitset
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

from test_undetermined_raise_except_matching import _exits

CLASS_EXIT = (
    "import shutil\n"
    "class CM:\n"
    "    def __enter__(self):\n"
    "        return 1\n"
    "    def __exit__(self, a, b, c):\n"
    "        shutil.rmtree('x')\n"
    "        return False\n"
    "def f():\n"
    "    with CM():\n"
    "        {body}\n"
    "{after}"
)

GENERATOR_EXIT = (
    "import contextlib, shutil\n"
    "@contextlib.contextmanager\n"
    "def cm():\n"
    "    yield 1\n"
    "    shutil.rmtree('x')\n"
    "def f():\n"
    "    with cm():\n"
    "        return 1\n"
)


def _faces(exits):
    completed = [face for face in exits.exits if isinstance(face, Completed)]
    halted = [face for face in exits.exits if isinstance(face, Halted)]
    return completed, halted


def _returns(face):
    return [
        entry.value
        for entry in face.value.record.statements
        if isinstance(entry, ReturnValue)
    ]


@pytest.mark.parametrize(
    "source",
    [
        CLASS_EXIT.format(body="return 1", after=""),
        CLASS_EXIT.format(body="y = 1", after="    return 1\n"),
        GENERATOR_EXIT,
    ],
    ids=["class-return", "class-fall-through", "generator-post-yield"],
)
def test_an_exit_that_may_raise_completes_only_where_it_completes(tmp_path, source):
    completed, halted = _faces(_exits(tmp_path, source))
    (halt,) = halted
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert "shutil.rmtree" in halt.effect.producer_node_owner
    # One completed face, and it returns: no completion under the halt guard.
    (done,) = completed
    assert _returns(done) == [TermValue(1)]
    assert done.guard != halt.guard


def test_the_halt_face_keeps_the_with_bindings_on_its_state(tmp_path):
    _completed, (halt,) = _faces(
        _exits(tmp_path, CLASS_EXIT.format(body="return 1", after=""))
    )
    facts = [
        str(entry.formula)
        for entry in getattr(halt.state, "entries", ())
        if isinstance(entry, InvValue)
    ]
    assert any("manager_slot_value" in fact for fact in facts)
    assert any("exit_type" in fact for fact in facts)


def test_prepend_rides_on_halt_state_and_keeps_completed_fields():
    from sugar_lift_py_tests.ir import atomic, not_

    fact = object()
    prior = object()
    guard = atomic("g", ())
    halted = Halted(
        guard,
        UndeterminedRaiseEffect(blame="b", occurrence="b"),
        _ReducedBlock(entries=(prior,), can_fall_through=False, fall_through=()),
    )
    stateless = Halted(
        not_(guard), UndeterminedRaiseEffect(blame="c", occurrence="c")
    )
    done = Completed(
        atomic("h", ()),
        _ReducedBlock(entries=(), can_fall_through=True, fall_through=()),
        frozenset(),
    )
    out = prepend_facts_to_exitset(
        ExitSet((halted, stateless, done)), (fact,)
    ).exits
    halts = [face for face in out if isinstance(face, Halted)]
    dones = [face for face in out if isinstance(face, Completed)]
    assert len(halts) == 2 and len(dones) == 1
    states = sorted((face.state.entries for face in halts), key=len)
    assert states == [(fact,), (fact, prior)]
    assert dones[0].value.entries == (fact,)
