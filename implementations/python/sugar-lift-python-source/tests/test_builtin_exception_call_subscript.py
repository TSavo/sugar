"""Subscripting a freshly constructed builtin exception raises TypeError.

``ExceptionValue.subscript`` (#7582) decided ``exc[i]`` for a raised builtin
exception. A builtin exception constructed in value position,
``ValueError("a")[0]``, never became an ``ExceptionValue``: it stood as the
opaque ``call:ValueError`` CallSiteValue, whose subscript completed as a
symbolic ``py.subscript``. That hid a decided TypeError. The call now records
the builtin exception class it applied, read from the callee's bound value and
not its spelling, and its subscript is the same ground TypeError.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_source_tree.nodes import FunctionDef

from test_contextlib_suppress_source_exit_faces import _corpus, _open


def _exits(tmp_path: Path, body: str):
    source_file = _open(_corpus(tmp_path, body))
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    return func.sugar().desugar()


def _only_type_error(exits) -> RaiseEffect:
    (face,) = exits.exits
    assert isinstance(face, Halted)
    assert isinstance(face.effect, RaiseEffect)
    assert face.effect.exception_name == "TypeError"
    return face.effect


@pytest.mark.parametrize(
    "body",
    [
        "def f():\n    return ValueError('a')[0]\n",
        "def f():\n    e = ValueError('a')\n    return e[0]\n",
        "def f():\n    return KeyError('k')['k']\n",
        "def f():\n    return OSError(2, 'x')[0]\n",
    ],
)
def test_builtin_exception_instance_subscript_is_a_ground_type_error(
    tmp_path, body
) -> None:
    effect = _only_type_error(_exits(tmp_path, body))
    assert "py.subscript" not in repr(effect)


def test_an_exception_group_over_a_non_ground_member_is_the_unanswered_call(
    tmp_path,
) -> None:
    # ``ExceptionGroup``'s constructor reads its members (a non-exception
    # member is a TypeError, ``BaseExceptionGroup`` selects its subclass by
    # them), and ``ValueError('a')`` is no ground value: the construction is
    # the one unanswered call (#7757).  Its completed face is still a
    # builtin exception instance, whose subscript is the TypeError.
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    from test_unprojected_method_call_faces import _owners

    exits = _exits(
        tmp_path, "def f():\n    return ExceptionGroup('g', [ValueError('a')])[0]\n"
    )
    halts = [face.effect for face in exits.exits if isinstance(face, Halted)]
    assert not [face for face in exits.exits if isinstance(face, Completed)]
    assert len(owed_calls(exits)) == 1
    assert "UnknownCallee:ExceptionGroup" in _owners(halts)
    raised = [e.exception_name for e in halts if isinstance(e, RaiseEffect)]
    assert raised == ["TypeError"]


def test_the_type_error_is_caught_by_an_except_type_error(tmp_path) -> None:
    exits = _exits(
        tmp_path,
        "def f():\n"
        "    try:\n"
        "        return ValueError('a')[0]\n"
        "    except TypeError:\n"
        "        return 2\n",
    )
    assert not [face for face in exits.exits if isinstance(face, Halted)]
    (face,) = exits.exits
    assert isinstance(face, Completed)
    assert "TermValue(value=2)" in repr(face.value)


def test_a_rebound_exception_name_is_not_the_builtin(tmp_path) -> None:
    # The binding, not the spelling, decides: a local ValueError class with
    # __getitem__ is not the language-owned exception class.
    exits = _exits(
        tmp_path,
        "class ValueError:\n"
        "    def __getitem__(self, i):\n"
        "        return i\n"
        "def f():\n"
        "    return ValueError()[0]\n",
    )
    assert not [
        face
        for face in exits.exits
        if isinstance(face, Halted)
        and isinstance(face.effect, RaiseEffect)
        and face.effect.exception_name == "TypeError"
    ]
