"""A ``finally`` evaluated on two exit paths is two evaluations, two keys.

``Try.substitute`` substitutes a ``finally`` once for the try's completion
and once more for its halted faces.  The same ``x += e`` under the same loop
iterations used to get one evaluation key on both copies; with a ``return``
in the ``finally`` both copies complete, both faces reach one join, the key
held two values and was dropped, and the read fell back to the name.  The key
now carries the exit path, so each copy's read sees its own path's value.
"""

from __future__ import annotations

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import GuardedFaces, TermValue
from sugar_lift_py_tests.outcome import ExitSet, true_guard
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.if_sugar import _arm_evaluations
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import (
    AugAssign,
    EvaluationRef,
    FunctionDef,
    Return,
    Try,
)
from sugar_source_tree.tree import SourceFile

# ``finally`` binds ``x`` on the completion path (x = 2) and on the halt path
# (x = 1), and the ``return`` in it reads ``x`` on each.
RETURN_IN_FINALLY = (
    "def f(c):\n"
    "    x = 0\n"
    "    try:\n"
    "        if c:\n"
    "            x = 1\n"
    "            raise ValueError\n"
    "        x = 2\n"
    "    finally:\n"
    "        x += 10\n"
    "        return x\n"
)

# Both paths reach ``finally`` with the same ``x``: the halted copy is still
# its own evaluation.
READ_AFTER_TRY = (
    "def f(c):\n"
    "    x = 0\n"
    "    try:\n"
    "        if c:\n"
    "            raise ValueError\n"
    "    finally:\n"
    "        x += 10\n"
    "    return x\n"
)


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "finally_exit_path.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _try_copies(source: str):
    rewritten = _function(source).substitute({})
    try_ = next(node for node in rewritten.body if isinstance(node, Try))
    halted = getattr(try_, "try_finalbody_halted", None)
    assert halted, "a finally holding an evaluation gets its halted copy"
    return rewritten, tuple(try_.finalbody), tuple(halted)


def _keys(source: str) -> tuple[str, str]:
    _rewritten, completion, halted = _try_copies(source)
    return completion[0].evaluation, halted[0].evaluation


def test_each_exit_path_of_finally_is_its_own_evaluation() -> None:
    _rewritten, completion, halted = _try_copies(RETURN_IN_FINALLY)
    on_completion, on_halt = completion[0], halted[0]
    assert isinstance(on_completion, AugAssign)
    assert isinstance(on_halt, AugAssign)
    assert isinstance(on_completion.evaluation, str)
    assert isinstance(on_halt.evaluation, str)
    assert on_completion.evaluation != on_halt.evaluation


def test_the_read_in_each_finally_copy_references_its_own_path() -> None:
    _rewritten, completion, halted = _try_copies(RETURN_IN_FINALLY)
    for copy in (completion, halted):
        aug, ret = copy
        assert isinstance(ret, Return)
        assert isinstance(ret.value, EvaluationRef)
        assert ret.value.evaluation == aug.evaluation
        assert ret.value.name == "x"


def test_a_halt_with_the_same_state_still_gets_its_own_key() -> None:
    rewritten, completion, halted = _try_copies(READ_AFTER_TRY)
    assert completion[0].evaluation != halted[0].evaluation
    ret = rewritten.body[-1]
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == completion[0].evaluation


def test_the_same_source_gives_the_same_exit_path_keys() -> None:
    assert _keys(RETURN_IN_FINALLY) == _keys(RETURN_IN_FINALLY)


def _face(ctx) -> ExitSet:
    return ExitSet.completed(_ReducedBlock((), True, (), context=ctx))


def test_both_paths_reach_one_join_and_each_read_sees_its_value() -> None:
    on_completion, on_halt = _keys(RETURN_IN_FINALLY)
    base = ReduceContext.root(owner="finally-exit-path")
    completed = base.with_temporal(
        base.temporal.bind_value(on_completion, TermValue(12))
    )
    halted = base.with_temporal(base.temporal.bind_value(on_halt, TermValue(11)))
    carried = _arm_evaluations((_face(completed), _face(halted)), base)
    assert dict(carried) == {
        on_completion: TermValue(12),
        on_halt: TermValue(11),
    }
    joined = GuardedFaces(
        guard=true_guard(),
        entries=(),
        then_exits=False,
        else_exits=False,
        evaluations=carried,
    ).extend_scope(base)
    for key, value in ((on_completion, 12), (on_halt, 11)):
        read = EvaluationRefSugar(evaluation=key, name="x", site=None)
        assert read.desugar(joined) == ExitSet.completed(TermValue(value))
