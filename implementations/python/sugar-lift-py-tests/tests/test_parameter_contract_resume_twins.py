"""Phase-3 resume decision twins: the exact-complete-set discipline + the
owner's continuation replay guard. A link unit owes no candidate (inventory item
43), so the good resume is the empty set; every corruption raises a loud
ResumeStalePanic (which the kit lifts to a ConstructionPanic; it never silently
reconstructs)."""

import pytest

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.caller_parameter_contract import (
    ParameterOwnedContractV1,
    ParameterContractLinkUnitV1,
    ParameterContractResolutionSetV1,
    resume_apply_resolutions,
    ResumeStalePanic,
    _cid,
)

SRC = "blake3-512:" + "a" * 128


def _link_unit():
    owner_def = SourceFragmentCoordinateV1(SRC, 1, 0, 10, 4)
    coord = FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=SRC,
        owner_definition_locus=owner_def,
        declaration_locus=SourceFragmentCoordinateV1(SRC, 1, 17, 1, 22),
        ordinal=0,
        parameter_kind="positional-or-keyword",
        declared_name="value",
        sort=PrimitiveSort("Value"),
    )
    owned = ParameterOwnedContractV1.mint(
        name="encodeBase64",
        owner_source_identity_cid=SRC,
        owner_definition_locus=owner_def,
        formal_coordinates=(coord,),
        declared_demand_cids=[],
    )
    unit = ParameterContractLinkUnitV1.mint(
        source_memento={"file": "vendor/b64vendor.py"},
        parameter_owned_contract=owned,
        candidates=(),
    )
    return unit, owned


def _resolution(contract_cid):
    pre = {
        "kind": "parameter-contract-resolution",
        "schemaVersion": "1",
        "demandCid": "blake3-512:" + "d" * 128,
        "candidateCid": "blake3-512:" + "c" * 128,
        "contractCid": contract_cid,
        "basis": "declared-demand",
        "callerUniverseCid": None,
    }
    return {**pre, "resolutionCid": _cid(pre)}


def test_twin_empty_set_honored():
    unit, _ = _link_unit()
    empty = ParameterContractResolutionSetV1.mint(
        link_unit_cid=unit.link_unit_cid, resolutions=()
    )
    assert resume_apply_resolutions(unit, empty) == {}


def test_twin_any_resolution_is_foreign():
    unit, owned = _link_unit()
    rset = ParameterContractResolutionSetV1.mint(
        link_unit_cid=unit.link_unit_cid, resolutions=(_resolution(owned.contract_cid),)
    )
    with pytest.raises(ResumeStalePanic, match="foreign demand"):
        resume_apply_resolutions(unit, rset)


def test_twin_stale_resolution_cid_panics():
    unit, owned = _link_unit()
    res = _resolution(owned.contract_cid)
    res["resolutionCid"] = "blake3-512:" + "0" * 128
    rset = ParameterContractResolutionSetV1.mint(
        link_unit_cid=unit.link_unit_cid, resolutions=(res,)
    )
    with pytest.raises(ResumeStalePanic, match="stale"):
        resume_apply_resolutions(unit, rset)


def test_twin_lost_continuation_panics():
    unit, _ = _link_unit()
    # a set minted for a DIFFERENT continuation key
    foreign = ParameterContractResolutionSetV1.mint(
        link_unit_cid="blake3-512:" + "9" * 128, resolutions=()
    )
    with pytest.raises(ResumeStalePanic, match="different continuation"):
        resume_apply_resolutions(unit, foreign)
