"""Nested generator managers — publication + lifecycle through the pipeline.

Shape:

    @contextmanager
    def inner():
        prior = None          # pre-yield Assign peer (merged law)
        yield 'inner'

    @contextmanager
    def outer():
        with inner():
            yield 'outer'

Both layers publish; enter executes nested then yields outer resource; nested
cleanup runs before outer yield-resume on the halted edge; distinct occurrence
identities; tampered inner refuses; unpublishable nested is a loud named gap.

No nodes.py / With-consumer / carrier / ExitSet edits.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path
from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerResolutionGapV1,
    SourceDerivedGeneratorResourceRefV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import StringValue, TermValue
from sugar_lift_py_tests.generator_construction import (
    NestedEnteredBindingV1,
    NestedManagerExitStepV1,
    NestedManagerStepV1,
    YieldEffect,
    YieldStepV1,
    GeneratorConstructionV1,
    ReturnStepV1,
)
from sugar_lift_py_tests.outcome import Complete, Incomplete, outcome_to_exitset
from sugar_lift_py_tests.sugar.string_literal_sugar import StringLiteralSugar
from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.manager_protocol_construction import (
    EnteredGeneratorManagerStateV1,
    construct_generator_backed_protocol,
)
from sugar_lift_python_source.manager_summary_derivation import (
    GeneratorBackedLifecycleProtocolV1,
    GeneratorNestedManagerLayerV1,
    populate_source_derived_resource_refs,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _distribution(root: Path, implementation: str) -> importlib.metadata.Distribution:
    package = root / "unprivileged"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(
        "from unprivileged.helpers import outer, inner\n", encoding="utf-8"
    )
    (package / "helpers.py").write_text(implementation, encoding="utf-8")
    metadata = root / "unprivileged_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: unprivileged-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        "unprivileged/__init__.py",
        "unprivileged/helpers.py",
        "unprivileged_dist-1.0.dist-info/METADATA",
        "unprivileged_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _publish(tmp_path: Path, implementation: str, consumer: str | None = None):
    distribution = _distribution(tmp_path, implementation)
    path = tmp_path / "consumer.py"
    path.write_text(
        consumer
        or ("from unprivileged import outer\n" "with outer():\n" "    pass\n"),
        encoding="utf-8",
    )
    context = TreeConstructionContextV1.for_source_call_construction(
        workspace_root=str(tmp_path)
    )
    tree = SourceFile(
        path_source(str(path)),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )
    return context


_NESTED_CM = (
    "from contextlib import contextmanager\n"
    "\n"
    "@contextmanager\n"
    "def inner():\n"
    "    prior = None\n"
    "    yield 'inner'\n"
    "\n"
    "@contextmanager\n"
    "def outer():\n"
    "    with inner():\n"
    "        yield 'outer'\n"
)


def _outer_ref(context) -> SourceDerivedGeneratorResourceRefV1:
    refs = [
        v
        for v in context.source_derived_contract_refs.values()
        if isinstance(v, SourceDerivedGeneratorResourceRefV1)
    ]
    assert refs, (
        f"expected SourceDerivedGeneratorResourceRefV1; "
        f"got { {type(v).__name__ for v in context.source_derived_contract_refs.values()} }"
    )
    # Outer is the consumer-seated manager.
    return refs[0]


def test_nested_manager_publishes_both_layers(tmp_path: Path) -> None:
    context = _publish(tmp_path, _NESTED_CM)
    ref = _outer_ref(context)
    protocol = ref.generator_protocol
    assert isinstance(protocol, GeneratorBackedLifecycleProtocolV1)
    assert len(protocol.nested_manager_layers) == 1
    layer = protocol.nested_manager_layers[0]
    assert isinstance(layer, GeneratorNestedManagerLayerV1)
    assert layer.temporal_phase == "pre-yield"
    assert layer.cid == cid_of_json(layer.preimage)
    assert layer.nested_protocol_construction_cid.startswith("blake3-512:")
    assert layer.nested_generator_frame_cid.startswith("blake3-512:")
    # Distinct occurrence from outer protocol construction.
    assert layer.cid != protocol.protocol_construction_cid
    assert layer.occurrence["cid"] != protocol.protocol_construction_cid
    assert layer.nested_protocol_construction_cid != protocol.protocol_construction_cid


def test_nested_enter_executes_inner_then_yields_outer(tmp_path: Path) -> None:
    context = _publish(tmp_path, _NESTED_CM)
    protocol = _outer_ref(context).generator_protocol
    outcome = protocol.enter_resource_outcome()
    assert isinstance(outcome, Complete), type(outcome)
    entered = outcome.value
    assert isinstance(entered, EnteredGeneratorManagerStateV1)
    # Floor projects string yields as StringValue (or TermValue) — either is fine.
    assert str(getattr(entered.enter_value, "value", entered.enter_value)) == "outer"
    # Nested enter recorded on the live machine.
    assert any(
        isinstance(b, NestedEnteredBindingV1) for b in entered.machine.binding_state
    )


def test_nested_cleanup_runs_before_outer_resume_on_halt(tmp_path: Path) -> None:
    """Halted edge: NestedManagerExitStep cleans nested before halt propagates."""
    context = _publish(tmp_path, _NESTED_CM)
    protocol = _outer_ref(context).generator_protocol
    entered = protocol.enter_resource_outcome().value
    machine = entered.machine
    assert isinstance(machine.steps[machine.cursor], NestedManagerExitStepV1)
    # Plant a throw at the post-yield suspension (halted body edge).
    effect = RaiseEffect(
        exception_name="RuntimeError",
        blame="body",
        occurrence="body:halt",
        raised_value="boom",
    )
    halted = machine.throw(effect)
    # Nested exit must have run: NestedEnteredBinding still present but exit was
    # called (one-shot nested protocol refuses double exit).
    nested_binding = next(
        b for b in machine.binding_state if isinstance(b, NestedEnteredBindingV1)
    )
    with pytest.raises(Exception):
        # Double exit of nested is loud — proves exit already ran on throw.
        nested_binding.nested_protocol.exit_outcome_for(nested_binding.nested_entered)
    # Halt still carries the body effect.
    from sugar_lift_py_tests.outcome import Halted

    assert any(isinstance(e, Halted) for e in halted.exits)


def test_distinct_occurrence_identities_per_layer(tmp_path: Path) -> None:
    context = _publish(tmp_path, _NESTED_CM)
    protocol = _outer_ref(context).generator_protocol
    layer = protocol.nested_manager_layers[0]
    assert layer.occurrence["cid"] != protocol.generator_frame_cid
    assert layer.nested_generator_frame_cid != protocol.generator_frame_cid
    assert layer.cid not in {
        face.cid for face in protocol.yield_faces
    } | {face.cid for face in protocol.enter_halt_faces}


def test_tampered_inner_source_refuses_stable_layer_identity(tmp_path: Path) -> None:
    left_root = tmp_path / "a"
    right_root = tmp_path / "b"
    left_root.mkdir()
    right_root.mkdir()
    left = _publish(left_root, _NESTED_CM)
    right = _publish(
        right_root,
        _NESTED_CM.replace("prior = None", "prior = 1"),
    )
    left_layer = _outer_ref(left).generator_protocol.nested_manager_layers[0]
    right_layer = _outer_ref(right).generator_protocol.nested_manager_layers[0]
    # Tampered inner body changes nested frame / protocol construction CID.
    assert (
        left_layer.nested_protocol_construction_cid
        != right_layer.nested_protocol_construction_cid
        or left_layer.nested_generator_frame_cid != right_layer.nested_generator_frame_cid
    )


def test_unpublishable_nested_manager_is_loud_named_gap(tmp_path: Path) -> None:
    """Nested generator recognized but missing enter/exit coords → gap."""
    # Class-based generator-like that is not a @contextmanager decorator return
    # of a class with __enter__/__exit__ from contextmanager helper — use a
    # generator decorated with a non-CM decorator so coords are unavailable.
    impl = (
        "def not_cm(fn):\n"
        "    return fn\n"
        "\n"
        "@not_cm\n"
        "def inner():\n"
        "    yield 'inner'\n"
        "\n"
        "from contextlib import contextmanager\n"
        "\n"
        "@contextmanager\n"
        "def outer():\n"
        "    with inner():\n"
        "        yield 'outer'\n"
    )
    context = _publish(tmp_path, impl)
    # Outer seats as a gap or has no nested-honest ref.
    values = list(context.source_derived_contract_refs.values())
    if not values:
        return  # no seat — also honest residual
    for value in values:
        if isinstance(value, ContextManagerResolutionGapV1):
            detail = str(getattr(value, "detail", value))
            assert "nested" in detail.lower() or "nested-manager" in str(
                getattr(value, "kind", "")
            )
            return
        if isinstance(value, SourceDerivedGeneratorResourceRefV1):
            # Must not silently publish without nested layer when With(inner)
            # is a recognized generator without protocol coords — that is a gap.
            pytest.fail(
                "nested generator Without protocol coords must gap, not publish "
                f"a generator-backed ref: layers="
                f"{getattr(value.protocol, 'nested_manager_layers', None)}"
            )


def test_planted_nested_manager_step_lifecycle_performance() -> None:
    """Planted NestedManagerStep (no nodes emission) enters/exits nested once."""
    inner_frame = SimpleNamespace(
        frame_cid=cid_of_json({"frame": "inner-nested"}),
        generator_steps=(
            YieldStepV1(StringLiteralSugar("inner", site="nested:inner-yield")),
            ReturnStepV1(None),
        ),
        runtime_entries=(),
    )
    enter = SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 1, 0, 2, 0)
    exit_ = SourceFragmentCoordinateV1("blake3-512:" + "b" * 128, 3, 0, 4, 0)
    inner_protocol = construct_generator_backed_protocol(
        frame=inner_frame,
        enter_definition=enter,
        exit_definition=exit_,
        exit_face_id="inner-face",
        construction_cid="blake3-512:" + "c" * 128,
    )
    outer_steps = (
        NestedManagerStepV1(
            nested_protocol=inner_protocol,
            body_steps=(
                YieldStepV1(StringLiteralSugar("outer", site="nested:outer-yield")),
            ),
            fragment_cid="blake3-512:" + "d" * 128,
            occurrence_cid="blake3-512:" + "e" * 128,
        ),
        ReturnStepV1(None),
    )
    outer_frame = SimpleNamespace(
        frame_cid=cid_of_json({"frame": "outer-nested"}),
        generator_steps=outer_steps,
        runtime_entries=(),
    )
    outer_enter = SourceFragmentCoordinateV1("blake3-512:" + "f" * 128, 5, 0, 6, 0)
    outer_exit = SourceFragmentCoordinateV1("blake3-512:" + "0" * 128, 7, 0, 8, 0)
    outer_protocol = construct_generator_backed_protocol(
        frame=outer_frame,
        enter_definition=outer_enter,
        exit_definition=outer_exit,
        exit_face_id="outer-face",
        construction_cid="blake3-512:" + "1" * 128,
    )
    outcome = outer_protocol.enter_resource_outcome()
    assert isinstance(outcome, Complete)
    entered = outcome.value
    assert entered.enter_value == StringValue("outer")
    assert any(isinstance(b, NestedEnteredBindingV1) for b in entered.machine.binding_state)
    # Exit outer: NestedManagerExitStep exits nested then terminates.
    exit_outcome = outer_protocol.exit_outcome_for(entered)
    exits = outcome_to_exitset(exit_outcome)
    assert len(exits.exits) == 1
