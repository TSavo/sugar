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


# -- the bodiless ``.args`` read: BaseException's law, or no answer ---------


def _bodiless_exception_call(class_name, *, keyword_names=()):
    """A bodiless call of the builtin exception class ``class_name``, as the
    call site applies it: its binding's class, its raised type's coordinate,
    three positional actuals (the last ones keywords when ``keyword_names``)."""
    from sugar_lift_py_tests.call_symbol import call_symbol
    from sugar_lift_py_tests.floor import StringValue
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.temporal.builtin_name_bindings import (
        builtin_name_temporal,
    )

    actuals = (StringValue("a"), StringValue("b"), StringValue("c"))
    return CallSiteValue(
        target_name=class_name,
        arg_values=actuals,
        parameters=(),
        term=ctor(
            call_symbol(class_name),
            [value.to_term(owner="test") for value in actuals],
        ),
        body=None,
        keyword_names=keyword_names,
        exception_type_coordinate=ctor(
            "python:exception_type_identity",
            [str_const("builtin"), str_const(class_name)],
        ),
        builtin_exception_class=builtin_name_temporal().value_if_bound(class_name),
    )


def test_a_base_exception_law_call_reads_its_positional_actuals_as_args() -> None:
    from sugar_lift_py_tests.floor import StringValue, TupleValue

    (face,) = _bodiless_exception_call("ValueError").attribute("args", None, None).exits
    assert isinstance(face, Completed)
    assert face.value == TupleValue(
        (StringValue("a"), StringValue("b"), StringValue("c"))
    )


@pytest.mark.parametrize(
    "class_name", ["OSError", "FileNotFoundError", "SyntaxError", "IndentationError"]
)
def test_a_constructor_of_its_own_never_reads_the_actuals_as_args(class_name) -> None:
    # ``OSError('a', 'b', 'c').args == ('a', 'b')``: not BaseException's law,
    # so ``.args`` is not the actuals; it is refused by name.
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(SugarNotWritten):
        _bodiless_exception_call(class_name).attribute("args", None, None)


def test_a_call_with_a_keyword_never_reads_the_actuals_as_args() -> None:
    from sugar_source_tree.panic import SugarNotWritten

    call = _bodiless_exception_call("ImportError", keyword_names=("name",))
    with pytest.raises(SugarNotWritten):
        call.attribute("args", None, None)
