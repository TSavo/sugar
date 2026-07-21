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
    SourceTreePanic,
    SubstituteNotWritten,
    SugarNotWritten,
    vocabulary_missing,
)
from .reporter import NULL_REPORTER, AuditReporter
from .spans import LineColSpan, LineTable, Span


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_table", LineTable(self.source))


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
    # The audit channel, threaded at construction (backend.materialize) and
    # handed on to every child this node resolves. Off the audit path this is
    # the shared do-nothing NULL_REPORTER; nothing allocates, nothing changes.
    reporter: AuditReporter = NULL_REPORTER

    # Ordered names of fields holding child nodes (Node, optional
    # Node, or tuple of Node). Leaf values (str/int/...)
    # and operators are NOT children. Declared per class, in grammar order.
    # ClassVar on purpose: never a dataclass field, never instance state.
    _child_fields: ClassVar[Tuple[str, ...]] = ()

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
            return new, new is not value
        items = tuple(value)
        new_items = tuple(
            item.substitute(scope) if isinstance(item, Node) else item
            for item in items
        )
        changed = any(new is not old for new, old in zip(new_items, items))
        return (new_items if changed else value), changed

    def _substitute_children(self, scope: "dict[str, Node]") -> "Node":
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

    def substitution_binding(self, scope: "dict[str, Node]") -> "Optional[dict[str, Node]]":
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
        return materialize(self.unit, ShadowNode("BinOp", self.span, slots), self.reporter)

    def _substitute_body(self, statements: tuple, scope: "dict[str, Node]"):
        """Substitute a statement sequence, THREADING each statement's binding:
        an assignment binds its name to its substituted rhs for the rest of the
        block. This is the temporal that used to live in ``ctx.temporal`` -- now
        it is the tree rewriting itself, statement by statement, in single-
        assignment form (each binding a fresh entry; a rebind shadows the old
        for the tail). A walrus (``NamedExpr``) nested anywhere in the statement
        also leaks its binding to the rest of the block. Returns
        ``(new_statements, changed)``."""
        scope = dict(scope)
        new_items = []
        changed = False
        for stmt in statements:
            new_stmt = stmt.substitute(scope)
            if new_stmt is not stmt:
                changed = True
            new_items.append(new_stmt)
            binding = new_stmt.substitution_binding(scope)
            if binding:
                scope = {**scope, **binding}
            # walrus bindings nested inside the statement's expressions leak out
            # to the enclosing block (their scope is the containing function).
            for node in new_stmt.walk():
                if node.kind == "NamedExpr":
                    wb = node.substitution_binding(scope)
                    if wb:
                        scope = {**scope, **wb}
        return (tuple(new_items) if changed else statements), changed

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
            stack.extend(
                child for _, _, child in reversed(list(node.children()))
            )

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

    def sugar(self):
        """A formal stands as its symbolic universe variable. Plain parameters
        only; a default or annotation is not yet folded in, so a parameter that
        carries one stays a loud gap rather than silently dropping it."""
        if self.default is not None or self.annotation is not None:
            return super().sugar()
        from sugar_lift_py_tests.sugar.param_sugar import ParamSugar

        return ParamSugar(name=self.name, site=self.fragment)


class Keyword(Node):
    """A keyword argument at a call site. ``arg is None`` means ``**expr``
    (double-star spread) — a structural absence, not a refusal."""

    arg: Optional[str]
    value: Expression
    _child_fields = ("value",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)


