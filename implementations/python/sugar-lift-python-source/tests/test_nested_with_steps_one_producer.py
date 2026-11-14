"""A nested With body is named by the one generator step producer (#7757).

``_nameable_nested_with_body_steps`` used to be a second step builder beside
``FunctionDef``'s: it named ``y = yield v`` as an ``AssignStepV1`` of the
yield, had no yield assignment, and seated its own finally cleanup.  It now
asks ``FunctionDef._generator_step_producer`` for the suite's steps, so a
nested body's steps are a top-level body's steps.
"""

from __future__ import annotations

from sugar_lift_py_tests.generator_construction import (
    FinallyStepV1,
    ReturnStepV1,
    TermStepV1,
    YieldAssignStepV1,
    YieldFromStepV1,
    YieldStepV1,
)
from sugar_lift_python_source.manager_summary_derivation import (
    _nameable_nested_with_body_steps,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.nodes import FunctionDef, With
from sugar_source_tree.tree import SourceFile


def _with_body(tmp_path, source: str):
    path = tmp_path / "m.py"
    path.write_text(source, encoding="utf-8")
    function = next(iter(SourceFile(path_source(str(path))).functions()))
    (statement,) = [item for item in function.body if isinstance(item, With)]
    return statement.body


def _producer_kinds(body) -> list:
    _name_statement, branch_steps = FunctionDef._generator_step_producer()
    return [type(step) for step in branch_steps(tuple(body))]


def test_a_nested_yield_assignment_is_the_producers_yield_assign_step(
    tmp_path,
) -> None:
    body = _with_body(
        tmp_path,
        "def g(m):\n    with m():\n        y = yield 1\n        return y\n",
    )
    steps = _nameable_nested_with_body_steps(body)
    assert steps is not None
    assert [type(step) for step in steps] == [YieldAssignStepV1, ReturnStepV1]
    assert [type(step) for step in steps] == _producer_kinds(body)
    assert isinstance(steps[0].yield_step, YieldStepV1)
    assert [name for name, _evaluation in steps[0].targets] == ["y"]


def test_nested_unpacking_and_delegating_assignments_are_named(tmp_path) -> None:
    body = _with_body(
        tmp_path,
        (
            "def g(m):\n"
            "    with m():\n"
            "        a, b = yield 1\n"
            "        x = yield from (1, 2)\n"
        ),
    )
    steps = _nameable_nested_with_body_steps(body)
    assert steps is not None
    assert [type(step) for step in steps] == [YieldAssignStepV1, YieldAssignStepV1]
    assert steps[0].unpack is not None
    assert isinstance(steps[1].yield_step, YieldFromStepV1)


def test_a_nested_term_only_finally_runs_through_the_cleanup_sub_machine(
    tmp_path,
) -> None:
    body = _with_body(
        tmp_path,
        (
            "def g(m):\n"
            "    with m():\n"
            "        try:\n"
            "            yield 1\n"
            "        finally:\n"
            "            cleanup()\n"
        ),
    )
    steps = _nameable_nested_with_body_steps(body)
    assert steps is not None
    assert [type(step) for step in steps] == _producer_kinds(body)
    cleanup = next(step for step in steps if isinstance(step, FinallyStepV1))
    assert cleanup.statements == ()
    assert [type(step) for step in cleanup.cleanup_steps] == [TermStepV1]


def test_an_unnameable_nested_statement_keeps_the_with_loud(tmp_path) -> None:
    body = _with_body(
        tmp_path,
        "def g(m, o):\n    with m():\n        o.x = yield 1\n",
    )
    assert _nameable_nested_with_body_steps(body) is None
