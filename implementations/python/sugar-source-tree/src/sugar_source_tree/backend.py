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

from dataclasses import dataclass, field
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
    key = cache.key(ref, reporter, ctx, unit.construction_context)
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


class _PrivateSeal:
    __slots__ = ("owner_type", "preimage")

    def __init__(self, owner_type: type, preimage: dict[str, object]) -> None:
        self.owner_type = owner_type
        self.preimage = preimage


@dataclass(init=False)
class _SealedBackendRelation:
    _owner_token: object = field(repr=False, compare=False, kw_only=True)
    _copy_message = "copied sealed relation"
    _tamper_message = "sealed relation preimage"

    def __init__(self, *, _owner_token: object = None, **fields: object) -> None:
        if _owner_token is None:
            if not fields:
                raise BackendDefect(
                    blame=type(self).__name__,
                    owner="Backend.materialize_module",
                    observed="closed constructor requires backend-owned capability",
                    requested="closed constructor requires backend-owned capability",
                    fix="consume the sole producer product",
                )
            raise TypeError("backend construction owner")
        if not isinstance(_owner_token, _PrivateSeal) or _owner_token.owner_type is not type(self):
            raise TypeError("backend construction owner")
        changed = tuple(
            name
            for name, expected in _owner_token.preimage.items()
            if name not in fields
            or (
                fields[name] is not expected
                if not isinstance(expected, (str, int, float, tuple, type(None)))
                else fields[name] != expected
            )
        )
        message = (
            self._copy_message
            if not changed
            else self._tamper_for(changed[0], fields, _owner_token.preimage)
        )
        raise BackendDefect(
            blame=type(self).__name__,
            owner="Backend.materialize_module",
            observed=message,
            requested=message,
            fix="consume only the producer-minted sealed relation",
        )

    def _tamper_for(
        self,
        field_name: str,
        fields: dict[str, object],
        preimage: dict[str, object],
    ) -> str:
        del fields, preimage
        return self._tamper_message

    def __setattr__(self, name: str, value: object) -> None:
        raise BackendDefect(
            blame=self,
            owner="Backend.materialize_module",
            observed=self._tamper_message,
            requested=self._tamper_message,
            fix="sealed relations are immutable",
        )

    def __copy__(self):
        return type(self)(_owner_token=self._owner_token, **self._visible_fields())

    def __deepcopy__(self, _memo):
        return self.__copy__()

    def _visible_fields(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "_owner_token"
        }


def _close_private(instance: _SealedBackendRelation, **fields: object) -> object:
    for name, value in fields.items():
        object.__setattr__(instance, name, value)
    object.__setattr__(instance, "_owner_token", _PrivateSeal(type(instance), dict(fields)))
    return instance


@dataclass(init=False)
class _BackendLeafAssertionRowV1(_SealedBackendRelation):
    """One physical Call beneath an Assert, minted by module construction."""

    source_cid: str
    constructed_module_identity: object
    backend_fingerprint: str
    construction_event_identity: object
    filename: str
    function_occurrence: object
    function_locus: object
    assert_occurrence: object
    assert_locus: object
    call_occurrence: object
    call_locus: object
    translated_atom_identity: object
    translated_atom_value: object
    translated_term_identity: object
    translated_term_value: object
    _copy_message = "copied sealed leaf assertion relation"
    _tamper_message = "sealed leaf assertion relation"

    def _tamper_for(
        self,
        field_name: str,
        fields: dict[str, object],
        preimage: dict[str, object],
    ) -> str:
        del fields, preimage
        return {
            "source_cid": "leaf source CID",
            "constructed_module_identity": "enclosing ConstructedModule identity",
            "backend_fingerprint": "leaf backend fingerprint",
            "construction_event_identity": "leaf construction event identity",
            "function_occurrence": "exact leaf FunctionDef occurrence",
            "function_locus": "exact leaf FunctionDef locus",
            "assert_occurrence": "exact leaf Assert occurrence",
            "assert_locus": "exact leaf Assert locus",
            "call_occurrence": "exact leaf Call occurrence",
            "call_locus": "exact leaf Call locus",
            "translated_atom_identity": "translated atom identity",
            "translated_atom_value": "translated atom value",
            "translated_term_identity": "translated term identity",
            "translated_term_value": "translated term value",
        }.get(field_name, self._tamper_message)

    @property
    def function_occurrence_identity(self) -> object:
        return (
            None
            if self.function_occurrence is None
            else (self.source_cid, type(self.function_occurrence), self.function_locus)
        )

    @property
    def assert_occurrence_identity(self) -> object:
        return (self.source_cid, type(self.assert_occurrence), self.assert_locus)

    @property
    def call_occurrence_identity(self) -> object:
        return (self.source_cid, type(self.call_occurrence), self.call_locus)


