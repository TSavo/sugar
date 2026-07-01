# SPDX-License-Identifier: Apache-2.0
import nacl.signing
import pytest

from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.witness_oracle import (
    WitnessOracleRefusal,
    resolve_witness,
)


def _signed(content: bytes):
    """A witness = arbitrary content, content-addressed and signed. Substrate
    canonical form: `ed25519:` + base64."""
    import base64

    sk = nacl.signing.SigningKey.generate()
    cid = blake3_512_of(content)
    signature = "ed25519:" + base64.b64encode(
        sk.sign(cid.encode("utf-8")).signature
    ).decode("ascii")
    signer = "ed25519:" + base64.b64encode(bytes(sk.verify_key)).decode("ascii")
    return cid, signature, signer


def test_poem_witness_is_signature_then_content_verified():
    poem = b"roses are red / the proof is signed / what runs is what's pinned"
    cid, signature, signer = _signed(poem)
    memento = {
        "witness_cid": cid,
        "kind": "poem",
        "signer": signer,
        "signature": signature,
    }

    # No package pulled -> signature is the only check (whose sharpie).
    assert resolve_witness(memento)["verified_by"] == "signature"
    # Package pulled -> the bytes must BE the pinned witness.
    assert (
        resolve_witness(memento, witness_content=poem)["verified_by"]
        == "content-address"
    )
    # Swapped witness -> refuse loudly.
    with pytest.raises(WitnessOracleRefusal, match="content misaligned"):
        resolve_witness(memento, witness_content=b"a different poem")


def test_bad_signature_refused():
    cid, _signature, signer = _signed(b"a CI run log")
    memento = {"witness_cid": cid, "signer": signer, "signature": "00" * 64}
    with pytest.raises(WitnessOracleRefusal, match="signature invalid"):
        resolve_witness(memento)


def test_runnable_witness_recompute_or_refuse():
    cid, signature, signer = _signed(b"junit: 42 passed")
    memento = {
        "witness_cid": cid,
        "kind": "pytest",
        "signer": signer,
        "signature": signature,
    }
    # Re-runnable + deterministic: re-run reproduces the CID -> recompute-verified.
    assert (
        resolve_witness(memento, recompute_fn=lambda _m: cid)["verified_by"]
        == "recompute"
    )
    # Re-run drifts -> refuse.
    with pytest.raises(WitnessOracleRefusal, match="recompute misaligned"):
        resolve_witness(memento, recompute_fn=lambda _m: "blake3-512:" + "0" * 128)
