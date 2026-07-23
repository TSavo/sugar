"""The source tree: the class hierarchy IS the grammar.

``Node`` is the abstract base; ``Call``, ``FunctionDef``,
``Assert``, ``Name``, ... subclass it. Which fields exist is answered by
which class you hold — you cannot ask a non-Call for its args because you do
not have one. Arity lives in the field types (``Expression`` vs
``Expression | None`` vs ``tuple[Expression, ...]``). There is no
``NodeKind`` dispatch, no ``match`` on tags, no ASDL table.

``Typeable`` is the interface: "you may ask me for my type."
``Typed`` is the abstract class: "I have a resolved type, here it is."
The transition between them IS the construction event: a backend handle is
``Typeable`` (it can be asked to resolve, and panics as a MISSING if it
cannot); every constructed node is ``Typed`` by virtue of being an
instance of its concrete class. A ``Typeable`` that cannot resolve NEVER
becomes a quiet ``False`` or a bare ``None``.

Asking "which node is this" is ``isinstance`` on THESE classes — blessed
and encouraged (design review, #5940 section 6). What is banned is tag
dispatch on strings.

Field *data* is memoized once per backend site on the unit (source or
shadow ref + control context). Node shells may be constructed freely over
that memo — memoize data, construct the class as often as needed. Structural
equality across sources is a CID question (mementos), not ``__eq__`` on shells.

Nothing is written onto a backend node (no stamping). Shadow rewrite is the
same construction door with a different backend: a ShadowNode that already
carries the rewritten shape, then memoized like any other ref.
"""

from __future__ import annotations

import symtable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, ClassVar, Iterator, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from .fragment import SourceFragment

from .operators import (
    BinaryOperator,
    BooleanOperator,
    ComparisonOperator,
    UnaryOperator,
)
from .panic import (
    backend_defect,
    RuntimeSelectedContextManager,
    SourceTreePanic,
    SubstituteNotWritten,
    SugarNotWritten,
    vocabulary_missing,
)
from .reporter import NULL_REPORTER, AuditReporter
from .spans import LineColSpan, LineTable, Span
from .binding_state import (
    BindingEntryV1,
    BindingMap,
    BindingState,
    BindingStateWireGap,
    BranchResultSlot,
    GuardedBinding,
    LoopProjectedBinding,
    RuntimeBindingEntryFactoryV1,
    SubstitutionTraceBuilderV1,
    UnboundBinding,
    binding_state_read_node,
    branch_result_slot,
    join_binding_state,
    unwrap_binding_state,
)

# Scope metadata travels beside temporal bindings under an unforgeable key.
# It lets recognition distinguish a builtin spelling from a lexically bound
# formal without substituting a fake value for that formal.
_LEXICALLY_BOUND_NAMES = object()
_SCOPE_OWNER_CID = object()
_SUBSTITUTION_TRACE_BUILDER = object()
_BINDING_ENTRY_FACTORY = object()
_MISSING = object()


@dataclass(frozen=True)
class ControlConstructionContextV1:
    loop_targets: tuple[object, ...] = ()
    exception_slots: tuple[str, ...] = ()

    def enter_loop(self, target: object) -> "ControlConstructionContextV1":
        return ControlConstructionContextV1(
            (*self.loop_targets, target), self.exception_slots
        )

    def enter_exception(self, slot_id: str) -> "ControlConstructionContextV1":
        return ControlConstructionContextV1(
            self.loop_targets, (*self.exception_slots, slot_id)
        )

    def nearest_loop_target(self):
        if not self.loop_targets:
            from sugar_lift_py_tests.loop_construction import LoopWireError

            raise LoopWireError("loop-control occurrence has no enclosing loop")
        return self.loop_targets[-1]

    def nearest_exception_slot(self) -> str:
        if not self.exception_slots:
            raise SugarNotWritten(
                owner="ControlConstructionContextV1.nearest_exception_slot",
                observed="bare raise has no authenticated in-flight exception slot",
                requested="an enclosing except handler effect-slot coordinate",
                fix="construct bare raise only inside the handler that owns its effect",
            )
        return self.exception_slots[-1]


def _explicit_state(name: str, state):
    if name in state:
        return unwrap_binding_state(state[name])
    return _MISSING


@dataclass(frozen=True)
class _ConditionalRaiseRoute:
    slot: BranchResultSlot
    raised_on_true: bool
    exception_identity: object | None
    exception_mro: tuple | None


_NESTED_COMPREHENSION_TEMPLATE = object()


@dataclass(frozen=True)
class SourceUnit:
    """One parsed source: oracle-pinned text, its content address, its line table.

    The identity ``(source, filename, source_cid)`` is the SourceOracle's
    triple, carried verbatim. This type never opens a file and never hashes
    text — minting an address is the oracle's job, and a unit that minted
    its own would be a second, unpinned identity for the same bytes.
    """

    filename: str
    source: str
    source_cid: str
    construction_context: object | None = None

    # populated in __post_init__, never by callers
    line_table: LineTable = field(init=False, default=None)  # type: ignore[assignment]
    module_bound_names: frozenset[str] = field(init=False, default_factory=frozenset)
    module_symtable: object = field(init=False, default=None)
    # Bound by SourceFile after the backend materializes the Module — the sole
    # structural authority for module-body identity. Never a second parse.
    typed_module: object = field(init=False, default=None)
    # Field-data memo for materialize (see construction_cache.py).
    construction_cache: object = field(init=False, default=None)
    module_direct_bindings: object = field(init=False, default=None)
    function_nodes: Tuple[object, ...] = field(init=False, default=())

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_table", LineTable(self.source))
        table = symtable.symtable(self.source, self.filename, "exec")
        object.__setattr__(self, "module_symtable", table)
        symbols = table.get_symbols()
        object.__setattr__(
            self,
            "module_bound_names",
            frozenset(
                symbol.get_name()
                for symbol in symbols
                if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()
            ),
        )
        object.__setattr__(self, "typed_module", None)
        object.__setattr__(self, "construction_cache", None)
        object.__setattr__(self, "module_direct_bindings", None)
        object.__setattr__(self, "function_nodes", ())

    def bind_typed_module(self, module: "Module") -> None:
        """Attach the already-materialized Module root (SourceFile only)."""
        object.__setattr__(self, "typed_module", module)
        bindings = {}
        for statement in module.body:
            for name in self._module_statement_bound_names(statement):
                bindings.setdefault(name, []).append(statement)
        object.__setattr__(
            self,
            "module_direct_bindings",
            {name: tuple(items) for name, items in bindings.items()},
        )
        object.__setattr__(
            self,
            "function_nodes",
            tuple(
                node
                for node in module.walk()
                if isinstance(node, (FunctionDef, AsyncFunctionDef))
            ),
        )

    def loop_target_coordinate_for_loop(self, owner: "Node"):
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.loop_construction import mint_loop_target_coordinate_v1

        if owner.kind not in ("For", "AsyncFor", "While"):
            raise ValueError("loop target owner must be a loop node")
        span = owner.line_col_span()
        return mint_loop_target_coordinate_v1(
            owner.kind,
            SourceFragmentCoordinateV1(
                self.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            ),
        )

    def _require_typed_module(self, owner: str) -> "Module":
        module = self.typed_module
        if module is None:
            raise SourceTreePanic(
                owner=owner,
                observed="typed Module is not bound on this SourceUnit",
                requested=(
                    "the SourceFile-materialized Module as structural authority"
                ),
                fix=(
                    "construct through SourceFile so the typed tree is bound "
                    "before module-level identity queries"
                ),
            )
        return module  # type: ignore[return-value]

    def function_symtable(self, name: str, lineno: int):
        matches = []

        def visit(table) -> None:
            for child in table.get_children():
                if (
                    child.get_type() == "function"
                    and child.get_name() == name
                    and child.get_lineno() == lineno
                ):
                    matches.append(child)
                visit(child)

        visit(self.module_symtable)
        if len(matches) != 1:
            raise SourceTreePanic(
                owner="SourceUnit.function_symtable",
                observed=(
                    f"{len(matches)} function symtables for {name!r} at line {lineno}"
                ),
                requested="one CPython function symtable selected by type, name, and line",
                fix="preserve the source function's exact CPython symtable identity",
            )
        return matches[0]

    def is_module_level_function(self, name: str, lineno: int) -> bool:
        """Whether this exact definition occupies an importable module slot.

        Authority is the already-materialized typed Module body (direct
        ``FunctionDef`` / ``AsyncFunctionDef`` children only) — never a second
        parse of the source text as semantic authority.
        """
        module = self._require_typed_module("SourceUnit.is_module_level_function")
        for statement in module.body:
            if statement.kind not in ("FunctionDef", "AsyncFunctionDef"):
                continue
            if (
                statement.name == name
                and statement.line_col_span().start_line == lineno
            ):
                return True
        return False

    def source_allocation_definition_for_call(self, call: "Call") -> "ClassDef | None":
        """Resolve one source allocation definition at an exact call use-site.

        Spelling is only the lexical lookup key.  Authority is the unique typed
        module binding plus the use-site's CPython scope classification. A
        local/free/nonlocal shadow or competing module binding keeps the
        allocation definition unauthenticated. Behavior is checked separately;
        it never participates in identity admission.
        """
        if not isinstance(call.func, Name):
            return None
        # A directly materialized Call/Assign still owns its ordinary sugar.
        # Absence of the SourceFile-bound module means only that class identity
        # cannot be authenticated here; it must not revoke the existing call
        # construction path.
        module = self.typed_module
        if module is None:
            return None
        span = call.line_col_span()
        containing = []
        for candidate in self.function_nodes:
            owner_span = candidate.line_col_span()
            if (
                (owner_span.start_line, owner_span.start_col)
                <= (span.start_line, span.start_col)
                <= (owner_span.end_line, owner_span.end_col)
            ):
                containing.append(candidate)
        if containing:
            owner = max(
                containing, key=lambda item: item.line_col_span().start_line
            )
            table = self.function_symtable(
                owner.name, owner.line_col_span().start_line
            )
            try:
                symbol = table.lookup(call.func.id)
            except KeyError:
                symbol = None
            if symbol is not None and (
                symbol.is_parameter()
                or symbol.is_local()
                or symbol.is_free()
                or symbol.is_nonlocal()
            ):
                return None

        bindings = (self.module_direct_bindings or {}).get(call.func.id, ())
        if len(bindings) != 1 or not isinstance(bindings[0], ClassDef):
            return None
        return bindings[0]

    @staticmethod
    def source_class_has_authenticated_default_attribute_behavior(
        definition: "ClassDef",
    ) -> bool:
        """Whether ordinary attribute storage/lookup is source-constructed."""
        forbidden_methods = {
            "__new__",
            "__getattr__",
            "__getattribute__",
            "__setattr__",
            "__delattr__",
            "__getitem__",
            "__setitem__",
            "__delitem__",
        }
        return not (
            definition.bases
            or definition.keywords
            or definition.decorators
            or definition.type_params
            or any(
                not isinstance(member, (Pass, FunctionDef))
                for member in definition.body
            )
            or any(
                isinstance(member, FunctionDef)
                and (member.name in forbidden_methods or member.decorators)
                for member in definition.body
            )
        )

    def construction_generation(self, node: "Node") -> int:
        """The source-authenticated generation of this exact occurrence.

        The byte offset is stable across shadow rewrites of the same occurrence
        and differs for distinct occurrences. It comes from the oracle-sealed
        construction fragment, never a binding owner or process counter.
        """
        if not isinstance(node, Call):
            raise SourceTreePanic(
                owner="SourceUnit.construction_generation",
                observed=type(node).__name__,
                requested="one exact Call construction occurrence",
                fix="mint object identity only at the sole Call boundary",
            )
        return node.fragment.seal().start

    @staticmethod
    def _module_statement_bound_names(statement: "Node") -> set[str]:
        if isinstance(statement, (FunctionDef, AsyncFunctionDef, ClassDef)):
            return {statement.name}
        if isinstance(statement, (Assign, AnnAssign, AugAssign)):
            targets = (
                statement.targets
                if isinstance(statement, Assign)
                else (statement.target,)
            )
            return {
                node.id
                for target in targets
                for node in target.walk()
                if isinstance(node, Name)
            }
        if statement.kind in ("Import", "ImportFrom"):
            return {
                alias.asname or alias.name.split(".", 1)[0]
                for alias in statement.names
            }
        return set()

    def exception_type_identity(self, node: "Name"):
        """Return the authenticated exception-class coordinate reaching ``node``.

        This is deliberately lexical and closed: the Python builtin vocabulary,
        an exact ``from builtins import ...`` binding, or one source class
        definition.  Ambiguous, reassigned, parameter, and computed bindings
        have no identity coordinate and therefore stay loud at the consumer.

        Structural authority is the already-materialized typed Module plus the
        unit's CPython ``symtable`` (function scope flags). No second parse.
        """
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            BUILTIN_EXCEPTION_NAMES,
        )

        module = self._require_typed_module("SourceUnit.exception_type_identity")
        span = node.line_col_span()
        containing = []
        for candidate in module.walk():
            if candidate.kind not in ("FunctionDef", "AsyncFunctionDef"):
                continue
            cspan = candidate.line_col_span()
            start = (cspan.start_line, cspan.start_col)
            end = (cspan.end_line, cspan.end_col)
            if start <= (span.start_line, span.start_col) <= end:
                containing.append(candidate)
        if containing:
            owner = max(containing, key=lambda value: value.line_col_span().start_line)
            table = self.function_symtable(owner.name, owner.line_col_span().start_line)
            try:
                symbol = table.lookup(node.id)
            except KeyError:
                symbol = None
            if symbol is not None and (
                symbol.is_parameter()
                or symbol.is_local()
                or symbol.is_free()
                or symbol.is_nonlocal()
            ):
                return None

        bindings = []
        for statement in module.body:
            kind = statement.kind
            if kind == "ImportFrom":
                for alias in statement.names:
                    if (alias.asname or alias.name) == node.id:
                        bindings.append(("import", statement.module, alias.name))
            elif kind == "ClassDef" and statement.name == node.id:
                bindings.append(("class", statement))
            elif kind in ("FunctionDef", "AsyncFunctionDef"):
                if statement.name == node.id:
                    bindings.append(("other",))
            elif kind in ("Assign", "AnnAssign", "AugAssign"):
                targets = statement.targets if kind == "Assign" else (statement.target,)
                if any(
                    isinstance(target, Name) and target.id == node.id
                    for target in targets
                ):
                    bindings.append(("other",))

        if not bindings and node.id in BUILTIN_EXCEPTION_NAMES:
            return ctor(
                "python:exception_type_identity",
                [str_const("builtins"), str_const(node.id)],
            )
        if len(bindings) != 1:
            return None
        binding = bindings[0]
        if (
            binding[0] == "import"
            and binding[1] == "builtins"
            and binding[2] in BUILTIN_EXCEPTION_NAMES
        ):
            return ctor(
                "python:exception_type_identity",
                [str_const("builtins"), str_const(binding[2])],
            )
        if binding[0] == "class":
            definition = binding[1]
            lc = definition.line_col_span()
            coordinate = (
                f"{self.source_cid}:{lc.start_line}:{lc.start_col}:"
                f"{lc.end_line}:{lc.end_col}"
            )
            return ctor(
                "python:exception_type_identity",
                [str_const("source-class"), str_const(coordinate)],
            )
        return None

    def exception_type_mro(self, node: "Name"):
        """Return the source-authenticated ancestry known for ``node``.

        Builtin/imported identities authenticate the exact class. Source class
        identities additionally carry every lexically resolved base coordinate.
        A computed base or cycle leaves the testimony unavailable, never guessed.
        """
        identity = self.exception_type_identity(node)
        if identity is None:
            return None
        module = self._require_typed_module("SourceUnit.exception_type_mro")
        definitions = [
            statement
            for statement in module.body
            if statement.kind == "ClassDef" and statement.name == node.id
        ]
        if len(definitions) != 1:
            return (identity,)

        result = [identity]
        visiting: set[str] = set()

        def append_definition(definition) -> bool:
            if definition.name in visiting:
                return False
            visiting.add(definition.name)
            for base in definition.bases:
                if not isinstance(base, Name):
                    return False
                base_identity = self.exception_type_identity(base)
                if base_identity is None:
                    return False
                if base_identity not in result:
                    result.append(base_identity)
                base_definitions = [
                    candidate
                    for candidate in module.body
                    if candidate.kind == "ClassDef" and candidate.name == base.id
                ]
                if len(base_definitions) == 1 and not append_definition(
                    base_definitions[0]
                ):
                    return False
            visiting.remove(definition.name)
            return True

        return tuple(result) if append_definition(definitions[0]) else None


class Typeable:
    """The interface: you may ask me for my node type.

    ``resolve_type`` has two arms: a concrete ``Node`` subclass,
    or ``SourceTreePanic``. There is no third arm.
    """

    def resolve_type(self) -> type["Node"]:
        raise NotImplementedError


class Typed(Typeable):
    """The abstract class: I HAVE a resolved type; resolution already happened.

    For nodes the resolved type is the concrete class itself; the
    construction event was the resolution.
    """

    def resolve_type(self) -> type["Node"]:
        tp = type(self)
        if tp in _ABSTRACT or not issubclass(tp, Node):
            # Neither of the two panics fits: this is not a backend-facing
            # question at all (no BackendHandle, no adapter, no vocabulary
            # gap) and not a structural-defect-in-backend-output question
            # either. It is an internal invariant on OUR OWN construction
            # code: only concrete classes are ever instantiated (construct.py
            # resolves through resolve_kind, which already excludes
            # _ABSTRACT). Reaching here means our own code, not a backend,
            # built an abstract instance. Raised as the common base directly
            # — deliberately, not a guess at which subclass fits.
            raise SourceTreePanic(
                owner="nodes.Typed.resolve_type",
                observed=f"instance of abstract node class {tp.__name__}",
                requested="a concrete grammar class",
                fix="abstract node classes are never instantiated",
            )
        return tp


KIND_REGISTRY: dict[str, type["Node"]] = {}
_ABSTRACT: set[type] = set()


def _abstract(cls: type) -> type:
    _ABSTRACT.add(cls)
    KIND_REGISTRY.pop(cls.__name__, None)
    return cls


class _Splice:
    """A substitute result that EXPANDS one statement into several. Returned by
    ``For.substitute`` when a concrete loop unrolls: the loop dissolves into its
    body statements, and ``_substitute_body`` splices them into the enclosing
    block so the loop's carried accumulator is just ordinary block-threading.
    Not a Node -- only ``_substitute_body`` handles it, and a `for` is always a
    statement in a block, so it is never substituted anywhere else."""

    __slots__ = ("statements", "bindings")

    def __init__(self, statements: tuple, bindings: BindingMap | None = None) -> None:
        self.statements = statements
        self.bindings = bindings or {}


