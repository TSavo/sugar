"""A constructor's guarded stores survive the ``super().__init__`` merge.

pytest's ``AbstractRaises.__init__`` stores ``self.match = re.compile(match)``
inside ``try``/``except re.error`` under ``isinstance(match, str)``.  Reached
through ``super().__init__(match=match)``, the completed construction came
back with no ``match`` under every guard: the callee's store was guarded, the
statement splice kept only unconditional stores, and the ground ``if`` flattened
its suite's routes into one ``true``-guarded completion.  A completed
construction never stores ``match`` in that merge, which is false.

The law: a decided ``if`` hands back the selected suite's own faces, and each
routed face of a ``try`` decides its own route slot.  So a completed
construction exists only where ``re.compile`` completed, and it carries the
compiled ``match``; the handler route halts; the unmatched raise stays an
undetermined halt.  ``e is None`` for a raised object is decided false -- an
exception is never the ``None`` singleton -- so the handler route of the
``re_error`` shape is a halt, not a completed construction without ``match``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect, UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted

from test_undetermined_raise_except_matching import _exits

RAISE_FROM = 'import re\nclass Base:\n    def __init__(self, *, match):\n        if isinstance(match, str):\n            try:\n                self.match = re.compile(match)\n            except re.error as e:\n                raise ValueError("bad") from e\n        else:\n            self.match = match\nclass Sub(Base):\n    def __init__(self, *, match=None):\n        super().__init__(match=match)\ndef f():\n    s = Sub(match="boom")\n    return s.match\n'

RE_ERROR_FLAG = 'import re\nclass Base:\n    def __init__(self, *, match):\n        if isinstance(match, str):\n            re_error = None\n            try:\n                self.match = re.compile(match)\n            except re.error as e:\n                re_error = e\n            if re_error is not None:\n                raise ValueError("bad")\n        else:\n            self.match = match\n        self._fail_reason = None\nclass Sub(Base):\n    def __init__(self, *, match=None):\n        super().__init__(match=match)\ndef f():\n    s = Sub(match="boom")\n    return s.match\n'


def _construction_faces(tmp_path: Path, source):
    """The faces of ``f``: ``Sub(...)`` is a call, so its faces are ``f``'s.

    A completed face returns ``s.match`` as that route's constructor stored it;
    the constructor's halts are ``f``'s own (#7756: never packed inside a
    completed value).
    """
    return _exits(tmp_path, source).exits


def _returned(face):
    (returned,) = [
        entry.value
        for entry in face.value.record.statements
        if type(entry).__name__ == "ReturnValue"
    ]
    return returned


@pytest.mark.parametrize("source", [RAISE_FROM, RE_ERROR_FLAG], ids=["raise-from", "re-error-flag"])
def test_completed_construction_keeps_the_compiled_match(tmp_path, source):
    faces = _construction_faces(tmp_path, source)
    completed = [face for face in faces if isinstance(face, Completed)]
    halted = [face for face in faces if isinstance(face, Halted)]

    # Exactly one completed construction: where re.compile completed.
    (face,) = completed
    assert getattr(face.guard, "name", None) == "python:source_call.completes"
    match = _returned(face)
    assert "re" in repr(match) and "compile" in repr(match)
    assert type(match).__name__ != "NoneValue"

    # The handler route halts with ValueError; the unmatched raise stays an
    # undetermined halt -- neither is silently a completion.
    effects = [type(face.effect) for face in halted]
    assert RaiseEffect in effects
    assert UndeterminedRaiseEffect in effects
    (value_error,) = [face for face in halted if type(face.effect) is RaiseEffect]
    assert "'ValueError'" in repr(value_error.effect.exception_type_coordinate)
    assert "'re.error'" in repr(value_error.guard)


def test_a_raised_object_is_never_none(tmp_path):
    exits = _exits(
        tmp_path,
        '''import textwrap
def f():
    try:
        textwrap.dedent("a")
    except ValueError as e:
        if e is None:
            return 2
        return 3
    return 1
''',
    )
    text = "\n".join(repr(face) for face in exits.exits if isinstance(face, Completed))
    assert "TermValue(value=3)" in text
    # ``e is None`` is decided false: no completion returns 2.
    assert "TermValue(value=2)" not in text
