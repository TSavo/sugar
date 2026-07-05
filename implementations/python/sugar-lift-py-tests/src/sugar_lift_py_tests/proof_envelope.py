# SPDX-License-Identifier: MIT OR Apache-2.0
#
# Proof-envelope builder. Deterministic CBOR (RFC 8949 §4.2.1) encoding
# of a catalog memento with member envelopes embedded as opaque byte
# strings, signed with Ed25519.
#
# Protocol:
#   1. Build the unsigned body as a CBOR map; cbor2 with canonical=True
#      sorts map keys by bytewise lex order of their CBOR-encoded form
#      (RFC 8949 §4.2.1) -- byte-identical to the Rust manual encoder.
#   2. Ed25519-sign the unsigned-body bytes.
#   3. Re-emit the body with the ``signature`` key added; canonical sort
#      slots it in by lex order automatically.
#   4. BLAKE3-512 the final bytes; the full self-identifying string
#      ``"blake3-512:<128 hex>"`` IS the catalog CID.
#
# The ``members`` map key is the embedded envelope's own CID, and the
# value is its canonical bytes (JCS-JSON for memento envelopes per the
# memento envelope grammar) encoded as a CBOR byte string.
#
# Reference (authoritative):
#   implementations/rust/sugar-proof-envelope/src/proof.rs
#   protocol/specs/2026-04-30-proof-file-format.md
#
# Cross-kit byte-equivalence:
#   The Python output is byte-identical to the Rust kit for the same
#   canonical input. See test_proof_envelope.py cross-kit-bytes tests.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cbor2
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from .canonicalizer import Value, blake3_512_of, vobj, vstr
from .signing import FOUNDATION_V0_SEED, ed25519_sign_with_seed


@dataclass
class ProofEnvelopeInput:
    """Logical input shape for a .proof catalog memento.

    Mirrors ``ProofEnvelopeInput`` in
    implementations/rust/sugar-proof-envelope/src/proof.rs. Field
    ``binary_cid`` corresponds to the Rust ``binaryCid`` (back-pin from
    the .proof bundle to the binary it attests).

    members: map from member CID (e.g. ``blake3-512:<hex>``) to that
    member's canonical bytes (JCS-JSON for memento envelopes).

    signer_seed: 32-byte Ed25519 seed. Defaults to FOUNDATION_V0_SEED
    (the publicly-known test key used by all other kits). Pass your own
    seed for application-specific signing.
    """

    name: str
    version: str
    members: Dict[str, bytes]
    signer_cid: str
    declared_at: str  # ISO-8601, ms precision, trailing 'Z'
    signer_seed: bytes = field(default_factory=lambda: FOUNDATION_V0_SEED)
    binary_cid: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None


@dataclass
class ProofEnvelopeOutput:
    """Result of ``build_proof_envelope``.

    ``bytes``: CBOR bytes of the signed catalog. The BLAKE3-512 hash of
    these bytes IS the catalog CID.

    ``cid``: Full self-identifying CID, e.g. ``"blake3-512:<128 hex>"``.
    This string is the .proof filename without extension.
    """

    bytes: bytes
    cid: str


def build_proof_envelope(inp: ProofEnvelopeInput) -> ProofEnvelopeOutput:
    """Build a .proof envelope from ``inp``.

    Output is byte-identical to the Rust kit's ``build_proof_envelope``
    for the same canonical input. See the module docstring for the
    four-step protocol.
    """
    # Step 1: build unsigned body dict. cbor2 canonical=True sorts keys
    # by bytewise lex of their CBOR-encoded form, matching Rust's
    # emit_sorted_map sort.
    unsigned = _unsigned_body(inp)
    unsigned_bytes = cbor2.dumps(unsigned, canonical=True)

    # Step 2: Ed25519-sign the unsigned bytes.
    sig = ed25519_sign_with_seed(inp.signer_seed, unsigned_bytes)

    # Step 3: re-emit with signature added; canonical sort slots it in.
    signed = dict(unsigned)
    signed["signature"] = sig  # raw bytes -> CBOR byte string
    final_bytes = cbor2.dumps(signed, canonical=True)

    # Step 4: filename CID = BLAKE3-512 of the final signed bytes.
    cid = blake3_512_of(final_bytes)
    return ProofEnvelopeOutput(bytes=final_bytes, cid=cid)