@_abstract
@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Node(Typed):
    """Abstract base of every node. The hierarchy is the grammar.

    Shell over memoized field *data* on the unit ConstructionCache. Accessors
    resolve each backend slot at most once per (ref, reporter, control_context)
    into that shared row; re-reads hit the row. Shells are free to construct.
    Shadow rewrite uses the same door with a shadow backend ref.
    """

    unit: SourceUnit
    ref: object  # the BackendNode reference; duck-typed to avoid a cycle
    # The roll call. REQUIRED -- no default -- so a node cannot be constructed
    # off the roll: this is what makes construction complete BY CONSTRUCTION,
    # not by a call someone remembers to make. The constructor registers the
    # node (``__post_init__``); every child this node resolves is constructed
    # with the same reporter, so registration flows through the whole tree.
    reporter: AuditReporter
    control_context: ControlConstructionContextV1 = field(
        default_factory=ControlConstructionContextV1,
        compare=False,
        repr=False,
    )
    owned_loop_target: object | None = field(
        init=False, default=None, compare=False, repr=False
    )

    # Ordered names of fields holding child nodes (Node, optional
    # Node, or tuple of Node). Leaf values (str/int/...)
    # and operators are NOT children. Declared per class, in grammar order.
    # ClassVar on purpose: never a dataclass field, never instance state.
    _child_fields: ClassVar[Tuple[str, ...]] = ()

    def __post_init__(self) -> None:
        # THE construction event IS the registration. Registering here, in the
        # constructor, means calling ``cls(...)`` at all is showing up on the
        # roll -- there is no way to new a node without it. (register only
        # records the reference; field *data* is memoized on the unit cache.)
        self.reporter.register(self)
        if isinstance(self, (For, AsyncFor, While)):
            object.__setattr__(
                self,
                "owned_loop_target",
                self.unit.loop_target_coordinate_for_loop(self),
            )

    def _child_control_context(self, field_name: str) -> ControlConstructionContextV1:
        if isinstance(self, (For, AsyncFor, While)) and field_name == "body":
            if self.owned_loop_target is None:
                from sugar_lift_py_tests.loop_construction import LoopWireError

                raise LoopWireError("loop node has no owned target coordinate")
            return self.control_context.enter_loop(self.owned_loop_target)
        if isinstance(self, ExceptHandler) and field_name == "body":
            return self.control_context.enter_exception(self._effect_slot_id())
        if (
            isinstance(self, (FunctionDef, AsyncFunctionDef, ClassDef, Lambda))
            and field_name == "body"
        ):
            return ControlConstructionContextV1()
        return self.control_context

    def __init_subclass__(cls, **kw: object) -> None:
        super().__init_subclass__(**kw)
        KIND_REGISTRY[cls.__name__] = cls

    def __getattr__(self, name: str):
        # Field data is memoized on the unit once per site; this shell exposes it.
        if name.startswith("_"):
            raise AttributeError(name)
        from .construction_cache import ConstructionCache

        cache = self.unit.construction_cache
        if cache is None:
            cache = ConstructionCache()
            object.__setattr__(self.unit, "construction_cache", cache)
        key = cache.key(self.ref, self.reporter, self.control_context)
        row = cache.fields.setdefault(key, {})
        if name in row:
            return row[name]
        for slot_name, slot in self.ref.describe().slots:
            if slot_name == name:
                value = slot.resolve(
                    self.unit,
                    self.reporter,
                    self._child_control_context(slot_name),
                )
                row[name] = value
                return value
        if name in _declared_fields(type(self)):
            vocabulary_missing(
                owner="nodes.Node.__getattr__",
                observed=(
                    f"backend answer for {type(self).__name__} has no slot "
                    f"for declared accessor {name!r}"
                ),
                requested="the backend satisfies every accessor the class declares",
                fix="teach the adapter to answer this accessor; never guess",
            )
        raise AttributeError(name)

    @property
    def span(self) -> Span:
        desc = self.ref.describe()
        if desc.raw_span is not None:
            return desc.raw_span
        spans = list(desc.anchors) + [child.span for _, _, child in self.children()]
        if not spans:
            # Our own adapter's anchor-rule vocabulary is incomplete for a
            # kind it has not seen positioned before: a MISSING, not a defect.
            vocabulary_missing(
                owner="nodes.Node.span",
                observed=(
                    f"{self.kind} with neither a backend position nor any "
                    "spanned child"
                ),
                requested="every node has a source extent",
                fix="give the adapter an anchor rule for this kind; never invent a span",
            )
        span = spans[0]
        for s in spans[1:]:
            span = span.envelope(s)
        return span

    @property
    def kind(self) -> str:
        """Frozen wire word for serialization. Never a dispatch mechanism."""
        override = getattr(type(self), "_kind", None)
        return override if isinstance(override, str) else type(self).__name__

    def substitute(self, scope: "dict[str, Node]") -> "Node":
        """This node's substitution — the temporal rewrite that binds a hole to
        its shape. Every concrete class writes it deliberately: a leaf returns
        itself, a compound recurses (``_substitute_children``), a scope-owner
        masks its bound names before recursing, a ``Name`` binds. There is NO
        permissive recurse-by-default — a silent default would let a binding
        node capture (rewrite an outer name into a body that rebinds it) and
        never say so. So the abstract throws: writing the override IS writing
        the substitution, coverage visible in the hierarchy, the capture hazard
        loud rather than silent.
        """
        where = f"{self.unit.filename}"
        try:
            lc = self.line_col_span()
            where = f"{self.unit.filename}:{lc.start_line}:{lc.start_col}"
        except SourceTreePanic:
            pass
        raise SubstituteNotWritten(
            owner=f"{type(self).__name__}.substitute",
            observed=f"{self.kind} at {where} has no substitution written",
            requested="a deliberate substitution (recurse, mask, bind, or inert)",
            fix=(
                f"write substitute() on {type(self).__name__}: a leaf returns "
                "self, a compound returns self._substitute_children(scope), a "
                "scope-owner masks its bound names first; never a silent default"
            ),
        )

    def _substitute_field(self, value, scope):
        """Substitute ONE field value (a child Node, None, or a tuple of
        them) against a scope. Returns ``(new_value, changed)``. A scope-owner
        uses this per field so it can hand different fields different scopes
        (its signature the outer scope, its body the masked one)."""
        if value is None:
            return value, False
        if isinstance(value, Node):
            new = value.substitute(scope)
            if isinstance(new, _Splice):
                raise TypeError(
                    "_Splice escaped into a generic child field: a statement "
                    f"tuple holding a {value.kind} must go through "
                    "_substitute_body (a block), never _substitute_children -- "
                    "give the containing node a block-aware substitute"
                )
            return new, new is not value
        items = tuple(value)
        new_items = tuple(
            item.substitute(scope) if isinstance(item, Node) else item for item in items
        )
        changed = any(new is not old for new, old in zip(new_items, items))
        return (new_items if changed else value), changed

    def _substitute_children(self, scope: BindingMap) -> "Node":
        """The structural recurse a NON-binding compound opts into: substitute
        every child against the SAME scope; if any changed, rebuild me around
        them (a shadow node borrowing my span); if none changed, return myself.
        A node calls this DELIBERATELY — it is never the silent default, because
        a scope-owner must mask its bound names before it can use it safely."""
        from .shadow import rewrite

        changed: dict[str, object] = {}
        for name in type(self)._child_fields:
            new, diff = self._substitute_field(getattr(self, name), scope)
            if diff:
                changed[name] = new
        if not changed:
            return self
        return rewrite(self, **changed)

    def substitution_binding(self, scope: BindingMap) -> "Optional[BindingMap]":
        """The binding this STATEMENT introduces for the rest of its block, or
        None. An assignment returns ``{name: its substituted rhs}``; an augmented
        assignment reads the OLD value from ``scope`` to build ``x OP e``;
        everything else binds nothing. Read AFTER this statement was substituted,
        so its value is already rewritten against the scope that stood before it."""
        return None

    def refine_binding_entries(
        self, binding: BindingMap, scope: BindingMap
    ) -> BindingMap:
        """Refine freshly minted entries without creating another binding map."""
        del scope
        return binding

    def post_binding_statement(self, binding: BindingMap) -> "Node":
        """Project a store's post-version into its substituted target."""
        del binding
        return self

    def post_binding_scope(self, scope: BindingMap) -> BindingMap:
        """Apply statement-owned invalidations to the one temporal map."""
        exposed = {
            state.object_identity_cid
            for call in self.walk()
            if isinstance(call, Call)
            for state in call.exposed_object_places()
        }
        if not exposed:
            return scope
        replacements = {}
        for name, entry in scope.items():
            if (
                isinstance(name, str)
                and isinstance(entry, BindingEntryV1)
                and isinstance(entry.state, ObjectPlaceStateV1)
                and entry.state.object_identity_cid in exposed
            ):
                replacements[name] = replace(
                    entry, state=entry.state.invalidate(self.fragment)
                )
        return {**scope, **replacements}

    def _make_binop(self, left: "Node", op, right: "Node") -> "Node":
        """Construct a fresh BinOp node ``<left> <op> <right>`` as a shadow that
        borrows this node's span (so it still addresses this source site). Used
        by an augmented assignment to synthesize its ``x OP e`` rebind."""
        from .backend import Child, OpLeaf, materialize
        from .panic import backend_defect
        from .shadow import ShadowNode, _handle_of

        if not isinstance(left, Node) or not isinstance(right, Node):
            backend_defect(
                owner="nodes.Node._make_binop",
                observed=(
                    "a synthesized binary operation received non-Node "
                    f"operands {type(left).__name__}, {type(right).__name__}"
                ),
                requested=(
                    "both binary-operation operands projected into constructed "
                    "tree Nodes before shadow enrollment"
                ),
                fix=(
                    "project BindingState through binding_state_read_node at "
                    "the read site; never put state-only testimony in Child"
                ),
            )

        slots = (
            ("left", Child(_handle_of(left))),
            ("op", OpLeaf(op)),
            ("right", Child(_handle_of(right))),
        )
        return materialize(
            self.unit, ShadowNode("BinOp", self.span, slots), self.reporter
        )

    def _make_call(self, func: "Node", args: tuple = ()) -> "Node":
        """Construct a fresh Call ``<func>(<args...>)`` as a shadow borrowing
        this node's span."""
        from .backend import Child, Children, materialize
        from .shadow import ShadowNode, _handle_of

        slots = (
            ("func", Child(_handle_of(func))),
            ("args", Children(tuple(_handle_of(a) for a in args))),
            ("keywords", Children(())),
        )
        return materialize(
            self.unit, ShadowNode("Call", self.span, slots), self.reporter
        )

    def _make_attribute(self, value: "Node", attr: str) -> "Node":
        """Construct ``<value>.<attr>`` as a shadow borrowing this node's span."""
        from .backend import Child, Leaf, materialize
        from .shadow import ShadowNode, _handle_of

        slots = (
            ("value", Child(_handle_of(value))),
            ("attr", Leaf(attr)),
        )
        return materialize(
            self.unit, ShadowNode("Attribute", self.span, slots), self.reporter
        )

    def _make_none_constant(self) -> "Node":
        """Synthesize ``None`` literal at this node's span."""
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (
            ("value", Leaf(None)),
            ("literal_kind", Leaf(None)),
        )
        return materialize(
            self.unit, ShadowNode("Constant", self.span, slots), self.reporter
        )

    def _effect_slot_id(self) -> str:
        """Content-addressed slot identity from this binding occurrence.

        The preimage pins the source, fragment, and occurrence span. Re-resolving
        the same source occurrence is byte-identical; equal text at another
        occurrence cannot collide. No process identity fallback exists.
        """
        try:
            lc = self.line_col_span()
        except SourceTreePanic as exc:
            raise SugarNotWritten(
                owner=f"{type(self).__name__}._effect_slot_id",
                observed=f"{self.kind} has no stable source span for an effect slot",
                requested="a deterministic file:line:col extent for the binding site",
                fix="ensure the adapter anchors this node; never invent a process-local identity",
            ) from exc
        from sugar_lift_python_source.canonical import cid_of_json

        memento = self.fragment.seal()
        return cid_of_json(
            {
                "kind": "python-effect-slot-v1",
                "sourceCid": memento.source_cid,
                "fragmentCid": memento.cid,
                "span": {
                    "startLine": lc.start_line,
                    "startCol": lc.start_col,
                    "endLine": lc.end_line,
                    "endCol": lc.end_col,
                },
            }
        )

    def _make_effect_ref(self, slot_id: str) -> "Node":
        """Synthesize EffectRef(slot) — tree coordinate, not a floor object."""
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (("slot_id", Leaf(slot_id)),)
        return materialize(
            self.unit, ShadowNode("EffectRef", self.span, slots), self.reporter
        )

    def _make_observation_ref(self, slot_id: str, projection: str) -> "Node":
        """Synthesize ObservationRef(slot, projection) for with-as bindings."""
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (
            ("slot_id", Leaf(slot_id)),
            ("projection", Leaf(projection)),
        )
        return materialize(
            self.unit,
            ShadowNode("ObservationRef", self.span, slots),
            self.reporter,
        )

    def _substitute_body(self, statements: tuple, scope: BindingMap):
        new_items, changed, _net = self._substitute_body_tracked(statements, scope)
        return new_items, changed

    def _binding_entries(
        self, binding: BindingMap | None, scope: BindingMap
    ) -> BindingMap | None:
        if not binding:
            return binding
        builder = scope.get(_SUBSTITUTION_TRACE_BUILDER)
        if not isinstance(builder, SubstitutionTraceBuilderV1):
            return binding
        wrapped: BindingMap = {}
        for local_index, (name, state) in enumerate(binding.items()):
            if isinstance(state, BindingEntryV1):
                wrapped[name] = state
                continue
            site, path = self._binding_site_and_path(name, local_index)
            wrapped[name] = builder.mint_entry(
                binding_site=site,
                local_projection_path=path,
                state=state,
            )
        return wrapped

    def _binding_site_and_path(self, name: str, ordinal: int):
        candidates = []
        targets = getattr(self, "targets", None)
        if isinstance(targets, tuple):
            for target_index, target in enumerate(targets):
                for projection_index, node in enumerate(target.walk()):
                    if isinstance(node, Name) and node.id == name:
                        candidates.append(
                            (
                                node.fragment,
                                (
                                    "targets",
                                    target_index,
                                    "projection",
                                    projection_index,
                                ),
                            )
                        )
        target = getattr(self, "target", None)
        if isinstance(target, Node):
            for projection_index, node in enumerate(target.walk()):
                if isinstance(node, Name) and node.id == name:
                    candidates.append(
                        (node.fragment, ("target", "projection", projection_index))
                    )
        if ordinal < len(candidates):
            return candidates[ordinal]
        return self.fragment, ("constructed-projection", ordinal)

    def _substitute_body_tracked(self, statements: tuple, scope: BindingMap):
        """Substitute a statement sequence, THREADING each statement's binding:
        an assignment binds its name to its substituted rhs for the rest of the
        block. This is the temporal that used to live in ``ctx.temporal`` -- now
        it is the tree rewriting itself, statement by statement, in single-
        assignment form (each binding a fresh entry; a rebind shadows the old
        for the tail). A walrus (``NamedExpr``) nested anywhere in the statement
        also leaks its binding to the rest of the block. Returns
        ``(new_statements, changed)``."""
        from sugar_lift_py_tests.engine_log import reduction_span

        initial = dict(scope)
        scope = dict(scope)
        new_items = []
        changed = False
        for stmt in statements:
            pre_statement_scope = dict(scope)
            lc = stmt.line_col_span()
            with reduction_span(
                sugar="SubstituteStatement",
                role="temporal",
                site=f"{stmt.unit.filename}:{lc.start_line} {stmt.kind}",
            ):
                new_stmt = stmt.substitute(scope)
            if new_stmt is not stmt:
                changed = True
            # A statement may EXPAND into several: a `for` over a concrete
            # iterable dissolves into its unrolled body statements, spliced right
            # here so the block threads each one -- the loop's carried accumulator
            # is just ordinary block-threading over the unrolled sequence. The
            # expanded statements are already substituted; thread their bindings.
            produced = (
                new_stmt.statements if isinstance(new_stmt, _Splice) else (new_stmt,)
            )
            for produced_stmt in produced:
                new_items.append(produced_stmt)
                binding = produced_stmt.substitution_binding(scope)
                if binding:
                    binding = produced_stmt._binding_entries(binding, scope)
                    binding = produced_stmt.refine_binding_entries(binding, scope)
                    post_binding = produced_stmt.post_binding_statement(binding)
                    if post_binding is not produced_stmt:
                        produced_stmt = post_binding
                        new_items[-1] = produced_stmt
                        changed = True
                    scope = {**scope, **binding}
                # walrus bindings nested in the statement's expressions leak out
                # to the enclosing block (their scope is the containing function).
                for node in produced_stmt.walk():
                    if node.kind == "NamedExpr":
                        wb = node.substitution_binding(scope)
                        if wb:
                            wb = node._binding_entries(wb, scope)
                            scope = {**scope, **wb}
                scope = produced_stmt.post_binding_scope(scope)
            if isinstance(new_stmt, _Splice) and new_stmt.bindings:
                projected = stmt._binding_entries(new_stmt.bindings, scope)
                scope = {**scope, **projected}
            trace = scope.get(_SUBSTITUTION_TRACE_BUILDER)
            if isinstance(trace, SubstitutionTraceBuilderV1):
                trace.record(stmt, pre_statement_scope, scope)
        net = {k: v for k, v in scope.items() if initial.get(k) is not v}
        return (tuple(new_items) if changed else statements), changed, net

    def _bound_names_in(self, target: "Node") -> set:
        """The names an assignment/for/with/lambda target binds. A Name binds;
        a Tuple/List/Starred target nests them. Walking for Names is
        conservative on attribute/subscript targets (over-masking a load
        under-substitutes rather than captures -- safe)."""
        return {n.id for n in target.walk() if n.kind == "Name"}

    def _substitute_generators(self, generators, scope):
        """Substitute comprehension generators, threading each target as a
        binding for the FOLLOWING generators and the result expression. Returns
        (new_generators, result_scope, changed) -- result_scope has every
        generator target masked."""
        bound = set()
        inner = scope
        new_gens = []
        changed = False
        for gen in generators:
            new_gen = gen.substitute(inner)
            if new_gen is not gen:
                changed = True
            new_gens.append(new_gen)
            bound |= self._bound_names_in(gen.target)
            inner = {k: v for k, v in scope.items() if k not in bound}
        return (tuple(new_gens) if changed else generators), inner, changed

    def _pattern_bound_names(self, pattern) -> set:
        """The names a match pattern captures -- MatchAs/MatchStar `name` and a
        MatchMapping `rest`. Captures are str fields, not Name references, so
        the patterns themselves substitute structurally; the MatchCase masks
        these for its guard and body."""
        names = set()
        for n in pattern.walk():
            if n.kind in ("MatchAs", "MatchStar"):
                nm = getattr(n, "name", None)
                if isinstance(nm, str):
                    names.add(nm)
            elif n.kind == "MatchMapping":
                r = getattr(n, "rest", None)
                if isinstance(r, str):
                    names.add(r)
        return names

    def sugar(self) -> object:
        """The roll-call DISCHARGE. A node registered on the roll when it was
        constructed (``__post_init__``); desugaring is how it answers. This
        template constructs the node's sugar (``_construct_sugar``, which each
        concrete class overrides) and records the PRESENT answer through the
        reporter the node already carries -- no parameter is threaded, because
        the node holds its own roll call. The ABSENT answer is recorded inside
        the abstract ``_construct_sugar`` before it throws. So every node either
        answers present here or is reported absent there: no node discharges
        silently.
        """
        result = self._construct_sugar()
        self.reporter.present_construction(self, result)
        self.reporter.present_fact(self)
        return result

    def _construct_sugar(self) -> object:
        """This node's sugar, constructed by the node itself.

        The tree recognizes and CONSTRUCTS; sugar carries the meaning
        (desugar, witnesses, universe coordinates). Every concrete class
        either overrides this and constructs its sugar, or inherits this
        throw. Two arms enforced by inheritance: no factory, no catalog,
        no registry — the absence of an override IS the loud MISSING.

        Overrides narrow the return type to their sugar class.
        """
        where = f"{self.unit.filename}"
        try:
            lc = self.line_col_span()
            where = f"{self.unit.filename}:{lc.start_line}:{lc.start_col}"
        except SourceTreePanic:
            pass  # an unpositioned kind still panics usefully, by file
        panic = SugarNotWritten(
            owner=f"{type(self).__name__}.sugar",
            observed=f"{self.kind} at {where} has no sugar written",
            requested="a constructed sugar object",
            fix=(
                f"override sugar() on {type(self).__name__} and construct "
                "its sugar deliberately; never a fallback, never None"
            ),
        )
        # Testify the gap through the audit channel BEFORE throwing. An audit
        # walk's CollectingReporter records it (the frontier row); the report
        # never suppresses the throw. Every gap carries its own .fragment, so
        # the census -> wire memento is one hop: node.fragment.seal().
        self.reporter.report_gap(self, panic)
        raise panic

    def segment(self) -> str:
        return self.span.slice(self.unit.source)

    @property
    def fragment(self) -> "SourceFragment":
        """This node as a SourceFragment: its slice of the same oracle-pinned
        text the whole file answers. One accessor, one typed answer — never
        assembled by the caller from span + segment + cid."""
        from .fragment import SourceFragment

        return SourceFragment(unit=self.unit, span=self.span, node=self)

    def line_col_span(self) -> LineColSpan:
        return self.unit.line_table.project(self.span)

    # Stable source-location projections for consumers migrating off backend
    # AST objects.  These are computed from our span currency; they never read
    # or retain a backend-native node.
    @property
    def lineno(self) -> int:
        return self.line_col_span().start_line

    @property
    def col_offset(self) -> int:
        return self.line_col_span().start_col

    @property
    def end_lineno(self) -> int:
        return self.line_col_span().end_line

    @property
    def end_col_offset(self) -> int:
        return self.line_col_span().end_col

    def children(self) -> Iterator[tuple[str, Optional[int], "Node"]]:
        """Yield (field_name, index-or-None, child) in declared grammar order."""
        for name in type(self)._child_fields:
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, Node):
                yield name, None, value
            else:
                for i, item in enumerate(value):
                    if item is not None:
                        yield name, i, item

    def walk(self) -> Iterator["Node"]:
        """Pre-order walk over the constructed graph. Iterative — never recursive."""
        stack: list[Node] = [self]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(child for _, _, child in reversed(list(node.children())))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.kind} [{self.span.start},{self.span.end})>"


@_abstract
class Statement(Node):
    pass


@_abstract
class Expression(Node):
    pass


@_abstract
class Pattern(Node):
    """A structural pattern inside ``match``."""


@_abstract
class TypeParam(Node):
    """A PEP 695 type parameter."""


# --------------------------------------------------------------------------
# Helper nodes (grammar constituents that are not statements or expressions)
# --------------------------------------------------------------------------


class Param(Node):
    """One formal parameter. ``param_kind`` is one of: positional_only,
    positional_or_keyword, vararg, keyword_only, kwarg."""

    name: str
    annotation: Optional[Expression]
    default: Optional[Expression]
    param_kind: str
    _child_fields = ("annotation", "default")

    @property
    def arg(self) -> str:
        """The formal's identifier, projected from the typed binding site."""
        return self.name

    def substitute(self, scope):
        """A parameter's NAME is a binding site (a str, not a reference), so it
        is never captured; its annotation and default are ordinary expressions
        in the enclosing scope. So this just recurses into them -- the masking
        of the name itself is the enclosing FunctionDef's job, for the body."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """A formal stands as its symbolic universe variable. Plain parameters
        only; a default or annotation is not yet folded in, so a parameter that
        carries one stays a loud gap rather than silently dropping it."""
        if self.default is not None or self.annotation is not None:
            return super()._construct_sugar()
        from sugar_lift_py_tests.sugar.param_sugar import ParamSugar

        return ParamSugar(name=self.name, site=self.fragment)


@dataclass(frozen=True)
class ArgumentsProjection:
    """Read-only signature projection derived from typed ``Param`` nodes."""

    posonlyargs: Tuple[Param, ...]
    args: Tuple[Param, ...]
    vararg: Optional[Param]
    kwonlyargs: Tuple[Param, ...]
    kw_defaults: Tuple[Optional[Expression], ...]
    kwarg: Optional[Param]
    defaults: Tuple[Expression, ...]


def _arguments_projection(params: Tuple[Param, ...]) -> ArgumentsProjection:
    positional_only = tuple(p for p in params if p.param_kind == "positional_only")
    positional = tuple(p for p in params if p.param_kind == "positional_or_keyword")
    vararg = next((p for p in params if p.param_kind == "vararg"), None)
    keyword_only = tuple(p for p in params if p.param_kind == "keyword_only")
    kwarg = next((p for p in params if p.param_kind == "kwarg"), None)
    positional_defaults = tuple(
        p.default for p in (*positional_only, *positional) if p.default is not None
    )
    return ArgumentsProjection(
        posonlyargs=positional_only,
        args=positional,
        vararg=vararg,
        kwonlyargs=keyword_only,
        kw_defaults=tuple(p.default for p in keyword_only),
        kwarg=kwarg,
        defaults=positional_defaults,
    )


class Keyword(Node):
    """A keyword argument at a call site. ``arg is None`` means ``**expr``
    (double-star spread) — a structural absence, not a gap."""

    arg: Optional[str]
    value: Expression
    _child_fields = ("value",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)


class DictItem(Node):
    """One ``key: value`` entry of a Dict display. ``key is None`` means
    ``**expr`` (double-star spread) — a structural absence, not a gap."""

    key: Optional[Expression]
    value: Expression
    _child_fields = ("key", "value")

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)


class Comprehension(Node):
    """One ``for target in iter [if ...]*`` clause."""

    target: Expression
    iter: Expression
    ifs: Tuple[Expression, ...]
    is_async: bool
    _child_fields = ("target", "iter", "ifs")

    def substitute(self, scope):
        """One `for <target> in <iter> [if ...]` clause: iter in the given
        scope; the target binds for its own ifs. Threading across clauses is the
        enclosing comprehension's job (_substitute_generators)."""
        from .shadow import rewrite

        new_iter, di = self._substitute_field(self.iter, scope)
        bound = self._bound_names_in(self.target)
        ifs_scope = (
            {k: v for k, v in scope.items() if k not in bound} if bound else scope
        )
        new_ifs, df = self._substitute_field(self.ifs, ifs_scope)
        changed = {}
        if di:
            changed["iter"] = new_iter
        if df:
            changed["ifs"] = new_ifs
        return self if not changed else rewrite(self, **changed)


class ExceptHandler(Node):
    type_: Optional[Expression]
    name: Optional[str]
    body: Tuple[Statement, ...]
    _child_fields = ("type_", "body")

    @property
    def type(self) -> Optional[Expression]:
        return self.type_

    def substitute(self, scope):
        """except <type> as <name>: rewrite name → EffectRef(slot) in the body.

        Syntax creates the coordinate; routing authenticates it. The name is
        NOT exported after the handler (Python clears the exception target).
        Never E() — EffectRef is not an exception object.
        """
        from .shadow import rewrite

        changed = {}
        new_type, d = self._substitute_field(self.type_, scope)
        if d:
            changed["type_"] = new_type
        if self.name:
            slot_id = self._effect_slot_id()
            ref = self._make_effect_ref(slot_id)
            body_scope = {**scope, self.name: ref}
        else:
            body_scope = scope
        new_body, d = self._substitute_body(self.body, body_scope)
        if d:
            changed["body"] = new_body
        return self if not changed else rewrite(self, **changed)


class WithItem(Node):
    context_expr: Expression
    optional_vars: Optional[Expression]
    _child_fields = ("context_expr", "optional_vars")

    def substitute(self, scope):
        """Substitute the manager while retaining its enrolled source locus.

        A formal/temporal projection borrows the definition's span.  Contract
        resolution is keyed by this With occurrence, so that rewritten span
        must never replace the original manager use-site coordinate.
        """
        from .backend import Leaf, materialize
        from .shadow import ShadowNode, rewrite

        new_ctx, d = self._substitute_field(self.context_expr, scope)
        rewritten = self if not d else rewrite(self, context_expr=new_ctx)
        if hasattr(self, "manager_use_site_start_line"):
            return rewritten
        span = self.context_expr.line_col_span()
        desc = rewritten.ref.describe()
        return materialize(
            self.unit,
            ShadowNode(
                desc.kind,
                desc.raw_span or self.span,
                (
                    *desc.slots,
                    ("manager_use_site_start_line", Leaf(span.start_line)),
                    ("manager_use_site_start_col", Leaf(span.start_col)),
                    ("manager_use_site_end_line", Leaf(span.end_line)),
                    ("manager_use_site_end_col", Leaf(span.end_col)),
                ),
            ),
            self.reporter,
        )

    def _manager_use_site_span(self):
        """The immutable source occurrence used by preconstruction enrollment."""
        if hasattr(self, "manager_use_site_start_line"):
            return (
                self.manager_use_site_start_line,
                self.manager_use_site_start_col,
                self.manager_use_site_end_line,
                self.manager_use_site_end_col,
            )
        span = self.context_expr.line_col_span()
        return span.start_line, span.start_col, span.end_line, span.end_col

    def _manager_slot_id(self) -> str:
        """Stable once-eval manager identity for this with-item."""
        return self._effect_slot_id()

    def _make_manager_ref(self) -> "Node":
        """``ManagerRef(M)`` — single manager coordinate for enter and exit."""
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (("slot_id", Leaf(self._manager_slot_id())),)
        return materialize(
            self.unit, ShadowNode("ManagerRef", self.span, slots), self.reporter
        )

    def _make_enter_call(self) -> "Node":
        """Tree coordinate ``ManagerRef(M).__enter__()`` — not ``context_expr`` twice."""
        enter_attr = self._make_attribute(self._make_manager_ref(), "__enter__")
        return self._make_call(enter_attr, ())

    def _exit_face_id(self) -> str:
        """Stable exit-face coordinate X for parametric exit-arg refs."""
        return f"{self._manager_slot_id()}#exit_face"

    def _make_exit_type_ref(self) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (("face_id", Leaf(self._exit_face_id())),)
        return materialize(
            self.unit, ShadowNode("ExitTypeRef", self.span, slots), self.reporter
        )

    def _make_exit_value_ref(self) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (("face_id", Leaf(self._exit_face_id())),)
        return materialize(
            self.unit, ShadowNode("ExitValueRef", self.span, slots), self.reporter
        )

    def _make_exit_traceback_ref(self) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (("face_id", Leaf(self._exit_face_id())),)
        return materialize(
            self.unit,
            ShadowNode("ExitTracebackRef", self.span, slots),
            self.reporter,
        )

    def _make_exit_call(self, typ: "Node", val: "Node", tb: "Node") -> "Node":
        """Tree coordinate ``ManagerRef(M).__exit__(typ, val, tb)``."""
        exit_attr = self._make_attribute(self._make_manager_ref(), "__exit__")
        return self._make_call(exit_attr, (typ, val, tb))

    def _make_parametric_exit_call(self) -> "Node":
        """One exit call: ``M.__exit__(ExitTypeRef(X), ExitValueRef(X), ExitTracebackRef(X))``.

        Face-specific values are ExitFaceBinding testimony under guards —
        not alternate MethodCall sugars built at desugar time.
        """
        return self._make_exit_call(
            self._make_exit_type_ref(),
            self._make_exit_value_ref(),
            self._make_exit_traceback_ref(),
        )


class ImportAlias(Node):
    name: str
    asname: Optional[str]

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self


class MatchCase(Node):
    pattern: Pattern
    guard: Optional[Expression]
    body: Tuple[Statement, ...]
    _child_fields = ("pattern", "guard", "body")

    def substitute(self, scope, extra_bindings=None):
        """`case <pattern> [if <guard>]: <body>` -- the pattern captures bind for
        the guard and body. Pattern value-exprs evaluate in the enclosing scope;
        guard and body are masked by the captures, then any ``extra_bindings``
        (a capture bound to the match SUBJECT, threaded by ``Match.substitute``)
        are re-applied so a `case x:` body sees x = subject, not a free name."""
        from .shadow import rewrite

        bound = self._pattern_bound_names(self.pattern)
        inner = {k: v for k, v in scope.items() if k not in bound} if bound else scope
        if extra_bindings:
            inner = {**inner, **extra_bindings}
        changed = {}
        new_pat, d = self._substitute_field(self.pattern, scope)
        if d:
            changed["pattern"] = new_pat
        new_guard, d = self._substitute_field(self.guard, inner)
        if d:
            changed["guard"] = new_guard
        new_body, d = self._substitute_body(self.body, inner)
        if d:
            changed["body"] = new_body
        return self if not changed else rewrite(self, **changed)


# --------------------------------------------------------------------------
# Module and statements
# --------------------------------------------------------------------------


class Module(Node):
    body: Tuple[Statement, ...]
    _child_fields = ("body",)

    def substitute(self, scope):
        """The module is the top block: it threads its statements (a module-
        level assignment binds its name for the rest) but masks nothing -- there
        is no enclosing scope above it."""
        from .shadow import rewrite

        new_body, changed = self._substitute_body(self.body, scope)
        if not changed:
            return self
        return rewrite(self, body=new_body)


