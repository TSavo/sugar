"""``len(x)`` over a formal (or any operand whose type is undecided) keeps
its halt face (#7757).

``BuiltinSemanticCallable._len`` answered ``len(x)`` with the operand
floor's ``length``, and ``SymbolicValue.length`` (a formal's floor) and
``CallSiteValue.length`` (a call's result) completed ``call:len(x)`` with no
halt face.  Python raises there: ``TypeError`` when the type has no
``__len__``, and ``TypeError`` / ``ValueError`` / ``OverflowError`` when
``__len__`` returns something that is not an index, is negative or is past
``sys.maxsize``.  Now ``len`` of every undecided operand is the builtin's
one unanswered call (``floor_value.unanswered_length``,
``UnknownCalleeCallV1("len")``): it completes under
``python:unknown_callee_call.completes`` and halts undetermined under the
complement, owed either way -- the form #9079 gave a source-class instance.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each
half goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.callable_application import CallableApplication
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue
from sugar_lift_py_tests.floor.builtin_semantic_callable import (
    BuiltinSemanticCallable,
)
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

_SOURCE = (
    "class Neg:\n"
    "    def __len__(self):\n"
    "        return -1\n"
    "\n"
    "\n"
    "def f(x):\n"
    "    return len(x)\n"
    "\n"
    "\n"
    "def test_len_of_formal():\n"
    "    assert {claim}\n"
)

# ``name: (claim, half)``.
_CASES = {
    # ``len('abc')`` is 3.
    "len-of-str-truthful": ("f('abc') == 3", "truthful"),
    # ``len([1, 2, 3])`` is 3.
    "len-of-list-truthful": ("f([1, 2, 3]) == 3", "truthful"),
    # ``len(5)`` raises ``TypeError``: no value is returned at all.
    "len-of-int-lying": ("f(5) == 3", "lying"),
    # ``len('ab')`` is 2.
    "len-of-short-str-lying": ("f('ab') == 3", "lying"),
    # ``Neg.__len__`` returns -1: ``len`` raises ``ValueError``.
    "len-negative-dunder-lying": ("f(Neg()) == -1", "lying"),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows ``f``."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("case", sorted(_CASES))
def test_len_of_a_formal_never_refutes_a_truth_nor_admits_a_lie(
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


def _site(tmp_path: Path):
    """The fragment of ``return len(x)`` in ``f``."""
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    path = tmp_path / "formal_len.py"
    path.write_text("def f(x):\n    return len(x)\n")
    tree = open_source_file_for_construction(path, root=tmp_path)
    function = next(tree.functions())
    return function.body[0].fragment


def _assert_len_s_unanswered_call(outcome) -> None:
    """Two faces, both owed: a completion under the unanswered call's
    ``completes`` atom and the undetermined halt under its complement."""
    completed = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert len(completed) == 1, outcome
    assert "python:unknown_callee_call.completes" in repr(completed[0].guard)
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect), halt
    assert halt.effect.producer_node_owner == "UnknownCallee:len"
    assert len(outcome.owed_items()) == 1, outcome.owed_items()
    for arm in outcome.exits:
        assert arm.owed, arm


def test_a_formal_s_length_keeps_the_halt_face(tmp_path: Path) -> None:
    site = _site(tmp_path)

    outcome = SymbolicValue(make_var("x")).length(site)

    _assert_len_s_unanswered_call(outcome)


def test_a_call_result_s_length_keeps_the_halt_face(tmp_path: Path) -> None:
    site = _site(tmp_path)
    result = CallSiteValue("g", (), (), ctor("call:g", []), None)

    outcome = result.length(site)

    _assert_len_s_unanswered_call(outcome)


def test_the_len_builtin_over_a_formal_keeps_the_halt_face(tmp_path: Path) -> None:
    """The path ``CallSiteSugar`` takes for ``len(x)``: the builtin's
    binding applies ``BuiltinSemanticCallable._len`` to the formal."""
    site = _site(tmp_path)
    builtin = BuiltinSemanticCallable(operation="python.len")

    outcome = builtin.callable_application_with(
        CallableApplication((SymbolicValue(make_var("x")),), (), site), None
    )

    _assert_len_s_unanswered_call(outcome)
