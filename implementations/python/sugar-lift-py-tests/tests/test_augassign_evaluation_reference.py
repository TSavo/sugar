"""``x += e``: a later read is a reference to the statement's one evaluation.

Temporal choice 1 (#7661): substitution rewrites a read of ``x`` after
``x += e`` to ``EvaluationRef(<the statement's evaluation key>)``, never to
the bare name; the statement -- the one mutation door's in-place call
(``ContainerMutationStatement``, #7757) -- binds its in-place result under
that key, and an ``if`` carries the keys its arms bound out to the phi.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import GuardedFaces, TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import ExitSet, true_guard
from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
    ContainerMutationStatementSugar,
)
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.if_sugar import _arm_evaluations
from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import (
    ContainerMutationStatement,
    EvaluationRef,
    FunctionDef,
    Return,
)
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


def _augs(body) -> list:
    """The substituted ``x += e`` statements: the one door's statements that
    write their name to the in-place result."""
    return [
        node
        for node in body
        if isinstance(node, ContainerMutationStatement)
        and isinstance(getattr(node, "rebinds", None), str)
    ]


def test_read_after_augassign_references_its_evaluation() -> None:
    rewritten = _function("def f(x):\n    x += 1\n    return x\n").substitute({})
    aug, ret = rewritten.body
    assert _augs([aug]) == [aug]
    assert aug.rebinds == "x"
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == aug.evaluation
    assert aug.evaluation.startswith(EVALUATION_PREFIX)
    assert ret.value.name == "x"


def test_statement_sugar_carries_its_evaluation_key() -> None:
    function = _function("def f(x):\n    x += 1\n    return x\n")
    statement = function.sugar().statements[0]
    assert isinstance(statement, ContainerMutationStatementSugar)
    key, _index = statement.result_evaluation
    assert isinstance(key, str)
    assert key.startswith(EVALUATION_PREFIX)


def test_each_unrolled_iteration_is_its_own_evaluation() -> None:
    rewritten = _function(
        "def f():\n    t = 0\n    for v in [1, 2]:\n        t += v\n    return t\n"
    ).substitute({})
    augs = _augs(rewritten.body)
    assert len(augs) == 2
    assert augs[0].evaluation != augs[1].evaluation
    ret = rewritten.body[-1]
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == augs[1].evaluation


def test_the_same_source_gives_the_same_keys() -> None:
    source = "def f():\n    t = 0\n    for v in [1, 2]:\n        t += v\n    return t\n"
    first = [node.evaluation for node in _augs(_function(source).substitute({}).body)]
    second = [node.evaluation for node in _augs(_function(source).substitute({}).body)]
    assert first and first == second


def test_a_reference_reads_the_evaluation() -> None:
    ctx = ReduceContext.root(owner="evaluation-ref")
    ctx = ctx.with_temporal(ctx.temporal.bind_value(KEY, TermValue(5)))
    assert _ref().desugar(ctx) == ExitSet.completed(TermValue(5))


def test_a_later_write_of_the_name_is_not_read() -> None:
    # The reference reads its key only: a binding of the name, before or
    # after the key, is never read in its place.
    ctx = ReduceContext.root(owner="evaluation-ref")
    ctx = ctx.with_temporal(ctx.temporal.bind_value(KEY, TermValue(5)))
    ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(7)))
    assert _ref().desugar(ctx) == ExitSet.completed(TermValue(5))


def test_an_evaluation_written_after_the_name_is_read() -> None:
    ctx = ReduceContext.root(owner="evaluation-ref")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(7)))
    ctx = ctx.with_temporal(ctx.temporal.bind_value(KEY, TermValue(5)))
    assert _ref().desugar(ctx) == ExitSet.completed(TermValue(5))


@pytest.mark.parametrize("name_bound", [False, True])
def test_an_unbound_key_is_refused_by_name(name_bound: bool) -> None:
    # No evaluation bound: refused by name, naming the key.  Never the name
    # read (whatever it holds), never a free symbolic name.
    ctx = ReduceContext.root(owner="evaluation-ref")
    if name_bound:
        ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(7)))
    with pytest.raises(ConstructionPanic) as refused:
        _ref().desugar(ctx)
    assert refused.value.info.owner == "EvaluationRefSugar"
    assert KEY in refused.value.info.observed
    assert "`x`" in refused.value.info.observed


def test_no_temporal_is_refused_by_name() -> None:
    with pytest.raises(ConstructionPanic) as refused:
        _ref().desugar(None)
    assert KEY in refused.value.info.observed


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


def test_two_values_on_overlapping_arms_are_not_carried() -> None:
    # Both arms hold under truth: the key is at two values on one path, so
    # no one value is carried and its read is refused by name.
    base = ReduceContext.root(owner="evaluation-join")
    one = base.with_temporal(base.temporal.bind_value(KEY, TermValue(2)))
    two = base.with_temporal(base.temporal.bind_value(KEY, TermValue(3)))
    assert _arm_evaluations((_arm(one), _arm(two)), base) == ()


def test_two_values_on_exclusive_arms_are_each_carried_under_their_guard() -> None:
    # The two faces of one split bind the key to different values: the key
    # is carried as each face's value under that face's guard, never left
    # out and never one face's value on both.
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.ir import atomic, not_
    from sugar_lift_py_tests.outcome.exit_set import partition

    base = ReduceContext.root(owner="evaluation-join")
    one = base.with_temporal(base.temporal.bind_value(KEY, TermValue(2)))
    two = base.with_temporal(base.temporal.bind_value(KEY, TermValue(3)))
    guard = atomic("c", [])
    then_face, else_face = partition(("evaluation-join", "c"))
    arms = _arm(one).guarded(guard, then_face).union(
        _arm(two).guarded(not_(guard), else_face)
    )
    assert len(arms.exits) == 2, arms
    ((key, value),) = _arm_evaluations((arms,), base)
    assert key == KEY
    assert value == GuardedValue(guard, TermValue(2), TermValue(3))


def test_arms_that_bound_one_evaluation_differently_are_not_merged() -> None:
    # Equal records, different values of one evaluation: two paths, never
    # one arm reading the first path's value on both.
    base = ReduceContext.root(owner="evaluation-join")
    one = base.with_temporal(base.temporal.bind_value(KEY, TermValue(2)))
    two = base.with_temporal(base.temporal.bind_value(KEY, TermValue(3)))
    assert len(_arm(one).union(_arm(two)).exits) == 2
    same = base.with_temporal(base.temporal.bind_value(KEY, TermValue(2)))
    assert len(_arm(one).union(_arm(same)).exits) == 1


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
