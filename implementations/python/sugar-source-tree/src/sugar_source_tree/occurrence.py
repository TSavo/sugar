"""The durable relation key: which SOURCE OCCURRENCE a node denotes.

Sugar carries two non-interchangeable identities over a node, and #7346 rules
that they may never stand in for each other:

* **construction/shell identity** -- the ``BackendNode`` ref and the typed
  ``Node`` shell viewing it.  This is a CAPABILITY: it answers accessors, it
  memoizes field data, it registers on the roll.  Many shells lawfully view
  one occurrence, and ``materialize`` mints a fresh one every call.
* **source-occurrence identity** -- this module.  Pinned source CID + exact
  span + node kind, minted from the already-authenticated source fragment.
  This is the durable key for every SEMANTIC relation over nodes.

``shadow.rewrite`` deliberately borrows the origin's span ("so its memento
still addresses the source the rewrite stands for") and then mints a fresh
ShadowNode and a fresh typed shell.  A relation keyed on shell identity
therefore loses its rows the instant a substitution rewrites the node, and
loses them as a plausible EMPTY rather than as a failed join.  A relation
keyed on the occurrence survives, because the occurrence never moved.

The occurrence key is content-addressed, not text-addressed: the segment CID
alone is insufficient because identical text occurs at different loci, so the
key retains the pinned source and the exact span.  A node from another file,
another pinned revision of the same file, another extent, or another grammar
kind is a DIFFERENT occurrence and must not join -- there is no fallback,
no name match, no span-only arm.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .nodes import Node


@dataclass(frozen=True, slots=True)
class SourceOccurrenceIdentityV1:
    """The one durable key for semantic relations over source nodes.

    Value equality on purpose -- and it is the ONLY equality this type has, so
    a relation keyed by it cannot be joined with ``is`` by accident.  Minted
    only by :meth:`of`, from a node that already answers an oracle-pinned unit
    and an exact span; this type never opens a file, parses, or invents a span.
    """

    file: str
    source_cid: str
    start: int
    end: int
    node_kind: str

    @classmethod
    def of(cls, node: "Node") -> "SourceOccurrenceIdentityV1":
        """The occurrence this node denotes. Inherited by shadow rewrites."""
        span = node.span
        unit = node.unit
        return cls(
            file=unit.filename,
            source_cid=unit.source_cid,
            start=span.start,
            end=span.end,
            node_kind=node.kind,
        )

    def __str__(self) -> str:  # pragma: no cover - diagnostics only
        return f"{self.node_kind}@{self.file}[{self.start},{self.end})"
