"""An undecided ``if`` whose two suites each hold an operation on a formal.

``return -x`` and ``return ~x`` over a formal ``x`` were deferred carriers
once, and with BOTH suites deferred the join had to wait for both
discharges.  No operation on a formal waits on a caller any more (#7757
NEW-1): each suite's operation is the undecided two faces, owed, its halt
kept, so the ``if`` joins the two suites by the ordinary union -- each
suite's faces under its own polarity, neither suite decided early and no
halt dropped.
"""

from __future__ import annotations

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile

HELPER = (
    "import textwrap\n"
    "def helper(x):\n"
    "    if textwrap.dedent('a'):\n"
    "        return -x\n"
    "    else:\n"
    "        return ~x\n"
)


def _helper_outcome(source: str):
    """The helper lifted on its own, its own proof."""
    tree = SourceFile(
        (source, "if-both-deferred.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function.sugar().desugar(None)


def _undetermined_owners(outcome) -> set[str]:
    return {
        face.effect.producer_node_owner
        for face in outcome.exits
        if isinstance(face, Halted) and type(face.effect) is UndeterminedRaiseEffect
    }


def test_both_suites_on_a_formal_lift_with_no_carrier() -> None:
    outcome = _helper_outcome(HELPER)
    assert not isinstance(outcome, NativeOperationExitCarrierV1), type(outcome)
    assert isinstance(outcome, ExitSet), type(outcome)
    assert any(isinstance(face, Completed) for face in outcome.exits), outcome


def test_each_suite_keeps_its_undecided_operation_halt() -> None:
    """Both suites stay reachable: the ``-x`` halt and the ``~x`` halt both
    stand, beside the ``if`` test's own truth halt and the unknown callee's.
    None is dropped for the other."""
    owners = _undetermined_owners(_helper_outcome(HELPER))
    assert {
        "SymbolicValue.unary_minus",
        "SymbolicValue.bitwise_invert",
        "IfSugar.test",
    } <= owners, owners


def test_neither_suite_folds_a_value_it_has_no_actual_for() -> None:
    """No caller's actual is supplied here, so no suite completes with a
    folded ``int``: each return is the undecided ``py.unary_neg`` /
    ``py.unary_invert``."""
    text = repr(_helper_outcome(HELPER))
    assert "py.unary_neg" in text and "py.unary_invert" in text
    assert "python:unary_neg.completes" in text
    assert "python:unary_invert.completes" in text
