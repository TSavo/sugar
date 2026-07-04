# SPDX-License-Identifier: MIT OR Apache-2.0
#
# The VERIFY dimension over witnesses.
#
# verify does NOT trust the Witness Oracle. The oracle RESOLVES a witness body
# and refuses loudly on drift -- that is its job, the resolution layer. verify
# AUDITS: it recomputes the CID itself (blake3 over the body) and re-checks the
# signature, independently of whatever the oracle reported.
#
# So a BROKEN oracle -- one that hands back content not addressing to the pinned
# CID, or that wrongly reports a witness as verified -- is caught HERE, because
# verify does the math anyway. The pinned CID is the pinned CID; no resolver can
# talk verify out of a 64-byte memcmp. Trust nothing, not even our own oracle.
# Verification IS recomputation ([[project_sugar_first_principle]]).
#
# This is the witness axis of the three-axis pin made a first-class attestation:
# not lazily resolved at materialize time, but enumerated and recomputed as a
# checked dimension of `verify`. exact-or-refuse, no silent loss.

from __future__ import annotations

from typing import Any, Callable

from .canonicalizer import blake3_512_of
from .witness_oracle import WitnessOracleRefusal, _verify_signature


class WitnessVerifyRefusal(Exception):
    """The witness does not hold: signature invalid, or a body that does not
    recompute to the pinned witness_cid. verify refuses loudly."""


class BrokenOracleError(Exception):
    """The oracle APPROVED a witness whose body verify independently computes a
    DIFFERENT CID for. The resolver lied or broke; verify caught it by doing the
    math anyway. The substrate trusts recomputation, not resolvers -- so verify
    audits the oracle, not just the witness."""


def verify_witness(
    memento: dict[str, Any],
    *,
    witness_content: bytes | None = None,
    recompute_fn: Callable[[dict[str, Any]], str] | None = None,
    oracle: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify a WitnessMemento by RECOMPUTATION. Independent of the oracle:

    - SIGNATURE (always): re-verify the ed25519 mark over the witness CID.
    - CONTENT-ADDRESS (when a body is supplied): compute ``blake3(body)`` HERE and
      compare to the pinned ``witness_cid``. If ``oracle`` is also supplied and it
      APPROVED this body, its verdict must agree with the math -- if it approved a
      body that does not address to the CID, raise ``BrokenOracleError``.
    - RECOMPUTE (when re-runnable): re-derive the CID via ``recompute_fn`` and
      compare.

    Any misalignment -> ``WitnessVerifyRefusal``. A lying/broken oracle ->
    ``BrokenOracleError``. Returns the checks performed on success."""
    cid = memento.get("witness_cid")
    if not isinstance(cid, str) or not cid:
        raise WitnessVerifyRefusal("witness memento missing `witness_cid`")

    # 1. SIGNATURE -- recomputed here, not taken from the oracle's word.
    if not _verify_signature(cid, memento.get("signature"), memento.get("signer")):
        raise WitnessVerifyRefusal(
            f"signature invalid for {cid} (signer {memento.get('signer')!r})"
        )
    checks = ["signature"]

    # 2. CONTENT-ADDRESS -- verify computes blake3(body) ITSELF. This is the
    #    backstop: whatever the oracle says, the pinned CID is the pinned CID.
    if witness_content is not None:
        recomputed = blake3_512_of(witness_content)

        # Audit the oracle: if consulted and it APPROVED this body, the verdict
        # must agree with the math. An oracle that approved content not addressing
        # to the pinned CID is BROKEN -- caught right here by recomputing anyway.
        if oracle is not None:
            oracle_approved = False
            try:
                verdict = oracle(memento, witness_content=witness_content)
                oracle_approved = verdict.get("verified_by") == "content-address"
            except WitnessOracleRefusal:
                oracle_approved = False
            if oracle_approved and recomputed != cid:
                raise BrokenOracleError(
                    f"oracle APPROVED {cid} but its body computes to {recomputed} "
                    f"-- the oracle is broken; verify recomputed the CID and refused"
                )

        if recomputed != cid:
            raise WitnessVerifyRefusal(
                f"content misaligned: pinned {cid}, body computes to {recomputed} "
                f"-- this witness is not the body that was signed for"
            )
        checks.append("content-address")

    # 3. RECOMPUTE -- only for re-runnable, deterministic witnesses.
    if recompute_fn is not None:
        reproduced = recompute_fn(memento)
        if reproduced != cid:
            raise WitnessVerifyRefusal(
                f"recompute misaligned: pinned {cid}, reproduced {reproduced} "
                f"-- the run drifted"
            )
        checks.append("recompute")

    return {"witness_cid": cid, "verified": True, "checks": checks}
