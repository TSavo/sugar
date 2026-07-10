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
from pathlib import Path
from typing import Iterable


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