class FunctionDef(Statement):
    name: str
    params: Tuple[Param, ...]
    body: Tuple[Statement, ...]
    decorators: Tuple[Expression, ...]
    returns: Optional[Expression]
    type_params: Tuple[TypeParam, ...]
    _child_fields = ("decorators", "type_params", "params", "returns", "body")

    @property
    def args(self):
        return _arguments_projection(self.params)

    def source_visible_call_frame(self):
        """Construct this callable body through the ordinary node/Sugar door.

        Parameterized frames require the shared BindingCoordinateV1 owner.  The
        coordinate-free zero-parameter arm can already carry its exact body;
        it is built from the same substituted statement nodes as `_construct_sugar`.
        """
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.source_call_frame import SourceVisibleCallFrameV1
        from sugar_source_tree.binding_provenance import BindingCoordinateV1

        span = self.line_col_span()
        site = SourceFragmentCoordinateV1(
            self.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
        parameters = tuple(param.name for param in self.params)
        owner_cid = self.fragment.seal().cid
        coordinates = tuple(
            BindingCoordinateV1.mint(owner_cid, param.fragment, ("formal", index))
            for index, param in enumerate(self.params)
        )
        formal_scope = {
            param.name: self._make_coordinate_ref(param, coordinate)
            for param, coordinate in zip(self.params, coordinates, strict=True)
        }
        from sugar_lift_py_tests.sugar.source_visible_function_body_sugar import (
            SourceVisibleFunctionBodySugar,
        )

        substituted_body, _ = self._substitute_body(self.body, formal_scope)
        body = SourceVisibleFunctionBodySugar(
            tuple(statement.sugar() for statement in substituted_body), self.fragment
        )
        return SourceVisibleCallFrameV1(
            source_identity_cid=self.unit.source_cid,
            definition_site=site,
            definition_fragment_cid=self.fragment.seal().cid,
            parameters=parameters,
            formal_coordinates=coordinates,
            parameter_kinds=tuple(param.param_kind for param in self.params),
            default_sugars=tuple(
                param.default.sugar() if param.default is not None else None
                for param in self.params
            ),
            default_nodes=tuple(param.default for param in self.params),
            default_fragments=tuple(
                param.default.fragment if param.default is not None else None
                for param in self.params
            ),
            default_fragment_cids=tuple(
                param.default.fragment.seal().cid if param.default is not None else None
                for param in self.params
            ),
            body=body,
            owner=self,
        )

    def _source_visible_body(self, scope):
        from sugar_lift_py_tests.sugar.source_visible_function_body_sugar import (
            SourceVisibleFunctionBodySugar,
        )

        substituted_body, _ = self._substitute_body(self.body, scope)
        return SourceVisibleFunctionBodySugar(
            tuple(statement.sugar() for statement in substituted_body), self.fragment
        )

    def _make_coordinate_ref(self, param: "Param", coordinate) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "BindingCoordinateRef",
                param.span,
                (("coordinate", Leaf(coordinate)),),
            ),
            self.reporter,
        )

    def substitute(self, scope):
        """The first MASKING node: a function opens a scope. Its parameters
        (and any PEP 695 type parameters) bind their names, and ONLY THE BODY
        sees them -- so only the body's scope has those names held out. The
        signature (decorators, type params, parameter annotations/defaults, the
        return annotation) is evaluated in the ENCLOSING scope, unmasked. This
        is why the abstract panics rather than recursing blindly: a blind
        recurse would substitute an outer `x` into a body whose parameter is
        `x`, capturing it. Masking is that capture, left as a gap.
        """
        from .shadow import rewrite

        table = self.unit.function_symtable(self.name, self.line_col_span().start_line)
        parameters = frozenset(table.get_parameters())
        locals_ = frozenset(table.get_locals()) - parameters
        bound = {p.name for p in self.params}
        for tp in self.type_params:
            name = getattr(tp, "name", None)
            if isinstance(name, str):
                bound.add(name)
        body_scope = (
            {k: v for k, v in scope.items() if k not in bound} if bound else scope
        )
        inherited_bound = scope.get(_LEXICALLY_BOUND_NAMES, frozenset())
        formal_refs = {
            parameter.name: self._make_parameter_entry(parameter, ordinal, scope)
            for ordinal, parameter in enumerate(self.params)
        }
        body_scope = {
            **body_scope,
            **formal_refs,
            **{
                name: UnboundBinding(name=name, cause=self.fragment) for name in locals_
            },
            _LEXICALLY_BOUND_NAMES: frozenset(inherited_bound) | bound | locals_,
        }

        changed: dict[str, object] = {}
        # signature: the enclosing scope, unmasked (evaluated before the body).
        for field in ("decorators", "type_params", "params", "returns"):
            new, diff = self._substitute_field(getattr(self, field), scope)
            if diff:
                changed[field] = new
        # body: the enclosing scope with the bound names held out, THREADED --
        # each assignment binds its name for the statements after it.
        new_body, body_diff = self._substitute_body(self.body, body_scope)
        if body_diff:
            changed["body"] = new_body

        if not changed:
            return self
        return rewrite(self, **changed)

    def _make_parameter_entry(self, parameter: Param, ordinal: int, scope):
        ref = self._make_parameter_ref(parameter, ordinal)
        factory = scope.get(_BINDING_ENTRY_FACTORY)
        if not isinstance(factory, RuntimeBindingEntryFactoryV1):
            return ref
        return factory.mint_entry(
            binding_site=parameter.fragment,
            projection_path=("formal", ordinal),
            state=ref,
        )

    def _make_parameter_ref(self, parameter: Param, ordinal: int) -> "Node":
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
        from sugar_lift_py_tests.ir import PrimitiveSort

        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        kind = {
            "positional_only": "positional-only",
            "positional_or_keyword": "positional-or-keyword",
            "vararg": "variadic-positional",
            "keyword_only": "keyword-only",
            "kwarg": "variadic-keyword",
        }.get(parameter.param_kind)
        if kind is None:
            from .panic import BackendDefect

            raise BackendDefect(
                owner="FunctionDef._make_parameter_ref",
                observed=parameter.param_kind,
                requested="one canonical Python parameter kind",
                fix="repair the backend parameter-kind projection",
            )

        def coordinate(node: Node) -> SourceFragmentCoordinateV1:
            span = node.line_col_span()
            return SourceFragmentCoordinateV1(
                node.unit.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            )

        formal = FormalParameterCoordinateV1.mint(
            owner_source_identity_cid=self.unit.source_cid,
            owner_definition_locus=coordinate(self),
            declaration_locus=coordinate(parameter),
            ordinal=ordinal,
            parameter_kind=kind,
            declared_name=parameter.name,
            sort=PrimitiveSort("Value"),
        )
        return materialize(
            self.unit,
            ShadowNode("FormalRef", parameter.span, (("coordinate", Leaf(formal)),)),
            self.reporter,
        )

    def _construct_sugar(self):
        """`def <name>(<formals>): <body>` constructs FunctionUniverseSugar WITH
        each body statement's own sugar — the recursion, child-before-parent.

        The body is SUBSTITUTED first: every temporal binding (a local
        assignment, a conditional phi) is rewritten into the tree before any
        sugar runs, so by the time a statement is sugared its names are already
        resolved — a `Name` that survives is only ever a free formal (the
        parameters are masked by ``substitute``, so they stand as symbolic
        Vars). This is why the meaning layer holds NO temporal: substitute did
        it. A body statement whose sugar is not written yet raises
        SugarNotWritten from its own `.sugar()`, which propagates out here.
        """
        from sugar_lift_py_tests.engine_log import reduction_span
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            FunctionUniverseSugar,
        )

        # CONSTRUCTION IS THE INSTRUMENTED BOUNDARY: the span names this
        # function while it substitutes+constructs, so the engine log's
        # heartbeat testifies exactly which function a slow lift is inside --
        # the bisection instrument (macro says nothing; the active frame says
        # where to cut next). The factory had this on SugarBody.reduce; the
        # tree construction path re-enters it here.
        lc = self.line_col_span()
        where = f"{self.unit.filename}:{lc.start_line} {self.name}"
        with reduction_span(sugar="FunctionUniverse", role="construction", site=where):
            # Phase spans: the bisection instrument. A slow function names its
            # slow PHASE here; the per-statement spans inside _substitute_body
            # then name the statement. We measure; we do not guess.
            with reduction_span(sugar="Substitute", role="temporal", site=where):
                # Substitute the body against an empty scope: formals are masked
                # (stay free -> symbolic), locals thread/inline, phis -> IfExps.
                from sugar_lift_python_source.canonical import cid_of_json

                scope_owner_cid = cid_of_json(
                    {
                        "kind": "binding-scope-owner",
                        "schemaVersion": "1",
                        "source": self.fragment.seal().to_dict(),
                    }
                )
                trace_builder = SubstitutionTraceBuilderV1(scope_owner_cid)
                loop_trace_required = any(
                    isinstance(node, (For, AsyncFor, While))
                    for statement in self.body
                    for node in statement.walk()
                )
                substituted = self.substitute(
                    {
                        _SCOPE_OWNER_CID: scope_owner_cid,
                        _SUBSTITUTION_TRACE_BUILDER: trace_builder,
                        _BINDING_ENTRY_FACTORY: RuntimeBindingEntryFactoryV1(
                            scope_owner_cid
                        ),
                    }
                )
            with reduction_span(sugar="Construct", role="construction", site=where):
                from .backend import materialize
                from .binding_state import ConstructionTestimonyReporterV1

                if loop_trace_required:
                    testimony_reporter = ConstructionTestimonyReporterV1(
                        self.reporter, trace_builder
                    )
                    construction_root = materialize(
                        substituted.unit, substituted.ref, testimony_reporter
                    )
                    statements = tuple(stmt.sugar() for stmt in construction_root.body)
                    substitution_trace = trace_builder.freeze(testimony_reporter)
                else:
                    # Every statement still has an immutable runtime snapshot.
                    # Only a loop consumer demands the sealed state projection;
                    # ordinary functions retain the trace without re-hashing all
                    # constructed ProofIR content merely for coexistence.
                    statements = tuple(stmt.sugar() for stmt in substituted.body)
                    substitution_trace = trace_builder.freeze()
                bridge_source_symbol = None
                context = self.unit.construction_context
                workspace_root = getattr(context, "workspace_root", None)
                if workspace_root is not None and self.unit.is_module_level_function(
                    self.name, self.line_col_span().start_line
                ):
                    from pathlib import Path

                    relative = (
                        Path(self.unit.filename)
                        .resolve()
                        .relative_to(Path(workspace_root).resolve())
                    )
                    module_parts = list(relative.with_suffix("").parts)
                    if module_parts and module_parts[-1] == "__init__":
                        module_parts.pop()
                    module_name = ".".join(module_parts)
                    bridge_source_symbol = f"python:{module_name}.{self.name}"
                return FunctionUniverseSugar(
                    name=self.name,
                    formals=tuple(p.name for p in self.params),
                    statements=statements,
                    site=self.fragment,
                    bridge_source_symbol=bridge_source_symbol,
                    substitution_trace=substitution_trace,
                )


class AsyncFunctionDef(Statement):
    name: str
    params: Tuple[Param, ...]
    body: Tuple[Statement, ...]
    decorators: Tuple[Expression, ...]
    returns: Optional[Expression]
    type_params: Tuple[TypeParam, ...]
    _child_fields = ("decorators", "type_params", "params", "returns", "body")

    @property
    def args(self):
        return _arguments_projection(self.params)

    def substitute(self, scope):
        """Same scope shape as FunctionDef (identical fields): masks its
        parameters for the threaded body."""
        return FunctionDef.substitute(self, scope)


class ClassDef(Statement):
    name: str
    bases: Tuple[Expression, ...]
    keywords: Tuple[Keyword, ...]
    body: Tuple[Statement, ...]
    decorators: Tuple[Expression, ...]
    type_params: Tuple[TypeParam, ...]
    _child_fields = ("decorators", "type_params", "bases", "keywords", "body")

    def substitute(self, scope):
        """A class: decorators and type params evaluate in the enclosing scope;
        the type params then bind for the bases, keywords, and body. The body is
        threaded (a class body reads the enclosing scope; it opens no closure)."""
        from .shadow import rewrite

        tnames = {
            n
            for tp in self.type_params
            for n in [getattr(tp, "name", None)]
            if isinstance(n, str)
        }
        inner = {k: v for k, v in scope.items() if k not in tnames} if tnames else scope
        changed = {}
        for fld in ("decorators", "type_params"):
            new, d = self._substitute_field(getattr(self, fld), scope)
            if d:
                changed[fld] = new
        for fld in ("bases", "keywords"):
            new, d = self._substitute_field(getattr(self, fld), inner)
            if d:
                changed[fld] = new
        new_body, d = self._substitute_body(self.body, inner)
        if d:
            changed["body"] = new_body
        return self if not changed else rewrite(self, **changed)

    def _construct_sugar(self):
        """Construct source-visible class structure through child method Sugars.

        Instantiation/receiver fields remain a typed coordinate gap in the
        resulting floor value.  No class body is interpreted beside this door.
        """
        methods = tuple(item for item in self.body if isinstance(item, FunctionDef))
        docstring_cid = None
        if self.body:
            first = self.body[0]
            if (
                isinstance(first, Expr)
                and isinstance(first.value, Constant)
                and isinstance(first.value.value, str)
            ):
                docstring_cid = first.fragment.seal().cid
        class_assignments = tuple(
            (item.targets[0].id, item.value, item.fragment)
            for item in self.body
            if isinstance(item, Assign)
            and len(item.targets) == 1
            and isinstance(item.targets[0], Name)
        )
        annotated_assignments = tuple(
            item
            for item in self.body
            if isinstance(item, AnnAssign) and isinstance(item.target, Name)
        )
        unsupported = tuple(
            item
            for index, item in enumerate(self.body)
            if not isinstance(item, (FunctionDef, ClassDef, Pass))
            and not (
                index == 0
                and isinstance(item, Expr)
                and isinstance(item.value, Constant)
                and isinstance(item.value.value, str)
            )
            and not (
                isinstance(item, Assign)
                and len(item.targets) == 1
                and isinstance(item.targets[0], Name)
            )
            and not (isinstance(item, AnnAssign) and isinstance(item.target, Name))
        )
        if unsupported:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner="ClassDef._construct_sugar",
                observed=f"unsupported class member {unsupported[0].kind}",
                requested="a total source-visible class member construction arm",
                fix="add the member's ordinary node Sugar arm or keep the class loud",
            )
        from sugar_lift_py_tests.floor import (
            ConstructedClassFieldV1,
            ConstructedClassMethodV1,
        )
        from sugar_lift_py_tests.sugar.class_definition_sugar import (
            ClassDefinitionSugar,
        )

        constructed = tuple(
            ConstructedClassMethodV1(
                method.name,
                method.fragment.seal().cid,
                method.sugar(),
                method.source_visible_call_frame(),
            )
            for method in methods
        )
        fields = (
            tuple(
                ConstructedClassFieldV1(
                    name,
                    fragment.seal().cid,
                    value.sugar(),
                )
                for name, value, fragment in class_assignments
            )
            + tuple(
                ConstructedClassFieldV1(
                    item.target.id,
                    item.fragment.seal().cid,
                    item.value.sugar(),
                )
                for item in annotated_assignments
                if item.value is not None
            )
            + tuple(
                ConstructedClassFieldV1(
                    item.name,
                    item.fragment.seal().cid,
                    item.sugar(),
                )
                for item in self.body
                if isinstance(item, ClassDef)
            )
        )
        base_sugars = ()
        if self.bases:
            context = self.unit.construction_context
            table = (
                getattr(context, "source_class_bases", None)
                if context is not None
                else None
            )
            base_sugars = (
                () if table is None else table.get(self.fragment.seal().cid, ())
            )
        return ClassDefinitionSugar(
            class_name=self.name,
            source_identity_cid=self.unit.source_cid,
            definition_fragment_cid=self.fragment.seal().cid,
            methods=constructed,
            fields=fields,
            docstring_cid=docstring_cid,
            annotation_cids=tuple(
                item.fragment.seal().cid for item in annotated_assignments
            ),
            decorator_cids=tuple(item.fragment.seal().cid for item in self.decorators),
            base_sugars=base_sugars,
            base_fragment_cids=tuple(base.fragment.seal().cid for base in self.bases),
            site=self.fragment,
        )

    def source_visible_constructor_frame(self):
        """The class call projected through its already-constructed definition."""
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.source_call_frame import SourceVisibleCallFrameV1
        from sugar_lift_py_tests.sugar.class_constructor_body_sugar import (
            ClassConstructorBodySugar,
        )
        from sugar_source_tree.binding_provenance import BindingCoordinateV1

        initializer = next(
            (
                item
                for item in self.body
                if isinstance(item, FunctionDef) and item.name == "__init__"
            ),
            None,
        )
        params = () if initializer is None else initializer.params[1:]
        owner_cid = self.fragment.seal().cid
        coordinates = tuple(
            BindingCoordinateV1.mint(owner_cid, param.fragment, ("formal", index))
            for index, param in enumerate(params)
        )
        span = self.line_col_span()
        site = SourceFragmentCoordinateV1(
            self.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
        formal_scope = {
            param.name: self._make_constructor_coordinate_ref(param, coordinate)
            for param, coordinate in zip(params, coordinates, strict=True)
        }
        return SourceVisibleCallFrameV1(
            source_identity_cid=self.unit.source_cid,
            definition_site=site,
            definition_fragment_cid=owner_cid,
            parameters=tuple(param.name for param in params),
            formal_coordinates=coordinates,
            parameter_kinds=tuple(param.param_kind for param in params),
            default_sugars=tuple(
                param.default.sugar() if param.default is not None else None
                for param in params
            ),
            default_nodes=tuple(param.default for param in params),
            default_fragments=tuple(
                param.default.fragment if param.default is not None else None
                for param in params
            ),
            default_fragment_cids=tuple(
                param.default.fragment.seal().cid if param.default is not None else None
                for param in params
            ),
            body=self._source_visible_body(formal_scope),
            owner=self,
        )

    def _make_constructor_coordinate_ref(self, param: "Param", coordinate) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "BindingCoordinateRef",
                param.span,
                (("coordinate", Leaf(coordinate)),),
            ),
            self.reporter,
        )

    def _source_visible_body(self, scope):
        from sugar_lift_py_tests.sugar.class_constructor_body_sugar import (
            ClassConstructorBodySugar,
        )
        from sugar_source_tree.binding_provenance import (
            BindingCoordinateV1,
            BoundBindingStateV1,
        )
        from sugar_source_tree.binding_state import BindingEntryV1

        initializer = next(
            (
                item
                for item in self.body
                if isinstance(item, FunctionDef) and item.name == "__init__"
            ),
            None,
        )
        initializer_body = None
        receiver_coordinate_cid = None
        if initializer is not None:
            receiver_param = initializer.params[0]
            coordinate = BindingCoordinateV1.mint(
                self.fragment.seal().cid,
                receiver_param.fragment,
                ("receiver", 0),
            )
            receiver = self._make_constructed_receiver_ref(coordinate.cid)
            receiver_coordinate_cid = coordinate.cid
            initializer_scope = {
                receiver_param.name: BindingEntryV1(
                    coordinate, receiver, BoundBindingStateV1(None)
                ),
                **scope,
            }
            initializer_body = initializer._source_visible_body(initializer_scope)
        return ClassConstructorBodySugar(
            definition=self.sugar(),
            initializer_body=initializer_body,
            receiver_coordinate_cid=receiver_coordinate_cid,
            site=self.fragment,
        )

    def _make_constructed_receiver_ref(self, receiver_coordinate_cid):
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "ConstructedReceiverRef",
                self.span,
                (
                    ("class_name", Leaf(self.name)),
                    ("binding_coordinate_cid", Leaf(receiver_coordinate_cid)),
                ),
            ),
            self.reporter,
        )


class Return(Statement):
    value: Optional[Expression]
    _child_fields = ("value",)

    def substitute(self, scope):
        """`return <expr>` binds nothing: recurse into the returned expression."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """Construct the function exit, including Python's real empty return."""
        from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar

        return ReturnSugar(
            value=self.value.sugar() if self.value is not None else None,
            site=self.fragment,
        )


class Delete(Statement):
    targets: Tuple[Expression, ...]
    _child_fields = ("targets",)

    def substitute(self, scope):
        """Lower supported targets to ordered delete operations."""
        if any(not isinstance(t, (Name, Attribute, Subscript)) for t in self.targets):
            return self._substitute_children(scope)

        current = dict(scope)
        operations = []
        for target in self.targets:
            if isinstance(target, Name):
                prior = _explicit_state(target.id, current)
                if prior is _MISSING:
                    prior = UnboundBinding(name=target.id, cause=target.fragment)
                operation = self._make_delete_name(target.id, prior, target.span)
                current[target.id] = UnboundBinding(
                    name=target.id, cause=target.fragment
                )
            elif isinstance(target, Attribute):
                operation = self._make_delete_attribute(
                    target.value.substitute(current), target.attr, target.span
                )
            else:
                operation = self._make_delete_subscript(
                    target.value.substitute(current),
                    target.slice_.substitute(current),
                    target.span,
                )
            operations.append(operation)
        return operations[0] if len(operations) == 1 else _Splice(tuple(operations))

    def _make_delete_name(
        self, name: str, prior: BindingState, span: Span | None = None
    ) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "DeleteName",
                span or self.span,
                (("name", Leaf(name)), ("prior", Leaf(prior))),
            ),
            self.reporter,
        )

    def _make_delete_attribute(self, receiver, attr: str, span: Span) -> "Node":
        from .backend import Child, Leaf, materialize
        from .shadow import ShadowNode, _handle_of

        return materialize(
            self.unit,
            ShadowNode(
                "DeleteAttribute",
                span,
                (("receiver", Child(_handle_of(receiver))), ("attr", Leaf(attr))),
            ),
            self.reporter,
        )

    def _make_delete_subscript(self, receiver, index, span: Span) -> "Node":
        from .backend import Child, materialize
        from .shadow import ShadowNode, _handle_of

        return materialize(
            self.unit,
            ShadowNode(
                "DeleteSubscript",
                span,
                (
                    ("receiver", Child(_handle_of(receiver))),
                    ("index", Child(_handle_of(index))),
                ),
            ),
            self.reporter,
        )