@dataclass(init=False)
class _BackendLexicalCallRowV1(_SealedBackendRelation):
    source_cid: str
    definition_occurrence: object
    definition_locus: object
    lexical_parent: object
    call_occurrence: object
    call_locus: object
    lexical_scope: object
    _copy_message = "copied sealed lexical relation"
    _tamper_message = "sealed lexical relation preimage"

    def _tamper_for(
        self,
        field_name: str,
        fields: dict[str, object],
        preimage: dict[str, object],
    ) -> str:
        del fields, preimage
        return {
            "definition_occurrence": "exact definition occurrence",
            "lexical_parent": "lexical parent capability",
            "call_occurrence": "exact call occurrence",
            "lexical_scope": "lexical scope capability",
        }.get(field_name, self._tamper_message)

    @property
    def definition_occurrence_identity(self) -> object:
        return self.definition_occurrence.ref

    @property
    def lexical_parent_identity(self) -> object:
        return self.lexical_parent.ref

    @property
    def call_occurrence_identity(self) -> object:
        return self.call_occurrence.ref

    @property
    def lexical_scope_identity(self) -> object:
        return self.lexical_scope.ref


class _ConstructedProviderValueV1:
    __slots__ = ("value", "identity", "sort")


@dataclass(init=False)
class _BackendProviderMemberRowV1(_SealedBackendRelation):
    source_cid: str
    constructed_module_identity: object
    backend_fingerprint: str
    construction_event_identity: object
    definition_occurrence: object
    definition_locus: object
    constructed_term_value_identity: object
    constructed_term_value: object
    constructed_term_sort: object
    _copy_message = "copied sealed provider member"
    _tamper_message = "sealed provider member preimage"

    def _tamper_for(
        self,
        field_name: str,
        fields: dict[str, object],
        preimage: dict[str, object],
    ) -> str:
        del fields, preimage
        return {
            "source_cid": "provider source CID",
            "constructed_module_identity": "enclosing ConstructedModule identity",
            "backend_fingerprint": "provider backend fingerprint",
            "construction_event_identity": "provider construction event identity",
            "definition_occurrence": "exact member definition occurrence",
            "definition_locus": "exact member definition locus",
            "constructed_term_value_identity": "constructed TermValue identity",
            "constructed_term_value": "constructed TermValue value",
            "constructed_term_sort": "constructed TermValue sort",
        }.get(field_name, self._tamper_message)


@dataclass(init=False)
class _BackendConstructionEventReceiptV1(_SealedBackendRelation):
    """Closed receipt for the testimony emitted by one module construction."""

    construction_event_identity: object
    closed_roll_call: object
    provider_member_rows: tuple[object, ...]
    leaf_assertion_rows: tuple[object, ...]
    registered_occurrences: tuple[object, ...]
    source_cid: str
    constructed_module_identity: object
    root_identity: object
    backend_fingerprint: str
    construction_event_receipt_cid: str
    _copy_message = "copied sealed construction event"
    _tamper_message = "sealed construction event receipt"


def _validated_construction_event_receipt_cid(value: object) -> str | None:
    """Project one producer-sealed module event to its immutable CID."""
    if type(value) is not _BackendConstructionEventReceiptV1:
        return None
    token = value._owner_token
    if not isinstance(token, _PrivateSeal) or token.owner_type is not type(value):
        return None
    visible = value._visible_fields()
    if tuple(visible) != tuple(token.preimage):
        return None
    for name, expected in token.preimage.items():
        actual = visible[name]
        if (
            actual is not expected
            if not isinstance(expected, (str, int, float, tuple, type(None)))
            else actual != expected
        ):
            return None
    registered = value.registered_occurrences
    if not registered:
        return None
    from sugar_lift_python_source.canonical import cid_of_json

    expected_cid = cid_of_json(
        {
            "kind": "backend-module-construction-receipt",
            "schemaVersion": "1",
            "sourceCid": value.source_cid,
            "backendFingerprint": value.backend_fingerprint,
            "rootMemento": registered[0].fragment.seal().to_dict(),
            "constructedNodeMementoCids": [
                node.fragment.seal().cid for node in registered
            ],
        }
    )
    if expected_cid != value.construction_event_receipt_cid:
        return None
    return value.construction_event_receipt_cid


