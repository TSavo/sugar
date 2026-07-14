"""Independent on-disk census for lift-coverage (#4013).

Second computation — pure ``ast`` — NOT the lifter's bookkeeping.
Used as ground truth against ``sugar lift --report`` accounting.

Two axes stay divergent (do not fold into one coverage number):

* **Assertions** — claims stated on disk (``ast.Assert``); default report body.
* **Minority** — function bodies present on disk (``FunctionDef`` /
  ``AsyncFunctionDef``). Dig is assertion-triggered; un-asserted bodies
  are scope, not a lifter bug.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class BodyOwnerDisposition(str, Enum):
    """Closed source→factory classification; there is no optional/unknown arm."""

    CONSTRUCTED = "constructed"
    LOUD_GAP = "loud-gap"
    INACTIVE_BOUNDARY = "inactive-boundary"
    VIOLATION = "violation"


_BODY_OWNER_KINDS = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


@dataclass(frozen=True)
class BodyOwnerLocus:
    file: str
    line: int
    col: int
    kind: str

    @property
    def identity(self) -> str:
        return f"{self.file}:{self.line}:{self.col}:{self.kind}"


def body_owner_descendant_loci(
    node: ast.AST, *, file: str
) -> tuple[BodyOwnerLocus, ...]:
    """Return source owners poisoned when construction of ``node`` fails.

    The independent conservation census owns the closed body-owner taxonomy.
    Recovery uses this same door so suppressed subtrees cannot silently lose a
    control-flow, class, comprehension, or future owner kind while reporting
    only nested function definitions.
    """
    return tuple(
        BodyOwnerLocus(
            file=file,
            line=descendant.lineno,
            col=descendant.col_offset,
            kind=type(descendant).__name__,
        )
        for descendant in ast.walk(node)
        if descendant is not node and isinstance(descendant, _BODY_OWNER_KINDS)
    )


@dataclass(frozen=True)
class BodyOwnerClassification:
    locus: BodyOwnerLocus
    disposition: BodyOwnerDisposition
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "locus": self.locus.identity,
            "file": self.locus.file,
            "line": self.locus.line,
            "col": self.locus.col,
            "astKind": self.locus.kind,
            "classification": self.disposition.value,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SourceFactoryConservation:
    entries: tuple[BodyOwnerClassification, ...]

    @property
    def violations(self) -> tuple[BodyOwnerClassification, ...]:
        return tuple(
            entry
            for entry in self.entries
            if entry.disposition is BodyOwnerDisposition.VIOLATION
        )

    @property
    def complete(self) -> bool:
        return not self.violations

    def to_json(self) -> dict[str, Any]:
        counts = {disposition.value: 0 for disposition in BodyOwnerDisposition}
        for entry in self.entries:
            counts[entry.disposition.value] += 1
        return {
            "complete": self.complete,
            "sourceLoci": len(self.entries),
            "classificationCounts": dict(sorted(counts.items())),
            "violations": [entry.to_json() for entry in self.violations],
            "entries": [entry.to_json() for entry in self.entries],
        }


def reconcile_body_owner_loci(
    source: str, *, file: str, factory_rows: Sequence[Any]
) -> SourceFactoryConservation:
    """Conserve every body-owning AST locus across the factory boundary.

    A locus is reached (constructed or loud), explicitly outside the current
    per-function audit frontier, or a typed violation.  A loud ancestor owns
    suppression of its descendants, preventing both double-counting and silent
    subtree disappearance.
    """
    tree = ast.parse(source, filename=file)
    reached = _factory_row_index(factory_rows)
    entries: list[BodyOwnerClassification] = []

    def walk(node: ast.AST, active: bool, loud_ancestor: BodyOwnerLocus | None) -> None:
        is_owner = isinstance(node, _BODY_OWNER_KINDS)
        locus = (
            BodyOwnerLocus(file, node.lineno, node.col_offset, type(node).__name__)
            if is_owner
            else None
        )
        row = (
            reached.get((node.lineno, node.col_offset, type(node).__name__))
            if locus
            else None
        )
        this_active = active or isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        )
        next_loud = loud_ancestor
        if locus is not None:
            if loud_ancestor is not None:
                disposition = BodyOwnerDisposition.INACTIVE_BOUNDARY
                reason = f"suppressed by loud ancestor {loud_ancestor.identity}"
            elif row is not None:
                is_gap, reason = row
                disposition = (
                    BodyOwnerDisposition.LOUD_GAP
                    if is_gap
                    else BodyOwnerDisposition.CONSTRUCTED
                )
                if is_gap:
                    next_loud = locus
            elif not this_active:
                disposition = BodyOwnerDisposition.INACTIVE_BOUNDARY
                reason = "outside per-function factory audit frontier"
            else:
                disposition = BodyOwnerDisposition.VIOLATION
                reason = "source body owner disappeared before factory classification"
            entries.append(BodyOwnerClassification(locus, disposition, reason))
        for child in ast.iter_child_nodes(node):
            walk(child, this_active, next_loud)

    walk(tree, False, None)
    entries.sort(
        key=lambda entry: (entry.locus.line, entry.locus.col, entry.locus.kind)
    )
    return SourceFactoryConservation(tuple(entries))


def _factory_row_index(
    rows: Sequence[Any],
) -> dict[tuple[int, int, str], tuple[bool, str]]:
    indexed: dict[tuple[int, int, str], tuple[bool, str]] = {}
    for raw in rows:
        row: Mapping[str, Any]
        if isinstance(raw, Mapping):
            row = raw
        elif hasattr(raw, "to_rpc"):
            row = raw.to_rpc()
        else:
            continue
        line = row.get("line")
        kind = row.get("ast_kind", row.get("astKind"))
        span = row.get("span")
        if not isinstance(span, Mapping):
            memento = row.get("sourceMemento")
            if isinstance(memento, Mapping):
                span = memento.get("span")
        col = 0
        if isinstance(span, Mapping):
            col = int(span.get("start_col", span.get("startCol", 0)) or 0)
        if isinstance(line, int) and isinstance(kind, str):
            key = (line, col, kind)
            gap = row.get("verdict") == "gap"
            indexed[key] = (
                gap,
                str(row.get("reason") or row.get("status") or "factory reached"),
            )
    return indexed


@dataclass(frozen=True)
class AssertLocus:
    file: str
    line: int
    col: int
    end_line: int | None
    end_col: int | None
    preview: str

    @property
    def key(self) -> tuple[str, int, int]:
        return (self.file, self.line, self.col)

    def to_json(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "end_line": self.end_line,
            "end_col": self.end_col,
            "preview": self.preview,
        }


@dataclass(frozen=True)
class BodyLocus:
    file: str
    line: int
    col: int
    end_line: int | None
    end_col: int | None
    name: str
    qualname: str

    @property
    def key(self) -> tuple[str, int, str]:
        return (self.file, self.line, self.name)

    def to_json(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "end_line": self.end_line,
            "end_col": self.end_col,
            "name": self.name,
            "qualname": self.qualname,
        }


@dataclass
class DiskCensus:
    """Independent on-disk construct counts for one or more source files."""

    asserts: list[AssertLocus] = field(default_factory=list)
    bodies: list[BodyLocus] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "files": list(self.files),
            "assertions_stated": len(self.asserts),
            "bodies_present": len(self.bodies),
            "asserts": [a.to_json() for a in self.asserts],
            "bodies": [b.to_json() for b in self.bodies],
        }


def census_source(source: str, *, file: str) -> DiskCensus:
    """Count asserts + function bodies in one source string (independent ast)."""
    tree = ast.parse(source, filename=file)
    lines = source.splitlines()
    census = DiskCensus(files=[file])

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._emit_body(node)
            self._stack.append(node.name)
            self.generic_visit(node)
            self._stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._emit_body(node)
            self._stack.append(node.name)
            self.generic_visit(node)
            self._stack.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._stack.append(node.name)
            self.generic_visit(node)
            self._stack.pop()

        def visit_Assert(self, node: ast.Assert) -> None:
            preview = ""
            if 1 <= node.lineno <= len(lines):
                preview = lines[node.lineno - 1].strip()[:120]
            census.asserts.append(
                AssertLocus(
                    file=file,
                    line=node.lineno,
                    col=node.col_offset,
                    end_line=getattr(node, "end_lineno", None),
                    end_col=getattr(node, "end_col_offset", None),
                    preview=preview,
                )
            )
            self.generic_visit(node)

        def _emit_body(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            qual = ".".join([*self._stack, node.name]) if self._stack else node.name
            census.bodies.append(
                BodyLocus(
                    file=file,
                    line=node.lineno,
                    col=node.col_offset,
                    end_line=getattr(node, "end_lineno", None),
                    end_col=getattr(node, "end_col_offset", None),
                    name=node.name,
                    qualname=qual,
                )
            )

    _Visitor().visit(tree)
    census.asserts.sort(key=lambda a: (a.file, a.line, a.col))
    census.bodies.sort(key=lambda b: (b.file, b.line, b.name))
    return census


def census_paths(paths: Iterable[Path], *, root: Path | None = None) -> DiskCensus:
    """Census every ``.py`` path; ``file`` keys are root-relative when possible."""
    root = root.resolve() if root is not None else None
    merged = DiskCensus()
    for path in sorted(paths, key=lambda p: str(p)):
        path = path.resolve()
        if not path.is_file() or path.suffix != ".py":
            continue
        if "__pycache__" in path.parts:
            continue
        try:
            rel = path.relative_to(root).as_posix() if root is not None else path.name
        except ValueError:
            rel = path.name
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        part = census_source(source, file=rel)
        merged.files.append(rel)
        merged.asserts.extend(part.asserts)
        merged.bodies.extend(part.bodies)
    merged.asserts.sort(key=lambda a: (a.file, a.line, a.col))
    merged.bodies.sort(key=lambda b: (b.file, b.line, b.name))
    return merged


def body_contains_assert(body: BodyLocus, asserts: Iterable[AssertLocus]) -> bool:
    """True if any assert locus falls within the body's line span."""
    end = body.end_line if body.end_line is not None else body.line
    for a in asserts:
        if a.file != body.file:
            continue
        if body.line <= a.line <= end:
            return True
    return False
