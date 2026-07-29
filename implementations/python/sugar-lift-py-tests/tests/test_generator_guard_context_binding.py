"""#6691 guard-context: binder Floors into pre-yield guard temporal (rev2 teeth).

Governing law
-------------
SourceCallFrame.bind_actuals produces formal-ordered Floor actuals.  Those
Floors are paired with formal coordinate CIDs at the binder boundary and
carried into GeneratorConstructionV1.allocate, which verifies the roster
against sealed BindingEntryV1 formals.  Guard evaluation installs those Floors
by identity via the caller's ``with_temporal`` surface.
"""

from __future__ import annotations

import tempfile
from dataclasses import replace

import pytest

from sugar_lift_py_tests.claim.sugar_catalog import SugarCatalog
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.generator_construction import (
    FormalFloorBindingGap,
    FormalFloorBindingV1,
    GeneratorConstructionV1,
    GeneratorTerminationV1,
    GeneratorTransitionGapV1,
    IfStepV1,
    ReturnStepV1,
    YieldEffect,
    YieldStepV1,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.binding_coordinate_ref_sugar import (
    BindingCoordinateRefSugar,
)
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.temporal.temporal_context import TemporalContext
from sugar_lift_python_source.canonical import blake3_512_of, cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_state import (
    BindingEntryV1,
    RuntimeBindingEntryFactoryV1,
    seal_bound_binding_entry_v1,
)
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    return next(SourceFile(path_source(path)).functions())


def _formal_entry(*, truth: bool = True):
    literal = "True" if truth else "False"
    function = _function(f"def option_context(enabled):\n    flag = {literal}\n")
    assignment = next(node for node in function.walk() if node.kind == "Assign")
    param = function.params[0]
    factory = RuntimeBindingEntryFactoryV1(
        cid_of_json({"scope": function.fragment.seal().to_dict()})
    )
    entry = seal_bound_binding_entry_v1(
        factory.mint_entry(
            binding_site=param.fragment,
            projection_path=("formal", 0),
            state=assignment.value,
        )
    )
    return function, param, entry


def _machine(*, entry, floor, guard=None, then_steps=None, else_steps=(), ctx=None):
    then_steps = then_steps or (YieldStepV1(IntLiteralSugar(1, site="then")),)
    if guard is None:
        guard = BindingCoordinateRefSugar(entry.coordinate, entry.state.fragment)
    return GeneratorConstructionV1.allocate(
        allocation_coordinate="call:option_context:1",
        frame_coordinate="frame:option_context",
        binding_state=(entry,),
        steps=(
            IfStepV1(guard, then_steps, else_steps, "frag:guard"),
            ReturnStepV1(),
        ),
        formal_floor_bindings=(FormalFloorBindingV1(entry.coordinate.cid, floor),),
        reduction_context=ctx,
    )


def _call_coordinate(call: Call) -> SourceFragmentCoordinateV1:
    span = call.line_col_span()
    return SourceFragmentCoordinateV1(
        call.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _production_generator_call(source: str):
    """Parse generator + call; return (tree, function, call, bound_frame)."""
    construction = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, "prod_guard.py", blake3_512_of(source.encode("utf-8"))),
        construction_context=construction,
    )
    function = next(
        node for node in tree.nodes() if isinstance(node, FunctionDef)
    )
    call = next(node for node in tree.nodes() if isinstance(node, Call))
    frame = function.source_visible_call_frame().bind_node_actuals(
        call.args,
        tuple(
            (kw.arg, kw.value) for kw in call.keywords if kw.arg is not None
        ),
    )
    construction.source_call_frames[_call_coordinate(call)] = frame
    return tree, function, call, frame, construction


# ---------------------------------------------------------------------------
# 1. Roster law at allocate + substitution lying twin
# ---------------------------------------------------------------------------


