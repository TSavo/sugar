# SPDX-License-Identifier: MIT OR Apache-2.0
import nacl.signing
import pytest

from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.witness_oracle import resolve_witness
from sugar_lift_py_tests.witness_verify import (
    BrokenOracleError,
    WitnessVerifyRefusal,
    verify_witness,
)


def _signed(content: bytes):
    import base64

    sk = nacl.signing.SigningKey.generate()
    cid = blake3_512_of(content)
    signature = "ed25519:" + base64.b64encode(
        sk.sign(cid.encode("utf-8")).signature
    ).decode("ascii")
    signer = "ed25519:" + base64.b64encode(bytes(sk.verify_key)).decode("ascii")
    return cid, signature, signer


def _memento(content: bytes):
    cid, signature, signer = _signed(content)
    return {
        "witness_cid": cid,
        "kind": "pytest-witness",
        "signer": signer,
        "signature": signature,
    }


# A deliberately BROKEN oracle: it approves EVERYTHING, regardless of content.
def _lying_oracle(_memento, *, witness_content=None, **_kw):
    return {"verified_by": "content-address", "witness_cid": _memento["witness_cid"]}


def test_verify_recomputes_and_passes_aligned_witness():
    body = b"junit: 42 passed, 0 failed"
    m = _memento(body)
    out = verify_witness(m, witness_content=body, oracle=resolve_witness)
    assert out["verified"] and "content-address" in out["checks"]


def test_verify_refuses_tampered_body_even_with_real_oracle():
    m = _memento(b"junit: 42 passed")
    # the real oracle would also refuse -- but verify recomputes regardless.
    with pytest.raises(WitnessVerifyRefusal, match="content misaligned"):
        verify_witness(m, witness_content=b"junit: 0 passed", oracle=resolve_witness)


def test_verify_detects_a_BROKEN_oracle_by_computing_the_cid_anyway():
    # The oracle LIES: it approves a swapped body. verify computes blake3 itself,
    # sees the CID does not match, and catches the oracle red-handed.
    m = _memento(b"the real, signed-for witness")
    swapped = b"a forged witness the broken oracle waved through"
    assert blake3_512_of(swapped) != m["witness_cid"]
    with pytest.raises(BrokenOracleError, match="oracle is broken"):
        verify_witness(m, witness_content=swapped, oracle=_lying_oracle)


def test_broken_oracle_no_false_alarm_on_aligned_body():
    # The lying oracle approves -- but so does the math. No BrokenOracleError.
    body = b"a body that really does address to its CID"
    m = _memento(body)
    out = verify_witness(m, witness_content=body, oracle=_lying_oracle)
    assert out["verified"] and "content-address" in out["checks"]


def test_verify_refuses_tampered_body_with_NO_oracle():
    # No oracle at all -> verify is still the backstop; recompute catches it.
    m = _memento(b"a CI run log")
    with pytest.raises(WitnessVerifyRefusal, match="content misaligned"):
        verify_witness(m, witness_content=b"a different CI run log")


def test_verify_refuses_bad_signature():
    m = _memento(b"a compiler report")
    m["signature"] = "00" * 64
    with pytest.raises(WitnessVerifyRefusal, match="signature invalid"):
        verify_witness(m)


def test_verify_recompute_dimension_for_runnable_witness():
    cid, signature, signer = _signed(b"a deterministic re-run")
    m = {"witness_cid": cid, "signer": signer, "signature": signature}
    out = verify_witness(m, recompute_fn=lambda _m: cid)
    assert "recompute" in out["checks"]
    with pytest.raises(WitnessVerifyRefusal, match="recompute misaligned"):
        verify_witness(m, recompute_fn=lambda _m: "blake3-512:" + "0" * 128)
