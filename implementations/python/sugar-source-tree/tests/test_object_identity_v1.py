from __future__ import annotations

import tempfile

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.object_identity import (
    OpaqueObjectCoordinateV1,
    SourceObjectCoordinateV1,
    decode_object_coordinate_v1,
)
from sugar_source_tree.tree import SourceFile


def _calls():
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write("def f():\n    left = C()\n    right = C()\n")
        path = handle.name
    function = next(SourceFile(path_source(path)).functions())
    return [node.fragment for node in function.walk() if node.kind == "Call"]


def _source(site, generation=0):
    return SourceObjectCoordinateV1.mint(
        allocation_definition=site,
        call_occurrence=site,
        construction_generation=generation,
        source_cid=site.source_cid,
        artifact_cid=cid_of_json({"artifact": "fixture"}),
    )


def test_object_identity_is_call_occurrence_not_binding_or_shape():
    first_site, second_site = _calls()
    first = _source(first_site)
    second = _source(second_site)
    assert first.cid != second.cid
    assert "binding" not in repr(first.wire()).lower()
    assert decode_object_coordinate_v1(first.wire()) == first


def test_opaque_result_proves_only_occurrence_identity_and_aliasing():
    first_site, _ = _calls()
    opaque = OpaqueObjectCoordinateV1.mint(
        call_occurrence=first_site,
        construction_generation=3,
        source_cid=first_site.source_cid,
        artifact_cid=cid_of_json({"artifact": "native"}),
    )
    assert decode_object_coordinate_v1(opaque.wire()) == opaque
    assert not ({"fields", "behavior", "class", "type"} & set(opaque.wire()))
