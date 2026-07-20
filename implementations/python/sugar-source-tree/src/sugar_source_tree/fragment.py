"""The two currencies: SourceFragment (live) and SourceMemento (sealed).

Sugar deals in exactly two: a ``SourceFragment`` is the LIVE, CAPABLE
object — oracle-pinned text, a span into it, and (when it was minted by
enumeration) the typed node it views. It points at actual source on disk
and answers whatever operations the work needs. A ``SourceMemento`` is
the sealed minimal address — file, span, two CIDs — inert, never grows.

They are interchangeable through the SourceOracle, and ONLY through it:

    fragment.seal()            -> SourceMemento   (pin)
    resolve_memento(memento)   -> SourceFragment  (recompute, exact-or-refuse)

Resolution goes back through the oracle's ``resolve_span_memento``: the
on-disk file must recompute to the pinned file CID and the sliced segment
to the pinned segment CID, or the oracle refuses loudly. Nothing here
opens a file or mints a hash outside the oracle.

Enumeration is the only fragment constructor: ``SourceFile.fragment``
answers the whole file, ``Node.fragment`` answers that node's slice of
the same pinned text. A fragment that exists is correct because there is
no other way to make one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from sugar_lift_python_source.source_oracle import (
    SourceOracleRefusal,
    resolve_span_memento,
)

from .spans import LineColSpan, Span

if TYPE_CHECKING:  # pragma: no cover
    from .backend import Backend
    from .nodes import Node, SourceUnit
    from .tree import SourceFile


@dataclass(frozen=True)
class SourceMemento:
    """The sealed currency: file, span, content CIDs. Minimal, inert.

    ``source_cid`` pins the whole file; ``cid`` pins the sliced segment.
    Both are the oracle's addresses, carried verbatim from sealing.
    """

    file: str
    start: int
    end: int
    source_cid: str
    cid: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "span": {"start": self.start, "end": self.end},
            "source_cid": self.source_cid,
            "cid": self.cid,
        }


class SourceFragment:
    """The live currency: oracle-pinned text + span + (optionally) the node.

    Rich on purpose: it holds the unit (text, CID, line table), the span,
    and the typed node when enumeration minted it — the working handle,
    not a value triple. Equality is content identity: same file, same
    pinned source CID, same span. The node is capability, not identity.
    """

    __slots__ = ("unit", "span", "node")

    def __init__(self, unit: "SourceUnit", span: Span, node: Optional["Node"]) -> None:
        self.unit = unit
        self.span = span
        self.node = node

    @property
    def filename(self) -> str:
        return self.unit.filename

    @property
    def source_cid(self) -> str:
        return self.unit.source_cid

    @property
    def text(self) -> str:
        return self.span.slice(self.unit.source)

    @property
    def line_col_span(self) -> LineColSpan:
        return self.unit.line_table.project(self.span)

    @property
    def line(self) -> int:
        """The 1-based start line: this fragment's construction-site row."""
        return self.line_col_span.start_line

    @property
    def col(self) -> int:
        """The 0-based start column: this fragment's construction-site column."""
        return self.line_col_span.start_col

    def memento(self):
        """The sealed WIRE warrant for this fragment: a SourceMementoDto (file,
        span, segment CID). Distinct from ``seal()`` (the tree's own inert
        SourceMemento currency): this is the kit's wire DTO the floor values
        mint into contract rows as source warrants. Lazy import, like ``sugar``
        — the meaning package owns the wire shape; the fragment just answers it.
        """
        from sugar_lift_py_tests.kit_rpc.source_memento_dto import SourceMementoDto
        from sugar_lift_py_tests.kit_rpc.source_span_dto import SourceSpanDto

        lc = self.line_col_span
        return SourceMementoDto(
            file=self.filename,
            span=SourceSpanDto(lc.start_line, lc.start_col, lc.end_line, lc.end_col),
            source_cid=self.seal().cid,
        )

    def seal(self) -> SourceMemento:
        """Fragment -> memento. The segment CID is minted by the oracle's
        hash over the oracle-pinned text — this layer computes a slice of
        text the oracle already addressed; it never invents an address."""
        from sugar_lift_python_source.canonical import blake3_512_of

        return SourceMemento(
            file=self.unit.filename,
            start=self.span.start,
            end=self.span.end,
            source_cid=self.unit.source_cid,
            cid=blake3_512_of(self.text.encode("utf-8")),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SourceFragment):
            return NotImplemented
        return (
            self.unit.filename == other.unit.filename
            and self.unit.source_cid == other.unit.source_cid
            and self.span == other.span
        )

    def __hash__(self) -> int:
        return hash((self.unit.filename, self.unit.source_cid, self.span))

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SourceFragment {self.unit.filename!r} "
            f"[{self.span.start}, {self.span.end}) "
            f"node={type(self.node).__name__ if self.node is not None else None}>"
        )


def resolve_memento(
    memento: SourceMemento,
    backend: Optional["Backend"] = None,
    project_root: Optional[str] = None,
) -> SourceFragment:
    """Memento -> fragment, through the oracle. Exact or refuse.

    The oracle re-reads the file, recomputes both CIDs, and refuses on any
    drift. On success the file is re-parsed through a backend and the
    fragment is re-bound to the node whose span equals the pinned span, so
    the resolved fragment is as live as the one that sealed. A pinned span
    that matches no node when the CIDs aligned is a loud refusal — the
    backend disagreed with itself, and that never becomes silence.
    """
    from .tree import SourceFile

    resolved = resolve_span_memento(memento.to_dict(), project_root)
    file = SourceFile(
        (resolved["source"], resolved["filename"], resolved["source_cid"]),
        backend=backend,
    )
    span = Span(memento.start, memento.end)
    if span == Span(0, len(file.unit.source)):
        return file.fragment
    for node in file.nodes():
        if node.span == span:
            return node.fragment
    raise SourceOracleRefusal(
        f"span [{span.start}, {span.end}) recomputed to the pinned CIDs in "
        f"`{memento.file}` but no enumerated node answers it -- the backend "
        "disagreed with the enumeration that sealed"
    )
