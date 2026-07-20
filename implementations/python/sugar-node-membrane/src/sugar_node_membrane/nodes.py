"""The node membrane: the class hierarchy IS the grammar.

``SourceFragment`` is the abstract base; ``Call``, ``FunctionDef``,
``Assert``, ``Name``, ... subclass it. Which fields exist is answered by
which class you hold — you cannot ask a non-Call for its args because you do
not have one. Arity lives in the field types (``Expression`` vs
``Expression | None`` vs ``tuple[Expression, ...]``). There is no
``NodeKind`` dispatch, no ``match`` on tags, no ASDL table.

``Typeable`` is the interface: "you may ask me for my type."
``Typed`` is the abstract class: "I have a resolved type, here it is."
The transition between them IS the construction event: a backend handle is
``Typeable`` (it can be asked to resolve, and panics as a MISSING if it
cannot); every constructed membrane node is ``Typed`` by virtue of being an
instance of its concrete class. A ``Typeable`` that cannot resolve NEVER
becomes a quiet ``False`` or a bare ``None``.

Asking "which node is this" is ``isinstance`` on THESE classes — blessed
and encouraged (design review, #5940 section 6). What is banned is tag
dispatch on strings.

Equality is identity: nodes are interned one-per-site by the pool
(construct.py), so ``a is b`` is the sameness question. Structural equality
across sources is a CID question, answered by mementos, not by ``__eq__``.

Membrane nodes carry their own fields; nothing is ever written onto a
backend node (no stamping). Synthetic nodes (a future ``assert_with_test``)
are ordinary instances of these classes with no backend handle at all —
the backend contract stays read-only.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, fields as dataclass_fields
from typing import ClassVar, Iterator, Optional, Tuple

from .operators import (
    BinaryOperator,
    BooleanOperator,
    ComparisonOperator,
    UnaryOperator,
)
from .panic import MembranePanic, membrane_missing
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
    """The interface: you may ask me for my membrane type.

    ``resolve_type`` has two arms: a concrete ``SourceFragment`` subclass,
    or ``MembranePanic``. There is no third arm.
    """

    def resolve_type(self) -> type["SourceFragment"]:
        raise NotImplementedError


class Typed(Typeable):
    """The abstract class: I HAVE a resolved type; resolution already happened.

    For membrane nodes the resolved type is the concrete class itself; the
    construction event was the resolution.
    """

    def resolve_type(self) -> type["SourceFragment"]:
        tp = type(self)
        if tp in _ABSTRACT or not issubclass(tp, SourceFragment):
            # Neither of the two panics fits: this is not a provider-facing
            # question at all (no ProviderHandle, no adapter, no vocabulary
            # gap) and not a structural-defect-in-provider-output question
            # either. It is an internal invariant on OUR OWN construction
            # code: only concrete classes are ever instantiated (construct.py
            # resolves through resolve_kind, which already excludes
            # _ABSTRACT). Reaching here means our own code, not a provider,
            # built an abstract instance. Raised as the common base directly
            # — deliberately, not a guess at which subclass fits.
            raise MembranePanic(
                owner="nodes.Typed.resolve_type",
                observed=f"instance of abstract membrane class {tp.__name__}",
                requested="a concrete grammar class",
                fix="abstract membrane classes are never instantiated",
            )
        return tp


KIND_REGISTRY: dict[str, type["SourceFragment"]] = {}
_ABSTRACT: set[type] = set()


def _abstract(cls: type) -> type:
    _ABSTRACT.add(cls)
    KIND_REGISTRY.pop(cls.__name__, None)
    return cls


@_abstract
@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class SourceFragment(Typed):
    """Abstract base of every membrane node. The hierarchy is the grammar."""

    unit: SourceUnit
    span: Span

    # Ordered names of fields holding child nodes (SourceFragment, optional
    # SourceFragment, or tuple of SourceFragment). Leaf values (str/int/...)
    # and operators are NOT children. Declared per class, in grammar order.
    # ClassVar on purpose: never a dataclass field, never instance state.
    _child_fields: ClassVar[Tuple[str, ...]] = ()

    def __init_subclass__(cls, **kw: object) -> None:
        super().__init_subclass__(**kw)
        KIND_REGISTRY[cls.__name__] = cls

    @property
    def kind(self) -> str:
        """Frozen wire word for serialization. Never a dispatch mechanism."""
        override = getattr(type(self), "_kind", None)
        return override if isinstance(override, str) else type(self).__name__

    def segment(self) -> str:
        return self.span.slice(self.unit.source)

    def line_col_span(self) -> LineColSpan:
        return self.unit.line_table.project(self.span)

    def children(self) -> Iterator[tuple[str, Optional[int], "SourceFragment"]]:
        """Yield (field_name, index-or-None, child) in declared grammar order."""
        for name in type(self)._child_fields:
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, SourceFragment):
                yield name, None, value
            else:
                for i, item in enumerate(value):
                    if item is not None:
                        yield name, i, item

    def walk(self) -> Iterator["SourceFragment"]:
        """Pre-order walk over the constructed graph. Iterative — never recursive."""
        stack: list[SourceFragment] = [self]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(
                child for _, _, child in reversed(list(node.children()))
            )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.kind} [{self.span.start},{self.span.end})>"


@_abstract
@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Statement(SourceFragment):
    pass


@_abstract
@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Expression(SourceFragment):
    pass


@_abstract
@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Pattern(SourceFragment):
    """A structural pattern inside ``match``."""


@_abstract
@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class TypeParam(SourceFragment):
    """A PEP 695 type parameter."""


# --------------------------------------------------------------------------
# Helper nodes (grammar constituents that are not statements or expressions)
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Param(SourceFragment):
    """One formal parameter. ``param_kind`` is one of: positional_only,
    positional_or_keyword, vararg, keyword_only, kwarg."""

    name: str = ""
    annotation: Optional[Expression] = None
    default: Optional[Expression] = None
    param_kind: str = "positional_or_keyword"
    _child_fields = ("annotation", "default")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Keyword(SourceFragment):
    """A keyword argument at a call site. ``arg is None`` means ``**expr``
    (double-star spread) — a structural absence, not a refusal."""

    arg: Optional[str] = None
    value: Expression
    _child_fields = ("value",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class DictItem(SourceFragment):
    """One ``key: value`` entry of a Dict display. ``key is None`` means
    ``**expr`` (double-star spread) — a structural absence, not a refusal."""

    key: Optional[Expression] = None
    value: Expression
    _child_fields = ("key", "value")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Comprehension(SourceFragment):
    """One ``for target in iter [if ...]*`` clause."""

    target: Expression
    iter: Expression
    ifs: Tuple[Expression, ...] = ()
    is_async: bool = False
    _child_fields = ("target", "iter", "ifs")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class ExceptHandler(SourceFragment):
    type_: Optional[Expression] = None
    name: Optional[str] = None
    body: Tuple[Statement, ...] = ()
    _child_fields = ("type_", "body")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class WithItem(SourceFragment):
    context_expr: Expression
    optional_vars: Optional[Expression] = None
    _child_fields = ("context_expr", "optional_vars")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class ImportAlias(SourceFragment):
    name: str = ""
    asname: Optional[str] = None


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class MatchCase(SourceFragment):
    pattern: Pattern
    guard: Optional[Expression] = None
    body: Tuple[Statement, ...] = ()
    _child_fields = ("pattern", "guard", "body")


# --------------------------------------------------------------------------
# Module and statements
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Module(SourceFragment):
    body: Tuple[Statement, ...] = ()
    _child_fields = ("body",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class FunctionDef(Statement):
    name: str = ""
    params: Tuple[Param, ...] = ()
    body: Tuple[Statement, ...] = ()
    decorators: Tuple[Expression, ...] = ()
    returns: Optional[Expression] = None
    type_params: Tuple[TypeParam, ...] = ()
    _child_fields = ("decorators", "type_params", "params", "returns", "body")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class AsyncFunctionDef(Statement):
    name: str = ""
    params: Tuple[Param, ...] = ()
    body: Tuple[Statement, ...] = ()
    decorators: Tuple[Expression, ...] = ()
    returns: Optional[Expression] = None
    type_params: Tuple[TypeParam, ...] = ()
    _child_fields = ("decorators", "type_params", "params", "returns", "body")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class ClassDef(Statement):
    name: str = ""
    bases: Tuple[Expression, ...] = ()
    keywords: Tuple[Keyword, ...] = ()
    body: Tuple[Statement, ...] = ()
    decorators: Tuple[Expression, ...] = ()
    type_params: Tuple[TypeParam, ...] = ()
    _child_fields = ("decorators", "type_params", "bases", "keywords", "body")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Return(Statement):
    value: Optional[Expression] = None
    _child_fields = ("value",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Delete(Statement):
    targets: Tuple[Expression, ...] = ()
    _child_fields = ("targets",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Assign(Statement):
    targets: Tuple[Expression, ...] = ()
    value: Expression
    _child_fields = ("targets", "value")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class AugAssign(Statement):
    target: Expression
    op: BinaryOperator
    value: Expression
    _child_fields = ("target", "value")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class AnnAssign(Statement):
    target: Expression
    annotation: Expression
    value: Optional[Expression] = None
    simple: bool = True
    _child_fields = ("target", "annotation", "value")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class TypeAlias(Statement):
    name: Expression
    type_params: Tuple[TypeParam, ...] = ()
    value: Expression
    _child_fields = ("name", "type_params", "value")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class For(Statement):
    target: Expression
    iter: Expression
    body: Tuple[Statement, ...] = ()
    orelse: Tuple[Statement, ...] = ()
    _child_fields = ("target", "iter", "body", "orelse")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class AsyncFor(Statement):
    target: Expression
    iter: Expression
    body: Tuple[Statement, ...] = ()
    orelse: Tuple[Statement, ...] = ()
    _child_fields = ("target", "iter", "body", "orelse")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class While(Statement):
    test: Expression
    body: Tuple[Statement, ...] = ()
    orelse: Tuple[Statement, ...] = ()
    _child_fields = ("test", "body", "orelse")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class If(Statement):
    test: Expression
    body: Tuple[Statement, ...] = ()
    orelse: Tuple[Statement, ...] = ()
    _child_fields = ("test", "body", "orelse")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class With(Statement):
    items: Tuple[WithItem, ...] = ()
    body: Tuple[Statement, ...] = ()
    _child_fields = ("items", "body")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class AsyncWith(Statement):
    items: Tuple[WithItem, ...] = ()
    body: Tuple[Statement, ...] = ()
    _child_fields = ("items", "body")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Raise(Statement):
    exc: Optional[Expression] = None
    cause: Optional[Expression] = None
    _child_fields = ("exc", "cause")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Try(Statement):
    body: Tuple[Statement, ...] = ()
    handlers: Tuple[ExceptHandler, ...] = ()
    orelse: Tuple[Statement, ...] = ()
    finalbody: Tuple[Statement, ...] = ()
    _child_fields = ("body", "handlers", "orelse", "finalbody")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class TryStar(Statement):
    body: Tuple[Statement, ...] = ()
    handlers: Tuple[ExceptHandler, ...] = ()
    orelse: Tuple[Statement, ...] = ()
    finalbody: Tuple[Statement, ...] = ()
    _child_fields = ("body", "handlers", "orelse", "finalbody")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Assert(Statement):
    test: Expression
    msg: Optional[Expression] = None
    _child_fields = ("test", "msg")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Import(Statement):
    names: Tuple[ImportAlias, ...] = ()
    _child_fields = ("names",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class ImportFrom(Statement):
    module: Optional[str] = None
    names: Tuple[ImportAlias, ...] = ()
    level: int = 0
    _child_fields = ("names",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Global(Statement):
    names: Tuple[str, ...] = ()


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Nonlocal(Statement):
    names: Tuple[str, ...] = ()


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Expr(Statement):
    """An expression in statement position."""

    value: Expression
    _child_fields = ("value",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Pass(Statement):
    pass


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Break(Statement):
    pass


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Continue(Statement):
    pass


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Match(Statement):
    subject: Expression
    cases: Tuple[MatchCase, ...] = ()
    _child_fields = ("subject", "cases")


# --------------------------------------------------------------------------
# Expressions
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class BoolOp(Expression):
    op: BooleanOperator
    values: Tuple[Expression, ...] = ()
    _child_fields = ("values",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class NamedExpr(Expression):
    target: Expression
    value: Expression
    _child_fields = ("target", "value")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class BinOp(Expression):
    left: Expression
    op: BinaryOperator
    right: Expression
    _child_fields = ("left", "right")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class UnaryOp(Expression):
    op: UnaryOperator
    operand: Expression
    _child_fields = ("operand",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Lambda(Expression):
    params: Tuple[Param, ...] = ()
    body: Expression
    _child_fields = ("params", "body")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class IfExp(Expression):
    test: Expression
    body: Expression
    orelse: Expression
    _child_fields = ("body", "test", "orelse")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Dict(Expression):
    items: Tuple[DictItem, ...] = ()
    _child_fields = ("items",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Set(Expression):
    elts: Tuple[Expression, ...] = ()
    _child_fields = ("elts",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class ListComp(Expression):
    elt: Expression
    generators: Tuple[Comprehension, ...] = ()
    _child_fields = ("elt", "generators")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class SetComp(Expression):
    elt: Expression
    generators: Tuple[Comprehension, ...] = ()
    _child_fields = ("elt", "generators")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class DictComp(Expression):
    key: Expression
    value: Expression
    generators: Tuple[Comprehension, ...] = ()
    _child_fields = ("key", "value", "generators")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class GeneratorExp(Expression):
    elt: Expression
    generators: Tuple[Comprehension, ...] = ()
    _child_fields = ("elt", "generators")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Await(Expression):
    value: Expression
    _child_fields = ("value",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Yield(Expression):
    value: Optional[Expression] = None
    _child_fields = ("value",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class YieldFrom(Expression):
    value: Expression
    _child_fields = ("value",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Compare(Expression):
    left: Expression
    ops: Tuple[ComparisonOperator, ...] = ()
    comparators: Tuple[Expression, ...] = ()
    _child_fields = ("left", "comparators")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Call(Expression):
    func: Expression
    args: Tuple[Expression, ...] = ()
    keywords: Tuple[Keyword, ...] = ()
    _child_fields = ("func", "args", "keywords")

    def receiver(self) -> Optional[Expression]:
        """The object a method call is invoked on, when the callee is an
        attribute access. ``None`` is a structural absence (a plain call)."""
        func = self.func
        if isinstance(func, Attribute):
            return func.value
        return None


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class FormattedValue(Expression):
    value: Expression
    conversion: int = -1
    format_spec: Optional["JoinedStr"] = None
    _child_fields = ("value", "format_spec")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class JoinedStr(Expression):
    values: Tuple[Expression, ...] = ()
    _child_fields = ("values",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Constant(Expression):
    value: object = None
    literal_kind: Optional[str] = None


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Attribute(Expression):
    value: Expression
    attr: str = ""
    _child_fields = ("value",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Subscript(Expression):
    value: Expression
    slice_: Expression
    _child_fields = ("value", "slice_")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Starred(Expression):
    value: Expression
    _child_fields = ("value",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Name(Expression):
    id: str = ""


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class List(Expression):
    elts: Tuple[Expression, ...] = ()
    _child_fields = ("elts",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Tuple_(Expression):
    elts: Tuple[Expression, ...] = ()
    _child_fields = ("elts",)


# Wire word for tuples is "Tuple"; the class name carries a trailing
# underscore only to avoid shadowing typing.Tuple inside this module.
Tuple_._kind = "Tuple"
KIND_REGISTRY["Tuple"] = KIND_REGISTRY.pop("Tuple_")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Slice(Expression):
    lower: Optional[Expression] = None
    upper: Optional[Expression] = None
    step: Optional[Expression] = None
    _child_fields = ("lower", "upper", "step")


# --------------------------------------------------------------------------
# match patterns
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class MatchValue(Pattern):
    value: Expression
    _child_fields = ("value",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class MatchSingleton(Pattern):
    value: object = None


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class MatchSequence(Pattern):
    patterns: Tuple[Pattern, ...] = ()
    _child_fields = ("patterns",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class MatchMapping(Pattern):
    keys: Tuple[Expression, ...] = ()
    patterns: Tuple[Pattern, ...] = ()
    rest: Optional[str] = None
    _child_fields = ("keys", "patterns")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class MatchClass(Pattern):
    cls_: Expression
    patterns: Tuple[Pattern, ...] = ()
    kwd_attrs: Tuple[str, ...] = ()
    kwd_patterns: Tuple[Pattern, ...] = ()
    _child_fields = ("cls_", "patterns", "kwd_patterns")


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class MatchStar(Pattern):
    name: Optional[str] = None


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class MatchAs(Pattern):
    pattern: Optional[Pattern] = None
    name: Optional[str] = None
    _child_fields = ("pattern",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class MatchOr(Pattern):
    patterns: Tuple[Pattern, ...] = ()
    _child_fields = ("patterns",)


# --------------------------------------------------------------------------
# PEP 695 type parameters
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class TypeVar(TypeParam):
    name: str = ""
    bound: Optional[Expression] = None
    _child_fields = ("bound",)


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class ParamSpec(TypeParam):
    name: str = ""


@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class TypeVarTuple(TypeParam):
    name: str = ""


def resolve_kind(kind: str, observed_at: str) -> type[SourceFragment]:
    """Two arms: a registered concrete membrane class, or panic.

    A backend kind with no membrane class is a MISSING grammar class — the
    conformance finding itself — never a permissive fallback.
    """
    cls = KIND_REGISTRY.get(kind)
    if cls is None or cls in _ABSTRACT:
        membrane_missing(
            owner="nodes.resolve_kind",
            observed=f"backend kind {kind!r} at {observed_at} has no membrane class",
            requested="a concrete SourceFragment subclass for every constructible shape",
            fix="add the missing grammar class to nodes.py — never map to a fallback",
        )
        raise AssertionError("unreachable")
    return cls


def field_names(cls: type[SourceFragment]) -> Tuple[str, ...]:
    """Constructor field names beyond the base (unit, span), in order."""
    return tuple(
        f.name for f in dataclass_fields(cls) if f.name not in ("unit", "span")
    )
