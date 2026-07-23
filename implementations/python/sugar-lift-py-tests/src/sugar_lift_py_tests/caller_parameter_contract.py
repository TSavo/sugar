from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Any

from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs
from sugar_lift_py_tests.context_manager_contract import _json_value
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.ir import Formula, Term, formula_to_value, term_to_value


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


@dataclass(frozen=True)
class ParameterContractDemandV1:
    owner_source_identity_cid: str
    formal_coordinate_cid: str
    operation_site: SourceFragmentCoordinateV1
    demanded_formula: Formula
    candidate_cid: str
    demand_cid: str
    demanded_effect_bound: object | None = None
    kind: str = "parameter-contract-demand"
    schema_version: str = "1"

    @classmethod
    def mint(
        cls,
        *,
        owner_source_identity_cid: str,
        formal_coordinate_cid: str,
        operation_site: SourceFragmentCoordinateV1,
        demanded_formula: Formula,
        candidate_cid: str,
    ) -> "ParameterContractDemandV1":
        preimage = {
            "kind": "parameter-contract-demand",
            "schemaVersion": "1",
            "ownerSourceIdentityCid": owner_source_identity_cid,
            "formalCoordinateCid": formal_coordinate_cid,
            "operationSite": operation_site.wire(),
            "demandedFormula": _json(formula_to_value(demanded_formula)),
            "demandedEffectBound": None,
            "candidateCid": candidate_cid,
        }
        return cls(
            owner_source_identity_cid,
            formal_coordinate_cid,
            operation_site,
            demanded_formula,
            candidate_cid,
            _cid(preimage),
        )

    def to_value(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "schemaVersion": self.schema_version,
            "ownerSourceIdentityCid": self.owner_source_identity_cid,
            "formalCoordinateCid": self.formal_coordinate_cid,
            "operationSite": self.operation_site.wire(),
            "demandedFormula": _json(formula_to_value(self.demanded_formula)),
            "demandedEffectBound": None,
            "candidateCid": self.candidate_cid,
            "demandCid": self.demand_cid,
        }


@dataclass(frozen=True)
class ContractConditionalConstructionV1:
    source_node: SourceFragmentCoordinateV1
    candidate: Term
    candidate_cid: str
    demand: ParameterContractDemandV1
    value: FloorValue

    @classmethod
    def mint(
        cls,
        *,
        site,
        candidate: Term,
        demand_formula: Formula,
        value: FloorValue,
        coordinate,
    ):
        source_node = source_coordinate(site)
        candidate_preimage = {
            "kind": "parameter-contract-candidate",
            "schemaVersion": "1",
            "sourceNode": source_node.wire(),
            "candidate": _json(term_to_value(candidate)),
        }
        candidate_cid = _cid(candidate_preimage)
        demand = ParameterContractDemandV1.mint(
            owner_source_identity_cid=coordinate.owner_source_identity_cid,
            formal_coordinate_cid=coordinate.coordinate_cid,
            operation_site=source_node,
            demanded_formula=demand_formula,
            candidate_cid=candidate_cid,
        )
        return cls(source_node, candidate, candidate_cid, demand, value)

    def and_then(self, step):
        from sugar_lift_py_tests.outcome import Complete

        following = step(self.value)
        if isinstance(following, Complete):
            return replace(self, value=following.value)
        return following

    def contribution(self):
        return (self,)

    def inv_contribution(self):
        return self.value.inv_contribution()

    def post_contribution(self):
        return self.value.post_contribution()

    def derived_post_contribution(self):
        return self.value.derived_post_contribution()

    def edge_contribution(self, source_name):
        return self.value.edge_contribution(source_name)

    def follow(self):
        return self.value.follow_rest()

    def extend_scope(self, ctx):
        return self.value.extend_scope(ctx)

    def to_value(self) -> dict[str, Any]:
        return {
            "kind": "contract-conditional-construction",
            "schemaVersion": "1",
            "sourceNode": self.source_node.wire(),
            "candidate": _json(term_to_value(self.candidate)),
            "candidateCid": self.candidate_cid,
            "demand": self.demand.to_value(),
        }


@dataclass(frozen=True)
class ValueOccurrenceCoordinateV1:
    source: SourceFragmentCoordinateV1
    occurrence_cid: str

    @classmethod
    def mint(cls, source: SourceFragmentCoordinateV1):
        return cls(source, _cid({"kind": "value-occurrence", "source": source.wire()}))

    def to_value(self):
        return {"source": self.source.wire(), "occurrenceCid": self.occurrence_cid}

    @classmethod
    def from_value(cls, value):
        if not isinstance(value, dict) or set(value) != {"source", "occurrenceCid"}:
            raise ValueError("value occurrence requires an exact key set")
        result = cls(
            SourceFragmentCoordinateV1.decode(value["source"]), value["occurrenceCid"]
        )
        if result != cls.mint(result.source):
            raise ValueError("value occurrence CID is stale")
        return result


