from __future__ import annotations

from dataclasses import replace
import tempfile

import pytest

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_provenance import (
    BindingCoordinateV1,
    BindingEntryV1,
    BindingProvenanceGap,
    BoundBindingStateV1,
    ConstructedValueTestimonyV1,
    SubstitutionTraceRecordV1,
    SubstitutionTraceV1,
)
from sugar_source_tree.tree import SourceFile


def _assignments(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    function = next(SourceFile(path_source(path)).functions())
    return function, [node for node in function.walk() if node.kind == "Assign"]


def test_coordinate_is_occurrence_and_projection_not_identifier():
    function, assignments = _assignments(
        "def arbitrary():\n    same = 1\n    same = 2\n"
    )
    owner = cid_of_json({"scope": function.fragment.seal().to_dict()})
    first = BindingCoordinateV1.mint(
        owner, assignments[0].targets[0].fragment, ("targets", 0)
    )
    second = BindingCoordinateV1.mint(
        owner, assignments[1].targets[0].fragment, ("targets", 0)
    )
    assert first.cid != second.cid
    assert "same" not in first.preimage
    assert BindingCoordinateV1.decode(first.wire()) == first


def test_borrowed_span_values_require_distinct_occurrence_paths():
    function, assignments = _assignments("def arbitrary():\n    value = 1\n")
    owner = cid_of_json({"scope": function.fragment.seal().to_dict()})
    site = assignments[0].targets[0].fragment
    one = BindingCoordinateV1.mint(owner, site, ("synthetic", 0))
    two = BindingCoordinateV1.mint(owner, site, ("synthetic", 1))
    assert one.cid != two.cid


def test_constructed_value_testimony_is_authenticated_and_unavailable_is_loud():
    _function, assignments = _assignments("def arbitrary():\n    value = 1\n")
    value = assignments[0].value
    testimony = ConstructedValueTestimonyV1.mint(
        value.fragment, cid_of_json({"kind": "IntLiteralSugar", "value": 1})
    )
    assert ConstructedValueTestimonyV1.decode(testimony.wire()) == testimony
    # Bound sealed state requires testimony at construction; None is unrepresentable.
    with pytest.raises(BindingProvenanceGap, match="testimony unavailable"):
        BoundBindingStateV1(None)
    # Sealed wire entry without a bound state cannot project testimony.
    from sugar_source_tree.binding_provenance import UnboundBindingStateV1

    entry = BindingEntryV1(
        BindingCoordinateV1.mint(
            cid_of_json({"scope": "arbitrary"}),
            assignments[0].targets[0].fragment,
            ("targets", 0),
        ),
        UnboundBindingStateV1(value.fragment.seal().cid),
    )
    with pytest.raises(BindingProvenanceGap, match="not a bound value"):
        entry.constructed_value_testimony_cid()


def test_trace_round_trip_authenticates_every_preimage():
    function, assignments = _assignments("def arbitrary():\n    value = 1\n")
    owner = cid_of_json({"scope": function.fragment.seal().to_dict()})
    coordinate = BindingCoordinateV1.mint(
        owner, assignments[0].targets[0].fragment, ("targets", 0)
    )
    testimony = ConstructedValueTestimonyV1.mint(
        assignments[0].value.fragment, cid_of_json({"value": 1})
    )
    entry = BindingEntryV1(coordinate, BoundBindingStateV1(testimony))
    record = SubstitutionTraceRecordV1.mint(assignments[0].fragment, (), (entry,))
    trace = SubstitutionTraceV1.mint(owner, (record,))
    assert SubstitutionTraceV1.decode(trace.wire()) == trace

    stale = trace.wire()
    stale["traceCid"] = "blake3-512:stale"
    with pytest.raises(BindingProvenanceGap, match="trace CID mismatch"):
        SubstitutionTraceV1.decode(stale)

    with pytest.raises(BindingProvenanceGap, match="coordinate CID mismatch"):
        BindingCoordinateV1.decode(replace(coordinate, cid="blake3-512:stale").wire())
