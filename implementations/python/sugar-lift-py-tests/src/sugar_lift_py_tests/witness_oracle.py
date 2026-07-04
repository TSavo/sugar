# SPDX-License-Identifier: MIT OR Apache-2.0
#
# The Witness Oracle.
#
# A witness is ARBITRARY CONTENT used as an attestation -- a JUnit run, a
# program's stdout, a compiler report, a CI run, a human sign-off, a poem,
# Trump's sharpie squiggle on a map. The substrate interprets NONE of it. Like
# sugar, a witness is uninterpreted content: content-addressed (CID) and SIGNED.
#
# So the `.proof` does not carry the witness body. A WitnessMemento is a pointer
# + hash + signature -- { witness_cid, kind, signer, signature, runtime_cid? } --
# zero content. The witness body lives in a WITNESS PACKAGE, deployed SEPARATELY
# and pulled only by those who want to re-examine it (the audit material, not the
# ship material -- the witness axis of the three-axis pin made distributable).
#
# You do not ask the `.proof` for the witness body -- you ask the Witness Oracle.
# Verification is by the KIND of arbitrary thing the witness is -- "can this
# declaration be reproduced?":
#   - SIGNATURE (always): the witness CID is signed; verify whose sharpie it is.
#       The universal check -- a poem and a sharpie can only be signature-trusted.
#   - CONTENT-ADDRESS (when the package is pulled): the bytes in the witness
#       package recompute to witness_cid -- the content IS what was pinned.
#   - RECOMPUTE (when re-runnable + deterministic): re-run, re-derive the CID,
#       confirm it reproduces. Only the substrate's own runnable, deterministic
#       witnesses (e.g. a unit test via the kit's discharge) take this path.
# Any mismatch -> REFUSE, loudly. exact-or-refuse, no silent loss.

from __future__ import annotations

from typing import Any, Callable

from .canonicalizer import blake3_512_of


class WitnessOracleRefusal(Exception):
    """Raised LOUDLY when a witness fails to verify: bad signature, package
    content that does not recompute to the pinned CID, or a re-run that drifts."""


def resolve_witness(
    memento: dict[str, Any],
    *,
    witness_content: bytes | None = None,
    recompute_fn: Callable[[dict[str, Any]], str] | None = None,
) -> dict[str, Any]:
    """Verify a WitnessMemento. SIGNATURE is the universal check (whose sharpie);
    CONTENT-ADDRESS is checked when the witness package is supplied; RECOMPUTE is
    checked when the witness is re-runnable. Returns the strongest verification
    achieved, or refuses loudly."""
    witness_cid = memento.get("witness_cid")
    if not isinstance(witness_cid, str) or not witness_cid:
        raise WitnessOracleRefusal("witness memento missing `witness_cid`")

    # 1. SIGNATURE -- the universal path. A witness is a signed mark; verify whose.
    if not _verify_signature(
        witness_cid, memento.get("signature"), memento.get("signer")
    ):
        raise WitnessOracleRefusal(
            f"witness signature invalid for {witness_cid} "
            f"(signer {memento.get('signer')!r}) -- cannot trust the mark"
        )
    verified_by = "signature"

    # 2. CONTENT-ADDRESS -- if the witness package is pulled, the bytes must BE the
    #    pinned witness (the poem/report/run that was signed for).
    if witness_content is not None:
        recomputed = blake3_512_of(witness_content)
        if recomputed != witness_cid:
            raise WitnessOracleRefusal(
                f"witness content misaligned: pinned {witness_cid}, "
                f"package content {recomputed} -- the witness was swapped"
            )
        verified_by = "content-address"

    # 3. RECOMPUTE -- only for re-runnable, deterministic witnesses the substrate
    #    can reproduce. A poem/sharpie/CI-run has no recompute_fn and stays
    #    signature-trusted (loudly bounded: stated, not hidden).
    if recompute_fn is not None:
        reproduced = recompute_fn(memento)
        if reproduced != witness_cid:
            raise WitnessOracleRefusal(
                f"witness recompute misaligned: pinned {witness_cid}, "
                f"reproduced {reproduced} -- the run drifted"
            )
        verified_by = "recompute"

    return {
        "witness_cid": witness_cid,
        "kind": memento.get("kind", "declaration"),
        "signer": memento.get("signer"),
        "verified_by": verified_by,
    }


def _verify_signature(message_cid: Any, signature_string: Any, signer: Any) -> bool:
    """Ed25519-verify a signature over the witness CID bytes. Both `signer` and
    `signature_string` use the substrate's canonical form `ed25519:<base64>` (the
    same the rust verifier emits/checks). Missing signature/signer -> not signed
    -> not trusted."""
    if not isinstance(message_cid, str) or not isinstance(signature_string, str):
        return False
    if not isinstance(signer, str) or not signer:
        return False
    import base64

    pubkey_b64 = signer.split(":", 1)[1] if ":" in signer else signer
    sig_b64 = (
        signature_string.split(":", 1)[1]
        if ":" in signature_string
        else signature_string
    )
    try:
        from nacl.exceptions import BadSignatureError
        from nacl.signing import VerifyKey

        vk = VerifyKey(base64.b64decode(pubkey_b64))
        vk.verify(message_cid.encode("utf-8"), base64.b64decode(sig_b64))
        return True
    except (BadSignatureError, ValueError, Exception):
        return False
