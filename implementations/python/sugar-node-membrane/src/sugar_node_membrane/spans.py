"""Span semantics — OUR definition, a pure function of source text.

T's ruling on #5940: "We're not freezing anything. There's nothing to freeze
against. There's segfaults, and that's about it." The span is specified here,
by us, and every provider adapter normalizes into it. CPython's conventions
are one provider's implementation detail, not the spec.

THE SPEC
========

A ``Span`` is a half-open interval ``[start, end)`` of **codepoint offsets**
into the module source string (``str`` indices). Not UTF-8 byte offsets:
byte columns are a CPython implementation artifact no other provider has a
reason to reproduce, and they diverge from character positions on any line
containing a non-ASCII character before the node.

Derived line/column projections (for mementos and humans) are:
1-based lines, 0-based codepoint columns, end-exclusive.

Rulings for the shapes where providers actually differ:

- **Parenthesized expressions**: grouping parentheses are NEVER part of an
  expression's span. ``(x + y)`` -> the ``BinOp`` spans ``x + y``. Grouping
  is presentation, not structure. Applies equally to walrus: ``(n := 10)``
  -> the ``NamedExpr`` spans ``n := 10``.
- **Decorated defs**: ``FunctionDef`` / ``AsyncFunctionDef`` / ``ClassDef``
  spans start at the ``def`` / ``class`` keyword. Decorators are excluded
  from the def's span; each decorator expression is its own node with its
  own span.
- **f-strings**: ``JoinedStr`` spans the entire literal including prefix and
  quotes. Each ``FormattedValue`` spans its ``{...}`` including both braces.
  The inner expression spans its own text inside the braces. A format
  spec is itself a ``JoinedStr`` spanning the spec text AFTER the ``:``
  delimiter — the colon introduces the spec and is not part of it. Nested
  f-strings apply the same rules recursively at each level.
- **Implicit string concatenation**: the single ``Constant`` (or
  ``JoinedStr``, when any piece is an f-string) spans from the first
  piece's opening prefix/quote to the last piece's closing quote, including
  the whitespace/newlines between pieces.
- **Multi-line calls**: ``Call`` spans from the start of its callee
  expression to the closing parenthesis, across lines.
- **Comprehensions**: the comprehension expression (``ListComp`` etc.)
  spans the whole bracketed form including brackets (parenthesized
  ``GeneratorExp`` follows the grouping rule: parens excluded when they are
  grouping, included when they are the call's argument parens is not a
  thing — a bare genexp argument has no parens of its own and spans the
  ``x for x in xs`` text). Each ``Comprehension`` clause node spans from
  its ``for`` keyword (``async`` when the clause is async) to the end of
  its last ``if`` (or of its iterable when it has no ifs). Providers do
  not position the clause; the ``for`` anchor is recovered by a pure
  backscan from the target — between the keyword and its target only
  whitespace can occur.
- **Lambdas**: ``Lambda`` spans from the ``lambda`` keyword to the end of
  its body expression.
- **match**: ``Match`` spans from the ``match`` keyword to the end of the
  last case's body. ``MatchCase`` has no position in some providers; its
  span is the envelope of pattern, guard, and body. Patterns span their own
  text.
- **Tuples**: an enclosed tuple display ``(1, 2)`` includes its
  parentheses — for a tuple the parens delimit the display the way ``[]``
  delimits a list. A bare tuple ``1, 2`` spans its elements. This is the
  one construct where enclosing parens are part of the node.
- **Parameters**: a ``Param`` spans ``name[: annotation][= default]``.
  Leading ``*`` / ``**`` sigils on vararg/kwarg parameters are excluded:
  they are arity markers of the parameter LIST, not of the parameter.
- **Star-args**: ``Starred`` spans ``*expr`` including the star. A
  double-star keyword (``**kwargs`` at a call site) is a ``Keyword`` node
  with ``arg is None`` spanning ``**expr`` including both stars.
- **Envelope rule (general)**: any node kind for which a provider supplies
  no anchor position (``Comprehension``, ``MatchCase``, ``WithItem``,
  ``DictItem``, ``Param`` defaults) takes the envelope of its children's
  spans, optionally widened by adapter-supplied anchor spans (e.g. a
  ``Param``'s name token). A node with neither a provider position nor any
  spanned child is a MISSING and panics: there is no such thing as a node
  with no source extent.
- **Module**: spans the entire source, ``[0, len(source))``.

Everything in this module is a pure function of the source string. No
parser, no provider, no ``ast``.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from .panic import membrane_panic


@dataclass(frozen=True, order=True)
class Span:
    """Half-open codepoint interval [start, end) into the module source."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            membrane_panic(
                owner="spans.Span",
                observed=f"degenerate span [{self.start}, {self.end})",
                requested="0 <= start <= end",
                fix="adapters must normalize provider positions before minting a Span",
            )

    def slice(self, source: str) -> str:
        return source[self.start : self.end]

    def envelope(self, other: "Span") -> "Span":
        return Span(min(self.start, other.start), max(self.end, other.end))