def test_unrelated_coordinate_with_floor_refuses_at_allocate() -> None:
    """Lying: foreign coordinate CID is not a sealed formal on this machine."""
    _fn, param, entry = _formal_entry(truth=True)
    floor = TrueBoolLiteralSugar(site=param.fragment)
    foreign_cid = "blake3-512:" + "b" * 128
    with pytest.raises(FormalFloorBindingGap, match="roster must equal"):
        GeneratorConstructionV1.allocate(
            allocation_coordinate="call:lie",
            frame_coordinate="frame:lie",
            binding_state=(entry,),
            steps=(ReturnStepV1(),),
            formal_floor_bindings=(FormalFloorBindingV1(foreign_cid, floor),),
        )


def test_non_floor_object_refuses_formal_floor_binding() -> None:
    with pytest.raises(FormalFloorBindingGap, match="FloorValue"):
        FormalFloorBindingV1("blake3-512:" + "c" * 128, object())


def test_unconstrained_string_coordinate_refuses() -> None:
    with pytest.raises(FormalFloorBindingGap, match="blake3-512"):
        FormalFloorBindingV1("not-a-cid", TrueBoolLiteralSugar(site="s"))


def test_missing_floor_for_sealed_formal_refuses_at_allocate() -> None:
    _fn, _param, entry = _formal_entry(truth=True)
    with pytest.raises(FormalFloorBindingGap, match="roster must equal"):
        GeneratorConstructionV1.allocate(
            allocation_coordinate="call:missing",
            frame_coordinate="frame:missing",
            binding_state=(entry,),
            steps=(ReturnStepV1(),),
            formal_floor_bindings=(),
        )


# ---------------------------------------------------------------------------
# 2. Production binder tooth — positional and keyword/default
# ---------------------------------------------------------------------------


def test_production_positional_bind_actuals_floor_reaches_guard_by_identity() -> None:
    """ONE production positional call: binder Floor is guard identity."""
    source = (
        "def option_context(enabled):\n"
        "    if enabled:\n"
        "        yield 1\n"
        "option_context(True)\n"
    )
    _tree, function, call, frame, _construction = _production_generator_call(source)
    assert frame.generator_steps is not None
    true_arg = TrueBoolLiteralSugar(site=call.args[0].fragment)
    # Production binder: bind_actuals then CallSiteSugar.allocate path.
    bound_floors = frame.bind_actuals((true_arg,), ())
    assert bound_floors.actuals[0] is true_arg
    assert isinstance(bound_floors.actuals[0], FloorValue)

    caller = ReduceContext.root(owner="production-positional-guard")
    sugar = CallSiteSugar(
        target_name="option_context",
        args=(true_arg,),
        site=call.fragment,
        source_call_frame=frame,
    )
    outcome = sugar.desugar(caller)
    assert isinstance(outcome, Complete)
    machine = outcome.value
    assert isinstance(machine, GeneratorConstructionV1)
    assert len(machine.formal_floor_bindings) == 1
    assert machine.formal_floor_bindings[0].floor_value is true_arg
    assert (
        machine.formal_floor_bindings[0].coordinate_cid
        == frame.formal_coordinates[0].cid
    )
    # Guard table holds binder identity.
    assert machine._guard_evaluation_context().temporal.value_if_bound(
        frame.formal_coordinates[0].cid
    ) is true_arg
    # Guard resolves and splices then-branch.
    result = machine.resume()
    assert isinstance(result, YieldEffect)


