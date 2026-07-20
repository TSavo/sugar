"""Bottom-up, stack-driven construction. The constructed graph IS the cache.

The walk is a series of ``new`` operations: push top-down, drain the stack
so the deepest handles construct first, and build every parent FROM its
already-Typed children. Shape follows ``ir.py``'s ``_intern_term``
(iterative post-order, phase 0 = enter / phase 1 = children ready). No
recursion anywhere in the pass — the recursive descent that segfaults
(#5932) is CPython's, not ours.

There are no lazy get-or-mint accessors and no multi-layer memo scheme: a
parent computes what it needs once, at construction, with children in hand.
The ONLY cache is the entry: source -> root.

Interning: one membrane object per node. Same site, same object, verified
by ``is``. Keys are content coordinates — ``(source_cid, kind, span)`` —
NEVER ``id()`` (#5571/#5573 were that bug; the in-flight ``id(handle)``
walk index below is the ``ir.py``-sanctioned exception: handles are pinned
alive for the duration of the build, so ids cannot be recycled mid-walk).
"""

from __future__ import annotations

from typing import Optional

from .backend import (
    Child,
    Children,
    Description,
    Leaf,
    MaybeChild,
    OpLeaf,
    OpsLeaf,
    Provider,
    ProviderHandle,
)
from .nodes import Module, SourceFragment, SourceUnit
from .panic import membrane_panic
from .spans import Span


class NodePool:
    """Content-coordinate interning: (source_cid, kind, span) -> node."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str, int, int], SourceFragment] = {}
        self._roots: dict[str, Module] = {}

    def root(self, source_cid: str) -> Optional[Module]:
        return self._roots.get(source_cid)

    def commit_root(self, root: Module) -> Module:
        existing = self._roots.get(root.unit.source_cid)
        if existing is not None:
            return existing
        self._roots[root.unit.source_cid] = root
        return root

    def intern(self, node: SourceFragment, kwargs: dict[str, object]) -> SourceFragment:
        key = (node.unit.source_cid, node.kind, node.span.start, node.span.end)
        existing = self._by_key.get(key)
        if existing is None:
            self._by_key[key] = node
            return node
        # A key hit for a node under construction must be the SAME site: same
        # class, same fields (child equality is identity — children are
        # interned). Anything else is a coordinate collision and panics.
        if type(existing) is not type(node) or any(
            getattr(existing, name) != value for name, value in kwargs.items()
        ):
            membrane_panic(
                owner="construct.NodePool.intern",
                observed=(
                    f"two distinct {node.kind} constructions at "
                    f"{key[0][:16]}…[{node.span.start},{node.span.end})"
                ),
                requested="one membrane object per site",
                fix="the content coordinate no longer identifies the site; widen the key deliberately",
            )
        return existing


class Membrane:
    """Source text in, constructed graph out. A pure function plus its cache."""

    def __init__(self, provider: Optional[Provider] = None) -> None:
        if provider is None:
            from .cpython_adapter import CPythonAstProvider

            provider = CPythonAstProvider()
        self.provider = provider
        self.pool = NodePool()

    def parse(self, source: str, filename: str = "<membrane>") -> Module:
        unit = SourceUnit(filename=filename, source=source)
        cached = self.pool.root(unit.source_cid)
        if cached is not None:
            return cached
        root_handle = self.provider.parse(unit)
        root = _build(unit, root_handle, self.pool)
        if not isinstance(root, Module):
            membrane_panic(
                owner="construct.Membrane.parse",
                observed=f"provider root constructed as {type(root).__name__}",
                requested="a Module at the root",
                fix="the provider must hand up a module root",
            )
        return self.pool.commit_root(root)


def _build(unit: SourceUnit, root: ProviderHandle, pool: NodePool) -> SourceFragment:
    # id(handle) -> constructed node. Handles are pinned in ``pins`` for the
    # whole build, so no id can be recycled while it is a live index.
    done: dict[int, SourceFragment] = {}
    pins: list[ProviderHandle] = []
    # (handle, phase): phase 0 = enter, phase 1 = children ready.
    stack: list[tuple[ProviderHandle, int]] = [(root, 0)]

    while stack:
        handle, phase = stack.pop()
        if phase == 0:
            if id(handle) in done:
                continue
            pins.append(handle)
            desc = handle.describe()
            stack.append((handle, 1))
            for child in _child_handles(desc):
                stack.append((child, 0))
            continue

        # phase 1: every child handle below is constructed and Typed.
        desc = handle.describe()
        kwargs: dict[str, object] = {}
        child_spans: list[Span] = []

        for name, slot in desc.slots:
            if isinstance(slot, Child):
                node = _constructed(done, slot.handle)
                kwargs[name] = node
                child_spans.append(node.span)
            elif isinstance(slot, MaybeChild):
                if slot.handle is None:
                    kwargs[name] = None
                else:
                    node = _constructed(done, slot.handle)
                    kwargs[name] = node
                    child_spans.append(node.span)
            elif isinstance(slot, Children):
                nodes = tuple(_constructed(done, h) for h in slot.handles)
                kwargs[name] = nodes
                child_spans.extend(n.span for n in nodes)
            elif isinstance(slot, Leaf):
                kwargs[name] = slot.value
            elif isinstance(slot, OpLeaf):
                kwargs[name] = slot.op
            elif isinstance(slot, OpsLeaf):
                kwargs[name] = slot.ops
            else:  # pragma: no cover - Slot union is closed
                membrane_panic(
                    owner="construct._build",
                    observed=f"unknown slot type {type(slot).__name__}",
                    requested="a Slot from backend.py",
                    fix="the Slot union is closed; extend it deliberately",
                )

        # Typeable -> Typed: THE construction event. Panics on MISSING kind.
        cls = handle.resolve_type()
        span = _span_of(desc, child_spans)
        node = cls(unit=unit, span=span, **kwargs)  # Typed at construction
        done[id(handle)] = pool.intern(node, kwargs)

    return done[id(root)]


def _child_handles(desc: Description) -> list[ProviderHandle]:
    """Child handles of a description, reversed so the leftmost pops first."""
    out: list[ProviderHandle] = []
    for _, slot in desc.slots:
        if isinstance(slot, Child):
            out.append(slot.handle)
        elif isinstance(slot, MaybeChild):
            if slot.handle is not None:
                out.append(slot.handle)
        elif isinstance(slot, Children):
            out.extend(slot.handles)
    out.reverse()
    return out


def _constructed(done: dict[int, SourceFragment], handle: ProviderHandle) -> SourceFragment:
    node = done.get(id(handle))
    if node is None:
        raise AssertionError(
            "membrane build reached parent construction before a child; "
            "the stack discipline is broken"
        )
    return node


def _span_of(desc: Description, child_spans: list[Span]) -> Span:
    if desc.raw_span is not None:
        return desc.raw_span
    spans = list(desc.anchors) + child_spans
    if not spans:
        membrane_panic(
            owner="construct._span_of",
            observed=f"{desc.kind} with neither a provider position nor any spanned child",
            requested="every node has a source extent",
            fix="give the adapter an anchor rule for this kind; never invent a span",
        )
    span = spans[0]
    for s in spans[1:]:
        span = span.envelope(s)
    return span
