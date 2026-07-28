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

from .nodes import (
    ControlConstructionContextV1,
    Node,
    SourceUnit,
    Typeable,
    resolve_kind,
)
from .operators import Operator
from .panic import BackendDefect, backend_defect
from .reporter import NULL_REPORTER, AuditReporter
from .spans import Span


def materialize(
    unit: SourceUnit,
    ref: "BackendNode",
    reporter: AuditReporter = NULL_REPORTER,
    control_context: ControlConstructionContextV1 | None = None,
) -> Node:
    """Typeable -> Typed: THE construction event. Panics on MISSING kind.

    Constructs a Node shell for this backend ref (source or shadow). Field
    *data* is memoized on the unit's ConstructionCache — slots resolve once
    per (ref, reporter, control_context) into a shared row; shells may be
    built freely over that row. Registration runs in the constructor.

    ``unit`` is the unit to construct UNDER, which is the parent's for a child
    slot. A ref that was parsed out of a specific source overrides it with that
    source (``BackendNode.minting_unit``): a span belongs to the text it was
    measured in, and no parent may re-home it. The unit also owns the field
    memo, so this keeps a node's cached field data with the file it came from.
    """
    from .construction_cache import ConstructionCache

    minting_unit = ref.minting_unit
    if minting_unit is not None:
        unit = minting_unit
    ctx = control_context or ControlConstructionContextV1()
    cache = getattr(unit, "construction_cache", None)
    if cache is None:
        cache = ConstructionCache()
        object.__setattr__(unit, "construction_cache", cache)
    # Ensure the field row exists (filled lazily on first accessor).
    key = cache.key(ref, reporter, ctx)
    cache.fields.setdefault(key, {})

    cls = ref.resolve_type()
    return cls(
        unit=unit,
        ref=ref,
        reporter=reporter,
        control_context=ctx,
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
        return (
            None
            if self.handle is None
            else materialize(unit, self.handle, reporter, control_context)
        )


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
        return tuple(
            materialize(unit, h, reporter, control_context) for h in self.handles
        )


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


class _BackendLeafAssertionRowV1:
    """One physical Call beneath an Assert, minted by module construction."""

    __slots__ = (
        "source_cid",
        "constructed_module_identity",
        "backend_fingerprint",
        "construction_event_identity",
        "filename",
        "function_occurrence",
        "function_locus",
        "assert_occurrence",
        "assert_locus",
        "call_occurrence",
        "call_locus",
        "translated_atom_identity",
        "translated_atom_value",
        "translated_term_identity",
        "translated_term_value",
    )

    def __init__(self, **_copied_fields: object) -> None:
        raise BackendDefect(
            blame=self,
            owner="Backend.materialize_module",
            observed="direct leaf assertion relation construction",
            requested="the sealed relation minted by the sole module construction event",
            fix="consume ConstructedModule.leaf_assertion_rows",
        )


class _BackendConstructionEventReceiptV1:
    """Closed receipt for the testimony emitted by one module construction."""

    __slots__ = (
        "construction_event_identity",
        "closed_roll_call",
        "provider_member_rows",
        "leaf_assertion_rows",
        "registered_occurrences",
        "source_cid",
        "constructed_module_identity",
        "root_identity",
        "backend_fingerprint",
    )

    def __init__(self, **_copied_fields: object) -> None:
        raise BackendDefect(
            blame=self,
            owner="Backend.materialize_module",
            observed="direct construction event receipt construction",
            requested="the sealed construction event receipt",
            fix="consume ConstructedModule.construction_event_receipt",
        )


class _ConstructedModuleV1:
    """The private, atomic result of the sole backend module construction."""

    __slots__ = (
        "backend_fingerprint",
        "source_cid",
        "constructed_module_identity",
        "root",
        "closed_roll_call",
        "function_nodes",
        "lexical_call_rows",
        "provider_member_rows",
        "leaf_assertion_rows",
        "construction_event_receipt",
        "reporting_projection",
    )

    def __init__(self, **_copied_fields: object) -> None:
        raise BackendDefect(
            blame=self,
            owner="Backend.materialize_module",
            observed="direct constructed module construction",
            requested="the sealed constructed module preimage",
            fix="call Backend.materialize_module through SourceFile",
        )


def _seat_private(instance: object, **fields: object) -> object:
    """Seat owner-minted fields without exposing a caller construction door."""
    for name, value in fields.items():
        object.__setattr__(instance, name, value)
    return instance


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

    @property
    def minting_unit(self) -> Optional[SourceUnit]:
        """The source this handle's span was MINTED FROM, when it has one.

        A span is only meaningful against the text it was measured in, so a
        handle parsed out of a file must say which file that was. Adapters that
        parse answer with their unit; a handle whose span is BORROWED from an
        origin (every shadow rewrite, every synthetic constituent) answers
        ``None`` and correctly takes the unit it is materialized under, because
        a borrowed span is already expressed in that source's coordinates.

        This exists because a child slot used to inherit its PARENT's unit
        unconditionally. Within one file that is free and right. Across files --
        which is what happens the moment a caller's actual argument is bound
        into a callee body parsed from another file -- it re-homed the child
        onto a source its span was never measured in, and projecting it read
        `offset 55069 outside 0..27637` (a pandas use site against contextlib.py
        on the census's Python 3.12). The span was never wrong; the source it
        was being read against was.
        """
        return None

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

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "materialize_module" in cls.__dict__:
            raise TypeError("final Backend.materialize_module")

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

    def materialize_module(
        self,
        unit: SourceUnit,
        reporter: AuditReporter = NULL_REPORTER,
    ) -> _ConstructedModuleV1:
        """Construct and close one module product in one eager traversal."""
        from .nodes import Assert, AsyncFunctionDef, Call, FunctionDef, Module

        backend_root = self.root(unit)
        root = materialize(unit, backend_root, reporter)
        if not isinstance(root, Module):
            backend_defect(
                blame=root.fragment,
                owner="Backend.materialize_module",
                observed=f"backend root constructed as {type(root).__name__}",
                requested="a Module at the root",
                fix="the backend must hand up a module root",
            )
            raise AssertionError("unreachable")

        # This is the sole completed traversal.  Every roster below is a
        # projection of these exact constructed node objects, never a reread.
        constructed_nodes_list: list[Node] = []
        parent_positions: list[int | None] = []
        stack: list[tuple[Node, int | None]] = [(root, None)]
        while stack:
            node, parent_position = stack.pop()
            position = len(constructed_nodes_list)
            constructed_nodes_list.append(node)
            parent_positions.append(parent_position)
            stack.extend(
                (child, position)
                for _, _, child in reversed(tuple(node.children()))
            )
        constructed_nodes = tuple(constructed_nodes_list)
        function_nodes = tuple(
            node
            for node in constructed_nodes
            if isinstance(node, (FunctionDef, AsyncFunctionDef))
        )
        unit.bind_typed_module(
            root,
            constructed_nodes=constructed_nodes,
            function_nodes=function_nodes,
        )
        event_identity = object()
        module_identity = (unit.source_cid, self.fingerprint())
        leaf_rows = []
        for call_position, call in enumerate(constructed_nodes):
            if not isinstance(call, Call):
                continue
            ancestor_position = parent_positions[call_position]
            owning_assert = None
            owning_function = None
            while ancestor_position is not None:
                ancestor = constructed_nodes[ancestor_position]
                if owning_assert is None and isinstance(ancestor, Assert):
                    owning_assert = ancestor
                if isinstance(ancestor, (FunctionDef, AsyncFunctionDef)):
                    owning_function = ancestor
                    break
                ancestor_position = parent_positions[ancestor_position]
            if owning_assert is None:
                continue
            row = object.__new__(_BackendLeafAssertionRowV1)
            _seat_private(
                row,
                source_cid=unit.source_cid,
                constructed_module_identity=module_identity,
                backend_fingerprint=self.fingerprint(),
                construction_event_identity=event_identity,
                filename=unit.filename,
                function_occurrence=owning_function,
                function_locus=(None if owning_function is None else owning_function.line_col_span()),
                assert_occurrence=owning_assert,
                assert_locus=owning_assert.line_col_span(),
                call_occurrence=call,
                call_locus=call.line_col_span(),
                translated_atom_identity=owning_assert,
                translated_atom_value=owning_assert,
                translated_term_identity=call,
                translated_term_value=call,
            )
            leaf_rows.append(row)
        leaf_assertion_rows = tuple(leaf_rows)

        # The existing reporter object is the constructor-bound roll.  Closing
        # it here is an identity projection; downstream conversion is owned by
        # the reporting lane.
        closed_roll_call = reporter
        registered = tuple(getattr(reporter, "registered", ()))
        receipt = object.__new__(_BackendConstructionEventReceiptV1)
        _seat_private(
            receipt,
            construction_event_identity=event_identity,
            closed_roll_call=closed_roll_call,
            provider_member_rows=(),
            leaf_assertion_rows=leaf_assertion_rows,
            registered_occurrences=registered,
            source_cid=unit.source_cid,
            constructed_module_identity=module_identity,
            root_identity=module_identity,
            backend_fingerprint=self.fingerprint(),
        )
        reporter.present_construction(root, receipt)
        product = object.__new__(_ConstructedModuleV1)
        _seat_private(
            product,
            backend_fingerprint=self.fingerprint(),
            source_cid=unit.source_cid,
            constructed_module_identity=module_identity,
            root=root,
            closed_roll_call=closed_roll_call,
            function_nodes=function_nodes,
            lexical_call_rows=(),
            provider_member_rows=(),
            leaf_assertion_rows=leaf_assertion_rows,
            construction_event_receipt=receipt,
            reporting_projection=reporter,
        )
        return product
