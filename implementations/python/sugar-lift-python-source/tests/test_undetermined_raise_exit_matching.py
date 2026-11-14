"""``__exit__`` receives an undetermined body raise like any other raise.

A may-raise operation in a ``with`` body (a C call, an unprojected source
call) halts with an ``UndeterminedRaiseEffect`` that carries the one exception
object it threw, ``UndeterminedExceptionValue`` (#7590). Python hands that
exception to ``__exit__`` as ``(type(e), e, tb)``. Source-constructed exits
refused it (``ManagerProtocol.exit_outcome_for_body``), and managers whose
exit is a parametric call treated it as never suppressed -- false whenever
the exit can swallow it.

Now ``e`` is passed as itself and ``type(e)`` is
``UndeterminedExceptionTypeValue`` (``python:type_of(e)``), derived from it and
never named. The exit's own tests then split exactly as ``except`` does:
``exc_type is None`` is false, ``issubclass(type(e), BaseException)`` is true,
``issubclass(type(e), B)`` for a builtin ``B`` retains the same
``adt.is_python_type(e, B)`` atom ``except B`` retains, and the exit's return
truth decides suppression.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.undetermined_exception_value import (
    UndeterminedExceptionTypeValue,
    UndeterminedExceptionValue,
)
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_lift_py_tests.outcome.resource_bindings import ExitFaceBinding

from test_undetermined_raise_except_matching import (
    C_CALL,
    SOURCE_CALL,
    _exits,
    _handler,
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


def _returns_seven(exits):
    """Completed faces of f whose record returns 7 (the With's continuation)."""
    rows = []
    for face in exits.exits:
        if not isinstance(face, Completed):
            continue
        record = getattr(face.value, "record", None)
        statements = getattr(record, "statements", ())
        if any("TermValue(value=7)" in repr(s) for s in statements if type(s).__name__ == "ReturnValue"):
            rows.append(face)
    return rows


@_OPERATIONS
def test_suppress_named_class_splits_on_the_raised_exception(
    tmp_path, prelude, operation, producer
) -> None:
    exits = _exits(tmp_path, _with(prelude, "contextlib.suppress(ValueError)", operation))
    head, producer_text = _subject(producer)
    handler = _handler("ValueError")
    suppressed = [
        face for face in _returns_seven(exits)
        if producer_text in repr(face.guard) and head in repr(face.guard)
    ]
    (face,) = suppressed
    assert handler in repr(face.guard)
    assert "kind='not', operands=(" + head not in repr(face.guard)
    (escaping,) = _undetermined_halts(exits, producer)
    assert "kind='not', operands=(" + head in escaping[2]
    assert handler in escaping[2]


@_OPERATIONS
def test_suppress_base_exception_is_total(tmp_path, prelude, operation, producer) -> None:
    exits = _exits(tmp_path, _with(prelude, "contextlib.suppress(BaseException)", operation))
    assert _undetermined_halts(exits, producer) == []
    assert not [f for f in exits.exits if isinstance(f, Halted)]
    # The operation completes or its exception is swallowed: both return 7.
    assert len(_returns_seven(exits)) == 2
    # Nothing is split: no face's guard tests the exception's class.
    assert all("adt.is_python_type" not in repr(f.guard) for f in exits.exits)


def test_suppress_tuple_is_a_disjunction(tmp_path) -> None:
    prelude, operation, producer = SOURCE_CALL
    exits = _exits(
        tmp_path, _with(prelude, "contextlib.suppress(KeyError, ValueError)", operation)
    )
    head, producer_text = _subject(producer)
    (face,) = [f for f in _returns_seven(exits) if head in repr(f.guard)]
    assert "kind='or'" in repr(face.guard)
    assert _handler("KeyError") in repr(face.guard)
    assert _handler("ValueError") in repr(face.guard)
    assert len(_undetermined_halts(exits, producer)) == 1


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
def test_source_exit_catching_by_type_splits(tmp_path, prelude, operation, producer) -> None:
    exits = _exits(tmp_path, _with(prelude + _CATCHING_MANAGER, "M()", operation))
    head, producer_text = _subject(producer)
    handler = _handler("KeyError")
    (face,) = [f for f in _returns_seven(exits) if head in repr(f.guard)]
    assert handler in repr(face.guard) and producer_text in repr(face.guard)
    (escaping,) = _undetermined_halts(exits, producer)
    assert "kind='not', operands=(" in escaping[2] and handler in escaping[2]


@_OPERATIONS
def test_never_suppressing_source_exit_reraises(tmp_path, prelude, operation, producer) -> None:
    manager = (
        "class M:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, t, v, tb):\n"
        "        return False\n"
    )
    exits = _exits(tmp_path, _with(prelude + manager, "M()", operation))
    (escaping,) = _undetermined_halts(exits, producer)
    head, _ = _subject(producer)
    assert head not in escaping[2]
    # Only the completed operation reaches the tail; nothing is swallowed.
    assert all(head not in repr(f.guard) for f in _returns_seven(exits))
    assert len(_returns_seven(exits)) == 1


def test_exit_receives_the_exception_itself(tmp_path) -> None:
    prelude, operation, producer = SOURCE_CALL
    manager = (
        "class M:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, t, v, tb):\n"
        "        if isinstance(v, KeyError):\n"
        "            return True\n"
        "        return False\n"
    )
    exits = _exits(tmp_path, _with(prelude + manager, "M()", operation))
    head, producer_text = _subject(producer)
    (face,) = [f for f in _returns_seven(exits) if head in repr(f.guard)]
    assert _handler("KeyError") in repr(face.guard)
    assert len(_undetermined_halts(exits, producer)) == 1


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
    assert exc_type.is_identical(NoneValue(), None).value.formula == false_guard()
    assert type(
        exc_type.test_python_subtype(builtin("BaseException"), None).value
    ) is TrueBoolLiteralSugar
    retained = exc_type.test_python_subtype(builtin("ValueError"), None).value
    assert type(retained) is PredicateValue
    assert retained.formula.name == "adt.is_python_type"
    assert retained.formula.args[0] == exception.to_term(owner="t")
    with pytest.raises(ConstructionPanic):
        exc_type.is_identical(builtin("ValueError"), None)
    with pytest.raises(ConstructionPanic):
        exc_type.equals(builtin("ValueError"), None, None)


def test_exit_face_binding_names_the_exception_and_its_type() -> None:
    effect = UndeterminedRaiseEffect(
        occurrence="e.py:3:8", producer_node_owner="UnprojectedSourceCall:m.g"
    )
    binding = ExitFaceBinding.from_body_exit("X", Halted(None, effect))
    assert binding.kind == "undetermined"
    rows = repr([fact.formula for fact in binding.to_facts()])
    assert "python:type_of" in rows
    assert repr(effect.exception_value.to_term(owner="t")) in rows
    assert ExitFaceBinding.from_body_exit("X", Halted(None, UndeterminedRaiseEffect())).kind == "open"
