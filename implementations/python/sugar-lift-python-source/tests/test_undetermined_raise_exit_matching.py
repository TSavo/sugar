"""``__exit__`` receives an undetermined body raise like any other raise.

A may-raise operation in a ``with`` body (a C call, an unprojected source
call) halts with an ``UndeterminedRaiseEffect`` that carries the one exception
object it threw, ``UndeterminedExceptionValue`` (#7590). Python hands that
exception to ``__exit__`` as ``(type(e), e, tb)``: ``e`` is passed as itself
and ``type(e)`` is ``UndeterminedExceptionTypeValue``
(``python:type_of(e)``), derived from it and never named.  Its own tests
split exactly as ``except`` does: ``exc_type is None`` is false,
``issubclass(type(e), BaseException)`` is true, ``issubclass(type(e), B)`` for
a builtin ``B`` retains the same ``adt.is_python_type(e, B)`` atom ``except B``
retains.

The manager is what the ``with`` head reduces to (#7757, #8280), and no
manager body is read at lift: an imported manager (``contextlib.suppress``)
is the undecided manager, and a same-file class's ``__enter__``/``__exit__``
are its dispatched calls, coordinate and edge, joined at prove (#8744).
Either way the body's undetermined halt is carried out of the ``with``: what
the exit decides about it is decided where the exit is.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.undetermined_exception_value import (
    UndeterminedExceptionTypeValue,
    UndeterminedExceptionValue,
)
from sugar_lift_py_tests.outcome import Halted
from sugar_lift_py_tests.outcome.resource_bindings import ExitFaceBinding

from test_undetermined_raise_except_matching import (
    C_CALL,
    SOURCE_CALL,
    _exits,
    _subject,
    _undetermined_halts,
)

_OPERATIONS = pytest.mark.parametrize(
    "prelude, operation, producer", [C_CALL, SOURCE_CALL], ids=["c-call", "source-call"]
)


def _with(prelude: str, manager: str, operation: str, tail: str = "return 7") -> str:
    return (
        f"import contextlib\n{prelude}def f():\n"
        f"    with {manager}:\n        {operation}\n    {tail}\n"
    )


_CATCHING_MANAGER = (
    "class M:\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, t, v, tb):\n"
    "        if t is None:\n"
    "            return False\n"
    "        if issubclass(t, KeyError):\n"
    "            return True\n"
    "        return False\n"
)


@_OPERATIONS
def test_an_undecided_managers_exit_keeps_the_body_halt(
    tmp_path, prelude, operation, producer
) -> None:
    """``contextlib.suppress`` answers from no staged proof: the undecided
    manager.  Its exit's result is opaque, so the body's undetermined halt
    leaves the ``with`` under that exit, never split on a class its body
    would test and never dropped."""
    exits = _exits(tmp_path, _with(prelude, "contextlib.suppress(ValueError)", operation))
    escaping = _undetermined_halts(exits, producer)
    assert escaping
    assert all("python:undecided_manager" in row[2] for row in escaping)
    head, _ = _subject(producer)
    assert all(head not in row[2] for row in escaping)


@_OPERATIONS
def test_a_same_file_exit_is_its_edge_and_keeps_the_body_halt(
    tmp_path, prelude, operation, producer
) -> None:
    """``M.__exit__`` tests the exception's class, but its body is not read
    at lift: the exit is the dispatched call (#8744).  The body's halt leaves
    the ``with`` once, with no class test minted over it here."""
    exits = _exits(tmp_path, _with(prelude + _CATCHING_MANAGER, "M()", operation))
    (escaping,) = _undetermined_halts(exits, producer)
    head, _ = _subject(producer)
    assert head not in escaping[2]
    assert all(head not in repr(face.guard) for face in exits.exits)


def test_exception_type_is_derived_never_named() -> None:
    from sugar_lift_py_tests.floor import BlockValue, NoneValue
    from sugar_lift_py_tests.floor.builtin_exception_class_value import (
        BuiltinExceptionClassValue,
    )
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.outcome.exit_set import false_guard
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    def builtin(name):
        return BuiltinExceptionClassValue(name, (), BlockValue(()))

    exception = UndeterminedExceptionValue("e.py:3:8", "UnprojectedSourceCall:m.g")
    exc_type = UndeterminedExceptionTypeValue(exception)
    term = repr(exc_type.to_term(owner="t"))
    assert term.startswith("_Ctor(name='python:type_of'")
    assert repr(exception.to_term(owner="t")) in term
    # Each test answers the one completed face it decides (an ExitSet).
    assert (
        exc_type.is_identical(NoneValue(), None).completed_value().formula
        == false_guard()
    )
    assert type(
        exc_type.test_python_subtype(builtin("BaseException"), None).completed_value()
    ) is TrueBoolLiteralSugar
    retained = exc_type.test_python_subtype(builtin("ValueError"), None).completed_value()
    assert type(retained) is PredicateValue
    assert retained.formula.name == "adt.is_python_type"
    assert retained.formula.args[0] == exception.to_term(owner="t")
    with pytest.raises(ConstructionPanic):
        exc_type.is_identical(builtin("ValueError"), None)
    with pytest.raises(ConstructionPanic):
        exc_type.equals(builtin("ValueError"), None, None)


def test_exit_face_binding_names_the_exception_and_its_type() -> None:
    effect = UndeterminedRaiseEffect(
        occurrence="e.py:3:8",
        producer_node_owner="UnprojectedSourceCall:m.g",
        site="e.py:3:8",
    )
    binding = ExitFaceBinding.from_body_exit("X", Halted(None, effect))
    assert binding.kind == "undetermined"
    rows = repr([fact.formula for fact in binding.to_facts()])
    assert "python:type_of" in rows
    assert repr(effect.exception_value.to_term(owner="t")) in rows
    nameless = UndeterminedRaiseEffect(site="e.py:3:8")
    assert ExitFaceBinding.from_body_exit("X", Halted(None, nameless)).kind == "open"
