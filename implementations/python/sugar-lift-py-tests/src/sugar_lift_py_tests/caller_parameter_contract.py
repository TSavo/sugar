from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.context_manager_contract import _json_value


def _json(value) -> Any:
    return json.loads(encode_jcs(value))


def _cid(value: Any) -> str:
    return blake3_512_of(encode_jcs(_json_value(value)).encode("utf-8"))


def source_coordinate(site) -> SourceFragmentCoordinateV1:
    span = site.line_col_span
    return SourceFragmentCoordinateV1(
        site.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


# --- Phase 1/2/3 continuation schema (mirrors sugar-linker/src/caller_parameter.rs) ---


@dataclass(frozen=True)
class ParameterOwnedContractV1:
    """The callee's structural identity: its formals + the demands it
    STRUCTURALLY OWNS, independent of any post projection. `semantic_decl` is a
    contract declaration whose JCS CID is `contract_cid`; the four ownership
    sub-fields are re-derived byte-for-byte by Rust `ParameterOwnedContractV1::
    validate` against the sibling fields."""

    contract_cid: str
    semantic_decl: Any
    owner_source_identity_cid: str
    owner_definition_locus: SourceFragmentCoordinateV1
    formal_coordinates: tuple
    formal_sorts: tuple
    declared_demand_cids: tuple

    @classmethod
    def mint(
        cls,
        *,
        name: str,
        owner_source_identity_cid: str,
        owner_definition_locus: SourceFragmentCoordinateV1,
        formal_coordinates: tuple,
        declared_demand_cids,
    ) -> "ParameterOwnedContractV1":
        from sugar_lift_py_tests.ir import ContractDecl, contract_decl_to_value

        coords = tuple(formal_coordinates)
        # Rust BTreeSet<Cid>: sorted, de-duplicated.
        declared = tuple(sorted(set(declared_demand_cids)))
        formal_declarations = [
            {"coordinate": coordinate.to_value()} for coordinate in coords
        ]
        decl = ContractDecl(
            name=name,
            owner_source_identity_cid=owner_source_identity_cid,
            owner_definition_locus=owner_definition_locus.wire(),
            formal_declarations=formal_declarations,
            declared_parameter_demand_cids=list(declared),
        )
        semantic_decl = _json(contract_decl_to_value(decl))
        return cls(
            contract_cid=_cid(semantic_decl),
            semantic_decl=semantic_decl,
            owner_source_identity_cid=owner_source_identity_cid,
            owner_definition_locus=owner_definition_locus,
            formal_coordinates=coords,
            formal_sorts=tuple(coordinate.sort for coordinate in coords),
            declared_demand_cids=declared,
        )

    def to_value(self) -> dict[str, Any]:
        return {
            "contractCid": self.contract_cid,
            "semanticDecl": self.semantic_decl,
            "ownerSourceIdentityCid": self.owner_source_identity_cid,
            "ownerDefinitionLocus": self.owner_definition_locus.wire(),
            "formalDeclarations": [
                {"coordinate": coordinate.to_value()}
                for coordinate in self.formal_coordinates
            ],
            "formalSorts": [
                {"kind": "primitive", "name": sort.name} for sort in self.formal_sorts
            ],
            "declaredDemandCids": list(self.declared_demand_cids),
        }


@dataclass(frozen=True)
class ParameterContractLinkUnitV1:
    """One function's closed enrollment row: its owned contract, its candidates
    (none: nothing in the lift owes a parameter contract, inventory item 43),
    and the retained continuation key `link_unit_cid`.

    It records no call. A Python call's only record is its `undecided` member
    (step 8; PR B on #7766); the link unit's edge list, always empty for
    Python, is gone."""

    source_memento: Any
    parameter_owned_contract: ParameterOwnedContractV1
    candidates: tuple
    link_unit_cid: str

    @classmethod
    def mint(cls, *, source_memento, parameter_owned_contract, candidates):
        cands = tuple(candidates)
        preimage = {
            "kind": "parameter-contract-link-unit",
            "schemaVersion": "1",
            "sourceMemento": source_memento,
            "parameterOwnedContract": parameter_owned_contract.to_value(),
            "candidates": [candidate.to_value() for candidate in cands],
        }
        return cls(source_memento, parameter_owned_contract, cands, _cid(preimage))

    def to_value(self) -> dict[str, Any]:
        return {
            "kind": "parameter-contract-link-unit",
            "schemaVersion": "1",
            "sourceMemento": self.source_memento,
            "parameterOwnedContract": self.parameter_owned_contract.to_value(),
            "candidates": [candidate.to_value() for candidate in self.candidates],
            "linkUnitCid": self.link_unit_cid,
        }


@dataclass(frozen=True)
class ParameterContractResolutionSetV1:
    """The Phase-2 fold's authenticated verdict set, bound to the continuation
    it discharges. `set_cid` mutually binds `link_unit_cid` (the replay guard):
    a resume accepts a set ONLY when both CIDs agree with the retained
    continuation."""

    link_unit_cid: str
    resolutions: tuple
    set_cid: str

    @classmethod
    def mint(cls, *, link_unit_cid: str, resolutions):
        rows = tuple(resolutions)
        preimage = {
            "kind": "parameter-contract-resolution-set",
            "schemaVersion": "1",
            "linkUnitCid": link_unit_cid,
            "resolutions": list(rows),
        }
        return cls(link_unit_cid, rows, _cid(preimage))

    @classmethod
    def from_value(cls, value) -> "ParameterContractResolutionSetV1":
        expected = {"kind", "schemaVersion", "linkUnitCid", "resolutions", "setCid"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("resolution set requires an exact key set")
        result = cls.mint(
            link_unit_cid=value["linkUnitCid"],
            resolutions=tuple(value["resolutions"]),
        )
        if (
            value["kind"] != "parameter-contract-resolution-set"
            or value["schemaVersion"] != "1"
            or result.set_cid != value["setCid"]
        ):
            raise ValueError("resolution set CID is stale")
        return result

    def to_value(self) -> dict[str, Any]:
        return {
            "kind": "parameter-contract-resolution-set",
            "schemaVersion": "1",
            "linkUnitCid": self.link_unit_cid,
            "resolutions": list(self.resolutions),
            "setCid": self.set_cid,
        }


class ResumeStalePanic(Exception):
    """A resume that could not be honored: loud, never a silent reconstruction."""


def _resolution_preimage(resolution: dict) -> dict:
    return {
        "kind": resolution["kind"],
        "schemaVersion": resolution["schemaVersion"],
        "demandCid": resolution["demandCid"],
        "candidateCid": resolution["candidateCid"],
        "contractCid": resolution["contractCid"],
        "basis": resolution["basis"],
        "callerUniverseCid": resolution["callerUniverseCid"],
    }


def _validate_resolution(resolution: dict) -> None:
    expected = {
        "kind",
        "schemaVersion",
        "demandCid",
        "candidateCid",
        "contractCid",
        "basis",
        "callerUniverseCid",
        "resolutionCid",
    }
    if not isinstance(resolution, dict) or set(resolution) != expected:
        raise ResumeStalePanic("resolution requires an exact key set")
    if (
        resolution["kind"] != "parameter-contract-resolution"
        or resolution["schemaVersion"] != "1"
        or _cid(_resolution_preimage(resolution)) != resolution["resolutionCid"]
    ):
        raise ResumeStalePanic("resolution CID is stale")
    basis = resolution["basis"]
    if basis == "declared-demand":
        if resolution["callerUniverseCid"] is not None:
            raise ResumeStalePanic(
                "declared-demand resolution carries a caller universe"
            )
    elif basis == "closed-callers":
        if resolution["callerUniverseCid"] is None:
            raise ResumeStalePanic("closed-callers resolution lacks a caller universe")
    else:
        raise ResumeStalePanic("resolution basis is unknown")


def resume_apply_resolutions(link_unit, resolution_set) -> dict[str, dict]:
    """The Phase-3 resume decision. Given the RETAINED link unit (the immutable
    continuation) and the presented resolution set, honor the resume ONLY when
    the set is bound to THIS continuation (the replay guard:
    resolution_set.link_unit_cid == link_unit.link_unit_cid, and set_cid
    re-derives, checked by ParameterContractResolutionSetV1.from_value) and
    names no demand: a link unit owes no candidate (inventory item 43), so every
    presented resolution is foreign. Each one is validated first, so a stale
    CID is named as stale.

    Returns ``{}`` on success; raises ResumeStalePanic (which the caller lifts to
    a ConstructionPanic) otherwise. Never reconstructs.
    """
    if resolution_set.link_unit_cid != link_unit.link_unit_cid:
        raise ResumeStalePanic(
            "resolution set is bound to a different continuation "
            f"({resolution_set.link_unit_cid} != {link_unit.link_unit_cid})"
        )
    for resolution in resolution_set.resolutions:
        _validate_resolution(resolution)
        raise ResumeStalePanic(
            f"resolution for a foreign demand {resolution['demandCid']}"
        )
    return {}


def function_link_unit(fn, def_memento):
    """A function's ParameterContractLinkUnitV1, read off the def itself.

    The unit is the callee's structural identity: its name and its own formal
    coordinates (``FunctionDef.formal_coordinates``), no owned demand and no
    candidate. Nothing in the lift owes a parameter contract (inventory item
    43), so nothing of the body is read: no reduction, no outcome, no arm.
    ``None`` for a def with no formal (no unit to link).
    """
    coords = tuple(fn.formal_coordinates())
    if not coords:
        return None
    owned = ParameterOwnedContractV1.mint(
        name=fn.name,
        owner_source_identity_cid=coords[0].owner_source_identity_cid,
        owner_definition_locus=coords[0].owner_definition_locus,
        formal_coordinates=coords,
        declared_demand_cids=[],
    )
    return ParameterContractLinkUnitV1.mint(
        source_memento=def_memento,
        parameter_owned_contract=owned,
        candidates=(),
    )
