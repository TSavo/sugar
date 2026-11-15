"""Frozen, authenticated context-manager coordinates installed before construction."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .canonicalizer import blake3_512_of, encode_jcs
from .context_manager_contract import (
    ContextManagerContractError,
    ContextManagerSemanticsV1,
    ImportSignatureV2,
    decode_context_manager_semantics_v1,
    decode_import_signature_v2,
    _json_value,
)
from .ir import Sort


class ContractRefProtocolError(ValueError):
    pass


class NativeProtocolSlot(str, Enum):
    """Closed source protocol slots, independent of vendor member spelling."""

    CONTEXT_ENTER = "context-enter"
    CONTEXT_EXIT = "context-exit"
    TRUTH = "truth"
    SET_ITEM = "set-item"
    GET_ITEM = "get-item"


@dataclass(frozen=True, order=True)
class SourceFragmentCoordinateV1:
    source_cid: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int

    @classmethod
    def decode(cls, raw: Any) -> "SourceFragmentCoordinateV1":
        if not isinstance(raw, dict) or set(raw) != {
            "sourceCid",
            "startLine",
            "startCol",
            "endLine",
            "endCol",
        }:
            raise ContractRefProtocolError("malformed source-fragment coordinate")
        values = (raw["startLine"], raw["startCol"], raw["endLine"], raw["endCol"])
        if not isinstance(raw["sourceCid"], str) or not all(
            isinstance(value, int) and value >= 0 for value in values
        ):
            raise ContractRefProtocolError(
                "malformed source-fragment coordinate fields"
            )
        return cls(raw["sourceCid"], *values)

    def wire(self) -> dict[str, Any]:
        return {
            "sourceCid": self.source_cid,
            "startLine": self.start_line,
            "startCol": self.start_col,
            "endLine": self.end_line,
            "endCol": self.end_col,
        }

    @property
    def cid(self) -> str:
        """Canonical CID of this owner's existing wire representation."""
        from sugar_lift_python_source.canonical import cid_of_json

        return cid_of_json(self.wire())


@dataclass(frozen=True)
class ContextManagerContractRefV1:
    resolution_cid: str
    demand_cid: str
    use_site: SourceFragmentCoordinateV1
    use_site_cid: str
    authenticated_import_use_cid: str
    import_binding_cid: str
    construction_context_generation_cid: str
    contract_cid: str
    payload_cid: str
    provenance_cid: str
    distribution_artifact_cid: str
    dependency_artifact_graph_cid: str
    module_source_cid: str
    resolved_definition_cid: str
    manager_construction_cid: str
    enter_testimony_cid: str
    exit_testimony_cid: str
    import_signature: ImportSignatureV2
    semantics: ContextManagerSemanticsV1


#: The one statement for a gap nothing here decides (#7757 item 4): which
#: exception was caught, or which default a row carried, never chooses a label.
#: What was observed rides in the gap's detail.
UNDECIDED_GAP_KIND = "undecided"


@dataclass(frozen=True)
class ContextManagerResolutionGapV1:
    """One unresolved context-manager demand: a structural kind beside its data.

    ``kind`` is the STRUCTURAL key and nothing else -- a member of the closed
    vocabulary in :func:`_gap_kinds`.  It never contains a symbol.  The
    derivation layer used to fuse ``f"{kind}:{detail}"`` into this field, which
    put most of the pinned-pandas resolution board's mass under a vendor spelling
    (#6371) and produced, in process, a gap this module's own decoder would
    refuse.

    ``target_symbol`` and ``detail`` are DATA: they ride the row for a human
    reading one row, and are never a bucket key.  A measurement a vendor rename
    can move is not a measurement.

    Unresolved demand after derivation: construct the contract or panic.
    """

    demand_cid: str
    use_site: SourceFragmentCoordinateV1
    target_symbol: str | None
    kind: str
    candidate_member_cids: tuple[str, ...]
    # In-process only.  Not read from or written to the wire, so no preimage
    # and no CID changes: the authenticated table hashes the bytes present.
    detail: str | None = None


ContextManagerResolutionV1 = ContextManagerContractRefV1 | ContextManagerResolutionGapV1


