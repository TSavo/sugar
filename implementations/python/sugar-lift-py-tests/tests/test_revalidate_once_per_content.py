"""Revalidate asks once per use content, not once per path.

Cold open of pandas/tests/io/json/test_pandas.py measured 1011
``AuthenticatedImportUseV1.revalidate`` calls over only 75 unique use CIDs
(max 67× one face).  Snapshot amortization already shared the module pass;
the residual was re-hashing the same demand face at every seating / resolve /
roster-retain door.  Success is pure content: memo it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.import_binding import (
    _REVALIDATED_USE_CIDS,
    authenticated_import_use_receipts,
    authenticated_import_value_use_receipts,
    clear_lexical_revalidation_snapshots,
)

_SOURCE = "import example_pkg\nexample_pkg.build(1)\nexample_pkg.build(2)\n"


@pytest.fixture(autouse=True)
def _hermetic():
    clear_lexical_revalidation_snapshots()
    yield
    clear_lexical_revalidation_snapshots()


def _module(tmp_path: Path, source: str = _SOURCE):
    path = tmp_path / "consumer.py"
    path.write_text(source, encoding="utf-8")
    return tmp_path, path, source, blake3_512_of(source.encode("utf-8"))


def test_revalidate_second_call_is_free_for_same_use_cid(tmp_path: Path) -> None:
    root, path, text, cid = _module(tmp_path)
    receipts, _ = authenticated_import_use_receipts(
        root, path, text, cid, module_identities={}
    )
    assert receipts, "fixture must mint at least one call-use receipt"
    receipt = receipts[0]
    use_cid = receipt.use["cid"]

    receipt.revalidate()
    assert use_cid in _REVALIDATED_USE_CIDS

    # Force a second path: same content, fresh object face from a second mint
    # would still share use cid; re-call on the same object must not re-work.
    # Patch contains_row to explode if the body re-enters.
    from sugar_lift_py_tests import import_binding as ib

    orig = ib._LexicalRevalidationSnapshotV1.contains_row

    def boom(self, row):  # type: ignore[no-untyped-def]
        raise AssertionError(
            "revalidate re-entered snapshot body for an already-passed use cid"
        )

    ib._LexicalRevalidationSnapshotV1.contains_row = boom  # type: ignore[method-assign]
    try:
        receipt.revalidate()  # must return on content memo
        receipt.revalidate()
    finally:
        ib._LexicalRevalidationSnapshotV1.contains_row = orig  # type: ignore[method-assign]


def test_revalidate_clear_drops_content_memo(tmp_path: Path) -> None:
    root, path, text, cid = _module(tmp_path)
    receipts, _ = authenticated_import_use_receipts(
        root, path, text, cid, module_identities={}
    )
    receipt = receipts[0]
    receipt.revalidate()
    assert _REVALIDATED_USE_CIDS
    clear_lexical_revalidation_snapshots()
    assert not _REVALIDATED_USE_CIDS


def test_failed_revalidate_is_not_memoized(tmp_path: Path) -> None:
    """Only successful revalidate enters the content set — failures re-check."""
    root, path, text, cid = _module(tmp_path)
    receipts, _ = authenticated_import_use_receipts(
        root, path, text, cid, module_identities={}
    )
    target = receipts[0]
    # Poison demand so snapshot membership fails; must not land in the set.
    use_cid = target.use["cid"]
    target.demand["forgedMarker"] = True
    with pytest.raises(ValueError, match="byte-identical"):
        target.revalidate()
    assert use_cid not in _REVALIDATED_USE_CIDS


def test_value_use_revalidate_also_memos(tmp_path: Path) -> None:
    source = "import example_pkg\nx = example_pkg.build\n"
    root, path, text, cid = _module(tmp_path, source)
    receipts, _ = authenticated_import_value_use_receipts(
        root, path, text, cid, module_identities={}
    )
    if not receipts:
        pytest.skip("no value-use receipts for fixture")
    r = receipts[0]
    r.revalidate()
    assert r.use["cid"] in _REVALIDATED_USE_CIDS
    from sugar_lift_py_tests import import_binding as ib

    orig = ib._LexicalRevalidationSnapshotV1.contains_row

    def boom(self, row):  # type: ignore[no-untyped-def]
        raise AssertionError("value-use revalidate re-entered after content memo")

    ib._LexicalRevalidationSnapshotV1.contains_row = boom  # type: ignore[method-assign]
    try:
        r.revalidate()
    finally:
        ib._LexicalRevalidationSnapshotV1.contains_row = orig  # type: ignore[method-assign]
