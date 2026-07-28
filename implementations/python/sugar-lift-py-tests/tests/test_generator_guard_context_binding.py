"""#6691 guard-context producer: binder Floors into pre-yield guard temporal.

Governing law
-------------
SourceCallFrame.bind_actuals produces formal-ordered Floor actuals.  Those
Floors are paired with formal coordinate CIDs at the binder boundary and
carried into GeneratorConstructionV1.allocate.  Guard evaluation installs
those Floors by identity into (an extension of) the caller reduction context.
BindingCoordinateRefSugar.desugar remains the sole consumer door.

Forbidden
---------
- Node.state → sugar() → desugar() reconstruction inside the consumer
- temporal-only fabricated context that discards authenticated caller context
- broad Exception catch converting construction defects to absent testimony
"""

from __future__ import annotations

import tempfile
from dataclasses import replace

import pytest

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.generator_construction import (
    FormalFloorBindingV1,
    GeneratorConstructionV1,
    GeneratorTerminationV1,
    GeneratorTransitionGapV1,
    IfStepV1,
    ReturnStepV1,
    YieldEffect,
    YieldStepV1,
)
from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
from sugar_lift_py_tests.sugar.binding_coordinate_ref_sugar import (
    BindingCoordinateRefSugar,
)
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.temporal.temporal_context import TemporalContext
from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_state import (
    BindingEntryV1,
    RuntimeBindingEntryFactoryV1,
    seal_bound_binding_entry_v1,
)
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    return next(SourceFile(path_source(path)).functions())


def _formal_entry_and_coordinate(*, truth: bool = True):
    """Sealed BindingEntryV1 for runtime_entries + its coordinate CID."""
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


def _machine(
    *,
    entry: BindingEntryV1,
    floor,
    guard=None,
    then_steps=None,
    else_steps=(),
    reduction_context=None,
    formal_floor_bindings=None,
):
    then_steps = then_steps or (YieldStepV1(IntLiteralSugar(1, site="then")),)
    if guard is None:
        guard = BindingCoordinateRefSugar(entry.coordinate, entry.state.fragment)
    if formal_floor_bindings is None:
        formal_floor_bindings = (
            FormalFloorBindingV1(entry.coordinate.cid, floor),
        )
    return GeneratorConstructionV1.allocate(
        allocation_coordinate="call:option_context:1",
        frame_coordinate="frame:option_context",
        binding_state=(entry,),
        steps=(
            IfStepV1(guard, then_steps, else_steps, "frag:guard"),
            ReturnStepV1(),
        ),
        formal_floor_bindings=formal_floor_bindings,
        reduction_context=reduction_context,
    )


# ---------------------------------------------------------------------------
# Binder Floor reaches the guard BY IDENTITY
# ---------------------------------------------------------------------------


def test_binder_floor_reaches_guard_by_identity() -> None:
    """Truthful: the exact bind_actuals Floor object is what the guard resolves."""
    _fn, param, entry = _formal_entry_and_coordinate(truth=True)
    floor = TrueBoolLiteralSugar(site=param.fragment)
    machine = _machine(entry=entry, floor=floor)

    outcome = machine.resume()

    assert isinstance(outcome, YieldEffect)
    # Install table holds the same object the binder produced.
    ctx = machine._guard_evaluation_context()
    resolved = ctx.temporal.value_if_bound(entry.coordinate.cid)
    assert resolved is floor
    assert len(outcome.machine.binding_state) == 1
    assert outcome.machine.binding_state[0].coordinate.cid == entry.coordinate.cid


def test_binder_false_floor_splices_else_branch() -> None:
    _fn, param, entry = _formal_entry_and_coordinate(truth=False)
    floor = FalseBoolLiteralSugar(site=param.fragment)
    machine = _machine(
        entry=entry,
        floor=floor,
        then_steps=(YieldStepV1(IntLiteralSugar(1, site="then")),),
        else_steps=(),
    )

    outcome = machine.resume()

    assert isinstance(outcome, GeneratorTerminationV1)
    assert machine._guard_evaluation_context().temporal.value_if_bound(
        entry.coordinate.cid
    ) is floor


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

    outcome = machine.resume()

    assert isinstance(outcome, YieldEffect)
    assert machine._guard_evaluation_context().temporal.value_if_bound(
        entry.coordinate.cid
    ) is floor


def test_default_and_keyword_binder_path_is_the_same_floor_table() -> None:
    """Defaults/keywords land through bind_actuals formal order — same install."""
    _fn, param, entry = _formal_entry_and_coordinate(truth=True)
    # Simulate a keyword-bound formal: still one FormalFloorBindingV1 at the cid.
    floor = TrueBoolLiteralSugar(site="kw-bound")
    machine = _machine(entry=entry, floor=floor)

    assert machine.formal_floor_bindings[0].coordinate_cid == entry.coordinate.cid
    assert machine.formal_floor_bindings[0].floor_value is floor
    assert isinstance(machine.resume(), YieldEffect)


# ---------------------------------------------------------------------------
# Wrong coordinate / absent floor — loud
# ---------------------------------------------------------------------------


def test_wrong_coordinate_does_not_resolve_binder_floor() -> None:
    _fn, param, entry = _formal_entry_and_coordinate(truth=True)
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
    # Guard points at *other* coordinate; machine only carries *entry*'s floor.
    guard = BindingCoordinateRefSugar(other_entry.coordinate, other_param.fragment)
    machine = _machine(entry=entry, floor=floor, guard=guard)

    outcome = machine.resume()

    assert isinstance(outcome, GeneratorTransitionGapV1)
    assert (
        machine._guard_evaluation_context().temporal.value_if_bound(
            other_entry.coordinate.cid
        )
        is None
    )


