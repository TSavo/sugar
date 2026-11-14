"""``(x := e)``: a later read is a reference to the walrus's one evaluation.

Temporal choice 1 (#7661), as #7886 did for ``x += e``: substitution rewrites
a read of ``x`` after ``(x := e)`` to ``EvaluationRef(<the walrus's evaluation
key>)``; ``NamedExpressionValue`` binds the assigned value under that key.

Two hazards are pinned here:

1. A walrus in an ``if`` condition binds its key into the context both suites
   start from.  The join measures what the arms bound against the context
   before the condition, so the key is carried out of the ``if``.
2. A walrus nested in a larger expression (an assignment's right-hand side, a
   call's actual) carries its bind out to the enclosing statement on the
   value, and a comprehension's element writes its key per member.  A read
   resolves through the key only: where the key was never bound it is
   refused, never read as the name or as the walrus's value evaluated again.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import GuardedFaces, TermValue
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.branch_result_coordinate import BranchResultSlot
from sugar_lift_py_tests.floor.named_expression_value import (
    NamedExpressionValue,
    bind_walrus_binds,
    carrying_walrus_binds,
    peel_walrus_binds,
)
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Completed, ExitSet, outcome_to_exitset
from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar
from sugar_lift_py_tests.sugar.comprehension_sugar import ComprehensionSugar
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.if_sugar import IfSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.named_expr_sugar import NamedExprSugar
from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, EvaluationRef, FunctionDef, Return
from sugar_source_tree.tree import SourceFile

KEY = EVALUATION_PREFIX + "blake3-512:test-walrus-evaluation"


@dataclass(frozen=True)
class _Site:
    filename: str = "walrus_evaluation.py"
    line: int = 1
    col: int = 0

    def __str__(self) -> str:
        return f"{self.filename}:{self.line}:{self.col}"


SITE = _Site()


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "walrus_evaluation.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _walruses(node) -> list:
    return [child for child in node.walk() if child.kind == "NamedExpr"]


def _root(owner: str = "walrus-evaluation") -> ReduceContext:
    return ReduceContext.root(owner=owner)


def _value(outcome):
    """The one unconditional completed value of an outcome (#7825 reads
    ``ExitSet`` only), else None."""
    return outcome_to_exitset(outcome).completed_value()


# ---------------------------------------------------------------------------
# Substitution: the read is a reference to the walrus's evaluation
# ---------------------------------------------------------------------------


def test_read_after_walrus_references_its_evaluation() -> None:
    rewritten = _function("def f(z):\n    (x := z)\n    return x\n").substitute({})
    (walrus,) = _walruses(rewritten)
    ret = rewritten.body[-1]
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert isinstance(walrus.evaluation, str)
    assert walrus.evaluation.startswith(EVALUATION_PREFIX)
    assert ret.value.evaluation == walrus.evaluation
    assert ret.value.name == "x"


def test_walrus_sugar_carries_its_evaluation_key() -> None:
    rewritten = _function("def f(z):\n    (x := z)\n    return x\n").substitute({})
    (walrus,) = _walruses(rewritten)
    sugar = walrus.sugar()
    assert isinstance(sugar, NamedExprSugar)
    assert sugar.evaluation == walrus.evaluation


def test_each_unrolled_iteration_is_its_own_walrus_evaluation() -> None:
    rewritten = _function(
        "def f():\n    for v in [1, 2]:\n        (t := v)\n    return t\n"
    ).substitute({})
    walruses = _walruses(rewritten)
    assert len(walruses) == 2
    assert walruses[0].evaluation != walruses[1].evaluation
    ret = rewritten.body[-1]
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == walruses[1].evaluation


# ---------------------------------------------------------------------------
# Reduce: the walrus binds its value under its key
# ---------------------------------------------------------------------------


def test_walrus_value_binds_its_evaluation_and_its_name() -> None:
    value = NamedExpressionValue("x", TermValue(5), evaluation=KEY)
    ctx = value.extend_scope(_root())
    assert ctx.temporal.value_if_bound(KEY) == TermValue(5)
    assert ctx.temporal.value_if_bound("x") == TermValue(5)
    read = EvaluationRefSugar(evaluation=KEY, name="x", site=None)
    assert _value(read.desugar(ctx)) == TermValue(5)


def test_a_comparison_carries_the_walrus_evaluation() -> None:
    value = NamedExpressionValue("x", TermValue(5), evaluation=KEY)
    compared = _value(value.greater_than(TermValue(0), SITE, None))
    assert isinstance(compared, NamedExpressionValue)
    assert compared.evaluation == KEY
    ctx = compared.extend_scope(_root())
    assert ctx.temporal.value_if_bound(KEY) == TermValue(5)


# ---------------------------------------------------------------------------
# Hazard 1: a walrus in an if condition is carried out of the if
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("assigned", [5, 0])
def test_a_condition_walrus_is_carried_out_of_the_if(assigned: int) -> None:
    walrus = NamedExprSugar(
        name="n",
        value=IntLiteralSugar(assigned, site=SITE),
        site=SITE,
        evaluation=KEY,
    )
    outcome = IfSugar(
        test=walrus,
        branch_slot=BranchResultSlot(slot_id="b0"),
        then_body=(),
        else_body=(),
        site=SITE,
    ).desugar(_root("walrus-if"))
    faces = _value(outcome)
    assert isinstance(faces, GuardedFaces)
    # Measured against the context the suites started from, the condition's
    # key looked bound before the if and was dropped.
    assert [key for key, _carried in faces.evaluations] == [KEY]
    after = faces.extend_scope(_root("walrus-after-if"))
    read = EvaluationRefSugar(evaluation=KEY, name="n", site=None)
    assert _value(read.desugar(after)) is faces.evaluations[0][1]


# ---------------------------------------------------------------------------
# Hazard 2: a nested walrus's bind reaches the statement; a read resolves
# through the key only
# ---------------------------------------------------------------------------


def _returned_value(outcome):
    """The one completed return value of a reduced call."""
    assert isinstance(outcome, ExitSet), type(outcome)
    assert len(outcome.exits) == 1
    face = outcome.exits[0]
    assert isinstance(face, Completed), type(face)
    value = face.value
    force = getattr(value, "force_floor", None)
    if callable(force):
        forced = force(None, owner="walrus_evaluation_test")
        if isinstance(forced, BlockValue):
            returns = [s for s in forced.statements if isinstance(s, ReturnValue)]
            assert returns, forced.statements
            return returns[-1].value
        return forced
    record = getattr(value, "record", None)
    if record is not None:
        returns = [s for s in record.statements if isinstance(s, ReturnValue)]
        if returns:
            return returns[-1].value
    return value


def _call_outcome(source: str):
    """``source``'s last call, reduced through the production door."""
    tree = SourceFile(
        (source, "walrus_call.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def test_read_after_a_walrus_nested_in_an_assignment_is_its_value() -> None:
    # `x += 1` wrote the name; the walrus nested in `y = ...` is the later
    # write, and the read resolves through its key.
    returned = _returned_value(
        _call_outcome(
            "def f(x):\n"
            "    x += 1\n"
            "    y = (x := 5)\n"
            "    return x\n"
            "\n"
            "f(3)\n"
        )
    )
    assert returned == TermValue(5)
    assert returned != TermValue(4)


def test_read_after_a_walrus_in_a_comprehension_is_the_last_member() -> None:
    returned = _returned_value(
        _call_outcome(
            "def f():\n"
            "    [(last := v) for v in [1, 2, 3]]\n"
            "    return last\n"
            "\n"
            "f()\n"
        )
    )
    assert returned == TermValue(3)


def test_a_comprehension_with_a_walrus_constructs() -> None:
    rewritten = _function(
        "def f():\n"
        "    value = 7\n"
        "    [(captured := value) for x in [1]]\n"
        "    return captured\n"
    ).substitute({})
    (walrus,) = _walruses(rewritten)
    comprehension = next(node for node in rewritten.walk() if node.kind == "ListComp")
    assert isinstance(comprehension.sugar(), ComprehensionSugar)
    ret = rewritten.body[-1]
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.name == "captured"
    assert ret.value.evaluation == walrus.evaluation
    assert ret.value.walrus is True
    assert getattr(ret.value, "unevaluated", None) is None
    sugar = ret.value.sugar()
    assert isinstance(sugar, EvaluationRefSugar)
    assert sugar.walrus is True


def test_each_member_writes_the_walrus_key() -> None:
    rewritten = _function(
        "def f():\n    [(last := v) for v in [1, 2]]\n    return last\n"
    ).substitute({})
    (walrus,) = _walruses(rewritten)
    comprehension = next(node for node in rewritten.walk() if node.kind == "ListComp")
    carried = _value(comprehension.sugar().desugar(_root("walrus-comprehension")))
    binds, presented = peel_walrus_binds(carried)
    # One write carried out: the last member's, under the walrus's key.
    assert [(bind.name, bind.evaluation) for bind in binds] == [
        ("last", walrus.evaluation)
    ]
    assert binds[0].assigned_value == TermValue(2)
    # The comprehension's own value is the members, not the walrus wrapper.
    assert not any(
        isinstance(element, NamedExpressionValue)
        for element in presented.finite_elements
    )
    after = bind_walrus_binds(binds, _root("walrus-after-comprehension"))
    ret = rewritten.body[-1]
    assert isinstance(ret, Return)
    assert _value(ret.value.sugar().desugar(after)) == TermValue(2)


def test_a_call_carries_its_actual_walrus_to_the_result() -> None:
    walrus = NamedExpressionValue("x", TermValue(5), evaluation=KEY)
    seen = []

    def call(actual):
        seen.append(actual)
        return ExitSet.completed(TermValue(9))

    result = _value(carrying_walrus_binds(walrus, call))
    # The call consumes the value the walrus presents, once.
    assert seen == [TermValue(5)]
    binds, presented = peel_walrus_binds(result)
    assert presented == TermValue(9)
    assert [(bind.name, bind.evaluation) for bind in binds] == [("x", KEY)]
    ctx = bind_walrus_binds(binds, _root("walrus-call"))
    assert ctx.temporal.value_if_bound(KEY) == TermValue(5)


def test_an_assignment_binds_its_rhs_walrus() -> None:
    walrus = NamedExprSugar(
        name="x", value=IntLiteralSugar(5, site=SITE), site=SITE, evaluation=KEY
    )
    ctx = _root("walrus-assign")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(4)))
    statement = AssignSugar(name="y", value=walrus, site=SITE)
    (face,) = outcome_to_exitset(statement.desugar(ctx)).exits
    assert isinstance(face, Completed)
    after = face.value.context
    read = EvaluationRefSugar(evaluation=KEY, name="x", site=None, walrus=True)
    assert _value(read.desugar(after)) == TermValue(5)


def test_a_walrus_read_never_falls_back_to_the_name() -> None:
    # The key was never bound: the name's older write is not the walrus's
    # value, and the walrus's value is not evaluated again.  Refused by name.
    read = EvaluationRefSugar(evaluation=KEY, name="x", site=None, walrus=True)
    ctx = _root()
    ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(1)))
    with pytest.raises(ConstructionPanic):
        read.desugar(ctx)


def test_an_evaluated_walrus_is_read_from_its_key() -> None:
    read = EvaluationRefSugar(evaluation=KEY, name="x", site=None, walrus=True)
    ctx = _root()
    ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(1)))
    ctx = ctx.with_temporal(ctx.temporal.bind_value(KEY, TermValue(9)))
    assert _value(read.desugar(ctx)) == TermValue(9)


def test_a_write_of_the_name_after_the_walrus_is_read() -> None:
    read = EvaluationRefSugar(evaluation=KEY, name="x", site=None, walrus=True)
    ctx = _root()
    ctx = ctx.with_temporal(ctx.temporal.bind_value(KEY, TermValue(9)))
    ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(3)))
    assert _value(read.desugar(ctx)) == TermValue(3)
