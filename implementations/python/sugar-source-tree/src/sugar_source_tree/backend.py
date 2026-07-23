"""The backend contract: every enumeration is a QUERY into the backend.

Two queries, one per level:

- ``Backend.root(unit)`` — give me this file's root. Two outcomes: a
  ``BackendNode`` reference, or ``BackendCouldNotParse`` raised when the source
  is not valid input for this backend.
- ``BackendNode.describe()`` — give me THIS node's children (and its
  kind, its span, its leaf values). Called on demand, per node, when our
  layer enumerates; never as a bulk walk our layer performs up front.

What the backend does behind a query is entirely its own affair, and we
neither know nor ask. It may have parsed the whole file up front; it may
parse incrementally; it may hold a tree between queries or hold nothing.
Backend-internal retention is permitted and invisible — it is the
adapter's implementation detail, below our line. The no-caching rule
governs OUR layer only: we hold nothing between calls, no pool, no keyed
store, no registry, no memo, and we stamp nothing onto backend objects.

A ``BackendNode`` is a read-only reference in OUR terms: our kinds, our
field names, our codepoint spans (already normalized — see spans.py). It
is ``Typeable``: it can be asked for its node type, and a kind with no
node class panics as a MISSING. Nothing above an adapter may name ``ast``
(or any other backend library), and nothing above an adapter ever
receives a backend-native object — only ``BackendNode`` references and
the typed nodes materialized from them.

Failure vocabulary, three distinct classes, never a string:

- ``VocabularyMissing`` (panic.py) — OUR gap: the backend produced a
  shape we have no class for.
- ``BackendDefect`` (panic.py) — the backend produced something
  structurally invalid.
- ``BackendCouldNotParse`` (here) — the backend's own parse outcome: the raw text was
  not valid input for it at all. Every adapter must raise exactly this —
  never its native library exception (``SyntaxError``,
  ``libcst.ParserSyntaxError``, ...) — so no caller above this module
  ever needs to know which parsing library answers the queries today.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .nodes import ControlConstructionContextV1, Node, SourceUnit, Typeable, resolve_kind
from .operators import Operator
from .reporter import NULL_REPORTER, AuditReporter
from .spans import Span


def materialize(
    unit: SourceUnit,
    ref: "BackendNode",
    reporter: AuditReporter = NULL_REPORTER,
    control_context: ControlConstructionContextV1 | None = None,
) -> Node:
    """Typeable -> Typed: THE construction event. Panics on MISSING kind.

    The returned node holds only ``unit``, ``ref``, and its ``reporter``;
    every field access on it is a fresh query through ``ref.describe()``.
    The reporter is threaded here so EVERY constructed node carries one and
    hands it on to the children it later resolves.

    THE construction event IS the registration: a node registers on the roll in
    its own constructor (``Node.__post_init__``), so being constructed is being
    on the roster and there is no way to new a node off the roll -- that is what
    it means to be an AST node. materialize does not register; the constructor
    does.
    """
    cls = ref.resolve_type()
    return cls(
        unit=unit,
        ref=ref,
        reporter=reporter,
        control_context=control_context or ControlConstructionContextV1(),
    )


@dataclass(frozen=True)
class Child:
    """Exactly-one child slot."""

    handle: "BackendNode"

    def resolve(
        self,
        unit: SourceUnit,
        reporter: AuditReporter = NULL_REPORTER,
        control_context: ControlConstructionContextV1 | None = None,
    ) -> Node:
        return materialize(unit, self.handle, reporter, control_context)


@dataclass(frozen=True)
class MaybeChild:
    """Zero-or-one child slot. ``None`` is a structural absence."""

    handle: Optional["BackendNode"]

    def resolve(
        self,
        unit: SourceUnit,
        reporter: AuditReporter = NULL_REPORTER,
        control_context: ControlConstructionContextV1 | None = None,
    ) -> Optional[Node]:
        return None if self.handle is None else materialize(unit, self.handle, reporter, control_context)


@dataclass(frozen=True)
class Children:
    """Zero-or-more child slot."""

    handles: Tuple["BackendNode", ...]

    def resolve(
        self,
        unit: SourceUnit,
        reporter: AuditReporter = NULL_REPORTER,
        control_context: ControlConstructionContextV1 | None = None,
    ) -> Tuple[Node, ...]:
        return tuple(materialize(unit, h, reporter, control_context) for h in self.handles)


@dataclass(frozen=True)
class Leaf:
    """A non-node value carried on the node (identifier, constant, flag)."""

    value: object

    def resolve(
        self,
        unit: SourceUnit,
        reporter: AuditReporter = NULL_REPORTER,
        control_context: ControlConstructionContextV1 | None = None,
    ) -> object:
        del control_context
        return self.value


@dataclass(frozen=True)
class OpLeaf:
    """A single operator (see operators.py)."""

    op: Operator

    def resolve(
        self,
        unit: SourceUnit,
        reporter: AuditReporter = NULL_REPORTER,
        control_context: ControlConstructionContextV1 | None = None,
    ) -> Operator:
        del control_context
        return self.op


@dataclass(frozen=True)
class OpsLeaf:
    """An operator sequence (Compare)."""

    ops: Tuple[Operator, ...]

    def resolve(
        self,
        unit: SourceUnit,
        reporter: AuditReporter = NULL_REPORTER,
        control_context: ControlConstructionContextV1 | None = None,
    ) -> Tuple[Operator, ...]:
        del control_context
        return self.ops


Slot = Child | MaybeChild | Children | Leaf | OpLeaf | OpsLeaf


class BackendCouldNotParse(Exception):
    """The backend could not parse the source unit: not valid input for it.

    Distinct from both panics (panic.py): ``VocabularyMissing`` is a shape
    the backend DID produce that we have no class for; ``BackendDefect``
    is structurally invalid output. This is the backend declining to
    answer at all: a syntax error, a tokenizer error, a null byte, an
    encoding it will not accept. Every adapter's ``root`` raises exactly
    this on such input, carrying its own backend name, the file, and the
    backend's own reason — never letting its native exception type escape.

    Never caught to continue silently: a could-not-parse outcome is a recorded outcome
    (corpus.py records it as a failure row), not a substitute for success
    and never a bare ``None``.
    """

    def __init__(self, backend: str, file: str, reason: str) -> None:
        super().__init__(backend, file, reason)
        self.backend = backend
        self.file = file
        self.reason = reason

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return f"BACKEND COULD NOT PARSE [{self.backend}] {self.file}: {self.reason}"


@dataclass(frozen=True)
class Description:
    """One node's answer to the children query, in OUR terms.

    ``raw_span`` is the node's span in OUR semantics, or ``None`` for
    kinds the backend does not position (the node then takes the envelope
    of child spans and ``anchors``). ``slots`` maps node field names to
    slot values, in the node class's declared field order.
    """

    kind: str
    raw_span: Optional[Span]
    anchors: Tuple[Span, ...]
    slots: Tuple[Tuple[str, Slot], ...]


class BackendNode(Typeable):
    """A read-only reference to one backend node. Typeable, not Typed.

    ``describe()`` IS the per-node query: give me this node's children.
    Whether the answer is precomputed, retained, or derived fresh is the
    adapter's own affair.
    """

    def describe(self) -> Description:
        raise NotImplementedError

    def resolve_type(self) -> type[Node]:
        """Two arms: the concrete node class for this kind, or panic."""
        return resolve_kind(self.describe().kind, observed_at=repr(self))


class Backend:
    """A parsing backend behind the query contract.

    ``root`` is the file-level query: give me this file's root. Two
    outcomes: a ``BackendNode``, or ``BackendCouldNotParse`` — never the
    backend's native library exception.
    """

    name: str = ""

    def fingerprint(self) -> str:
        """The identity of THIS backend at the version that determines its
        output. The node stream a backend produces is a function of its
        version-of-record — for the CPython ``ast`` backend that is the
        interpreter, for a library backend (libcst/parso/tree-sitter) it is the
        library release. A golden is pinned per fingerprint: a backend at a new
        version is a new backend, recorded faithfully in its own file, never
        folded into another's or normalized to match. Defaults to the bare name
        for a versionless backend; version-sensitive backends append theirs."""
        return self.name

    def root(self, unit: SourceUnit) -> BackendNode:
        raise NotImplementedError
