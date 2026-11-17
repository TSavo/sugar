"""A decided value answers isinstance from its type's real order, and an
undecided classinfo is the two-faced undecided type test (#7757).

1. **The lie on decided values.**  ``StringValue``, ``BytesValue``,
   ``ComplexValue``, ``TermValue`` and ``EllipsisValue`` answered ``False``
   for every classinfo but their own type, ``object`` and their real bases
   included: ``isinstance("a", object)`` was decided ``False`` (Python:
   ``True``) and ``isinstance(True, int)`` ``False`` (Python: ``True``).
   Every floor that knows its value's builtin type now answers from the one
   table of builtin orders (``python_type_coordinate.BUILTIN_TYPE_ORDER``):
   ``True`` for every class in the order, ``False`` only for a builtin class
   of metaclass ``type`` provably not in it, and the undecided type test,
   its halt kept, for anything else.

2. **Halt-only classinfo.**  A classinfo nothing decides -- a formal
   (``SymbolicValue.test_python_type``) or an uncited call's result
   (``CallSiteValue.test_python_type``) -- halted with no completion face
   (``DynamicTypeOperandRuntimeEffect`` / ``CallResultTypeRuntimeEffect``).
   ``isinstance(x, str)`` with ``str`` passed in completes in Python, so the
   halt-only outcome refuted that truth.  It is now the undecided type test:
   completes owed, its halt kept.

The prove halves go through ``run_source_through_real_solver`` (real ``sugar
mint`` then real ``sugar prove``).  A lying claim is never ``sat``; a
truthful one is never ``unsat``.  ``isinstance("a", object) == True`` is
decided, so its truthful half is ``sat`` and its lying half ``unsat``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import (
    BlockValue,
    BytesValue,
    CallSiteValue,
    ClassValue,
    ComplexValue,
    EllipsisValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.floor_value import undecided_type_test
from sugar_lift_py_tests.floor.predicate_value import PredicateValue
from sugar_lift_py_tests.ir import ctor, make_var, str_const
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

# -- prove halves -------------------------------------------------------------

_SOURCE = (
    "def pick():\n"
    "    return str\n"
    "\n"
    "\n"
    "def completes_formal(x, t):\n"
    "    isinstance(x, t)\n"
    "    return True\n"
    "\n"
    "\n"
    "def completes_call(x):\n"
    "    isinstance(x, pick())\n"
    "    return True\n"
    "\n"
    "\n"
    "def test_type():\n"
    "    assert {claim}\n"
)

# ``name: (claim, half)``: the decided twins of the lie (1).
_DECIDED = {
    "str-object-truthful": ('isinstance("a", object) == True', "truthful"),
    "str-object-lying": ('isinstance("a", object) == False', "lying"),
}

# ``name: (claim, half)``: never sat when lying, never unsat when truthful.
_CASES = {
    **_DECIDED,
    "bytes-object-truthful": ('isinstance(b"a", object) == True', "truthful"),
    "bytes-object-lying": ('isinstance(b"a", object) == False', "lying"),
    "complex-object-truthful": ("isinstance(1j, object) == True", "truthful"),
    "complex-object-lying": ("isinstance(1j, object) == False", "lying"),
    "ellipsis-object-truthful": ("isinstance(..., object) == True", "truthful"),
    "ellipsis-object-lying": ("isinstance(..., object) == False", "lying"),
    "int-object-truthful": ("isinstance(1, object) == True", "truthful"),
    "int-object-lying": ("isinstance(1, object) == False", "lying"),
    "float-object-truthful": ("isinstance(1.5, object) == True", "truthful"),
    "float-object-lying": ("isinstance(1.5, object) == False", "lying"),
    "str-int-truthful": ('isinstance("a", int) == False', "truthful"),
    "str-int-lying": ('isinstance("a", int) == True', "lying"),
    # (2): ``isinstance("a", str)`` completes in Python, whatever classinfo
    # nothing in the helper decides.
    "formal-classinfo-truthful": ('completes_formal("a", str) == True', "truthful"),
    "formal-classinfo-lying": ('completes_formal("a", str) == False', "lying"),
    "call-classinfo-truthful": ('completes_call("a") == True', "truthful"),
    "call-classinfo-lying": ('completes_call("a") == False', "lying"),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows every helper."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("case", sorted(_CASES))
def test_a_type_test_never_refutes_a_truth_nor_admits_a_lie(
    tmp_path: Path, case: str
) -> None:
    claim, half = _CASES[case]
    text = _SOURCE.format(claim=claim)
    result = run_source_through_real_solver(tmp_path / case, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc


@pytest.mark.parametrize("case", sorted(_DECIDED))
def test_a_str_is_decided_an_object(tmp_path: Path, case: str) -> None:
    """``isinstance("a", object)`` is decided ``True``: the truth ``sat``, the
    lie ``unsat``.  Before, it was decided ``False``: the lie read ``sat``."""
    claim, half = _DECIDED[case]
    text = _SOURCE.format(claim=claim)
    result = run_source_through_real_solver(tmp_path / case, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    assert verdict == ("unsat" if half == "lying" else "sat"), result.prove_doc


# -- unit halves --------------------------------------------------------------


def _type(name: str):
    return ctor("python:type", [str_const(name)])


# Each decided floor and the builtin type of the value it carries.
_DECIDED_FLOORS = {
    "str": lambda: StringValue("a"),
    "bytes": lambda: BytesValue(b"a"),
    "complex": lambda: ComplexValue(0.0, 1.0),
    "ellipsis": lambda: EllipsisValue(),
    "int": lambda: TermValue(1),
    "float": lambda: TermValue(1.5),
    "bool": lambda: TermValue(True),
    "tuple": lambda: TupleValue(()),
    "type": lambda: ClassValue(name="int", bases=(), record=BlockValue(())),
}

# The real bases of each (``type.__mro__`` by name).
_ORDERS = {
    "str": ("str", "object"),
    "bytes": ("bytes", "object"),
    "complex": ("complex", "object"),
    "ellipsis": ("ellipsis", "object"),
    "int": ("int", "object"),
    "float": ("float", "object"),
    "bool": ("bool", "int", "object"),
    "tuple": ("tuple", "object"),
    "type": ("type", "object"),
}

_BUILTIN_CLASSES = (
    "object",
    "type",
    "int",
    "bool",
    "float",
    "complex",
    "str",
    "bytes",
    "list",
    "tuple",
    "dict",
    "set",
    "frozenset",
    "NoneType",
    "ValueError",
)


@pytest.mark.parametrize("floor", sorted(_DECIDED_FLOORS))
@pytest.mark.parametrize("classinfo", _BUILTIN_CLASSES)
def test_a_decided_value_answers_from_its_real_order(
    floor: str, classinfo: str
) -> None:
    outcome = _DECIDED_FLOORS[floor]().python_isinstance(
        classinfo, _type(classinfo), f"isinstance-{floor}-{classinfo}"
    )

    assert outcome.halts() == (), outcome
    expected = (
        TrueBoolLiteralSugar if classinfo in _ORDERS[floor] else FalseBoolLiteralSugar
    )
    assert type(outcome.completed_value()) is expected, outcome


@pytest.mark.parametrize("floor", sorted(_DECIDED_FLOORS))
def test_every_decided_value_is_an_object(floor: str) -> None:
    """The lie: ``isinstance("a", object)`` decided ``False``."""
    outcome = _DECIDED_FLOORS[floor]().python_isinstance(
        "object", _type("object"), f"isinstance-{floor}-object"
    )

    assert type(outcome.completed_value()) is TrueBoolLiteralSugar, outcome


def test_a_bool_is_an_int_and_an_int_is_no_bool() -> None:
    as_int = TermValue(True).python_isinstance("int", _type("int"), "bool-int")
    as_bool = TermValue(1).python_isinstance("bool", _type("bool"), "int-bool")

    assert type(as_int.completed_value()) is TrueBoolLiteralSugar, as_int
    assert type(as_bool.completed_value()) is FalseBoolLiteralSugar, as_bool


def _assert_undecided_type_test(outcome, owner: str) -> None:
    """Two faces, both owed: the keyed undecided result under its own atom,
    an undetermined raise under the complement."""
    assert outcome.completed_value() is None, outcome
    (completed,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert "python:isinstance_op.completes" in repr(completed.guard)
    assert completed.value.term.name == "python:isinstance_result"
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect), halt
    assert halt.effect.producer_node_owner == owner
    for arm in outcome.exits:
        assert arm.owed, arm


@pytest.mark.parametrize("floor", sorted(_DECIDED_FLOORS))
@pytest.mark.parametrize("classinfo", ("len", "Sequence"))
def test_a_classinfo_the_order_does_not_decide_is_the_undecided_test(
    floor: str, classinfo: str
) -> None:
    """A builtin name that is no class (``isinstance("a", len)`` raises
    ``TypeError``) or a class outside the table (an ABC's metaclass runs its
    own ``__instancecheck__``) is never decided ``False``."""
    outcome = _DECIDED_FLOORS[floor]().python_isinstance(
        classinfo, _type(classinfo), f"isinstance-{floor}-{classinfo}"
    )

    _assert_undecided_type_test(outcome, "FloorValue.python_isinstance")


def _cited_type_call() -> CallSiteValue:
    term = ctor(
        "call:type",
        [SymbolicValue(make_var("y")).to_term(owner="type-call")],
        symbol_kind="builtin",
    )
    return CallSiteValue(
        target_name="type",
        arg_values=(SymbolicValue(make_var("y")),),
        parameters=(),
        term=term,
        body=None,
        site="type-call",
        python_type_coordinate=term,
    )


def test_type_of_a_value_is_a_type_but_never_decided_outside_its_order() -> None:
    """``type(y)`` is a class whose metaclass is undecided: ``type`` and
    ``object`` hold; against ``tuple`` a metaclass ``__class__`` may raise
    where ``object_isinstance`` reads it, so it is never decided ``False``."""
    as_type = _cited_type_call().python_isinstance("type", _type("type"), "t-type")
    as_tuple = _cited_type_call().python_isinstance("tuple", _type("tuple"), "t-tup")

    assert type(as_type.completed_value()) is TrueBoolLiteralSugar, as_type
    _assert_undecided_type_test(as_tuple, "FloorValue.python_isinstance")


def test_a_formal_classinfo_is_the_two_faced_undecided_test() -> None:
    outcome = SymbolicValue(make_var("t")).test_python_type(
        StringValue("a"), "isinstance-formal-classinfo"
    )

    _assert_undecided_type_test(outcome, "SymbolicValue.test_python_type")
    assert "adt.is_python_type" not in repr(outcome)


def test_an_uncited_call_classinfo_is_the_two_faced_undecided_test() -> None:
    pick = CallSiteValue(
        target_name="pick",
        arg_values=(),
        parameters=(),
        term=ctor("call:pick", [], symbol_kind="coordinate"),
        body=None,
        site="pick-call",
    )

    outcome = pick.test_python_type(StringValue("a"), "isinstance-call-classinfo")

    _assert_undecided_type_test(outcome, "CallSiteValue.test_python_type")
    assert "adt.is_python_type" not in repr(outcome)


def test_the_truth_of_an_undecided_type_test_owes_no_second_halt() -> None:
    """``isinstance`` returns a ``bool`` and ``bool.__bool__`` cannot raise:
    the truth of the undecided result completes, owed, with no halt face."""
    tested = undecided_type_test(
        SymbolicValue(make_var("x")),
        SymbolicValue(_type("list")),
        "isinstance-truth",
        owner="test",
    )
    (completed,) = [arm for arm in tested.exits if isinstance(arm, Completed)]

    truth = completed.value.truth("isinstance-truth-read")

    assert truth.halts() == (), truth
    assert isinstance(truth.completed_value(), PredicateValue), truth
    for arm in truth.exits:
        assert arm.owed, arm
