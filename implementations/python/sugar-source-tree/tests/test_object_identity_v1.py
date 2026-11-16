from __future__ import annotations

import tempfile

import pytest

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_provenance import BindingProvenanceGap
from sugar_source_tree.object_identity import (
    OpaqueObjectCoordinateV1,
    decode_object_coordinate_v1,
)
from sugar_source_tree.tree import SourceFile


def _calls():
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write("def f():\n    left = C()\n    right = C()\n")
        path = handle.name
    function = next(SourceFile(path_source(path)).functions())
    return [node.fragment for node in function.walk() if node.kind == "Call"]


def _object(site, evaluation="evaluation:fixture/left"):
    return OpaqueObjectCoordinateV1.mint(
        call_occurrence=site,
        construction_evaluation=evaluation,
        source_cid=site.source_cid,
        artifact_cid=cid_of_json({"artifact": "fixture"}),
    )


def test_object_identity_is_call_occurrence_not_binding_or_shape():
    first_site, second_site = _calls()
    first = _object(first_site)
    second = _object(second_site)
    assert first.cid != second.cid
    assert "binding" not in repr(first.wire()).lower()
    assert decode_object_coordinate_v1(first.wire()) == first


def test_two_evaluations_of_one_call_are_two_objects():
    # One allocation per evaluation: the same call evaluated twice (two
    # unrolled iterations, two calls of its function) makes two objects.
    site, _ = _calls()
    first = _object(site, "evaluation:iteration-0/b")
    second = _object(site, "evaluation:iteration-1/b")
    assert first.cid != second.cid
    assert _object(site, "evaluation:iteration-0/b").cid == first.cid


def test_opaque_result_proves_only_occurrence_identity_and_aliasing():
    first_site, _ = _calls()
    opaque = OpaqueObjectCoordinateV1.mint(
        call_occurrence=first_site,
        construction_evaluation="evaluation:fixture/opaque",
        source_cid=first_site.source_cid,
        artifact_cid=cid_of_json({"artifact": "native"}),
    )
    assert decode_object_coordinate_v1(opaque.wire()) == opaque
    assert not ({"fields", "behavior", "class", "type"} & set(opaque.wire()))


def test_an_object_coordinate_names_no_allocation_definition():
    # One object coordinate (#7757): the call occurrence and the evaluation
    # that made it.  What the callee denotes is never part of it, so the
    # deleted ``source-object-coordinate`` kind is refused by name.
    site, _ = _calls()
    wire = _object(site).wire()
    assert "allocationDefinition" not in wire
    with pytest.raises(BindingProvenanceGap, match="unsupported ObjectCoordinateV1"):
        decode_object_coordinate_v1({**wire, "kind": "source-object-coordinate"})
