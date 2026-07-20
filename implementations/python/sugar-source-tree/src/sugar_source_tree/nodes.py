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

import hashlib
from dataclasses import dataclass, field
from typing import ClassVar, Iterator, Optional, Tuple

from .operators import (
    BinaryOperator,
    BooleanOperator,
    ComparisonOperator,
    UnaryOperator,
)
from .panic import SourceTreePanic, vocabulary_missing
from .spans import LineColSpan, LineTable, Span


@dataclass(frozen=True)
class SourceUnit:
    """One parsed source: text, its content address, and its line table.

    ``source_cid`` is sha256 over the UTF-8 encoding of the source string —
    a pure function of the text, never of the parser.
    """

    filename: str
    source: str

    # populated in __post_init__, never by callers
    source_cid: str = field(init=False, default="")
    line_table: LineTable = field(init=False, default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        digest = hashlib.sha256(self.source.encode("utf-8")).hexdigest()
        object.__setattr__(self, "source_cid", f"sha256:{digest}")
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
                return slot.resolve(self.unit)
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

    def segment(self) -> str:
        return self.span.slice(self.unit.source)

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


class Attribute(Expression):
    value: Expression
    attr: str
    _child_fields = ("value",)


class Subscript(Expression):
    value: Expression
    slice_: Expression
    _child_fields = ("value", "slice_")


class Starred(Expression):
    value: Expression
    _child_fields = ("value",)


class Name(Expression):
    id: str


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
