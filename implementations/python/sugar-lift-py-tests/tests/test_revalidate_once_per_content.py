"""Revalidate asks once per demand content, not once per path.

Black cold profile on tests/io/json/test_pandas.py: revalidate ×1011 on one
file — a volume bomb. Same disease as auth #7083: content-addressed answer
re-asked because a different path reached the receipt.

Shell: per-path revalidate work (re-hash demand + snapshot membership).
Replacement: demand_cid + process _REVALIDATED_DEMANDS; mint prevalidates
when the snapshot is filled from the same rows.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.import_binding import (
    _REVALIDATED_DEMANDS,
    authenticated_import_use_receipts,
    clear_lexical_revalidation_snapshots,
)


def _mint_many(tmp_path: Path, n_sites: int = 20):
    lines = ["import json"] + [f'json.loads("{i}")' for i in range(n_sites)]
    source = "\n".join(lines) + "\n"
    path = tmp_path / "consumer.py"
    path.write_text(source, encoding="utf-8")
    source_cid = blake3_512_of(source.encode("utf-8"))
    receipts, _ = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    return receipts


def test_mint_prevalidates_so_revalidate_is_free(tmp_path: Path, monkeypatch) -> None:
    clear_lexical_revalidation_snapshots()
    receipts = _mint_many(tmp_path, n_sites=12)
    assert len(receipts) == 12
    # Mint filled _REVALIDATED_DEMANDS for every demand content.
    assert len(_REVALIDATED_DEMANDS) == 12

    import sugar_lift_py_tests.import_binding as ib

    calls = {"snapshot": 0, "hash": 0}
    original_snap = ib._lexical_revalidation_snapshot
    original_hash = ib._hash

    def counting_snap(*args, **kwargs):
        calls["snapshot"] += 1
        return original_snap(*args, **kwargs)

    def counting_hash(value):
        calls["hash"] += 1
        return original_hash(value)

    monkeypatch.setattr(ib, "_lexical_revalidation_snapshot", counting_snap)
    monkeypatch.setattr(ib, "_hash", counting_hash)

    # Multi-path revalidate (manager seat + resolve_import_binding + floor).
    for _ in range(5):
        for receipt in receipts:
            receipt.revalidate()

    assert calls["snapshot"] == 0, (
        f"prevalidated revalidate still opened snapshot {calls['snapshot']} times"
    )
    assert calls["hash"] == 0, (
        f"prevalidated revalidate still re-hashed demand {calls['hash']} times"
    )


def test_second_path_same_content_does_not_re_ask(tmp_path: Path, monkeypatch) -> None:
    """Reminted receipts with same demand content hit process memo."""
    clear_lexical_revalidation_snapshots()
    first = _mint_many(tmp_path, n_sites=8)
    for receipt in first:
        receipt.revalidate()

    # Drop instance flags only — process content memo must still serve.
    for receipt in first:
        object.__setattr__(receipt, "_revalidated_ok", False)

    import sugar_lift_py_tests.import_binding as ib

    snaps = {"n": 0}
    original = ib._lexical_revalidation_snapshot

    def counting(*args, **kwargs):
        snaps["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(ib, "_lexical_revalidation_snapshot", counting)
    for receipt in first:
        receipt.revalidate()
    assert snaps["n"] == 0


def test_forged_demand_still_fails_after_memo(tmp_path: Path) -> None:
    clear_lexical_revalidation_snapshots()
    receipts = _mint_many(tmp_path, n_sites=1)
    receipt = receipts[0]
    # Forge a demand that is not in the snapshot; clear prevalidation.
    forged = dict(receipt.demand)
    forged["targetSymbol"] = "python:forged.symbol"
    object.__setattr__(receipt, "demand", forged)
    object.__setattr__(receipt, "demand_cid", "")  # force recompute
    object.__setattr__(receipt, "_revalidated_ok", False)
    # demand_cid empty triggers re-hash in a manual revalidate path — rebuild cid
    from sugar_lift_py_tests import import_binding as ib

    object.__setattr__(receipt, "demand_cid", ib._hash(forged))
    _REVALIDATED_DEMANDS.discard((receipt.demand_cid, "call"))
    try:
        receipt.revalidate()
        raise AssertionError("forged demand must fail revalidation")
    except ValueError as exc:
        assert "byte-identical" in str(exc)
