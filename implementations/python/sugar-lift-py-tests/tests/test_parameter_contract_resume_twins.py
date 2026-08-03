"""Phase-3 resume decision twins: the exact-complete-set discipline + the
owner's continuation replay guard. Each arm is a discrimination twin -- the good
resume is honored, every corruption raises a loud ResumeStalePanic (which the
kit lifts to a ConstructionPanic; it never silently reconstructs)."""

import types
import pytest

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort, atomic, make_var, ctor, num
from sugar_lift_py_tests.caller_parameter_contract import (
    ParameterOwnedContractV1,
    ContractConditionalConstructionV1,
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
    span = types.SimpleNamespace(start_line=3, start_col=9, end_line=3, end_col=17)
    site = types.SimpleNamespace(source_cid=SRC, line_col_span=span)
    cand = ContractConditionalConstructionV1.mint(
        site=site,
        candidate=ctor("py.subscript", [make_var("value"), num(0)]),
        demand_formula=atomic("python:indexable", [make_var("value")]),
        value=None,
        coordinate=coord,
    )
    owned = ParameterOwnedContractV1.mint(
        name="encodeBase64",
        owner_source_identity_cid=SRC,
        owner_definition_locus=owner_def,
        formal_coordinates=(coord,),
        declared_demand_cids=[cand.sole_demand().demand_cid],
    )
    unit = ParameterContractLinkUnitV1.mint(
        source_memento={"file": "vendor/b64vendor.py"},
        parameter_owned_contract=owned,
        candidates=(cand,),
        call_edges=(),
    )
    return unit, cand, owned


def _resolution(
    demand_cid, candidate_cid, contract_cid, basis="declared-demand", universe=None
):
    pre = {
        "kind": "parameter-contract-resolution",
        "schemaVersion": "1",
        "demandCid": demand_cid,
        "candidateCid": candidate_cid,
        "contractCid": contract_cid,
        "basis": basis,
        "callerUniverseCid": universe,
    }
    return {**pre, "resolutionCid": _cid(pre)}


def _good_set(unit, cand, owned):
    res = _resolution(
        cand.sole_demand().demand_cid, cand.candidate_cid, owned.contract_cid
    )
    return (
        ParameterContractResolutionSetV1.mint(
            link_unit_cid=unit.link_unit_cid, resolutions=(res,)
        ),
        res,
    )


def test_twin_standalone_self_declared_honored():
    unit, cand, owned = _link_unit()
    rset, res = _good_set(unit, cand, owned)
    accepted = resume_apply_resolutions(unit, rset)
    assert accepted[cand.sole_demand().demand_cid] == res


def test_twin_missing_resolution_panics():
    unit, cand, owned = _link_unit()
    empty = ParameterContractResolutionSetV1.mint(
        link_unit_cid=unit.link_unit_cid, resolutions=()
    )
    with pytest.raises(ResumeStalePanic, match="incomplete"):
        resume_apply_resolutions(unit, empty)


def test_twin_duplicate_resolution_panics():
    unit, cand, owned = _link_unit()
    res = _resolution(
        cand.sole_demand().demand_cid, cand.candidate_cid, owned.contract_cid
    )
    rset = ParameterContractResolutionSetV1.mint(
        link_unit_cid=unit.link_unit_cid, resolutions=(res, res)
    )
    with pytest.raises(ResumeStalePanic, match="duplicate"):
        resume_apply_resolutions(unit, rset)


def test_twin_stale_resolution_cid_panics():
    unit, cand, owned = _link_unit()
    res = _resolution(
        cand.sole_demand().demand_cid, cand.candidate_cid, owned.contract_cid
    )
    res["resolutionCid"] = "blake3-512:" + "0" * 128
    rset = ParameterContractResolutionSetV1.mint(
        link_unit_cid=unit.link_unit_cid, resolutions=(res,)
    )
    with pytest.raises(ResumeStalePanic, match="stale"):
        resume_apply_resolutions(unit, rset)


def test_twin_foreign_contract_panics():
    unit, cand, owned = _link_unit()
    res = _resolution(
        cand.sole_demand().demand_cid, cand.candidate_cid, "blake3-512:" + "f" * 128
    )
    rset = ParameterContractResolutionSetV1.mint(
        link_unit_cid=unit.link_unit_cid, resolutions=(res,)
    )
    with pytest.raises(ResumeStalePanic, match="foreign contract"):
        resume_apply_resolutions(unit, rset)


def test_twin_wrong_candidate_panics():
    unit, cand, owned = _link_unit()
    res = _resolution(
        cand.sole_demand().demand_cid, "blake3-512:" + "c" * 128, owned.contract_cid
    )
    rset = ParameterContractResolutionSetV1.mint(
        link_unit_cid=unit.link_unit_cid, resolutions=(res,)
    )
    with pytest.raises(ResumeStalePanic, match="wrong candidate"):
        resume_apply_resolutions(unit, rset)


def test_twin_lost_continuation_panics():
    unit, cand, owned = _link_unit()
    res = _resolution(
        cand.sole_demand().demand_cid, cand.candidate_cid, owned.contract_cid
    )
    # a set minted for a DIFFERENT continuation key
    foreign = ParameterContractResolutionSetV1.mint(
        link_unit_cid="blake3-512:" + "9" * 128, resolutions=(res,)
    )
    with pytest.raises(ResumeStalePanic, match="different continuation"):
        resume_apply_resolutions(unit, foreign)