def test_production_keyword_and_default_bind_actuals_floor_by_identity() -> None:
    """ONE keyword call + default formal: same binder → Floor identity table."""
    source = (
        "def option_context(enabled, flag=True):\n"
        "    if enabled:\n"
        "        yield 1\n"
        "option_context(enabled=True)\n"
    )
    _tree, function, call, frame, _construction = _production_generator_call(source)
    assert frame.parameters == ("enabled", "flag")
    enabled_floor = TrueBoolLiteralSugar(site="kw:enabled")
    # Keyword for enabled; flag takes default via bind_actuals.
    bound = frame.bind_actuals((), (("enabled", enabled_floor),))
    assert bound.actuals[0] is enabled_floor
    assert isinstance(bound.actuals[1], FloorValue)  # default True

    sugar = CallSiteSugar(
        target_name="option_context",
        args=(),
        keywords=(("enabled", enabled_floor),),
        site=call.fragment,
        source_call_frame=frame,
    )
    outcome = sugar.desugar(
        ReduceContext.root(owner="production-keyword-guard")
    )
    assert isinstance(outcome, Complete)
    machine = outcome.value
    assert isinstance(machine, GeneratorConstructionV1)
    assert len(machine.formal_floor_bindings) == 2
    by_cid = {
        item.coordinate_cid: item.floor_value
        for item in machine.formal_floor_bindings
    }
    assert by_cid[frame.formal_coordinates[0].cid] is enabled_floor
    # Default formal is the exact object bind_actuals returned.
    assert by_cid[frame.formal_coordinates[1].cid] is bound.actuals[1]
    assert machine._guard_evaluation_context().temporal.value_if_bound(
        frame.formal_coordinates[0].cid
    ) is enabled_floor


# ---------------------------------------------------------------------------
# 3. with_temporal required; no probe ladder
# ---------------------------------------------------------------------------


def test_caller_context_requires_with_temporal_surface() -> None:
    _fn, param, entry = _formal_entry(truth=True)
    floor = TrueBoolLiteralSugar(site=param.fragment)

    class _NoWithTemporal:
        temporal = TemporalContext()

    with pytest.raises(TypeError, match="with_temporal"):
        GeneratorConstructionV1.allocate(
            allocation_coordinate="call:probe",
            frame_coordinate="frame:probe",
            binding_state=(entry,),
            steps=(ReturnStepV1(),),
            formal_floor_bindings=(
                FormalFloorBindingV1(entry.coordinate.cid, floor),
            ),
            reduction_context=_NoWithTemporal(),
        )


def test_caller_with_temporal_is_extended_not_replaced() -> None:
    _fn, param, entry = _formal_entry(truth=True)
    floor = TrueBoolLiteralSugar(site=param.fragment)
    marker = TrueBoolLiteralSugar(site="caller-marker")
    caller = ReduceContext.root(owner="caller-temporal").with_temporal(
        TemporalContext().bind_value("caller_marker", marker)
    )
    machine = _machine(entry=entry, floor=floor, ctx=caller)
    ctx = machine._guard_evaluation_context()
    assert ctx.temporal.value_if_bound("caller_marker") is marker
    assert ctx.temporal.value_if_bound(entry.coordinate.cid) is floor


# ---------------------------------------------------------------------------
# Core acceptance (identity, refuse, rename, hostile sugar, halt)
# ---------------------------------------------------------------------------


def test_binder_floor_reaches_guard_by_identity() -> None:
    _fn, param, entry = _formal_entry(truth=True)
    floor = TrueBoolLiteralSugar(site=param.fragment)
    machine = _machine(entry=entry, floor=floor)
    assert isinstance(machine.resume(), YieldEffect)
    assert machine._guard_evaluation_context().temporal.value_if_bound(
        entry.coordinate.cid
    ) is floor


def test_binder_false_floor_splices_else_branch() -> None:
    _fn, param, entry = _formal_entry(truth=False)
    floor = FalseBoolLiteralSugar(site=param.fragment)
    machine = _machine(
        entry=entry,
        floor=floor,
        then_steps=(YieldStepV1(IntLiteralSugar(1, site="then")),),
        else_steps=(),
    )
    assert isinstance(machine.resume(), GeneratorTerminationV1)


def test_renamed_formal_uses_coordinate_not_spelling() -> None:
    renamed = _function("def option_context_renamed(flag):\n    flag = True\n")
    param = renamed.params[0]
    factory = RuntimeBindingEntryFactoryV1(
        cid_of_json({"scope": renamed.fragment.seal().to_dict()})
    )
    assignment = next(node for node in renamed.walk() if node.kind == "Assign")
    entry = seal_bound_binding_entry_v1(
        factory.mint_entry(
            binding_site=param.fragment,
            projection_path=("formal", 0),
            state=assignment.value,
        )
    )
    floor = TrueBoolLiteralSugar(site=param.fragment)
    machine = _machine(entry=entry, floor=floor)
    assert isinstance(machine.resume(), YieldEffect)
    assert machine._guard_evaluation_context().temporal.value_if_bound(
        entry.coordinate.cid
    ) is floor


