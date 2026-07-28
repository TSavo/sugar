"""Generator bound entries seal with mandatory ConstructedValueTestimonyV1.

Producer (seal_bound_binding_entry_v1 / seal_generator_binding_state_v1) mints
testimony from the bound Node's source fragment and actual value content.
Successfully sealed entries wire without delayed BindingStateWireGap.
"""

from __future__ import annotations

import tempfile
from dataclasses import replace

import pytest

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_provenance import (
    BoundBindingStateV1,
    ConstructedValueTestimonyV1,
)
from sugar_source_tree.binding_state import (
    BindingEntryV1,
    BindingStateWireGap,
    RuntimeBindingEntryFactoryV1,
    seal_bound_binding_entry_v1,
    seal_generator_binding_state_v1,
)
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    return next(SourceFile(path_source(path)).functions())


def _bound_entry(source: str = "def gen():\n    bound = 7\n    yield bound\n"):
    function = _function(source)
    assignments = [node for node in function.walk() if node.kind == "Assign"]
    assert assignments, "need an assignment to bind"
    value_node = assignments[0].value
    site = assignments[0].targets[0].fragment
    factory = RuntimeBindingEntryFactoryV1(
        cid_of_json({"scope": function.fragment.seal().to_dict()})
    )
    entry = factory.mint_entry(
        binding_site=site,
        projection_path=("formal", 0),
        state=value_node,
    )
    return function, value_node, entry


def test_bound_binding_state_requires_testimony_at_construction():
    with pytest.raises(Exception, match="testimony unavailable"):
        BoundBindingStateV1(None)


def test_unsealed_entry_has_no_bound_projection():
    _fn, _value, entry = _bound_entry()
    assert entry.sealed_state is None
    assert entry.constructed_value_testimony is None
    with pytest.raises(BindingStateWireGap, match="no authenticated sealed"):
        entry.wire()


def test_seal_mints_testimony_from_value_content_and_wires():
    _fn, value_node, entry = _bound_entry(
        "def gen():\n    bound = 7\n    yield bound\n"
    )
    sealed = seal_bound_binding_entry_v1(entry)
    testimony = sealed.require_constructed_value_testimony()
    assert isinstance(testimony, ConstructedValueTestimonyV1)
    assert testimony.source_fragment_cid == value_node.fragment.seal().cid
    # Wire succeeds now — no delayed gap after successful seal.
    projected = sealed.wire()
    assert projected["state"]["kind"] == "bound"
    assert (
        projected["state"]["testimony"]["constructedValueTestimonyCid"] == testimony.cid
    )


def test_identical_source_and_value_yield_identical_testimony():
    _fn, value_node, entry = _bound_entry(
        "def gen():\n    bound = 7\n    yield bound\n"
    )
    left = seal_bound_binding_entry_v1(entry)
    right = seal_bound_binding_entry_v1(entry)
    assert (
        left.require_constructed_value_testimony().cid
        == right.require_constructed_value_testimony().cid
    )
    assert left.wire() == right.wire()
    # Explicit mint of the same content matches the producer.
    semantic = left.require_constructed_value_testimony().semantic_value_cid
    reminted = ConstructedValueTestimonyV1.mint(value_node.fragment, semantic)
    assert reminted.cid == left.require_constructed_value_testimony().cid


def test_changed_value_content_changes_testimony():
    _fn_a, _va, entry_a = _bound_entry("def gen():\n    bound = 1\n    yield bound\n")
    _fn_b, _vb, entry_b = _bound_entry("def gen():\n    bound = 2\n    yield bound\n")
    sealed_a = seal_bound_binding_entry_v1(entry_a)
    sealed_b = seal_bound_binding_entry_v1(entry_b)
    assert (
        sealed_a.require_constructed_value_testimony().cid
        != sealed_b.require_constructed_value_testimony().cid
    )


def test_changed_binding_coordinate_changes_entry_wire():
    function = _function("def gen():\n    a = 1\n    b = 1\n")
    assignments = [node for node in function.walk() if node.kind == "Assign"]
    factory = RuntimeBindingEntryFactoryV1(
        cid_of_json({"scope": function.fragment.seal().to_dict()})
    )
    first = factory.mint_entry(
        binding_site=assignments[0].targets[0].fragment,
        projection_path=("targets", 0),
        state=assignments[0].value,
    )
    second = factory.mint_entry(
        binding_site=assignments[1].targets[0].fragment,
        projection_path=("targets", 0),
        state=assignments[1].value,
    )
    sealed_first = seal_bound_binding_entry_v1(first)
    sealed_second = seal_bound_binding_entry_v1(second)
    assert sealed_first.coordinate.cid != sealed_second.coordinate.cid
    assert sealed_first.wire() != sealed_second.wire()


def test_mismatched_testimony_refuses_at_seal():
    _fn, value_node, entry = _bound_entry(
        "def gen():\n    bound = 7\n    yield bound\n"
    )
    lying = ConstructedValueTestimonyV1.mint(
        value_node.fragment,
        cid_of_json({"kind": "lying-value", "value": 99}),
    )
    with pytest.raises(BindingStateWireGap, match="does not match bound value content"):
        seal_bound_binding_entry_v1(entry, testimony=lying)


def test_stale_coordinate_refuses_at_seal():
    _fn, _value, entry = _bound_entry("def gen():\n    bound = 7\n    yield bound\n")
    stale = replace(
        entry,
        coordinate=replace(entry.coordinate, cid="blake3-512:" + "0" * 128),
    )
    with pytest.raises(BindingStateWireGap, match="coordinate CID mismatch"):
        seal_bound_binding_entry_v1(stale)


def test_seal_generator_binding_state_seals_entries_only():
    _fn, _value, entry = _bound_entry("def gen():\n    bound = 7\n    yield bound\n")
    resume = ("resume-stub",)
    sealed = seal_generator_binding_state_v1((entry, "bound:x", *resume))
    assert len(sealed) == 3
    assert isinstance(sealed[0], BindingEntryV1)
    assert sealed[0].require_constructed_value_testimony() is not None
    assert sealed[0].wire()["state"]["kind"] == "bound"
    assert sealed[1] == "bound:x"
    assert sealed[2] == "resume-stub"


def test_successfully_sealed_entry_never_delays_wire_gap():
    _fn, _value, entry = _bound_entry("def gen():\n    bound = 7\n    yield bound\n")
    sealed = seal_bound_binding_entry_v1(entry)
    # Round-trip wire is stable and never raises BindingStateWireGap.
    first = sealed.wire()
    second = sealed.wire()
    assert first == second
    assert first["state"]["testimony"]["constructedValueTestimonyCid"] == (
        sealed.require_constructed_value_testimony().cid
    )
