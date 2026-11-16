"""A ``try`` hands back its own faces; it never flattens its routes into one.

``TrySugar`` collapsed every routed outcome through ``exitset_to_outcome``:
one completed record whose entries were merely guarded.  The routes' own
temporal state -- stores, the reduction context, fall-through -- was merged,
so a body that bound ``x = 1`` only after ``textwrap.dedent`` completed
produced two completions, ``x == 1`` under ``completes`` and ``x == 0`` under
``not completes``.  The second is a state no route produces: when the call
raises something other than ``ValueError`` the function does not complete at
all.

The try now returns its face set; the block reducer sequences the tail under
each completed face, so every face keeps exactly the state its route built.
The routes are read in the function that holds the ``try``: a same-file
class's constructor is its call, coordinate and edge (#7757 step 6, #8958),
never its body followed from a caller.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted

from test_undetermined_raise_except_matching import _exits

ROUTES = '''import textwrap
def f():
    x = 0
    try:
        textwrap.dedent("a")
        x = 1
    except ValueError:
        pass
    return x
'''


def _route_faces(tmp_path: Path):
    """The faces of ``f``: each completed face returns the ``x`` its route
    bound; the uncaught escape is ``f``'s own halt."""
    return _exits(tmp_path, ROUTES).exits


def _returned_x(face):
    (returned,) = [
        entry.value.value
        for entry in face.value.record.statements
        if type(entry).__name__ == "ReturnValue"
    ]
    return returned


def test_each_route_keeps_only_the_state_it_built(tmp_path):
    faces = _route_faces(tmp_path)
    completed = [face for face in faces if isinstance(face, Completed)]
    halted = [face for face in faces if isinstance(face, Halted)]

    by_x = {_returned_x(face): face.guard for face in completed}
    assert set(by_x) == {0, 1}
    # x == 1 only where the call completed.
    assert "python:unknown_callee_call.completes" in repr(by_x[1])
    assert "adt.is_python_type" not in repr(by_x[1])
    # x == 0 only where the handler caught a ValueError -- never under the
    # bare complement of ``completes``.
    assert "adt.is_python_type" in repr(by_x[0])
    assert "'ValueError'" in repr(by_x[0])

    # Any other exception leaves the function uncaught.
    (escape,) = halted
    assert isinstance(escape.effect, UndeterminedRaiseEffect)
    assert escape.effect.producer_node_owner == "UnknownCallee:textwrap.dedent"
    assert "kind='not', operands=(_Atomic(name='adt.is_python_type'" in repr(escape.guard)


def test_a_multi_route_try_is_its_face_set(tmp_path):
    exits = _exits(
        tmp_path,
        '''import decimal
def f():
    try:
        return decimal.getcontext()
    except ValueError:
        return 1
''',
    )
    kinds = sorted(type(face).__name__ for face in exits.exits)
    assert kinds == ["Completed", "Completed", "Halted"]
    (caught,) = [
        face
        for face in exits.exits
        if isinstance(face, Completed) and "adt.is_python_type" in repr(face.guard)
    ]
    returns = [
        entry.value.value
        for entry in caught.value.record.statements
        if type(entry).__name__ == "ReturnValue"
    ]
    assert returns == [1]
