# SPDX-License-Identifier: MIT OR Apache-2.0
#
# Ed25519 signing helper. v1.1.0 of the protocol mandates
# self-identifying signatures of the form:
#
#   "ed25519:" + base64-stdpad(64-byte-signature)
#
# And self-identifying public keys in the same form. The .proof file
# envelope itself stores its catalog signature as a RAW 64-byte CBOR
# byte string (not the prefixed string form): only the per-memento
# `producerSignature` field uses the prefixed string form, because
# memento envelopes are JCS-JSON.
#
# Backed by PyNaCl (libsodium-backed Ed25519). Byte-equivalent to
# the Rust ed25519-dalek peer: both implement RFC 8032 Ed25519.
#
# Reference:
#   implementations/rust/sugar-proof-envelope/src/sign.rs
#   implementations/csharp/Sugar.ProofEnvelope/Sign.cs

from __future__ import annotations

import base64
import binascii

from nacl.signing import SigningKey, VerifyKey
from nacl.exceptions import BadSignatureError

ED25519_SIG_PREFIX = "ed25519:"
ED25519_KEY_PREFIX = "ed25519:"


def ed25519_sign_with_seed(seed: bytes, message: bytes) -> bytes:
    """Sign ``message`` with the Ed25519 private key derived from ``seed``.

    ``seed`` must be exactly 32 bytes (RFC 8032 §5.1.5 seed format).
    Returns the raw 64-byte signature. Byte-identical to the Rust
    ``ed25519_sign_with_seed`` for the same (seed, message) pair.
    """
    if len(seed) != 32:
        raise ValueError("seed must be exactly 32 bytes")
    sk = SigningKey(seed)
    return bytes(sk.sign(message).signature)


def ed25519_sign_string(seed: bytes, message: bytes) -> str:
    """Sign and return the spec's self-identifying string form.

    Format: ``"ed25519:" + base64-stdpad(64-byte-signature)``.
    Mirrors ``ed25519_sign_string`` in the Rust kit.
    """
    sig = ed25519_sign_with_seed(seed, message)
    return ED25519_SIG_PREFIX + base64.b64encode(sig).decode("ascii")


def ed25519_pubkey_string(seed: bytes) -> str:
    """Derive the public key from ``seed`` and return the self-identifying
    string form: ``"ed25519:" + base64-stdpad(32-byte-pubkey)``.

    Mirrors ``ed25519_pubkey_string`` in the Rust kit.
    """
    if len(seed) != 32:
        raise ValueError("seed must be exactly 32 bytes")
    sk = SigningKey(seed)
    vk = sk.verify_key
    return ED25519_KEY_PREFIX + base64.b64encode(bytes(vk)).decode("ascii")


def ed25519_verify_string(pubkey_string: str, sig_string: str, message: bytes) -> bool:
    """Verify ``message`` against ``sig_string`` using ``pubkey_string``.

    Both strings use the spec's self-identifying form
    (``"ed25519:" + base64-stdpad(bytes)``).

    Returns ``True`` iff the signature is valid. Returns ``False`` for
    any malformed input rather than raising, so the caller's fast-path
    and verify-failed-path stay separate.

    Mirrors ``ed25519_verify_string`` in the Rust kit.
    """
    if not pubkey_string.startswith(ED25519_KEY_PREFIX):
        return False
    if not sig_string.startswith(ED25519_SIG_PREFIX):
        return False
    try:
        pk_bytes = base64.b64decode(pubkey_string[len(ED25519_KEY_PREFIX) :])
        sig_bytes = base64.b64decode(sig_string[len(ED25519_SIG_PREFIX) :])
    except (ValueError, binascii.Error):
        return False
    if len(pk_bytes) != 32 or len(sig_bytes) != 64:
        return False
    try:
        vk = VerifyKey(pk_bytes)
        vk.verify(message, sig_bytes)
        return True
    except BadSignatureError:
        return False
    except (TypeError, ValueError):
        return False


# Foundation v0 seed: publicly-known, deterministic test seed.
# Documented as a test seed; v1 is HSM-generated.
# Source: tools/foundation-keygen/src/lib.rs FOUNDATION_V0_SEED.
FOUNDATION_V0_SEED: bytes = bytes([0x42] * 32)


# ---------------------------------------------------------------------------
# Signer: minimal handle bundling the per-actor stable fields.
#
# Used by claim_envelope.ClaimEnvelope.from_contract_decl(decl, signer).
# Only the fields that are stable per-actor live on the Signer; the
# per-attestation fields (produced_at, authoring, input_cids) are passed
# at call time.
# ---------------------------------------------------------------------------


class Signer:
    """Minimal signing handle: 32-byte Ed25519 seed + producer-id string.

    The producer-id ("rust-test@1.0", "py-kit@1.0", etc.) is bound into
    the contract's bindingHash (per `mint_contract` derivation rule
    ``bindingHash = hash(JCS({producerId, contractName, propertyHash}))``)
    so it lives on the Signer rather than being recomputed at every call.

    Per-attestation fields like ``produced_at`` (ISO-8601 timestamp),
    ``authoring`` (kit-author / lift / llm union), and ``input_cids`` are
    passed at call time, not stored on the signer.
    """

    __slots__ = ("seed", "producer_id")

    def __init__(self, seed: bytes, producer_id: str) -> None:
        if not isinstance(seed, (bytes, bytearray)) or len(seed) != 32:
            raise ValueError("Signer seed must be exactly 32 bytes")
        if not isinstance(producer_id, str) or not producer_id:
            raise ValueError("Signer producer_id must be a non-empty str")
        self.seed = bytes(seed)
        self.producer_id = producer_id

    @classmethod
    def foundation_v0(cls, producer_id: str = "py-kit@1.0") -> "Signer":
        """Convenience: a Signer using the public foundation v0 test seed.

        Foundation v0 is the publicly-known cross-kit test seed; it is
        appropriate for fixtures and conformance tests, not production.
        """
        return cls(FOUNDATION_V0_SEED, producer_id)

    def pubkey_string(self) -> str:
        """Self-identifying public-key string: ``ed25519:<base64>``."""
        return ed25519_pubkey_string(self.seed)

    def sign_claim(
        self,
        decl,
        *,
        produced_at: str,
        authoring=None,
        input_cids=None,
    ):
        """Build a v1.2-layered ClaimEnvelope from a `ContractDecl`.

        Convenience delegate to ``ClaimEnvelope.from_contract_decl``.
        Imported lazily to avoid the ``signing -> claim_envelope ->
        signing`` import cycle (claim_envelope itself imports `Signer`).
        """
        from .claim_envelope import ClaimEnvelope

        return ClaimEnvelope.from_contract_decl(
            decl,
            self,
            produced_at=produced_at,
            authoring=authoring,
            input_cids=input_cids,
        )
