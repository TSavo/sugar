from __future__ import annotations

from copy import deepcopy
import tempfile

import pytest

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_provenance import BindingProvenanceGap
from sugar_source_tree.object_identity import (
    AttributeFieldCoordinateV1,
    AttributeFieldVersionV1,
    OpaqueObjectCoordinateV1,
    SourceObjectCoordinateV1,
    SubscriptFieldCoordinateV1,
    SubscriptFieldVersionV1,
    SubscriptKeyCoordinateV1,
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


def test_attribute_versions_are_immutable_prior_linked_and_closed():
    site, _ = _calls()
    owner = _source(site)
    field = AttributeFieldCoordinateV1.mint(owner, "payload")
    first = AttributeFieldVersionV1.mint(
        owner=owner,
        field=field,
        store_occurrence=site,
        construction_generation=0,
        stored_value_testimony_cid=cid_of_json({"value": 7}),
        prior_version_cid=None,
    )
    second = AttributeFieldVersionV1.mint(
        owner=owner,
        field=field,
        store_occurrence=site,
        construction_generation=1,
        stored_value_testimony_cid=cid_of_json({"value": 8}),
        prior_version_cid=first.cid,
    )
    assert second.prior_version_cid == first.cid
    assert AttributeFieldVersionV1.decode(second.wire()) == second

    for key in second.wire():
        forged = deepcopy(second.wire())
        value = forged[key]
        if isinstance(value, int):
            forged[key] = value + 1
        elif value is None:
            forged[key] = cid_of_json({"forged": key})
        elif isinstance(value, dict):
            forged[key] = {**value, "unexpected": True}
        else:
            forged[key] = "blake3-512:forged"
        with pytest.raises(BindingProvenanceGap):
            AttributeFieldVersionV1.decode(forged)


def test_subscript_versions_key_the_same_object_by_authenticated_key_coordinate():
    site, _ = _calls()
    owner = _source(site)
    zero = SubscriptKeyCoordinateV1.mint(
        constructed_value_cid=cid_of_json({"key": 0}),
        construction_testimony_cid=cid_of_json({"testimony": 0}),
    )
    one = SubscriptKeyCoordinateV1.mint(
        constructed_value_cid=cid_of_json({"key": 1}),
        construction_testimony_cid=cid_of_json({"testimony": 1}),
    )
    zero_field = SubscriptFieldCoordinateV1.mint(owner, zero)
    one_field = SubscriptFieldCoordinateV1.mint(owner, one)
    assert zero_field.cid != one_field.cid

    first = SubscriptFieldVersionV1.mint(
        owner=owner,
        field=zero_field,
        store_occurrence=site,
        construction_generation=1,
        stored_value_testimony_cid=cid_of_json({"value": 7}),
        prior_version_cid=None,
    )
    second = SubscriptFieldVersionV1.mint(
        owner=owner,
        field=zero_field,
        store_occurrence=site,
        construction_generation=2,
        stored_value_testimony_cid=cid_of_json({"value": 8}),
        prior_version_cid=first.cid,
    )
    assert second.prior_version_cid == first.cid
    assert SubscriptFieldVersionV1.decode(second.wire()) == second

    forged = deepcopy(second.wire())
    forged["fieldCoordinate"] = one_field.wire()
    with pytest.raises(BindingProvenanceGap):
        SubscriptFieldVersionV1.decode(forged)