def verify_proof(proof_bytes: bytes, expected_cid: str, signer_pubkey: bytes) -> bool:
    """Verify a .proof envelope against ``expected_cid`` and ``signer_pubkey``.

    Checks:
      1. CID matches: BLAKE3-512(proof_bytes) == expected_cid.
      2. CBOR decodes to a catalog map with the required keys.
      3. Ed25519 signature verifies: re-encode the unsigned body
         (all keys except ``signature``) and verify the embedded
         ``signature`` bytes against ``signer_pubkey`` (raw 32-byte
         Ed25519 public key).

    ``signer_pubkey`` is the raw 32-byte public key -- NOT the seed /
    private key. Use ``nacl.signing.SigningKey(seed).verify_key`` bytes
    or ``ed25519_pubkey_string`` to derive it from a seed if needed.

    Returns ``True`` iff all three checks pass.
    """
    if not isinstance(signer_pubkey, (bytes, bytearray)) or len(signer_pubkey) != 32:
        return False

    # Check 1: CID
    actual_cid = blake3_512_of(proof_bytes)
    if actual_cid != expected_cid:
        return False

    # Check 2: decode + shape
    try:
        catalog = cbor2.loads(proof_bytes)
    except Exception:
        return False
    if not isinstance(catalog, dict):
        return False
    if catalog.get("kind") != "catalog":
        return False
    required = {
        "kind",
        "name",
        "version",
        "members",
        "signer",
        "declaredAt",
        "signature",
    }
    if not required.issubset(catalog.keys()):
        return False
    sig_bytes = catalog.get("signature")
    if not isinstance(sig_bytes, bytes) or len(sig_bytes) != 64:
        return False

    # Check 3: verify signature over the unsigned body
    unsigned = {k: v for k, v in catalog.items() if k != "signature"}
    unsigned_bytes = cbor2.dumps(unsigned, canonical=True)
    try:
        vk = VerifyKey(bytes(signer_pubkey))
        vk.verify(unsigned_bytes, sig_bytes)
        return True
    except BadSignatureError:
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Legacy helper -- kept for backward compatibility with existing callers.
# The STORED-ONLY restriction has been lifted; use build_proof_envelope
# for the normative proof-building path.
# ---------------------------------------------------------------------------


def envelope_body_to_value(env: ProofEnvelopeInput) -> Value:
    """Logical body shape as a canonicalizer Value tree.

    This is a JCS-only view of the body fields (NOT the signed CBOR
    catalog bytes). Useful for round-tripping field sets in Python
    pipelines and pinning JCS conformance of the body payload.

    NOTE: the protocol CID is BLAKE3-512 of the signed CBOR bytes from
    ``build_proof_envelope``, not of the JCS-Value bytes from this
    function. Do not use this function's output as a proof bundle CID.

    members are emitted as ``{cid -> base16(bytes)}`` for round-trip
    purposes; the real protocol stores raw CBOR byte strings, not hex.
    """
    pairs: List[Tuple[str, Value]] = [
        ("kind", vstr("catalog")),
        ("name", vstr(env.name)),
        ("version", vstr(env.version)),
        # Insertion-order members; JCS sorts at emit.
        (
            "members",
            vobj([(cid, vstr(_bytes_to_hex(b))) for cid, b in env.members.items()]),
        ),
        ("signer", vstr(env.signer_cid)),
        ("declaredAt", vstr(env.declared_at)),
    ]
    if env.binary_cid is not None:
        pairs.append(("binaryCid", vstr(env.binary_cid)))
    if env.metadata is not None:
        pairs.append(
            (
                "metadata",
                vobj([(k, vstr(v)) for k, v in env.metadata.items()]),
            )
        )
    return vobj(pairs)


def _bytes_to_hex(b: bytes) -> str:
    if not isinstance(b, (bytes, bytearray)):
        raise TypeError("members values must be bytes")
    return bytes(b).hex()


def _unsigned_body(inp: ProofEnvelopeInput) -> Dict:
    """Build the unsigned body dict for CBOR encoding.

    The dict contains all catalog fields except ``signature``. cbor2
    with canonical=True will sort keys by their CBOR-encoded bytewise
    form, which matches Rust's ``emit_sorted_map`` sort.

    The ``members`` value is a plain dict of ``{str: bytes}``, which
    cbor2 encodes as ``{tstr: bstr}`` -- byte-identical to Rust's
    ``make_members_pair``.
    """
    body: Dict = {
        "kind": "catalog",
        "name": inp.name,
        "version": inp.version,
        "members": {cid: bytes(b) for cid, b in inp.members.items()},
        "signer": inp.signer_cid,
        "declaredAt": inp.declared_at,
    }
    if inp.binary_cid is not None:
        body["binaryCid"] = inp.binary_cid
    if inp.metadata is not None:
        body["metadata"] = dict(inp.metadata)
    return body
