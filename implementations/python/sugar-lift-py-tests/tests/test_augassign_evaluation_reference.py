"""``x += e``: a later read is a reference to the statement's one evaluation.

Temporal choice 1 (#7661): substitution rewrites a read of ``x`` after
``x += e`` to ``EvaluationRef(<the statement's evaluation key>)``, never to
the bare name; ``AugAssignSugar`` binds its completed value under that key,
and an ``if`` carries the keys its arms bound out to the phi.
"""

from __future__ import annotations

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import GuardedFaces, SymbolicValue, TermValue
from sugar_lift_py_tests.outcome import ExitSet, true_guard
from sugar_lift_py_tests.sugar.augassign_sugar import AugAssignSugar
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.if_sugar import _arm_evaluations
from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import AugAssign, EvaluationRef, FunctionDef, Return
from sugar_source_tree.tree import SourceFile

KEY = EVALUATION_PREFIX + "blake3-512:test-evaluation"


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "evaluation_reference.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _ref() -> EvaluationRefSugar:
    return EvaluationRefSugar(evaluation=KEY, name="x", site=None)


def test_read_after_augassign_references_its_evaluation() -> None:
    rewritten = _function("def f(x):\n    x += 1\n    return x\n").substitute({})
    aug, ret = rewritten.body
    assert isinstance(aug, AugAssign)
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == aug.evaluation
    assert aug.evaluation.startswith(EVALUATION_PREFIX)
    assert ret.value.name == "x"


def test_statement_sugar_carries_its_evaluation_key() -> None:
    function = _function("def f(x):\n    x += 1\n    return x\n")
    statement = function.sugar().statements[0]
    assert isinstance(statement, AugAssignSugar)
    assert isinstance(statement.evaluation, str)
    assert statement.evaluation.startswith(EVALUATION_PREFIX)


def test_each_unrolled_iteration_is_its_own_evaluation() -> None:
    rewritten = _function(
        "def f():\n    t = 0\n    for v in [1, 2]:\n        t += v\n    return t\n"
    ).substitute({})
    augs = [node for node in rewritten.body if isinstance(node, AugAssign)]
    assert len(augs) == 2
    assert augs[0].evaluation != augs[1].evaluation
    ret = rewritten.body[-1]
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == augs[1].evaluation


def test_the_same_source_gives_the_same_keys() -> None:
    source = "def f():\n    t = 0\n    for v in [1, 2]:\n        t += v\n    return t\n"
    first = [
        node.evaluation
        for node in _function(source).substitute({}).body
        if isinstance(node, AugAssign)
    ]
    second = [
        node.evaluation
        for node in _function(source).substitute({}).body
        if isinstance(node, AugAssign)
    ]
    assert first == second


def test_a_reference_reads_the_evaluation() -> None:
    ctx = ReduceContext.root(owner="evaluation-ref")
    ctx = ctx.with_temporal(ctx.temporal.bind_value(KEY, TermValue(5)))
    assert _ref().desugar(ctx) == ExitSet.completed(TermValue(5))


def test_a_later_write_of_the_name_is_read_instead() -> None:
    # A dynamic unpack rebinds the name at reduce; substitution never saw it.
    ctx = ReduceContext.root(owner="evaluation-ref")
    ctx = ctx.with_temporal(ctx.temporal.bind_value(KEY, TermValue(5)))
    ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(7)))
    assert _ref().desugar(ctx) == ExitSet.completed(TermValue(7))


def test_an_evaluation_written_after_the_name_is_read() -> None:
    ctx = ReduceContext.root(owner="evaluation-ref")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(7)))
    ctx = ctx.with_temporal(ctx.temporal.bind_value(KEY, TermValue(5)))
    assert _ref().desugar(ctx) == ExitSet.completed(TermValue(5))


def test_no_evaluation_is_the_name_read() -> None:
    outcome = _ref().desugar(ReduceContext.root(owner="evaluation-ref"))
    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), SymbolicValue)


def _arm(ctx) -> ExitSet:
    return ExitSet.completed(_ReducedBlock((), True, (), context=ctx))


def test_an_if_carries_an_arm_evaluation_out() -> None:
    base = ReduceContext.root(owner="evaluation-join")
    then = base.with_temporal(base.temporal.bind_value(KEY, TermValue(2)))
    assert _arm_evaluations((_arm(then), _arm(base)), base) == ((KEY, TermValue(2)),)


def test_an_evaluation_bound_before_the_if_is_not_carried_again() -> None:
    base = ReduceContext.root(owner="evaluation-join")
    base = base.with_temporal(base.temporal.bind_value(KEY, TermValue(2)))
    assert _arm_evaluations((_arm(base), _arm(base)), base) == ()


def test_two_values_for_one_evaluation_are_not_carried() -> None:
    base = ReduceContext.root(owner="evaluation-join")
    one = base.with_temporal(base.temporal.bind_value(KEY, TermValue(2)))
    two = base.with_temporal(base.temporal.bind_value(KEY, TermValue(3)))
    assert _arm_evaluations((_arm(one), _arm(two)), base) == ()


def test_guarded_faces_bind_the_carried_evaluations() -> None:
    faces = GuardedFaces(
        guard=true_guard(),
        entries=(),
        then_exits=False,
        else_exits=False,
        evaluations=((KEY, TermValue(2)),),
    )
    ctx = faces.extend_scope(ReduceContext.root(owner="evaluation-join"))
    assert ctx.temporal.value_if_bound(KEY) == TermValue(2)
    assert ctx.temporal.value_if_bound("x") is None
