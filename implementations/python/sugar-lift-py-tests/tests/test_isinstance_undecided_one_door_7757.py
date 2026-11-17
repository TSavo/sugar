"""Every isinstance / issubclass over an undecided operand is the one
undecided type test, its halt kept (#7757).

``isinstance(x, list | str | int | tuple | set)`` (and each plain form) over
a value whose type nothing decides took the builtin type law's open branch
(``FloorValue.python_isinstance``): a halt-free completion with
``adt.is_python_type``.  That dropped a real halt: ``type(x)`` need not be a
subclass, and then ``object_isinstance`` (Objects/abstract.c) asks ``x`` for
its ``__class__``, which a property or a ``__getattribute__`` of its type may
answer by raising (``Boom`` below raises ``RuntimeError`` from
``isinstance(Boom(), list)``).  The open branch is now
``floor_value.undecided_type_test``: ``python:isinstance_result(...)`` under
``python:isinstance_op.completes``, an undetermined raise under the
complement, both owed.  A floor that knows its value's type still decides
(a ``str`` is not a ``list``).

The prove twins go through ``run_source_through_real_solver`` (real ``sugar
mint`` then real ``sugar prove``): a handler around the type test is reached
in Python, so ``raises_boom(Boom()) == True`` is the truth and ``== False``
the lie.  With the halt dropped, the handler was unreachable: the lie read
``sat`` and the truth ``unsat``.  A lying claim is never ``sat``; a truthful
one is never ``unsat``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import (
    BlockValue,
    BuiltinDictClassValue,
    BuiltinSemanticCallable,
    ClassValue,
    SymbolicValue,
)
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.ir import ctor, make_var, str_const
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

_UNION = ("list", "str", "int", "tuple", "set")

_SOURCE = (
    "class Boom:\n"
    "    @property\n"
    "    def __class__(self):\n"
    "        raise RuntimeError('boom')\n"
    "\n"
    "\n"
    "def raises_boom(x):\n"
    "    try:\n"
    "        isinstance(x, {classinfo})\n"
    "    except RuntimeError:\n"
    "        return True\n"
    "    return False\n"
    "\n"
    "\n"
    "def test_type():\n"
    "    assert {claim}\n"
)

# ``isinstance(Boom(), <classinfo>)`` raises ``RuntimeError``: ``Boom`` is no
# subclass of any of them, so ``Boom().__class__`` is read, and it raises.
_CLASSINFOS = {
    "list": "list",
    "str": "str",
    "int": "int",
    "tuple": "tuple",
    "set": "set",
    "dict": "dict",
    "tuple-of-types": "(list, str)",
    "pep604-union": "list | str | int | tuple | set",
}

_HALVES = {
    "truthful": "raises_boom(Boom()) == True",
    "lying": "raises_boom(Boom()) == False",
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows every helper."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", sorted(_HALVES))
@pytest.mark.parametrize("classinfo", sorted(_CLASSINFOS))
def test_a_type_test_halt_is_never_dropped(
    tmp_path: Path, classinfo: str, half: str
) -> None:
    text = _SOURCE.format(classinfo=_CLASSINFOS[classinfo], claim=_HALVES[half])
    result = run_source_through_real_solver(tmp_path / f"{classinfo}-{half}", text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc


def _builtin(name: str):
    """The builtin class ``name`` as the builtin namespace binds it: ``dict``
    its own class value, ``tuple`` / ``set`` their constructor callables,
    every other one a ``ClassValue``."""
    if name == "dict":
        return BuiltinDictClassValue(operation="python.dict.construct")
    if name in ("tuple", "set"):
        return BuiltinSemanticCallable(operation=f"python.{name}.construct")
    return ClassValue(name=name, bases=(), record=BlockValue(()))


def _isinstance_halts(outcome):
    return tuple(
        halt
        for halt in outcome.halts()
        if isinstance(halt.effect, UndeterminedRaiseEffect)
        and halt.effect.producer_node_owner == "FloorValue.python_isinstance"
    )


@pytest.mark.parametrize("name", (*_UNION, "dict"))
def test_each_builtin_type_test_over_an_undecided_value_keeps_its_halt(
    name: str,
) -> None:
    outcome = _builtin(name).test_python_type(
        SymbolicValue(make_var("x")), f"isinstance-{name}"
    )

    assert outcome.completed_value() is None, outcome
    (completed,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert "python:isinstance_op.completes" in repr(completed.guard)
    assert completed.value.term.name == "python:isinstance_result"
    assert completed.value.term.args[0] == ctor("python:type", [str_const(name)])
    (halt,) = _isinstance_halts(outcome)
    assert halt.guard != completed.guard
    assert "adt.is_python_type" not in repr(outcome)
    for arm in outcome.exits:
        assert arm.owed, arm


def test_the_union_keeps_a_halt_face_for_each_builtin_in_it() -> None:
    """``isinstance(x, list | str | int | tuple | set)``: one undecided type
    test per arm of the union, each with its own halt face."""
    union = ctor("python:type", [str_const(_UNION[0])])
    for name in _UNION[1:]:
        union = ctor("|", [union, ctor("python:type", [str_const(name)])])

    outcome = SymbolicValue(union).test_python_type(
        SymbolicValue(make_var("x")), "isinstance-union"
    )

    halts = _isinstance_halts(outcome)
    assert halts, outcome
    # A builtin's test reaches a halt guard only through its own completes
    # atom: a halt-free arm (the dropped halt) would name it in none.
    for name in _UNION:
        type_term = repr(ctor("python:type", [str_const(name)]))
        assert any(type_term in repr(halt.guard) for halt in halts), name
    assert "adt.is_python_type" not in repr(outcome)
    assert any(isinstance(arm, Completed) for arm in outcome.exits), outcome


def test_issubclass_of_an_undecided_operand_keeps_its_halt() -> None:
    outcome = SymbolicValue(make_var("t")).test_python_subtype(
        _builtin("int"), "issubclass-undecided"
    )

    assert outcome.completed_value() is None, outcome
    (completed,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert "python:issubclass_op.completes" in repr(completed.guard)
    assert "python:issubclass_result" in repr(completed.value)
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect), halt
    assert "python.subtype" not in repr(outcome)


@pytest.mark.parametrize("name", _UNION)
def test_a_value_whose_floor_knows_its_type_still_decides(name: str) -> None:
    outcome = _builtin(name).test_python_type(StringValue("s"), f"isinstance-{name}")

    assert outcome.halts() == (), outcome
    expected = TrueBoolLiteralSugar if name == "str" else FalseBoolLiteralSugar
    assert type(outcome.completed_value()) is expected, outcome
