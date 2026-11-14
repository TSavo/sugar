from __future__ import annotations

import json

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import (
    ContractDecl,
    PrimitiveSort,
    contract_decl_to_value,
)


def _site(source: str, start: int, end: int) -> SourceFragmentCoordinateV1:
    return SourceFragmentCoordinateV1(source, 1, start, 1, end)


def test_contract_decl_content_addresses_formal_ownership_testimony() -> None:
    source = "blake3-512:" + "99" * 64
    owner = _site(source, 0, 10)
    coordinate = FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=source,
        owner_definition_locus=owner,
        declaration_locus=_site(source, 4, 6),
        ordinal=0,
        parameter_kind="positional-or-keyword",
        declared_name="items",
        sort=PrimitiveSort("Value"),
    )
    value = json.loads(
        encode_jcs(
            contract_decl_to_value(
                ContractDecl(
                    "transform",
                    owner_source_identity_cid=source,
                    owner_definition_locus=owner.wire(),
                    formal_declarations=[coordinate.to_value()],
                )
            )
        )
    )
    assert value["ownerSourceIdentityCid"] == source
    assert value["formalDeclarations"] == [coordinate.to_value()]