class DictItem(Node):
    """One ``key: value`` entry of a Dict display. ``key is None`` means
    ``**expr`` (double-star spread) — a structural absence, not a refusal."""

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
        ifs_scope = {k: v for k, v in scope.items() if k not in bound} if bound else scope
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
        """except <type> as <name>: binds the exception name for the body."""
        from .shadow import rewrite
        bound = {self.name} if self.name else set()
        bs = {k: v for k, v in scope.items() if k not in bound} if bound else scope
        changed = {}
        new_type, d = self._substitute_field(self.type_, scope)
        if d:
            changed["type_"] = new_type
        new_body, d = self._substitute_body(self.body, bs)
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

    def substitute(self, scope):
        """`case <pattern> [if <guard>]: <body>` -- the pattern captures bind for
        the guard and body. Pattern value-exprs evaluate in the enclosing scope;
        guard and body are masked by the captures (body threaded)."""
        from .shadow import rewrite
        bound = self._pattern_bound_names(self.pattern)
        inner = {k: v for k, v in scope.items() if k not in bound} if bound else scope
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
        `x`, capturing it. Masking is that capture, refused.
        """
        from .shadow import rewrite

        bound = {p.name for p in self.params}
        for tp in self.type_params:
            name = getattr(tp, "name", None)
            if isinstance(name, str):
                bound.add(name)
        body_scope = (
            {k: v for k, v in scope.items() if k not in bound} if bound else scope
        )

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

    def sugar(self):
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
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            FunctionUniverseSugar,
        )

        # Substitute the body against an empty scope: formals are masked (they
        # stay free -> symbolic), locals thread and inline, phis land as IfExps.
        substituted = self.substitute({})
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
        tnames = {n for tp in self.type_params
                  for n in [getattr(tp, "name", None)] if isinstance(n, str)}
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

    def sugar(self):
        """`return <expr>` constructs ReturnSugar WITH the value's sugar. A bare
        `return` (no value) stays a loud gap -- no invented None return."""
        if self.value is None:
            return super().sugar()
        from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar

        return ReturnSugar(value=self.value.sugar(), site=self.fragment)


class Delete(Statement):
    targets: Tuple[Expression, ...]
    _child_fields = ("targets",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)


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

    def substitution_binding(self, scope):
        # A single Name target binds its name to the already-substituted rhs.
        # Tuple / attribute / subscript targets thread nothing yet -- their
        # references stay honest gaps rather than a wrong binding.
        if len(self.targets) == 1 and isinstance(self.targets[0], Name):
            return {self.targets[0].id: self.value}
        return None

    def sugar(self):
        """`<name> = <rhs>` constructs AssignSugar WITH the rhs's sugar (held as
        the deferred source). Single Name target only: tuple/attribute/subscript
        targets and chained `a = b = c` stay loud gaps until their own sugars
        are written -- never a partial binding."""
        if len(self.targets) != 1 or not isinstance(self.targets[0], Name):
            return super().sugar()
        from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar

        return AssignSugar(
            name=self.targets[0].id,
            value=self.value.sugar(),
            site=self.fragment,
        )


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


class TypeAlias(Statement):
    name: Expression
    type_params: Tuple[TypeParam, ...]
    value: Expression
    _child_fields = ("name", "type_params", "value")

    def substitute(self, scope):
        """`type <name>[<params>] = <value>` -- the type params bind for the
        value; the name is a binding site."""
        from .shadow import rewrite
        tnames = {n for tp in self.type_params
                  for n in [getattr(tp, "name", None)] if isinstance(n, str)}
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
        """for <target> in <iter>: binds the loop target for body/orelse."""
        from .shadow import rewrite
        bound = self._bound_names_in(self.target)
        bs = {k: v for k, v in scope.items() if k not in bound} if bound else scope
        changed = {}
        new_iter, d = self._substitute_field(self.iter, scope)
        if d:
            changed["iter"] = new_iter
        for f in ("body", "orelse"):
            new, d = self._substitute_body(getattr(self, f), bs)
            if d:
                changed[f] = new
        return self if not changed else rewrite(self, **changed)


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

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)


class If(Statement):
    test: Expression
    body: Tuple[Statement, ...]
    orelse: Tuple[Statement, ...]
    _child_fields = ("test", "body", "orelse")

    def substitute(self, scope):
        """An if introduces no names into its own scope, but each branch is a
        sub-block that threads its OWN assignments. So: substitute the test, then
        thread each branch body (its within-branch bindings inline), and rebuild.
        What a name binds to AFTER the if is the phi -- that is
        ``substitution_binding``, not this."""
        from .shadow import rewrite

        changed = {}
        new_test, d = self._substitute_field(self.test, scope)
        if d:
            changed["test"] = new_test
        new_body, d = self._substitute_body(self.body, scope)
        if d:
            changed["body"] = new_body
        new_orelse, d = self._substitute_body(self.orelse, scope)
        if d:
            changed["orelse"] = new_orelse
        return self if not changed else rewrite(self, **changed)

    def _branch_bindings(self, statements, scope):
        """The net bindings a branch leaves for the rest of ITS block, threaded
        exactly as ``_substitute_body`` threads a block: each statement's
        ``substitution_binding`` plus any nested walrus. Returns the map of names
        this branch bound to their final substituted values."""
        local = dict(scope)
        touched: "dict[str, Node]" = {}
        for stmt in statements:
            new_stmt = stmt.substitute(local)
            binding = new_stmt.substitution_binding(local)
            if binding:
                local = {**local, **binding}
                touched.update(binding)
            for node in new_stmt.walk():
                if node.kind == "NamedExpr":
                    wb = node.substitution_binding(local)
                    if wb:
                        local = {**local, **wb}
                        touched.update(wb)
        return touched

    def substitution_binding(self, scope):
        """The phi. A name bound in either branch rebinds, for the rest of the
        block, to ``<then value> if <test> else <else value>`` -- an ``IfExp``
        whose two arms are the branches' values and whose test is the condition.
        A name bound in only one branch takes its PRIOR binding in the other arm;
        with no prior binding the other arm would be an invented value, so we
        leave that name an honest gap (unbound) rather than guess."""
        then_binds = self._branch_bindings(self.body, scope)
        else_binds = self._branch_bindings(self.orelse, scope)
        names = set(then_binds) | set(else_binds)
        if not names:
            return None
        test = self.test.substitute(scope)
        result: "dict[str, Node]" = {}
        for name in names:
            then_val = then_binds.get(name, scope.get(name))
            else_val = else_binds.get(name, scope.get(name))
            if then_val is None or else_val is None:
                continue  # bound in one branch, no prior: honest gap, not a guess
            result[name] = self._make_ifexp(test, then_val, else_val)
        return result or None

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
        return materialize(self.unit, ShadowNode("IfExp", self.span, slots), self.reporter)

    def sugar(self):
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

    def substitute(self, scope):
        """with ... as <vars>: binds the as-targets for the body."""
        from .shadow import rewrite
        bound = set()
        for item in self.items:
            if item.optional_vars is not None:
                bound |= self._bound_names_in(item.optional_vars)
        bs = {k: v for k, v in scope.items() if k not in bound} if bound else scope
        changed = {}
        new_items, d = self._substitute_field(self.items, scope)
        if d:
            changed["items"] = new_items
        new_body, d = self._substitute_body(self.body, bs)
        if d:
            changed["body"] = new_body
        return self if not changed else rewrite(self, **changed)


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

    def sugar(self):
        """`raise <exc>[ from <cause>]` constructs RaiseSugar -- the halt arm.
        The exception name is provenance, read structurally; the expression is
        never desugared as a child (we do not construct the exception)."""
        if self.cause is not None:
            # `raise X from Y` -- the cause is exception-chaining provenance, not
            # part of the halt. Carrying it is not written yet, so rather than
            # silently drop it we FAIL LOUDLY (the MISSING-becomes-success this
            # design forbids), exactly as AssertSugar does with its message.
            return super().sugar()
        from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar

        return RaiseSugar(exception_name=self._exception_name(), site=self.fragment)


class Try(Statement):
    body: Tuple[Statement, ...]
    handlers: Tuple[ExceptHandler, ...]
    orelse: Tuple[Statement, ...]
    finalbody: Tuple[Statement, ...]
    _child_fields = ("body", "handlers", "orelse", "finalbody")

    def substitute(self, scope):
        """Binds nothing itself (its handlers mask): recurse."""
        return self._substitute_children(scope)


class TryStar(Statement):
    body: Tuple[Statement, ...]
    handlers: Tuple[ExceptHandler, ...]
    orelse: Tuple[Statement, ...]
    finalbody: Tuple[Statement, ...]
    _child_fields = ("body", "handlers", "orelse", "finalbody")

    def substitute(self, scope):
        """Binds nothing itself (its handlers mask): recurse."""
        return self._substitute_children(scope)


class Assert(Statement):
    test: Expression
    msg: Optional[Expression]
    _child_fields = ("test", "msg")

    def substitute(self, scope):
        """`assert <test>[, <msg>]` binds nothing: recurse into test and msg."""
        return self._substitute_children(scope)

    def sugar(self):
        """`assert <test>[, <msg>]` constructs AssertSugar WITH the test's
        sugar. The test recognizes itself (self.test.sugar()) — the recursion.
        The message is provenance only (#4593/#4594): AssertSugar never builds
        or reduces it, so it is not passed as a child sugar.
        """
        from sugar_lift_py_tests.sugar.assert_sugar import AssertSugar

        if self.msg is not None:
            # The message is provenance (assertMessage on the memento, #4593/
            # #4594) — never a child sugar, but NOT nothing. Carrying it onto
            # the memento is not written yet, so an assert that has one FAILS
            # LOUDLY rather than silently dropping it. Silent loss is the exact
            # MISSING-becomes-success this design forbids.
            return super().sugar()
        return AssertSugar(test=self.test.sugar(), site=self.fragment)


class Import(Statement):
    names: Tuple[ImportAlias, ...]
    _child_fields = ("names",)

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self


class ImportFrom(Statement):
    module: Optional[str]
    names: Tuple[ImportAlias, ...]
    level: int
    _child_fields = ("names",)

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self


class Global(Statement):
    names: Tuple[str, ...]

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self


class Nonlocal(Statement):
    names: Tuple[str, ...]

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self


class Expr(Statement):
    """An expression in statement position."""

    value: Expression
    _child_fields = ("value",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)


class Pass(Statement):
    pass

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self


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
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


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

    def sugar(self):
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

    def sugar(self):
        """`<left> <op> <right>` constructs BinOpSugar WITH both sides' sugars.
        The node already knows its operator, so one sugar dispatches to the
        floor method that operator names. An operator with no floor method is a
        genuine gap -- it inherits the base throw, never a silent default."""
        from sugar_lift_py_tests.sugar.binop_sugar import BINOP_METHODS, BinOpSugar

        if self.op.kind not in BINOP_METHODS:
            return super().sugar()
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

    def sugar(self):
        """`<op> <operand>` constructs UnaryOpSugar WITH the operand's sugar. The
        node already knows its operator; an operator with no floor method inherits
        the base throw, never a silent default."""
        from sugar_lift_py_tests.sugar.unary_op_sugar import (
            UNARYOP_METHODS,
            UnaryOpSugar,
        )

        if self.op.kind != "Not" and self.op.kind not in UNARYOP_METHODS:
            return super().sugar()
        return UnaryOpSugar(
            op_kind=self.op.kind, operand=self.operand.sugar(), site=self.fragment
        )


class Lambda(Expression):
    params: Tuple[Param, ...]
    body: Expression
    _child_fields = ("params", "body")

    def substitute(self, scope):
        """lambda <params>: masks its parameters for the body expression."""
        from .shadow import rewrite
        bound = {p.name for p in self.params}
        bs = {k: v for k, v in scope.items() if k not in bound} if bound else scope
        changed = {}
        new_params, d = self._substitute_field(self.params, scope)
        if d:
            changed["params"] = new_params
        new_body, d = self._substitute_field(self.body, bs)
        if d:
            changed["body"] = new_body
        return self if not changed else rewrite(self, **changed)


class IfExp(Expression):
    test: Expression
    body: Expression
    orelse: Expression
    _child_fields = ("body", "test", "orelse")

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def sugar(self):
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

    def sugar(self):
        """`{k: v, ...}` constructs DictSugar WITH each key and value sugar. A
        `**d` spread (a DictItem with key None) stays loud until its own sugar."""
        from sugar_lift_py_tests.sugar.collection_sugar import DictSugar

        if any(item.key is None for item in self.items):
            return super().sugar()
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

    def sugar(self):
        """`{e, ...}` constructs SetSugar WITH each element's sugar; `*xs` is loud."""
        from sugar_lift_py_tests.sugar.collection_sugar import SetSugar

        if any(e.kind == "Starred" for e in self.elts):
            return super().sugar()
        return SetSugar(
            elements=tuple(e.sugar() for e in self.elts), site=self.fragment
        )


class ListComp(Expression):
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


class SetComp(Expression):
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


class DictComp(Expression):
    key: Expression
    value: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("key", "value", "generators")

    def substitute(self, scope):
        """A dict comprehension: thread the generators, then key and value
        against the scope with every target masked."""
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

    def sugar(self):
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
            return super().sugar()

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

    def sugar(self):
        """`<name>(<args>)` constructs CallSiteSugar WITH the argument sugars.
        The result is a call-site coordinate -- the DIG CUE the enclosing assert
        carries into its InvValue. Plain positional calls to a NAMED callee
        only; method/attribute/computed callees and keyword arguments stay loud
        gaps until their own sugars are written."""
        if not isinstance(self.func, Name) or self.keywords:
            return super().sugar()
        from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar

        return CallSiteSugar(
            target_name=self.func.id,
            args=tuple(a.sugar() for a in self.args),
            site=self.fragment,
        )


class FormattedValue(Expression):
    value: Expression
    conversion: int
    format_spec: Optional["JoinedStr"]
    _child_fields = ("value", "format_spec")

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def sugar(self):
        """`{value}` in an f-string. A conversion (!r/!s/!a) or a format spec is
        not lifted yet -- LOUD rather than a silently dropped modifier."""
        from sugar_lift_py_tests.sugar.fstring_sugar import FormattedValueSugar

        if self.conversion != -1 or self.format_spec is not None:
            return super().sugar()
        return FormattedValueSugar(value=self.value.sugar(), site=self.fragment)


class JoinedStr(Expression):
    values: Tuple[Expression, ...]
    _child_fields = ("values",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def sugar(self):
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

    def sugar(self):
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
            return super().sugar()  # bool is its own sugar, not yet written
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
        return super().sugar()  # bool / bytes / ... not yet written


class Attribute(Expression):
    value: Expression
    attr: str
    _child_fields = ("value",)

    def sugar(self):
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

    def sugar(self):
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

    def substitute(self, scope: "dict[str, Node]") -> "Node":
        # A name resolves to its bound node, or stands unbound. This is the
        # whole substitution base case — it returns an EXISTING node, so it
        # needs no synthetic construction.
        bound = scope.get(self.id)
        return bound if bound is not None else self

    def sugar(self):
        """A name constructs NameSugar with its identifier. A name is a leaf:
        nothing to build from children, only to look up against the temporal
        scope when the body reduces (an unbound name panics there, loudly)."""
        from sugar_lift_py_tests.sugar.name_sugar import NameSugar

        return NameSugar(name=self.id, site=self.fragment)


class List(Expression):
    elts: Tuple[Expression, ...]
    _child_fields = ("elts",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def sugar(self):
        """`[e, ...]` constructs ListSugar WITH each element's sugar. A `*xs`
        spread is not one element -- it stays loud until its own sugar lands."""
        from sugar_lift_py_tests.sugar.collection_sugar import ListSugar

        if any(e.kind == "Starred" for e in self.elts):
            return super().sugar()
        return ListSugar(
            elements=tuple(e.sugar() for e in self.elts), site=self.fragment
        )


class Tuple_(Expression):
    elts: Tuple[Expression, ...]
    _child_fields = ("elts",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def sugar(self):
        """`(e, ...)` constructs TupleSugar WITH each element's sugar; `*xs` is loud."""
        from sugar_lift_py_tests.sugar.collection_sugar import TupleSugar

        if any(e.kind == "Starred" for e in self.elts):
            return super().sugar()
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
