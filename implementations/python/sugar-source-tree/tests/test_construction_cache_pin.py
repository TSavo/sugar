from __future__ import annotations

from sugar_source_tree.construction_cache import ConstructionCache


class _Ctx:
    loop_targets = ()
    exception_slots = ()


def test_cache_pins_keyed_refs_against_id_reuse():
    # The cache key embeds id(ref). Transient shadow refs minted during
    # substitution are GC'd and their addresses reused by the next shadow
    # (a loop-unroll iteration's rewritten node), which previously collided on
    # the dead ref's cached field row and served its stale children. The cache
    # must PIN every keyed ref so its id() stays unique while the row lives.
    cache = ConstructionCache()
    reporter = object()
    ctx = _Ctx()

    ref = object()
    key = cache.key(ref, reporter, ctx)
    # the exact ref is retained (kept alive) under its own key
    assert cache._pinned[key] is ref

    # a second, distinct ref keyed while the first is pinned keeps a distinct
    # key -- the first cannot have been GC'd and reused underneath it
    other = object()
    other_key = cache.key(other, reporter, ctx)
    assert other_key != key
    assert cache._pinned[other_key] is other
    assert cache._pinned[key] is ref  # first still pinned, unaffected
