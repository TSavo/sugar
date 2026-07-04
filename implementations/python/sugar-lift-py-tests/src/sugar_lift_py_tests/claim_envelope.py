# SPDX-License-Identifier: MIT OR Apache-2.0
#
# Claim-envelope minter (v1.2 layered shape).
#
# `mint_contract` / `mint_bridge` / `mint_implication` build a signed
# memento in the v1.2 LAYERED shape introduced by
# `protocol/specs/2026-05-03-substrate-layers-envelope-header-body.md`:
#
#   { "envelope": {...}, "header": {...}, "metadata": {...} }
#
#   * envelope = { signer, declaredAt, signature }
#       The signature is computed over JCS({"header": header,
#       "metadata": metadata}). The envelope's CID (= attestation CID)
#       is BLAKE3-512(JCS(envelope)) AFTER the signature has been
#       embedded.
#
#   * header   = substrate-load-bearing data the verifier reads:
#                schemaVersion, kind, cid, plus kind-specific REQUIRED
#                fields and the derived hashes (bindingHash,
#                propertyHash, verdict, inputCids) used by the
#                resolve/index pipeline.
#
#   * metadata = everything else (authoring attribution, lifecycle
#                strings like producedBy/producedAt, derived per-formula
#                hashes that are pure tooling convenience). Opaque to
#                the substrate verifier; signed transitively via the
#                envelope.
#
# Reference (authoritative):
#   implementations/rust/sugar-claim-envelope/src/lib.rs
#
# Cross-kit byte-equivalence:
#   The Python output is byte-identical to the Rust kit for the same
#   canonical input. See test_claim_envelope.py cross-kit-bytes tests.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple, Union

