"""Work memoization for typed construction — field *data*, not Node shells.

Each ``(ref, reporter, control_context)`` site owns a field row. Slots resolve
at most once into that row on first need. ``materialize`` may construct Node
shells freely; each shell reads the shared row. Source and shadow backends use
the same map (different ``ref``).
"""

from __future__ import annotations

import weakref
from typing import Any

# The construction-shape CID is a CATEGORY of content-addressed work: a pure
# function of a backend ref (fragment + subtree preimage). It is NOT unit-scoped
# -- the same content addresses to the same CID everywhere -- so its registry is
# STATIC, shared by every construction in the process: new does the work once,
# every view (in this file or any other) sees it done. Keyed by the ref OBJECT,
# not id(ref): a WeakKeyDictionary auto-drops a ref's entry when it dies, so it
# neither leaks across the corpus nor suffers the id-reuse staleness that a raw
# id()-keyed map hits when a transient shadow ref's address is recycled -- the
# weak key IS the live identity, no pinning needed.
_SHAPE_CIDS: "weakref.WeakKeyDictionary[object, str]" = weakref.WeakKeyDictionary()


def shape_cid_for(ref: object) -> str | None:
    """The memoized construction-shape CID for ``ref``, or None if unseen."""
    return _SHAPE_CIDS.get(ref)


def remember_shape_cid(ref: object, cid: str) -> None:
    """Record ``ref``'s shape CID in the static category registry."""
    _SHAPE_CIDS[ref] = cid


class ConstructionCache:
    """Shared field rows keyed by backend site + reporter + control context."""

    __slots__ = ("fields", "sugar_results", "sugar_panics", "_pinned")

    def __init__(self) -> None:
        # key -> {slot_name: resolved value}
        self.fields: dict[tuple, dict[str, Any]] = {}
        # key -> constructed sugar. Substitution SHARES node objects (a bound
        # name substitutes to the bound node itself), so the constructed graph
        # is a DAG while ``walk``/``_construct_sugar`` traverse it as a TREE:
        # without this row a shared site re-constructs once per incoming PATH
        # (measured 433x on one pandas function). The coordinate is the same
        # one the field row already uses -- ``key`` below -- and it is
        # exhaustive for construction: ``backend.materialize`` picks the node
        # CLASS by ``ref.resolve_type()``, the field row is a function of the
        # same key, and a loop's owned target coordinate is a function of the
        # ref's kind and span. Same coordinate therefore means the same
        # construction, so each distinct coordinate constructs -- and answers
        # the roll -- exactly once, never once per DAG path.
        self.sugar_results: dict[tuple, Any] = {}
        # key -> the construction panic this coordinate raised. A gap MUST stay
        # a gap on every subsequent call, so a panic is memoized as loudly as a
        # value: the SAME panic object is re-raised, never swallowed, never
        # softened into an absent value. Memoizing it (rather than leaving
        # failures uncached) is what keeps present and absent SYMMETRIC under
        # the coordinate rule -- the reporter testifies each coordinate once,
        # whether it answers present or absent.
        self.sugar_panics: dict[tuple, BaseException] = {}
        # key -> ref. The cache key embeds ``id(ref)``, and shadow refs minted
        # during substitution are transient: once a rewritten shadow is GC'd its
        # address is reused by the NEXT shadow (e.g. one loop-unroll iteration's
        # `x == 0` after the previous iteration's), which would then collide on
        # the dead shadow's cached field row and serve its stale children. Pin
        # every keyed ref so its ``id()`` stays unique for the row's lifetime;
        # distinct constructions therefore keep distinct keys.
        self._pinned: dict[tuple, object] = {}

    def key(
        self,
        ref: object,
        reporter: object,
        control_context: object,
    ) -> tuple:
        loop_targets = getattr(control_context, "loop_targets", ())
        exception_slots = getattr(control_context, "exception_slots", ())
        computed = (id(ref), id(reporter), loop_targets, exception_slots)
        self._pinned[computed] = ref
        return computed