class Assign(Statement):
    targets: Tuple[Expression, ...]
    value: Expression
    _child_fields = ("targets", "value")

    def substitute(self, scope):
        """Substitute the RHS only. The targets are BINDING SITES -- a Name
        being defined, not referenced -- so they are never substituted (that
        would rewrite the name being bound). The binding this introduces for the
        rest of the block is reported by substitution_binding()."""
        from .shadow import rewrite

        new_value, changed = self._substitute_field(self.value, scope)
        changes = {"value": new_value} if changed else {}
        if len(self.targets) == 1 and isinstance(
            self.targets[0], (Attribute, Subscript)
        ):
            target = self.targets[0]
            receiver, receiver_changed = self._substitute_field(target.value, scope)
            if receiver_changed:
                changes["targets"] = (rewrite(target, value=receiver),)
        if not changes:
            return self
        return rewrite(self, **changes)

    def _destructured_binding(self):
        # Destructure only an already-constructed Tuple/List display.  This is
        # structural projection, not an iterator guess: a symbolic/opaque RHS
        # has no authenticated cardinality and therefore stays loud.
        target = self.targets[0]
        if not isinstance(target, (Tuple_, List)):
            return None
        return self._destructure_display(target, self.value)

    def _destructure_display(self, target, value):
        if isinstance(target, Name):
            return {target.id: value}
        if not isinstance(target, (Tuple_, List)) or not isinstance(
            value, (Tuple_, List)
        ):
            return None

        starred = [
            index
            for index, element in enumerate(target.elts)
            if isinstance(element, Starred)
        ]
        if len(starred) > 1:
            return None
        pairs = []
        if not starred:
            if len(target.elts) != len(value.elts):
                return None
            pairs = list(zip(target.elts, value.elts))
        else:
            star_index = starred[0]
            suffix = len(target.elts) - star_index - 1
            if len(value.elts) < len(target.elts) - 1:
                return None
            pairs.extend(zip(target.elts[:star_index], value.elts[:star_index]))
            rest_end = len(value.elts) - suffix if suffix else len(value.elts)
            rest = self._make_unpack_rest_list(value.elts[star_index:rest_end])
            pairs.append((target.elts[star_index].value, rest))
            if suffix:
                pairs.extend(zip(target.elts[-suffix:], value.elts[-suffix:]))

        bindings = {}
        for child_target, child_value in pairs:
            child = self._destructure_display(child_target, child_value)
            if child is None:
                return None
            bindings.update(child)
        return bindings

    def _make_unpack_rest_list(self, elements):
        """The starred target's real CPython list result, from real RHS children."""
        from .backend import Children, materialize
        from .shadow import ShadowNode, _handle_of

        return materialize(
            self.unit,
            ShadowNode(
                "List",
                self.span,
                (
                    (
                        "elts",
                        Children(tuple(_handle_of(element) for element in elements)),
                    ),
                ),
            ),
            self.reporter,
        )

    def _binding_site_and_path(self, name: str, ordinal: int):
        del ordinal
        matches = []

        def collect(target, path):
            if isinstance(target, Name):
                if target.id == name:
                    matches.append((target.fragment, path))
                return
            if isinstance(target, Starred):
                collect(target.value, (*path, "starred"))
                return
            if isinstance(target, (Tuple_, List)):
                kind = "tuple" if isinstance(target, Tuple_) else "list"
                for index, child in enumerate(target.elts):
                    collect(child, (*path, kind, index))

        for target_index, target in enumerate(self.targets):
            collect(target, ("targets", target_index))
        if matches:
            # Repeated targets are legal; the final store is the live binding.
            return matches[-1]
        return super()._binding_site_and_path(name, 0)

    def substitution_binding(self, scope):
        # A single Name target binds its name to the already-substituted rhs.
        # A single Tuple/List target of plain Names destructures against a
        # matching display rhs (see _destructured_binding). A chain of plain
        # Name targets (`x = y = e`) binds each name to the same rhs.
        # Attribute / subscript targets, starred/nested tuples, and arity
        # mismatches thread nothing -- their references stay honest gaps
        # rather than a wrong binding.
        if len(self.targets) == 1:
            target = self.targets[0]
            if isinstance(target, Name):
                return {target.id: self.value}
            if isinstance(target, Attribute) and isinstance(
                target.value, ObjectPlaceStateV1
            ):
                updated = target.value.with_attribute_store(
                    target.attr, self.value, self.fragment
                )
                if updated is None:
                    return None
                return {
                    name: replace(entry, state=updated)
                    for name, entry in scope.items()
                    if isinstance(name, str)
                    and isinstance(entry, BindingEntryV1)
                    and isinstance(entry.state, ObjectPlaceStateV1)
                    and entry.state.object_identity_cid
                    == target.value.object_identity_cid
                }
            return self._destructured_binding()
        if all(isinstance(t, (Name, Attribute, Subscript)) for t in self.targets):
            # Store targets do not bind lexical names, but they also do not
            # erase the Name targets in the same left-to-right assignment.
            return {t.id: self.value for t in self.targets if isinstance(t, Name)}
        return None

    def refine_binding_entries(self, binding, scope):
        del scope
        if len(self.targets) != 1 or not isinstance(self.targets[0], Name):
            return binding
        entry = binding.get(self.targets[0].id)
        if not isinstance(entry, BindingEntryV1):
            return binding
        if isinstance(entry.state, ObjectPlaceStateV1):
            return {
                **binding,
                self.targets[0].id: replace(
                    entry.with_testimony(entry.state.construction_testimony),
                    state=entry.state,
                ),
            }
        if isinstance(entry.state, OpaqueObjectStateV1):
            return binding
        state = self._object_place_state(entry)
        if state is None:
            return binding
        if isinstance(state, OpaqueObjectStateV1):
            return {**binding, self.targets[0].id: replace(entry, state=state)}
        return {
            **binding,
            self.targets[0].id: replace(
                entry.with_testimony(state.construction_testimony), state=state
            ),
        }

    def _object_place_state(self, entry: BindingEntryV1):
        del entry
        if not isinstance(self.value, Call):
            return None
        definition = self.unit.source_allocation_definition_for_call(self.value)
        if definition is None:
            from .backend import Child, Leaf, materialize
            from .object_identity import OpaqueObjectCoordinateV1
            from .shadow import ShadowNode, _handle_of

            coordinate = OpaqueObjectCoordinateV1.mint(
                call_occurrence=self.value.fragment,
                construction_generation=self.unit.construction_generation(self.value),
                source_cid=self.unit.source_cid,
                artifact_cid=self.unit.source_cid,
            )
            return materialize(
                self.unit,
                ShadowNode(
                    "OpaqueObjectStateV1",
                    self.targets[0].span,
                    (
                        ("object_coordinate", Leaf(coordinate)),
                        ("base", Child(_handle_of(self.value))),
                    ),
                ),
                self.reporter,
            )
        if not self.unit.source_class_has_authenticated_default_attribute_behavior(
            definition
        ):
            return None
        constructed = self._constructed_floor_value(self.value)
        if constructed is None:
            return None
        floor_value, testimony = constructed
        from sugar_lift_py_tests.floor import ObjectValue
        from sugar_lift_py_tests.outcome import Complete

        if not isinstance(floor_value, ObjectValue):
            return None
        class_outcome = definition.sugar().desugar()
        if not isinstance(class_outcome, Complete):
            return None
        class_definition_cid = class_outcome.value.class_definition_cid
        from .object_identity import SourceObjectCoordinateV1

        object_coordinate = SourceObjectCoordinateV1.mint(
            allocation_definition=definition.fragment,
            call_occurrence=self.value.fragment,
            construction_generation=self.unit.construction_generation(self.value),
            source_cid=self.unit.source_cid,
            artifact_cid=self.unit.source_cid,
        )
        from .backend import Child, Children, Leaf, materialize
        from .shadow import ShadowNode, _handle_of

        return materialize(
            self.unit,
            ShadowNode(
                "ObjectPlaceStateV1",
                self.targets[0].span,
                (
                    ("object_coordinate", Leaf(object_coordinate)),
                    ("class_definition_cid", Leaf(class_definition_cid)),
                    ("construction_testimony", Leaf(testimony)),
                    ("constructed_value", Leaf(floor_value)),
                    ("object_identity_cid", Leaf(object_coordinate.cid)),
                    ("base", Child(_handle_of(self.value))),
                    ("selectors", Leaf(())),
                    ("values", Children(())),
                    ("value_testimonies", Leaf(())),
                    ("version_cids", Leaf(())),
                    ("version_records", Leaf(())),
                    ("prior_version_cids", Leaf(())),
                    ("store_occurrence_cids", Leaf(())),
                    ("invalidated_by_opaque_call", Leaf(False)),
                ),
            ),
            self.reporter,
        )

    @staticmethod
    def _constructed_floor_value(value):
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import _term_content_cid
        from sugar_lift_py_tests.outcome import Complete
        from .binding_provenance import ConstructedValueTestimonyV1

        outcome = value.sugar().desugar()
        if not isinstance(outcome, Complete):
            return None
        constructed = outcome.value
        if isinstance(constructed, CallSiteValue):
            constructed = constructed.force_floor(
                None,
                owner="Assign._constructed_floor_value",
                project_callsite=False,
            )
        term = constructed.to_term(owner="Assign._constructed_floor_value")
        testimony = ConstructedValueTestimonyV1.mint(
            value.fragment, _term_content_cid(term)
        )
        return constructed, testimony

    def post_binding_statement(self, binding):
        if len(self.targets) == 1 and isinstance(self.targets[0], Name):
            entry = binding.get(self.targets[0].id)
            if isinstance(entry, BindingEntryV1) and isinstance(
                entry.state, ObjectPlaceStateV1
            ):
                from .shadow import rewrite

                return rewrite(self, value=entry.state)
        if len(self.targets) != 1 or not isinstance(self.targets[0], Attribute):
            return self
        prior = self.targets[0].value
        if not isinstance(prior, ObjectPlaceStateV1):
            return self
        updated = next(
            (
                entry.state
                for entry in binding.values()
                if isinstance(entry, BindingEntryV1)
                and isinstance(entry.state, ObjectPlaceStateV1)
                and entry.state.object_identity_cid == prior.object_identity_cid
            ),
            None,
        )
        if updated is None:
            return self
        from .shadow import rewrite

        target = self.targets[0]
        projected = updated.attribute_field(target.attr)
        if projected is None:
            return self
        return rewrite(
            self,
            targets=(rewrite(target, value=updated),),
            value=projected,
        )

    def _construct_sugar(self):
        """`<name> = <rhs>` constructs AssignSugar WITH the rhs's sugar (held as
        the deferred source). A destructured tuple/list target or a chained
        `x = y = e` whose binding threaded constructs MultiAssignSugar -- both
        are inert once substitute has done its work, exactly like the single
        Name case. Any shape whose binding did NOT thread (attribute/subscript
        targets, starred/nested tuples, arity mismatches) stays a loud gap --
        never a partial binding rendered inert."""
        if len(self.targets) == 1 and isinstance(self.targets[0], Name):
            from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar

            return AssignSugar(
                name=self.targets[0].id,
                value=self.value.sugar(),
                site=self.fragment,
            )

        if len(self.targets) == 1 and isinstance(self.targets[0], (Tuple_, List)):
            bindings = self._destructured_binding()
            if bindings is None:
                return super()._construct_sugar()
            from sugar_lift_py_tests.sugar.assign_sugar import MultiAssignSugar

            return MultiAssignSugar(
                bindings=tuple((name, val.sugar()) for name, val in bindings.items()),
                site=self.fragment,
            )

        if len(self.targets) > 1 and all(isinstance(t, Name) for t in self.targets):
            from sugar_lift_py_tests.sugar.assign_sugar import ChainedAssignSugar

            value_sugar = self.value.sugar()
            return ChainedAssignSugar(
                bindings=tuple((t.id, value_sugar) for t in self.targets),
                stores=(),
                value=value_sugar,
                site=self.fragment,
            )

        if len(self.targets) > 1 and all(
            isinstance(t, (Name, Attribute, Subscript)) for t in self.targets
        ):
            from sugar_lift_py_tests.sugar.assign_sugar import ChainedAssignSugar

            value_sugar = self.value.sugar()
            stores = []
            for target in self.targets:
                if isinstance(target, Attribute):
                    from sugar_lift_py_tests.sugar.store_effect_sugar import (
                        AttributeStoreEffectSugar,
                    )

                    stores.append(
                        AttributeStoreEffectSugar(
                            receiver=target.value.sugar(),
                            value=value_sugar,
                            attr=target.attr,
                            site=target.fragment,
                        )
                    )
                elif isinstance(target, Subscript):
                    from sugar_lift_py_tests.sugar.store_effect_sugar import (
                        SubscriptStoreEffectSugar,
                    )

                    stores.append(
                        SubscriptStoreEffectSugar(
                            index_text=target.slice_.fragment.text,
                            site=target.fragment,
                        )
                    )
            return ChainedAssignSugar(
                bindings=tuple(
                    (target.id, value_sugar)
                    for target in self.targets
                    if isinstance(target, Name)
                ),
                stores=tuple(stores),
                value=value_sugar,
                site=self.fragment,
            )

        if len(self.targets) == 1 and isinstance(self.targets[0], Attribute):
            if isinstance(self.targets[0].value, ObjectPlaceStateV1):
                from sugar_lift_py_tests.sugar.place_assign_sugar import (
                    PlaceAssignSugar,
                )

                return PlaceAssignSugar(
                    receiver=self.targets[0].value.sugar(),
                    selector_kind="attribute",
                    selector=self.targets[0].attr,
                    value=self.value.sugar(),
                    site=self.fragment,
                )
            if isinstance(
                self.targets[0].value,
                (BindingCoordinateRef, ConstructedReceiverRef),
            ):
                from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
                    ReceiverFieldStoreSugar,
                )

                return ReceiverFieldStoreSugar(
                    receiver=self.targets[0].value.sugar(),
                    value=self.value.sugar(),
                    attr=self.targets[0].attr,
                    site=self.fragment,
                )
            from sugar_lift_py_tests.sugar.store_effect_sugar import (
                AttributeStoreEffectSugar,
            )

            return AttributeStoreEffectSugar(
                receiver=self.targets[0].value.sugar(),
                value=self.value.sugar(),
                attr=self.targets[0].attr,
                site=self.fragment,
            )

        if len(self.targets) == 1 and isinstance(self.targets[0], Subscript):
            if isinstance(self.targets[0].value, ObjectPlaceStateV1):
                return super()._construct_sugar()
            from sugar_lift_py_tests.sugar.store_effect_sugar import (
                SubscriptStoreEffectSugar,
            )

            return SubscriptStoreEffectSugar(
                index_text=self.targets[0].slice_.fragment.text,
                site=self.fragment,
            )

        return super()._construct_sugar()


class AugAssign(Statement):
    target: Expression
    op: BinaryOperator
    value: Expression
    _child_fields = ("target", "value")

    def substitute(self, scope):
        """`<target> OP= <value>` -- substitute the value; the target is both
        read and written, but as a node it is a binding site, not substituted.
        The rebind (target OP value) is threaded by substitution_binding."""
        from .shadow import rewrite

        new_value, d = self._substitute_field(self.value, scope)
        rewritten = self if not d else rewrite(self, value=new_value)
        if not isinstance(rewritten.target, Name):
            return rewritten
        name = rewritten.target.id
        old_state = unwrap_binding_state(scope.get(name, rewritten.target))
        old_read = binding_state_read_node(
            old_state,
            make_read=rewritten.target._make_binding_read,
        )
        operation = rewritten._make_binop(old_read, rewritten.op, rewritten.value)
        from .backend import Child, materialize
        from .shadow import ShadowNode, _handle_of

        desc = rewritten.ref.describe()
        return materialize(
            self.unit,
            ShadowNode(
                desc.kind,
                desc.raw_span or self.span,
                (*desc.slots, ("operation", Child(_handle_of(operation)))),
            ),
            self.reporter,
        )

    def substitution_binding(self, scope):
        # `x OP= e` rebinds x to `x OP e`, reading the OLD x from the scope
        # (or the target itself if x was free). Only a plain Name target binds.
        if not isinstance(self.target, Name):
            return None
        operation = getattr(self, "operation", None)
        if isinstance(operation, Node):
            return {self.target.id: operation}
        name = self.target.id
        old_state = scope.get(name, self.target)
        old_state = unwrap_binding_state(old_state)
        old_read = binding_state_read_node(
            old_state,
            make_read=self.target._make_binding_read,
        )
        return {name: self._make_binop(old_read, self.op, self.value)}

    def _construct_sugar(self):
        """`<target> OP= <value>` -- a plain Name target is INERT at the
        meaning layer: substitution_binding ALWAYS threads for a Name target
        (it falls back to the target itself as the old value when nothing was
        bound yet, so there is no shape where a Name target both fails to
        thread and stays loud). The rebind rode into the tail as the fold
        binding; the statement itself states nothing more. Attribute/subscript
        targets are runtime stores rather than lexical bindings, so they reuse
        Assign's typed attribute/subscript store effects."""
        if isinstance(self.target, Name):
            from sugar_lift_py_tests.sugar.augassign_sugar import AugAssignSugar

            operation = getattr(self, "operation", None)
            if not isinstance(operation, Node):
                return super()._construct_sugar()
            return AugAssignSugar(
                operation=operation.sugar(),
                site=self.fragment,
            )
        if isinstance(self.target, Attribute):
            from sugar_lift_py_tests.sugar.store_effect_sugar import (
                AttributeStoreEffectSugar,
            )

            return AttributeStoreEffectSugar(
                receiver=self.target.value.sugar(),
                value=self.value.sugar(),
                attr=self.target.attr,
                site=self.fragment,
            )
        if isinstance(self.target, Subscript):
            from sugar_lift_py_tests.sugar.store_effect_sugar import (
                SubscriptStoreEffectSugar,
            )

            return SubscriptStoreEffectSugar(
                index_text=self.target.slice_.fragment.text,
                site=self.fragment,
            )
        return super()._construct_sugar()


class AnnAssign(Statement):
    target: Expression
    annotation: Expression
    value: Optional[Expression]
    simple: bool
    _child_fields = ("target", "annotation", "value")

    def substitute(self, scope):
        """`<target>: <ann> = <value>` -- substitute the annotation and value;
        the target is a binding site, never substituted."""
        from .shadow import rewrite

        changed = {}
        for fld in ("annotation", "value"):
            new, d = self._substitute_field(getattr(self, fld), scope)
            if d:
                changed[fld] = new
        return self if not changed else rewrite(self, **changed)

    def substitution_binding(self, scope):
        # Only an annotated assignment WITH a value and a plain Name target
        # binds; a bare `x: int` is a declaration and binds nothing.
        if self.value is not None and isinstance(self.target, Name):
            return {self.target.id: self.value}
        return None

    def _construct_sugar(self):
        """`<target>: <annotation> [= <value>]` -- a plain Name target is
        INERT at the meaning layer. If there is a value, its binding already
        threaded via substitution_binding, exactly as a plain Assign's does;
        the rebind rode into the tail and this node contributes nothing more.
        If there is no value, it is a bare declaration: no bytecode runs, no
        binding is introduced, nothing happens at runtime at all.  A bare
        attribute annotation is different: CPython evaluates the receiver and
        discards it, without reading the attribute or performing a store.

        The annotation itself is NEVER a fact the meaning layer states either
        way: Python does not check it at runtime (no TypeError on mismatch),
        so an annotation asserts nothing -- it is documentation the tree
        passes through, never a stated post. A valued attribute/subscript target
        is the same runtime store owned by Assign.  A bare Attribute therefore
        reuses the ordinary expression-statement path for its receiver only.
        Other bare non-Name annotations stay loud."""
        if isinstance(self.target, Name):
            from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

            return InertSugar(site=self.fragment)
        if self.value is None and isinstance(self.target, Attribute):
            from sugar_lift_py_tests.sugar.expr_statement_sugar import (
                ExprStatementSugar,
            )

            return ExprStatementSugar(
                value=self.target.value.sugar(),
                site=self.fragment,
            )
        if self.value is not None and isinstance(self.target, Attribute):
            from sugar_lift_py_tests.sugar.store_effect_sugar import (
                AttributeStoreEffectSugar,
            )

            return AttributeStoreEffectSugar(
                receiver=self.target.value.sugar(),
                value=self.value.sugar(),
                attr=self.target.attr,
                site=self.fragment,
            )
        if self.value is not None and isinstance(self.target, Subscript):
            from sugar_lift_py_tests.sugar.store_effect_sugar import (
                SubscriptStoreEffectSugar,
            )

            return SubscriptStoreEffectSugar(
                index_text=self.target.slice_.fragment.text,
                site=self.fragment,
            )
        return super()._construct_sugar()


class TypeAlias(Statement):
    name: Expression
    type_params: Tuple[TypeParam, ...]
    value: Expression
    _child_fields = ("name", "type_params", "value")

    def substitute(self, scope):
        """`type <name>[<params>] = <value>` -- the type params bind for the
        value; the name is a binding site."""
        from .shadow import rewrite

        tnames = {
            n
            for tp in self.type_params
            for n in [getattr(tp, "name", None)]
            if isinstance(n, str)
        }
        inner = {k: v for k, v in scope.items() if k not in tnames} if tnames else scope
        changed = {}
        new_tp, d = self._substitute_field(self.type_params, scope)
        if d:
            changed["type_params"] = new_tp
        new_val, d = self._substitute_field(self.value, inner)
        if d:
            changed["value"] = new_val
        return self if not changed else rewrite(self, **changed)


class For(Statement):
    target: Expression
    iter: Expression
    body: Tuple[Statement, ...]
    orelse: Tuple[Statement, ...]
    _child_fields = ("target", "iter", "body", "orelse")

    def substitute(self, scope):
        """`for <target> in <iter>: <body>` -- a loop is a FOLD, and over a
        CONCRETE iterable it DISSOLVES: the fold has known length, so it unrolls.
        The body is threaded once per element (the target rebound to that
        element, every loop-carried variable threaded forward exactly as a
        straight-line block threads its assignments -- `t = t + x` reads the
        previous iteration's t), and the unrolled statements are SPLICED into the
        enclosing block via ``_Splice``. The `for` node itself is gone; its
        carried accumulator is now just block-threading over the unrolled
        sequence, and there is no loop-sugar left to write.

        A SYMBOLIC iterable is the real fold (carried variables become fold terms,
        the body a universal `forall x in iter`); it is not lifted yet, so it
        keeps the `for` node (masking the target) and inherits the loud
        SugarNotWritten. `else` and a tuple target likewise stay loud."""
        from .shadow import rewrite

        new_iter, iter_changed = self._substitute_field(self.iter, scope)
        subst_iter = new_iter if iter_changed else self.iter

        # `else` is unrollable too: the jump-guard means no `break` exists, and
        # with no break the else ALWAYS runs -- it is just more block, spliced
        # after the unrolled iterations.
        concrete = self.target.kind in ("Name", "Tuple", "List")
        elements = self._concrete_elements(subst_iter) if concrete else None
        if elements is not None and len(elements) > self._UNROLL_FUEL:
            elements = None  # past the unroll budget: the fold/universal stands
        if elements is not None:
            bindings = [self._target_bindings(e) for e in elements]
            if all(b is not None for b in bindings):
                if self._body_has_owned_loop_control():
                    controlled = self._unroll_concrete_controlled(bindings, scope)
                    if controlled is not None:
                        statements, final_bindings = controlled
                        return _Splice(statements, final_bindings)
                    # A symbolic guard owns a jump.  It cannot be selected by
                    # concrete unrolling and must remain a real loop below.
                    elements = None
            if elements is not None and all(b is not None for b in bindings):
                target_names = self._bound_names_in(self.target)
                unrolled: list = []
                carried = dict(scope)  # carries loop variables across iterations
                final_target_bindings = None
                for element_bindings in bindings:
                    final_target_bindings = element_bindings
                    iter_scope = {**carried, **element_bindings}
                    new_body, _c = self._substitute_body(self.body, iter_scope)
                    unrolled.extend(new_body)
                    # thread this iteration's bindings forward (the carried
                    # fold), never the loop target's own names (rebound next
                    # iteration).
                    for stmt in new_body:
                        b = stmt.substitution_binding(iter_scope)
                        if b:
                            iter_scope = {**iter_scope, **b}
                    carried = {
                        k: v for k, v in iter_scope.items() if k not in target_names
                    }
                if self.orelse:
                    else_scope = (
                        {**carried, **final_target_bindings}
                        if final_target_bindings is not None
                        else carried
                    )
                    else_body, _c = self._substitute_body(self.orelse, else_scope)
                    unrolled.extend(else_body)
                return _Splice(tuple(unrolled), final_target_bindings)

        # Symbolic (or unsupported) loop: keep the node, mask the target AND every
        # loop-carried variable (a name the body rebinds), recurse. Masking the
        # carried names keeps the update SYMBOLIC in the body (`total = total + x`
        # stays, not `total = 0 + x`) so substitution_binding can read the fold;
        # the pre-loop value seeds it from the outer scope. A symbolic loop is not
        # a dead unroll -- it is the universal / fold over the hole.
        bound = self._bound_names_in(self.target) | For._stmts_bound_names(self.body)
        bs = {k: v for k, v in scope.items() if k not in bound} if bound else scope
        changed = {}
        if iter_changed:
            changed["iter"] = new_iter
        for f in ("body", "orelse"):
            new, d = self._substitute_body(getattr(self, f), bs)
            if d:
                changed[f] = new
        return self if not changed else rewrite(self, **changed)

    @staticmethod
    def _stmts_bound_names(statements) -> set:
        """The names any statement (at any depth) binds -- the structural twin
        of _stmts_bind, for the symbolic-loop carried-name mask."""
        names: set = set()
        for stmt in statements:
            for n in stmt.walk():
                if n.kind in ("Assign",):
                    for t in n.targets:
                        if t.kind == "Name":
                            names.add(t.id)
                elif n.kind in ("AugAssign", "AnnAssign", "NamedExpr"):
                    t = n.target
                    if t.kind == "Name":
                        names.add(t.id)
        return names

    @staticmethod
    def _stmts_bind(statements) -> bool:
        """True when any statement (at any depth) binds a name for a tail --
        Assign/AugAssign/AnnAssign or a walrus. STRUCTURAL, not a binding read:
        an If no longer reports its branch bindings (phis are spliced at
        substitute time), so classification walks the source shape instead of
        asking for bindings that are only materialized during substitution."""
        return any(
            n.kind in ("Assign", "AugAssign", "AnnAssign", "NamedExpr")
            for stmt in statements
            for n in stmt.walk()
        )

    def _carried_and_facts(self):
        """Split the body into carried assignments (statements that bind a name
        for the tail -- the fold's update) and fact statements (asserts, the rest
        -- the universal's body). A pure-fold loop is all carried; an assert-only
        loop is all facts; a loop with BOTH is the accumulator-referencing case
        (point 3), left loud."""
        carried, facts = [], []
        for stmt in self.body:
            (carried if For._stmts_bind((stmt,)) else facts).append(stmt)
        return carried, facts

    def substitution_binding(self, scope):
        """Never synthesize a symbolic loop post-value.

        The only lawful symbolic post-binding is projected from a decoded
        ``LoopConstructionV1`` by ``project_loop_post_binding`` after the loop
        has constructed its exact completed faces. Until block sequencing owns
        that projection, the source occurrence remains typed-loud and contributes
        no fabricated tail binding here.
        """
        del scope
        return None

    def _make_name(self, identifier: str) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode("Name", self.span, (("id", Leaf(identifier)),)),
            self.reporter,
        )

    def _make_call(self, func: "Node", args: tuple) -> "Node":
        from .backend import Child, Children, materialize
        from .shadow import ShadowNode, _handle_of

        slots = (
            ("func", Child(_handle_of(func))),
            ("args", Children(tuple(_handle_of(a) for a in args))),
            ("keywords", Children(())),
        )
        return materialize(
            self.unit, ShadowNode("Call", self.span, slots), self.reporter
        )

    def _construct_sugar(self):
        """A residual symbolic loop is typed-loud until its recurrence graph is
        sealed; it is never weakened to a universal or an inert pseudo-fold."""
        return super()._construct_sugar()

    def _body_has_loop_control(self) -> bool:
        """True when any `break`/`continue` appears anywhere in the body. The
        plain unroll repeats the body verbatim, which would duplicate the jump
        and silently mis-thread the carried state -- a break is the last hole
        being filled, and the unroll must not fake past it. Conservative on
        purpose (a nested loop's own jumps also block): over-blocking falls to
        the symbolic branch (loud), never to a wrong unroll."""
        return any(
            ("break" in stmt.segment() or "continue" in stmt.segment())
            and any(n.kind in ("Break", "Continue") for n in stmt.walk())
            for stmt in self.body
        )

    def _body_has_owned_loop_control(self) -> bool:
        target_cid = self.owned_loop_target.target_cid
        return any(
            node.kind in ("Break", "Continue")
            and node.control_context.nearest_loop_target().target_cid == target_cid
            for statement in self.body
            for node in statement.walk()
        )

    def _unroll_concrete_controlled(self, bindings, scope):
        """Exact AST-local execution of bounded jump-bearing loop structure.

        Only literal-decidable branch guards are selected.  A symbolic guard
        returns ``None`` so the source loop remains typed and loud/opaque.
        """
        unrolled = []
        carried = dict(scope)
        final_target_bindings = None
        broke = False
        for element_bindings in bindings:
            final_target_bindings = element_bindings
            iteration = {**carried, **element_bindings}
            reduced = self._substitute_controlled_suite(self.body, iteration)
            if reduced is None:
                return None
            statements, iteration, action = reduced
            unrolled.extend(statements)
            target_names = self._bound_names_in(self.target)
            carried = {
                key: value
                for key, value in iteration.items()
                if key not in target_names
            }
            if action == "break":
                broke = True
                break
            # continue and fallthrough both advance to the next concrete item;
            # the controlled suite already omitted the skipped tail.
        if not broke and self.orelse:
            else_scope = (
                {**carried, **final_target_bindings}
                if final_target_bindings is not None
                else carried
            )
            else_body, _changed = self._substitute_body(self.orelse, else_scope)
            unrolled.extend(else_body)
        return tuple(unrolled), final_target_bindings

    def _substitute_controlled_suite(self, statements, scope):
        produced = []
        current = dict(scope)
        for statement in statements:
            if (
                statement.kind == "Try"
                and not statement.handlers
                and not statement.orelse
                and statement.finalbody
                and len(statement.body) == 1
                and statement.body[0].kind in ("Break", "Continue")
                and statement.body[0].control_context.nearest_loop_target().target_cid
                == self.owned_loop_target.target_cid
            ):
                # A concrete loop dissolves before construction, so consume its
                # owned jump here only after routing the mandatory cleanup.  The
                # jump has no value to evaluate; ``finally`` therefore precedes
                # the selected loop edge.  A cleanup halt/return remains in the
                # produced block and supersedes that edge through ordinary
                # ExitSet reduction.  Wider Try shapes retain their live
                # TrySugar router below rather than being linearized here.
                incoming_action = statement.body[0].kind.lower()
                cleanup = For._substitute_controlled_suite(
                    self, statement.finalbody, current
                )
                if cleanup is None:
                    return None
                cleanup_statements, current, cleanup_action = cleanup
                produced.extend(cleanup_statements)
                return produced, current, cleanup_action or incoming_action
            if statement.kind == "Break":
                return produced, current, "break"
            if statement.kind == "Continue":
                return produced, current, "continue"
            if statement.kind == "If" and any(
                node.kind in ("Break", "Continue")
                and node.control_context.nearest_loop_target().target_cid
                == self.owned_loop_target.target_cid
                for node in statement.walk()
            ):
                test, _changed = statement._substitute_field(statement.test, current)
                verdict = While._ground_truth(self, test)
                if verdict is None:
                    return None
                branch = statement.body if verdict else statement.orelse
                nested = For._substitute_controlled_suite(self, branch, current)
                if nested is None:
                    return None
                branch_statements, current, action = nested
                produced.extend(branch_statements)
                if action is not None:
                    return produced, current, action
                continue
            substituted = statement.substitute(current)
            expanded = (
                substituted.statements
                if isinstance(substituted, _Splice)
                else (substituted,)
            )
            produced.extend(expanded)
            for item in expanded:
                binding = item.substitution_binding(current)
                if binding:
                    binding = item._binding_entries(binding, current)
                    current = {**current, **binding}
            if isinstance(substituted, _Splice) and substituted.bindings:
                projected = statement._binding_entries(substituted.bindings, current)
                current = {**current, **projected}
        return produced, current, None

    # The unroll budget. A concrete loop within it dissolves to its unroll; past
    # it, the SYMBOLIC form (universal / fold coordinate) stands -- not merely
    # cheaper: 1,100 iterations of a carried update is a fold, and unrolling it
    # grows a term chain quadratically. Small on purpose; proofs want small
    # unrolls.
    _UNROLL_FUEL = 128

    def _target_bindings_for(self, target: "Node", element: "Node") -> "Optional[dict]":
        """`_target_bindings` for an explicit target (shared with comprehensions)."""
        if target.kind == "Name":
            return {target.id: element}
        names = []
        for t in target.elts:
            if t.kind != "Name":
                return None
            names.append(t.id)
        if element.kind not in ("Tuple", "List") or len(element.elts) != len(names):
            return None
        return dict(zip(names, element.elts))

    def _target_bindings(self, element: "Node") -> "Optional[dict]":
        """What this loop's target binds when the element is `element`, or None
        when the shapes do not destructure. A Name target binds it whole; a
        tuple/list target of plain Names destructures a tuple/list DISPLAY
        element of the same arity (`for a, b in [(1, 2)]` binds a=1, b=2). A
        nested or starred target, or an element that is not a matching display,
        is not destructured here -- the loop falls to the symbolic branch."""
        return For._target_bindings_for(self, self.target, element)

    def _concrete_elements(self, iterable: "Expression") -> "Optional[list]":
        """The element nodes to unroll over, or ``None`` if `iterable` is not
        concrete. A `List`/`Tuple_` literal is concrete by construction; a
        `range(...)` call is concrete only when every argument (after
        substitution) is a literal `int` -- a symbolic bound leaves the fold
        real, so it is not recognized here."""
        if iterable.kind in ("List", "Tuple"):
            return list(iterable.elts)
        if (
            iterable.kind == "Call"
            and iterable.func.kind == "Name"
            and iterable.func.id == "range"
            and not iterable.keywords
        ):
            ints = []
            for arg in iterable.args:
                v = For._concrete_int(self, arg)
                if v is None:
                    return None
                ints.append(v)
            return [For._int_constant(self, i) for i in range(*ints)]
        return None

    def _concrete_int(self, arg: "Expression") -> "Optional[int]":
        """The literal int an arg denotes, or ``None`` if it is not one. A
        negative bound parses as `UnaryOp(USub, Constant(n))` (cpython does
        not fold the literal), so both shapes are recognized; `bool` is
        rejected even though it subclasses `int`."""
        if (
            arg.kind == "Constant"
            and isinstance(arg.value, int)
            and not isinstance(arg.value, bool)
        ):
            return arg.value
        if arg.kind == "UnaryOp" and arg.op.kind == "USub":
            inner = For._concrete_int(self, arg.operand)
            return -inner if inner is not None else None
        if arg.kind == "BinOp":
            # A ground arithmetic composition denotes its int as surely as a
            # negative literal does: `0 + 1` reads 1. Structural reading of what
            # the literals compose to (int-closed operators only), never an
            # evaluation of anything symbolic -- a non-ground side reads None.
            left = For._concrete_int(self, arg.left)
            right = For._concrete_int(self, arg.right)
            if left is None or right is None:
                return None
            op = arg.op.kind
            if op == "FloorDiv" and right == 0:
                return None  # a ground ZeroDivisionError is an effect, not an int
            if op == "Mod" and right == 0:
                return None
            return {
                "Add": lambda: left + right,
                "Sub": lambda: left - right,
                "Mult": lambda: left * right,
                "FloorDiv": lambda: left // right,
                "Mod": lambda: left % right,
            }.get(op, lambda: None)()
        return None

    def _int_constant(self, value: int) -> "Node":
        """Synthesize an int `Constant` node bound to `value`, borrowing this
        `for`'s span -- the unroll rebinds the loop target to a real node, and
        `range`'s elements have no source site of their own to borrow."""
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (
            ("value", Leaf(value)),
            ("literal_kind", Leaf(None)),
        )
        return materialize(
            self.unit, ShadowNode("Constant", self.span, slots), self.reporter
        )


