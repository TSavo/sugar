"""An import-use receipt is cited by its validated native CID (#7669).

A guarded manager partition seats the import member a factory face reads
(``contextlib.nullcontext``, ``tm.assert_produces_warning``) into its
constructed value.  Canonicalizing that value walked the receipt's
``root``/``path`` (``pathlib.Path``) and the binding's list-valued payload,
which have no constructed-value category, so pinned pandas
``tests/frame/indexing/test_setitem.py`` panicked.  The receipt's demand row
is its complete authenticated content and the binding is authenticated by its
own CID: both are self-authenticating ``cid``/``preimage`` pairs.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.import_binding import (
    authenticated_import_use_receipts,
    authenticated_import_value_use_receipts,
    clear_lexical_revalidation_snapshots,
)
from sugar_source_tree.binding_state import (
    _validated_native_cid,
    constructed_value_cid_v2,
)

_SOURCE = (
    "import contextlib\n"
    "from os import path as p\n"
    "contextlib.nullcontext(1)\n"
    "contextlib.nullcontext(2)\n"
    "x = contextlib.suppress\n"
)


def _seated(receipt) -> str:
    # The receipt is a SLOT of a constructed value (an import member read),
    # which is where the canonicalizer meets it.
    return constructed_value_cid_v2((receipt,))


def _receipts(root: Path, source: str = _SOURCE):
    clear_lexical_revalidation_snapshots()
    path = root / "consumer.py"
    path.write_text(source, encoding="utf-8")
    cid = blake3_512_of(source.encode("utf-8"))
    calls, _ = authenticated_import_use_receipts(root, path, source, cid, module_identities={})
    values = authenticated_import_value_use_receipts(root, path, source, cid, module_identities={})
    if isinstance(values, tuple):
        values = values[0]
    return list(calls) + list(values)


def test_receipt_and_binding_are_native_cid_leaves(tmp_path: Path) -> None:
    receipts = _receipts(tmp_path)
    assert len(receipts) >= 3
    for receipt in receipts:
        assert _validated_native_cid(receipt) == receipt.cid
        assert _validated_native_cid(receipt.import_binding) == receipt.import_binding.cid
        # Canonicalizes (no Path / list category gap) and is content-stable.
        assert _seated(receipt) == _seated(receipt)


def test_distinct_uses_have_distinct_cids(tmp_path: Path) -> None:
    receipts = _receipts(tmp_path)
    cids = [_seated(r) for r in receipts]
    assert len(set(cids)) == len(cids)


def test_lookup_location_is_not_content(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    left = _receipts(first)
    right = _receipts(second)
    assert [_seated(r) for r in left] == [
        _seated(r) for r in right
    ]
