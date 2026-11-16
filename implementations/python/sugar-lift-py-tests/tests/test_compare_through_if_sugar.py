"""Formal ordering comparisons keep their two undecided faces through
``IfSugar``; none is a carrier (#7757, audit row NEW-1)."""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    GuardedReturn,
    TermValue,
)
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile

HELPER = (
    "def helper(left, right):\n"
    "    if left < right:\n"
    "        return 1\n"
    "    return 0\n"
)


def _tree(calls: str = "") -> SourceFile:
    source = f"{HELPER}\n{calls}"
    return SourceFile(
        (source, "compare-through-if.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _function_outcome():
    function = next(node for node in _tree().nodes() if isinstance(node, FunctionDef))
    return function.sugar().desugar(None)


def _call_outcomes(calls: str):
    return tuple(
        node.sugar().desugar(None)
        for node in _tree(calls).nodes()
        if isinstance(node, Call)
    )


def _the_call_edge(outcome: object) -> tuple[CallSiteValue, Halted]:
    """#7757 step 5 (#8705, the owner's ruling "Edge, join at prove"): a call
    of a same-file def is its coordinate and edge, never the callee's body
    applied to the actuals.  It is the one unanswered call: it completes under
    its ``python:unknown_callee_call.completes`` atom with the call's result,
    and halts under the complement with nothing named here.  Which branch
    the actuals select, and the ``TypeError`` of ``None < 2``, are stated by
    the callee's contract over its formals (its two faces below) and decided at
    prove, where the join binds the actuals.

    Desugared with no context, its completed value carries its record that
    it may reach every module global (#9108, ``bind_after_call``); the call
    is the value beneath that record."""
    from sugar_lift_py_tests.floor.call_site_value import AfterCallRecordValue
    from sugar_lift_py_tests.floor.named_expression_value import (
        peel_walrus_binds,
    )

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 2
    (completed,) = (face for face in outcome.exits if isinstance(face, Completed))
    (halted,) = outcome.halts()
    assert completed.guard.name == "python:unknown_callee_call.completes"
    binds, value = peel_walrus_binds(completed.value)
    assert any(
        isinstance(bind.assigned_value, AfterCallRecordValue)
        and bind.assigned_value.reaches_every_global()
        for bind in binds
    ), binds
    assert isinstance(value, CallSiteValue)
    assert value.body is None
    assert value.term.name == "python:call_result"
    assert type(halted.effect) is UndeterminedRaiseEffect
    assert halted.effect.exception_name is None
    return value, halted


def test_formal_ordering_condition_creates_no_carrier() -> None:
    """A parameter operand is no deferred operation (#7757, audit row
    NEW-1): ``left < right`` is the undecided ordering's two faces, one
    ``UndecidedCompare:Lt`` halt."""
    outcome = _function_outcome()

    assert isinstance(outcome, ExitSet)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UndecidedCompare:Lt"
    ]
    assert len(halts) == 1


def test_a_call_of_the_helper_is_its_coordinate_and_edge() -> None:
    """Was: the caller's actuals discharged the helper's carrier at the call
    (``helper(1, 2)`` returned 1, ``helper(2, 1)`` returned 0, ``helper(None,
    2)`` halted with ``TypeError`` and its state reached an assertion
    boundary).  That was the body-following application #8705 deleted; each
    call is now its own coordinate, the three told apart by their actuals."""
    outcomes = _call_outcomes("helper(1, 2)\nhelper(2, 1)\nhelper(None, 2)\n")

    assert len(outcomes) == 3
    terms = []
    for outcome in outcomes:
        value, _halted = _the_call_edge(outcome)
        (call_term, _occurrence) = value.term.args
        assert call_term.name.startswith("call:")
        assert len(value.arg_values) == 2
        terms.append(call_term)
    assert len(set(map(repr, terms))) == 3
    assert "TypeError" not in repr(outcomes)


def test_symbolic_if_branches_keep_complementary_guards() -> None:
    exits = _function_outcome()
    assert isinstance(exits, ExitSet)
    # ``<`` over two parameters, values not decided here, is two-faced: it
    # completes under
    # its own ``python:compare.completes`` guard, or the comparison itself
    # raises something undetermined.  Both faces are kept.
    assert len(exits.exits) == 2
    (completed,) = (face for face in exits.exits if isinstance(face, Completed))
    (halted,) = (face for face in exits.exits if isinstance(face, Halted))
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.effect.producer_node_owner.endswith(":Lt")
    assert completed.guard.name == "python:compare.completes"
    record = completed.value.record
    returns = tuple(
        value for value in record.statements if isinstance(value, GuardedReturn)
    )
    assert len(returns) == 2
    then_return, else_return = returns
    assert then_return.value == TermValue(1)
    assert else_return.value == TermValue(0)
    # Each return is guarded by the test's own condition (the completed
    # comparison's truth), never by the branch slot no input decides (#7757).
    assert "python:branch_result" not in repr(then_return.guards[0])
    assert else_return.guards[0].kind == "not"
    assert else_return.guards[0].operands[0] == then_return.guards[0]