class AsyncFor(Statement):
    target: Expression
    iter: Expression
    body: Tuple[Statement, ...]
    orelse: Tuple[Statement, ...]
    _child_fields = ("target", "iter", "body", "orelse")

    def substitute(self, scope):
        """Same as For: masks the loop target for body/orelse."""
        return For.substitute(self, scope)


class While(Statement):
    test: Expression
    body: Tuple[Statement, ...]
    orelse: Tuple[Statement, ...]
    _child_fields = ("test", "body", "orelse")

    # The unroll bound. A CONCRETE while whose state never satisfies exit within
    # this many iterations is treated as not-concrete (falls to the symbolic
    # branch, which is loud) -- `while True:` lands there honestly rather than
    # spinning substitute forever. Not a semantic limit: a real concrete loop
    # that long is beyond what an unroll should dissolve anyway.
    _FUEL = 128  # the shared unroll budget (see For._UNROLL_FUEL)

    def substitute(self, scope):
        """`while <test>: <body>` -- the unbounded loop, and over CONCRETE state
        it DISSOLVES exactly like a concrete `for`: each iteration is one more
        substitution. The condition, substituted against the carried state, is
        ground-decidable (constants only); while it decides True the body is
        threaded once more (its bindings carried forward), and the unrolled
        statements are SPLICED into the enclosing block. `i = 0; while i < 3:
        i = i + 1` unrolls to three rebinds of i; `return i` reads 3.

        A condition that is NOT ground-decidable against the carried state (a
        formal in the state, an effect) keeps the node -- the symbolic while is
        the recurrence-with-exit-condition, an unwritten segment that stays
        loud. `while True:` exhausts the fuel and lands there too: an infinite
        concrete loop is a non-termination the unroll must not fake."""
        from .shadow import rewrite

        unrolled = self._try_unroll(scope)
        if unrolled is not None:
            return _Splice(unrolled)

        # Symbolic (or unsupported) while: keep the node; mask the carried
        # names (any name the body rebinds) so the update stays symbolic.
        bound = For._stmts_bound_names(self.body)
        bs = {k: v for k, v in scope.items() if k not in bound} if bound else scope
        changed = {}
        new_test, d = self._substitute_field(self.test, bs)
        if d:
            changed["test"] = new_test
        for f in ("body", "orelse"):
            new, d = self._substitute_body(getattr(self, f), bs)
            if d:
                changed[f] = new
        return self if not changed else rewrite(self, **changed)

    def _try_unroll(self, scope):
        """The unrolled statement tuple, or None if the loop is not concrete
        (condition undecidable against the carried state, or fuel exhausted)."""
        controlled = For._body_has_owned_loop_control(self)
        carried = dict(scope)
        unrolled: list = []
        for _ in range(self._FUEL):
            test, _d = self._substitute_field(self.test, carried)
            verdict = self._ground_truth(test)
            if verdict is None:
                return None  # not decidable -- not a concrete loop
            if verdict is False:
                # Exit via the condition: with no break (jump-guard), the
                # `else` always runs -- spliced after the iterations.
                if self.orelse:
                    else_body, _c = self._substitute_body(self.orelse, carried)
                    unrolled.extend(else_body)
                return tuple(unrolled)
            if controlled:
                reduced = For._substitute_controlled_suite(self, self.body, carried)
                if reduced is None:
                    return None
                new_body, carried, action = reduced
                unrolled.extend(new_body)
                if action == "break":
                    return tuple(unrolled)
                continue
            new_body, _c = self._substitute_body(self.body, carried)
            unrolled.extend(new_body)
            for stmt in new_body:
                b = stmt.substitution_binding(carried)
                if b:
                    carried = {**carried, **b}
        return None  # fuel exhausted: an infinite/huge loop is not an unroll

    def _ground_truth(self, test):
        """Decide a GROUND condition structurally, or None. Constants only --
        this is the same structural reading as For._concrete_int (recognizing
        literals), never an evaluation of symbolic meaning: a bool Constant
        stands as itself; a single-op Compare over int literals decides by the
        operator. Anything else (a free name, a call) is not ground."""
        if test.kind == "Constant" and isinstance(test.value, bool):
            return test.value
        if test.kind == "Compare" and len(test.ops) == 1:
            left = For._concrete_int(self, test.left)
            right = For._concrete_int(self, test.comparators[0])
            if left is None or right is None:
                return None
            op = test.ops[0].kind
            return {
                "Lt": left < right,
                "LtE": left <= right,
                "Gt": left > right,
                "GtE": left >= right,
                "Eq": left == right,
                "NotEq": left != right,
            }.get(op)
        return None


class If(Statement):
    test: Expression
    body: Tuple[Statement, ...]
    orelse: Tuple[Statement, ...]
    _child_fields = ("test", "body", "orelse")

    def substitute(self, scope):
        """An if introduces no names into its own scope; each branch is a
        sub-block that threads its OWN assignments. The branch-carried bindings
        become the PHI, emitted HERE, ONCE, as explicit spliced SSA assignments
        after the if: `x = <then> if <test> else <else>`. Resolve at
        construction -- the reads downstream are O(1) Assign bindings, never a
        re-walk of the branches (the re-read was 2^nesting on real code)."""
        from .shadow import rewrite

        changed = {}
        new_test, d = self._substitute_field(self.test, scope)
        if d:
            changed["test"] = new_test
        slot = branch_result_slot(self.test)
        new_body, d, then_net = self._substitute_body_tracked(self.body, scope)
        if d:
            changed["body"] = new_body
        new_orelse, d, else_net = self._substitute_body_tracked(self.orelse, scope)
        if d:
            changed["orelse"] = new_orelse
        node = self._rewrite_with_slot(changed, slot)

        names = set(then_net) | set(else_net)
        phis = []
        availability: BindingMap = {}
        for name in sorted(names):
            incoming = _explicit_state(name, scope)
            then_val = then_net.get(name, incoming)
            else_val = else_net.get(name, incoming)
            if then_val is _MISSING or else_val is _MISSING:
                continue
            joined = join_binding_state(
                slot=slot,
                when_true=then_val,
                when_false=else_val,
                make_ifexp=self._make_ifexp,
            )
            if isinstance(joined, Node):
                phis.append(self._make_assign(name, joined))
            else:
                availability[name] = joined
        if not phis and not availability:
            return node
        return _Splice((node, *phis), availability)

    def _rewrite_with_slot(self, changed, slot):
        from .backend import Leaf, materialize
        from .shadow import ShadowNode, rewrite

        rewritten = rewrite(self, **changed)
        desc = rewritten.ref.describe()
        return materialize(
            self.unit,
            ShadowNode(
                desc.kind,
                desc.raw_span or self.span,
                (*desc.slots, ("branch_result_slot_id", Leaf(slot.slot_id))),
            ),
            self.reporter,
        )

    def _make_assign(self, name: str, value: "Node") -> "Node":
        """Synthesize `name = <value>` -- the phi as an explicit SSA assignment,
        borrowing this if's span."""
        from .backend import Child, Children, materialize
        from .shadow import ShadowNode, _handle_of

        target = For._make_name(self, name)
        slots = (
            ("targets", Children((_handle_of(target),))),
            ("value", Child(_handle_of(value))),
        )
        return materialize(
            self.unit, ShadowNode("Assign", self.span, slots), self.reporter
        )

    def _make_ifexp(
        self, slot: BranchResultSlot, body: "Node", orelse: "Node"
    ) -> "Node":
        """Synthesize ``<body> if <test> else <orelse>`` as a shadow IfExp that
        borrows this if's span (so the phi still addresses this source site)."""
        from .backend import Child, materialize
        from .shadow import ShadowNode, _handle_of

        test = self._make_branch_result_ref(slot)
        slots = (
            ("body", Child(_handle_of(body))),
            ("test", Child(_handle_of(test))),
            ("orelse", Child(_handle_of(orelse))),
        )
        return materialize(
            self.unit, ShadowNode("IfExp", self.span, slots), self.reporter
        )

    def _make_branch_result_ref(self, slot: BranchResultSlot) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "BranchResultRef", self.span, (("slot_id", Leaf(slot.slot_id)),)
            ),
            self.reporter,
        )

    def _construct_sugar(self):
        """`if <test>: <body> [else: <orelse>]` constructs IfSugar -- the guard.
        The test recognizes itself; each branch's statements recognize themselves.
        The guard turns each branch's stated facts into implications; the binding
        phi is substitute's job, never this."""
        from sugar_lift_py_tests.sugar.if_sugar import IfSugar

        try:
            slot = BranchResultSlot(self.branch_result_slot_id)
        except AttributeError:
            backend_defect(
                owner="If._construct_sugar",
                observed="If without a stored branch-result slot",
                requested="consume the slot minted once by If.substitute",
                fix="route every If through substitution before Sugar construction",
            )
        return IfSugar(
            test=self.test.sugar(),
            branch_slot=slot,
            then_body=tuple(s.sugar() for s in self.body),
            else_body=tuple(s.sugar() for s in self.orelse),
            site=self.fragment,
        )


class With(Statement):
    items: Tuple[WithItem, ...]
    body: Tuple[Statement, ...]
    _child_fields = ("items", "body")

    def _prebound_manager_resolution(self, item: WithItem):
        """Read the sole preconstruction contract resolution for this occurrence."""
        context = self.unit.construction_context
        if context is None:
            return None
        from sugar_lift_py_tests.context_manager_resolution import (
            ContractRefProtocolError,
            SourceFragmentCoordinateV1,
            TreeConstructionContextV1,
        )

        if not isinstance(context, TreeConstructionContextV1):
            backend_defect(
                owner="With._construct_sugar",
                observed="tree construction context is not TreeConstructionContextV1",
                requested="the immutable prereq-2 contract-ref table",
                fix="inject the decoded typed table before SourceFile construction",
            )
        start_line, start_col, end_line, end_col = item._manager_use_site_span()
        coordinate = SourceFragmentCoordinateV1(
            self.unit.source_cid,
            start_line,
            start_col,
            end_line,
            end_col,
        )
        derived = context.source_derived_contract_refs.get(coordinate)
        if derived is not None:
            return derived
        try:
            return context.contract_refs.require(coordinate)
        except ContractRefProtocolError as exc:
            backend_defect(
                owner="With._construct_sugar",
                observed=str(exc),
                requested="one contract-resolution row for every enrolled With demand",
                fix="repair prereq-2 demand/table generation; never search at construction",
            )

    def _raise_resolution_gap(self, resolution) -> None:
        from .panic import ContextManagerResolutionConstructionGap

        panic = ContextManagerResolutionConstructionGap(
            kind=resolution.kind,
            demand_cid=resolution.demand_cid,
            candidate_member_cids=resolution.candidate_member_cids,
            owner="With._construct_sugar",
            observed=f"authenticated preconstruction resolution gap: {resolution.kind}",
            requested="one resolved authenticated ContextManagerContractRefV1",
            fix="publish or resolve the exact typed CM contract before construction",
        )
        self.reporter.report_gap(self, panic)
        raise panic

    def _require_narrow_cm_ref(self, item: WithItem):
        resolution = self._prebound_manager_resolution(item)
        if resolution is None:
            return None
        from sugar_lift_py_tests.context_manager_contract import (
            EffectBoundarySemanticsV1,
            ExpectsModeV1,
            SuppressesModeV1,
            RaiseEffectKindV1,
            NeverSuppressesDispositionV1,
            ProtocolResourceSemanticsV1,
            TotalCompletionV1,
        )
        from sugar_lift_py_tests.context_manager_resolution import (
            ContextManagerContractRefV1,
            ContextManagerResolutionGapV1,
            SourceDerivedContextManagerRefV1,
        )
        from sugar_lift_py_tests.ir import PrimitiveSort
        from .panic import UnsupportedContextManagerSemantics

        if isinstance(resolution, ContextManagerResolutionGapV1):
            self._raise_resolution_gap(resolution)
        if not isinstance(
            resolution, (ContextManagerContractRefV1, SourceDerivedContextManagerRefV1)
        ):
            backend_defect(
                owner="With._construct_sugar",
                observed=f"unexpected resolution value {type(resolution).__name__}",
                requested="ContextManagerContractRefV1 or ContextManagerResolutionGapV1",
                fix="keep the injected table closed and typed",
            )
        semantics = resolution.semantics
        admitted_resource = (
            isinstance(semantics, ProtocolResourceSemanticsV1)
            and semantics.schema_version == "1"
            and isinstance(semantics.enter.completion, TotalCompletionV1)
            and semantics.enter.projection == "enter-result"
            and isinstance(semantics.enter.sort, PrimitiveSort)
            and semantics.enter.sort.name == "Value"
            and isinstance(semantics.exit.completion, TotalCompletionV1)
            and isinstance(semantics.exit.disposition, NeverSuppressesDispositionV1)
        )
        admitted_boundary = (
            isinstance(semantics, EffectBoundarySemanticsV1)
            and semantics.schema_version == "1"
            and isinstance(semantics.mode, (ExpectsModeV1, SuppressesModeV1))
            and isinstance(semantics.effect_kind, RaiseEffectKindV1)
        )
        if not (admitted_resource or admitted_boundary):
            panic = UnsupportedContextManagerSemantics(
                demand_cid=resolution.demand_cid,
                member_cid=resolution.contract_cid,
                owner="With._construct_sugar",
                observed=(
                    "authenticated CM member carries unsupported enter/exit semantics "
                    f"at {resolution.contract_cid}"
                ),
                requested="total Value/NeverSuppresses resource or typed Expects/Raise boundary",
                fix="leave unsupported authenticated semantics loud; never upgrade testimony",
            )
            self.reporter.report_gap(self, panic)
            raise panic
        return resolution

    def _construct_sugar(self):
        """Build only from the pre-resolved authenticated CM contract ref.

        There is no consumer/vendor membrane fallback. Missing provider
        publication or resolution remains a typed construction gap. The narrow
        resource arm admits one synchronous manager and an optional simple-name
        binding to its real enter-result projection."""
        if len(self.items) != 1:
            from .panic import MultipleContextManagerItems

            panic = MultipleContextManagerItems(
                owner="With._construct_sugar",
                observed=f"synchronous With contains {len(self.items)} manager items",
                requested="exactly one pre-resolved synchronous manager item",
                fix="keep multi-item context-manager composition loud",
            )
            self.reporter.report_gap(self, panic)
            raise panic
        item = self.items[0]
        as_name = None
        if item.optional_vars is not None:
            # ``as <Name>`` only: substitute already rewrote loads to
            # ObservationRef(slot). Non-Name targets stay loud.
            if item.optional_vars.kind != "Name":
                from .panic import UnsupportedWithBindingTarget

                panic = UnsupportedWithBindingTarget(
                    owner="With._construct_sugar",
                    observed=f"unsupported with binding target {item.optional_vars.kind}",
                    requested="no target or one simple Name target",
                    fix="leave destructuring and attribute targets loud",
                )
                self.reporter.report_gap(self, panic)
                raise panic
            as_name = item.optional_vars.id

        resolved_ref = self._require_narrow_cm_ref(item)
        if resolved_ref is not None:
            from sugar_lift_py_tests.context_manager_contract import (
                EffectBoundarySemanticsV1,
                ProtocolResourceSemanticsV1,
            )
            from sugar_lift_py_tests.kit_rpc import ContextManagerEdgeDtoV1
            from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar

            from sugar_lift_py_tests.context_manager_resolution import (
                SourceDerivedContextManagerRefV1,
            )

            if isinstance(
                resolved_ref, SourceDerivedContextManagerRefV1
            ) and isinstance(resolved_ref.semantics, ProtocolResourceSemanticsV1):
                from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
                    WithSourceResourceSugar,
                )

                manager_slot = item._manager_slot_id()
                enter_slot = (
                    f"{manager_slot}#enter_result" if as_name is not None else None
                )
                return WithSourceResourceSugar(
                    manager=item.context_expr.sugar(),
                    protocol=resolved_ref.protocol,
                    summary=resolved_ref,
                    body=tuple(stmt.sugar() for stmt in self.body),
                    manager_slot_id=manager_slot,
                    enter_slot_id=enter_slot,
                    exit_face_id=item._exit_face_id(),
                    site=self.fragment,
                )

            if isinstance(resolved_ref.semantics, EffectBoundarySemanticsV1):
                from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
                    WithEffectBoundarySugar,
                )

                if as_name is not None:
                    from .panic import UnsupportedWithBindingTarget

                    panic = UnsupportedWithBindingTarget(
                        owner="With._construct_sugar",
                        observed="EffectBoundary as-binding projection is not yet authenticated",
                        requested="an EffectBoundary manager without optional_vars",
                        fix="keep exception-info/warning observation binding loud until its projection slot is authenticated",
                    )
                    self.reporter.report_gap(self, panic)
                    raise panic
                manager_sugar = item.context_expr.sugar()
                manager_sugar = self._authenticate_expected_exception_type(
                    item.context_expr, manager_sugar, resolved_ref
                )
                return WithEffectBoundarySugar(
                    manager=manager_sugar,
                    body=tuple(stmt.sugar() for stmt in self.body),
                    semantics=resolved_ref.semantics,
                    contract_ref=resolved_ref,
                    context_manager_edge=(
                        None
                        if isinstance(resolved_ref, SourceDerivedContextManagerRefV1)
                        else ContextManagerEdgeDtoV1.from_resolved(
                            resolved_ref, resolved_ref.use_site
                        )
                    ),
                    site=self.fragment,
                )

            if not isinstance(resolved_ref.semantics, ProtocolResourceSemanticsV1):
                backend_defect(
                    owner="With._construct_sugar",
                    observed="closed CM resolver returned an unknown semantics variant",
                    requested="ProtocolResourceSemanticsV1 or EffectBoundarySemanticsV1",
                    fix="keep the semantics union exhaustive",
                )

            manager_slot = item._manager_slot_id()
            enter_slot = f"{manager_slot}#enter_result" if as_name is not None else None
            return WithResourceSugar(
                manager=item.context_expr.sugar(),
                manager_slot_id=manager_slot,
                enter=item._make_enter_call().sugar(),
                exit=item._make_parametric_exit_call().sugar(),
                exit_face_id=item._exit_face_id(),
                body=tuple(stmt.sugar() for stmt in self.body),
                disposition=resolved_ref.semantics.exit.disposition,
                contract_ref=resolved_ref,
                context_manager_edge=ContextManagerEdgeDtoV1.from_resolved(
                    resolved_ref, resolved_ref.use_site
                ),
                enter_slot_id=enter_slot,
                site=self.fragment,
            )
        panic = RuntimeSelectedContextManager(
            owner="With.sugar",
            observed="With manager has no injected authenticated preconstruction authority",
            requested="one resolved ContextManagerContractRefV1 at the exact use-site",
            fix="run authenticated contract resolution before tree construction",
        )
        self.reporter.report_gap(self, panic)
        raise panic

    def _authenticate_expected_exception_type(self, manager, manager_sugar, reference):
        """Attach the floor-owned identity to the selected real call operand."""
        from dataclasses import replace

        from sugar_lift_py_tests.context_manager_contract import (
            FormalArgumentProjectionV1,
            KeywordOnlyV1,
            PositionalOnlyV1,
            PositionalOrKeywordV1,
        )
        from sugar_lift_py_tests.sugar.authenticated_exception_type_sugar import (
            AuthenticatedExceptionTypeSugar,
        )
        from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
        from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar

        selector = reference.semantics.expected_type_operand
        if not isinstance(selector, FormalArgumentProjectionV1):
            return manager_sugar
        if not isinstance(manager, Call) or not isinstance(
            manager_sugar, (CallSiteSugar, MethodCallSugar)
        ):
            return manager_sugar
        positional = list(enumerate(manager.args))
        keywords = {
            keyword.arg: keyword.value for keyword in manager.keywords if keyword.arg
        }
        actual = None
        actual_location = None
        for index, parameter in enumerate(reference.import_signature.parameters):
            if positional and isinstance(
                parameter.passing, (PositionalOnlyV1, PositionalOrKeywordV1)
            ):
                position, value = positional.pop(0)
                location = ("arg", position)
            elif parameter.name in keywords and isinstance(
                parameter.passing, (PositionalOrKeywordV1, KeywordOnlyV1)
            ):
                value = keywords[parameter.name]
                location = ("keyword", parameter.name)
            else:
                continue
            if index == selector.parameter_index:
                actual, actual_location = value, location
                break
        if not isinstance(actual, Name):
            return manager_sugar
        identity = self.unit.exception_type_identity(actual)
        if identity is None:
            return manager_sugar
        if actual_location[0] == "arg":
            args = list(manager_sugar.args)
            position = actual_location[1]
            args[position] = AuthenticatedExceptionTypeSugar(
                args[position], identity, site=actual.fragment
            )
            return replace(manager_sugar, args=tuple(args))
        keywords_sugar = list(manager_sugar.keywords)
        for position, (name, sugar) in enumerate(keywords_sugar):
            if name == actual_location[1]:
                keywords_sugar[position] = (
                    name,
                    AuthenticatedExceptionTypeSugar(
                        sugar, identity, site=actual.fragment
                    ),
                )
                break
        return replace(manager_sugar, keywords=tuple(keywords_sugar))

    def substitute(self, scope):
        """Rewrite a simple as-name to the resolved resource enter projection."""
        from .shadow import rewrite
        from sugar_lift_py_tests.context_manager_contract import (
            ENTER_RESULT,
        )

        changed = {}
        new_items, d = self._substitute_field(self.items, scope)
        if d:
            changed["items"] = new_items
        items = new_items if d else self.items

        body_scope = dict(scope)
        if self.unit.construction_context is not None:
            if len(items) != 1:
                return self if not changed else rewrite(self, **changed)
            item = items[0]
            if item.optional_vars is not None and item.optional_vars.kind == "Name":
                self._require_narrow_cm_ref(item)
                enter_slot = f"{item._manager_slot_id()}#enter_result"
                body_scope[item.optional_vars.id] = item._make_observation_ref(
                    enter_slot, ENTER_RESULT
                )
            new_body, d = self._substitute_body(self.body, body_scope)
            if d:
                changed["body"] = new_body
            return self if not changed else rewrite(self, **changed)
        for item in items:
            if item.optional_vars is not None:
                for name in self._bound_names_in(item.optional_vars):
                    body_scope.pop(name, None)

        new_body, d = self._substitute_body(self.body, body_scope)
        if d:
            changed["body"] = new_body
        return self if not changed else rewrite(self, **changed)

    def substitution_binding(self, scope):
        """Export ObservationRef for resolved resource enter-result as-names."""
        from sugar_lift_py_tests.context_manager_contract import (
            ENTER_RESULT,
        )

        del scope
        if self.unit.construction_context is not None:
            if len(self.items) != 1:
                return None
            item = self.items[0]
            if item.optional_vars is None or item.optional_vars.kind != "Name":
                return None
            self._require_narrow_cm_ref(item)
            enter_slot = f"{item._manager_slot_id()}#enter_result"
            return {
                item.optional_vars.id: item._make_observation_ref(
                    enter_slot, ENTER_RESULT
                )
            }
        return None


class AsyncWith(Statement):
    items: Tuple[WithItem, ...]
    body: Tuple[Statement, ...]
    _child_fields = ("items", "body")

    def substitute(self, scope):
        """Async context management stays loud before child construction."""
        del scope
        return self._raise_async_gap()

    def _raise_async_gap(self):
        from .panic import AsyncContextManagerUnsupported

        panic = AsyncContextManagerUnsupported(
            owner="AsyncWith._construct_sugar",
            observed="async context manager is outside the narrow synchronous arm",
            requested="one synchronous pre-resolved NeverSuppresses manager",
            fix="keep async enter/exit semantics loud until separately specified",
        )
        self.reporter.report_gap(self, panic)
        raise panic

    def _construct_sugar(self):
        return self._raise_async_gap()


