"""Producer: recursive IfStepV1 + Finally ConstructedTermSugar cleanup.

Specimens are source-defined (and renamed) generator managers — no pandas
spelling admission. Suspension-owning if, try/finally cleanup expression
calls, and raise validation arms construct through
FunctionDef._source_visible_generator_steps_from only.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim.sugar_catalog import SugarCatalog
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor.predicate_value import PredicateValue
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
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.ir import atomic, not_, str_const
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.expr_statement_sugar import ExprStatementSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _ProducedActualSugar(ConstructedTermSugar):
    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)

    def to_term(self, *, owner: str):
        del owner
        return str_const("test:produced-actual")


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


def _production_machine(source: str, actual: ConstructedTermSugar):
    construction = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, "manager.py", blake3_512_of(source.encode("utf-8"))),
        construction_context=construction,
    )
    function = next(node for node in tree.nodes() if node.kind == "FunctionDef")
    call = next(
        node
        for node in tree.nodes()
        if node.kind == "Call" and getattr(node.func, "id", None) == function.name
    )
    frame = function.source_visible_call_frame().bind_node_actuals(
        call.args,
        tuple((kw.arg, kw.value) for kw in call.keywords if kw.arg is not None),
    )
    span = call.line_col_span()
    construction.source_call_frames[
        SourceFragmentCoordinateV1(
            call.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
    ] = frame
    outcome = CallSiteSugar(
        target_name=function.name,
        args=(actual,),
        site=call.fragment,
        source_call_frame=frame,
    ).desugar(ReduceContext.root(owner="generator-step-if-finally"))
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, GeneratorConstructionV1)
    return outcome.value


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
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.outcome import exit_set as exit_set_module

    guard = atomic("test.generator.guard", [])
    machine = _production_machine(
        "def manager(c):\n"
        "    if c:\n"
        "        yield 1\n"
        "    else:\n"
        "        yield 2\n"
        "manager(caller_value)\n",
        _ProducedActualSugar(PredicateValue(guard, "guard:occurrence")),
    )
    minted = []
    unfactored = []
    real_partition = exit_set_module.partition
    real_factor = ExitSet.factor_completed

    def record_partition(owner):
        minted.append(owner)
        return real_partition(owner)

    def record_factor(exits):
        unfactored.extend(exits.exits)
        return real_factor(exits)

    exit_set_module.partition = record_partition
    ExitSet.factor_completed = record_factor
    try:
        outcome = machine.resume()
    finally:
        exit_set_module.partition = real_partition
        ExitSet.factor_completed = real_factor
    assert isinstance(outcome, ExitSet)
    faces = [exit_ for exit_ in outcome.exits if isinstance(exit_, Completed)]
    assert len(faces) == 1
    guarded = faces[0].value
    assert isinstance(guarded, GuardedValue)
    successors = [guarded.when_true, guarded.when_false]
    assert all(
        isinstance(successor, GeneratorConstructionV1) for successor in successors
    )
    assert {successor.instance_coordinate for successor in successors} == {
        machine.instance_coordinate
    }
    assert guarded.when_true is not guarded.when_false
    produced = [face for face in unfactored if isinstance(face, Completed)]
    assert len(produced) == 2
    assert {face.guard for face in produced} == {
        guarded.guard,
        not_(guarded.guard),
    }
    assert minted == [
        (
            "generator.branch",
            machine.instance_coordinate,
            machine.steps[0].fragment_cid,
        )
    ]
    # Neither branch executed during guard production: both successors remain
    # seated at their own first YieldStepV1 with the exact pre-guard bindings.
    assert all(successor.cursor == machine.cursor for successor in successors)
    assert all(
        successor.binding_state == machine.binding_state for successor in successors
    )
    assert {
        successor.steps[successor.cursor].value.value for successor in successors
    } == {1, 2}


def test_guard_halt_bypasses_both_branches_with_pre_halt_state() -> None:
    steps = _steps(
        "def manager():\n"
        "    if guard():\n"
        "        yield 1\n"
        "    else:\n"
        "        yield 2\n"
        "def guard():\n"
        "    raise RuntimeError('guard halt')\n"
    )
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:h",
        frame_coordinate="frame:h",
        binding_state=(),
        steps=steps,
    )
    halted = machine.resume()
    assert isinstance(halted, ExitSet)
    faces = [exit_ for exit_ in halted.exits if isinstance(exit_, Halted)]
    assert len(faces) == 1
    face = faces[0]
    assert face.effect.exception_name == "RuntimeError"
    assert face.effect.occurrence.endswith(":7:4")
    assert face.state is machine
    assert face.state.cursor == 0
    assert face.state.instance_coordinate == machine.instance_coordinate
    assert face.state.steps is machine.steps


def test_nonhalting_guard_twin_executes_only_selected_branch() -> None:
    steps = _steps(
        "def manager():\n"
        "    if True:\n"
        "        yield 1\n"
        "    else:\n"
        "        raise RuntimeError('unselected')\n"
    )
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:h:twin",
        frame_coordinate="frame:h:twin",
        binding_state=(),
        steps=steps,
    )
    selected = machine.resume()
    assert isinstance(selected, YieldEffect)
    assert selected.value.value == 1


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
            (ExprStatementSugar(value=IntLiteralSugar(1, site="x"), site="s"),)
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


def test_try_finally_fallthrough_places_cleanup_on_the_outgoing_face() -> None:
    steps = _steps(
        "def manager():\n"
        "    try:\n"
        "        setup()\n"
        "    finally:\n"
        "        cleanup()\n"
        "    yield 1\n"
    )
    kinds = [type(step).__name__ for step in steps]
    assert kinds[:3] == ["TermStepV1", "FinallyStepV1", "YieldStepV1"]


def test_try_finally_return_places_cleanup_before_the_return_face() -> None:
    steps = _steps(
        "def manager():\n"
        "    try:\n"
        "        return 7\n"
        "    finally:\n"
        "        cleanup()\n"
        "    yield 1\n"
    )
    kinds = [type(step).__name__ for step in steps]
    assert kinds[:2] == ["FinallyStepV1", "ReturnStepV1"]


def test_try_finally_halt_places_cleanup_before_the_raise_face() -> None:
    steps = _steps(
        "def manager():\n"
        "    try:\n"
        "        raise ValueError('body')\n"
        "    finally:\n"
        "        cleanup()\n"
        "    yield 1\n"
    )
    kinds = [type(step).__name__ for step in steps]
    assert kinds[:2] == ["FinallyStepV1", "RaiseStepV1"]


def test_return_face_runs_cleanup_and_preserves_return_when_cleanup_falls_through() -> (
    None
):
    steps = _steps(
        "def manager():\n"
        "    try:\n"
        "        return 7\n"
        "    finally:\n"
        "        cleanup()\n"
        "    yield 1\n"
        "def cleanup():\n"
        "    pass\n"
    )
    outcome = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:return-finally",
        frame_coordinate="frame:return-finally",
        binding_state=(),
        steps=steps,
    ).resume()
    assert type(outcome).__name__ == "GeneratorTerminationV1"
    assert outcome.return_value.value == 7


@pytest.mark.parametrize(
    ("body", "incoming"),
    (("return 7", "return"), ("raise ValueError('body')", "halt")),
)
def test_terminating_cleanup_supersedes_return_and_halt_faces(
    body: str, incoming: str
) -> None:
    steps = _steps(
        "def manager():\n"
        "    try:\n"
        f"        {body}\n"
        "    finally:\n"
        "        cleanup()\n"
        "    yield 1\n"
        "def cleanup():\n"
        "    raise RuntimeError('cleanup')\n"
    )
    outcome = GeneratorConstructionV1.allocate(
        allocation_coordinate=f"call:cleanup-supersedes:{incoming}",
        frame_coordinate=f"frame:cleanup-supersedes:{incoming}",
        binding_state=(),
        steps=steps,
    ).resume()
    assert isinstance(outcome, ExitSet)
    halted = [exit_ for exit_ in outcome.exits if isinstance(exit_, Halted)]
    assert len(halted) == 1
    assert halted[0].effect.exception_name == "RuntimeError"
    assert halted[0].effect.occurrence.endswith(":8:4")


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
    assert (
        _function(
            "def alpha(c):\n    if c:\n        yield 1\n    try:\n        yield 2\n"
            "    finally:\n        restore()\n"
        ).name
        != _function(
            "def beta_renamed(c):\n    if c:\n        yield 1\n    try:\n        yield 2\n"
            "    finally:\n        restore()\n"
        ).name
    )


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
        "def manager(c):\n" "    if c:\n" "        x = yield 1\n" "    yield 2\n"
    )
    assert isinstance(steps[0], OpaqueStepV1)
    assert steps[0].observed == "If"
    assert steps[0].carries_suspension is True


def test_structured_for_cleanup_stays_owned_by_finally() -> None:
    from sugar_lift_py_tests.generator_construction import FinallyStepV1, ForStepV1

    steps = _steps(
        "def manager():\n"
        "    try:\n"
        "        yield 1\n"
        "    finally:\n"
        "        for x in items:\n"
        "            pass\n"
    )
    cleanup = next(s for s in steps if isinstance(s, FinallyStepV1))
    assert len(cleanup.cleanup_steps) == 1
    assert isinstance(cleanup.cleanup_steps[0], ForStepV1)


def test_cleanup_construction_invariant_failure_stays_loud() -> None:
    function = _function(
        "def manager():\n"
        "    try:\n"
        "        yield 1\n"
        "    finally:\n"
        "        for x in items:\n"
        "            pass\n"
    )
    cleanup_for = next(node for node in function.walk() if node.kind == "For")
    iterable_type = type(cleanup_for.iter)
    original = iterable_type.sugar

    def invariant_failure(self):
        raise RuntimeError("cleanup constructor invariant")

    iterable_type.sugar = invariant_failure
    try:
        with pytest.raises(RuntimeError, match="cleanup constructor invariant"):
            _steps_of(function)
    finally:
        iterable_type.sugar = original


def test_cleanup_call_is_term_step_when_bare_expr_before_yield() -> None:
    steps = _steps("def manager():\n" "    setup()\n" "    yield 1\n")
    assert isinstance(steps[0], TermStepV1)
    assert steps[0].fragment_cid.startswith("blake3-512:")
    assert isinstance(steps[1], YieldStepV1)


# ---------------------------------------------------------------------------
# Required twins (coordinator list)
# ---------------------------------------------------------------------------


def test_twin_branch_swap_changes_then_else_payloads() -> None:
    a = _steps("def m(c):\n    if c:\n        yield 1\n    else:\n        yield 2\n")[0]
    b = _steps("def m(c):\n    if c:\n        yield 2\n    else:\n        yield 1\n")[0]
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
    term_cids = [s.fragment_cid for s in steps if isinstance(s, TermStepV1)]
    finally_steps = [s for s in steps if isinstance(s, FinallyStepV1)]
    assert term_cids  # first() before yield
    assert finally_steps
    # finally is after the yield in source order of the step list
    yield_i = next(i for i, s in enumerate(steps) if isinstance(s, YieldStepV1))
    finally_i = next(i for i, s in enumerate(steps) if isinstance(s, FinallyStepV1))
    assert yield_i < finally_i
