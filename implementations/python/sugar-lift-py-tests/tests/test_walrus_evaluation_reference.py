"""``(x := e)``: a later read is a reference to the walrus's one evaluation.

Temporal choice 1 (#7661), as #7886 did for ``x += e``: substitution rewrites
a read of ``x`` after ``(x := e)`` to ``EvaluationRef(<the walrus's evaluation
key>)``; ``NamedExpressionValue`` binds the assigned value under that key.

Two hazards are pinned here:

1. A walrus in an ``if`` condition binds its key into the context both suites
   start from.  The join measures what the arms bound against the context
   before the condition, so the key is carried out of the ``if``.
2. A walrus the temporal never receives (inside a comprehension, which is
   refused at construction, or nested in an assignment's right-hand side)
   keeps the read it had: the walrus's substituted value, never a free name.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import GuardedFaces, TermValue
from sugar_lift_py_tests.floor.branch_result_coordinate import BranchResultSlot
from sugar_lift_py_tests.floor.named_expression_value import NamedExpressionValue
from sugar_lift_py_tests.outcome import outcome_to_exitset
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.if_sugar import IfSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.named_expr_sugar import NamedExprSugar
from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import EvaluationRef, FunctionDef, Return
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
# Hazard 2: a walrus the temporal never receives keeps its read
# ---------------------------------------------------------------------------


def test_read_after_a_comprehension_walrus_carries_the_walrus_value() -> None:
    rewritten = _function(
        "def f():\n"
        "    value = 7\n"
        "    [(captured := value) for x in [1]]\n"
        "    return captured\n"
    ).substitute({})
    ret = rewritten.body[-1]
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.name == "captured"
    assert ret.value.unevaluated.kind == "Constant"
    assert ret.value.unevaluated.value == 7
    sugar = ret.value.sugar()
    assert isinstance(sugar, EvaluationRefSugar)
    assert sugar.unevaluated is not None
    # The comprehension never evaluates (it is refused at construction), so
    # its key is never bound: the read is the value it was before, not free.
    ctx = _root("walrus-comprehension")
    read = _value(sugar.desugar(ctx))
    assert read is not None
    assert read == _value(sugar.unevaluated.desugar(ctx))


def test_an_unevaluated_walrus_is_read_as_its_value() -> None:
    read = EvaluationRefSugar(
        evaluation=KEY,
        name="x",
        site=None,
        unevaluated=IntLiteralSugar(7, site=SITE),
    )
    ctx = _root()
    seven = _value(IntLiteralSugar(7, site=SITE).desugar(ctx))
    assert seven is not None
    assert _value(read.desugar(ctx)) == seven


def test_an_unevaluated_walrus_never_reads_an_older_write_of_the_name() -> None:
    # `x += 1; y = (x := 7); return x`: the augmented assignment wrote the
    # name; the nested walrus never reached the temporal.
    read = EvaluationRefSugar(
        evaluation=KEY,
        name="x",
        site=None,
        unevaluated=IntLiteralSugar(7, site=SITE),
    )
    ctx = _root()
    ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(1)))
    read_value = _value(read.desugar(ctx))
    assert read_value != TermValue(1)
    assert read_value == _value(IntLiteralSugar(7, site=SITE).desugar(ctx))


def test_an_evaluated_walrus_is_read_from_its_key() -> None:
    read = EvaluationRefSugar(
        evaluation=KEY,
        name="x",
        site=None,
        unevaluated=IntLiteralSugar(7, site=SITE),
    )
    ctx = _root()
    ctx = ctx.with_temporal(ctx.temporal.bind_value(KEY, TermValue(9)))
    assert _value(read.desugar(ctx)) == TermValue(9)


def test_a_write_of_the_name_after_the_walrus_is_read() -> None:
    read = EvaluationRefSugar(
        evaluation=KEY,
        name="x",
        site=None,
        unevaluated=IntLiteralSugar(7, site=SITE),
    )
    ctx = _root()
    ctx = ctx.with_temporal(ctx.temporal.bind_value(KEY, TermValue(9)))
    ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(3)))
    assert _value(read.desugar(ctx)) == TermValue(3)
