"""SourceTree enumerates SourceFile; SourceFile enumerates its nodes.

Strongly typed objects that enumerate strongly typed children, delegating
to a swappable backend:

    SourceTree   enumerates ->  SourceFile
    SourceFile   enumerates ->  its nodes
    Node         enumerates ->  its children

TEXT ENTERS ONLY THROUGH THE ORACLE. A ``SourceFile`` is constructed from
the SourceOracle's identity triple ``(source, filename, content CID)``
(``path_source`` / ``installed_module_source``); this layer never opens a
file, never hashes text, never owns an address. There is no raw-string
door and no ``read_text`` anywhere in the parser.

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
from typing import Iterator, Optional, Tuple

from sugar_lift_python_source.source_oracle import (
    SourceUnavailable,
    installed_module_source,
    path_source,
)

from .backend import Backend, materialize
from .fragment import SourceFragment
from .nodes import Module, Node, SourceUnit
from .panic import backend_defect
from .reporter import NULL_REPORTER, AuditReporter
from .spans import Span


def _default_backend() -> Backend:
    from .cpython_adapter import CPythonAstBackend

    return CPythonAstBackend()


class SourceFile:
    """One source file, parsed through a backend into a typed tree.

    Constructed from the SourceOracle's identity triple ``(source,
    filename, content CID)`` — the ONE currency exchange. Use
    ``SourceFile.from_path`` / ``SourceFile.from_module`` to go through
    the oracle's doors; there is no raw-string constructor and no
    filesystem read here.

    Parsing happens at construction: a ``SourceFile`` you hold is always
    a parsed file, never a promise of one. ``root`` is the ``Module``;
    ``nodes()`` enumerates every node of the file, pre-order, iterative.

    Failure at construction is one of the three loud outcomes:
    ``BackendCouldNotParse`` (the backend's own "not valid input"),
    ``VocabularyMissing`` (our vocabulary has no class for a shape the
    backend produced), or ``BackendDefect`` (the backend produced
    something structurally invalid). Never silence, never a bare None.
    """

    def __init__(
        self,
        identity: Tuple[str, str, str],
        backend: Optional[Backend] = None,
        reporter: AuditReporter = NULL_REPORTER,
        construction_context: object | None = None,
    ) -> None:
        source, filename, source_cid = identity
        self.unit = SourceUnit(
            filename=filename,
            source=source,
            source_cid=source_cid,
            construction_context=construction_context,
        )
        self.backend = backend if backend is not None else _default_backend()
        # The reporter enters the whole tree here: the root carries it and
        # hands it to every child it resolves. An audit walk passes a
        # CollectingReporter; everyone else takes the do-nothing default.
        self.reporter = reporter
        root = materialize(self.unit, self.backend.root(self.unit), reporter)
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
    def from_path(
        cls,
        path: Path | str,
        backend: Optional[Backend] = None,
        reporter: AuditReporter = NULL_REPORTER,
    ) -> "SourceFile":
        """Through the oracle's path-addressed door. Unreadable/undecodable
        is the oracle's loud ``SourceUnavailable``, never a swallow."""
        return cls(path_source(str(path)), backend=backend, reporter=reporter)

    @classmethod
    def from_module(
        cls,
        module_name: str,
        backend: Optional[Backend] = None,
        reporter: AuditReporter = NULL_REPORTER,
    ) -> "SourceFile":
        """Through the oracle's installed-module door."""
        identity = installed_module_source(module_name)
        if identity is None:
            raise SourceUnavailable(
                f"oracle has no installed source for module `{module_name}`"
            )
        return cls(identity, backend=backend, reporter=reporter)

    @property
    def filename(self) -> str:
        return self.unit.filename

    @property
    def source(self) -> str:
        return self.unit.source

    @property
    def fragment(self) -> SourceFragment:
        """The whole file as a SourceFragment: full span, oracle CID."""
        return SourceFragment(
            unit=self.unit, span=Span(0, len(self.unit.source)), node=self.root
        )

    def functions(self) -> Iterator[Node]:
        """Every function definition in this file, at any depth — the
        `functions` enumeration level.

        Assertions live in functions; that is the nature of the game, so
        this is where the wire's questions begin. Transitive through class
        bodies deliberately: vendor suites keep most of their testimony in
        ``class TestX: def test_y()``, and a class is just where Python
        keeps functions. Yields ``FunctionDef`` and ``AsyncFunctionDef``
        nodes — typed, in source order. Laziness stays honest one level
        down: a function yields nothing further until asked.
        """
        from .nodes import AsyncFunctionDef, FunctionDef

        for node in self.root.walk():
            if isinstance(node, (FunctionDef, AsyncFunctionDef)):
                yield node

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

    Enumerating NAMES (globbing) is the tree's job; reading TEXT is the
    oracle's: every path found here enters as the oracle's path-addressed
    identity, so the parser itself never opens a file.
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

    def fragment_of(self, path: Path) -> "SourceFragment":
        """One file's WHOLE-FILE fragment: the oracle's identity, full span,
        no parse. The per-file unit ``fragments()`` iterates. Loud oracle
        source-unavailable result on unreadable/undecodable input."""
        from .fragment import SourceFragment
        from .nodes import SourceUnit
        from .spans import Span

        source, filename, cid = path_source(str(path))
        unit = SourceUnit(filename=filename, source=source, source_cid=cid)
        return SourceFragment(unit, Span(0, len(source)), node=None)

    def fragments(self) -> Iterator["SourceFragment"]:
        """Enumerate WHOLE-FILE fragments: identity without parsing.

        A file-level fragment is literally the entire file — the oracle's
        (source, filename, CID) with the full span. No backend runs, no
        tree is built; this is the ``source_files`` enumeration level, and
        a memento sealed from one of these fragments is the file's locator.
        An unreadable/undecodable file raises ``SourceUnavailable`` loudly
        here — a caller that wants record-and-continue catches per file and
        records a gap; nothing is swallowed and nothing masquerades as a
        source file.
        """
        for path in self.paths():
            yield self.fragment_of(path)

    def files(self) -> Iterator[SourceFile]:
        """Enumerate ``SourceFile``s, each through the oracle's identity.
        Parse failures propagate loudly — a caller that wants
        record-and-continue catches the three contract types plus
        ``SourceUnavailable`` per file (see corpus.py); nothing here
        swallows."""
        for path in self.paths():
            yield SourceFile(path_source(str(path)), backend=self.backend)

    def __iter__(self) -> Iterator[SourceFile]:
        return self.files()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SourceTree {str(self.root)!r} backend={self.backend.name}>"
