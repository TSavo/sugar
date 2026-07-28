"""#6691 guard-context producer: sealed binding state into pre-yield guard temporal.

Governing law
-------------
GeneratorConstructionV1 carries authenticated sealed BindingEntryV1 state into
the temporal context used for pre-yield guard evaluation.  The sole consumer
door remains BindingCoordinateRefSugar.desugar (exact coordinate.cid lookup).
No name lookup, coordinate scanning, or unspecialized-formal fallback is added
to that door.

Acceptance
----------
- real bound option_context-style actual resolves at the guard's exact formal
  coordinate
- renamed twin uses the same path
- wrong coordinate / tampered / absent testimony stay loud
- undecidable guard retains complementary faces with the same sealed state
- guard halt retains exact pre-halt state
"""

from __future__ import annotations

import tempfile
from dataclasses import replace

import pytest

from sugar_lift_py_tests.generator_construction import (
    GeneratorConstructionV1,
    GeneratorTerminationV1,
    GeneratorTransitionGapV1,
    IfStepV1,
    ReturnStepV1,
    YieldEffect,
    YieldStepV1,
)
from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.sugar.binding_coordinate_ref_sugar import (
    BindingCoordinateRefSugar,
)
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.temporal.temporal_context import TemporalContext
from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_provenance import ConstructedValueTestimonyV1
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


def _bool_formal_entry(*, truth: bool):
    """One sealed formal binding whose actual is a ground bool Constant."""
    literal = "True" if truth else "False"
    function = _function(f"def option_context(enabled):\n    flag = {literal}\n")
    assignment = next(node for node in function.walk() if node.kind == "Assign")
    param = function.params[0]
    factory = RuntimeBindingEntryFactoryV1(
        cid_of_json({"scope": function.fragment.seal().to_dict()})
    )
    entry = factory.mint_entry(
        binding_site=param.fragment,
        projection_path=("formal", 0),
        state=assignment.value,
    )
    return function, param, seal_bound_binding_entry_v1(entry)


def _guard_ref(function, param, coordinate) -> BindingCoordinateRefSugar:
    return BindingCoordinateRefSugar(coordinate, param.fragment)


def _machine_with_guard(entry: BindingEntryV1, guard, *, then_steps=None, else_steps=()):
    then_steps = then_steps or (YieldStepV1(TrueBoolLiteralSugar(site="then")),)
    steps = (
        IfStepV1(guard, then_steps, else_steps, "frag:guard"),
        ReturnStepV1(),
    )
    return GeneratorConstructionV1.allocate(
        allocation_coordinate="call:option_context:1",
        frame_coordinate="frame:option_context",
        binding_state=(entry,),
        steps=steps,
    )


# ---------------------------------------------------------------------------
# Real bound actual resolves at the exact formal coordinate
# ---------------------------------------------------------------------------


def test_bound_option_context_actual_resolves_at_exact_formal_coordinate() -> None:
    """Truthful: sealed formal True splices the then-branch at its coordinate."""
    function, param, entry = _bool_formal_entry(truth=True)
    guard = _guard_ref(function, param, entry.coordinate)
    machine = _machine_with_guard(entry, guard)

    outcome = machine.resume()

    assert isinstance(outcome, YieldEffect)
    # Sealed state is unchanged across the decided branch.
    assert len(outcome.machine.binding_state) == 1
    sealed = outcome.machine.binding_state[0]
    assert isinstance(sealed, BindingEntryV1)
    assert sealed.coordinate.cid == entry.coordinate.cid
    assert sealed.require_constructed_value_testimony().cid == (
        entry.require_constructed_value_testimony().cid
    )


def test_bound_false_formal_splices_else_branch() -> None:
    function, param, entry = _bool_formal_entry(truth=False)
    guard = _guard_ref(function, param, entry.coordinate)
    machine = _machine_with_guard(
        entry,
        guard,
        then_steps=(YieldStepV1(TrueBoolLiteralSugar(site="then")),),
        else_steps=(),
    )

    outcome = machine.resume()

    # False guard + empty else → termination (no yield).
    assert isinstance(outcome, GeneratorTerminationV1)
    assert outcome.binding_state[0].coordinate.cid == entry.coordinate.cid


def test_renamed_twin_resolves_on_the_same_coordinate_path() -> None:
    """Renamed formal spelling does not change coordinate-keyed resolution."""
    # Same projection path / sealed actual; only the source param name differs.
    function, param, entry = _bool_formal_entry(truth=True)
    # Rebuild under a renamed source function; coordinate identity is the seal.
    renamed = _function("def option_context_renamed(flag):\n    flag = True\n")
    renamed_param = renamed.params[0]
    factory = RuntimeBindingEntryFactoryV1(
        cid_of_json({"scope": renamed.fragment.seal().to_dict()})
    )
    assignment = next(node for node in renamed.walk() if node.kind == "Assign")
    renamed_entry = seal_bound_binding_entry_v1(
        factory.mint_entry(
            binding_site=renamed_param.fragment,
            projection_path=("formal", 0),
            state=assignment.value,
        )
    )
    guard = BindingCoordinateRefSugar(
        renamed_entry.coordinate, renamed_param.fragment
    )
    machine = _machine_with_guard(renamed_entry, guard)

    outcome = machine.resume()

    assert isinstance(outcome, YieldEffect)
    assert outcome.machine.binding_state[0].coordinate.cid == renamed_entry.coordinate.cid


# ---------------------------------------------------------------------------
# Wrong coordinate / tampered / absent testimony — loud
# ---------------------------------------------------------------------------


