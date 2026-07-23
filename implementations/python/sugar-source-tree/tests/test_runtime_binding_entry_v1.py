from __future__ import annotations

import tempfile

import pytest

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_provenance import (
    BindingEntryV1 as SealedBindingEntryV1,
    ConstructedValueTestimonyV1,
)
from sugar_source_tree.binding_state import (
    BindingEntryV1,
    RuntimeBindingEntryFactoryV1,
    RuntimeBindingEntryGap,
)
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    return next(SourceFile(path_source(path)).functions())


def _entry(source: str = "def arbitrary():\n    renamed = 1\n"):
    function = _function(source)
    assignment = next(node for node in function.walk() if node.kind == "Assign")
    target = assignment.targets[0]
    live_state = assignment.value
    factory = RuntimeBindingEntryFactoryV1(
        cid_of_json({"scope": function.fragment.seal().to_dict()})
    )
    entry = factory.mint_entry(
        binding_site=target.fragment,
        projection_path=("targets", 0),
        state=live_state,
    )
    return assignment, live_state, entry


def test_runtime_entry_keeps_live_node_and_projects_only_pure_wire():
    assignment, live_state, entry = _entry()
    assert entry.state is live_state
    assert "renamed" not in entry.coordinate.preimage
    with pytest.raises(RuntimeBindingEntryGap, match="testimony unavailable"):
        entry.wire()

    testimony = ConstructedValueTestimonyV1.mint(
        assignment.value.fragment,
        cid_of_json({"kind": "constructed-int", "value": 1}),
    )
    projected = entry.with_testimony(testimony).wire()
    assert set(projected) == {"coordinate", "state"}
    assert "state" in projected and "ref" not in repr(projected)
    assert SealedBindingEntryV1.decode(projected).wire() == projected


def test_projection_reauthenticates_coordinate_and_testimony_cids():
    from dataclasses import replace

    assignment, _live_state, entry = _entry()
    testimony = ConstructedValueTestimonyV1.mint(
        assignment.value.fragment, cid_of_json({"value": 1})
    )
    ready = entry.with_testimony(testimony)
    with pytest.raises(ValueError, match="coordinate CID mismatch"):
        replace(
            ready,
            coordinate=replace(ready.coordinate, cid="blake3-512:stale"),
        ).wire()
    with pytest.raises(ValueError, match="testimony CID mismatch"):
        ready.with_testimony(
            replace(testimony, cid="blake3-512:stale")
        ).wire()


def test_distinct_occurrences_borrowing_one_span_never_collide():
    assignment, _live_state, _entry_one = _entry()
    factory = RuntimeBindingEntryFactoryV1(
        cid_of_json({"scope": assignment.fragment.seal().to_dict()})
    )
    first = factory.mint_entry(
        binding_site=assignment.targets[0].fragment,
        projection_path=("targets", 0),
        state=assignment.value,
    )
    second = factory.mint_entry(
        binding_site=assignment.targets[0].fragment,
        projection_path=("targets", 0),
        state=assignment.value,
    )
    assert first.coordinate.cid != second.coordinate.cid


def test_runtime_binding_map_has_one_carrier_not_parallel_name_to_node_state():
    assignment, live_state, entry = _entry()
    bindings = {"renamed": entry}
    assert bindings["renamed"] is entry
    assert isinstance(bindings["renamed"], BindingEntryV1)
    assert bindings["renamed"].state is live_state