class Raise(Statement):
    exc: Optional[Expression]
    cause: Optional[Expression]
    _child_fields = ("exc", "cause")

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _exception_name(self):
        """The raised exception's name, read structurally off ``exc`` (never
        desugared): ``raise E`` -> ``"E"``, ``raise E(...)`` -> ``"E"``,
        ``raise mod.E`` / ``raise mod.E(...)`` -> ``"mod.E"``. A bare ``raise``
        (re-raise, ``exc is None``) or an exotic raised expression we cannot read
        is ``None`` -- the halt is no less real, the name is only its label."""
        node = self.exc
        if node is None:
            return None
        if node.kind == "Call":  # raise E(...) -- the constructor
            node = node.func
        parts = []
        while node is not None and node.kind == "Attribute":  # mod.sub.E
            parts.append(node.attr)
            node = node.value
        if node is not None and node.kind == "Name":
            parts.append(node.id)
        if not parts:
            return None
        return ".".join(reversed(parts))

    def _construct_sugar(self):
        """Build exception and explicit cause children for the halt effect."""
        if self.exc is None:
            from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar

            return RaiseSugar(
                exception=None,
                cause=None,
                exception_name=None,
                site=self.fragment,
                in_flight_slot=self.control_context.nearest_exception_slot(),
            )
        from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar
        from dataclasses import replace

        from sugar_lift_py_tests.sugar.authenticated_exception_type_sugar import (
            AuthenticatedExceptionTypeSugar,
        )
        from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar

        identity = None
        mro = None
        if isinstance(self.exc, Call) and isinstance(self.exc.func, Name):
            identity = self.unit.exception_type_identity(self.exc.func)
            mro = self.unit.exception_type_mro(self.exc.func)
        elif isinstance(self.exc, Name):
            identity = self.unit.exception_type_identity(self.exc)
            mro = self.unit.exception_type_mro(self.exc)

        exception_sugar = self.exc.sugar()
        if identity is not None and isinstance(exception_sugar, CallSiteSugar):
            exception_sugar = replace(
                exception_sugar,
                exception_type_coordinate=identity,
                exception_type_mro=mro,
            )
        elif identity is not None:
            exception_sugar = AuthenticatedExceptionTypeSugar(
                exception_sugar, identity, mro, self.exc.fragment
            )

        return RaiseSugar(
            exception=exception_sugar,
            cause=self.cause.sugar() if self.cause is not None else None,
            exception_name=self._exception_name(),
            site=self.fragment,
        )


class Try(Statement):
    body: Tuple[Statement, ...]
    handlers: Tuple[ExceptHandler, ...]
    orelse: Tuple[Statement, ...]
    finalbody: Tuple[Statement, ...]
    _child_fields = ("body", "handlers", "orelse", "finalbody")

    def substitute(self, scope):
        """Rewrite each routed completion edge and export its binding state."""
        from .shadow import rewrite

        if type(self) is not Try:
            changed = {}
            new_handlers, d = self._substitute_field(self.handlers, scope)
            if d:
                changed["handlers"] = new_handlers
            for field_name in ("body", "orelse", "finalbody"):
                new_value, d = self._substitute_body(getattr(self, field_name), scope)
                if d:
                    changed[field_name] = new_value
            return self if not changed else rewrite(self, **changed)

        changed = {}
        new_body, d, body_net = self._substitute_body_tracked(self.body, scope)
        if d:
            changed["body"] = new_body
        body_state = {**scope, **body_net}
        new_orelse, d, else_net = self._substitute_body_tracked(self.orelse, body_state)
        if d:
            changed["orelse"] = new_orelse
        body_completion = {**body_net, **else_net}

        handler_nets = []
        new_handlers = []
        for handler in self.handlers:
            handler_changed = {}
            new_type, type_changed = handler._substitute_field(handler.type_, scope)
            if type_changed:
                handler_changed["type_"] = new_type
            handler_scope = dict(scope)
            if handler.name:
                handler_scope[handler.name] = handler._make_effect_ref(
                    handler._effect_slot_id()
                )
            new_handler_body, body_changed, handler_net = (
                handler._substitute_body_tracked(handler.body, handler_scope)
            )
            if body_changed:
                handler_changed["body"] = new_handler_body
            rewritten = (
                handler if not handler_changed else rewrite(handler, **handler_changed)
            )
            new_handlers.append(rewritten)
            if handler.name:
                handler_net = {
                    **handler_net,
                    handler.name: UnboundBinding(
                        name=handler.name, cause=handler.fragment
                    ),
                }
            handler_nets.append(handler_net)
        if any(new is not old for new, old in zip(new_handlers, self.handlers)):
            changed["handlers"] = tuple(new_handlers)

        unconditional = self._unconditional_raise_testimony(self.body)
        conditional = self._conditional_raise(self.body)
        completion_nets = []
        if unconditional is None:
            completion_nets.append(body_completion)
        for handler, handler_net in zip(self.handlers, handler_nets):
            if unconditional is not None:
                include = self._handler_matches(handler, *unconditional)
            elif conditional is not None:
                include = self._handler_matches(
                    handler,
                    conditional.exception_identity,
                    conditional.exception_mro,
                )
            else:
                include = True
            if include:
                completion_nets.append(handler_net)

        merged = self._merge_completion_nets(
            scope,
            completion_nets,
            conditional_route=conditional,
        )
        final_scope = {**scope, **merged}
        new_finalbody, d, final_net = self._substitute_body_tracked(
            self.finalbody, final_scope
        )
        if d:
            changed["finalbody"] = new_finalbody
        merged = {**merged, **final_net}

        node = self if not changed else rewrite(self, **changed)
        return _Splice((node,), merged) if merged else node

    def _handler_matches(self, handler, exception_identity, exception_mro) -> bool:
        if handler.type_ is None:
            return True
        if exception_identity is None:
            return True
        nodes = (
            handler.type_.elts
            if isinstance(handler.type_, Tuple_)
            else (handler.type_,)
        )
        for node in nodes:
            if not isinstance(node, Name):
                continue
            handler_identity = self.unit.exception_type_identity(node)
            if handler_identity == exception_identity or (
                exception_mro is not None and handler_identity in exception_mro
            ):
                return True
        return False

    def _unconditional_raise_testimony(self, statements):
        for statement in statements:
            if isinstance(statement, Raise):
                node = statement.exc
                if isinstance(node, Call):
                    node = node.func
                if not isinstance(node, Name):
                    return (None, None)
                return (
                    self.unit.exception_type_identity(node),
                    self.unit.exception_type_mro(node),
                )
            if isinstance(statement, Return):
                return None
            if isinstance(statement, If):
                left = self._unconditional_raise_testimony(statement.body)
                right = self._unconditional_raise_testimony(statement.orelse)
                if left is not None and left == right:
                    return left
            # The first ordinary statement can complete, so continue scanning.
        return None

    def _conditional_raise(self, statements):
        for statement in statements:
            if not isinstance(statement, If):
                continue
            left = self._unconditional_raise_testimony(statement.body)
            right = self._unconditional_raise_testimony(statement.orelse)
            if left is not None and right is None:
                return _ConditionalRaiseRoute(
                    slot=branch_result_slot(statement.test),
                    raised_on_true=True,
                    exception_identity=left[0],
                    exception_mro=left[1],
                )
            if right is not None and left is None:
                return _ConditionalRaiseRoute(
                    slot=branch_result_slot(statement.test),
                    raised_on_true=False,
                    exception_identity=right[0],
                    exception_mro=right[1],
                )
        return None

    def _merge_completion_nets(
        self,
        scope,
        nets,
        *,
        conditional_route,
    ) -> BindingMap:
        if not nets:
            return {}
        if len(nets) == 1:
            return dict(nets[0])
        names = set().union(*(net.keys() for net in nets))
        merged: BindingMap = {}
        for name in sorted(names):
            states = [net.get(name, _explicit_state(name, scope)) for net in nets]
            if any(state is _MISSING for state in states):
                continue
            if all(state is states[0] or state == states[0] for state in states[1:]):
                merged[name] = states[0]
                continue
            if conditional_route is not None and len(states) == 2:
                body_state, handler_state = states
                when_true, when_false = (
                    (handler_state, body_state)
                    if conditional_route.raised_on_true
                    else (body_state, handler_state)
                )
                merged[name] = join_binding_state(
                    slot=conditional_route.slot,
                    when_true=when_true,
                    when_false=when_false,
                    make_ifexp=self._make_ifexp,
                )
                continue
            if all(isinstance(state, UnboundBinding) for state in states):
                merged[name] = states[0]
        return merged

    def _make_ifexp(self, test, body, orelse):
        return If._make_ifexp(self, test, body, orelse)

    def _make_branch_result_ref(self, slot):
        return If._make_branch_result_ref(self, slot)

    def _construct_sugar(self):
        """`try: body (except E: handler)+ [else] [finally]` -- the STRUCTURAL
        sibling of with-raises. A typed clause contributes one constructed,
        authenticated exception coordinate per Name element of a tuple; a bare
        clause contributes the widest raise matcher. Unresolved/dotted/computed
        type expressions and empty tuples stay loud. ``except*`` lives on
        TryStar and stays loud there.

        ``except <type> as <name>``: substitute already rewrote loads of
        ``name`` to ``EffectRef(slot)`` inside the handler. Routing
        authenticates that slot with the matched Halted raise — never E().
        """
        from sugar_lift_py_tests.sugar.try_sugar import TrySugar

        if not self.handlers:
            # try/finally-only (no except): same TrySugar with empty handlers;
            # finally is ExitSet.and_finally over the body exits.
            if not self.finalbody:
                return super()._construct_sugar()
            return TrySugar(
                body=tuple(stmt.sugar() for stmt in self.body),
                handlers=(),
                orelse=tuple(stmt.sugar() for stmt in self.orelse),
                finalbody=tuple(stmt.sugar() for stmt in self.finalbody),
                site=self.fragment,
            )

        handler_specs = []
        for handler in self.handlers:
            # Every handler owns an effect slot. ``as e`` projects it; a bare
            # re-raise cites the same slot even without a lexical target.
            slot_id = handler._effect_slot_id()
            body_sugars = tuple(stmt.sugar() for stmt in handler.body)
            if handler.type_ is None:
                handler_specs.append((None, body_sugars, slot_id))
                continue

            type_nodes = (
                handler.type_.elts
                if handler.type_.kind == "Tuple"
                else (handler.type_,)
            )
            if not type_nodes:
                return super()._construct_sugar()  # empty tuple: no honest matcher
            for type_node in type_nodes:
                if not isinstance(type_node, Name):
                    return super()._construct_sugar()
                identity = self.unit.exception_type_identity(type_node)
                if identity is None:
                    raise SugarNotWritten(
                        owner="Try._construct_sugar",
                        observed="typed except handler lacks authenticated exception identity",
                        requested="a constructed exception-type coordinate",
                        fix="resolve the handler type lexically or keep the try loud",
                    )
                from sugar_lift_py_tests.sugar.authenticated_exception_type_sugar import (
                    AuthenticatedExceptionTypeSugar,
                )

                handler_specs.append(
                    (
                        AuthenticatedExceptionTypeSugar(
                            type_node.sugar(),
                            identity,
                            self.unit.exception_type_mro(type_node),
                            type_node.fragment,
                        ),
                        body_sugars,
                        slot_id,
                    )
                )

        return TrySugar(
            body=tuple(stmt.sugar() for stmt in self.body),
            handlers=tuple(handler_specs),
            orelse=tuple(stmt.sugar() for stmt in self.orelse),
            finalbody=tuple(stmt.sugar() for stmt in self.finalbody),
            site=self.fragment,
        )


class TryStar(Statement):
    body: Tuple[Statement, ...]
    handlers: Tuple[ExceptHandler, ...]
    orelse: Tuple[Statement, ...]
    finalbody: Tuple[Statement, ...]
    _child_fields = ("body", "handlers", "orelse", "finalbody")

    def substitute(self, scope):
        """Same block-aware substitute as Try (identical fields)."""
        return Try.substitute(self, scope)


class Assert(Statement):
    test: Expression
    msg: Optional[Expression]
    _child_fields = ("test", "msg")

    def substitute(self, scope):
        """`assert <test>[, <msg>]` binds nothing: recurse into test and msg."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`assert <test>[, <msg>]` constructs AssertSugar WITH the test's
        sugar. The test recognizes itself (self.test.sugar()) — the recursion.
        The message is provenance only (#4593/#4594): AssertSugar never builds
        or reduces it; its pinned fragment rides separately from the condition.
        """
        from sugar_lift_py_tests.sugar.assert_sugar import AssertSugar

        return AssertSugar(
            test=self.test.sugar(),
            message=self.msg.fragment if self.msg is not None else None,
            site=self.fragment,
        )


class Import(Statement):
    names: Tuple[ImportAlias, ...]
    _child_fields = ("names",)

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self

    def _construct_sugar(self):
        """`import <module>` binds a module name that stays a FREE SYMBOLIC
        in the meaning layer: nothing about the import itself is stated as
        a fact. A later `pd.concat(...)` reduces as a method coordinate on
        the free name `pd` -- correct without the import ever having stated
        anything. So the import contributes an honestly empty record."""
        from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

        return InertSugar(site=self.fragment)


class ImportFrom(Statement):
    module: Optional[str]
    names: Tuple[ImportAlias, ...]
    level: int
    _child_fields = ("names",)

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self

    def _construct_sugar(self):
        """`from <module> import <names>` binds free symbolics the same way
        plain `import` does: the bound names stay FREE SYMBOLIC in the
        meaning layer, reduced only where a later expression uses them as a
        coordinate. The import statement itself states nothing."""
        from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

        return InertSugar(site=self.fragment)


class Global(Statement):
    names: Tuple[str, ...]

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self

    def _construct_sugar(self):
        """`global <names>` is a scope DECLARATION, not a fact: it tells
        substitute which enclosing binding a name resolves against. That
        binding semantics lives entirely in substitute (see above) -- by
        the time sugar/meaning runs, the declaration itself has nothing
        left to state."""
        from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

        return InertSugar(site=self.fragment)


class Nonlocal(Statement):
    names: Tuple[str, ...]

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self

    def _construct_sugar(self):
        """`nonlocal <names>` is a scope DECLARATION like `global`: it
        routes a name to an enclosing function scope during substitute.
        Once substitute has resolved the binding, the declaration carries
        no further meaning-layer content of its own."""
        from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

        return InertSugar(site=self.fragment)