def test_wrong_coordinate_does_not_resolve_another_formal() -> None:
    """Lying: a nearby formal coordinate is not this guard's binding."""
    _fn, _param, entry = _bool_formal_entry(truth=True)
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
    # Guard points at *other* coordinate while machine holds *entry*.
    guard = BindingCoordinateRefSugar(other_entry.coordinate, other_param.fragment)
    machine = _machine_with_guard(entry, guard)

    outcome = machine.resume()

    # Wrong coordinate → unspecialized formal → undecided → loud gap.
    assert isinstance(outcome, GeneratorTransitionGapV1)


def test_absent_testimony_is_not_installed_into_guard_temporal() -> None:
    """Lying: unsealed binding state does not authorize formal resolution."""
    function, param, sealed = _bool_formal_entry(truth=True)
    # Strip seal: runtime entry without sealed_state.
    unsealed = BindingEntryV1(sealed.coordinate, sealed.state, None)
    assert unsealed.constructed_value_testimony is None
    guard = _guard_ref(function, param, sealed.coordinate)
    # allocate will re-seal — so allocate with unsealed and then replace state.
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:absent",
        frame_coordinate="frame:absent",
        binding_state=(unsealed,),
        steps=(
            IfStepV1(
                guard,
                (YieldStepV1(TrueBoolLiteralSugar(site="t")),),
                (),
                "frag",
            ),
            ReturnStepV1(),
        ),
    )
    # allocate seals; force-absent for the twin:
    machine = replace(
        machine,
        binding_state=(BindingEntryV1(sealed.coordinate, sealed.state, None),),
    )
    # Producer installs nothing; consumer refuses → undecided gap.
    outcome = machine.resume()
    assert isinstance(outcome, GeneratorTransitionGapV1)


def test_binding_coordinate_ref_consumer_stays_the_refusal_boundary() -> None:
    """BindingCoordinateRefSugar.desugar is still the sole consumer door."""
    function, param, entry = _bool_formal_entry(truth=True)
    guard = _guard_ref(function, param, entry.coordinate)
    # Empty temporal: exact consumer refusal, not a generator-side rewrite.
    class _Empty:
        temporal = TemporalContext()

    with pytest.raises(SugarNotWritten, match="unspecialized source-call formal"):
        guard.desugar(_Empty())


def test_tampered_coordinate_cid_does_not_hit_sealed_entry() -> None:
    function, param, entry = _bool_formal_entry(truth=True)
    tampered = replace(
        entry.coordinate,
        cid="blake3-512:" + "a" * 128,
    )
    guard = BindingCoordinateRefSugar(tampered, param.fragment)
    machine = _machine_with_guard(entry, guard)

    outcome = machine.resume()

    assert isinstance(outcome, GeneratorTransitionGapV1)


# ---------------------------------------------------------------------------
# Undecidable guard: complementary faces keep the same sealed state
# ---------------------------------------------------------------------------


def test_undecidable_guard_faces_retain_the_same_sealed_binding_state() -> None:
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import atomic
    from sugar_lift_py_tests.outcome.exit_set import Completed

    _fn, _param, entry = _bool_formal_entry(truth=True)
    guard = PredicateValue(atomic("symbolic_guard", ()), "s")
    machine = _machine_with_guard(
        entry,
        guard,
        then_steps=(YieldStepV1(TrueBoolLiteralSugar(site="t")),),
        else_steps=(YieldStepV1(FalseBoolLiteralSugar(site="e")),),
    )

    outcome = machine.resume()

    assert isinstance(outcome, ExitSet)
    completed = [exit_ for exit_ in outcome.exits if isinstance(exit_, Completed)]
    assert len(completed) >= 1
    # Factor may collapse to one GuardedValue arm; every successor machine that
    # still carries generator state must retain the sealed formal binding.
    sealed_cid = entry.require_constructed_value_testimony().cid

    def _check_state(value):
        if isinstance(value, GeneratorConstructionV1):
            assert len(value.binding_state) == 1
            bound = value.binding_state[0]
            assert isinstance(bound, BindingEntryV1)
            assert bound.coordinate.cid == entry.coordinate.cid
            assert bound.require_constructed_value_testimony().cid == sealed_cid
            return
        # GuardedValue / factored forms may wrap the machine.
        inner = getattr(value, "value", None) or getattr(value, "machine", None)
        if inner is not None and inner is not value:
            _check_state(inner)
        for face in getattr(value, "faces", ()) or ():
            _check_state(getattr(face, "value", face))

    for exit_ in completed:
        _check_state(exit_.value)


# ---------------------------------------------------------------------------
# Guard halt retains exact pre-halt state
# ---------------------------------------------------------------------------


def test_guard_halt_retains_exact_pre_halt_sealed_state() -> None:
    function, param, entry = _bool_formal_entry(truth=True)
    guard = _guard_ref(function, param, entry.coordinate)
    machine = _machine_with_guard(entry, guard)

    effect = RaiseEffect(exception_name="HaltProbe", occurrence="guard:halt")
    halted = machine.throw(effect)

    assert isinstance(halted, ExitSet)
    halted_exits = [exit_ for exit_ in halted.exits if isinstance(exit_, Halted)]
    assert halted_exits
    for exit_ in halted_exits:
        state = exit_.state
        assert isinstance(state, GeneratorConstructionV1)
        assert len(state.binding_state) == 1
        assert state.binding_state[0].coordinate.cid == entry.coordinate.cid
        assert state.binding_state[0].require_constructed_value_testimony().cid == (
            entry.require_constructed_value_testimony().cid
        )
        # Cursor / steps unchanged: pre-halt snapshot.
        assert state.cursor == machine.cursor
        assert state.steps == machine.steps
        assert state.instance_coordinate == machine.instance_coordinate
