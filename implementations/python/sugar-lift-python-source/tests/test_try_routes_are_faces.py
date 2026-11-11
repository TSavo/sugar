"""A ``try`` hands back its own faces; it never flattens its routes into one.

``TrySugar`` collapsed every routed outcome through ``exitset_to_outcome``:
one completed record whose entries were merely guarded.  The routes' own
temporal state -- receiver stores, the reduction context, fall-through -- was
merged, so a constructor that stored ``self.x = 1`` only after
``textwrap.dedent`` completed produced two completed constructions, ``x == 1``
under ``completes`` and ``x == 0`` under ``not completes``.  The second is a
state no route produces: when the call raises something other than
``ValueError`` the constructor does not complete at all.

The try now returns its face set; the block reducer sequences the tail under
each completed face, so every face keeps exactly the state its route built.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted

from test_undetermined_raise_except_matching import _exits

CONSTRUCTOR = '''import textwrap
class C:
    def __init__(self):
        self.x = 0
        try:
            textwrap.dedent("a")
            self.x = 1
        except ValueError:
            pass
def f():
    c = C()
    return c.x
'''


def _construction_faces(tmp_path: Path):
    """The faces of ``f``: ``C()`` is a call, so its routes are ``f``'s routes.

    Each completed face returns the ``x`` that route's constructor built; the
    uncaught escape is ``f``'s own halt (#7756: a constructor's halts are the
    call's, never packed inside a completed value).
    """
    return _exits(tmp_path, CONSTRUCTOR).exits


def _returned_x(face):
    (returned,) = [
        entry.value.value
        for entry in face.value.record.statements
        if type(entry).__name__ == "ReturnValue"
    ]
    return returned


def test_each_route_constructs_only_the_state_it_built(tmp_path):
    faces = _construction_faces(tmp_path)
    completed = [face for face in faces if isinstance(face, Completed)]
    halted = [face for face in faces if isinstance(face, Halted)]

    by_x = {_returned_x(face): face.guard for face in completed}
    assert set(by_x) == {0, 1}
    # x == 1 only where the call completed.
    assert getattr(by_x[1], "name", None) == "python:source_call.completes"
    # x == 0 only where the handler caught a ValueError -- never under the
    # bare complement of ``completes``.
    assert "adt.is_python_type" in repr(by_x[0])
    assert "'ValueError'" in repr(by_x[0])

    # Any other exception leaves the constructor uncaught, carrying x == 0.
    (escape,) = halted
    assert isinstance(escape.effect, UndeterminedRaiseEffect)
    assert escape.effect.producer_node_owner == "UnprojectedSourceCall:textwrap.dedent"
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
