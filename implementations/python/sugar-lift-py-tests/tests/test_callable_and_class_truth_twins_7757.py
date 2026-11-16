"""A function's or a class's truth is decided, never a construction panic
(#7757, audit 7 row H12).

``LambdaCallable`` (a lambda, or the function a ``def`` builds),
``BoundMethodValue`` and ``ClassDefinitionValue`` defined no ``truth``, so
``if f:``, ``f or g`` and ``if Cls:`` fell to ``FloorValue.truth``: a
construction panic.  Python decides them:

- a function or a bound method is ``True``: its type binds neither
  ``__bool__`` nor ``__len__``;
- a class is ``True`` where its metaclass is decided to be ``type``
  (``ClassDefinitionValue._metaclass_is_type``); otherwise the metaclass may
  bind ``__bool__`` or ``__len__``, so the truth is the one undecided truth,
  both faces owed.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each
half goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.bound_method_value import BoundMethodValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.floor.lambda_callable import LambdaCallable
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile

_SOURCE = (
    "class Falsy(type):\n"
    "    def __bool__(cls):\n"
    "        return False\n"
    "\n"
    "\n"
    "class Plain:\n"
    "    pass\n"
    "\n"
    "\n"
    "class Empty(metaclass=Falsy):\n"
    "    pass\n"
    "\n"
    "\n"
    "def one():\n"
    "    return 1\n"
    "\n"
    "\n"
    "def two():\n"
    "    return 2\n"
    "\n"
    "\n"
    "def if_function():\n"
    "    if one:\n"
    "        return 1\n"
    "    return 0\n"
    "\n"
    "\n"
    "def if_lambda():\n"
    "    k = lambda: 3\n"
    "    if k:\n"
    "        return 1\n"
    "    return 0\n"
    "\n"
    "\n"
    "def or_function():\n"
    "    picked = one or two\n"
    "    return picked()\n"
    "\n"
    "\n"
    "def not_function():\n"
    "    return not one\n"
    "\n"
    "\n"
    "def if_class():\n"
    "    if Plain:\n"
    "        return 1\n"
    "    return 0\n"
    "\n"
    "\n"
    "def if_falsy_metaclass():\n"
    "    if Empty:\n"
    "        return 1\n"
    "    return 0\n"
    "\n"
    "\n"
    "def test_truth():\n"
    "    assert {claim}\n"
)

# ``name: (claim, half)``.
_CASES = {
    # A function is truthy: ``if one:`` takes the body.
    "if-function-truthful": ("if_function() == 1", "truthful"),
    "if-function-lying": ("if_function() == 0", "lying"),
    # A lambda is a function.
    "if-lambda-truthful": ("if_lambda() == 1", "truthful"),
    "if-lambda-lying": ("if_lambda() == 0", "lying"),
    # ``one or two`` is ``one``: its call returns 1.
    "or-function-truthful": ("or_function() == 1", "truthful"),
    "or-function-lying": ("or_function() == 2", "lying"),
    # ``not one`` is ``False``.
    "not-function-truthful": ("not_function() == False", "truthful"),
    "not-function-lying": ("not_function() == True", "lying"),
    # A class whose metaclass is ``type`` is truthy.
    "if-class-truthful": ("if_class() == 1", "truthful"),
    "if-class-lying": ("if_class() == 0", "lying"),
    # ``Falsy.__bool__`` returns False: ``if Empty:`` skips the body.  The
    # lift does not read the metaclass, so the truth is owed; the lie that
    # the class is truthy must never read ``sat``.
    "if-falsy-metaclass-truthful": ("if_falsy_metaclass() == 0", "truthful"),
    "if-falsy-metaclass-lying": ("if_falsy_metaclass() == 1", "lying"),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows every helper."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("case", sorted(_CASES))
def test_callable_and_class_truth_never_refutes_a_truth_nor_admits_a_lie(
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


def _function() -> LambdaCallable:
    return LambdaCallable(parameters=(), body=None, construction_identity="one")


def _is_decided_true(outcome) -> None:
    assert outcome.halts() == (), outcome
    assert type(outcome.completed_value()) is TrueBoolLiteralSugar, outcome


def test_a_function_s_truth_is_decided_true() -> None:
    _is_decided_true(_function().truth("if-function"))


def test_a_bound_method_s_truth_is_decided_true() -> None:
    method = BoundMethodValue(receiver=None, name="m", member=_function())

    _is_decided_true(method.truth("if-method"))


def _classes(source: str) -> dict:
    tree = SourceFile(
        (source, "class_truth.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    return {node.name: node for node in tree.root.body if isinstance(node, ClassDef)}


def _class_value(statement: ClassDef) -> ClassDefinitionValue:
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


_CLASSES = (
    "class Falsy(type):\n"
    "    def __bool__(cls):\n"
    "        return False\n"
    "\n"
    "\n"
    "class Plain:\n"
    "    pass\n"
    "\n"
    "\n"
    "class Empty(metaclass=Falsy):\n"
    "    pass\n"
)


def test_a_class_of_metaclass_type_is_decided_true() -> None:
    plain = _class_value(_classes(_CLASSES)["Plain"])

    _is_decided_true(plain.truth("if-class"))


def test_a_class_whose_metaclass_is_not_decided_is_the_undecided_truth() -> None:
    """Two faces, both owed: never ``True`` assumed, never a panic."""
    empty = _class_value(_classes(_CLASSES)["Empty"])

    outcome = empty.truth("if-falsy-metaclass")

    completed = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert len(completed) == 1, outcome
    assert "python:truth.completes" in repr(completed[0].guard)
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect), halt
    assert halt.effect.producer_node_owner == "ClassDefinitionValue.truth"
    for arm in outcome.exits:
        assert arm.owed, arm
