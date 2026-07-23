from __future__ import annotations

import json

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    CallEdgeV2,
    FormalActualBindingV1,
    ValueOccurrenceCoordinateV1,
)
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import (
    ContractDecl,
    PrimitiveSort,
    contract_decl_to_value,
    term_to_value,
)


def _site(source: str, start: int, end: int) -> SourceFragmentCoordinateV1:
    return SourceFragmentCoordinateV1(source, 1, start, 1, end)


def test_call_edge_v2_has_only_ordered_coordinate_bindings() -> None:
    source = "blake3-512:" + "11" * 64
    call_site = _site(source, 0, 12)
    occurrence = ValueOccurrenceCoordinateV1.mint(_site(source, 5, 6))
    binding = FormalActualBindingV1(
        formal_coordinate_cid="blake3-512:" + "22" * 64,
        actual_occurrence=occurrence,
        actual_term=TermValue(3).to_term(owner="test"),
    )
    edge = CallEdgeV2.mint(
        source_contract_cid="blake3-512:" + "33" * 64,
        target_contract_cid="blake3-512:" + "44" * 64,
        call_site=call_site,
        formal_actual_bindings=(binding,),
    )

    wire = edge.to_value()
    assert "formalActualBindings" in wire
    assert "formalActuals" not in wire
    assert CallEdgeV2.from_value(wire) == edge

    malformed = {**wire, "formalActuals": {"x": term_to_value(binding.actual_term)}}
    with pytest.raises(ValueError, match="exact key set"):
        CallEdgeV2.from_value(malformed)


def test_duplicate_formal_coordinate_is_loud() -> None:
    source = "blake3-512:" + "55" * 64
    occurrence = ValueOccurrenceCoordinateV1.mint(_site(source, 3, 4))
    binding = FormalActualBindingV1(
        "blake3-512:" + "66" * 64,
        occurrence,
        TermValue(1).to_term(owner="test"),
    )
    with pytest.raises(ValueError, match="duplicate formal"):
        CallEdgeV2.mint(
            source_contract_cid="blake3-512:" + "77" * 64,
            target_contract_cid="blake3-512:" + "88" * 64,
            call_site=_site(source, 0, 9),
            formal_actual_bindings=(binding, binding),
        )


def test_contract_decl_content_addresses_formal_ownership_testimony() -> None:
    source = "blake3-512:" + "99" * 64
    owner = _site(source, 0, 10)
    declaration = _site(source, 4, 6)
    coordinate = FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=source,
        owner_definition_locus=owner,
        declaration_locus=declaration,
        ordinal=0,
        parameter_kind="positional-or-keyword",
        declared_name="xs",
        sort=PrimitiveSort("Value"),
    )
    value = json.loads(
        encode_jcs(
            contract_decl_to_value(
                ContractDecl(
                    "consume",
                    owner_source_identity_cid=source,
                    owner_definition_locus=owner.wire(),
                    formal_declarations=[coordinate.to_value()],
                )
            )
        )
    )
    assert value["ownerSourceIdentityCid"] == source
    assert value["ownerDefinitionLocus"] == owner.wire()
    assert value["formalDeclarations"] == [coordinate.to_value()]
