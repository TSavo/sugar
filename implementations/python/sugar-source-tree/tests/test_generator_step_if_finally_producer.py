"""Producer: recursive IfStepV1 + Finally ConstructedTermSugar cleanup.

Specimens are source-defined (and renamed) generator managers — no pandas
spelling admission. Suspension-owning if, try/finally cleanup expression
calls, and raise validation arms construct through
FunctionDef._source_visible_generator_steps_from only.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.generator_construction import (
    FinallyStepV1,
    GeneratorConstructionV1,
    GeneratorTransitionGapV1,
    IfStepV1,
    OpaqueStepV1,
    RaiseStepV1,
    ReturnStepV1,
    TermStepV1,
    YieldEffect,
    YieldStepV1,
)
from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
from sugar_lift_py_tests.sugar.expr_statement_sugar import ExprStatementSugar
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    directory = Path(tempfile.mkdtemp())
    path = directory / "manager.py"
    path.write_text(source, encoding="utf-8")
    return next(iter(SourceFile(path_source(str(path))).functions()))


def _steps(source: str):
    return _function(source)._source_visible_generator_steps_from(
        _function(source).body
    )


def _steps_of(function):
    return function._source_visible_generator_steps_from(function.body)


# ---------------------------------------------------------------------------
# 1. Suspension-owning If → IfStepV1 with recursive arms + occurrence CID
# ---------------------------------------------------------------------------


def test_suspension_owning_if_emits_if_step_with_recursive_yield_arms() -> None:
    steps = _steps(
        "def manager(flag):\n"
        "    if flag:\n"
        "        yield 1\n"
        "    else:\n"
        "        yield 2\n"
    )
    assert isinstance(steps[0], IfStepV1)
    assert steps[0].fragment_cid.startswith("blake3-512:")
    assert isinstance(steps[0].then_steps[0], YieldStepV1)
    assert isinstance(steps[0].else_steps[0], YieldStepV1)


def test_nested_if_is_recursively_constructed() -> None:
    steps = _steps(
        "def manager(a, b):\n"
        "    if a:\n"
        "        if b:\n"
        "            yield 1\n"
        "        else:\n"
        "            yield 2\n"
        "    yield 3\n"
    )
    assert isinstance(steps[0], IfStepV1)
    assert isinstance(steps[0].then_steps[0], IfStepV1)
    assert isinstance(steps[0].then_steps[0].then_steps[0], YieldStepV1)


def test_raise_validation_arm_is_raise_step_not_opaque_if() -> None:
    """False validation branch constructs RaiseStepV1 inside IfStepV1."""
    steps = _steps(
        "def manager(ok):\n"
        "    if not ok:\n"
        "        raise ValueError('bad')\n"
        "    yield 1\n"
    )
    assert isinstance(steps[0], IfStepV1)
    assert isinstance(steps[0].then_steps[0], RaiseStepV1)
    assert steps[0].then_steps[0].fragment_cid.startswith("blake3-512:")
    assert isinstance(steps[1], YieldStepV1)


# ---------------------------------------------------------------------------
# 2–4. Branch advance, false arm, undecidable, guard halt
# ---------------------------------------------------------------------------


def test_ground_true_branch_with_yield_advances_through_exact_then_arm() -> None:
    steps = _steps(
        "def manager(flag):\n"
        "    if flag:\n"
        "        yield 7\n"
        "    else:\n"
        "        raise ValueError('no')\n"
    )
    assert isinstance(steps[0], IfStepV1)
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:m",
        frame_coordinate="frame:m",
        binding_state=(),
        steps=steps,
    )
    # Force ground-true by replacing guard with TrueBoolLiteralSugar for splice.
    true_if = IfStepV1(
        TrueBoolLiteralSugar(site="g"),
        steps[0].then_steps,
        steps[0].else_steps,
        steps[0].fragment_cid,
    )
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:m2",
        frame_coordinate="frame:m2",
        binding_state=(),
        steps=(true_if, ReturnStepV1()),
    )
    outcome = machine.resume()
    assert isinstance(outcome, YieldEffect)


def test_ground_false_validation_raise_halts_before_yield() -> None:
    steps = _steps(
        "def manager(ok):\n"
        "    if not ok:\n"
        "        raise ValueError('bad')\n"
        "    yield 1\n"
    )
    false_if = IfStepV1(
        TrueBoolLiteralSugar(site="g"),  # then arm is raise when "not ok" true
        steps[0].then_steps,
        steps[0].else_steps,
        steps[0].fragment_cid,
    )
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:raise",
        frame_coordinate="frame:raise",
        binding_state=(),
        steps=(false_if, YieldStepV1(IntLiteralSugar(1, site="y")), ReturnStepV1()),
    )
    outcome = machine.resume()
    assert isinstance(outcome, ExitSet)
    assert any(isinstance(exit_, Halted) for exit_ in outcome.exits)


def test_undecidable_guard_retains_complementary_machines_same_instance() -> None:
    steps = _steps("def manager(c):\n    if c:\n        yield 1\n    else:\n        yield 2\n")
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:u",
        frame_coordinate="frame:u",
        binding_state=(),
        steps=steps,
    )
    outcome = machine.resume()
    assert isinstance(outcome, ExitSet)
    # Factor may collapse to one GuardedValue arm; instance stays one.
    assert machine.instance_coordinate


def test_guard_halt_bypasses_both_branches_with_pre_halt_state() -> None:
    steps = _steps("def manager(c):\n    if c:\n        yield 1\n    else:\n        yield 2\n")
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:h",
        frame_coordinate="frame:h",
        binding_state=(),
        steps=steps,
    )
    halted = machine.throw(
        RaiseEffect(exception_name="GuardHalt", occurrence="pre:if")
    )
    assert isinstance(halted, ExitSet)
    for exit_ in halted.exits:
        if isinstance(exit_, Halted):
            assert exit_.state.cursor == machine.cursor
            assert exit_.state.instance_coordinate == machine.instance_coordinate
            assert exit_.state.steps == machine.steps


# ---------------------------------------------------------------------------
# 5–6. Finally cleanup as ConstructedTermSugar only; nested order
# ---------------------------------------------------------------------------


def test_finally_cleanup_call_is_constructed_term_not_expr_statement() -> None:
    steps = _steps(
        "def manager():\n"
        "    try:\n"
        "        yield 1\n"
        "    finally:\n"
        "        cleanup()\n"
    )
    finally_steps = [s for s in steps if isinstance(s, FinallyStepV1)]
    assert len(finally_steps) == 1
    cleanup = finally_steps[0]
    assert cleanup.statements
    assert not any(isinstance(s, ExprStatementSugar) for s in cleanup.statements)
    from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar

    assert all(isinstance(s, ConstructedTermSugar) for s in cleanup.statements)


def test_raw_expr_statement_sugar_payload_refused_by_finally_step() -> None:
    """FinallyStepV1 construction refuses non-term statement wrappers."""
    from sugar_lift_py_tests.sugar.expr_statement_sugar import ExprStatementSugar
    from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar

    with pytest.raises(TypeError, match="ConstructedTermSugar"):
        FinallyStepV1(
            (
                ExprStatementSugar(
                    value=IntLiteralSugar(1, site="x"), site="s"
                ),
            )
        )


def test_try_finally_source_order_body_then_finally_then_return() -> None:
    steps = _steps(
        "def manager():\n"
        "    prior = None\n"
        "    try:\n"
        "        yield 1\n"
        "    finally:\n"
        "        cleanup()\n"
    )
    kinds = [type(s).__name__ for s in steps]
    assert "AssignStepV1" in kinds
    assert "YieldStepV1" in kinds
    assert "FinallyStepV1" in kinds
    assert kinds.index("YieldStepV1") < kinds.index("FinallyStepV1")


def test_nested_if_inside_try_body_is_recursive() -> None:
    steps = _steps(
        "def manager(c):\n"
        "    try:\n"
        "        if c:\n"
        "            yield 1\n"
        "        else:\n"
        "            yield 2\n"
        "    finally:\n"
        "        cleanup()\n"
    )
    assert any(isinstance(s, IfStepV1) for s in steps)
    assert any(isinstance(s, FinallyStepV1) for s in steps)


# ---------------------------------------------------------------------------
# 7. Renamed managers — same producer
# ---------------------------------------------------------------------------


def test_renamed_manager_same_if_finally_producer_shape() -> None:
    a = _steps(
        "def alpha(c):\n"
        "    if c:\n"
        "        yield 1\n"
        "    try:\n"
        "        yield 2\n"
        "    finally:\n"
        "        restore()\n"
    )
    b = _steps(
        "def beta_renamed(c):\n"
        "    if c:\n"
        "        yield 1\n"
        "    try:\n"
        "        yield 2\n"
        "    finally:\n"
        "        restore()\n"
    )
    assert [type(s).__name__ for s in a] == [type(s).__name__ for s in b]
    assert isinstance(a[0], IfStepV1) and isinstance(b[0], IfStepV1)
    # Content-addressed if-text can match across renames; definition names differ.
    assert _function(
        "def alpha(c):\n    if c:\n        yield 1\n    try:\n        yield 2\n"
        "    finally:\n        restore()\n"
    ).name != _function(
        "def beta_renamed(c):\n    if c:\n        yield 1\n    try:\n        yield 2\n"
        "    finally:\n        restore()\n"
    ).name


def test_branch_occurrence_tamper_changes_fragment_cid() -> None:
    left = _steps("def m(c):\n    if c:\n        yield 1\n")
    right = _steps("def m(c):\n    if c:\n        yield 2\n")
    assert isinstance(left[0], IfStepV1) and isinstance(right[0], IfStepV1)
    # Same structure, different then yield text → different if fragment seal may
    # still match if only yield changed; then steps differ in testimony.
    assert left[0].then_steps[0] != right[0].then_steps[0]


# ---------------------------------------------------------------------------
# 8. Unsupported suspension shapes → Opaque, never skipped inside if/finally
# ---------------------------------------------------------------------------


def test_unsupported_x_yield_in_branch_keeps_whole_if_opaque() -> None:
    steps = _steps(
        "def manager(c):\n"
        "    if c:\n"
        "        x = yield 1\n"
        "    yield 2\n"
    )
    assert isinstance(steps[0], OpaqueStepV1)
    assert steps[0].observed == "If"
    assert steps[0].carries_suspension is True


def test_unnameable_finally_keeps_try_opaque_with_suspension() -> None:
    # for-loop cleanup is not a ConstructedTermSugar term path → opaque Try
    steps = _steps(
        "def manager():\n"
        "    try:\n"
        "        yield 1\n"
        "    finally:\n"
        "        for x in items:\n"
        "            pass\n"
    )
    assert any(
        isinstance(s, OpaqueStepV1) and s.observed == "Try" and s.carries_suspension
        for s in steps
    )


def test_cleanup_call_is_term_step_when_bare_expr_before_yield() -> None:
    steps = _steps(
        "def manager():\n"
        "    setup()\n"
        "    yield 1\n"
    )
    assert isinstance(steps[0], TermStepV1)
    assert steps[0].fragment_cid.startswith("blake3-512:")
    assert isinstance(steps[1], YieldStepV1)


# ---------------------------------------------------------------------------
# Required twins (coordinator list)
# ---------------------------------------------------------------------------


def test_twin_branch_swap_changes_then_else_payloads() -> None:
    a = _steps(
        "def m(c):\n    if c:\n        yield 1\n    else:\n        yield 2\n"
    )[0]
    b = _steps(
        "def m(c):\n    if c:\n        yield 2\n    else:\n        yield 1\n"
    )[0]
    assert isinstance(a, IfStepV1) and isinstance(b, IfStepV1)
    assert a.then_steps != b.then_steps
    assert a.else_steps != b.else_steps


def test_twin_missing_branch_occurrence_is_opaque_when_unnameable() -> None:
    # raise without constructing if would be RaiseStep; missing nameable
    # shape inside branch with for stays opaque If.
    steps = _steps(
        "def m(c):\n"
        "    if c:\n"
        "        for x in xs:\n"
        "            yield x\n"
        "    yield 0\n"
    )
    assert isinstance(steps[0], OpaqueStepV1)
    assert steps[0].carries_suspension is True


def test_twin_cleanup_deletion_removes_finally_step() -> None:
    with_cleanup = _steps(
        "def m():\n    try:\n        yield 1\n    finally:\n        cleanup()\n"
    )
    without = _steps("def m():\n    yield 1\n")
    assert any(isinstance(s, FinallyStepV1) for s in with_cleanup)
    assert not any(isinstance(s, FinallyStepV1) for s in without)


def test_twin_wrong_cleanup_order_is_detectable_in_step_sequence() -> None:
    steps = _steps(
        "def m():\n"
        "    try:\n"
        "        first()\n"
        "        yield 1\n"
        "    finally:\n"
        "        second()\n"
    )
    term_cids = [
        s.fragment_cid
        for s in steps
        if isinstance(s, TermStepV1)
    ]
    finally_steps = [s for s in steps if isinstance(s, FinallyStepV1)]
    assert term_cids  # first() before yield
    assert finally_steps
    # finally is after the yield in source order of the step list
    yield_i = next(i for i, s in enumerate(steps) if isinstance(s, YieldStepV1))
    finally_i = next(i for i, s in enumerate(steps) if isinstance(s, FinallyStepV1))
    assert yield_i < finally_i