class Expr(Statement):
    """An expression in statement position."""

    value: Expression
    _child_fields = ("value",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`<expr>` as a statement constructs ExprStatementSugar WITH the
        value's sugar. States nothing; an effect in the value rides."""
        from sugar_lift_py_tests.sugar.expr_statement_sugar import (
            ExprStatementSugar,
        )

        return ExprStatementSugar(value=self.value.sugar(), site=self.fragment)


class Pass(Statement):
    pass

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self

    def _construct_sugar(self):
        """`pass` states nothing by definition: it is the syntax for an
        intentionally empty statement body. Its sugar is the honestly
        empty record, not a placeholder awaiting content."""
        from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

        return InertSugar(site=self.fragment)


class Break(Statement):
    pass

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.loop_control_sugar import LoopControlSugar

        target = self.control_context.nearest_loop_target()
        return LoopControlSugar(
            "break", target.target_cid, self.fragment.seal().cid, self.fragment
        )


class Continue(Statement):
    pass

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.loop_control_sugar import LoopControlSugar

        target = self.control_context.nearest_loop_target()
        return LoopControlSugar(
            "continue", target.target_cid, self.fragment.seal().cid, self.fragment
        )


class Match(Statement):
    subject: Expression
    cases: Tuple[MatchCase, ...]
    _child_fields = ("subject", "cases")

    def substitute(self, scope):
        """The subject evaluates in the enclosing scope; each case's captures
        bind to that SUBJECT for its body. `case x:` is x = subject, so the
        subject node is threaded into that case's body substitution as the
        capture binding -- the temporal half of a capture, exactly as an
        assignment's rhs threads to the rest of a block."""
        from .shadow import rewrite

        new_subject, subj_changed = self._substitute_field(self.subject, scope)
        subject = new_subject if subj_changed else self.subject

        new_cases = []
        cases_changed = False
        for case in self.cases:
            capture = self._capture_name(case.pattern)
            if capture is not None:
                new_case = case.substitute(scope, extra_bindings={capture: subject})
            else:
                new_case = case.substitute(scope)
            if new_case is not case:
                cases_changed = True
            new_cases.append(new_case)

        changed = {}
        if subj_changed:
            changed["subject"] = new_subject
        if cases_changed:
            changed["cases"] = tuple(new_cases)
        return self if not changed else rewrite(self, **changed)

    def _pattern_alternatives(self, pattern):
        """The value-pattern alternatives a case matches, as literal sugars:
        ``()`` for a catch-all (`case _:` / capture `case x:`), ``(sugar,)`` for a
        value or singleton, the concatenation for an OR-pattern `a | b`. Returns
        None for a pattern this cut does not own (structural: sequence / mapping /
        class / star, or a nested capture inside an OR)."""
        if pattern.kind == "MatchValue":
            return (pattern.value.sugar(),)
        if pattern.kind == "MatchSingleton":
            return (self._singleton_sugar(pattern.value),)
        if pattern.kind == "MatchAs" and pattern.pattern is None:
            return ()  # wildcard or capture -- always matches
        if pattern.kind == "MatchOr":
            alts: list = []
            for sub in pattern.patterns:
                sub_alts = self._pattern_alternatives(sub)
                # An OR of value/singleton patterns only; a catch-all or
                # structural arm inside an OR is not a value alternative.
                if not sub_alts:
                    return None
                alts.extend(sub_alts)
            return tuple(alts)
        return None

    def _singleton_sugar(self, value):
        """The literal sugar for a MatchSingleton value (None / True / False)."""
        if value is None:
            from sugar_lift_py_tests.sugar.none_literal_sugar import NoneLiteralSugar

            return NoneLiteralSugar(site=self.fragment)
        if value:
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return TrueBoolLiteralSugar(site=self.fragment)
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        return FalseBoolLiteralSugar(site=self.fragment)

    @staticmethod
    def _capture_name(pattern):
        """The name a bare capture pattern (`case x:`) binds, or None. A capture
        is a MatchAs with no sub-pattern and a name; `case _:` (name None) is the
        wildcard and binds nothing."""
        if (
            pattern.kind == "MatchAs"
            and pattern.pattern is None
            and pattern.name is not None
        ):
            return pattern.name
        return None

    def _construct_sugar(self):
        """`match <subject>: case P: body ...` constructs MatchSugar -- an n-way
        guarded split. This first cut owns VALUE patterns (`case <literal>:`) and
        the wildcard (`case _:`), with no pattern guard and no capture. Any other
        pattern, a `case P if g:` guard, or a capture inherits the loud throw --
        each is real matching semantics, never guessed.
        """
        from sugar_lift_py_tests.sugar.match_sugar import MatchCaseSpec, MatchSugar

        specs = []
        for case in self.cases:
            if case.guard is not None:
                return super()._construct_sugar()  # `case P if g:` not written
            alternatives = self._pattern_alternatives(case.pattern)
            if alternatives is None:
                return (
                    super()._construct_sugar()
                )  # structural pattern (sequence/class/...)
            specs.append(
                MatchCaseSpec(
                    alternatives=alternatives,
                    body=tuple(s.sugar() for s in case.body),
                )
            )
        return MatchSugar(
            subject=self.subject.sugar(), cases=tuple(specs), site=self.fragment
        )


# --------------------------------------------------------------------------
# Expressions
# --------------------------------------------------------------------------


class BoolOp(Expression):
    op: BooleanOperator
    values: Tuple[Expression, ...]
    _child_fields = ("values",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`a and b` / `a or b` constructs BoolOpSugar WITH each operand's sugar.
        The node knows its connective (And/Or); the operands recognize themselves."""
        from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar

        return BoolOpSugar(
            op_kind=self.op.kind,
            values=tuple(v.sugar() for v in self.values),
            site=self.fragment,
        )


class NamedExpr(Expression):
    target: Expression
    value: Expression
    _child_fields = ("target", "value")

    def substitute(self, scope):
        """`(<target> := <value>)` -- substitute the value; the target is a
        binding site, not substituted. The walrus's binding leaks to the
        enclosing block (collected by `_substitute_body`), and the expression
        itself evaluates to the (substituted) value, so a use in the same
        expression sees it. Here we rewrite to the value: `(x := e)` as a
        sub-expression IS `e` once bound, and the binding is threaded out."""
        from .shadow import rewrite

        new_value, d = self._substitute_field(self.value, scope)
        return self if not d else rewrite(self, value=new_value)

    def substitution_binding(self, scope):
        # `x := e` binds x to e for the rest of the enclosing block. Only a
        # plain Name target binds.
        if isinstance(self.target, Name):
            return {self.target.id: self.value}
        return None


class BinOp(Expression):
    left: Expression
    op: BinaryOperator
    right: Expression
    _child_fields = ("left", "right")

    def substitute(self, scope):
        """A binary operation binds nothing: it just recurses into its two
        operands and reassembles. The op itself is a leaf, carried through."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`<left> <op> <right>` constructs BinOpSugar WITH both sides' sugars.
        The node already knows its operator, so one sugar dispatches to the
        floor method that operator names. An operator with no floor method is a
        genuine gap -- it inherits the base throw, never a silent default."""
        from sugar_lift_py_tests.sugar.binop_sugar import BINOP_METHODS, BinOpSugar

        if self.op.kind not in BINOP_METHODS:
            return super()._construct_sugar()
        return BinOpSugar(
            op_kind=self.op.kind,
            left=self.left.sugar(),
            right=self.right.sugar(),
            site=self.fragment,
        )


class UnaryOp(Expression):
    op: UnaryOperator
    operand: Expression
    _child_fields = ("operand",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`<op> <operand>` constructs UnaryOpSugar WITH the operand's sugar. The
        node already knows its operator; an operator with no floor method inherits
        the base throw, never a silent default."""
        from sugar_lift_py_tests.sugar.unary_op_sugar import (
            UNARYOP_METHODS,
            UnaryOpSugar,
        )

        if self.op.kind != "Not" and self.op.kind not in UNARYOP_METHODS:
            return super()._construct_sugar()
        return UnaryOpSugar(
            op_kind=self.op.kind, operand=self.operand.sugar(), site=self.fragment
        )


class Lambda(Expression):
    params: Tuple[Param, ...]
    body: Expression
    _child_fields = ("params", "body")

    @property
    def args(self):
        return _arguments_projection(self.params)

    def substitute(self, scope):
        """Mask formals and mark the result as substitution-authenticated."""
        from .shadow import rewrite

        bound = {p.name for p in self.params}
        bs = {k: v for k, v in scope.items() if k not in bound} if bound else scope
        new_params, d = self._substitute_field(self.params, scope)
        del d
        new_body, d = self._substitute_field(self.body, bs)
        del d
        # Always rewrite, even when the children are identical.  A ShadowNode
        # is the construction-time testimony that capture substitution ran.
        return rewrite(self, params=new_params, body=new_body)

    def source_visible_call_frame(self):
        """Project the lambda through the ordinary source-call-frame door."""
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.source_call_frame import SourceVisibleCallFrameV1
        from sugar_source_tree.binding_provenance import BindingCoordinateV1

        span = self.line_col_span()
        site = SourceFragmentCoordinateV1(
            self.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
        owner_cid = self.fragment.seal().cid
        coordinates = tuple(
            BindingCoordinateV1.mint(owner_cid, param.fragment, ("formal", index))
            for index, param in enumerate(self.params)
        )
        formal_scope = {
            param.name: self._make_coordinate_ref(param, coordinate)
            for param, coordinate in zip(self.params, coordinates, strict=True)
        }
        return SourceVisibleCallFrameV1(
            source_identity_cid=self.unit.source_cid,
            definition_site=site,
            definition_fragment_cid=owner_cid,
            parameters=tuple(param.name for param in self.params),
            formal_coordinates=coordinates,
            parameter_kinds=tuple(param.param_kind for param in self.params),
            default_sugars=tuple(
                param.default.sugar() if param.default is not None else None
                for param in self.params
            ),
            default_nodes=tuple(param.default for param in self.params),
            default_fragments=tuple(
                param.default.fragment if param.default is not None else None
                for param in self.params
            ),
            default_fragment_cids=tuple(
                param.default.fragment.seal().cid if param.default is not None else None
                for param in self.params
            ),
            body=self._source_visible_body(formal_scope),
            owner=self,
        )

    def _source_visible_body(self, scope):
        from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar
        from sugar_lift_py_tests.sugar.source_visible_function_body_sugar import (
            SourceVisibleFunctionBodySugar,
        )

        body = self.body.substitute(scope)
        return SourceVisibleFunctionBodySugar(
            (ReturnSugar(value=body.sugar(), site=self.fragment),), self.fragment
        )

    def _make_coordinate_ref(self, param: "Param", coordinate) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "BindingCoordinateRef",
                param.span,
                (("coordinate", Leaf(coordinate)),),
            ),
            self.reporter,
        )

    def _construct_sugar(self):
        """Construct an expression lambda carrying its ordinary source frame."""
        from .shadow import ShadowNode

        if not isinstance(self.ref, ShadowNode):
            return super()._construct_sugar()

        from sugar_lift_py_tests.sugar.lambda_sugar import LambdaSugar

        return LambdaSugar(
            formals=tuple(param.name for param in self.params),
            body=self.body.sugar(),
            source_call_frame=self.source_visible_call_frame(),
            site=self.fragment,
        )


class IfExp(Expression):
    test: Expression
    body: Expression
    orelse: Expression
    _child_fields = ("body", "test", "orelse")

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`<body> if <test> else <orelse>` constructs IfExpSugar -- the
        conditional VALUE the phi produces. It desugars to a GuardedValue that
        DISTRIBUTES (a return/equality splits into per-arm implications, each arm
        resolved per-atom), so the conditional never becomes a single mixed-sort
        term; the compiler stays Python-ignorant and only ever sees ir.eq."""
        from sugar_lift_py_tests.sugar.if_exp_sugar import IfExpSugar

        return IfExpSugar(
            test=self.test.sugar(),
            body=self.body.sugar(),
            orelse=self.orelse.sugar(),
            site=self.fragment,
        )


class Dict(Expression):
    items: Tuple[DictItem, ...]
    _child_fields = ("items",)

    @property
    def keys(self) -> Tuple[Optional[Expression], ...]:
        return tuple(item.key for item in self.items)

    @property
    def values(self) -> Tuple[Expression, ...]:
        return tuple(item.value for item in self.items)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`{k: v, ...}` constructs DictSugar WITH each key and value sugar.
        A `**d` entry uses the reference lifter's None-key spread shape."""
        from sugar_lift_py_tests.sugar.collection_sugar import DictSugar

        if any(item.key is None for item in self.items):
            from sugar_lift_py_tests.sugar.spread_sugar import SpreadDictSugar

            return SpreadDictSugar(
                entries=tuple(
                    (
                        item.key.sugar() if item.key is not None else None,
                        item.value.sugar(),
                    )
                    for item in self.items
                ),
                site=self.fragment,
            )
        return DictSugar(
            keys=tuple(item.key.sugar() for item in self.items),
            values=tuple(item.value.sugar() for item in self.items),
            site=self.fragment,
        )


class Set(Expression):
    elts: Tuple[Expression, ...]
    _child_fields = ("elts",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`{e, ...}` constructs SetSugar; a spread uses its reference term."""
        from sugar_lift_py_tests.sugar.collection_sugar import SetSugar

        if any(isinstance(e, Starred) for e in self.elts):
            from sugar_lift_py_tests.sugar.spread_sugar import SpreadCollectionSugar

            return SpreadCollectionSugar(
                kind="set",
                elements=tuple(
                    (
                        ("python:starred", e.value.sugar())
                        if isinstance(e, Starred)
                        else (None, e.sugar())
                    )
                    for e in self.elts
                ),
                site=self.fragment,
            )
        return SetSugar(
            elements=tuple(e.sugar() for e in self.elts), site=self.fragment
        )


class ListComp(Expression):
    elt: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("elt", "generators")

    def substitute(self, scope):
        """A comprehension: thread each generator's target, then substitute the
        element against the scope with every target masked.

        Over a CONCRETE iterable it DISSOLVES -- `map` disappearing for real:
        `[e for x in [1, 2, 3]]` is three substitutions of x into e, and the
        comprehension rewrites to the List DISPLAY of those elements. The
        comprehension was never a meaning; it was a count of rewrites."""
        unrolled = (
            None
            if scope.get(_NESTED_COMPREHENSION_TEMPLATE)
            else self._try_unroll_to_display(scope)
        )
        if unrolled is not None:
            return unrolled
        from .shadow import rewrite

        new_gens, inner, gc = self._substitute_generators(self.generators, scope)
        template_scope = inner
        if ListComp._contains_forbidden_shape(self, (self.elt,)):
            template_scope = {**inner, _NESTED_COMPREHENSION_TEMPLATE: True}
        new_elt, de = self._substitute_field(self.elt, template_scope)
        changed = {}
        if gc:
            changed["generators"] = new_gens
        if de:
            changed["elt"] = new_elt
        return self if not changed else rewrite(self, **changed)

    def _try_unroll_to_display(self, scope):
        """The List display this comprehension dissolves to, or None. One
        synchronous generator with ground-decidable filters,
        over a CONCRETE iterable whose elements destructure into the target:
        each element substitutes into `elt`, and the results are the display's
        elements. Reuses For's readers (same structural recognition)."""
        if len(self.generators) != 1 or ListComp._contains_forbidden_shape(
            self, (self.elt,)
        ):
            return None
        gen = self.generators[0]
        if gen.is_async or ListComp._contains_forbidden_shape(
            self, (gen.iter, *gen.ifs)
        ):
            return None
        new_iter, ic = self._substitute_field(gen.iter, scope)
        it = new_iter if ic else gen.iter
        if ListComp._calls_shadowed_range(self, it, scope):
            return None
        elements = For._concrete_elements(self, it)
        if elements is None:
            return None
        if len(elements) > For._UNROLL_FUEL:
            return None
        target = gen.target
        results = []
        for element in elements:
            bindings = For._target_bindings_for(self, target, element)
            if bindings is None:
                return None
            inner = {**scope, **bindings}
            filters_pass = ListComp._ground_filters_pass(self, gen.ifs, inner)
            if filters_pass is None:
                return None
            if not filters_pass:
                continue
            new_elt, _d = self._substitute_field(self.elt, inner)
            results.append(new_elt if _d else self.elt)
        return ListComp._make_list(self, tuple(results))

    def _ground_filters_pass(self, filters, scope) -> "Optional[bool]":
        """The conjunction of constructed ground filters, or no testimony.

        Every comprehension kind shares this reader. A symbolic guard yields
        ``None`` so the enclosing node stays loud; no guard verdict is guessed.
        """
        verdicts = []
        for guard in filters:
            new_guard, changed = self._substitute_field(guard, scope)
            verdict = While._ground_truth(self, new_guard if changed else guard)
            if verdict is None:
                return None
            verdicts.append(verdict)
        return all(verdicts)

    def _contains_forbidden_shape(self, roots: tuple) -> bool:
        """True for a nested comprehension or walrus in this comprehension."""
        return any(
            node.kind
            in ("ListComp", "SetComp", "DictComp", "GeneratorExp", "NamedExpr")
            for root in roots
            for node in root.walk()
        )

    def _contains_named_expression(self, roots: tuple) -> bool:
        """True when a walrus would bind outside the comprehension coordinate."""
        return any(node.kind == "NamedExpr" for root in roots for node in root.walk())

    def _calls_shadowed_range(self, iterable, scope) -> bool:
        return (
            (
                iterable.kind == "Call"
                and iterable.func.kind == "Name"
                and iterable.func.id == "range"
                and "range" in scope
            )
            or (
                iterable.kind == "Call"
                and iterable.func.kind == "Name"
                and iterable.func.id == "range"
                and "range" in scope.get(_LEXICALLY_BOUND_NAMES, ())
            )
            or (
                iterable.kind == "Call"
                and iterable.func.kind == "Name"
                and iterable.func.id == "range"
                and "range" in self.unit.module_bound_names
            )
        )

    def _ground_hash_key(self, expression):
        """A Python-equality key for the small ground scalar domain, or None."""
        integer = For._concrete_int(self, expression)
        if integer is not None:
            return ("number", integer)
        if expression.kind != "Constant":
            return None
        value = expression.value
        if type(value) is bool:
            return ("number", int(value))
        if type(value) is str:
            return ("str", value)
        if value is None:
            return ("none", None)
        return None

    def _make_list(self, elements: tuple) -> "Node":
        """Synthesize a List display of these element nodes, borrowing this
        comprehension's span -- the dissolved `map`, a display like any other."""
        from .backend import Children, materialize
        from .shadow import ShadowNode, _handle_of

        slots = (("elts", Children(tuple(_handle_of(e) for e in elements))),)
        return materialize(
            self.unit, ShadowNode("List", self.span, slots), self.reporter
        )

    def _construct_sugar(self):
        generators = ListComp._recurrence_generators(self)
        if generators is None or ListComp._contains_named_expression(self, (self.elt,)):
            return super()._construct_sugar()
        from sugar_lift_py_tests.sugar.comprehension_sugar import (
            ComprehensionSugar,
        )

        return ComprehensionSugar(
            kind="py.listcomp",
            generators=generators,
            element=self.elt.sugar(),
            site=self.fragment,
        )

    def _recurrence_generators(self):
        from sugar_lift_python_source.canonical import cid_of_json
        from sugar_lift_py_tests.sugar.comprehension_sugar import (
            ComprehensionGeneratorSugar,
        )
        from .binding_state import mint_binding_coordinate_v1

        specs = []
        scope_owner_cid = cid_of_json(
            {
                "kind": "comprehension-binding-scope",
                "schemaVersion": "1",
                "source": self.fragment.seal().to_dict(),
            }
        )
        for generator_index, gen in enumerate(self.generators):
            if (
                gen.is_async
                or gen.target.kind != "Name"
                or ListComp._contains_named_expression(self, (gen.iter, *gen.ifs))
            ):
                return None
            specs.append(
                ComprehensionGeneratorSugar(
                    source_name=gen.target.id,
                    binding_coordinate_cid=mint_binding_coordinate_v1(
                        scope_owner_cid=scope_owner_cid,
                        binding_site=gen.target.fragment,
                        projection_path=("generators", generator_index, "target"),
                    ).cid,
                    iterable=gen.iter.sugar(),
                    filters=tuple(guard.sugar() for guard in gen.ifs),
                )
            )
        return tuple(specs)

    def _simple_generator(self, *, allow_nested_iterable=False):
        if len(self.generators) != 1:
            return None
        gen = self.generators[0]
        if (
            gen.is_async
            or gen.ifs
            or gen.target.kind != "Name"
            or (
                ListComp._contains_named_expression(self, (gen.iter,))
                if allow_nested_iterable
                else ListComp._contains_forbidden_shape(self, (gen.iter,))
            )
        ):
            return None
        return gen


class SetComp(Expression):
    elt: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("elt", "generators")

    def substitute(self, scope):
        """A comprehension: thread each generator's target, then substitute the
        element against the scope with every target masked."""
        display = (
            None
            if scope.get(_NESTED_COMPREHENSION_TEMPLATE)
            else self._try_unroll_to_display(scope)
        )
        if display is not None:
            return display
        from .shadow import rewrite

        new_gens, inner, gc = self._substitute_generators(self.generators, scope)
        template_scope = inner
        if ListComp._contains_forbidden_shape(self, (self.elt,)):
            template_scope = {**inner, _NESTED_COMPREHENSION_TEMPLATE: True}
        new_elt, de = self._substitute_field(self.elt, template_scope)
        changed = {}
        if gc:
            changed["generators"] = new_gens
        if de:
            changed["elt"] = new_elt
        return self if not changed else rewrite(self, **changed)

    def _try_unroll_to_display(self, scope):
        if len(self.generators) != 1 or ListComp._contains_forbidden_shape(
            self, (self.elt,)
        ):
            return None
        gen = self.generators[0]
        if gen.is_async or ListComp._contains_forbidden_shape(self, (gen.iter,)):
            return None
        new_iter, changed = self._substitute_field(gen.iter, scope)
        iterable = new_iter if changed else gen.iter
        if ListComp._calls_shadowed_range(self, iterable, scope):
            return None
        elements = For._concrete_elements(self, iterable)
        if elements is None or len(elements) > For._UNROLL_FUEL:
            return None
        results = []
        seen = set()
        for element in elements:
            bindings = For._target_bindings_for(self, gen.target, element)
            if bindings is None:
                return None
            inner = {**scope, **bindings}
            filters_pass = ListComp._ground_filters_pass(self, gen.ifs, inner)
            if filters_pass is None:
                return None
            if not filters_pass:
                continue
            new_elt, changed = self._substitute_field(self.elt, inner)
            result = new_elt if changed else self.elt
            key = ListComp._ground_hash_key(self, result)
            if key is None:
                return None
            if key not in seen:
                seen.add(key)
                results.append(result)
        return SetComp._make_set(self, tuple(results))

    def _make_set(self, elements: tuple) -> "Node":
        from .backend import Children, materialize
        from .shadow import ShadowNode, _handle_of

        slots = (("elts", Children(tuple(_handle_of(e) for e in elements))),)
        return materialize(
            self.unit, ShadowNode("Set", self.span, slots), self.reporter
        )

    def _construct_sugar(self):
        generators = ListComp._recurrence_generators(self)
        if generators is None or ListComp._contains_forbidden_shape(self, (self.elt,)):
            return super()._construct_sugar()
        from sugar_lift_py_tests.sugar.comprehension_sugar import ComprehensionSugar

        return ComprehensionSugar(
            kind="py.setcomp",
            generators=generators,
            element=self.elt.sugar(),
            site=self.fragment,
        )


class DictComp(Expression):
    key: Expression
    value: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("key", "value", "generators")

    def substitute(self, scope):
        """A dict comprehension: thread the generators, then key and value
        against the scope with every target masked."""
        display = (
            None
            if scope.get(_NESTED_COMPREHENSION_TEMPLATE)
            else self._try_unroll_to_display(scope)
        )
        if display is not None:
            return display
        from .shadow import rewrite

        new_gens, inner, gc = self._substitute_generators(self.generators, scope)
        template_scope = inner
        if ListComp._contains_forbidden_shape(self, (self.key, self.value)):
            template_scope = {**inner, _NESTED_COMPREHENSION_TEMPLATE: True}
        changed = {}
        if gc:
            changed["generators"] = new_gens
        for fld in ("key", "value"):
            new, d = self._substitute_field(getattr(self, fld), template_scope)
            if d:
                changed[fld] = new
        return self if not changed else rewrite(self, **changed)

    def _try_unroll_to_display(self, scope):
        if len(self.generators) != 1 or ListComp._contains_forbidden_shape(
            self, (self.key, self.value)
        ):
            return None
        gen = self.generators[0]
        if gen.is_async or ListComp._contains_forbidden_shape(self, (gen.iter,)):
            return None
        new_iter, changed = self._substitute_field(gen.iter, scope)
        iterable = new_iter if changed else gen.iter
        if ListComp._calls_shadowed_range(self, iterable, scope):
            return None
        elements = For._concrete_elements(self, iterable)
        if elements is None or len(elements) > For._UNROLL_FUEL:
            return None
        pairs = []
        key_indexes = {}
        for element in elements:
            bindings = For._target_bindings_for(self, gen.target, element)
            if bindings is None:
                return None
            inner = {**scope, **bindings}
            filters_pass = ListComp._ground_filters_pass(self, gen.ifs, inner)
            if filters_pass is None:
                return None
            if not filters_pass:
                continue
            key, key_changed = self._substitute_field(self.key, inner)
            value, value_changed = self._substitute_field(self.value, inner)
            result_key = key if key_changed else self.key
            result_value = value if value_changed else self.value
            hash_key = ListComp._ground_hash_key(self, result_key)
            if hash_key is None:
                return None
            pair = (result_key, result_value)
            prior = key_indexes.get(hash_key)
            if prior is None:
                key_indexes[hash_key] = len(pairs)
                pairs.append(pair)
            else:
                pairs[prior] = pair
        return DictComp._make_dict(self, tuple(pairs))

    def _make_dict(self, pairs: tuple) -> "Node":
        from .backend import Child, Children, materialize
        from .shadow import ShadowNode, _handle_of

        items = []
        for key, value in pairs:
            slots = (
                ("key", Child(_handle_of(key))),
                ("value", Child(_handle_of(value))),
            )
            item = materialize(
                self.unit, ShadowNode("DictItem", self.span, slots), self.reporter
            )
            items.append(_handle_of(item))
        return materialize(
            self.unit,
            ShadowNode("Dict", self.span, (("items", Children(tuple(items))),)),
            self.reporter,
        )

    def _construct_sugar(self):
        generators = ListComp._recurrence_generators(self)
        if generators is None or ListComp._contains_forbidden_shape(
            self, (self.key, self.value)
        ):
            return super()._construct_sugar()
        from sugar_lift_py_tests.sugar.comprehension_sugar import ComprehensionSugar

        return ComprehensionSugar(
            kind="py.dictcomp",
            generators=generators,
            key=self.key.sugar(),
            element=self.value.sugar(),
            site=self.fragment,
        )


class GeneratorExp(Expression):
    elt: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("elt", "generators")

    def substitute(self, scope):
        """A comprehension: thread each generator's target, then substitute the
        element against the scope with every target masked."""
        from .shadow import rewrite

        new_gens, inner, gc = self._substitute_generators(self.generators, scope)
        template_scope = inner
        if ListComp._contains_forbidden_shape(self, (self.elt,)):
            template_scope = {**inner, _NESTED_COMPREHENSION_TEMPLATE: True}
        new_elt, de = self._substitute_field(self.elt, template_scope)
        changed = {}
        if gc:
            changed["generators"] = new_gens
        if de:
            changed["elt"] = new_elt
        return self if not changed else rewrite(self, **changed)

    def _construct_sugar(self):
        generators = ListComp._recurrence_generators(self)
        if generators is None or ListComp._contains_named_expression(self, (self.elt,)):
            return super()._construct_sugar()
        from sugar_lift_py_tests.sugar.comprehension_sugar import ComprehensionSugar

        return ComprehensionSugar(
            kind="py.generatorexp",
            generators=generators,
            element=self.elt.sugar(),
            site=self.fragment,
        )


class Await(Expression):
    value: Expression
    _child_fields = ("value",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)


class Yield(Expression):
    value: Optional[Expression]
    _child_fields = ("value",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)


class YieldFrom(Expression):
    value: Expression
    _child_fields = ("value",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)


class Compare(Expression):
    left: Expression
    ops: Tuple[ComparisonOperator, ...]
    comparators: Tuple[Expression, ...]
    _child_fields = ("left", "comparators")

    def substitute(self, scope):
        """A comparison binds nothing: recurse into its operands (the operators
        are leaves, carried through)."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """A comparison constructs its operator's sugar, built WITH its
        children's sugar. `==` is EqualityOpSugar (it also refines); the ordering
        family and `!=` are ComparisonOpSugar. A CHAINED comparison `a < b < c`
        is `(a < b) and (b < c)` -- each adjacent pair becomes its own comparison
        sugar and they conjoin (b is the same reduced term in both, as Python
        evaluates it once). Identity/membership operators (is/in/...) inherit the
        loud throw until written.
        """
        from .operators import Eq
        from sugar_lift_py_tests.sugar.comparison_op_sugar import (
            COMPARISON_KINDS,
            ComparisonOpSugar,
        )
        from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar

        def supported(op):
            return isinstance(op, Eq) or op.kind in COMPARISON_KINDS

        if not all(supported(op) for op in self.ops):
            return super()._construct_sugar()

        operands = (self.left, *self.comparators)

        def pair(index):
            op = self.ops[index]
            left_s = operands[index].sugar()
            right_s = operands[index + 1].sugar()
            if isinstance(op, Eq):
                return EqualityOpSugar(left=left_s, right=right_s, site=self.fragment)
            return ComparisonOpSugar(
                op_kind=op.kind, left=left_s, right=right_s, site=self.fragment
            )

        pairs = tuple(pair(i) for i in range(len(self.ops)))
        if len(pairs) == 1:
            return pairs[0]
        from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar

        return BoolOpSugar(op_kind="And", values=pairs, site=self.fragment)


class Call(Expression):
    func: Expression
    args: Tuple[Expression, ...]
    keywords: Tuple[Keyword, ...]
    _child_fields = ("func", "args", "keywords")

    def substitute(self, scope):
        """A call binds nothing: recurse into the callee, args, and keywords.
        (A receiver `v.c(1)` substitutes through `func`, its Attribute; the
        chain rewrites naturally as the receiver's own tree is substituted.)"""
        return self._substitute_children(scope)

    def receiver(self) -> Optional[Expression]:
        """The object a method call is invoked on, when the callee is an
        attribute access. ``None`` is a structural absence (a plain call)."""
        func = self.func
        if isinstance(func, Attribute):
            return func.value
        return None

    def exposed_object_places(self) -> tuple["ObjectPlaceStateV1", ...]:
        """Object states crossing this call without a frame-condition proof."""
        roots = list(self.args) + [keyword.value for keyword in self.keywords]
        receiver = self.receiver()
        if receiver is not None:
            roots.append(receiver)
        seen = {}
        for root in roots:
            for node in root.walk():
                if isinstance(node, ObjectPlaceStateV1):
                    seen[node.object_identity_cid] = node
        return tuple(seen.values())

    def _construct_sugar(self):
        """A call constructs its callee's sugar WITH the argument sugars.
        `<name>(<args>)` -> CallSiteSugar, the call-site coordinate (THE DIG
        CUE). `<receiver>.<name>(<args>)` -> MethodCallSugar, the method
        coordinate `call:<name>(receiver, args)` with the receiver riding as
        runtime_dispatch_receiver. Any other callee expression (`fs[i](x)`,
        `d["k"](x)`) -> ComputedCallSugar, the `py.call(callee, args)`
        coordinate -- the callee reduces through whatever sugar its own node
        built, so a callee with no sugar (a Lambda called inline) still stays
        loud through the ordinary recursion. Named keywords and ``**`` spreads
        ride explicitly on every coordinate; none is dropped or interpreted."""
        # Either spread form selects the reference call coordinate. In
        # particular, a lone ``**d`` must not fall through to the legacy
        # keyword bridge as ``py.kwarg("**", d)``.
        has_spread = any(isinstance(arg, Starred) for arg in self.args) or any(
            keyword.arg is None for keyword in self.keywords
        )
        if has_spread:
            from sugar_lift_py_tests.sugar.spread_sugar import SpreadCallSugar

            arguments = tuple(
                (
                    ("star", None, arg.value.sugar())
                    if isinstance(arg, Starred)
                    else ("positional", None, arg.sugar())
                )
                for arg in self.args
            ) + tuple(
                (
                    "double-star" if kw.arg is None else "keyword",
                    kw.arg,
                    kw.value.sugar(),
                )
                for kw in self.keywords
            )
            callee_name = self._spread_callee_name(self.func)
            return SpreadCallSugar(
                callee_name=callee_name,
                callee=(None if isinstance(self.func, Name) else self.func.sugar()),
                arguments=arguments,
                site=self.fragment,
            )

        keyword_sugars = tuple(
            (kw.arg if kw.arg is not None else "**", kw.value.sugar())
            for kw in self.keywords
        )
        context = self.unit.construction_context
        source_call_frame = None
        source_call_resolution = None
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
            TreeConstructionContextV1,
        )

        if (
            isinstance(context, TreeConstructionContextV1)
            and context.source_call_frames
        ):
            span = self.line_col_span()
            coordinate = SourceFragmentCoordinateV1(
                self.unit.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            )
            source_call_frame = context.source_call_frames.get(coordinate)
            source_call_resolution = context.source_call_resolutions.get(coordinate)
        elif isinstance(context, TreeConstructionContextV1):
            span = self.line_col_span()
            coordinate = SourceFragmentCoordinateV1(
                self.unit.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            )
            source_call_resolution = context.source_call_resolutions.get(coordinate)
        if source_call_resolution is not None:
            from sugar_lift_py_tests.source_call_resolution import (
                SourceCallPreconstructionGapV1,
                SourceCallPreconstructionRefV1,
            )
            from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar

            if isinstance(source_call_resolution, SourceCallPreconstructionGapV1):
                return CallSiteSugar(
                    target_name="python:unresolved-source-call",
                    args=tuple(a.sugar() for a in self.args),
                    site=self.fragment,
                    keywords=keyword_sugars,
                    contract_resolution_gap=(
                        f"{source_call_resolution.kind}:"
                        f"{source_call_resolution.detail}"
                    ),
                )
            if not isinstance(source_call_resolution, SourceCallPreconstructionRefV1):
                from sugar_source_tree.panic import BackendDefect

                raise BackendDefect(
                    owner="Call._construct_sugar",
                    observed=type(source_call_resolution).__name__,
                    requested="closed source-call preconstruction result",
                    fix="emit one typed source-call ref or gap at the exact use site",
                )
            if (
                source_call_frame is None
                or source_call_frame.frame_cid
                != source_call_resolution.source_call_frame_cid
            ):
                from sugar_source_tree.panic import BackendDefect

                raise BackendDefect(
                    owner="Call._construct_sugar",
                    observed="source-call ref/frame mismatch",
                    requested="byte-identical prebound source frame CID",
                    fix="re-run authenticated source-call preconstruction",
                )
        if source_call_frame is not None:
            from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
            from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar

            if any(keyword.arg is None for keyword in self.keywords):
                raise SourceCallBindingGap(
                    "spread keyword requires typed variadic projection"
                )
            bound_frame = (
                source_call_frame
                if source_call_resolution is not None
                else source_call_frame.bind_node_actuals(
                    self.args,
                    tuple(
                        (keyword.arg, keyword.value)
                        for keyword in self.keywords
                        if keyword.arg is not None
                    ),
                )
            )
            if (
                source_call_resolution is not None
                and source_call_resolution.dispatch_kind == "method"
            ):
                if not isinstance(self.func, Attribute):
                    from sugar_source_tree.panic import BackendDefect

                    raise BackendDefect(
                        owner="Call._construct_sugar",
                        observed=self.func.kind,
                        requested="attribute callee for authenticated method dispatch",
                        fix="bind the method ref to its exact attribute-call occurrence",
                    )
                from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar

                return MethodCallSugar(
                    receiver=self.func.value.sugar(),
                    name=self.func.attr,
                    args=tuple(a.sugar() for a in self.args),
                    site=self.fragment,
                    keywords=keyword_sugars,
                    source_call_frame=bound_frame,
                )
            return CallSiteSugar(
                target_name=f"python:resolved-source-call:{bound_frame.frame_cid}",
                args=tuple(a.sugar() for a in self.args),
                site=self.fragment,
                keywords=keyword_sugars,
                source_call_frame=bound_frame,
            )
        if isinstance(self.func, Name):
            from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar

            contract_ref = None
            contract_resolution_gap = None
            resolution = None
            from sugar_lift_py_tests.call_contract_resolution import (
                CallContractResolutionGapV1,
            )
            call_refs = getattr(context, "call_contract_refs", None)
            if call_refs is not None:
                from sugar_lift_py_tests.call_contract_resolution import (
                    CallContractRefProtocolError,
                    CallContractResolutionGapV1,
                )
                from sugar_lift_py_tests.context_manager_resolution import (
                    SourceFragmentCoordinateV1,
                )

                span = self.line_col_span()
                coordinate = SourceFragmentCoordinateV1(
                    self.unit.source_cid,
                    span.start_line,
                    span.start_col,
                    span.end_line,
                    span.end_col,
                )
                resolution = None
                if coordinate in call_refs.enrolled_use_sites:
                    try:
                        resolution = call_refs.require(coordinate)
                    except CallContractRefProtocolError as exc:
                        from sugar_source_tree.panic import BackendDefect

                        raise BackendDefect(
                            owner="Call._construct_sugar",
                            observed="enrolled call demand missing from resolution table",
                            requested="one typed resolution row for every enrolled imported call",
                            fix="repair call-contract preconstruction; never fall through to an ordinary call",
                        ) from exc
            if isinstance(resolution, CallContractResolutionGapV1):
                contract_resolution_gap = resolution.kind.value
            elif resolution is not None:
                contract_ref = resolution

            source_call_frame = None
            definition = self.unit.source_allocation_definition_for_call(self)
            if (
                definition is not None
                and self.unit.source_class_has_authenticated_default_attribute_behavior(
                    definition
                )
            ):
                from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

                if any(keyword.arg is None for keyword in self.keywords):
                    raise SourceCallBindingGap(
                        "spread keyword requires typed variadic projection"
                    )
                source_call_frame = (
                    definition.source_visible_constructor_frame().bind_node_actuals(
                        self.args,
                        tuple(
                            (keyword.arg, keyword.value)
                            for keyword in self.keywords
                            if keyword.arg is not None
                        ),
                    )
                )

            return CallSiteSugar(
                target_name=self.func.id,
                args=tuple(a.sugar() for a in self.args),
                site=self.fragment,
                keywords=keyword_sugars,
                contract_ref=contract_ref,
                contract_resolution_gap=contract_resolution_gap,
                source_call_frame=source_call_frame,
            )
        if isinstance(self.func, Attribute):
            from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar

            return MethodCallSugar(
                receiver=self.func.value.sugar(),
                name=self.func.attr,
                args=tuple(a.sugar() for a in self.args),
                site=self.fragment,
                keywords=keyword_sugars,
            )
        from sugar_lift_py_tests.sugar.computed_call_sugar import ComputedCallSugar

        source_call_frame = None
        if isinstance(self.func, Lambda):
            from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

            if any(keyword.arg is None for keyword in self.keywords):
                raise SourceCallBindingGap(
                    "spread keyword requires typed variadic projection"
                )
            source_call_frame = self.func.source_visible_call_frame().bind_node_actuals(
                self.args,
                tuple(
                    (keyword.arg, keyword.value)
                    for keyword in self.keywords
                    if keyword.arg is not None
                ),
            )

        return ComputedCallSugar(
            callee=self.func.sugar(),
            args=tuple(a.sugar() for a in self.args),
            site=self.fragment,
            keywords=keyword_sugars,
            source_call_frame=source_call_frame,
        )

    @staticmethod
    def _spread_callee_name(callee: Expression) -> Optional[str]:
        """The reference lifter spells Name/Attribute chains as one callee.

        A computed callee has no spelling and is carried by its constructed
        child sugar instead.
        """
        if isinstance(callee, Name):
            return callee.id
        if isinstance(callee, Attribute):
            base = Call._spread_callee_name(callee.value)
            return f"{base}.{callee.attr}" if base is not None else None
        return None


class FormattedValue(Expression):
    value: Expression
    conversion: int
    format_spec: Optional["JoinedStr"]
    _child_fields = ("value", "format_spec")

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """Project the Python-reference three-operand formatted-value shape.

        CPython carries conversion as ``-1`` or the codepoint for exactly
        ``a``/``r``/``s``.  Anything else is malformed backend testimony, not
        a new language arm.  The optional format spec remains its own nested
        JoinedStr sugar; neither operand is dropped or replaced with an empty
        string.
        """
        from sugar_lift_py_tests.sugar.fstring_sugar import FormattedValueSugar

        if self.conversion == -1:
            conversion = None
        elif self.conversion in {ord("a"), ord("r"), ord("s")}:
            conversion = chr(self.conversion)
        else:
            backend_defect(
                owner="FormattedValue._construct_sugar",
                observed=f"unsupported f-string conversion slot {self.conversion!r}",
                requested="-1 or the codepoint for 'a', 'r', or 's'",
                fix="repair the backend adapter; never invent a conversion",
            )
        format_spec = self.format_spec
        if format_spec is not None and not isinstance(format_spec, JoinedStr):
            backend_defect(
                owner="FormattedValue._construct_sugar",
                observed=f"format_spec constructed as {type(format_spec).__name__}",
                requested="None or a nested JoinedStr",
                fix="repair the backend adapter; never coerce a bare expression",
            )
        return FormattedValueSugar(
            value=self.value.sugar(),
            conversion=conversion,
            format_spec=format_spec.sugar() if format_spec is not None else None,
            site=self.fragment,
        )


class JoinedStr(Expression):
    values: Tuple[Expression, ...]
    _child_fields = ("values",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """The f-string: JoinedStrSugar over each part's sugar (literal chunks
        and {value} interpolations), concatenated."""
        from sugar_lift_py_tests.sugar.fstring_sugar import JoinedStrSugar

        return JoinedStrSugar(
            parts=tuple(v.sugar() for v in self.values), site=self.fragment
        )


class Constant(Expression):
    value: object
    literal_kind: Optional[str]

    def substitute(self, scope):
        """A literal is inert: no children, no hole, so it substitutes to
        itself under any scope. The terminus of the rewrite."""
        return self

    def _construct_sugar(self):
        """A literal constructs its literal sugar directly — a leaf: no child
        sugar, the value stands. Dispatch on the value's exact type (bool is a
        subclass of int, so it is checked first and is its own sugar). Every
        literal kind not yet converted inherits the loud SugarNotWritten throw.
        """
        v = self.value
        if v is None:
            from sugar_lift_py_tests.sugar.none_literal_sugar import NoneLiteralSugar

            return NoneLiteralSugar(site=self.fragment)
        if isinstance(v, bool):
            if v:
                from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                    TrueBoolLiteralSugar,
                )

                return TrueBoolLiteralSugar(site=self.fragment)
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )

            return FalseBoolLiteralSugar(site=self.fragment)
        if isinstance(v, int):
            from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar

            return IntLiteralSugar(value=v, site=self.fragment)
        if type(v) is float:
            from sugar_lift_py_tests.sugar.real_literal_sugar import RealLiteralSugar

            return RealLiteralSugar(value=v, site=self.fragment)
        if type(v) is str:
            from sugar_lift_py_tests.sugar.string_literal_sugar import (
                StringLiteralSugar,
            )

            return StringLiteralSugar(value=v, site=self.fragment)
        if type(v) is bytes:
            from sugar_lift_py_tests.sugar.bytes_literal_sugar import (
                BytesLiteralSugar,
            )

            return BytesLiteralSugar(value=v, site=self.fragment)
        if v is Ellipsis:
            from sugar_lift_py_tests.sugar.ellipsis_literal_sugar import (
                EllipsisLiteralSugar,
            )

            return EllipsisLiteralSugar(site=self.fragment)
        if type(v) is complex:
            from sugar_lift_py_tests.sugar.complex_literal_sugar import (
                ComplexLiteralSugar,
            )

            return ComplexLiteralSugar(real=v.real, imag=v.imag, site=self.fragment)
        return super()._construct_sugar()  # every literal kind is now converted


class OpaqueObjectStateV1(Expression):
    """Authenticated opaque call-result identity with no field testimony."""

    object_coordinate: object
    base: Expression
    _child_fields = ("base",)

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        """Identity is transparent until a consumer asks for unproved behavior."""
        from .object_identity import decode_object_coordinate_v1

        decode_object_coordinate_v1(self.object_coordinate.wire())
        return self.base.sugar()


class ObjectPlaceStateV1(Expression):
    """Immutable field versions carried only inside runtime BindingEntryV1.

    This is a constructed Node value, not a binding resolver or heap.  Its sole
    identity source is the owning entry's BindingCoordinateV1.  If it escapes
    the attribute store/read projections, its base value constructs normally.
    """

    object_coordinate: object
    class_definition_cid: str
    construction_testimony: object
    constructed_value: object
    object_identity_cid: str
    base: Expression
    selectors: Tuple[object, ...]
    values: Tuple[Expression, ...]
    value_testimonies: Tuple[object, ...]
    version_cids: Tuple[str, ...]
    version_records: Tuple[object, ...]
    prior_version_cids: Tuple[Optional[str], ...]
    store_occurrence_cids: Tuple[str, ...]
    invalidated_by_opaque_call: bool
    _child_fields = ("base", "values")

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        self.validate_identity()
        from sugar_lift_py_tests.sugar.constructed_object_place_sugar import (
            ConstructedObjectPlaceSugar,
        )

        return ConstructedObjectPlaceSugar(
            self.constructed_value,
            self.construction_testimony,
            self.fragment,
        )

    def validate_identity(self) -> None:
        from .binding_provenance import (
            BindingProvenanceGap,
            ConstructedValueTestimonyV1,
        )
        from .object_identity import decode_object_coordinate_v1

        coordinate = decode_object_coordinate_v1(self.object_coordinate.wire())
        ConstructedValueTestimonyV1.decode(self.construction_testimony.wire())
        from sugar_lift_py_tests.ir import _term_content_cid

        observed = _term_content_cid(
            self.constructed_value.to_term(owner="ObjectPlaceStateV1")
        )
        if observed != self.construction_testimony.semantic_value_cid:
            raise BindingProvenanceGap("object construction testimony mismatch")
        if coordinate.cid != self.object_identity_cid:
            raise BindingProvenanceGap("object place identity CID mismatch")

    def version(self, selector) -> Optional[str]:
        try:
            return self.version_cids[self.selectors.index(selector)]
        except ValueError:
            return None

    def with_attribute_store(self, name, value, occurrence):
        from .object_identity import AttributeFieldCoordinateV1

        return self._with_store(AttributeFieldCoordinateV1.mint(self.object_coordinate, name), value, occurrence)

    def _with_store(self, selector, value, occurrence, *, constructed=None):
        self.validate_identity()
        constructed = constructed or Assign._constructed_floor_value(value)
        if constructed is None:
            return None
        floor_value, testimony = constructed
        projected = ConstructedValueProjectionV1.create(
            value, floor_value, testimony
        )
        from .object_identity import AttributeFieldVersionV1

        prior = self.version(selector)
        version = AttributeFieldVersionV1.mint(
            owner=self.object_coordinate,
            field=selector,
            store_occurrence=occurrence,
            construction_generation=self.object_coordinate.construction_generation + len(self.version_cids) + 1,
            stored_value_testimony_cid=testimony.cid,
            prior_version_cid=prior,
        )
        occurrence_memento = occurrence.seal().to_dict()
        selectors = list(self.selectors)
        values = list(self.values)
        testimonies = list(self.value_testimonies)
        versions = list(self.version_cids)
        records = list(self.version_records)
        priors = list(self.prior_version_cids)
        occurrences = list(self.store_occurrence_cids)
        if selector in selectors:
            index = selectors.index(selector)
            values[index] = projected
            testimonies[index] = testimony
            versions[index] = version.cid
            records[index] = version
            priors[index] = prior
            occurrences[index] = occurrence_memento
        else:
            selectors.append(selector)
            values.append(projected)
            testimonies.append(testimony)
            versions.append(version.cid)
            records.append(version)
            priors.append(prior)
            occurrences.append(occurrence_memento)
        return self._replace_state(
            span=occurrence.node.span,
            selectors=tuple(selectors),
            values=tuple(values),
            value_testimonies=tuple(testimonies),
            version_cids=tuple(versions),
            version_records=tuple(records),
            prior_version_cids=tuple(priors),
            store_occurrence_cids=tuple(occurrences),
            invalidated=False,
        )

    def attribute_field(self, name: str):
        from .object_identity import AttributeFieldCoordinateV1

        return self.field(AttributeFieldCoordinateV1.mint(self.object_coordinate, name))

    def field(self, selector):
        self.validate_identity()
        if self.invalidated_by_opaque_call:
            return None
        try:
            index = self.selectors.index(selector)
        except ValueError:
            return None
        from .binding_provenance import (
            BindingProvenanceGap,
            ConstructedValueTestimonyV1,
        )
        from .object_identity import AttributeFieldVersionV1

        testimony = self.value_testimonies[index]
        ConstructedValueTestimonyV1.decode(testimony.wire())
        projected = self.values[index]
        if not isinstance(projected, ConstructedValueProjectionV1):
            raise BindingProvenanceGap("field value lacks constructed projection")
        projected.validate_testimony()
        if projected.construction_testimony != testimony:
            raise BindingProvenanceGap("field value testimony mismatch")
        version = AttributeFieldVersionV1.decode(self.version_records[index].wire())
        if (
            version.cid != self.version_cids[index]
            or version.owner.cid != self.object_coordinate.cid
            or version.field != selector
            or version.stored_value_testimony_cid != testimony.cid
            or version.prior_version_cid != self.prior_version_cids[index]
        ):
            raise BindingProvenanceGap("field version CID mismatch")
        return projected

    def invalidate(self, occurrence):
        self.validate_identity()
        return self._replace_state(
            span=occurrence.node.span,
            selectors=self.selectors,
            values=self.values,
            value_testimonies=self.value_testimonies,
            version_cids=self.version_cids,
            version_records=self.version_records,
            prior_version_cids=self.prior_version_cids,
            store_occurrence_cids=self.store_occurrence_cids,
            invalidated=True,
        )

    def _replace_state(
        self,
        *,
        span,
        selectors,
        values,
        value_testimonies,
        version_cids,
        version_records,
        prior_version_cids,
        store_occurrence_cids,
        invalidated,
    ):
        from .backend import Child, Children, Leaf, materialize
        from .shadow import ShadowNode, _handle_of

        return materialize(
            self.unit,
            ShadowNode(
                "ObjectPlaceStateV1",
                span,
                (
                    ("object_coordinate", Leaf(self.object_coordinate)),
                    ("class_definition_cid", Leaf(self.class_definition_cid)),
                    ("construction_testimony", Leaf(self.construction_testimony)),
                    ("constructed_value", Leaf(self.constructed_value)),
                    ("object_identity_cid", Leaf(self.object_identity_cid)),
                    ("base", Child(_handle_of(self.base))),
                    ("selectors", Leaf(selectors)),
                    ("values", Children(tuple(_handle_of(item) for item in values))),
                    ("value_testimonies", Leaf(value_testimonies)),
                    ("version_cids", Leaf(version_cids)),
                    ("version_records", Leaf(version_records)),
                    ("prior_version_cids", Leaf(prior_version_cids)),
                    ("store_occurrence_cids", Leaf(store_occurrence_cids)),
                    ("invalidated_by_opaque_call", Leaf(invalidated)),
                ),
            ),
            self.reporter,
        )


class ConstructedValueProjectionV1(Expression):
    """A source value already constructed once and sealed by its testimony."""

    constructed_value: object
    construction_testimony: object
    base: Expression
    _child_fields = ("base",)

    @classmethod
    def create(cls, base, constructed_value, testimony):
        from .backend import Child, Leaf, materialize
        from .shadow import ShadowNode, _handle_of

        return materialize(
            base.unit,
            ShadowNode(
                "ConstructedValueProjectionV1",
                base.span,
                (
                    ("constructed_value", Leaf(constructed_value)),
                    ("construction_testimony", Leaf(testimony)),
                    ("base", Child(_handle_of(base))),
                ),
            ),
            base.reporter,
        )

    def substitute(self, scope):
        del scope
        return self

    def validate_testimony(self):
        from .binding_provenance import (
            BindingProvenanceGap,
            ConstructedValueTestimonyV1,
        )
        from sugar_lift_py_tests.ir import _term_content_cid

        ConstructedValueTestimonyV1.decode(self.construction_testimony.wire())
        observed = _term_content_cid(
            self.constructed_value.to_term(owner="ConstructedValueProjectionV1")
        )
        if observed != self.construction_testimony.semantic_value_cid:
            raise BindingProvenanceGap("constructed field testimony mismatch")

    def _construct_sugar(self):
        self.validate_testimony()
        from sugar_lift_py_tests.sugar.constructed_object_place_sugar import (
            ConstructedObjectPlaceSugar,
        )

        return ConstructedObjectPlaceSugar(
            self.constructed_value,
            self.construction_testimony,
            self.fragment,
        )


class Attribute(Expression):
    value: Expression
    attr: str
    _child_fields = ("value",)

    def _construct_sugar(self):
        """`<value>.<attr>` constructs AttributeSugar WITH the receiver's sugar.
        The attr name is a static identifier carried onto the coordinate."""
        if isinstance(self.value, OpaqueObjectStateV1):
            return super()._construct_sugar()
        from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar

        return AttributeSugar(
            receiver=self.value.sugar(), name=self.attr, site=self.fragment
        )

    def substitute(self, scope):
        """Project only from a construction-authenticated object place."""
        from .shadow import rewrite

        receiver, changed = self._substitute_field(self.value, scope)
        if (
            isinstance(receiver, IfExp)
            and isinstance(receiver.body, ObjectPlaceStateV1)
            and isinstance(receiver.orelse, ObjectPlaceStateV1)
            and receiver.body.object_identity_cid
            == receiver.orelse.object_identity_cid
        ):
            when_true = receiver.body.attribute_field(self.attr)
            when_false = receiver.orelse.attribute_field(self.attr)
            if when_true is not None and when_false is not None:
                return rewrite(
                    receiver, body=when_true, orelse=when_false
                )
        if isinstance(receiver, ObjectPlaceStateV1):
            projected = receiver.attribute_field(self.attr)
            if projected is not None:
                return projected
        return self if not changed else rewrite(self, value=receiver)


class Subscript(Expression):
    value: Expression
    slice_: Expression
    _child_fields = ("value", "slice_")

    def substitute(self, scope):
        """`<value>[<slice>]` binds nothing: recurse into receiver and index."""
        from .shadow import rewrite

        receiver, receiver_changed = self._substitute_field(self.value, scope)
        index, index_changed = self._substitute_field(self.slice_, scope)
        if not receiver_changed and not index_changed:
            return self
        return rewrite(self, value=receiver, slice_=index)

    def _construct_sugar(self):
        """`<value>[<slice_>]` constructs SubscriptSugar WITH the receiver's and
        index's sugars. A Slice index reduces to its own gap through the
        recursion (slice_.sugar()), never silently handled here."""
        from sugar_lift_py_tests.sugar.subscript_sugar import SubscriptSugar

        return SubscriptSugar(
            receiver=self.value.sugar(),
            index=self.slice_.sugar(),
            site=self.fragment,
        )


class Starred(Expression):
    value: Expression
    _child_fields = ("value",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)


class Name(Expression):
    id: str

    def substitute(self, scope: BindingMap) -> "Node":
        # A name resolves to its bound node, or stands unbound. This is the
        # whole substitution base case — it returns an EXISTING node, so it
        # needs no synthetic construction.
        bound = scope.get(self.id, _MISSING)
        if bound is _MISSING:
            return self
        bound = unwrap_binding_state(bound)
        if isinstance(bound, Node):
            return bound
        return self._make_binding_read(bound)

    def _make_binding_read(self, state: BindingState) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "GuardedBindingRead",
                self.span,
                (("name", Leaf(self.id)), ("state", Leaf(state))),
            ),
            self.reporter,
        )

    def _construct_sugar(self):
        """A name constructs NameSugar with its identifier. A name is a leaf:
        nothing to build from children, only to look up against the temporal
        scope when the body reduces (an unbound name panics there, loudly)."""
        from sugar_lift_py_tests.sugar.name_sugar import NameSugar

        return NameSugar(name=self.id, site=self.fragment)


