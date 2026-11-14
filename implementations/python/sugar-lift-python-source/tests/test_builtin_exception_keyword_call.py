"""A builtin exception call with a keyword actual never completes with args.

``ValueError('x', code=1)`` was bodiless and completed, its keyword values
appended to ``arg_values`` -- so ``.args`` read ``('x', 1)`` (#7757, left by
#8058).  ``BaseException_new`` stores only the positional actuals, and every
builtin exception whose constructor is BaseException's law initializes through
``BaseException_init``, which raises TypeError for any keyword
(``builtin_exception_constructor_rejects_keywords``).  So the call is that
TypeError.  A class whose constructor may read keywords (``ImportError``,
``AttributeError``, ``NameError``) or is not BaseException's (``OSError``) is
not read: the call is the one unanswered call, never a completion with args.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_lift_py_tests.unanswered_calls import owed_calls
from sugar_source_tree.nodes import FunctionDef

from test_contextlib_suppress_source_exit_faces import _corpus, _open
from test_unprojected_method_call_faces import _owners


def _exits(tmp_path: Path, body: str):
    source_file = _open(_corpus(tmp_path, body))
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    return func.sugar().desugar()


@pytest.mark.parametrize(
    "body",
    [
        "def f():\n    return ValueError('a', code=1)\n",
        "def f():\n    raise KeyError('k', note=2)\n",
        "def f():\n    e = Exception(code=1)\n    return e.args\n",
    ],
)
def test_a_keyword_to_a_base_exception_constructor_is_the_type_error(
    tmp_path, body
) -> None:
    (face,) = _exits(tmp_path, body).exits
    assert isinstance(face, Halted)
    assert isinstance(face.effect, RaiseEffect)
    assert face.effect.exception_name == "TypeError"


def test_the_type_error_is_caught_by_an_except_type_error(tmp_path) -> None:
    exits = _exits(
        tmp_path,
        "def f():\n"
        "    try:\n"
        "        return ValueError('a', code=1)\n"
        "    except TypeError:\n"
        "        return 2\n",
    )
    (face,) = exits.exits
    assert isinstance(face, Completed)
    assert "TermValue(value=2)" in repr(face.value)


@pytest.mark.parametrize(
    "callee",
    ["ImportError('m', name='x')", "AttributeError('a', obj=1)", "OSError(2, x=1)"],
)
def test_a_constructor_that_may_read_keywords_is_the_unanswered_call(
    tmp_path, callee
) -> None:
    exits = _exits(tmp_path, f"def f():\n    return {callee}\n")
    halts = [face.effect for face in exits.exits if isinstance(face, Halted)]
    assert len(owed_calls(exits)) == 1
    assert _owners(halts) == [f"UnknownCallee:{callee.split('(')[0]}"]
