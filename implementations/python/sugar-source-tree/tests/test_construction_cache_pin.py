from __future__ import annotations

import gc
import weakref

from sugar_source_tree.construction_cache import (
    CONTROL_SENSITIVE_KINDS,
    ConstructionCache,
    control_key_fragment,
)


class _Ctx:
    def __init__(self, loop_targets=(), exception_slots=()):
        self.loop_targets = loop_targets
        self.exception_slots = exception_slots


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


def test_cache_pins_non_none_construction_context_and_keeps_none_shape():
    cache = ConstructionCache()
    reporter = object()
    control = _Ctx()
    ref = object()
    context = _Ctx()
    context_ref = weakref.ref(context)
    key = cache.key(ref, reporter, control, context)
    cache.fields[key] = {"receipt": "context-a"}

    del context
    gc.collect()

    assert context_ref() is not None
    pinned = cache._pinned[key]
    assert pinned[0] is ref
    assert pinned[1] is context_ref()
    foreign = _Ctx()
    foreign_key = cache.key(ref, reporter, control, foreign)
    assert foreign_key != key
    assert cache.fields.get(foreign_key) is None

    none_key = cache.key(ref, reporter, control)
    assert none_key == (id(ref), id(reporter), id(None), ())
    assert cache._pinned[none_key] is ref


def test_control_key_fragment_empty_for_non_sensitive_kinds():
    deep = _Ctx(loop_targets=("outer", "inner"), exception_slots=("h1",))
    for kind in ("Name", "Constant", "Attribute", "BinOp", "For", "Call", None):
        assert control_key_fragment(deep, kind) == ()


def test_control_key_fragment_nearest_only_for_sensitive_kinds():
    outer, inner = object(), object()
    deep = _Ctx(loop_targets=(outer, inner), exception_slots=("h0", "h1"))
    assert control_key_fragment(deep, "Break") == ("loop", inner)
    assert control_key_fragment(deep, "Continue") == ("loop", inner)
    assert control_key_fragment(deep, "Raise") == ("exc", "h1")
    assert CONTROL_SENSITIVE_KINDS == frozenset(("Break", "Continue", "Raise"))


def test_non_sensitive_kind_shares_key_across_control_stacks():
    """Name under two different loop nestings is ONE field row — the cache
    converges. Only Break/Continue/Raise split by nearest control binding."""
    cache = ConstructionCache()
    reporter = object()
    ref = object()
    outer, inner = object(), object()
    shallow = _Ctx(loop_targets=(outer,))
    deep = _Ctx(loop_targets=(outer, inner), exception_slots=("h",))

    k_name_shallow = cache.key(ref, reporter, shallow, kind="Name")
    k_name_deep = cache.key(ref, reporter, deep, kind="Name")
    assert k_name_shallow == k_name_deep

    k_break_shallow = cache.key(ref, reporter, shallow, kind="Break")
    k_break_deep = cache.key(ref, reporter, deep, kind="Break")
    assert k_break_shallow != k_break_deep
    assert k_break_shallow == (
        id(ref),
        id(reporter),
        id(None),
        ("loop", outer),
    )
    assert k_break_deep == (
        id(ref),
        id(reporter),
        id(None),
        ("loop", inner),
    )


def test_nested_breaks_keep_distinct_nearest_loop_keys():
    """Correctness tooth: break in outer and break in inner must not share."""
    cache = ConstructionCache()
    reporter = object()
    break_ref = object()
    loop_a, loop_b = object(), object()
    outer_only = _Ctx(loop_targets=(loop_a,))
    nested = _Ctx(loop_targets=(loop_a, loop_b))

    outer_key = cache.key(break_ref, reporter, outer_only, kind="Break")
    inner_key = cache.key(break_ref, reporter, nested, kind="Break")
    assert outer_key != inner_key
    assert outer_key[3] == ("loop", loop_a)
    assert inner_key[3] == ("loop", loop_b)
