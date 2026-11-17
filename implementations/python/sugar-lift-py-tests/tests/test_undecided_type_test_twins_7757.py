"""A type test nothing decides is the undecided type test, never a refusal
(#7757).

The pandas 3.0.3 / numpy 2.5.1 lane (main 13e3413ad) refused 137 functions
by the owner ``FloorValue.test_python_type`` (pandas 107, numpy 30):

- ``isinstance(x, dict)`` (pandas 66, numpy 10): ``dict`` is
  ``BuiltinDictClassValue``, which had no type test;
- ``isinstance(x, C)`` for a source class ``C`` whose metaclass is not
  decided to be ``type`` (pandas 41, numpy 20): a base the lifter does not
  read (``np.ndarray``, ``pd.DataFrame``, a numba type) or a ``metaclass=``
  keyword.

Each is decided where the value's own floor knows its type, else it is the
undecided type test (``floor_value.undecided_type_test``):
``python:isinstance_result(<classinfo>, <value>, <key>)`` completing under
``python:isinstance_op.completes``, an undetermined raise under the
complement (``type(x).__class__`` or a metaclass's ``__instancecheck__``
may raise), both owed.  A class of undecided metaclass is never the term
``python:isinstance(<x>, "<C>")`` prove's isinstance law answers off ``C``'s
order: its ``__instancecheck__`` need not agree.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  The
prove twins go through ``run_source_through_real_solver``: real ``sugar
mint`` then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import BuiltinDictClassValue, SymbolicValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile

_SOURCE = (
    "class Refuses(type):\n"
    "    def __instancecheck__(cls, obj):\n"
    "        return False\n"
    "\n"
    "\n"
    "class Never(metaclass=Refuses):\n"
    "    pass\n"
    "\n"
    "\n"
    "def is_never(x):\n"
    "    return isinstance(x, Never)\n"
    "\n"
    "\n"
    "def is_dict(x):\n"
    "    return isinstance(x, dict)\n"
    "\n"
    "\n"
    "def test_type():\n"
    "    assert {claim}\n"
)

# ``name: (claim, half)``.
_CASES = {
    # ``type(1)`` is not ``Never``, so ``Refuses.__instancecheck__`` answers.
    "metaclass-truthful": ("is_never(1) == False", "truthful"),
    "metaclass-lying": ("is_never(1) == True", "lying"),
    # ``type({})`` is ``dict``.
    "dict-truthful": ("is_dict({}) == True", "truthful"),
    "dict-lying": ("is_dict({}) == False", "lying"),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows every helper."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("case", sorted(_CASES))
def test_an_undecided_type_test_never_refutes_a_truth_nor_admits_a_lie(
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


def _never() -> ClassDefinitionValue:
    source = _SOURCE.format(claim="True")
    tree = SourceFile(
        (source, "type_test.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (statement,) = (
        node
        for node in tree.root.body
        if isinstance(node, ClassDef) and node.name == "Never"
    )
    span = statement.binding_target.line_col_span()
    return ClassDefinitionValue(
        class_name=statement.name,
        class_definition_cid=statement.fragment.seal().cid,
        methods=(),
        initializer=None,
        binding_target_occurrence=SourceFragmentCoordinateV1(
            statement.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        ),
        class_definition=statement,
    )


def _dict() -> BuiltinDictClassValue:
    return BuiltinDictClassValue(operation="python.dict.construct")


def _assert_undecided_type_test(outcome, owner: str) -> None:
    """Two faces, both owed: the keyed undecided result under its own atom,
    an undetermined raise under the complement."""
    completed = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert len(completed) == 1, outcome
    assert "python:isinstance_op.completes" in repr(completed[0].guard)
    assert "python:isinstance_result" in repr(completed[0].value)
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect), halt
    assert halt.effect.producer_node_owner == owner
    for arm in outcome.exits:
        assert arm.owed, arm


@pytest.mark.parametrize(
    "classinfo, owner",
    [
        (_never, "ClassDefinitionValue.test_python_type"),
        (_dict, "FloorValue.python_isinstance"),
    ],
    ids=["metaclass", "dict"],
)
def test_a_type_test_nothing_decides_is_two_faced(classinfo, owner) -> None:
    outcome = classinfo().test_python_type(
        SymbolicValue(make_var("x")), "isinstance-undecided"
    )

    _assert_undecided_type_test(outcome, owner)


@pytest.mark.parametrize("classinfo", [_never, _dict], ids=["metaclass", "dict"])
def test_an_undecided_type_test_is_never_the_law_read_term(classinfo) -> None:
    """The lie: a halt-free completion, or the term prove's isinstance law
    answers ``True`` off an order a metaclass's ``__instancecheck__`` need
    not agree with."""
    outcome = classinfo().test_python_type(
        SymbolicValue(make_var("x")), "isinstance-undecided"
    )

    assert outcome.completed_value() is None, outcome
    stated = repr(outcome)
    assert "python:isinstance.completes" not in stated
    assert "python:isinstance(" not in stated
    assert "'python:isinstance'" not in stated


def test_a_value_whose_floor_knows_its_type_decides_the_dict_test() -> None:
    outcome = _dict().test_python_type(StringValue("s"), "isinstance-str")

    assert outcome.halts() == (), outcome
    assert type(outcome.completed_value()) is FalseBoolLiteralSugar, outcome