@dataclass(frozen=True)
class FormalActualBindingV1:
    formal_coordinate_cid: str
    actual_occurrence: ValueOccurrenceCoordinateV1
    actual_term: Term
    actual_contract_ref_cid: str | None = None

    def to_value(self):
        return {
            "formalCoordinateCid": self.formal_coordinate_cid,
            "actualOccurrence": self.actual_occurrence.to_value(),
            "actualTerm": _json(term_to_value(self.actual_term)),
            "actualContractRefCid": self.actual_contract_ref_cid,
        }

    @classmethod
    def from_value(cls, value):
        expected = {
            "formalCoordinateCid",
            "actualOccurrence",
            "actualTerm",
            "actualContractRefCid",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("formal actual binding requires an exact key set")
        return cls(
            value["formalCoordinateCid"],
            ValueOccurrenceCoordinateV1.from_value(value["actualOccurrence"]),
            _term_from_value(value["actualTerm"]),
            value["actualContractRefCid"],
        )


@dataclass(frozen=True)
class CallEdgeV2:
    source_contract_cid: str
    target_contract_cid: str
    call_site: SourceFragmentCoordinateV1
    formal_actual_bindings: tuple[FormalActualBindingV1, ...]
    edge_cid: str

    @classmethod
    def mint(
        cls,
        *,
        source_contract_cid,
        target_contract_cid,
        call_site,
        formal_actual_bindings,
    ):
        coordinates = tuple(
            binding.formal_coordinate_cid for binding in formal_actual_bindings
        )
        if len(set(coordinates)) != len(coordinates):
            raise ValueError("CallEdgeV2 has a duplicate formal coordinate")
        preimage = {
            "kind": "call-edge",
            "schemaVersion": "2",
            "sourceContractCid": source_contract_cid,
            "targetContractCid": target_contract_cid,
            "callSite": call_site.wire(),
            "formalActualBindings": [
                binding.to_value() for binding in formal_actual_bindings
            ],
        }
        return cls(
            source_contract_cid,
            target_contract_cid,
            call_site,
            tuple(formal_actual_bindings),
            _cid(preimage),
        )

    def to_value(self):
        return {
            "kind": "call-edge",
            "schemaVersion": "2",
            "sourceContractCid": self.source_contract_cid,
            "targetContractCid": self.target_contract_cid,
            "callSite": self.call_site.wire(),
            "formalActualBindings": [
                binding.to_value() for binding in self.formal_actual_bindings
            ],
            "edgeCid": self.edge_cid,
        }

    @classmethod
    def from_value(cls, value):
        expected = {
            "kind",
            "schemaVersion",
            "sourceContractCid",
            "targetContractCid",
            "callSite",
            "formalActualBindings",
            "edgeCid",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("CallEdgeV2 requires an exact key set")
        if value["kind"] != "call-edge" or value["schemaVersion"] != "2":
            raise ValueError("CallEdgeV2 has the wrong tag")
        result = cls.mint(
            source_contract_cid=value["sourceContractCid"],
            target_contract_cid=value["targetContractCid"],
            call_site=SourceFragmentCoordinateV1.decode(value["callSite"]),
            formal_actual_bindings=tuple(
                FormalActualBindingV1.from_value(item)
                for item in value["formalActualBindings"]
            ),
        )
        if result.edge_cid != value["edgeCid"]:
            raise ValueError("CallEdgeV2 CID is stale")
        return result


def _term_from_value(value):
    from sugar_lift_py_tests.ir import (
        bool_const,
        ctor,
        make_var,
        num,
        real_lit,
        str_const,
    )

    if not isinstance(value, dict):
        raise ValueError("actual term must be a ProofIR term")
    kind = value.get("kind")
    if kind == "var" and set(value) == {"kind", "name"}:
        return make_var(value["name"])
    if kind == "ctor" and set(value) == {"kind", "name", "args"}:
        return ctor(value["name"], [_term_from_value(item) for item in value["args"]])
    if kind == "const" and set(value) == {"kind", "value", "sort"}:
        sort = value["sort"].get("name") if isinstance(value["sort"], dict) else None
        if sort == "Int" and type(value["value"]) is int:
            return num(value["value"])
        if sort == "Bool" and type(value["value"]) is bool:
            return bool_const(value["value"])
        if sort == "String" and isinstance(value["value"], str):
            return str_const(value["value"])
        if sort == "Real" and isinstance(value["value"], str):
            return real_lit(value["value"])
    raise ValueError("actual term shape is unsupported")
