"""Import-use source CID must match retained source text — refuse, never repair.

Dual-door identity (``read_text`` + ``blake3(read_bytes)``) is a fixture defect.
``authenticated_import_uses`` rejects a mismatched claimed tuple; it must not
rewrite the CID downstream of minting.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.import_binding import (
    authenticated_import_use_receipts,
    authenticated_import_uses,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_oracle import path_source


def test_lying_mismatched_source_cid_is_refused_at_import_use_mint(
    tmp_path: Path,
) -> None:
    """Lying twin: mismatched source text/CID must stay loud at the boundary."""
    path = tmp_path / "consumer.py"
    path.write_text("from pkg import f\nx = f()\n", encoding="utf-8")
    source, _, honest_cid = path_source(str(path))
    lying_cid = "blake3-512:" + "0" * 128
    assert lying_cid != honest_cid

    with pytest.raises(ValueError, match="authenticated import-use source CID is stale"):
        authenticated_import_uses(
            tmp_path, path, source, lying_cid, module_identities={}
        )

    with pytest.raises(ValueError, match="authenticated import-use source CID is stale"):
        authenticated_import_use_receipts(
            tmp_path, path, source, lying_cid, module_identities={}
        )


def test_dual_door_crlf_claim_is_refused_not_repaired(tmp_path: Path) -> None:
    """CRLF dual-door claim is refused; production must not normalize the CID."""
    path = tmp_path / "consumer.py"
    path.write_bytes(b"from pkg import f\r\nx = f()\r\n")
    # Dual-door anti-pattern (normalized text + byte-derived CID).
    source = path.read_text(encoding="utf-8")
    claimed = blake3_512_of(path.read_bytes())
    assert blake3_512_of(source.encode("utf-8")) != claimed

    with pytest.raises(ValueError, match="authenticated import-use source CID is stale"):
        authenticated_import_use_receipts(
            tmp_path, path, source, claimed, module_identities={}
        )


def test_honest_path_source_triple_mints_receipts(tmp_path: Path) -> None:
    """Authoritative door: path_source triple is accepted unchanged."""
    path = tmp_path / "consumer.py"
    path.write_text("from pkg import f\nx = f()\n", encoding="utf-8")
    source, locus, source_cid = path_source(str(path))
    receipts, outcomes = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    assert outcomes
    assert receipts
    for receipt in receipts:
        assert receipt.source_cid == source_cid
        assert blake3_512_of(receipt.source.encode("utf-8")) == receipt.source_cid
    del locus
