"""A builtin exception call with a keyword actual never completes with args.

``ValueError('x', code=1)`` was bodiless and completed, its keyword values
appended to ``arg_values`` -- so ``.args`` read ``('x', 1)`` (#7757, left by
#8058).  ``BaseException_new`` stores only the positional actuals, and every
builtin exception whose constructor is BaseException's law initializes through
``BaseException_init``, which raises TypeError for any keyword
(``builtin_exception_constructor_rejects_keywords``).  So the call is that
TypeError.  A class whose constructor may read keywords (``ImportError``,
``AttributeError``, ``NameError``) or is not BaseException's (``OSError``) is
not read over an actual known only by its type: the call is the one
unanswered call, never a completion with args.

Over ground actuals the pinned interpreter constructs the class
(``builtin_exception_cited_fold``, #7757): ``OSError(2, 'x')`` is a
``FileNotFoundError`` with ``args`` ``(2, 'x')``, ``SyntaxError('m', 5)`` is
the TypeError, and ``.args`` reads what the construction stored.
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
    ["ImportError('m', name=v)", "AttributeError('a', obj=v)", "OSError(2, x=v)"],
)
def test_a_constructor_that_may_read_keywords_is_the_unanswered_call(
    tmp_path, callee
) -> None:
    # ``v`` is known only by its type: what the constructor does with it is
    # not read here.
    exits = _exits(tmp_path, f"def f(v):\n    return {callee}\n")
    halts = [face.effect for face in exits.exits if isinstance(face, Halted)]
    assert len(owed_calls(exits)) == 1
    assert _owners(halts) == [f"UnknownCallee:{callee.split('(')[0]}"]


# -- ground actuals: the pinned interpreter constructs (#7757) --------------


def _completed_instance(exits):
    """The one value ``f`` returns, on its one face."""
    from test_assignment_evaluates_rhs import _rows

    ((kind, value, _guard),) = _rows(exits)
    assert kind == "return"
    return value


def test_ground_keywords_the_class_accepts_are_constructed_by_the_interpreter(
    tmp_path,
) -> None:
    from sugar_lift_py_tests.floor import StringValue, TupleValue

    value = _completed_instance(
        _exits(tmp_path, "def f():\n    return ImportError('m', name='x')\n")
    )
    assert value.builtin_exception_class.name == "ImportError"
    # ``ImportError('m', name='x').args == ('m',)``: keywords are never args.
    assert value.constructed_args == TupleValue((StringValue("m"),))


def test_ground_keywords_os_error_rejects_are_the_type_error(tmp_path) -> None:
    (face,) = _exits(tmp_path, "def f():\n    return OSError(2, x=1)\n").exits
    assert isinstance(face, Halted)
    assert isinstance(face.effect, RaiseEffect)
    assert face.effect.exception_name == "TypeError"


def _exception_identity(name):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity", [str_const("builtins"), str_const(name)]
    )


def test_os_error_with_an_errno_constructs_its_subclass(tmp_path) -> None:
    # ``OSError(2, 'x')`` is a ``FileNotFoundError`` (``OSError_new`` selects
    # the subclass by errno): never typed ``OSError``.
    from sugar_lift_py_tests.floor import StringValue, TermValue, TupleValue

    value = _completed_instance(
        _exits(tmp_path, "def f():\n    return OSError(2, 'x')\n")
    )
    assert value.builtin_exception_class.name == "FileNotFoundError"
    assert value.constructed_args == TupleValue((TermValue(2), StringValue("x")))
    (face,) = _exits(tmp_path, "def f():\n    raise OSError(2, 'x')\n").exits
    assert isinstance(face, Halted)
    assert isinstance(face.effect, RaiseEffect)
    assert face.effect.exception_type_coordinate == _exception_identity(
        "FileNotFoundError"
    )
    (args_face,) = face.effect.raised_value.attribute("args", None, None).exits
    assert args_face.value == TupleValue((TermValue(2), StringValue("x")))


def test_os_error_args_drop_the_filename(tmp_path) -> None:
    from sugar_lift_py_tests.floor import StringValue, TermValue, TupleValue

    value = _completed_instance(
        _exits(tmp_path, "def f():\n    return OSError(2, 'x', 'f')\n")
    )
    assert value.builtin_exception_class.name == "FileNotFoundError"
    assert value.constructed_args == TupleValue((TermValue(2), StringValue("x")))


def test_os_error_with_one_argument_stays_os_error(tmp_path) -> None:
    from sugar_lift_py_tests.floor import StringValue, TupleValue

    value = _completed_instance(
        _exits(tmp_path, "def f():\n    return OSError('m')\n")
    )
    assert value.builtin_exception_class.name == "OSError"
    assert value.constructed_args == TupleValue((StringValue("m"),))
    (face,) = _exits(tmp_path, "def f():\n    raise OSError('m')\n").exits
    assert isinstance(face, Halted)
    assert face.effect.exception_type_coordinate == _exception_identity("OSError")


def test_syntax_error_with_a_non_tuple_detail_is_the_type_error(tmp_path) -> None:
    # ``SyntaxError('m', 5)``: ``SyntaxError_init`` reads its second actual
    # as the details tuple; CPython raises TypeError.
    (face,) = _exits(tmp_path, "def f():\n    return SyntaxError('m', 5)\n").exits
    assert isinstance(face, Halted)
    assert isinstance(face.effect, RaiseEffect)
    assert face.effect.exception_name == "TypeError"


@pytest.mark.parametrize("statement", ["return", "raise"])
def test_os_error_over_a_symbolic_errno_is_the_unanswered_call(
    tmp_path, statement
) -> None:
    # ``e`` is known only by its type, and OSError's class is chosen by its
    # value: the one unanswered call, never a completion typed ``OSError``.
    exits = _exits(tmp_path, f"def f(e):\n    {statement} OSError(e, 'x')\n")
    halts = [face.effect for face in exits.exits if isinstance(face, Halted)]
    assert len(owed_calls(exits)) == 1
    assert "UnknownCallee:OSError" in _owners(halts)
    assert not [effect for effect in halts if isinstance(effect, RaiseEffect)]


def _group_faces(exits):
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    return [
        face
        for face in exits.exits
        if isinstance(face, Halted) and isinstance(face.effect, GroupedRaiseEffect)
    ]


def test_a_group_member_is_typed_by_its_construction(tmp_path) -> None:
    # The member ``OSError(2, 'x')`` is constructed as the raised call is: a
    # ``FileNotFoundError``, never typed ``OSError`` from its callee.
    exits = _exits(
        tmp_path, "def f():\n    raise ExceptionGroup('g', [OSError(2, 'x')])\n"
    )
    (group_face,) = _group_faces(exits)
    assert exits.exits == (group_face,)
    (leaf,) = group_face.effect.children
    assert isinstance(leaf, RaiseEffect)
    assert leaf.exception_type_coordinate == _exception_identity("FileNotFoundError")
    assert group_face.effect.exception_type_coordinate == _exception_identity(
        "ExceptionGroup"
    )


def test_a_group_member_over_a_symbolic_errno_is_undecided(tmp_path) -> None:
    # ``e`` is known only by its type: the member's construction is the one
    # unanswered call, so the member is undecided, and the call's own raise
    # halts before any group exists.  Whether the undecided member is an
    # ``Exception`` instance is not decided here, so neither is the group's
    # class: its construction is the one two-faced unanswered outcome,
    # owing the construction beside the member's call.
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect

    exits = _exits(
        tmp_path, "def f(e):\n    raise ExceptionGroup('g', [OSError(e, 'x')])\n"
    )
    (group_face,) = _group_faces(exits)
    (leaf,) = group_face.effect.children
    assert isinstance(leaf, UndeterminedRaiseEffect)
    assert group_face.effect.exception_type_coordinate is None
    assert group_face.effect.exception_type_mro is None
    assert group_face.owed
    assert len(owed_calls(exits)) == 2
    halts = [face.effect for face in exits.exits if isinstance(face, Halted)]
    owners = _owners(halts)
    assert "UnknownCallee:OSError" in owners
    assert "ExceptionGroupConstruction:ExceptionGroup" in owners


# -- the group's own class: its construction's, by CPython's rule (#7757) ----


def _one_halt(exits):
    (face,) = exits.exits
    assert isinstance(face, Halted)
    return face.effect


@pytest.mark.parametrize(
    ("raised", "constructed"),
    [
        # ``BaseExceptionGroup`` whose members are all ``Exception``
        # constructs an ``ExceptionGroup``.
        ("BaseExceptionGroup('g', [ValueError()])", "ExceptionGroup"),
        ("BaseExceptionGroup('g', [KeyboardInterrupt()])", "BaseExceptionGroup"),
        (
            "BaseExceptionGroup('g', [ValueError(), SystemExit()])",
            "BaseExceptionGroup",
        ),
        ("ExceptionGroup('g', [ValueError(), KeyError('k')])", "ExceptionGroup"),
        # A nested group is a member like any other: an ``ExceptionGroup`` is
        # an ``Exception``.
        (
            "BaseExceptionGroup('g', [BaseExceptionGroup('i', [ValueError()])])",
            "ExceptionGroup",
        ),
    ],
)
def test_a_group_class_is_decided_by_its_members(tmp_path, raised, constructed) -> None:
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    effect = _one_halt(_exits(tmp_path, f"def f():\n    raise {raised}\n"))
    assert isinstance(effect, GroupedRaiseEffect)
    assert effect.exception_type_coordinate == _exception_identity(constructed)
    assert effect.exception_type_mro[0] == _exception_identity(constructed)


@pytest.mark.parametrize(
    "raised",
    [
        "ExceptionGroup('g', [KeyboardInterrupt()])",
        "ExceptionGroup('g', [ValueError(), SystemExit()])",
        "ExceptionGroup('g', [BaseExceptionGroup('i', [KeyboardInterrupt()])])",
    ],
)
def test_an_exception_group_of_a_base_exception_is_the_type_error(
    tmp_path, raised
) -> None:
    # "Cannot nest BaseExceptions in an ExceptionGroup": the construction
    # raises before any group exists.
    effect = _one_halt(_exits(tmp_path, f"def f():\n    raise {raised}\n"))
    assert isinstance(effect, RaiseEffect)
    assert effect.exception_type_coordinate == _exception_identity("TypeError")


@pytest.mark.parametrize(
    "raised",
    [
        # A class named without calling it is not an exception instance:
        # "Item 0 of second argument (exceptions) is not an exception".
        "ExceptionGroup('g', [ValueError])",
        "BaseExceptionGroup('g', (ValueError(), KeyError))",
        "ExceptionGroup('g', [ValueError(), KeyError])",
        "BaseExceptionGroup('g', [KeyboardInterrupt])",
        # The exceptions must be a non-empty sequence.
        "ExceptionGroup('g', [])",
    ],
)
def test_a_group_of_a_non_instance_or_of_nothing_is_the_value_error(
    tmp_path, raised
) -> None:
    effect = _one_halt(_exits(tmp_path, f"def f():\n    raise {raised}\n"))
    assert isinstance(effect, RaiseEffect)
    assert effect.exception_type_coordinate == _exception_identity("ValueError")


def test_a_non_instance_member_is_caught_as_the_value_error(tmp_path) -> None:
    exits = _exits(
        tmp_path,
        "def f():\n"
        "    try:\n"
        "        raise ExceptionGroup('g', [ValueError])\n"
        "    except ValueError:\n"
        "        return 2\n",
    )
    (face,) = exits.exits
    assert isinstance(face, Completed)
    assert "TermValue(value=2)" in repr(face.value)


# -- the group's message: ``PyArg_ParseTuple("UO")`` (#7757) -----------------


@pytest.mark.parametrize(
    "raised",
    [
        "ExceptionGroup(1, [ValueError()])",
        "BaseExceptionGroup(2.5, [KeyboardInterrupt()])",
    ],
)
def test_a_non_str_group_message_is_the_type_error(tmp_path, raised) -> None:
    # The constructor parses its message as ``U`` before any member rule:
    # a decided non-``str`` message is the TypeError, no group exists.
    effect = _one_halt(_exits(tmp_path, f"def f():\n    raise {raised}\n"))
    assert isinstance(effect, RaiseEffect)
    assert effect.exception_type_coordinate == _exception_identity("TypeError")


def test_a_group_whose_message_type_is_undecided_is_two_faced(tmp_path) -> None:
    # ``m`` is known only by its type: the group is raised under
    # ``isinstance(m, str)`` and the TypeError under its complement, both
    # owing the one undecided read.
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    exits = _exits(
        tmp_path, "def f(m):\n    raise ExceptionGroup(m, [ValueError('v')])\n"
    )
    halts = [face for face in exits.exits if isinstance(face, Halted)]
    assert halts == list(exits.exits)
    groups = [face for face in halts if isinstance(face.effect, GroupedRaiseEffect)]
    type_errors = [
        face
        for face in halts
        if isinstance(face.effect, RaiseEffect)
        and face.effect.exception_type_coordinate == _exception_identity("TypeError")
    ]
    assert len(groups) == 1 and len(type_errors) == 1, halts
    assert groups[0].effect.exception_type_coordinate == _exception_identity(
        "ExceptionGroup"
    )
    assert "adt.is_python_type" in repr(groups[0].guard)
    assert groups[0].owed and type_errors[0].owed
    assert len(owed_calls(exits)) == 1


# -- except* over a plain undetermined raise (#7757) -------------------------


def test_except_star_routes_an_undetermined_raise_two_ways(tmp_path) -> None:
    # ``OSError(e, 'x')`` is the one unanswered call: its raise is of no
    # decided class.  ``except*`` matches it as its one-member group, the
    # match is retained, so the handler runs under the type test and the
    # raise leaves unwrapped under its complement -- never refused, and the
    # call's debt rides on every face.
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect

    exits = _exits(
        tmp_path,
        "def f(e):\n"
        "    try:\n"
        "        raise OSError(e, 'x')\n"
        "    except* ValueError:\n"
        "        return 2\n",
    )
    completed = [face for face in exits.exits if isinstance(face, Completed)]
    halted = [face for face in exits.exits if isinstance(face, Halted)]
    assert completed and halted, exits.exits
    assert all("TermValue(value=2)" in repr(face.value) for face in completed)
    assert all(isinstance(face.effect, UndeterminedRaiseEffect) for face in halted)
    assert all(face.owed for face in exits.exits)
    assert len(owed_calls(exits)) == 1


def test_a_symbolic_actual_to_a_base_exception_law_class_is_stored_as_args(
    tmp_path,
) -> None:
    from sugar_lift_py_tests.floor import StringValue

    value = _completed_instance(
        _exits(tmp_path, "def f(v):\n    return ValueError(v, 'b')\n")
    )
    assert value.builtin_exception_class.name == "ValueError"
    assert len(value.constructed_args.elements) == 2
    assert value.constructed_args.elements[1] == StringValue("b")


def test_a_symbolic_message_alone_to_os_error_is_stored_as_args(tmp_path) -> None:
    # ``OSError(m)``: one actual is never parsed (``oserror_parse_args``
    # reads 2 to 5), so the class is ``OSError`` and ``args`` is ``(m,)``.
    value = _completed_instance(
        _exits(tmp_path, "def f(m):\n    return OSError(m)\n")
    )
    assert value.builtin_exception_class.name == "OSError"
    assert len(value.constructed_args.elements) == 1


# -- the bodiless ``.args`` read: what the construction stored --------------


def _bodiless_exception_call(class_name, *, keyword_names=(), constructed_args=None):
    """A bodiless call of the builtin exception class ``class_name``, as the
    call site applies it: its binding's class, its raised type's coordinate,
    three positional actuals (the last ones keywords when ``keyword_names``),
    and the ``args`` its construction stored, if any."""
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
        constructed_args=constructed_args,
    )


def test_the_args_read_is_what_the_construction_stored() -> None:
    from sugar_lift_py_tests.floor import StringValue, TupleValue

    stored = TupleValue((StringValue("a"), StringValue("b")))
    call = _bodiless_exception_call("OSError", constructed_args=stored)
    (face,) = call.attribute("args", None, None).exits
    assert isinstance(face, Completed)
    assert face.value == stored


@pytest.mark.parametrize(
    "class_name",
    ["ValueError", "OSError", "FileNotFoundError", "SyntaxError", "IndentationError"],
)
def test_a_call_whose_construction_stored_no_args_never_reads_the_actuals(
    class_name,
) -> None:
    # ``OSError('a', 'b', 'c').args == ('a', 'b')``: ``.args`` is never read
    # from the actuals at the attribute; with nothing stored it is refused by
    # name.
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(SugarNotWritten):
        _bodiless_exception_call(class_name).attribute("args", None, None)


def test_a_call_with_a_keyword_never_reads_the_actuals_as_args() -> None:
    from sugar_source_tree.panic import SugarNotWritten

    call = _bodiless_exception_call("ImportError", keyword_names=("name",))
    with pytest.raises(SugarNotWritten):
        call.attribute("args", None, None)
