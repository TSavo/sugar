"""#6273 — the revalidation snapshot's *value* must be unwritable.

The key of ``_REVALIDATION_SNAPSHOTS`` was never the bug: it already carries
both determining inputs (consumer ``source_cid`` plus a hash of
``module_identities``) and a ``clear`` door.  The residual was one rung down —
the served value was a mutable ``(list, dict)`` pair handed out by reference,
so a consumer that mutated a returned row would corrupt every later hit at
that key.

These twins pin the second condition PR #6271 named for a content-addressed
registry: the key is complete *and the value is immutable*.  Each write path
is asserted to raise; none of it is claimed in prose.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.import_binding import (
    _REVALIDATION_SNAPSHOTS,
    _lexical_revalidation_snapshot,
    authenticated_import_use_receipts,
    authenticated_import_uses,
    clear_lexical_revalidation_snapshots,
)

_SOURCE = "import example_pkg\nexample_pkg.build(1)\nexample_pkg.build(2)\n"


@pytest.fixture(autouse=True)
def _hermetic_cache():
    clear_lexical_revalidation_snapshots()
    yield
    clear_lexical_revalidation_snapshots()


def _module(tmp_path: Path, source: str = _SOURCE):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "consumer.py"
    path.write_text(source, encoding="utf-8")
    return tmp_path, path, source, blake3_512_of(source.encode("utf-8"))


def _snapshot(tmp_path: Path, source: str = _SOURCE, identities=None):
    root, path, text, cid = _module(tmp_path, source)
    return _lexical_revalidation_snapshot(root, path, text, cid, identities or {})


def _receipts(tmp_path: Path, source: str = _SOURCE):
    root, path, text, cid = _module(tmp_path, source)
    receipts, _ = authenticated_import_use_receipts(
        root, path, text, cid, module_identities={}
    )
    assert receipts, "fixture must mint at least one receipt"
    return receipts


# --- twin 1: the served value cannot be mutated -------------------------


def test_served_snapshot_has_no_write_path(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.row_cids = frozenset()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.outcomes = {}  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        del snapshot.outcomes  # type: ignore[misc]

    # The outcomes mapping is served as a read-only view, not the live dict.
    site = next(iter(snapshot.outcomes))
    with pytest.raises(TypeError):
        snapshot.outcomes[site] = "forged"  # type: ignore[index]
    with pytest.raises(TypeError):
        del snapshot.outcomes[site]  # type: ignore[attr-defined]
    for mutator in ("clear", "update", "pop", "popitem", "setdefault"):
        assert not hasattr(snapshot.outcomes, mutator), mutator

    # The row surface is a frozenset of row CIDs: no add/discard/update at all.
    for mutator in ("add", "discard", "remove", "clear", "update"):
        assert not hasattr(snapshot.row_cids, mutator), mutator


# --- twin 2: two consumers cannot observe each other's writes -----------


def test_two_consumers_cannot_observe_each_others_writes(tmp_path: Path) -> None:
    first = _snapshot(tmp_path)
    second = _snapshot(tmp_path)
    assert first is second, "the amortized hit must still be served"

    site = next(iter(first.outcomes))
    before_outcome = first.outcomes[site]
    before_rows = set(first.row_cids)

    # Every write a first consumer could attempt raises rather than landing.
    with pytest.raises(TypeError):
        first.outcomes[site] = "forged"  # type: ignore[index]
    with pytest.raises(AttributeError):
        first.row_cids.add("forged")  # type: ignore[attr-defined]
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.outcomes = {site: "forged"}  # type: ignore[misc]

    assert second.outcomes[site] == before_outcome
    assert set(second.row_cids) == before_rows


def test_receipts_from_one_module_share_a_snapshot_and_all_revalidate(
    tmp_path: Path,
) -> None:
    receipts = _receipts(tmp_path)
    assert len(receipts) >= 2, "fixture must exercise sharing across receipts"
    for receipt in receipts:
        receipt.revalidate()
    assert len(_REVALIDATION_SNAPSHOTS) == 1, "one full-module pass, not N"


# --- twin 3: a real change to either determining input invalidates -------


def test_change_to_source_invalidates(tmp_path: Path) -> None:
    original = _snapshot(tmp_path / "a")
    changed = _snapshot(
        tmp_path / "b", source=_SOURCE + "example_pkg.build(3)\n"
    )
    assert original is not changed
    assert set(original.row_cids) != set(changed.row_cids)
    assert len(_REVALIDATION_SNAPSHOTS) == 2


def test_change_to_module_identities_invalidates(tmp_path: Path) -> None:
    original = _snapshot(tmp_path, identities={})
    changed = _snapshot(
        tmp_path,
        identities={"example_pkg": {"kind": "python-module-identity", "cid": "x"}},
    )
    assert original is not changed
    assert len(_REVALIDATION_SNAPSHOTS) == 2


# --- twin 4: the clear door still works ---------------------------------


def test_clear_door_drops_every_snapshot(tmp_path: Path) -> None:
    first = _snapshot(tmp_path)
    assert _REVALIDATION_SNAPSHOTS
    clear_lexical_revalidation_snapshots()
    assert not _REVALIDATION_SNAPSHOTS
    second = _snapshot(tmp_path)
    assert second is not first, "clear must force a fresh full-module pass"
    assert set(second.row_cids) == set(first.row_cids), "and an identical answer"


# --- twin 5: disabling the cache changes speed only ---------------------


def test_disabling_the_cache_changes_no_row_outcome_or_verdict(
    tmp_path: Path,
) -> None:
    root, path, text, cid = _module(tmp_path)

    cached = _lexical_revalidation_snapshot(root, path, text, cid, {})
    uncached_rows, uncached_outcomes = authenticated_import_uses(
        root, path, text, cid, module_identities={}
    )

    # Same answer, whether or not the amortized value was served.
    assert dict(cached.outcomes) == uncached_outcomes
    assert set(cached.row_cids) == {cached.row_cid(row) for row in uncached_rows}
    for row in uncached_rows:
        assert cached.contains_row(row)

    # And every receipt verdict is identical with the cache defeated between
    # each call (clear == "cache disabled": recompute every time).
    receipts = _receipts(tmp_path)
    with_cache = []
    for receipt in receipts:
        try:
            receipt.revalidate()
            with_cache.append("ok")
        except ValueError as error:  # pragma: no cover - verdict is the datum
            with_cache.append(str(error))

    without_cache = []
    for receipt in receipts:
        clear_lexical_revalidation_snapshots()
        try:
            receipt.revalidate()
            without_cache.append("ok")
        except ValueError as error:  # pragma: no cover - verdict is the datum
            without_cache.append(str(error))

    assert with_cache == without_cache == ["ok"] * len(receipts)


def test_a_forged_row_still_fails_revalidation(tmp_path: Path) -> None:
    """The panic floor is unweakened: a row the pass never minted is refused."""
    receipt = _receipts(tmp_path)[0]
    receipt.revalidate()
    snapshot = _lexical_revalidation_snapshot(
        receipt.root,
        receipt.path,
        receipt.source,
        receipt.source_cid,
        receipt.module_identities,
    )
    forged = dict(receipt.demand)
    forged["targetSymbol"] = "forged"
    assert not snapshot.contains_row(forged)