@dataclass(init=False)
class _ConstructedModuleV1(_SealedBackendRelation):
    """The private, atomic result of the sole backend module construction."""

    backend_fingerprint: str
    source_cid: str
    constructed_module_identity: object
    root: object
    closed_roll_call: object
    function_nodes: tuple[object, ...]
    lexical_call_rows: tuple[object, ...]
    provider_member_rows: tuple[object, ...]
    leaf_assertion_rows: tuple[object, ...]
    construction_event_receipt: object
    construction_event_receipt_cid: str
    reporting_projection: object
    _copy_message = "copied sealed constructed module"
    _tamper_message = "sealed constructed module preimage"

    def _tamper_for(
        self,
        field_name: str,
        fields: dict[str, object],
        preimage: dict[str, object],
    ) -> str:
        if field_name == "backend_fingerprint":
            return "backend fingerprint"
        if field_name == "construction_event_receipt":
            receipt = fields[field_name]
            if getattr(receipt, "source_cid", None) != fields.get("source_cid"):
                return "sealed construction event receipt"
        if field_name == "leaf_assertion_rows":
            proposed = fields[field_name]
            authentic = preimage[field_name]
            if (
                not isinstance(proposed, tuple)
                or len(proposed) != len(authentic)
                or (
                    tuple(map(id, proposed)) != tuple(map(id, authentic))
                    and set(map(id, proposed)) == set(map(id, authentic))
                )
            ):
                return "ordered physical leaf assertion roster"
        return self._tamper_message


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
        from .nodes import (
            Assert,
            Assign,
            AsyncFunctionDef,
            Call,
            Constant,
            Delete,
            FunctionDef,
            Module,
            Name,
        )

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
        constructed_nodes = tuple(root.walk())
        positions = {id(node): position for position, node in enumerate(constructed_nodes)}
        parent_positions: list[int | None] = [None] * len(constructed_nodes)
        for position, node in enumerate(constructed_nodes):
            for field_name in type(node)._child_fields:
                child_value = getattr(node, field_name)
                if child_value is None:
                    continue
                if isinstance(child_value, Node):
                    parent_positions[positions[id(child_value)]] = position
                else:
                    for child in child_value:
                        if child is not None:
                            parent_positions[positions[id(child)]] = position
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
        root_occurrence = root.fragment.seal()
        root_identity = (
            self.fingerprint(),
            root_occurrence.source_cid,
            root_occurrence.start,
            root_occurrence.end,
            root_occurrence.cid,
        )
        scope_at_position: list[int] = []
        module_position = 0
        for position, node in enumerate(constructed_nodes):
            ancestor_position = parent_positions[position]
            scope_position = module_position
            while ancestor_position is not None:
                ancestor = constructed_nodes[ancestor_position]
                if isinstance(ancestor, (FunctionDef, AsyncFunctionDef)):
                    scope_position = ancestor_position
                    break
                ancestor_position = parent_positions[ancestor_position]
            scope_at_position.append(scope_position)

        # Ordered construction-native binding events.  A spelling is only the
        # key joining a read to events in its authenticated lexical scope; the
        # row authority is the exact definition/call/scope occurrences below.
        bindings_by_scope: dict[int, list[tuple[int, str, object | None]]] = {}
        for position, node in enumerate(constructed_nodes):
            scope_position = scope_at_position[position]
            events = bindings_by_scope.setdefault(scope_position, [])
            if isinstance(node, (FunctionDef, AsyncFunctionDef)):
                parent_position = parent_positions[position]
                if parent_position is not None:
                    binding_scope = (
                        parent_position
                        if isinstance(
                            constructed_nodes[parent_position],
                            (FunctionDef, AsyncFunctionDef),
                        )
                        else scope_at_position[parent_position]
                    )
                    bindings_by_scope.setdefault(binding_scope, []).append(
                        (position, node.name, node)
                    )
                for parameter in node.params:
                    bindings_by_scope.setdefault(position, []).append(
                        (position, parameter.name, None)
                    )
            elif isinstance(node, Assign):
                for target in node.targets:
                    if isinstance(target, Name):
                        events.append((position, target.id, None))
            elif isinstance(node, Delete):
                for target in node.targets:
                    if isinstance(target, Name):
                        events.append((position, target.id, None))

        lexical_rows = []
        for call_position, call in enumerate(constructed_nodes):
            if not isinstance(call, Call) or not isinstance(call.func, Name):
                continue
            call_scope_position = scope_at_position[call_position]
            if call_scope_position == module_position:
                continue
            search_scope = call_scope_position
            definition = None
            definition_scope_position = None
            while True:
                matching = [
                    event
                    for event in bindings_by_scope.get(search_scope, ())
                    if event[0] < call_position and event[1] == call.func.id
                ]
                if matching:
                    _, _, candidate = matching[-1]
                    definition = candidate
                    definition_scope_position = search_scope
                    break
                parent_position = parent_positions[search_scope]
                if parent_position is None:
                    break
                search_scope = (
                    parent_position
                    if isinstance(
                        constructed_nodes[parent_position],
                        (FunctionDef, AsyncFunctionDef),
                    )
                    else scope_at_position[parent_position]
                )
                if search_scope == module_position:
                    break
            if not isinstance(definition, (FunctionDef, AsyncFunctionDef)):
                continue
            row = object.__new__(_BackendLexicalCallRowV1)
            _close_private(
                row,
                source_cid=unit.source_cid,
                definition_occurrence=definition,
                definition_locus=definition.line_col_span(),
                lexical_parent=constructed_nodes[definition_scope_position],
                call_occurrence=call,
                call_locus=call.line_col_span(),
                lexical_scope=constructed_nodes[call_scope_position],
            )
            lexical_rows.append(row)
        lexical_call_rows = tuple(lexical_rows)

        provider_rows = []
        for node in constructed_nodes:
            if not isinstance(node, Assign) or len(node.targets) != 1:
                continue
            if not isinstance(node.targets[0], Name) or not isinstance(node.value, Constant):
                continue
            value = node.value.value
            if type(value) not in (int, float, str):
                continue
            value_sugar = node.value._construct_sugar()
            value_cache = node.value._construction_cache()
            value_key = value_cache.key(
                node.value.ref,
                node.value.reporter,
                node.value.control_context,
                node.value.unit.construction_context,
            )
            value_cache.sugar_results[value_key] = value_sugar
            node.value.reporter.present_fact(node.value)
            assert node.value.sugar() is value_sugar
            constructed_value = object.__new__(_ConstructedProviderValueV1)
            value_identity = (
                unit.source_cid,
                type(node.value),
                node.value.line_col_span(),
                type(value_sugar),
            )
            value_sort = {int: "Int", float: "Real", str: "String"}[type(value)]
            _seat_private(
                constructed_value,
                value=value,
                identity=value_identity,
                sort=value_sort,
            )
            member = object.__new__(_BackendProviderMemberRowV1)
            _close_private(
                member,
                source_cid=unit.source_cid,
                constructed_module_identity=module_identity,
                backend_fingerprint=self.fingerprint(),
                construction_event_identity=event_identity,
                definition_occurrence=node,
                definition_locus=node.line_col_span(),
                constructed_term_value_identity=value_identity,
                constructed_term_value=constructed_value,
                constructed_term_sort=value_sort,
            )
            provider_rows.append(member)
        provider_member_rows = tuple(provider_rows)
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
            _close_private(
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
                translated_atom_identity=(
                    unit.source_cid,
                    type(owning_assert),
                    owning_assert.line_col_span(),
                ),
                translated_atom_value=owning_assert,
                translated_term_identity=(
                    unit.source_cid,
                    type(call),
                    call.line_col_span(),
                ),
                translated_term_value=call,
            )
            leaf_rows.append(row)
        leaf_assertion_rows = tuple(leaf_rows)

        # The existing reporter object is the constructor-bound roll.  Closing
        # it here is an identity projection; downstream conversion is owned by
        # the reporting lane.
        closed_roll_call = object()
        observed_registered = tuple(getattr(reporter, "registered", ()))
        registered = observed_registered or constructed_nodes
        receipt = object.__new__(_BackendConstructionEventReceiptV1)
        from sugar_lift_python_source.canonical import cid_of_json

        construction_event_receipt_cid = cid_of_json(
            {
                "kind": "backend-module-construction-receipt",
                "schemaVersion": "1",
                "sourceCid": unit.source_cid,
                "backendFingerprint": self.fingerprint(),
                "rootMemento": root.fragment.seal().to_dict(),
                "constructedNodeMementoCids": [
                    node.fragment.seal().cid for node in constructed_nodes
                ],
            }
        )
        _close_private(
            receipt,
            construction_event_identity=event_identity,
            closed_roll_call=closed_roll_call,
            provider_member_rows=provider_member_rows,
            leaf_assertion_rows=leaf_assertion_rows,
            registered_occurrences=registered,
            source_cid=unit.source_cid,
            constructed_module_identity=module_identity,
            root_identity=root_identity,
            backend_fingerprint=self.fingerprint(),
            construction_event_receipt_cid=construction_event_receipt_cid,
        )
        reporter.present_construction(root, receipt)
        product = object.__new__(_ConstructedModuleV1)
        _close_private(
            product,
            backend_fingerprint=self.fingerprint(),
            source_cid=unit.source_cid,
            constructed_module_identity=module_identity,
            root=root,
            closed_roll_call=closed_roll_call,
            function_nodes=function_nodes,
            lexical_call_rows=lexical_call_rows,
            provider_member_rows=provider_member_rows,
            leaf_assertion_rows=leaf_assertion_rows,
            construction_event_receipt=receipt,
            construction_event_receipt_cid=construction_event_receipt_cid,
            reporting_projection=reporter,
        )
        object.__setattr__(unit, "_constructed_module", product)
        return product