def test_wrong_coordinate_guard_refuses_when_roster_is_honest() -> None:
    _fn, param, entry = _formal_entry(truth=True)
    floor = TrueBoolLiteralSugar(site=param.fragment)
    other = _function("def other(x):\n    x = False\n")
    other_param = other.params[0]
    factory = RuntimeBindingEntryFactoryV1(
        cid_of_json({"scope": other.fragment.seal().to_dict()})
    )
    other_entry = seal_bound_binding_entry_v1(
        factory.mint_entry(
            binding_site=other_param.fragment,
            projection_path=("formal", 0),
            state=next(n for n in other.walk() if n.kind == "Assign").value,
        )
    )
    guard = BindingCoordinateRefSugar(other_entry.coordinate, other_param.fragment)
    machine = _machine(entry=entry, floor=floor, guard=guard)
    assert isinstance(machine.resume(), GeneratorTransitionGapV1)


def test_node_sugar_never_invoked_on_guard_path() -> None:
    function, param, entry = _formal_entry(truth=True)
    floor = TrueBoolLiteralSugar(site=param.fragment)
    machine = _machine(entry=entry, floor=floor)
    sugar_calls: list[object] = []
    original = type(entry.state).sugar

    def _boom(self, *a, **k):
        sugar_calls.append(self)
        raise RuntimeError("consumer reconstruction forbidden")

    type(entry.state).sugar = _boom  # type: ignore[method-assign]
    try:
        assert isinstance(machine.resume(), YieldEffect)
        assert sugar_calls == []
        assert not hasattr(GeneratorConstructionV1, "_floor_from_sealed_binding_entry")
    finally:
        type(entry.state).sugar = original  # type: ignore[method-assign]


def test_binding_coordinate_ref_consumer_stays_the_refusal_boundary() -> None:
    function, param, entry = _formal_entry(truth=True)
    guard = BindingCoordinateRefSugar(entry.coordinate, param.fragment)

    class _Empty:
        temporal = TemporalContext()

    with pytest.raises(SugarNotWritten, match="unspecialized source-call formal"):
        guard.desugar(_Empty())


def test_undecidable_guard_faces_retain_formal_floor_bindings() -> None:
    _fn, param, entry = _formal_entry(truth=True)
    floor = TrueBoolLiteralSugar(site=param.fragment)
    machine = _machine(
        entry=entry,
        floor=floor,
        guard=NameSugar("symbolic_guard", site="s"),
        then_steps=(YieldStepV1(IntLiteralSugar(1, site="t")),),
        else_steps=(YieldStepV1(IntLiteralSugar(0, site="e")),),
    )
    outcome = machine.resume()
    assert isinstance(outcome, ExitSet)
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    assert completed

    def _check(value):
        if isinstance(value, GeneratorConstructionV1):
            assert value.formal_floor_bindings[0].floor_value is floor
            return
        inner = getattr(value, "value", None) or getattr(value, "machine", None)
        if inner is not None and inner is not value:
            _check(inner)

    for exit_ in completed:
        _check(exit_.value)


def test_guard_halt_retains_exact_pre_halt_formal_floors() -> None:
    _fn, param, entry = _formal_entry(truth=True)
    floor = TrueBoolLiteralSugar(site=param.fragment)
    machine = _machine(entry=entry, floor=floor)
    halted = machine.throw(
        RaiseEffect(exception_name="HaltProbe", occurrence="guard:halt")
    )
    assert isinstance(halted, ExitSet)
    for exit_ in halted.exits:
        if not isinstance(exit_, Halted):
            continue
        state = exit_.state
        assert isinstance(state, GeneratorConstructionV1)
        assert state.formal_floor_bindings[0].floor_value is floor
        assert state.cursor == machine.cursor