class FormalRef(Expression):
    """The declaration-owned authenticated reference for one formal."""

    coordinate: object

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.formal_ref_sugar import FormalRefSugar

        return FormalRefSugar(coordinate=self.coordinate, site=self.fragment)


class BindingCoordinateRef(Expression):
    """Projection of one authenticated formal binding in a source call frame."""

    coordinate: object

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.binding_coordinate_ref_sugar import (
            BindingCoordinateRefSugar,
        )

        return BindingCoordinateRefSugar(self.coordinate, self.fragment)


class ConstructedReceiverRef(Expression):
    """Typed projection of the receiver constructed by this exact class call."""

    class_name: str
    binding_coordinate_cid: str

    def substitute(self, scope):
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.constructed_receiver_ref_sugar import (
            ConstructedReceiverRefSugar,
        )

        return ConstructedReceiverRefSugar(
            self.class_name, self.binding_coordinate_cid, self.fragment
        )


class BranchResultRef(Expression):
    """Projection of the one condition result authenticated by its owning if."""

    slot_id: str

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.branch_result_ref_sugar import (
            BranchResultRefSugar,
        )

        return BranchResultRefSugar(
            slot=BranchResultSlot(self.slot_id), site=self.fragment
        )


def _construct_binding_projection(state):
    from sugar_lift_py_tests.sugar.binding_projection import (
        GuardedProjection,
        UnboundProjection,
    )

    state = unwrap_binding_state(state)
    if isinstance(state, Node):
        return state.sugar()
    if isinstance(state, UnboundBinding):
        return UnboundProjection(state.name, state.cause)
    if isinstance(state, GuardedBinding):
        return GuardedProjection(
            state.slot,
            _construct_binding_projection(state.when_true),
            _construct_binding_projection(state.when_false),
        )
    if isinstance(state, LoopProjectedBinding):
        raise BindingStateWireGap(
            "loop projected binding has CID-only guards; exact guard formula "
            "testimony is required before downstream construction"
        )
    raise TypeError(type(state))


class GuardedBindingRead(Expression):
    """A read-site projection of immutable binding-state testimony."""

    name: str
    state: BindingState

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import (
            GuardedBindingReadSugar,
        )

        return GuardedBindingReadSugar(
            name=self.name,
            state=_construct_binding_projection(self.state),
            site=self.fragment,
        )


class DeleteName(Statement):
    """A plain-name delete carrying its pre-delete availability."""

    name: str
    prior: BindingState

    def substitute(self, scope):
        del scope
        return self

    def substitution_binding(self, scope):
        del scope
        return {self.name: UnboundBinding(name=self.name, cause=self.fragment)}

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.delete_name_sugar import DeleteNameSugar

        return DeleteNameSugar(
            name=self.name,
            prior=_construct_binding_projection(self.prior),
            site=self.fragment,
        )


class DeleteAttribute(Statement):
    receiver: Expression
    attr: str
    _child_fields = ("receiver",)

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.delete_effect_sugar import (
            AttributeDeleteEffectSugar,
        )

        return AttributeDeleteEffectSugar(
            receiver=self.receiver.sugar(), attr=self.attr, site=self.fragment
        )


class DeleteSubscript(Statement):
    receiver: Expression
    index: Expression
    _child_fields = ("receiver", "index")

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.delete_effect_sugar import (
            SubscriptDeleteEffectSugar,
        )

        return SubscriptDeleteEffectSugar(
            receiver=self.receiver.sugar(),
            index=self.index.sugar(),
            site=self.fragment,
        )


class EffectRef(Expression):
    """Preallocated effect coordinate: syntax creates it; routing authenticates.

    Not an exception object and not a floor witness. ``except E as e`` rewrites
    ``e`` to ``EffectRef(slot)`` in the handler only. Routing later associates
    the matched Halted raise payload with that slot — never E().
    """

    slot_id: str

    def substitute(self, scope: "dict[str, Node]") -> "Node":
        # Already a coordinate — never re-captured as a free name.
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.effect_ref_sugar import EffectRefSugar

        return EffectRefSugar(slot_id=self.slot_id, site=self.fragment)


class ManagerRef(Expression):
    """Once-evaluated manager coordinate for resource ``with``.

    Context expression evaluates once; ``ManagerRef(M)`` is the stable
    receiver for ``__enter__`` / ``__exit__`` — never a second evaluation of
    the context expression.
    """

    slot_id: str

    def substitute(self, scope: "dict[str, Node]") -> "Node":
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.resource_coord_sugar import ManagerRefSugar

        return ManagerRefSugar(slot_id=self.slot_id, site=self.fragment)


class ExitTypeRef(Expression):
    """Parametric ``__exit__`` type argument: ``ExitTypeRef(X)``."""

    face_id: str

    def substitute(self, scope: "dict[str, Node]") -> "Node":
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.resource_coord_sugar import ExitTypeRefSugar

        return ExitTypeRefSugar(face_id=self.face_id, site=self.fragment)


class ExitValueRef(Expression):
    """Parametric ``__exit__`` value argument: ``ExitValueRef(X)``."""

    face_id: str

    def substitute(self, scope: "dict[str, Node]") -> "Node":
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.resource_coord_sugar import ExitValueRefSugar

        return ExitValueRefSugar(face_id=self.face_id, site=self.fragment)


class ExitTracebackRef(Expression):
    """Parametric ``__exit__`` traceback argument: ``ExitTracebackRef(X)``."""

    face_id: str

    def substitute(self, scope: "dict[str, Node]") -> "Node":
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.resource_coord_sugar import (
            ExitTracebackRefSugar,
        )

        return ExitTracebackRefSugar(face_id=self.face_id, site=self.fragment)


class ObservationRef(Expression):
    """Contract-declared observation of an effect slot (e.g. ExceptionInfo).

    ``with Expects(...) as ei`` rewrites ``ei`` to ``ObservationRef(slot,
    projection)``. ``.value`` projects the same slot as EffectRef. Projection
    comes from the membrane contract, not from vendor names in the tree.
    """

    slot_id: str
    projection: str  # exception_info | warning_observation | effect | enter_result

    def substitute(self, scope: "dict[str, Node]") -> "Node":
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.effect_ref_sugar import ObservationRefSugar

        return ObservationRefSugar(
            slot_id=self.slot_id,
            projection=self.projection,
            site=self.fragment,
        )


class List(Expression):
    elts: Tuple[Expression, ...]
    _child_fields = ("elts",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`[e, ...]` constructs ListSugar; a spread uses its reference term."""
        from sugar_lift_py_tests.sugar.collection_sugar import ListSugar

        if any(isinstance(e, Starred) for e in self.elts):
            from sugar_lift_py_tests.sugar.spread_sugar import SpreadCollectionSugar

            return SpreadCollectionSugar(
                kind="list",
                elements=tuple(
                    (
                        ("python:starred", e.value.sugar())
                        if isinstance(e, Starred)
                        else (None, e.sugar())
                    )
                    for e in self.elts
                ),
                site=self.fragment,
            )
        return ListSugar(
            elements=tuple(e.sugar() for e in self.elts), site=self.fragment
        )


class Tuple_(Expression):
    elts: Tuple[Expression, ...]
    _child_fields = ("elts",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`(e, ...)` constructs TupleSugar; a spread uses its reference term."""
        from sugar_lift_py_tests.sugar.collection_sugar import TupleSugar

        if any(isinstance(e, Starred) for e in self.elts):
            from sugar_lift_py_tests.sugar.spread_sugar import SpreadCollectionSugar

            return SpreadCollectionSugar(
                kind="tuple",
                elements=tuple(
                    (
                        ("python:starred", e.value.sugar())
                        if isinstance(e, Starred)
                        else (None, e.sugar())
                    )
                    for e in self.elts
                ),
                site=self.fragment,
            )
        return TupleSugar(
            elements=tuple(e.sugar() for e in self.elts), site=self.fragment
        )


# Wire word for tuples is "Tuple"; the class name carries a trailing
# underscore only to avoid shadowing typing.Tuple inside this module.
Tuple_._kind = "Tuple"
KIND_REGISTRY["Tuple"] = KIND_REGISTRY.pop("Tuple_")


class Slice(Expression):
    lower: Optional[Expression]
    upper: Optional[Expression]
    step: Optional[Expression]
    _child_fields = ("lower", "upper", "step")

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`lower:upper:step` constructs SliceSugar; an omitted bound stays None
        (its NoneValue), as Python fills it."""
        from sugar_lift_py_tests.sugar.slice_sugar import SliceSugar

        return SliceSugar(
            lower=None if self.lower is None else self.lower.sugar(),
            upper=None if self.upper is None else self.upper.sugar(),
            step=None if self.step is None else self.step.sugar(),
            site=self.fragment,
        )


# --------------------------------------------------------------------------
# match patterns
# --------------------------------------------------------------------------


class MatchValue(Pattern):
    value: Expression
    _child_fields = ("value",)

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class MatchSingleton(Pattern):
    value: object

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class MatchSequence(Pattern):
    patterns: Tuple[Pattern, ...]
    _child_fields = ("patterns",)

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class MatchMapping(Pattern):
    keys: Tuple[Expression, ...]
    patterns: Tuple[Pattern, ...]
    rest: Optional[str]
    _child_fields = ("keys", "patterns")

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class MatchClass(Pattern):
    cls_: Expression
    patterns: Tuple[Pattern, ...]
    kwd_attrs: Tuple[str, ...]
    kwd_patterns: Tuple[Pattern, ...]
    _child_fields = ("cls_", "patterns", "kwd_patterns")

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class MatchStar(Pattern):
    name: Optional[str]

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class MatchAs(Pattern):
    pattern: Optional[Pattern]
    name: Optional[str]
    _child_fields = ("pattern",)

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class MatchOr(Pattern):
    patterns: Tuple[Pattern, ...]
    _child_fields = ("patterns",)

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


# --------------------------------------------------------------------------
# PEP 695 type parameters
# --------------------------------------------------------------------------


class TypeVar(TypeParam):
    name: str
    bound: Optional[Expression]
    default_value: Optional[Expression] = None  # PEP 696 (3.13+)
    _child_fields = ("bound", "default_value")

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class ParamSpec(TypeParam):
    name: str
    default_value: Optional[Expression] = None  # PEP 696 (3.13+)
    _child_fields = ("default_value",)

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class TypeVarTuple(TypeParam):
    name: str
    default_value: Optional[Expression] = None  # PEP 696 (3.13+)
    _child_fields = ("default_value",)

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


def resolve_kind(kind: str, observed_at: str) -> type[Node]:
    """Two arms: a registered concrete node class, or panic.

    A backend kind with no node class is a MISSING grammar class — the
    conformance finding itself — never a permissive fallback.
    """
    cls = KIND_REGISTRY.get(kind)
    if cls is None or cls in _ABSTRACT:
        vocabulary_missing(
            owner="nodes.resolve_kind",
            observed=f"backend kind {kind!r} at {observed_at} has no node class",
            requested="a concrete Node subclass for every constructible shape",
            fix="add the missing grammar class to nodes.py — never map to a fallback",
        )
        raise AssertionError("unreachable")
    return cls


def _declared_fields(cls: type[Node]) -> Tuple[str, ...]:
    """Annotated accessor names across the class's MRO, base fields excluded."""
    names: list[str] = []
    for klass in reversed(cls.__mro__):
        for name in getattr(klass, "__annotations__", {}):
            if name.startswith("_") or name in ("unit", "ref"):
                continue
            if name not in names:
                names.append(name)
    return tuple(names)
