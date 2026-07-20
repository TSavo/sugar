"""SourceTree enumerates SourceFile; SourceFile enumerates its nodes.

Strongly typed objects that enumerate strongly typed children, delegating
to a swappable backend:

    SourceTree   enumerates ->  SourceFile
    SourceFile   enumerates ->  its nodes
    Node         enumerates ->  its children

A ``SourceFile`` parses at construction and holds its own tree. That is
not a cache — it IS the file. There is no pool, no keyed store, no
registry, no memo: enumerate a ``SourceTree`` and each ``SourceFile`` is
built, yielded, and dropped when the caller lets go of it, so peak RSS is
bounded by the largest file, not the corpus.

Each enumeration is a QUERY into the backend: a ``SourceFile`` asking
for its nodes, a node asking for its children — answered per access,
never as a bulk walk our layer performs up front. What the backend
retains between queries is its own affair, below our line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Optional

from .backend import Backend, materialize
from .nodes import Module, Node, SourceUnit
from .panic import backend_defect


def _default_backend() -> Backend:
    from .cpython_adapter import CPythonAstBackend

    return CPythonAstBackend()


class SourceFile:
    """One source file, parsed through a backend into a typed tree.

    Parsing happens at construction: a ``SourceFile`` you hold is always
    a parsed file, never a promise of one. ``root`` is the ``Module``;
    ``nodes()`` enumerates every node of the file, pre-order, iterative.

    Failure at construction is one of the three loud outcomes:
    ``BackendRefused`` (the backend's own "not valid input"),
    ``VocabularyMissing`` (our vocabulary has no class for a shape the
    backend produced), or ``BackendDefect`` (the backend produced
    something structurally invalid). Never silence, never a bare None.
    """

    def __init__(
        self,
        filename: str,
        source: str,
        backend: Optional[Backend] = None,
    ) -> None:
        self.unit = SourceUnit(filename=filename, source=source)
        self.backend = backend if backend is not None else _default_backend()
        root = materialize(self.unit, self.backend.root(self.unit))
        if not isinstance(root, Module):
            backend_defect(
                owner="tree.SourceFile",
                observed=f"backend root constructed as {type(root).__name__}",
                requested="a Module at the root",
                fix="the backend must hand up a module root",
            )
            raise AssertionError("unreachable")
        self.root: Module = root

    @classmethod
    def read(cls, path: Path, filename: str, backend: Optional[Backend] = None) -> "SourceFile":
        return cls(filename=filename, source=path.read_text(encoding="utf-8"), backend=backend)

    @property
    def filename(self) -> str:
        return self.unit.filename

    @property
    def source(self) -> str:
        return self.unit.source

    def nodes(self) -> Iterator[Node]:
        """Every node of this file, pre-order, iterative."""
        return self.root.walk()

    def __iter__(self) -> Iterator[Node]:
        return self.nodes()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SourceFile {self.unit.filename!r}>"


class SourceTree:
    """A directory of Python sources, enumerated as ``SourceFile``s.

    ``files()`` is a generator: each yielded ``SourceFile`` is parsed on
    the way out and retained by nobody but the caller. The tree holds the
    root path and the backend — never the parsed files. That is what
    keeps peak RSS flat across a corpus of any size.
    """

    def __init__(self, root: Path, backend: Optional[Backend] = None) -> None:
        self.root = Path(root)
        self.backend = backend if backend is not None else _default_backend()

    def paths(self) -> Iterator[Path]:
        """Every ``*.py`` under the root, sorted, deterministic."""
        if self.root.is_file():
            yield self.root
            return
        for path in sorted(self.root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path

    def files(self) -> Iterator[SourceFile]:
        """Enumerate ``SourceFile``s. Parse failures propagate loudly —
        a caller that wants record-and-continue catches the three
        contract types per file (see corpus.py); nothing here swallows."""
        for path in self.paths():
            yield SourceFile.read(
                path,
                filename=str(path.relative_to(self.root) if self.root.is_dir() else path),
                backend=self.backend,
            )

    def __iter__(self) -> Iterator[SourceFile]:
        return self.files()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SourceTree {str(self.root)!r} backend={self.backend.name}>"