@dataclass(frozen=True)
class LineColSpan:
    """Human/memento projection: 1-based lines, 0-based codepoint columns."""

    start_line: int
    start_col: int
    end_line: int
    end_col: int


class LineTable:
    """Pure function of source text: line/column <-> codepoint offset.

    Lines are split on '\\n' only (source is expected in universal-newlines
    form, which is what every provider consumes). Columns are codepoint
    counts, never bytes.
    """

    def __init__(self, source: str) -> None:
        self.source = source
        starts = [0]
        for i, ch in enumerate(source):
            if ch == "\n":
                starts.append(i + 1)
        self._line_starts = starts
        # Per-line UTF-8 byte->codepoint tables are built lazily by adapters
        # that receive byte columns (a CPython detail, normalized here once).
        self._byte_maps: dict[int, dict[int, int]] = {}

    def offset(self, line: int, col: int) -> int:
        """1-based line + 0-based codepoint column -> absolute offset."""
        if line < 1 or line > len(self._line_starts):
            membrane_panic(
                owner="spans.LineTable.offset",
                observed=f"line {line} outside 1..{len(self._line_starts)}",
                requested="a position inside the source",
                fix="adapter handed a position not derived from this source",
            )
        return self._line_starts[line - 1] + col

    def line_col(self, offset: int) -> tuple[int, int]:
        """Absolute codepoint offset -> (1-based line, 0-based codepoint col)."""
        if offset < 0 or offset > len(self.source):
            membrane_panic(
                owner="spans.LineTable.line_col",
                observed=f"offset {offset} outside 0..{len(self.source)}",
                requested="an offset inside the source",
                fix="span was not minted from this source",
            )
        line_idx = bisect.bisect_right(self._line_starts, offset) - 1
        return line_idx + 1, offset - self._line_starts[line_idx]

    def offset_from_byte_col(self, line: int, byte_col: int) -> int:
        """1-based line + 0-based UTF-8 BYTE column -> absolute codepoint offset.

        This is the ONE place CPython's byte-column convention is allowed to
        exist; the adapter calls it and byte offsets never travel further.
        """
        cp_col = self._byte_map(line).get(byte_col)
        if cp_col is None:
            membrane_panic(
                owner="spans.LineTable.offset_from_byte_col",
                observed=f"byte col {byte_col} is not a codepoint boundary on line {line}",
                requested="a byte column landing on a codepoint boundary",
                fix="provider produced a mid-codepoint column; uninstall the provider",
            )
        return self.offset(line, cp_col)

    def project(self, span: Span) -> LineColSpan:
        sl, sc = self.line_col(span.start)
        el, ec = self.line_col(span.end)
        return LineColSpan(sl, sc, el, ec)

    def _byte_map(self, line: int) -> dict[int, int]:
        cached = self._byte_maps.get(line)
        if cached is not None:
            return cached
        start = self._line_starts[line - 1]
        end = (
            self._line_starts[line] - 1
            if line < len(self._line_starts)
            else len(self.source)
        )
        text = self.source[start:end]
        table: dict[int, int] = {}
        byte_pos = 0
        for cp_index, ch in enumerate(text):
            table[byte_pos] = cp_index
            byte_pos += len(ch.encode("utf-8"))
        table[byte_pos] = len(text)
        self._byte_maps[line] = table
        return table