from .canonicalizer import (
    Value,
    blake3_512_of,
    encode_jcs,
    varr,
    vint,
    vobj,
    vstr,
)
from .ir import ContractDecl, formula_to_value
from .signing import (
    Signer,
    ed25519_pubkey_string,
    ed25519_sign_string,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The layered-shape schema version stamped into every memento header
# emitted by this kit. Older flat mementos carry "1"; verifiers branch
# on this string at load time.
LAYERED_SCHEMA_VERSION: str = "2"


# ---------------------------------------------------------------------------
# Authoring (typed union mirrored from the C++/Rust kits)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthoringKitAuthor:
    """Authoring block: hand-authored by a human or kit, no inference.

    `note` is optional. Empty string is treated as absent (matches Rust).
    """

    author: str
    note: Optional[str] = None


@dataclass(frozen=True)
class AuthoringLift:
    """Authoring block: produced by a structural lifter from source.

    `evidence` is the lifter's classification of how the contract was
    inferred ("tests", "types", "docs", "symbolic-exec"). `source_cid`
    is optional; empty string is treated as absent (matches Rust).
    """

    lifter: str
    evidence: str
    source_cid: Optional[str] = None


@dataclass(frozen=True)
class AuthoringLlm:
    """Authoring block: produced by an LLM, with prompt provenance.

    `confidence` is a float in [0, 1]; serialized as `int(confidence *
    1000)` (truncating toward zero, matching Rust's `as i64` cast).
    `rationale` is optional; empty string is treated as absent.
    """

    llm: str
    llm_version: str
    prompt_cid: str
    confidence: float
    rationale: Optional[str] = None


# Tagged union over the three authoring shapes.
Authoring = Union[AuthoringKitAuthor, AuthoringLift, AuthoringLlm]


def _authoring_to_value(a: Authoring) -> Value:
    """Lower an Authoring block to a canonicalizer Value tree.

    Mirrors `authoring_to_value` in the Rust kit. Insertion order is
    preserved here for readability; JCS sorts keys at emit time, so the
    resulting bytes are identical regardless of insertion order.
    """
    if isinstance(a, AuthoringKitAuthor):
        pairs: List[Tuple[str, Value]] = [
            ("producerKind", vstr("kit-author")),
            ("author", vstr(a.author)),
        ]
        if a.note is not None and a.note != "":
            pairs.append(("note", vstr(a.note)))
        return vobj(pairs)
    if isinstance(a, AuthoringLift):
        pairs = [
            ("producerKind", vstr("lift")),
            ("lifter", vstr(a.lifter)),
            ("evidence", vstr(a.evidence)),
        ]
        if a.source_cid is not None and a.source_cid != "":
            pairs.append(("sourceCid", vstr(a.source_cid)))
        return vobj(pairs)
    if isinstance(a, AuthoringLlm):
        # Match Rust's `(confidence * 1000.0) as i64` -- truncation
        # toward zero, NOT rounding. `int(x)` on a float in Python
        # truncates toward zero, matching Rust's `as i64` cast for
        # finite non-NaN values.
        confidence_i = int(a.confidence * 1000.0)
        pairs = [
            ("producerKind", vstr("llm")),
            ("llm", vstr(a.llm)),
            ("llmVersion", vstr(a.llm_version)),
            ("promptCid", vstr(a.prompt_cid)),
            ("confidence", vint(confidence_i)),
        ]
        if a.rationale is not None and a.rationale != "":
            pairs.append(("rationale", vstr(a.rationale)))
        return vobj(pairs)
    raise TypeError(f"unknown Authoring variant: {type(a)!r}")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ClaimEnvelopeError(Exception):
    """Base error for claim-envelope construction."""


class EmptyContractError(ClaimEnvelopeError):
    """`mint_contract` rejected: at least one of pre/post/inv must be present."""


class EmptyOutBindingError(ClaimEnvelopeError):
    """`mint_contract` rejected: outBinding must not be empty."""


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimEnvelope:
    """Result of minting a layered claim envelope.

    Mirrors `MintedEnvelope` in Rust kit. Three fields:

    - `canonical_bytes`: JCS-canonical bytes of the full layered memento
      ``{envelope, header, metadata}``. This is what consumers store /
      transmit / re-hash.

    - `cid`: the attestation CID = BLAKE3-512(JCS(envelope)) AFTER the
      signature has been embedded. This identifies the SIGNED attestation
      and is what goes into bundle members maps. Self-identifying string
      form: ``"blake3-512:<128 hex>"``.

    - `contract_cid`: the signer-independent content CID for contract
      mementos (= BLAKE3-512(JCS({name, outBinding, pre?, post?, inv?}))).
      Empty string for bridges and implications. Two distinct signers
      attesting to the same logical contract produce the same
      `contract_cid`.
    """

    canonical_bytes: bytes
    cid: str
    contract_cid: str

    # ---- Constructors ------------------------------------------------------

    @classmethod
    def from_contract_decl(
        cls,
        decl: ContractDecl,
        signer: Signer,
        *,
        produced_at: str,
        authoring: Optional[Authoring] = None,
        input_cids: Optional[Sequence[str]] = None,
    ) -> "ClaimEnvelope":
        """Build a v1.2-layered ClaimEnvelope from a python `ContractDecl`.

        The `decl`'s `Formula` clauses (pre/post/inv) are lowered to
        canonicalizer Value trees via `ir.formula_to_value` before
        delegating to `mint_contract`.

        Required:
          - `decl`: the contract declaration with name, outBinding,
            and at least one of pre/post/inv populated.
          - `signer`: a `Signer` carrying the Ed25519 seed and producer-id.
          - `produced_at`: ISO-8601 timestamp (ms precision, trailing 'Z').

        Optional:
          - `authoring`: defaults to AuthoringKitAuthor(author=signer.producer_id).
          - `input_cids`: defaults to []; the order is canonicalized
            (sorted lex) inside the header.
        """
        pre_v = formula_to_value(decl.pre) if decl.pre is not None else None
        post_v = formula_to_value(decl.post) if decl.post is not None else None
        inv_v = formula_to_value(decl.inv) if decl.inv is not None else None
        if authoring is None:
            authoring = AuthoringKitAuthor(author=signer.producer_id)
        return mint_contract(
            contract_name=decl.name,
            out_binding=decl.out_binding,
            pre=pre_v,
            post=post_v,
            inv=inv_v,
            produced_by=signer.producer_id,
            produced_at=produced_at,
            authoring=authoring,
            input_cids=list(input_cids) if input_cids is not None else [],
            signer_seed=signer.seed,
        )


# ---------------------------------------------------------------------------
# Internal helpers (mirror the rust `lib.rs` private functions byte-for-byte)
# ---------------------------------------------------------------------------


def _hash_value(v: Value) -> str:
    """BLAKE3-512 of the JCS encoding of ``v``."""
    return blake3_512_of(encode_jcs(v).encode("utf-8"))


def _hash_string(s: str) -> str:
    """BLAKE3-512 of the UTF-8 bytes of ``s``."""
    return blake3_512_of(s.encode("utf-8"))


def _signing_bytes(header: Value, metadata: Value) -> bytes:
    """JCS-canonical bytes of ``{"header": header, "metadata": metadata}``.

    This is the message the envelope's Ed25519 signature covers, per
    substrate-layers spec §2 R2. Critical: the key is "metadata", not
    "body". The substrate verifier signs over the metadata field-name.
    """
    msg = vobj(
        [
            ("header", header),
            ("metadata", metadata),
        ]
    )
    return encode_jcs(msg).encode("utf-8")


def _build_header(
    kind: str,
    header_cid: str,
    kind_specific: List[Tuple[str, Value]],
) -> Value:
    """Build a header object: schemaVersion, kind, cid, then kind-specific.

    Insertion order: schemaVersion, kind, cid, then the kind-specific
    REQUIRED fields. JCS will sort the final keys at emit time, so the
    insertion order does not affect byte output, but mirrors Rust for
    traceability.
    """
    pairs: List[Tuple[str, Value]] = [
        ("schemaVersion", vstr(LAYERED_SCHEMA_VERSION)),
        ("kind", vstr(kind)),
        ("cid", vstr(header_cid)),
    ]
    pairs.extend(kind_specific)
    return vobj(pairs)


def _assemble_layered(
    header: Value,
    metadata: Value,
    declared_at: str,
    signer_seed: bytes,
    content_cid: str,
) -> ClaimEnvelope:
    """Sign the (header, metadata) pair and emit the full layered memento.

    Mirrors `assemble_layered` in Rust:
      1. signer = ed25519_pubkey_string(signer_seed)
      2. signing_msg = JCS({"header": header, "metadata": metadata})
      3. signature = ed25519_sign_string(signer_seed, signing_msg)
      4. envelope = {signer, declaredAt, signature}
      5. attestation_cid = BLAKE3-512(JCS(envelope))   <-- after signing
      6. memento = {envelope, header, metadata}
      7. canonical_bytes = JCS(memento) -> UTF-8

    `content_cid` is the signer-independent contract CID for contracts;
    empty string for bridges and implications.
    """
    signer_str = ed25519_pubkey_string(signer_seed)
    signing_msg = _signing_bytes(header, metadata)
    signature_str = ed25519_sign_string(signer_seed, signing_msg)

    envelope = vobj(
        [
            ("signer", vstr(signer_str)),
            ("declaredAt", vstr(declared_at)),
            ("signature", vstr(signature_str)),
        ]
    )
    envelope_jcs = encode_jcs(envelope)
    attestation_cid = blake3_512_of(envelope_jcs.encode("utf-8"))

    memento = vobj(
        [
            ("envelope", envelope),
            ("header", header),
            ("metadata", metadata),
        ]
    )
    memento_jcs = encode_jcs(memento)

    return ClaimEnvelope(
        canonical_bytes=memento_jcs.encode("utf-8"),
        cid=attestation_cid,
        contract_cid=content_cid,
    )


# ---------------------------------------------------------------------------
# Contract minting
# ---------------------------------------------------------------------------


def contract_cid(
    *,
    contract_name: str,
    out_binding: str,
    pre: Optional[Value] = None,
    post: Optional[Value] = None,
    inv: Optional[Value] = None,
) -> str:
    """Compute the **content** CID of a contract (signer-independent).

    Per ``protocol/specs/2026-05-03-contract-cid-vs-attestation-cid.md``
    §1, this is the BLAKE3-512 of the JCS encoding of the contract's
    substrate-load-bearing fields: name, outBinding, and any of
    pre/post/inv that are present. Two distinct signers attesting to
    the same logical contract produce the same contractCid.

    This value goes in `header.cid` of the minted layered memento.
    """
    pairs: List[Tuple[str, Value]] = [
        ("name", vstr(contract_name)),
        ("outBinding", vstr(out_binding)),
    ]
    if pre is not None:
        pairs.append(("pre", pre))
    if post is not None:
        pairs.append(("post", post))
    if inv is not None:
        pairs.append(("inv", inv))
    return _hash_value(vobj(pairs))


def mint_contract(
    *,
    contract_name: str,
    out_binding: str,
    pre: Optional[Value] = None,
    post: Optional[Value] = None,
    inv: Optional[Value] = None,
    produced_by: str,
    produced_at: str,
    authoring: Authoring,
    signer_seed: bytes,
    input_cids: Optional[Sequence[str]] = None,
) -> ClaimEnvelope:
    """Mint a v1.2-layered contract claim envelope.

    Byte-identical to Rust's `mint_contract` for the same canonical
    inputs. See `tests/test_claim_envelope.py::TestCrossKitByteEquivalence`.

    Required: at least one of pre/post/inv must be present (else
    `EmptyContractError`); `out_binding` must be non-empty (else
    `EmptyOutBindingError`).
    """
    if pre is None and post is None and inv is None:
        raise EmptyContractError(
            "mint_contract: at least one of pre/post/inv must be present"
        )
    if out_binding == "":
        raise EmptyOutBindingError("mint_contract: outBinding must not be empty")

    # DERIVED:
    #   propertyHash = hash(JCS({pre?, post?, inv?, outBinding}))
    #   bindingHash  = hash(JCS({producerId, contractName, propertyHash}))
    # Insertion order matches Rust: pre, post, inv, outBinding.
    ph_pairs: List[Tuple[str, Value]] = []
    if pre is not None:
        ph_pairs.append(("pre", pre))
    if post is not None:
        ph_pairs.append(("post", post))
    if inv is not None:
        ph_pairs.append(("inv", inv))
    ph_pairs.append(("outBinding", vstr(out_binding)))
    property_hash = _hash_value(vobj(ph_pairs))

    bh_obj = vobj(
        [
            ("producerId", vstr(produced_by)),
            ("contractName", vstr(contract_name)),
            ("propertyHash", vstr(property_hash)),
        ]
    )
    binding_hash = _hash_value(bh_obj)

    # Header: schemaVersion + kind + cid + kind-specific REQUIRED fields.
    header_cid = contract_cid(
        contract_name=contract_name,
        out_binding=out_binding,
        pre=pre,
        post=post,
        inv=inv,
    )
    kind_specific: List[Tuple[str, Value]] = [
        ("name", vstr(contract_name)),
        ("outBinding", vstr(out_binding)),
    ]
    if pre is not None:
        kind_specific.append(("pre", pre))
    if post is not None:
        kind_specific.append(("post", post))
    if inv is not None:
        kind_specific.append(("inv", inv))
    # authoring-time claim only: the substrate verifier recomputes; it never reads this field (verified 2026-07: rust verify path)
    kind_specific.append(("verdict", vstr("holds")))
    kind_specific.append(("bindingHash", vstr(binding_hash)))
    kind_specific.append(("propertyHash", vstr(property_hash)))
    sorted_inputs = sorted(list(input_cids) if input_cids is not None else [])
    kind_specific.append(("inputCids", varr([vstr(c) for c in sorted_inputs])))

    header = _build_header("contract", header_cid, kind_specific)

    # Metadata: producer attribution + per-formula derived hashes.
    metadata_pairs: List[Tuple[str, Value]] = [
        ("authoring", _authoring_to_value(authoring)),
        ("producedBy", vstr(produced_by)),
        ("producedAt", vstr(produced_at)),
    ]
    if pre is not None:
        metadata_pairs.append(("preHash", vstr(_hash_value(pre))))
    if post is not None:
        metadata_pairs.append(("postHash", vstr(_hash_value(post))))
    if inv is not None:
        metadata_pairs.append(("invHash", vstr(_hash_value(inv))))
    metadata = vobj(metadata_pairs)

    return _assemble_layered(
        header,
        metadata,
        produced_at,
        signer_seed,
        header_cid,
    )


# ---------------------------------------------------------------------------
# Bridge minting
# ---------------------------------------------------------------------------


def mint_bridge(
    *,
    produced_by: str,
    produced_at: str,
    source_symbol: str,
    source_layer: str,
    target_contract_cid: str,
    target_layer: str,
    ir_arg_sorts: Sequence[str],
    ir_return_sort: str,
    notes: str = "",
    signer_seed: bytes,
) -> ClaimEnvelope:
    """Mint a v1.2-layered bridge claim envelope.

    Byte-identical to Rust's `mint_bridge` for the same canonical
    inputs.

    DERIVED hashes (per spec):
      - bindingHash  = hash(JCS({sourceLayer, sourceSymbol}))
      - propertyHash = hash("bridge:" + sourceSymbol)
      - inputCids    = [target_contract_cid]   (single-element)
    """
    arg_sorts_v = varr([vstr(s) for s in ir_arg_sorts])

    bh_obj = vobj(
        [
            ("sourceLayer", vstr(source_layer)),
            ("sourceSymbol", vstr(source_symbol)),
        ]
    )
    binding_hash = _hash_value(bh_obj)
    property_hash = _hash_string(f"bridge:{source_symbol}")

    # Bridge content CID: BLAKE3-512(JCS({sourceSymbol, sourceLayer,
    # targetContractCid, targetLayer, irArgSorts, irReturnSort})).
    header_cid_v = vobj(
        [
            ("sourceSymbol", vstr(source_symbol)),
            ("sourceLayer", vstr(source_layer)),
            ("targetContractCid", vstr(target_contract_cid)),
            ("targetLayer", vstr(target_layer)),
            ("irArgSorts", arg_sorts_v),
            ("irReturnSort", vstr(ir_return_sort)),
        ]
    )
    header_cid = _hash_value(header_cid_v)

    kind_specific: List[Tuple[str, Value]] = [
        ("sourceSymbol", vstr(source_symbol)),
        ("sourceLayer", vstr(source_layer)),
        ("targetContractCid", vstr(target_contract_cid)),
        ("targetLayer", vstr(target_layer)),
        ("irArgSorts", arg_sorts_v),
        ("irReturnSort", vstr(ir_return_sort)),
        # authoring-time claim only: the substrate verifier recomputes; it never reads this field (verified 2026-07: rust verify path)
        ("verdict", vstr("holds")),
        ("bindingHash", vstr(binding_hash)),
        ("propertyHash", vstr(property_hash)),
        ("inputCids", varr([vstr(target_contract_cid)])),
    ]

    header = _build_header("bridge", header_cid, kind_specific)

    metadata_pairs: List[Tuple[str, Value]] = [
        ("producedBy", vstr(produced_by)),
        ("producedAt", vstr(produced_at)),
    ]
    if notes != "":
        metadata_pairs.append(("notes", vstr(notes)))
    metadata = vobj(metadata_pairs)

    return _assemble_layered(header, metadata, produced_at, signer_seed, "")


# ---------------------------------------------------------------------------
# Implication minting
# ---------------------------------------------------------------------------


def mint_implication(
    *,
    produced_by: str,
    produced_at: str,
    antecedent_hash: str,
    consequent_hash: str,
    antecedent_cid: str,
    consequent_cid: str,
    antecedent_slot: str,
    consequent_slot: str,
    prover: str,
    prover_run_ms: int,
    smt_lib_input: str = "",
    proof_witness: str = "",
    signer_seed: bytes,
) -> ClaimEnvelope:
    """Mint a v1.2-layered implication claim envelope.

    Byte-identical to Rust's `mint_implication` for the same canonical
    inputs.

    DERIVED hashes:
      - bindingHash  = hash(JCS({antecedentHash, consequentHash}))
      - propertyHash = hash("implication:" + ah + ":" + ch)
      - inputCids    = sorted([antecedent_cid, consequent_cid])
    """
    bh_obj = vobj(
        [
            ("antecedentHash", vstr(antecedent_hash)),
            ("consequentHash", vstr(consequent_hash)),
        ]
    )
    binding_hash = _hash_value(bh_obj)
    property_hash = _hash_string(f"implication:{antecedent_hash}:{consequent_hash}")

    header_cid_v = vobj(
        [
            ("antecedentHash", vstr(antecedent_hash)),
            ("consequentHash", vstr(consequent_hash)),
            ("antecedentCid", vstr(antecedent_cid)),
            ("consequentCid", vstr(consequent_cid)),
            ("antecedentSlot", vstr(antecedent_slot)),
            ("consequentSlot", vstr(consequent_slot)),
        ]
    )
    header_cid = _hash_value(header_cid_v)

    input_cids_sorted = sorted([antecedent_cid, consequent_cid])

    kind_specific: List[Tuple[str, Value]] = [
        ("antecedentHash", vstr(antecedent_hash)),
        ("consequentHash", vstr(consequent_hash)),
        ("antecedentCid", vstr(antecedent_cid)),
        ("consequentCid", vstr(consequent_cid)),
        ("antecedentSlot", vstr(antecedent_slot)),
        ("consequentSlot", vstr(consequent_slot)),
        # authoring-time claim only: the substrate verifier recomputes; it never reads this field (verified 2026-07: rust verify path)
        ("verdict", vstr("holds")),
        ("bindingHash", vstr(binding_hash)),
        ("propertyHash", vstr(property_hash)),
        ("inputCids", varr([vstr(c) for c in input_cids_sorted])),
    ]

    header = _build_header("implication", header_cid, kind_specific)

    metadata_pairs: List[Tuple[str, Value]] = [
        ("producedBy", vstr(produced_by)),
        ("producedAt", vstr(produced_at)),
        ("prover", vstr(prover)),
        ("proverRunMs", vint(prover_run_ms)),
    ]
    if smt_lib_input != "":
        metadata_pairs.append(("smtLibInput", vstr(smt_lib_input)))
    if proof_witness != "":
        metadata_pairs.append(("proofWitness", vstr(proof_witness)))
    metadata = vobj(metadata_pairs)

    return _assemble_layered(header, metadata, produced_at, signer_seed, "")


# ---------------------------------------------------------------------------
# Contract set CID (per `protocol/specs/2026-05-03-contract-set-extension.md`)
# ---------------------------------------------------------------------------


def compute_contract_set_cid(contract_cids: Sequence[str]) -> str:
    """Compute the **contract set CID** from a sequence of contractCids.

    Per ``protocol/specs/2026-05-03-contract-set-extension.md`` §1:

        contractSetCid := "blake3-512:" || hex(BLAKE3-512(JCS(<sorted contractCids>)))

    The sort is lexicographic on the raw ``blake3-512:hex`` strings,
    making the result order-independent. Two kits enumerating the same
    contracts in different order produce byte-identical
    `contractSetCid` values.

    Byte-identical to Rust's `compute_contract_set_cid` for the same
    set.
    """
    sorted_cids = sorted(list(contract_cids))
    arr = varr([vstr(c) for c in sorted_cids])
    return blake3_512_of(encode_jcs(arr).encode("utf-8"))