def test_absent_formal_floor_binding_refuses() -> None:
    """No FormalFloorBindingV1 install → consumer refuses (no reconstruction)."""
    function, param, entry = _formal_entry_and_coordinate(truth=True)
    guard = BindingCoordinateRefSugar(entry.coordinate, param.fragment)
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:absent",
        frame_coordinate="frame:absent",
        binding_state=(entry,),
        steps=(
            IfStepV1(
                guard,
                (YieldStepV1(IntLiteralSugar(1, site="t")),),
                (),
                "frag",
            ),
            ReturnStepV1(),
        ),
        formal_floor_bindings=(),  # empty — must not rebuild from entry.state
    )

    outcome = machine.resume()

    assert isinstance(outcome, GeneratorTransitionGapV1)


def test_binding_coordinate_ref_consumer_stays_the_refusal_boundary() -> None:
    function, param, entry = _formal_entry_and_coordinate(truth=True)
    guard = BindingCoordinateRefSugar(entry.coordinate, param.fragment)

    class _Empty:
        temporal = TemporalContext()

    with pytest.raises(SugarNotWritten, match="unspecialized source-call formal"):
        guard.desugar(_Empty())


def test_node_whose_sugar_would_panic_still_succeeds_without_consumer_rebuild() -> None:
    """Consumer never invokes state.sugar() — Floor comes only from the binder."""
    function, param, entry = _formal_entry_and_coordinate(truth=True)
    floor = TrueBoolLiteralSugar(site=param.fragment)
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:hostile",
        frame_coordinate="frame:hostile",
        binding_state=(entry,),
        steps=(
            IfStepV1(
                BindingCoordinateRefSugar(entry.coordinate, param.fragment),
                (YieldStepV1(IntLiteralSugar(1, site="t")),),
                (),
                "frag",
            ),
            ReturnStepV1(),
        ),
        formal_floor_bindings=(FormalFloorBindingV1(entry.coordinate.cid, floor),),
    )
    # After seal: any guard-path rebuild would call Node.sugar() on the bound state.
    sugar_calls: list[object] = []
    original_sugar = type(entry.state).sugar

    def _tracking_sugar(self, *args, **kwargs):
        sugar_calls.append(self)
        raise RuntimeError("consumer reconstruction is forbidden")

    type(entry.state).sugar = _tracking_sugar  # type: ignore[method-assign]
    try:
        outcome = machine.resume()
        assert isinstance(outcome, YieldEffect)
        assert sugar_calls == [], "guard path must not call Node.sugar()"
        assert machine._guard_evaluation_context().temporal.value_if_bound(
            entry.coordinate.cid
        ) is floor
        assert not hasattr(
            GeneratorConstructionV1, "_floor_from_sealed_binding_entry"
        )
    finally:
        type(entry.state).sugar = original_sugar  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Caller context extended, not discarded
# ---------------------------------------------------------------------------


def test_caller_reduction_context_is_extended_not_replaced() -> None:
    from sugar_lift_py_tests.claim.sugar_catalog import SugarCatalog
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext

    _fn, param, entry = _formal_entry_and_coordinate(truth=True)
    floor = TrueBoolLiteralSugar(site=param.fragment)
    marker = TrueBoolLiteralSugar(site="caller-marker")
    caller = FactoryBuildContext(
        filename="caller.py",
        catalog=SugarCatalog(),
        temporal=TemporalContext().bind_value("caller_marker", marker),
    )
    machine = _machine(entry=entry, floor=floor, reduction_context=caller)
    ctx = machine._guard_evaluation_context()

    assert hasattr(ctx, "filename") and ctx.filename == "caller.py"
    assert ctx.temporal.value_if_bound("caller_marker") is marker
    assert ctx.temporal.value_if_bound(entry.coordinate.cid) is floor


# ---------------------------------------------------------------------------
# Undecidable + halt retain formal floor install
# ---------------------------------------------------------------------------


def test_undecidable_guard_faces_retain_formal_floor_bindings() -> None:
    from sugar_lift_py_tests.outcome.exit_set import Completed

    _fn, param, entry = _formal_entry_and_coordinate(truth=True)
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
    completed = [exit_ for exit_ in outcome.exits if isinstance(exit_, Completed)]
    assert completed

    def _check(value):
        if isinstance(value, GeneratorConstructionV1):
            assert value.formal_floor_bindings[0].floor_value is floor
            assert value.formal_floor_bindings[0].coordinate_cid == entry.coordinate.cid
            return
        inner = getattr(value, "value", None) or getattr(value, "machine", None)
        if inner is not None and inner is not value:
            _check(inner)

    for exit_ in completed:
        _check(exit_.value)


def test_guard_halt_retains_exact_pre_halt_formal_floors() -> None:
    _fn, param, entry = _formal_entry_and_coordinate(truth=True)
    floor = TrueBoolLiteralSugar(site=param.fragment)
    machine = _machine(entry=entry, floor=floor)

    halted = machine.throw(
        RaiseEffect(exception_name="HaltProbe", occurrence="guard:halt")
    )

    assert isinstance(halted, ExitSet)
    halted_exits = [exit_ for exit_ in halted.exits if isinstance(exit_, Halted)]
    assert halted_exits
    for exit_ in halted_exits:
        state = exit_.state
        assert isinstance(state, GeneratorConstructionV1)
        assert state.formal_floor_bindings[0].floor_value is floor
        assert state.cursor == machine.cursor
        assert state.instance_coordinate == machine.instance_coordinate
