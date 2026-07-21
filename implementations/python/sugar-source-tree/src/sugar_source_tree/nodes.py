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
from .panic import SourceTreePanic, SugarNotWritten, vocabulary_missing
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
        """Rewrite this node against a scope (name -> bound node), yielding a
        NEW node. Reduction IS substitution into the tree — there is no
        environment threaded alongside; the rewritten tree is the state, and
        single assignment is its natural form (each rewrite is a fresh tree).

        Default: a node that binds nothing rewrites to itself. A Name resolves
        against the scope; a compound node rewrites its children; a scope-
        owning node masks its bound names before rewriting its body.
        """
        return self

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


class Keyword(Node):
    """A keyword argument at a call site. ``arg is None`` means ``**expr``
    (double-star spread) — a structural absence, not a refusal."""

    arg: Optional[str]
    value: Expression
    _child_fields = ("value",)


class DictItem(Node):
    """One ``key: value`` entry of a Dict display. ``key is None`` means
    ``**expr`` (double-star spread) — a structural absence, not a refusal."""

    key: Optional[Expression]
    value: Expression
    _child_fields = ("key", "value")


class Comprehension(Node):
    """One ``for target in iter [if ...]*`` clause."""

    target: Expression
    iter: Expression
    ifs: Tuple[Expression, ...]
    is_async: bool
    _child_fields = ("target", "iter", "ifs")


class ExceptHandler(Node):
    type_: Optional[Expression]
    name: Optional[str]
    body: Tuple[Statement, ...]
    _child_fields = ("type_", "body")


class WithItem(Node):
    context_expr: Expression
    optional_vars: Optional[Expression]
    _child_fields = ("context_expr", "optional_vars")


class ImportAlias(Node):
    name: str
    asname: Optional[str]


class MatchCase(Node):
    pattern: Pattern
    guard: Optional[Expression]
    body: Tuple[Statement, ...]
    _child_fields = ("pattern", "guard", "body")


# --------------------------------------------------------------------------
# Module and statements
# --------------------------------------------------------------------------


class Module(Node):
    body: Tuple[Statement, ...]
    _child_fields = ("body",)


