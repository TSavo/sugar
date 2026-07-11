"""The RPC door over the collapse: lift_file_payload builds each def through
the factory, slams it, and serves the record's projections as wire rows --
one function-contract row per universe (post, formals, the def's sealed
warrant) and one contract row per stated inv (Stated, its own warrant). The
old hasattr(result, "payload") silent-skip fork dies with this door."""

from __future__ import annotations

from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.lift_rpc import lift_file_payload

_SOURCE = "def A(z):\n    y = f(3)\n    assert y == 7\n    return z\n"


def test_the_payload_serves_the_collapse() -> None:
    payload = lift_file_payload(_SOURCE, "vendor.py")
    kinds = [row.kind for row in payload.ir]
    assert kinds == ["function-contract", "contract"]

    contract = payload.ir[0]
    assert contract.name == "A"
    assert contract.formals == ["z"]
    assert contract.post is not None
    assert contract.bridge_source_symbol == "A"

    inv_row = payload.ir[1]
    assert inv_row.inv is not None
    assert inv_row.source_warrants[0].source_cid == blake3_512_of(b"assert y == 7")


def test_two_functions_two_universes() -> None:
    source = "def A(z):\n    return z\n\ndef B(w):\n    return 1\n"
    payload = lift_file_payload(source, "t.py")
    assert [row.name for row in payload.ir if row.kind == "function-contract"] == [
        "A",
        "B",
    ]