@dataclass(frozen=True)
class TreeConstructionContextV1:
    """Explicit tree construction handle: the workspace a tree is built under.

    It holds no table (#7757). A ``with``'s manager is what its head reduces
    to (``With._reduced_manager_sugar``); a call's frame is the one its own
    lexical row's definition applies (``Call._construct_sugar``). Nothing
    outside the tree fills anything a node reads here.
    """

    workspace_root: str | None = None

    @classmethod
    def for_source_call_construction(
        cls,
        *,
        workspace_root: str | None = None,
    ) -> "TreeConstructionContextV1":
        """A construction context naming ``workspace_root`` (or none)."""
        return cls(workspace_root=workspace_root)

    @classmethod
    def for_test_without_workspace(cls) -> "TreeConstructionContextV1":
        """A caller ASSERTING it has no workspace. The name is the claim.

        Use this only where the assertion is true: a test that builds one
        function from a string literal, in a throwaway ``tempfile`` directory,
        with no corpus and no cross-language bridge to name. Every lookup
        through the returned context then answers "looked up, genuinely
        absent" -- which is a FACT, and is exactly the state
        ``_require_construction_context`` was built to make distinguishable
        from "this tree was opened without a context" (an instrument defect).

        WHAT IT DOES NOT MEAN, and why this constructor exists at all.
        ``workspace_root`` is None here, and ``workspace_root`` gates
        ``FunctionDef``'s ``bridge_source_symbol``. So a value constructed
        through this context is BYTE-IDENTICAL to the one the bare door
        produced -- ``bridge_source_symbol=None`` either way -- with the
        refusal removed::

            bare door                : bridge_source_symbol=None
            this context             : bridge_source_symbol=None
            a real workspace context : 'python:subject.module_level'

        Turning a loud refusal into a silent construction of the same answer is
        the defect this law exists to eliminate. It is legitimate HERE only
        because the caller genuinely has no workspace, and illegitimate the
        moment that is untrue.

        That is why this is a distinct constructor and not
        ``for_source_call_construction()`` with a default. "No workspace" is a
        claim about the CALLER, it has to be made per caller, and it must not
        arrive by inheritance in a file nobody read. Spelled this way it is
        explicit, greppable and auditable: every site that asserts it says so
        in the name, and a reviewer can enumerate them.

        ``test_an_empty_context_constructs_the_bare_doors_value`` pins the
        three-way result above, so a suite that goes green through this door
        can never be read as evidence the enrichment came back.
        """
        return cls.for_source_call_construction()


def _gap_kinds() -> None:
    """Deleted closed taxonomy. Kinds are free structural keys, not a census enum."""
    return None


def _cid(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("blake3-512:"):
        raise ContractRefProtocolError(f"{field} must be a CID")
    return value


def _decode_signature(raw: Any) -> ImportSignatureV2:
    try:
        return decode_import_signature_v2(raw)
    except ContextManagerContractError as exc:
        raise ContractRefProtocolError("malformed ImportSignatureV2") from exc


def _resolution_cid_preimage(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        key: raw[key]
        for key in (
            "schemaVersion",
            "demandCid",
            "useSite",
            "useSiteCid",
            "authenticatedImportUseCid",
            "importBindingCid",
            "constructionContextGenerationCid",
            "contractCid",
            "payloadCid",
            "provenanceCid",
            "distributionArtifactCid",
            "dependencyArtifactGraphCid",
            "moduleSourceCid",
            "resolvedDefinitionCid",
            "managerConstructionCid",
            "enterTestimonyCid",
            "exitTestimonyCid",
            "importSignature",
            "semantics",
        )
    }


def _hash_json(raw: Any) -> str:
    return blake3_512_of(encode_jcs(_json_value(raw)).encode("utf-8"))


def _decode_ref(raw: Any) -> ContextManagerContractRefV1:
    expected = {
        "kind",
        "schemaVersion",
        "resolutionCid",
        "demandCid",
        "useSite",
        "useSiteCid",
        "authenticatedImportUseCid",
        "importBindingCid",
        "constructionContextGenerationCid",
        "contractCid",
        "payloadCid",
        "provenanceCid",
        "distributionArtifactCid",
        "dependencyArtifactGraphCid",
        "moduleSourceCid",
        "resolvedDefinitionCid",
        "managerConstructionCid",
        "enterTestimonyCid",
        "exitTestimonyCid",
        "importSignature",
        "semantics",
    }
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ContractRefProtocolError("malformed context-manager contract ref")
    if raw["kind"] != "context-manager-contract-ref" or raw["schemaVersion"] != "1":
        raise ContractRefProtocolError("unsupported context-manager contract ref")
    resolution_cid = _cid(raw["resolutionCid"], "resolutionCid")
    if _hash_json(_resolution_cid_preimage(raw)) != resolution_cid:
        raise ContractRefProtocolError("resolution CID mismatch")
    try:
        signature = _decode_signature(raw["importSignature"])
        semantics = decode_context_manager_semantics_v1(raw["semantics"], signature)
    except ContextManagerContractError as exc:
        raise ContractRefProtocolError("unsupported context-manager semantics") from exc
    use_site = SourceFragmentCoordinateV1.decode(raw["useSite"])
    if _hash_json(use_site.wire()) != _cid(raw["useSiteCid"], "useSiteCid"):
        raise ContractRefProtocolError("use-site CID mismatch")
    return ContextManagerContractRefV1(
        resolution_cid,
        _cid(raw["demandCid"], "demandCid"),
        use_site,
        _cid(raw["useSiteCid"], "useSiteCid"),
        _cid(raw["authenticatedImportUseCid"], "authenticatedImportUseCid"),
        _cid(raw["importBindingCid"], "importBindingCid"),
        _cid(
            raw["constructionContextGenerationCid"], "constructionContextGenerationCid"
        ),
        _cid(raw["contractCid"], "contractCid"),
        _cid(raw["payloadCid"], "payloadCid"),
        _cid(raw["provenanceCid"], "provenanceCid"),
        _cid(raw["distributionArtifactCid"], "distributionArtifactCid"),
        _cid(raw["dependencyArtifactGraphCid"], "dependencyArtifactGraphCid"),
        _cid(raw["moduleSourceCid"], "moduleSourceCid"),
        _cid(raw["resolvedDefinitionCid"], "resolvedDefinitionCid"),
        _cid(raw["managerConstructionCid"], "managerConstructionCid"),
        _cid(raw["enterTestimonyCid"], "enterTestimonyCid"),
        _cid(raw["exitTestimonyCid"], "exitTestimonyCid"),
        signature,
        semantics,
    )


