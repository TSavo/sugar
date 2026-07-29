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


# The NodeShapeV2 (Merkle) shape CID of a ref, WITHOUT the node's source
# fragment: it is a pure function of the ref's own kind, local fields, and its
# children's V2 CIDs. This is the registry bottom-up construction reads and
# fills, so each ref encodes ONE preimage of its own arity, once, ever --
# the difference between O(sum of subtree sizes) and O(n).
#
# SEPARATE from ``_SHAPE_CIDS`` on purpose. That one holds the node-level
# construction-shape CID, which additionally binds the node's fragment
# coordinate; the two live in different identity namespaces and must never be
# read for each other.
#
# Content identity WITHOUT occurrence identity: two structurally identical
# subtrees under two distinct refs get two ROWS carrying the SAME value. They
# share content identity (that is what content-addressing means) and stay
# distinct occurrences (two live refs, and distinct ordered slot positions in
# their parents).
_SHAPE_CIDS_V2: "weakref.WeakKeyDictionary[object, str]" = weakref.WeakKeyDictionary()


def shape_cid_v2_for(ref: object) -> str | None:
    """The memoized NodeShapeV2 CID for ``ref``, or None if unseen."""
    return _SHAPE_CIDS_V2.get(ref)


def remember_shape_cid_v2(ref: object, cid: str) -> None:
    """Record ``ref``'s NodeShapeV2 CID in the static category registry."""
    _SHAPE_CIDS_V2[ref] = cid


# The ConstructedValueV2 (Merkle) content CID of one constructed SEMANTIC
# VALUE: a pure function of the value's own semantic type, its authenticated
# scalar leaves, and its children's V2 CIDs. This is the registry bottom-up
# construction reads and fills, so each memoizable value encodes ONE preimage of
# its own arity, once, ever -- the difference between O(sum of subtree sizes)
# and O(n) over the shared constructed DAG.
#
# A SEPARATE NAMESPACE from ``_SHAPE_CIDS`` and ``_SHAPE_CIDS_V2``. Those hold
# node-SHAPE identities; this holds constructed-VALUE identities. Three
# registries, three identity namespaces, never read for each other.
#
# ONLY FROZEN DATACLASSES GET A ROW, because only they have a coordinate whose
# inputs this module can NAME:
#
#   * frozen dataclass -> keyed by (type, id(value)). ``frozen=True`` is what
#     makes the field tuple a function of the object, so the live object IS the
#     coordinate; type is in the key because the semantic type tag is in the
#     output. The id-reuse hazard (#6212) is closed by construction: the row
#     holds a WEAK reference to the object it keyed and a hit is honored only
#     when that weakref still resolves to the SAME object, so a recycled address
#     misses instead of reading a dead value's CID. The weakref callback drops
#     the row, bounding the table by LIVE values.
#
#   * tuple / frozenset / mapping -> deliberately NO row. A mapping is MUTABLE,
#     so identity is not a coordinate at all. A tuple/frozenset is immutable but
#     its preimage is exactly its children's already-memoized CIDs, so a row
#     would buy the walk of ONE value's own arity -- which is precisely the work
#     the linear form is allowed to do.
#
#   * every leaf category (primitive, enum, Node, SourceFragment/Memento,
#     natively-authenticated CID owner) -> no row: they never mint a
#     ConstructedValueV2 CID at all, they inline.
#
# CONTENT IDENTITY WITHOUT OCCURRENCE IDENTITY. Two distinct-but-equal frozen
# values get two ROWS carrying the SAME CID. They share content identity -- that
# is what content-addressing means and what makes the form linear -- and stay
# distinct occurrences: two live objects, two rows, and distinct ordered ``at``
# coordinates in their parents.
_CONSTRUCTED_VALUE_CIDS_V2: dict[Any, tuple[Any, str]] = {}


def _constructed_value_coordinate(value: object) -> Any:
    """``value``'s content-CID coordinate, or ``None`` if it has no row."""
    from dataclasses import is_dataclass

    if not is_dataclass(value) or isinstance(value, type):
        return None
    params = getattr(value, "__dataclass_params__", None)
    if params is None or not params.frozen:
        return None
    return ("constructed-value-v2", type(value), id(value))


def constructed_value_cid_v2_for(value: object) -> str | None:
    """The memoized ConstructedValueV2 CID for ``value``, or None if unseen."""
    coordinate = _constructed_value_coordinate(value)
    if coordinate is None:
        return None
    remembered = _CONSTRUCTED_VALUE_CIDS_V2.get(coordinate)
    if remembered is None:
        return None
    keyed, cid = remembered
    # The identity-bearing key is honored only while the object it named is
    # alive and is the SAME object.
    if keyed() is not value:
        return None
    return cid


def remember_constructed_value_cid_v2(value: object, cid: str) -> None:
    """Record ``value``'s ConstructedValueV2 CID in its own static registry."""
    coordinate = _constructed_value_coordinate(value)
    if coordinate is None:
        return
    try:

        def _forget(_dead: Any, coordinate: Any = coordinate) -> None:
            _CONSTRUCTED_VALUE_CIDS_V2.pop(coordinate, None)

        reference = weakref.ref(value, _forget)
    except TypeError:
        # Cannot hold the live identity its key names -> no row, rather than a
        # row a recycled address could read.
        return
    _CONSTRUCTED_VALUE_CIDS_V2[coordinate] = (reference, cid)


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
        construction_context: object = None,
    ) -> tuple:
        loop_targets = getattr(control_context, "loop_targets", ())
        exception_slots = getattr(control_context, "exception_slots", ())
        computed = (
            id(ref),
            id(reporter),
            id(construction_context),
            loop_targets,
            exception_slots,
        )
        self._pinned[computed] = ref
        return computed
