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

Equality is identity: each build constructs one node per site, so
``a is b`` is the sameness question within a ``SourceFile``. There is no
pool and no interning across files — structural equality across sources
is a CID question, answered by mementos, not by ``__eq__``.

Nodes carry their own fields; nothing is ever written onto a
backend node (no stamping). Synthetic nodes (a future ``assert_with_test``)
are ordinary instances of these classes with no backend handle at all —
the backend contract stays read-only.
"""

from __future__ import annotations

import symtable
from dataclasses import dataclass, field
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
    RuntimeSelectedContextManager,
    SourceTreePanic,
    SubstituteNotWritten,
    SugarNotWritten,
    vocabulary_missing,
)
from .reporter import NULL_REPORTER, AuditReporter
from .spans import LineColSpan, LineTable, Span
from .binding_state import (
    BindingMap,
    BindingState,
    GuardedBinding,
    UnboundBinding,
    join_binding_state,
)


# Scope metadata travels beside temporal bindings under an unforgeable key.
# It lets recognition distinguish a builtin spelling from a lexically bound
# formal without substituting a fake value for that formal.
_LEXICALLY_BOUND_NAMES = object()
_FUNCTION_PARAMETERS = object()
_MISSING = object()


def _explicit_state(name: str, state, make_formal_ref):
    if name in state:
        return state[name]
    if name in state.get(_FUNCTION_PARAMETERS, frozenset()):
        return make_formal_ref(name)
    return _MISSING


@dataclass(frozen=True)
class _ConditionalRaiseRoute:
    test: "Node"
    raised_on_true: bool
    exception_name: str


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

    # populated in __post_init__, never by callers
    line_table: LineTable = field(init=False, default=None)  # type: ignore[assignment]
    module_bound_names: frozenset[str] = field(
        init=False, default_factory=frozenset
    )
    module_symtable: object = field(init=False, default=None)

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
                if symbol.is_assigned()
                or symbol.is_imported()
                or symbol.is_namespace()
            ),
        )

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

    A node holds only its ``unit`` and its backend reference ``ref``.
    Every declared accessor — ``Call.args``, ``FunctionDef.body``, a
    leaf like ``Name.id`` — is a QUERY: resolved through ``ref`` at the
    moment of access, never precomputed and never held between calls.
    The class annotations below each concrete class are the contract the
    backend must satisfy; an accessor the backend cannot answer panics
    loudly at that accessor, naming it — never silence, never a bare
    ``None``.
    """

    unit: SourceUnit
    ref: object  # the BackendNode reference; duck-typed to avoid a cycle
    # The roll call. REQUIRED -- no default -- so a node cannot be constructed
    # off the roll: this is what makes construction complete BY CONSTRUCTION,
    # not by a call someone remembers to make. The constructor registers the
    # node (``__post_init__``); every child this node resolves is constructed
    # with the same reporter, so registration flows through the whole tree.
    reporter: AuditReporter

    # Ordered names of fields holding child nodes (Node, optional
    # Node, or tuple of Node). Leaf values (str/int/...)
    # and operators are NOT children. Declared per class, in grammar order.
    # ClassVar on purpose: never a dataclass field, never instance state.
    _child_fields: ClassVar[Tuple[str, ...]] = ()

    def __post_init__(self) -> None:
        # THE construction event IS the registration. Registering here, in the
        # constructor, means calling ``cls(...)`` at all is showing up on the
        # roll -- there is no way to new a node without it. (register only
        # records the reference; the node's fields stay lazy through ref.)
        self.reporter.register(self)

    def __init_subclass__(cls, **kw: object) -> None:
        super().__init_subclass__(**kw)
        KIND_REGISTRY[cls.__name__] = cls

    def __getattr__(self, name: str):
        # Every annotated field is a query into the backend, answered per
        # access. Unknown names — including an accessor the backend's
        # answer does not cover — panic loudly, naming the accessor.
        if name.startswith("_"):
            raise AttributeError(name)
        for slot_name, slot in self.ref.describe().slots:
            if slot_name == name:
                return slot.resolve(self.unit, self.reporter)
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

    def _make_binop(self, left: "Node", op, right: "Node") -> "Node":
        """Construct a fresh BinOp node ``<left> <op> <right>`` as a shadow that
        borrows this node's span (so it still addresses this source site). Used
        by an augmented assignment to synthesize its ``x OP e`` rebind."""
        from .backend import Child, OpLeaf, materialize
        from .shadow import ShadowNode, _handle_of

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
        """Deterministic slot identity from this binding site's source extent.

        No process identity fallback. If a stable span cannot be produced,
        stay loud — do not invent a nondeterministic coordinate.
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
        return (
            f"{self.unit.filename}:{lc.start_line}:{lc.start_col}:"
            f"{lc.end_line}:{lc.end_col}"
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
                    scope = {**scope, **binding}
                # walrus bindings nested in the statement's expressions leak out
                # to the enclosing block (their scope is the containing function).
                for node in produced_stmt.walk():
                    if node.kind == "NamedExpr":
                        wb = node.substitution_binding(scope)
                        if wb:
                            scope = {**scope, **wb}
            if isinstance(new_stmt, _Splice) and new_stmt.bindings:
                scope = {**scope, **new_stmt.bindings}
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
        """Substitute the context expr; optional_vars is a binding site."""
        from .shadow import rewrite

        new_ctx, d = self._substitute_field(self.context_expr, scope)
        return self if not d else rewrite(self, context_expr=new_ctx)

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
        body_scope = {
            **body_scope,
            **{
                name: UnboundBinding(name=name, cause=self.fragment)
                for name in locals_
            },
            _LEXICALLY_BOUND_NAMES: frozenset(inherited_bound) | bound | locals_,
            _FUNCTION_PARAMETERS: parameters,
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
                substituted = self.substitute({})
            with reduction_span(sugar="Construct", role="construction", site=where):
                return FunctionUniverseSugar(
                    name=self.name,
                    formals=tuple(p.name for p in self.params),
                    statements=tuple(stmt.sugar() for stmt in substituted.body),
                    site=self.fragment,
                )


class AsyncFunctionDef(Statement):
    name: str
    params: Tuple[Param, ...]
    body: Tuple[Statement, ...]
    decorators: Tuple[Expression, ...]
    returns: Optional[Expression]
    type_params: Tuple[TypeParam, ...]
    _child_fields = ("decorators", "type_params", "params", "returns", "body")

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
        """A plain name delete captures availability without loading its target."""
        if len(self.targets) != 1 or not isinstance(self.targets[0], Name):
            return self._substitute_children(scope)
        target = self.targets[0]
        prior = _explicit_state(
            target.id,
            scope,
            lambda name: self._make_formal_ref(name, target.span),
        )
        if prior is _MISSING:
            prior = UnboundBinding(name=target.id, cause=target.fragment)
        return self._make_delete_name(target.id, prior)

    def _make_formal_ref(self, name: str, span: Span) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode("FormalRef", span, (("name", Leaf(name)),)),
            self.reporter,
        )

    def _make_delete_name(self, name: str, prior: BindingState) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "DeleteName",
                self.span,
                (("name", Leaf(name)), ("prior", Leaf(prior))),
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
        if not changed:
            return self
        return rewrite(self, value=new_value)

    def _destructured_binding(self):
        # `a, b = <display>` -- a single Tuple/List target of plain Names,
        # destructured against the already-substituted rhs when it is a
        # Tuple/List display of the same arity. Starred/nested targets, an
        # arity mismatch, or a non-display rhs return None here (mirrors
        # For._target_bindings_for -- the shared destructuring reader, called
        # class-explicitly so it never depends on `self` being a For).
        target = self.targets[0]
        if not isinstance(target, (Tuple_, List)):
            return None
        return For._target_bindings_for(self, target, self.value)

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
            return self._destructured_binding()
        if all(isinstance(t, Name) for t in self.targets):
            return {t.id: self.value for t in self.targets}
        return None

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
            from sugar_lift_py_tests.sugar.assign_sugar import MultiAssignSugar

            return MultiAssignSugar(
                bindings=tuple((t.id, self.value.sugar()) for t in self.targets),
                site=self.fragment,
            )

        if len(self.targets) == 1 and isinstance(self.targets[0], Attribute):
            from sugar_lift_py_tests.sugar.store_effect_sugar import (
                AttributeStoreEffectSugar,
            )

            return AttributeStoreEffectSugar(
                attr=self.targets[0].attr,
                site=self.fragment,
            )

        if len(self.targets) == 1 and isinstance(self.targets[0], Subscript):
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
        return self if not d else rewrite(self, value=new_value)

    def substitution_binding(self, scope):
        # `x OP= e` rebinds x to `x OP e`, reading the OLD x from the scope
        # (or the target itself if x was free). Only a plain Name target binds.
        if not isinstance(self.target, Name):
            return None
        name = self.target.id
        old = scope.get(name, self.target)
        return {name: self._make_binop(old, self.op, self.value)}

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
            from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

            return InertSugar(site=self.fragment)
        if isinstance(self.target, Attribute):
            from sugar_lift_py_tests.sugar.store_effect_sugar import (
                AttributeStoreEffectSugar,
            )

            return AttributeStoreEffectSugar(
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
        binding is introduced, nothing happens at runtime at all.

        The annotation itself is NEVER a fact the meaning layer states either
        way: Python does not check it at runtime (no TypeError on mismatch),
        so an annotation asserts nothing -- it is documentation the tree
        passes through, never a stated post. A valued attribute/subscript target
        is the same runtime store owned by Assign. A bare non-Name annotation
        stays loud: evaluating that target is not an inert name declaration."""
        if isinstance(self.target, Name):
            from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

            return InertSugar(site=self.fragment)
        if self.value is not None and isinstance(self.target, Attribute):
            from sugar_lift_py_tests.sugar.store_effect_sugar import (
                AttributeStoreEffectSugar,
            )

            return AttributeStoreEffectSugar(
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
        concrete = (
            self.target.kind in ("Name", "Tuple", "List")
            and not self._body_has_loop_control()
        )
        elements = self._concrete_elements(subst_iter) if concrete else None
        if elements is not None and len(elements) > self._UNROLL_FUEL:
            elements = None  # past the unroll budget: the fold/universal stands
        if elements is not None:
            bindings = [self._target_bindings(e) for e in elements]
            if all(b is not None for b in bindings):
                target_names = self._bound_names_in(self.target)
                unrolled: list = []
                carried = dict(scope)  # carries loop variables across iterations
                for element_bindings in bindings:
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
                    else_body, _c = self._substitute_body(self.orelse, carried)
                    unrolled.extend(else_body)
                return _Splice(tuple(unrolled))

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
        """The carried fold's binding for the rest of the block. A symbolic loop
        `total = total OP x` over `xs` rebinds `total`, for the tail, to the fold
        coordinate `py.fold.<op>(init, xs)` -- a REFERENCE the dig resolves, the
        same shape as a recursion's `call:f(...)`, not an opaque dead-end. So
        `return total` after the loop becomes `return py.fold.add(0, xs)`. A
        concrete iterable never reaches here (it unrolled via _Splice); only the
        symbolic single-accumulator `var = var OP x` shape is a fold today."""
        if self._concrete_elements(self.iter) is not None:
            return None  # concrete unrolled in substitute
        if self.orelse or self.target.kind != "Name":
            return None
        carried, facts = self._carried_and_facts()
        if facts or len(carried) != 1:
            return None  # accumulator+assert, or multi/zero carried -- not a fold
        assign = carried[0]
        if assign.kind != "Assign" or len(assign.targets) != 1:
            return None
        name = assign.targets[0]
        if name.kind != "Name":
            return None
        value = assign.value
        # value must be `<name> OP <expr involving the loop target>`.
        if (
            value.kind != "BinOp"
            or value.left.kind != "Name"
            or value.left.id != name.id
        ):
            return None
        init = scope.get(name.id)
        if init is None:
            return None  # no pre-loop value to seed the fold
        op = value.op.kind
        fold = self._make_call(self._make_name(f"py.fold.{op}"), (init, self.iter))
        return {name.id: fold}

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
        """A loop that did NOT dissolve in substitute is symbolic: its iterable is
        a hole (a formal), so it cannot unroll. Its meaning is the FOL that was
        always there. An assert-only body is the degenerate fold -- the universal
        `forall x in xs: P(x)` (ForUniversalSugar). A PURE-fold body (only carried
        assignments) states no fact of its own: the fold rides its
        substitution_binding into the tail, so the loop itself is inert here. A
        body with BOTH a carried accumulator and asserts (the accumulator-
        referencing case) and a tuple target / else stay loud until written."""
        from sugar_lift_py_tests.sugar.for_universal_sugar import ForUniversalSugar

        if self.orelse or self.target.kind != "Name":
            return super()._construct_sugar()
        carried, facts = self._carried_and_facts()
        if carried and facts:
            return super()._construct_sugar()  # accumulator-referencing assert -- point 3
        if carried:
            # Pure fold: the loop states nothing; its meaning is the fold binding
            # (substitution_binding), consumed where the carried name is read.
            from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

            return InertSugar(site=self.fragment)
        return ForUniversalSugar(
            target=self.target.id,
            iterable=self.iter.sugar(),
            body=tuple(s.sugar() for s in self.body),
            site=self.fragment,
        )

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
        if For._body_has_loop_control(self):
            return None  # a jump-bearing body is not a plain unroll
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
        test = new_test if d else self.test
        new_body, d, then_net = self._substitute_body_tracked(self.body, scope)
        if d:
            changed["body"] = new_body
        new_orelse, d, else_net = self._substitute_body_tracked(self.orelse, scope)
        if d:
            changed["orelse"] = new_orelse
        node = self if not changed else rewrite(self, **changed)

        names = set(then_net) | set(else_net)
        phis = []
        availability: BindingMap = {}
        for name in sorted(names):
            incoming = _explicit_state(
                name,
                scope,
                lambda spelling: self._make_formal_ref(spelling),
            )
            then_val = then_net.get(name, incoming)
            else_val = else_net.get(name, incoming)
            if then_val is _MISSING or else_val is _MISSING:
                continue
            joined = join_binding_state(
                test=test,
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

    def _make_formal_ref(self, name: str) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode("FormalRef", self.span, (("name", Leaf(name)),)),
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

    def _make_ifexp(self, test: "Node", body: "Node", orelse: "Node") -> "Node":
        """Synthesize ``<body> if <test> else <orelse>`` as a shadow IfExp that
        borrows this if's span (so the phi still addresses this source site)."""
        from .backend import Child, materialize
        from .shadow import ShadowNode, _handle_of

        slots = (
            ("body", Child(_handle_of(body))),
            ("test", Child(_handle_of(test))),
            ("orelse", Child(_handle_of(orelse))),
        )
        return materialize(
            self.unit, ShadowNode("IfExp", self.span, slots), self.reporter
        )

    def _construct_sugar(self):
        """`if <test>: <body> [else: <orelse>]` constructs IfSugar -- the guard.
        The test recognizes itself; each branch's statements recognize themselves.
        The guard turns each branch's stated facts into implications; the binding
        phi is substitute's job, never this."""
        from sugar_lift_py_tests.sugar.if_sugar import IfSugar

        return IfSugar(
            test=self.test.sugar(),
            then_body=tuple(s.sugar() for s in self.body),
            else_body=tuple(s.sugar() for s in self.orelse),
            site=self.fragment,
        )


class With(Statement):
    items: Tuple[WithItem, ...]
    body: Tuple[Statement, ...]
    _child_fields = ("items", "body")

    def _construct_sugar(self):
        """`with <manager> [as <name>]: <body>` -- the node consults the
        MEMBRANE, never a vendor name (#5994). A single manager whose
        membrane-issued contract is raise/warning Expects/Suppresses wires
        through the shared effect router (WithContractSugar). Plain ``as
        <Name>`` is admitted for Expects (step 5: matched-effect witness bound
        for the tail via substitution_binding).

        Unauthenticated managers stay LOUD as ``RuntimeSelectedContextManager``
        unless a SourceOracle-backed ``ExitDispositionProof`` proves every
        completed ``__exit__`` return is exact None/False (incl. implicit None)
        → ``NeverSuppresses`` via ``WithResourceSugar``. Generator CMs and
        builtins (``open``) stay RuntimeSelected until their separate proofs.
        Non-Name as-targets, Suppresses+as, and multiple managers stay loud."""
        if len(self.items) != 1:
            return super()._construct_sugar()
        item = self.items[0]
        as_name = None
        if item.optional_vars is not None:
            # ``as <Name>`` only: substitute already rewrote loads to
            # ObservationRef(slot). Non-Name targets stay loud.
            if item.optional_vars.kind != "Name":
                return super()._construct_sugar()
            as_name = item.optional_vars.id
        from sugar_lift_py_tests.context_manager_contract import (
            Expects,
            NeverSuppresses,
            RuntimeSelected,
            Suppresses,
        )
        from sugar_lift_py_tests.manifest_membrane import (
            contract_for_manager,
            default_community_manifest,
        )
        from sugar_lift_py_tests.sugar.with_contract_sugar import WithContractSugar
        from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar

        contract = contract_for_manager(
            default_community_manifest(), item.context_expr
        )
        if isinstance(contract, (Expects, Suppresses)):
            if contract.matcher.kind not in ("raise", "warning"):
                return super()._construct_sugar()
            # Suppresses+as is not a routed observation surface — stay loud.
            if as_name is not None and not isinstance(contract, Expects):
                return super()._construct_sugar()
            slot_id = None
            if as_name is not None and isinstance(contract, Expects):
                slot_id = item._effect_slot_id()
            return WithContractSugar(
                contract=contract,
                body=tuple(stmt.sugar() for stmt in self.body),
                site=self.fragment,
                slot_id=slot_id,
            )
        def _resource_sugar(disposition):
            manager_slot = item._manager_slot_id()
            enter_node = item._make_enter_call()
            exit_node = item._make_parametric_exit_call()
            enter_slot = (
                f"{manager_slot}#enter_result" if as_name is not None else None
            )
            return WithResourceSugar(
                manager=item.context_expr.sugar(),
                manager_slot_id=manager_slot,
                enter=enter_node.sugar(),
                exit=exit_node.sugar(),
                exit_face_id=item._exit_face_id(),
                body=tuple(stmt.sugar() for stmt in self.body),
                disposition=disposition,
                enter_slot_id=enter_slot,
                site=self.fragment,
            )

        if isinstance(contract, NeverSuppresses):
            # Membrane-issued NeverSuppresses (if ever enrolled) uses resource path.
            return _resource_sugar(contract)

        # Unauthenticated / RuntimeSelected: try source-visible __exit__ proof
        # before the named residual. Generator CMs (switchdir) stay loud here.
        if contract is None or isinstance(contract, RuntimeSelected):
            from sugar_lift_py_tests.exit_disposition_proof import (
                prove_exit_disposition_from_manager_expr,
            )

            proof = prove_exit_disposition_from_manager_expr(item.context_expr)
            if proof is not None and proof.kind == "never_suppresses":
                return _resource_sugar(proof.disposition())

            where = f"{self.unit.filename}"
            try:
                lc = self.line_col_span()
                where = f"{self.unit.filename}:{lc.start_line}:{lc.start_col}"
            except SourceTreePanic:
                pass
            panic = RuntimeSelectedContextManager(
                owner="With.sugar",
                observed=(
                    "unauthenticated context manager — exit suppression "
                    f"runtime-selected at {where}"
                ),
                requested=(
                    "a typed exit contract (NeverSuppresses from source-visible "
                    "__exit__ proof, or Expects/Suppresses via the membrane)"
                ),
                fix=(
                    "prove every completed __exit__ return is exact None/False "
                    "(incl. implicit None); never invent a normal-path-only expansion"
                ),
            )
            self.reporter.report_gap(self, panic)
            raise panic
        return super()._construct_sugar()

    def substitute(self, scope):
        """with ... as <Name>: rewrite name → ObservationRef(slot, projection).

        Projection comes from membrane Expects.binding or resource
        ENTER_RESULT under NeverSuppresses. Syntax creates the coordinate;
        routing/enter authenticates the slot.
        """
        from .shadow import rewrite
        from sugar_lift_py_tests.context_manager_contract import (
            ENTER_RESULT,
            Expects,
            NeverSuppresses,
        )
        from sugar_lift_py_tests.manifest_membrane import (
            contract_for_manager,
            default_community_manifest,
        )

        changed = {}
        new_items, d = self._substitute_field(self.items, scope)
        if d:
            changed["items"] = new_items
        items = new_items if d else self.items

        body_scope = dict(scope)
        for item in items:
            if item.optional_vars is None or item.optional_vars.kind != "Name":
                # Non-Name as-targets: mask only (no coordinate invented).
                if item.optional_vars is not None:
                    for n in self._bound_names_in(item.optional_vars):
                        body_scope.pop(n, None)
                continue
            contract = contract_for_manager(
                default_community_manifest(), item.context_expr
            )
            slot_id = item._effect_slot_id()
            if isinstance(contract, Expects) and contract.binding:
                ref = item._make_observation_ref(slot_id, contract.binding)
                body_scope[item.optional_vars.id] = ref
                continue
            if isinstance(contract, NeverSuppresses):
                # Enter-result slot is distinct from manager slot.
                enter_slot = f"{item._manager_slot_id()}#enter_result"
                ref = item._make_observation_ref(enter_slot, ENTER_RESULT)
                body_scope[item.optional_vars.id] = ref
                continue
            # Unauthenticated / suppresses: mask the name, stay without ref.
            body_scope.pop(item.optional_vars.id, None)

        new_body, d = self._substitute_body(self.body, body_scope)
        if d:
            changed["body"] = new_body
        return self if not changed else rewrite(self, **changed)

    def substitution_binding(self, scope):
        """Export ObservationRef for Expects / resource enter-result as-names."""
        from sugar_lift_py_tests.context_manager_contract import (
            ENTER_RESULT,
            Expects,
            NeverSuppresses,
        )
        from sugar_lift_py_tests.manifest_membrane import (
            contract_for_manager,
            default_community_manifest,
        )

        del scope
        exported: dict[str, Node] = {}
        for item in self.items:
            if item.optional_vars is None or item.optional_vars.kind != "Name":
                continue
            contract = contract_for_manager(
                default_community_manifest(), item.context_expr
            )
            slot_id = item._effect_slot_id()
            if isinstance(contract, Expects) and contract.binding:
                exported[item.optional_vars.id] = item._make_observation_ref(
                    slot_id, contract.binding
                )
            elif isinstance(contract, NeverSuppresses):
                enter_slot = f"{item._manager_slot_id()}#enter_result"
                exported[item.optional_vars.id] = item._make_observation_ref(
                    enter_slot, ENTER_RESULT
                )
        return exported or None


class AsyncWith(Statement):
    items: Tuple[WithItem, ...]
    body: Tuple[Statement, ...]
    _child_fields = ("items", "body")

    def substitute(self, scope):
        """Same as With: masks the as-targets for the body."""
        return With.substitute(self, scope)


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
        """Build the raised child and carry it on the function's halt exit."""
        if self.cause is not None:
            # `raise X from Y` -- the cause is exception-chaining provenance, not
            # part of the halt. Carrying it is not written yet, so rather than
            # silently drop it we FAIL LOUDLY (the MISSING-becomes-success this
            # design forbids), exactly as AssertSugar does with its message.
            return super()._construct_sugar()
        from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar

        return RaiseSugar(
            exception=self.exc.sugar() if self.exc is not None else None,
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
                new_value, d = self._substitute_body(
                    getattr(self, field_name), scope
                )
                if d:
                    changed[field_name] = new_value
            return self if not changed else rewrite(self, **changed)

        changed = {}
        new_body, d, body_net = self._substitute_body_tracked(self.body, scope)
        if d:
            changed["body"] = new_body
        body_state = {**scope, **body_net}
        new_orelse, d, else_net = self._substitute_body_tracked(
            self.orelse, body_state
        )
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
                handler
                if not handler_changed
                else rewrite(handler, **handler_changed)
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

        unconditional = self._unconditional_raise_name(self.body)
        conditional = self._conditional_raise(self.body)
        completion_nets = []
        if unconditional is None:
            completion_nets.append(body_completion)
        for handler, handler_net in zip(self.handlers, handler_nets):
            if unconditional is not None:
                include = self._handler_matches(handler, unconditional)
            elif conditional is not None:
                include = self._handler_matches(
                    handler, conditional.exception_name
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

    @staticmethod
    def _handler_matches(handler, exception_name: str) -> bool:
        if handler.type_ is None:
            return True
        nodes = (
            handler.type_.elts
            if isinstance(handler.type_, Tuple_)
            else (handler.type_,)
        )
        return any(Try._except_type_name(node) == exception_name for node in nodes)

    @staticmethod
    def _unconditional_raise_name(statements):
        for statement in statements:
            if isinstance(statement, Raise):
                return statement._exception_name()
            if isinstance(statement, Return):
                return None
            if isinstance(statement, If):
                left = Try._unconditional_raise_name(statement.body)
                right = Try._unconditional_raise_name(statement.orelse)
                if left is not None and left == right:
                    return left
            # The first ordinary statement can complete, so continue scanning.
        return None

    @staticmethod
    def _conditional_raise(statements):
        for statement in statements:
            if not isinstance(statement, If):
                continue
            left = Try._unconditional_raise_name(statement.body)
            right = Try._unconditional_raise_name(statement.orelse)
            if left is not None and right is None:
                return _ConditionalRaiseRoute(
                    test=statement.test,
                    raised_on_true=True,
                    exception_name=left,
                )
            if right is not None and left is None:
                return _ConditionalRaiseRoute(
                    test=statement.test,
                    raised_on_true=False,
                    exception_name=right,
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
            states = [
                net.get(name, _explicit_state(name, scope, self._make_formal_ref))
                for net in nets
            ]
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
                    test=conditional_route.test,
                    when_true=when_true,
                    when_false=when_false,
                    make_ifexp=self._make_ifexp,
                )
                continue
            if all(isinstance(state, UnboundBinding) for state in states):
                merged[name] = states[0]
        return merged

    def _make_formal_ref(self, name: str) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode("FormalRef", self.span, (("name", Leaf(name)),)),
            self.reporter,
        )

    def _make_ifexp(self, test, body, orelse):
        return If._make_ifexp(self, test, body, orelse)

    @staticmethod
    def _except_type_name(type_node):
        """Structural exception type name off an ``except E`` clause: bare
        ``Name`` -> ``"E"``, dotted ``Attribute`` chain -> ``"mod.E"``. Same
        walk as ``Raise._exception_name`` (no desugar, no factory). Tuple types,
        bare ``except:``, and exotic expressions return ``None`` so the sugar
        stays LOUD rather than inventing a matcher."""
        if type_node is None:
            return None
        node = type_node
        parts = []
        while node is not None and node.kind == "Attribute":
            parts.append(node.attr)
            node = node.value
        if node is not None and node.kind == "Name":
            parts.append(node.id)
        if not parts:
            return None
        return ".".join(reversed(parts))

    def _construct_sugar(self):
        """`try: body (except E: handler)+ [else] [finally]` -- the STRUCTURAL
        sibling of with-raises. A typed clause contributes one exact router
        matcher per bare/dotted type (including each element of a tuple); a
        bare clause contributes the widest raise matcher. Exotic type
        expressions and empty tuples stay loud. ``except*`` lives on TryStar
        and stays loud there.

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

        from sugar_lift_py_tests.context_manager_contract import EffectMatcher

        handler_specs = []
        for handler in self.handlers:
            # slot_id for authentication when this arm has `as` (substitute site).
            slot_id = handler._effect_slot_id() if handler.name else None
            body_sugars = tuple(stmt.sugar() for stmt in handler.body)
            if handler.type_ is None:
                handler_specs.append((None, body_sugars, slot_id))
                continue

            type_nodes = (
                handler.type_.elts if handler.type_.kind == "Tuple" else (handler.type_,)
            )
            if not type_nodes:
                return super()._construct_sugar()  # empty tuple: no honest matcher
            for type_node in type_nodes:
                type_name = self._except_type_name(type_node)
                if type_name is None:
                    return super()._construct_sugar()  # exotic tuple elt/type -- stay loud
                handler_specs.append(
                    (
                        EffectMatcher(kind="raise", name=type_name),
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


class Continue(Statement):
    pass

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self


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
                return super()._construct_sugar()  # structural pattern (sequence/class/...)
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

    def _construct_sugar(self):
        """Construct only plain positional-or-keyword expression lambdas.

        Every other binding role remains loud.  The body constructs through its
        own node so an unsupported child preserves that child's exact panic.
        """
        from .shadow import ShadowNode

        if not isinstance(self.ref, ShadowNode) or len(self.params) != 1 or any(
            param.param_kind != "positional_or_keyword"
            or param.default is not None
            or param.annotation is not None
            for param in self.params
        ):
            return super()._construct_sugar()

        from sugar_lift_py_tests.sugar.lambda_sugar import LambdaSugar

        return LambdaSugar(
            formals=tuple(param.name for param in self.params),
            body=self.body.sugar(),
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

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`{k: v, ...}` constructs DictSugar WITH each key and value sugar. A
        `**d` spread (a DictItem with key None) stays loud until its own sugar."""
        from sugar_lift_py_tests.sugar.collection_sugar import DictSugar

        if any(item.key is None for item in self.items):
            return super()._construct_sugar()
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
        """`{e, ...}` constructs SetSugar WITH each element's sugar; `*xs` is loud."""
        from sugar_lift_py_tests.sugar.collection_sugar import SetSugar

        if any(e.kind == "Starred" for e in self.elts):
            return super()._construct_sugar()
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
        unrolled = self._try_unroll_to_display(scope)
        if unrolled is not None:
            return unrolled
        from .shadow import rewrite

        new_gens, inner, gc = self._substitute_generators(self.generators, scope)
        new_elt, de = self._substitute_field(self.elt, inner)
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
            verdicts = []
            for guard in gen.ifs:
                new_guard, changed = self._substitute_field(guard, inner)
                verdict = While._ground_truth(self, new_guard if changed else guard)
                if verdict is None:
                    return None
                verdicts.append(verdict)
            if not all(verdicts):
                continue
            new_elt, _d = self._substitute_field(self.elt, inner)
            results.append(new_elt if _d else self.elt)
        return ListComp._make_list(self, tuple(results))

    def _contains_forbidden_shape(self, roots: tuple) -> bool:
        """True for a nested comprehension or walrus in this comprehension."""
        return any(
            node.kind
            in ("ListComp", "SetComp", "DictComp", "GeneratorExp", "NamedExpr")
            for root in roots
            for node in root.walk()
        )

    def _calls_shadowed_range(self, iterable, scope) -> bool:
        return (
            iterable.kind == "Call"
            and iterable.func.kind == "Name"
            and iterable.func.id == "range"
            and "range" in scope
        ) or (
            iterable.kind == "Call"
            and iterable.func.kind == "Name"
            and iterable.func.id == "range"
            and "range" in scope.get(_LEXICALLY_BOUND_NAMES, ())
        ) or (
            iterable.kind == "Call"
            and iterable.func.kind == "Name"
            and iterable.func.id == "range"
            and "range" in self.unit.module_bound_names
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


class SetComp(Expression):
    elt: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("elt", "generators")

    def substitute(self, scope):
        """A comprehension: thread each generator's target, then substitute the
        element against the scope with every target masked."""
        display = self._try_unroll_to_display(scope)
        if display is not None:
            return display
        from .shadow import rewrite

        new_gens, inner, gc = self._substitute_generators(self.generators, scope)
        new_elt, de = self._substitute_field(self.elt, inner)
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
        if gen.is_async or gen.ifs or ListComp._contains_forbidden_shape(
            self, (gen.iter,)
        ):
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
            new_elt, changed = self._substitute_field(
                self.elt, {**scope, **bindings}
            )
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


class DictComp(Expression):
    key: Expression
    value: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("key", "value", "generators")

    def substitute(self, scope):
        """A dict comprehension: thread the generators, then key and value
        against the scope with every target masked."""
        display = self._try_unroll_to_display(scope)
        if display is not None:
            return display
        from .shadow import rewrite

        new_gens, inner, gc = self._substitute_generators(self.generators, scope)
        changed = {}
        if gc:
            changed["generators"] = new_gens
        for fld in ("key", "value"):
            new, d = self._substitute_field(getattr(self, fld), inner)
            if d:
                changed[fld] = new
        return self if not changed else rewrite(self, **changed)

    def _try_unroll_to_display(self, scope):
        if len(self.generators) != 1 or ListComp._contains_forbidden_shape(
            self, (self.key, self.value)
        ):
            return None
        gen = self.generators[0]
        if gen.is_async or gen.ifs or ListComp._contains_forbidden_shape(
            self, (gen.iter,)
        ):
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


class GeneratorExp(Expression):
    elt: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("elt", "generators")

    def substitute(self, scope):
        """A comprehension: thread each generator's target, then substitute the
        element against the scope with every target masked."""
        from .shadow import rewrite

        new_gens, inner, gc = self._substitute_generators(self.generators, scope)
        new_elt, de = self._substitute_field(self.elt, inner)
        changed = {}
        if gc:
            changed["generators"] = new_gens
        if de:
            changed["elt"] = new_elt
        return self if not changed else rewrite(self, **changed)

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
        keyword_sugars = tuple(
            (kw.arg if kw.arg is not None else "**", kw.value.sugar())
            for kw in self.keywords
        )
        if isinstance(self.func, Name):
            from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar

            return CallSiteSugar(
                target_name=self.func.id,
                args=tuple(a.sugar() for a in self.args),
                site=self.fragment,
                keywords=keyword_sugars,
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

        return ComputedCallSugar(
            callee=self.func.sugar(),
            args=tuple(a.sugar() for a in self.args),
            site=self.fragment,
            keywords=keyword_sugars,
        )


class FormattedValue(Expression):
    value: Expression
    conversion: int
    format_spec: Optional["JoinedStr"]
    _child_fields = ("value", "format_spec")

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`{value}` in an f-string. A conversion (!r/!s/!a) or a format spec is
        not lifted yet -- LOUD rather than a silently dropped modifier."""
        from sugar_lift_py_tests.sugar.fstring_sugar import FormattedValueSugar

        if self.conversion != -1 or self.format_spec is not None:
            return super()._construct_sugar()
        return FormattedValueSugar(value=self.value.sugar(), site=self.fragment)


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


class Attribute(Expression):
    value: Expression
    attr: str
    _child_fields = ("value",)

    def _construct_sugar(self):
        """`<value>.<attr>` constructs AttributeSugar WITH the receiver's sugar.
        The attr name is a static identifier carried onto the coordinate."""
        from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar

        return AttributeSugar(
            receiver=self.value.sugar(), name=self.attr, site=self.fragment
        )

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)


class Subscript(Expression):
    value: Expression
    slice_: Expression
    _child_fields = ("value", "slice_")

    def substitute(self, scope):
        """`<value>[<slice>]` binds nothing: recurse into receiver and index."""
        return self._substitute_children(scope)

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
    """A lazily materialized formal used only when availability becomes explicit."""

    name: str

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.name_sugar import NameSugar

        return NameSugar(name=self.name, site=self.fragment)


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
            name=self.name, state=self.state, site=self.fragment
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

        return DeleteNameSugar(name=self.name, prior=self.prior, site=self.fragment)


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
        """`[e, ...]` constructs ListSugar WITH each element's sugar. A `*xs`
        spread is not one element -- it stays loud until its own sugar lands."""
        from sugar_lift_py_tests.sugar.collection_sugar import ListSugar

        if any(e.kind == "Starred" for e in self.elts):
            return super()._construct_sugar()
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
        """`(e, ...)` constructs TupleSugar WITH each element's sugar; `*xs` is loud."""
        from sugar_lift_py_tests.sugar.collection_sugar import TupleSugar

        if any(e.kind == "Starred" for e in self.elts):
            return super()._construct_sugar()
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