class FunctionDef(Statement):
    name: str
    params: Tuple[Param, ...]
    body: Tuple[Statement, ...]
    decorators: Tuple[Expression, ...]
    returns: Optional[Expression]
    type_params: Tuple[TypeParam, ...]
    _child_fields = ("decorators", "type_params", "params", "returns", "body")

    def sugar(self):
        """`def <name>(<formals>): <body>` constructs FunctionUniverseSugar WITH
        each body statement's own sugar — the recursion, child-before-parent.

        A body statement whose sugar is not written yet raises SugarNotWritten
        from its own `.sugar()`, which propagates out here: the whole function
        is a frontier gap until every statement it holds can be constructed.
        That is the honest 99% — no fallback, no partial universe.
        """
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            FunctionUniverseSugar,
        )

        return FunctionUniverseSugar(
            name=self.name,
            formals=tuple(p.name for p in self.params),
            statements=tuple(stmt.sugar() for stmt in self.body),
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


class ClassDef(Statement):
    name: str
    bases: Tuple[Expression, ...]
    keywords: Tuple[Keyword, ...]
    body: Tuple[Statement, ...]
    decorators: Tuple[Expression, ...]
    type_params: Tuple[TypeParam, ...]
    _child_fields = ("decorators", "type_params", "bases", "keywords", "body")


class Return(Statement):
    value: Optional[Expression]
    _child_fields = ("value",)


class Delete(Statement):
    targets: Tuple[Expression, ...]
    _child_fields = ("targets",)


class Assign(Statement):
    targets: Tuple[Expression, ...]
    value: Expression
    _child_fields = ("targets", "value")

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


class AnnAssign(Statement):
    target: Expression
    annotation: Expression
    value: Optional[Expression]
    simple: bool
    _child_fields = ("target", "annotation", "value")


class TypeAlias(Statement):
    name: Expression
    type_params: Tuple[TypeParam, ...]
    value: Expression
    _child_fields = ("name", "type_params", "value")


class For(Statement):
    target: Expression
    iter: Expression
    body: Tuple[Statement, ...]
    orelse: Tuple[Statement, ...]
    _child_fields = ("target", "iter", "body", "orelse")


class AsyncFor(Statement):
    target: Expression
    iter: Expression
    body: Tuple[Statement, ...]
    orelse: Tuple[Statement, ...]
    _child_fields = ("target", "iter", "body", "orelse")


class While(Statement):
    test: Expression
    body: Tuple[Statement, ...]
    orelse: Tuple[Statement, ...]
    _child_fields = ("test", "body", "orelse")


class If(Statement):
    test: Expression
    body: Tuple[Statement, ...]
    orelse: Tuple[Statement, ...]
    _child_fields = ("test", "body", "orelse")


class With(Statement):
    items: Tuple[WithItem, ...]
    body: Tuple[Statement, ...]
    _child_fields = ("items", "body")


class AsyncWith(Statement):
    items: Tuple[WithItem, ...]
    body: Tuple[Statement, ...]
    _child_fields = ("items", "body")


class Raise(Statement):
    exc: Optional[Expression]
    cause: Optional[Expression]
    _child_fields = ("exc", "cause")


class Try(Statement):
    body: Tuple[Statement, ...]
    handlers: Tuple[ExceptHandler, ...]
    orelse: Tuple[Statement, ...]
    finalbody: Tuple[Statement, ...]
    _child_fields = ("body", "handlers", "orelse", "finalbody")


class TryStar(Statement):
    body: Tuple[Statement, ...]
    handlers: Tuple[ExceptHandler, ...]
    orelse: Tuple[Statement, ...]
    finalbody: Tuple[Statement, ...]
    _child_fields = ("body", "handlers", "orelse", "finalbody")


class Assert(Statement):
    test: Expression
    msg: Optional[Expression]
    _child_fields = ("test", "msg")

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


class ImportFrom(Statement):
    module: Optional[str]
    names: Tuple[ImportAlias, ...]
    level: int
    _child_fields = ("names",)


class Global(Statement):
    names: Tuple[str, ...]


class Nonlocal(Statement):
    names: Tuple[str, ...]


class Expr(Statement):
    """An expression in statement position."""

    value: Expression
    _child_fields = ("value",)


class Pass(Statement):
    pass


class Break(Statement):
    pass


class Continue(Statement):
    pass


class Match(Statement):
    subject: Expression
    cases: Tuple[MatchCase, ...]
    _child_fields = ("subject", "cases")


# --------------------------------------------------------------------------
# Expressions
# --------------------------------------------------------------------------


class BoolOp(Expression):
    op: BooleanOperator
    values: Tuple[Expression, ...]
    _child_fields = ("values",)


class NamedExpr(Expression):
    target: Expression
    value: Expression
    _child_fields = ("target", "value")


class BinOp(Expression):
    left: Expression
    op: BinaryOperator
    right: Expression
    _child_fields = ("left", "right")

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


class Lambda(Expression):
    params: Tuple[Param, ...]
    body: Expression
    _child_fields = ("params", "body")


class IfExp(Expression):
    test: Expression
    body: Expression
    orelse: Expression
    _child_fields = ("body", "test", "orelse")


class Dict(Expression):
    items: Tuple[DictItem, ...]
    _child_fields = ("items",)


class Set(Expression):
    elts: Tuple[Expression, ...]
    _child_fields = ("elts",)


class ListComp(Expression):
    elt: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("elt", "generators")


class SetComp(Expression):
    elt: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("elt", "generators")


class DictComp(Expression):
    key: Expression
    value: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("key", "value", "generators")


class GeneratorExp(Expression):
    elt: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("elt", "generators")


class Await(Expression):
    value: Expression
    _child_fields = ("value",)


class Yield(Expression):
    value: Optional[Expression]
    _child_fields = ("value",)


class YieldFrom(Expression):
    value: Expression
    _child_fields = ("value",)


class Compare(Expression):
    left: Expression
    ops: Tuple[ComparisonOperator, ...]
    comparators: Tuple[Expression, ...]
    _child_fields = ("left", "comparators")

    def sugar(self):
        """A comparison constructs its operator's sugar, built WITH its
        children's sugar. Each comparison operator is its own sugar type
        (no operator field to switch on downstream) — dispatch here on the
        operator class and on arity. A single `==` is EqualityOpSugar; every
        other operator and chained comparisons inherit the loud throw until
        written.
        """
        from .operators import Eq

        if len(self.ops) == 1 and isinstance(self.ops[0], Eq):
            from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar

            return EqualityOpSugar(
                left=self.left.sugar(),
                right=self.comparators[0].sugar(),
                site=self.fragment,
            )
        return super().sugar()


class Call(Expression):
    func: Expression
    args: Tuple[Expression, ...]
    keywords: Tuple[Keyword, ...]
    _child_fields = ("func", "args", "keywords")

    def receiver(self) -> Optional[Expression]:
        """The object a method call is invoked on, when the callee is an
        attribute access. ``None`` is a structural absence (a plain call)."""
        func = self.func
        if isinstance(func, Attribute):
            return func.value
        return None


class FormattedValue(Expression):
    value: Expression
    conversion: int
    format_spec: Optional["JoinedStr"]
    _child_fields = ("value", "format_spec")


class JoinedStr(Expression):
    values: Tuple[Expression, ...]
    _child_fields = ("values",)


class Constant(Expression):
    value: object
    literal_kind: Optional[str]

    def sugar(self):
        """A literal constructs its literal sugar directly — a leaf: no child
        sugar, the value stands. Dispatch on the value's exact type (bool is a
        subclass of int, so it is checked first and is its own sugar). Every
        literal kind not yet converted inherits the loud SugarNotWritten throw.
        """
        v = self.value
        if isinstance(v, bool):
            return super().sugar()  # bool is its own sugar, not yet written
        if isinstance(v, int):
            from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar

            return IntLiteralSugar(value=v, site=self.fragment)
        if type(v) is str:
            from sugar_lift_py_tests.sugar.string_literal_sugar import (
                StringLiteralSugar,
            )

            return StringLiteralSugar(value=v, site=self.fragment)
        return super().sugar()  # float / bytes / None / ... not yet written


class Attribute(Expression):
    value: Expression
    attr: str
    _child_fields = ("value",)


class Subscript(Expression):
    value: Expression
    slice_: Expression
    _child_fields = ("value", "slice_")

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


class Tuple_(Expression):
    elts: Tuple[Expression, ...]
    _child_fields = ("elts",)


# Wire word for tuples is "Tuple"; the class name carries a trailing
# underscore only to avoid shadowing typing.Tuple inside this module.
Tuple_._kind = "Tuple"
KIND_REGISTRY["Tuple"] = KIND_REGISTRY.pop("Tuple_")


class Slice(Expression):
    lower: Optional[Expression]
    upper: Optional[Expression]
    step: Optional[Expression]
    _child_fields = ("lower", "upper", "step")


# --------------------------------------------------------------------------
# match patterns
# --------------------------------------------------------------------------


class MatchValue(Pattern):
    value: Expression
    _child_fields = ("value",)


class MatchSingleton(Pattern):
    value: object


class MatchSequence(Pattern):
    patterns: Tuple[Pattern, ...]
    _child_fields = ("patterns",)


class MatchMapping(Pattern):
    keys: Tuple[Expression, ...]
    patterns: Tuple[Pattern, ...]
    rest: Optional[str]
    _child_fields = ("keys", "patterns")


class MatchClass(Pattern):
    cls_: Expression
    patterns: Tuple[Pattern, ...]
    kwd_attrs: Tuple[str, ...]
    kwd_patterns: Tuple[Pattern, ...]
    _child_fields = ("cls_", "patterns", "kwd_patterns")


class MatchStar(Pattern):
    name: Optional[str]


class MatchAs(Pattern):
    pattern: Optional[Pattern]
    name: Optional[str]
    _child_fields = ("pattern",)


class MatchOr(Pattern):
    patterns: Tuple[Pattern, ...]
    _child_fields = ("patterns",)


# --------------------------------------------------------------------------
# PEP 695 type parameters
# --------------------------------------------------------------------------


class TypeVar(TypeParam):
    name: str
    bound: Optional[Expression]
    default_value: Optional[Expression] = None  # PEP 696 (3.13+)
    _child_fields = ("bound", "default_value")


class ParamSpec(TypeParam):
    name: str
    default_value: Optional[Expression] = None  # PEP 696 (3.13+)
    _child_fields = ("default_value",)


class TypeVarTuple(TypeParam):
    name: str
    default_value: Optional[Expression] = None  # PEP 696 (3.13+)
    _child_fields = ("default_value",)


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
