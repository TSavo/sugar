"""LibCST backend adapter — the second backend (#5940, #5932).

THE ONLY MODULE IN THIS PACKAGE THAT MAY NAME ``libcst``. Same read-only
contract as ``cpython_adapter``: ``parse(unit) -> handle``, and per handle a
single ``describe()`` giving our kind, our codepoint span, and our fields as
slots. Nothing is ever written onto a LibCST node (they are immutable
anyway), no backend node is ever constructed, and no handle travels above
the builder.

Why a second backend exists at all: #5932 isolated an intermittent SIGSEGV
to CPython's own ``ast.parse`` -> ``compile()``. LibCST is Rust-backed and
does not call ``compile()``. T's rule — a backend that segfaults, or
diverges on the golden corpus, is not debugged, it is uninstalled — only has
teeth when a second backend exists to switch to.

MAPPING NOTES (LibCST is a CONCRETE syntax tree; ours is AST-shaped)
====================================================================

What LibCST gives us for free, matching spans.py exactly:

- **Columns are codepoints.** ``PositionProvider`` reports character
  columns, which IS our span definition. CPython's UTF-8 byte columns are
  the ones needing normalization, not LibCST's. (Measured: ``é = f(ü)``
  puts the ``Call`` at codepoint [4,8).)
- **Grouping parens are excluded.** ``(x + y)`` positions the
  ``BinaryOperation`` at ``x + y``; ``(n := 10)`` positions the
  ``NamedExpr`` at ``n := 10``. Both are our ruling.
- **Decorated defs start at ``def``.** ``FunctionDef`` positions from the
  ``def`` keyword, decorators excluded — our ruling.

What this adapter must translate, because the CST vocabulary differs:

- **Pure-syntax nodes are not in our inventory** and are never materialized:
  ``SimpleStatementLine``, ``SimpleStatementSuite``, ``IndentedBlock``,
  ``Else``, ``Finally``, ``Decorator``, ``Annotation``, ``AsName``,
  ``Element``, ``Arg``, ``AssignTarget``, ``Index``, ``SubscriptElement``,
  ``ParamStar``, ``Parameters``, ``LeftParen``/``RightParen``, whitespace,
  commas, and every other trivia node. They are unwrapped or flattened.
- **Tuple parens.** LibCST excludes them; our spec includes them for a
  tuple display (spans.py, the one ruled exception). Recovered from the
  innermost ``lpar``/``rpar`` positions.
- **Param sigils.** LibCST's ``Param`` for ``*b`` spans ``*b``; our spec
  excludes the sigil (it is an arity marker of the parameter LIST). The
  ``Param`` is anchored on its NAME token and enveloped with annotation and
  default, exactly as the CPython adapter anchors on ``ast.arg``.
- **Comprehension clauses.** LibCST's ``CompFor`` span starts at the
  whitespace before ``for``; our spec starts at the keyword. Recovered by a
  forward scan over whitespace from the clause start — the mirror of the
  CPython adapter's backscan, and equally pure.
- **Literals.** LibCST has ``Integer``/``Float``/``Imaginary``/
  ``SimpleString``/``Ellipsis``, and spells ``True``/``False``/``None`` as
  ``Name``. All become our ``Constant``.
- **n-ary flattening.** ``a and b and c`` is left-nested in LibCST and
  n-ary in our ``BoolOp.values``; same for ``del a, b`` against our
  ``Delete.targets``. The node class declares the arity, so the adapter
  flattens into it.
- **Format specs.** LibCST carries a format spec as a bare sequence of
  content nodes with no wrapper; our ``FormattedValue.format_spec`` is a
  ``JoinedStr``. One is synthesized, spanning its contents — which is the
  text after the ``:``, our ruling.

A LibCST shape with no rule here panics as a MISSING at the boundary. There
is no generic fallback and no ``getattr`` sniffing: an unmapped CST node is
the conformance finding itself.

Source LibCST cannot parse at all raises ``libcst.ParserSyntaxError`` —
which does NOT subclass ``SyntaxError`` (#5946). This adapter catches it
and re-raises ``BackendCouldNotParse`` (backend.py), never letting the
library-native type escape, so a caller written against one backend
never silently stops working when the other is swapped in.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence, Tuple

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from .backend import (
    Child,
    Children,
    Description,
    Leaf,
    MaybeChild,
    OpLeaf,
    OpsLeaf,
    Backend,
    BackendNode,
    BackendCouldNotParse,
    Slot,
)
from .nodes import SourceUnit
from .operators import Operator, operator_for
from .panic import vocabulary_missing, backend_defect
from .spans import Span

# --------------------------------------------------------------------------
# Context: the position map, resolved once per parse
# --------------------------------------------------------------------------


class _Ctx:
    """Per-parse state: the unit and LibCST's resolved position metadata."""

    __slots__ = ("unit", "positions")

    def __init__(self, unit: SourceUnit, positions: object) -> None:
        self.unit = unit
        self.positions = positions

    def span(self, node: cst.CSTNode) -> Span:
        """LibCST CodeRange -> our codepoint Span. Columns are ALREADY
        codepoints; there is no byte seam on this backend."""
        try:
            rng = self.positions[node]  # type: ignore[index]
        except KeyError:
            vocabulary_missing(
                blame=node,
                owner="libcst_adapter._Ctx.span",
                observed=f"libcst {type(node).__name__} carries no position",
                requested="a positioned node, or a rule marking it envelope-spanned",
                fix="add an explicit rule for this kind; never invent a span",
            )
        table = self.unit.line_table
        return Span(
            table.offset(rng.start.line, rng.start.column),
            table.offset(rng.end.line, rng.end.column),
        )


# --------------------------------------------------------------------------
# Handles
# --------------------------------------------------------------------------


class _Handle(BackendNode):
    """Read-only view of one LibCST node, described by its rule."""

    __slots__ = ("_ctx", "_node", "_desc")

    def __init__(self, ctx: _Ctx, node: cst.CSTNode) -> None:
        self._ctx = ctx
        self._node = node
        self._desc: Optional[Description] = None

    def describe(self) -> Description:
        if self._desc is None:
            self._desc = _describe(self._ctx, self._node)
        return self._desc

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<libcst-handle {type(self._node).__name__} in {self._ctx.unit.filename}>"
        )


class _Synth(BackendNode):
    """A tree constituent LibCST does not materialize as one node.

    Used where the CST vocabulary is coarser or finer than ours: a
    ``DictItem`` pair, a ``Param``, a format-spec ``JoinedStr``, a
    multi-element subscript ``Tuple``. It describes node fields over
    LibCST children — it never constructs a backend node.
    """

    __slots__ = ("_kind", "_raw_span", "_anchors", "_slots", "_label")

    def __init__(
        self,
        kind: str,
        raw_span: Optional[Span],
        slots: Tuple[Tuple[str, Slot], ...],
        anchors: Tuple[Span, ...] = (),
        label: str = "",
    ) -> None:
        self._kind = kind
        self._raw_span = raw_span
        self._anchors = anchors
        self._slots = slots
        self._label = label

    def describe(self) -> Description:
        return Description(
            kind=self._kind,
            raw_span=self._raw_span,
            anchors=self._anchors,
            slots=self._slots,
        )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<libcst-synth {self._kind} {self._label}>"


# --------------------------------------------------------------------------
# Slot helpers
# --------------------------------------------------------------------------


def _child(ctx: _Ctx, node: cst.CSTNode) -> Child:
    return Child(_Handle(ctx, node))


def _maybe(ctx: _Ctx, node: Optional[cst.CSTNode]) -> MaybeChild:
    return MaybeChild(None if node is None else _Handle(ctx, node))


def _children(ctx: _Ctx, nodes: Sequence[cst.CSTNode]) -> Children:
    return Children(tuple(_Handle(ctx, n) for n in nodes))


def _unwrap_annotation(node: Optional[cst.Annotation]) -> Optional[cst.BaseExpression]:
    return None if node is None else node.annotation


def _asname_str(node: Optional[cst.AsName]) -> Optional[str]:
    if node is None:
        return None
    target = node.name
    if isinstance(target, cst.Name):
        return target.value
    vocabulary_missing(
        blame=target,
        owner="libcst_adapter._asname_str",
        observed=f"AsName over {type(target).__name__}, not a Name",
        requested="a simple name binding",
        fix="add an explicit rule; never guess an identifier",
    )
    raise AssertionError("unreachable")


def _dotted(node: cst.BaseExpression) -> str:
    """Dotted module name of an import target. Iterative, never recursive."""
    parts: list[str] = []
    cur = node
    while isinstance(cur, cst.Attribute):
        parts.append(cur.attr.value)
        cur = cur.value
    if not isinstance(cur, cst.Name):
        vocabulary_missing(
            blame=cur,
            owner="libcst_adapter._dotted",
            observed=f"import target head is {type(cur).__name__}, not a Name",
            requested="a Name or a chain of Attribute over a Name",
            fix="add an explicit rule for this import shape",
        )
    parts.append(cur.value)  # type: ignore[union-attr]
    return ".".join(reversed(parts))


# --------------------------------------------------------------------------
# Statement-body flattening: CST suites are not in our inventory
# --------------------------------------------------------------------------


def _statements(ctx: _Ctx, body: object) -> Tuple[BackendNode, ...]:
    """A CST suite/block/line -> our flat tuple of statement handles."""
    out: list[BackendNode] = []
    pending: list[object] = [body]
    while pending:
        item = pending.pop(0)
        if item is None:
            continue
        if isinstance(item, (list, tuple)):
            pending = list(item) + pending
            continue
        if isinstance(item, (cst.IndentedBlock, cst.SimpleStatementSuite)):
            pending = list(item.body) + pending
            continue
        if isinstance(item, cst.SimpleStatementLine):
            # ``a = 1; b = 2`` is one CST line and two of our statements.
            pending = list(item.body) + pending
            continue
        if isinstance(item, (cst.Else, cst.Finally)):
            pending = [item.body] + pending
            continue
        if isinstance(item, cst.CSTNode):
            out.append(_Handle(ctx, item))
            continue
        vocabulary_missing(
            blame=item,
            owner="libcst_adapter._statements",
            observed=f"{type(item).__name__} in statement position",
            requested="a CST statement, suite, or block",
            fix="add an explicit rule for this container",
        )
    return tuple(out)


def _orelse(ctx: _Ctx, node: object) -> Tuple[BackendNode, ...]:
    """``If.orelse``: an ``Else`` (flattened) or a nested ``If`` (an elif)."""
    if node is None:
        return ()
    if isinstance(node, cst.Else):
        return _statements(ctx, node.body)
    if isinstance(node, cst.If):
        return (_Handle(ctx, node),)
    vocabulary_missing(
        blame=node,
        owner="libcst_adapter._orelse",
        observed=f"{type(node).__name__} in orelse position",
        requested="an Else or a nested If",
        fix="add an explicit rule for this shape",
    )
    raise AssertionError("unreachable")


# --------------------------------------------------------------------------
# Operators
# --------------------------------------------------------------------------

_BINARY_OPS = {
    "Add": "Add",
    "Subtract": "Sub",
    "Multiply": "Mult",
    "Divide": "Div",
    "Modulo": "Mod",
    "Power": "Pow",
    "FloorDivide": "FloorDiv",
    "MatrixMultiply": "MatMult",
    "LeftShift": "LShift",
    "RightShift": "RShift",
    "BitOr": "BitOr",
    "BitAnd": "BitAnd",
    "BitXor": "BitXor",
}

_AUG_OPS = {
    "AddAssign": "Add",
    "SubtractAssign": "Sub",
    "MultiplyAssign": "Mult",
    "DivideAssign": "Div",
    "ModuloAssign": "Mod",
    "PowerAssign": "Pow",
    "FloorDivideAssign": "FloorDiv",
    "MatrixMultiplyAssign": "MatMult",
    "LeftShiftAssign": "LShift",
    "RightShiftAssign": "RShift",
    "BitOrAssign": "BitOr",
    "BitAndAssign": "BitAnd",
    "BitXorAssign": "BitXor",
}

_UNARY_OPS = {"Plus": "UAdd", "Minus": "USub", "Not": "Not", "BitInvert": "Invert"}

_BOOL_OPS = {"And": "And", "Or": "Or"}

_COMPARE_OPS = {
    "Equal": "Eq",
    "NotEqual": "NotEq",
    "LessThan": "Lt",
    "LessThanEqual": "LtE",
    "GreaterThan": "Gt",
    "GreaterThanEqual": "GtE",
    "In": "In",
    "NotIn": "NotIn",
    "Is": "Is",
    "IsNot": "IsNot",
}


def _op(table: dict[str, str], node: cst.CSTNode, where: str) -> Operator:
    kind = table.get(type(node).__name__)
    if kind is None:
        vocabulary_missing(
            blame=node,
            owner=f"libcst_adapter._op[{where}]",
            observed=f"libcst operator {type(node).__name__} has no tree operator",
            requested="a mapping into the frozen operator vocabulary",
            fix="add the operator deliberately in operators.py and here; never guess",
        )
        raise AssertionError("unreachable")
    return operator_for(kind, blame=node)


# --------------------------------------------------------------------------
# Span recovery for the shapes where LibCST and our spec differ
# --------------------------------------------------------------------------


def _tuple_span(ctx: _Ctx, node: cst.Tuple) -> Span:
    """Our spec: an enclosed tuple display INCLUDES its parens (the one
    ruled exception to the grouping rule). LibCST excludes them; the
    innermost paren pair is the display's delimiter."""
    inner = ctx.span(node)
    if node.lpar and node.rpar:
        return ctx.span(node.lpar[-1]).envelope(ctx.span(node.rpar[0]))
    return inner


def _comp_for_anchor(ctx: _Ctx, node: cst.CompFor) -> Span:
    """The clause's ``for`` (or ``async``) keyword start.

    LibCST's ``CompFor`` span begins at the trivia preceding the keyword;
    our spec begins at the keyword. Pure forward scan — the mirror of the
    CPython adapter's backscan.

    Between the element expression and the ``for`` keyword only whitespace
    and COMMENTS can occur. Comments are common here in real code (a
    ``# type: ignore`` on the element line), which a whitespace-only scan
    walks straight into.
    """
    start = ctx.span(node).start
    src = ctx.unit.source
    j = start
    while j < len(src):
        if src[j].isspace():
            j += 1
            continue
        if src[j] == "#":
            newline = src.find("\n", j)
            j = len(src) if newline == -1 else newline + 1
            continue
        break
    if not (src.startswith("for", j) or src.startswith("async", j)):
        vocabulary_missing(
            blame=node,
            owner="libcst_adapter._comp_for_anchor",
            observed=f"no 'for'/'async' keyword at comprehension clause start {j}",
            requested="'for' (optionally 'async for') opening the clause",
            fix="the forward-scan rule is wrong for this shape; extend it deliberately",
        )
    return Span(j, j)


def _comp_clauses(ctx: _Ctx, first: cst.CompFor) -> Tuple[BackendNode, ...]:
    """LibCST nests comprehension clauses via ``inner_for_in``; our
    ``generators`` is a flat tuple. Iterative, never recursive."""
    out: list[BackendNode] = []
    cur: Optional[cst.CompFor] = first
    while cur is not None:
        out.append(_Handle(ctx, cur))
        cur = cur.inner_for_in
    return tuple(out)


def _flatten_boolop(
    node: cst.BooleanOperation,
) -> tuple[cst.CSTNode, list[cst.BaseExpression]]:
    """``a and b and c`` is left-nested in LibCST and n-ary in our
    ``BoolOp.values``. Flatten same-operator chains; a parenthesized
    sub-operation is its own expression and is NOT flattened through."""
    op_type = type(node.operator)
    values: list[cst.BaseExpression] = [node.right]
    cur: cst.BaseExpression = node.left
    while (
        isinstance(cur, cst.BooleanOperation)
        and type(cur.operator) is op_type
        and not cur.lpar
    ):
        values.append(cur.right)
        cur = cur.left
    values.append(cur)
    values.reverse()
    return node.operator, values


def _concat_parts(node: cst.BaseExpression) -> list[cst.BaseExpression]:
    """Flatten a ``ConcatenatedString`` chain into its literal pieces."""
    parts: list[cst.BaseExpression] = []
    pending: list[cst.BaseExpression] = [node]
    while pending:
        item = pending.pop(0)
        if isinstance(item, cst.ConcatenatedString):
            pending = [item.left, item.right] + pending
            continue
        parts.append(item)
    return parts


# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------


def _param_handle(ctx: _Ctx, param: cst.Param, param_kind: str) -> BackendNode:
    """One formal parameter, anchored on its NAME token.

    Our spec excludes the ``*``/``**`` sigil from a ``Param`` span (it is an
    arity marker of the parameter LIST). LibCST's ``Param`` span includes
    it, so the name token is the anchor and annotation/default widen it by
    the envelope rule.
    """
    annotation = _unwrap_annotation(param.annotation)
    default = param.default
    return _Synth(
        kind="Param",
        raw_span=None,
        anchors=(ctx.span(param.name),),
        slots=(
            ("name", Leaf(param.name.value)),
            ("annotation", _maybe(ctx, annotation)),
            ("default", _maybe(ctx, default)),
            ("param_kind", Leaf(param_kind)),
        ),
        label=param.name.value,
    )


def _params(ctx: _Ctx, params: cst.Parameters) -> Children:
    out: list[BackendNode] = []
    for p in params.posonly_params:
        out.append(_param_handle(ctx, p, "positional_only"))
    for p in params.params:
        out.append(_param_handle(ctx, p, "positional_or_keyword"))
    star_arg = params.star_arg
    if isinstance(star_arg, cst.Param):
        out.append(_param_handle(ctx, star_arg, "vararg"))
    elif isinstance(star_arg, cst.ParamStar):
        pass  # bare ``*`` separator: a marker, not a parameter
    elif star_arg is not None and not isinstance(star_arg, cst.MaybeSentinel):
        vocabulary_missing(
            blame=star_arg,
            owner="libcst_adapter._params",
            observed=f"star_arg is {type(star_arg).__name__}",
            requested="a Param, a ParamStar, or absent",
            fix="add an explicit rule for this parameter shape",
        )
    for p in params.kwonly_params:
        out.append(_param_handle(ctx, p, "keyword_only"))
    if params.star_kwarg is not None:
        out.append(_param_handle(ctx, params.star_kwarg, "kwarg"))
    return Children(tuple(out))


# --------------------------------------------------------------------------
# Call / class arguments
# --------------------------------------------------------------------------


def _split_args(
    ctx: _Ctx, args: Sequence[cst.Arg]
) -> tuple[Tuple[BackendNode, ...], Tuple[BackendNode, ...]]:
    """CST ``Arg`` is one node for four shapes. Ours splits positional
    (including ``*spread``, which becomes ``Starred``) from keywords
    (including ``**spread``, a ``Keyword`` with ``arg is None``)."""
    positional: list[BackendNode] = []
    keywords: list[BackendNode] = []
    for arg in args:
        if arg.star == "*":
            positional.append(
                _Synth(
                    kind="Starred",
                    raw_span=ctx.span(arg),
                    slots=(("value", _child(ctx, arg.value)),),
                    label="*arg",
                )
            )
        elif arg.star == "**":
            keywords.append(
                _Synth(
                    kind="Keyword",
                    raw_span=ctx.span(arg),
                    slots=(("arg", Leaf(None)), ("value", _child(ctx, arg.value))),
                    label="**kwargs",
                )
            )
        elif arg.keyword is not None:
            keywords.append(
                _Synth(
                    kind="Keyword",
                    raw_span=ctx.span(arg),
                    slots=(
                        ("arg", Leaf(arg.keyword.value)),
                        ("value", _child(ctx, arg.value)),
                    ),
                    label=arg.keyword.value,
                )
            )
        else:
            positional.append(_Handle(ctx, arg.value))
    return tuple(positional), tuple(keywords)


# --------------------------------------------------------------------------
# Collection elements
# --------------------------------------------------------------------------


def _elements(ctx: _Ctx, elements: Sequence[cst.BaseElement]) -> Children:
    """``Element``/``StarredElement`` wrappers -> our expressions."""
    out: list[BackendNode] = []
    for el in elements:
        if isinstance(el, cst.StarredElement):
            out.append(
                _Synth(
                    kind="Starred",
                    raw_span=ctx.span(el),
                    slots=(("value", _child(ctx, el.value)),),
                    label="*element",
                )
            )
        elif isinstance(el, cst.Element):
            out.append(_Handle(ctx, el.value))
        else:
            vocabulary_missing(
                blame=el,
                owner="libcst_adapter._elements",
                observed=f"{type(el).__name__} in element position",
                requested="an Element or a StarredElement",
                fix="add an explicit rule for this element shape",
            )
    return Children(tuple(out))


def _dict_items(ctx: _Ctx, elements: Sequence[cst.BaseDictElement]) -> Children:
    out: list[BackendNode] = []
    for el in elements:
        if isinstance(el, cst.DictElement):
            out.append(
                _Synth(
                    kind="DictItem",
                    raw_span=None,
                    slots=(
                        ("key", _maybe(ctx, el.key)),
                        ("value", _child(ctx, el.value)),
                    ),
                    label="item",
                )
            )
        elif isinstance(el, cst.StarredDictElement):
            out.append(
                _Synth(
                    kind="DictItem",
                    raw_span=None,
                    slots=(
                        ("key", MaybeChild(None)),
                        ("value", _child(ctx, el.value)),
                    ),
                    label="**spread",
                )
            )
        else:
            vocabulary_missing(
                blame=el,
                owner="libcst_adapter._dict_items",
                observed=f"{type(el).__name__} in dict element position",
                requested="a DictElement or a StarredDictElement",
                fix="add an explicit rule for this dict entry shape",
            )
    return Children(tuple(out))


# --------------------------------------------------------------------------
# Subscripts
# --------------------------------------------------------------------------


def _has_comma(element: cst.SubscriptElement) -> bool:
    return isinstance(element.comma, cst.Comma)


def _subscript_slice(ctx: _Ctx, node: cst.Subscript) -> Child:
    """``a[x]`` is an expression subscript; ``a[x, y]`` AND ``a[x,]`` are
    tuple subscripts. The trailing comma is what makes a single-element
    subscript a tuple, so it is the discriminator, and it is inside the
    tuple's span — without it there is no tuple."""
    parts = list(node.slice)
    if len(parts) == 1 and not _has_comma(parts[0]):
        return Child(_slice_element(ctx, parts[0]))
    handles = tuple(_slice_element(ctx, p) for p in parts)
    span = ctx.span(parts[0].slice)
    for p in parts[1:]:
        span = span.envelope(ctx.span(p.slice))
    last = parts[-1]
    if _has_comma(last):
        span = span.envelope(ctx.span(last.comma))
    return Child(
        _Synth(
            kind="Tuple",
            raw_span=span,
            slots=(("elts", Children(handles)),),
            label="subscript-tuple",
        )
    )


def _slice_element(ctx: _Ctx, element: cst.SubscriptElement) -> BackendNode:
    inner = element.slice
    if isinstance(inner, cst.Index):
        return _Handle(ctx, inner.value)
    if isinstance(inner, cst.Slice):
        return _Handle(ctx, inner)
    vocabulary_missing(
        blame=inner,
        owner="libcst_adapter._slice_element",
        observed=f"{type(inner).__name__} in subscript position",
        requested="an Index or a Slice",
        fix="add an explicit rule for this subscript shape",
    )
    raise AssertionError("unreachable")


# --------------------------------------------------------------------------
# f-strings
# --------------------------------------------------------------------------


def _format_spec(
    ctx: _Ctx, spec: Optional[Sequence[cst.BaseFormattedStringContent]]
) -> MaybeChild:
    """Our ``FormattedValue.format_spec`` is a ``JoinedStr``; LibCST carries
    a bare content sequence with no wrapper node. Synthesize one, spanning
    its contents — i.e. the text AFTER the ``:``, per our ruling."""
    if spec is None:
        return MaybeChild(None)
    parts = list(spec)
    if not parts:
        vocabulary_missing(
            blame=spec,
            owner="libcst_adapter._format_spec",
            observed="an empty format spec with no content to span",
            requested="a spec with at least one content node, or no spec at all",
            fix="rule on the span of an empty format spec; never invent one",
        )
    span = ctx.span(parts[0])
    for p in parts[1:]:
        span = span.envelope(ctx.span(p))
    return MaybeChild(
        _Synth(
            kind="JoinedStr",
            raw_span=span,
            slots=(("values", _children(ctx, parts)),),
            label="format-spec",
        )
    )


_CONVERSIONS = {None: -1, "s": 115, "r": 114, "a": 97}


def _conversion(value: Optional[str]) -> int:
    code = _CONVERSIONS.get(value)
    if code is None:
        vocabulary_missing(
            blame=value,
            owner="libcst_adapter._conversion",
            observed=f"f-string conversion {value!r}",
            requested="one of !s, !r, !a, or none",
            fix="add the conversion deliberately; never guess a code",
        )
        raise AssertionError("unreachable")
    return code


# --------------------------------------------------------------------------
# Rules: one per LibCST node type we admit. No fallback.
# --------------------------------------------------------------------------

_Rule = Callable[[_Ctx, cst.CSTNode], Description]
_RULES: dict[str, _Rule] = {}


def _rule(*names: str) -> Callable[[_Rule], _Rule]:
    def register(fn: _Rule) -> _Rule:
        for name in names:
            _RULES[name] = fn
        return fn

    return register


def _desc(
    kind: str,
    span: Optional[Span],
    *slots: Tuple[str, Slot],
    anchors: Tuple[Span, ...] = (),
) -> Description:
    return Description(kind=kind, raw_span=span, anchors=anchors, slots=tuple(slots))


# --- module and statements -------------------------------------------------


@_rule("Module")
def _r_module(ctx: _Ctx, n: cst.Module) -> Description:
    return _desc(
        "Module",
        Span(0, len(ctx.unit.source)),
        ("body", Children(_statements(ctx, n.body))),
    )


@_rule("FunctionDef")
def _r_functiondef(ctx: _Ctx, n: cst.FunctionDef) -> Description:
    kind = "AsyncFunctionDef" if n.asynchronous is not None else "FunctionDef"
    return _desc(
        kind,
        ctx.span(n),
        ("name", Leaf(n.name.value)),
        ("params", _params(ctx, n.params)),
        ("body", Children(_statements(ctx, n.body))),
        (
            "decorators",
            Children(tuple(_Handle(ctx, d.decorator) for d in n.decorators)),
        ),
        ("returns", _maybe(ctx, _unwrap_annotation(n.returns))),
        ("type_params", _type_params(ctx, n.type_parameters)),
    )


@_rule("ClassDef")
def _r_classdef(ctx: _Ctx, n: cst.ClassDef) -> Description:
    bases, keywords = _split_args(ctx, list(n.bases) + list(n.keywords))
    return _desc(
        "ClassDef",
        ctx.span(n),
        ("name", Leaf(n.name.value)),
        ("binding_target", Child(_Handle(ctx, n.name))),
        ("bases", Children(bases)),
        ("keywords", Children(keywords)),
        ("body", Children(_statements(ctx, n.body))),
        (
            "decorators",
            Children(tuple(_Handle(ctx, d.decorator) for d in n.decorators)),
        ),
        ("type_params", _type_params(ctx, n.type_parameters)),
    )


def _type_params(ctx: _Ctx, node: Optional[cst.TypeParameters]) -> Children:
    if node is None:
        return Children(())
    return Children(tuple(_Handle(ctx, p.param) for p in node.params))


@_rule("TypeVar")
def _r_typevar(ctx: _Ctx, n: cst.TypeVar) -> Description:
    return _desc(
        "TypeVar",
        ctx.span(n),
        ("name", Leaf(n.name.value)),
        ("bound", _maybe(ctx, n.bound)),
    )


@_rule("ParamSpec")
def _r_paramspec(ctx: _Ctx, n: cst.ParamSpec) -> Description:
    return _desc("ParamSpec", ctx.span(n), ("name", Leaf(n.name.value)))


@_rule("TypeVarTuple")
def _r_typevartuple(ctx: _Ctx, n: cst.TypeVarTuple) -> Description:
    return _desc("TypeVarTuple", ctx.span(n), ("name", Leaf(n.name.value)))


@_rule("TypeAlias")
def _r_typealias(ctx: _Ctx, n: cst.TypeAlias) -> Description:
    return _desc(
        "TypeAlias",
        ctx.span(n),
        ("name", _child(ctx, n.name)),
        ("type_params", _type_params(ctx, n.type_parameters)),
        ("value", _child(ctx, n.value)),
    )


@_rule("Return")
def _r_return(ctx: _Ctx, n: cst.Return) -> Description:
    return _desc("Return", ctx.span(n), ("value", _maybe(ctx, n.value)))


@_rule("Del")
def _r_del(ctx: _Ctx, n: cst.Del) -> Description:
    target = n.target
    # ``del a, b``: our Delete.targets is n-ary; LibCST wraps in a bare Tuple.
    if isinstance(target, cst.Tuple) and not target.lpar:
        targets = _elements(ctx, target.elements)
    else:
        targets = Children((_Handle(ctx, target),))
    return _desc("Delete", ctx.span(n), ("targets", targets))


@_rule("Assign")
def _r_assign(ctx: _Ctx, n: cst.Assign) -> Description:
    return _desc(
        "Assign",
        ctx.span(n),
        ("targets", Children(tuple(_Handle(ctx, t.target) for t in n.targets))),
        ("value", _child(ctx, n.value)),
    )


@_rule("AugAssign")
def _r_augassign(ctx: _Ctx, n: cst.AugAssign) -> Description:
    return _desc(
        "AugAssign",
        ctx.span(n),
        ("target", _child(ctx, n.target)),
        ("op", OpLeaf(_op(_AUG_OPS, n.operator, "augassign"))),
        ("value", _child(ctx, n.value)),
    )


@_rule("AnnAssign")
def _r_annassign(ctx: _Ctx, n: cst.AnnAssign) -> Description:
    return _desc(
        "AnnAssign",
        ctx.span(n),
        ("target", _child(ctx, n.target)),
        ("annotation", Child(_Handle(ctx, n.annotation.annotation))),
        ("value", _maybe(ctx, n.value)),
        ("simple", Leaf(isinstance(n.target, cst.Name))),
    )


@_rule("For")
def _r_for(ctx: _Ctx, n: cst.For) -> Description:
    kind = "AsyncFor" if n.asynchronous is not None else "For"
    return _desc(
        kind,
        ctx.span(n),
        ("target", _child(ctx, n.target)),
        ("iter", _child(ctx, n.iter)),
        ("body", Children(_statements(ctx, n.body))),
        ("orelse", Children(_statements(ctx, n.orelse))),
    )


@_rule("While")
def _r_while(ctx: _Ctx, n: cst.While) -> Description:
    return _desc(
        "While",
        ctx.span(n),
        ("test", _child(ctx, n.test)),
        ("body", Children(_statements(ctx, n.body))),
        ("orelse", Children(_statements(ctx, n.orelse))),
    )


@_rule("If")
def _r_if(ctx: _Ctx, n: cst.If) -> Description:
    return _desc(
        "If",
        ctx.span(n),
        ("test", _child(ctx, n.test)),
        ("body", Children(_statements(ctx, n.body))),
        ("orelse", Children(_orelse(ctx, n.orelse))),
    )


@_rule("With")
def _r_with(ctx: _Ctx, n: cst.With) -> Description:
    kind = "AsyncWith" if n.asynchronous is not None else "With"
    return _desc(
        kind,
        ctx.span(n),
        ("items", _children(ctx, n.items)),
        ("body", Children(_statements(ctx, n.body))),
    )


@_rule("WithItem")
def _r_withitem(ctx: _Ctx, n: cst.WithItem) -> Description:
    asname = n.asname
    return _desc(
        "WithItem",
        None,
        ("context_expr", _child(ctx, n.item)),
        ("optional_vars", _maybe(ctx, None if asname is None else asname.name)),
    )


@_rule("Raise")
def _r_raise(ctx: _Ctx, n: cst.Raise) -> Description:
    cause = n.cause
    return _desc(
        "Raise",
        ctx.span(n),
        ("exc", _maybe(ctx, n.exc)),
        ("cause", _maybe(ctx, None if cause is None else cause.item)),
    )


@_rule("Try", "TryStar")
def _r_try(ctx: _Ctx, n: cst.CSTNode) -> Description:
    kind = "TryStar" if isinstance(n, cst.TryStar) else "Try"
    return _desc(
        kind,
        ctx.span(n),
        ("body", Children(_statements(ctx, n.body))),  # type: ignore[attr-defined]
        ("handlers", _children(ctx, n.handlers)),  # type: ignore[attr-defined]
        ("orelse", Children(_statements(ctx, n.orelse))),  # type: ignore[attr-defined]
        ("finalbody", Children(_statements(ctx, n.finalbody))),  # type: ignore[attr-defined]
    )


@_rule("ExceptHandler", "ExceptStarHandler")
def _r_excepthandler(ctx: _Ctx, n: cst.CSTNode) -> Description:
    return _desc(
        "ExceptHandler",
        ctx.span(n),
        ("type_", _maybe(ctx, n.type)),  # type: ignore[attr-defined]
        ("name", Leaf(_asname_str(n.name))),  # type: ignore[attr-defined]
        ("body", Children(_statements(ctx, n.body))),  # type: ignore[attr-defined]
    )


@_rule("Assert")
def _r_assert(ctx: _Ctx, n: cst.Assert) -> Description:
    return _desc(
        "Assert",
        ctx.span(n),
        ("test", _child(ctx, n.test)),
        ("msg", _maybe(ctx, n.msg)),
    )


@_rule("Import")
def _r_import(ctx: _Ctx, n: cst.Import) -> Description:
    return _desc("Import", ctx.span(n), ("names", _children(ctx, n.names)))


@_rule("ImportFrom")
def _r_importfrom(ctx: _Ctx, n: cst.ImportFrom) -> Description:
    module = None if n.module is None else _dotted(n.module)
    names = n.names
    if isinstance(names, cst.ImportStar):
        aliases: Tuple[BackendNode, ...] = (
            _Synth(
                kind="ImportAlias",
                raw_span=ctx.span(names),
                slots=(("name", Leaf("*")), ("asname", Leaf(None))),
                label="import-star",
            ),
        )
    else:
        aliases = tuple(_Handle(ctx, a) for a in names)
    return _desc(
        "ImportFrom",
        ctx.span(n),
        ("module", Leaf(module)),
        ("names", Children(aliases)),
        ("level", Leaf(len(n.relative))),
    )


@_rule("ImportAlias")
def _r_importalias(ctx: _Ctx, n: cst.ImportAlias) -> Description:
    return _desc(
        "ImportAlias",
        ctx.span(n),
        ("name", Leaf(_dotted(n.name))),
        ("asname", Leaf(_asname_str(n.asname))),
    )


@_rule("Global")
def _r_global(ctx: _Ctx, n: cst.Global) -> Description:
    return _desc(
        "Global", ctx.span(n), ("names", Leaf(tuple(i.name.value for i in n.names)))
    )


@_rule("Nonlocal")
def _r_nonlocal(ctx: _Ctx, n: cst.Nonlocal) -> Description:
    return _desc(
        "Nonlocal", ctx.span(n), ("names", Leaf(tuple(i.name.value for i in n.names)))
    )


@_rule("Expr")
def _r_expr(ctx: _Ctx, n: cst.Expr) -> Description:
    return _desc("Expr", ctx.span(n), ("value", _child(ctx, n.value)))


@_rule("Pass")
def _r_pass(ctx: _Ctx, n: cst.Pass) -> Description:
    return _desc("Pass", ctx.span(n))


@_rule("Break")
def _r_break(ctx: _Ctx, n: cst.Break) -> Description:
    return _desc("Break", ctx.span(n))


@_rule("Continue")
def _r_continue(ctx: _Ctx, n: cst.Continue) -> Description:
    return _desc("Continue", ctx.span(n))


# --- match -----------------------------------------------------------------


@_rule("Match")
def _r_match(ctx: _Ctx, n: cst.Match) -> Description:
    return _desc(
        "Match",
        ctx.span(n),
        ("subject", _child(ctx, n.subject)),
        ("cases", _children(ctx, n.cases)),
    )


@_rule("MatchCase")
def _r_matchcase(ctx: _Ctx, n: cst.MatchCase) -> Description:
    return _desc(
        "MatchCase",
        None,
        ("pattern", _child(ctx, n.pattern)),
        ("guard", _maybe(ctx, n.guard)),
        ("body", Children(_statements(ctx, n.body))),
    )


@_rule("MatchValue")
def _r_matchvalue(ctx: _Ctx, n: cst.MatchValue) -> Description:
    return _desc("MatchValue", ctx.span(n), ("value", _child(ctx, n.value)))


@_rule("MatchSingleton")
def _r_matchsingleton(ctx: _Ctx, n: cst.MatchSingleton) -> Description:
    return _desc(
        "MatchSingleton", ctx.span(n), ("value", Leaf(_singleton(n.value.value)))
    )


def _singleton(text: str) -> object:
    table: dict[str, object] = {"True": True, "False": False, "None": None}
    if text not in table:
        vocabulary_missing(
            blame=text,
            owner="libcst_adapter._singleton",
            observed=f"match singleton {text!r}",
            requested="True, False, or None",
            fix="add the singleton deliberately; never guess a value",
        )
    return table[text]


@_rule("MatchList", "MatchTuple", "MatchSequence")
def _r_matchsequence(ctx: _Ctx, n: cst.CSTNode) -> Description:
    return _desc(
        "MatchSequence",
        ctx.span(n),
        ("patterns", _match_patterns(ctx, n.patterns)),  # type: ignore[attr-defined]
    )


def _match_patterns(ctx: _Ctx, elements: Sequence[cst.CSTNode]) -> Children:
    out: list[BackendNode] = []
    for el in elements:
        if isinstance(el, cst.MatchSequenceElement):
            out.append(_Handle(ctx, el.value))
        elif isinstance(el, cst.MatchStar):
            out.append(_Handle(ctx, el))
        else:
            vocabulary_missing(
                blame=el,
                owner="libcst_adapter._match_patterns",
                observed=f"{type(el).__name__} in match sequence position",
                requested="a MatchSequenceElement or a MatchStar",
                fix="add an explicit rule for this pattern element",
            )
    return Children(tuple(out))


@_rule("MatchStar")
def _r_matchstar(ctx: _Ctx, n: cst.MatchStar) -> Description:
    name = n.name
    return _desc(
        "MatchStar",
        ctx.span(n),
        ("name", Leaf(None if name is None else name.value)),
    )


@_rule("MatchMapping")
def _r_matchmapping(ctx: _Ctx, n: cst.MatchMapping) -> Description:
    rest = n.rest
    return _desc(
        "MatchMapping",
        ctx.span(n),
        ("keys", Children(tuple(_Handle(ctx, e.key) for e in n.elements))),
        ("patterns", Children(tuple(_Handle(ctx, e.pattern) for e in n.elements))),
        ("rest", Leaf(None if rest is None else rest.value)),
    )


@_rule("MatchClass")
def _r_matchclass(ctx: _Ctx, n: cst.MatchClass) -> Description:
    return _desc(
        "MatchClass",
        ctx.span(n),
        ("cls_", _child(ctx, n.cls)),
        ("patterns", _match_patterns(ctx, n.patterns)),
        ("kwd_attrs", Leaf(tuple(k.key.value for k in n.kwds))),
        ("kwd_patterns", Children(tuple(_Handle(ctx, k.pattern) for k in n.kwds))),
    )


@_rule("MatchAs")
def _r_matchas(ctx: _Ctx, n: cst.MatchAs) -> Description:
    name = n.name
    return _desc(
        "MatchAs",
        ctx.span(n),
        ("pattern", _maybe(ctx, n.pattern)),
        ("name", Leaf(None if name is None else name.value)),
    )


@_rule("MatchOr")
def _r_matchor(ctx: _Ctx, n: cst.MatchOr) -> Description:
    return _desc(
        "MatchOr",
        ctx.span(n),
        ("patterns", Children(tuple(_Handle(ctx, e.pattern) for e in n.patterns))),
    )


# --- expressions -----------------------------------------------------------


@_rule("Name")
def _r_name(ctx: _Ctx, n: cst.Name) -> Description:
    # LibCST spells True/False/None as Name; ours are Constants.
    if n.value in ("True", "False", "None"):
        return _desc(
            "Constant",
            ctx.span(n),
            ("value", Leaf(_singleton(n.value))),
            ("literal_kind", Leaf(None)),
        )
    return _desc("Name", ctx.span(n), ("id", Leaf(n.value)))


@_rule("Integer", "Float", "Imaginary")
def _r_number(ctx: _Ctx, n: cst.CSTNode) -> Description:
    return _desc(
        "Constant",
        ctx.span(n),
        ("value", Leaf(n.evaluated_value)),  # type: ignore[attr-defined]
        ("literal_kind", Leaf(None)),
    )


@_rule("Ellipsis")
def _r_ellipsis(ctx: _Ctx, n: cst.Ellipsis) -> Description:
    return _desc(
        "Constant", ctx.span(n), ("value", Leaf(...)), ("literal_kind", Leaf(None))
    )


@_rule("SimpleString")
def _r_simplestring(ctx: _Ctx, n: cst.SimpleString) -> Description:
    return _desc(
        "Constant",
        ctx.span(n),
        ("value", Leaf(n.evaluated_value)),
        ("literal_kind", Leaf("u" if n.prefix.lower() == "u" else None)),
    )


@_rule("ConcatenatedString")
def _r_concatstring(ctx: _Ctx, n: cst.ConcatenatedString) -> Description:
    parts = _concat_parts(n)
    span = ctx.span(n)
    if any(isinstance(p, cst.FormattedString) for p in parts):
        # Any f-string piece makes the whole literal a JoinedStr, whose
        # values are the pieces' contents in order.
        values: list[BackendNode] = []
        for p in parts:
            if isinstance(p, cst.FormattedString):
                values.extend(_Handle(ctx, c) for c in p.parts)
            else:
                values.append(_Handle(ctx, p))
        return _desc("JoinedStr", span, ("values", Children(tuple(values))))
    values = [piece.evaluated_value for piece in parts]  # type: ignore[attr-defined]
    if all(isinstance(v, bytes) for v in values):
        joined: object = b"".join(values)
    elif all(isinstance(v, str) for v in values):
        joined = "".join(values)
    else:
        # LibCST parsed source CPython itself would reject at compile time
        # (mixed str/bytes implicit concatenation): the backend's own
        # output is structurally invalid, not a vocabulary gap.
        backend_defect(
            blame=n,
            owner="libcst_adapter._r_concatstring",
            observed="implicit concatenation mixing str and bytes pieces",
            requested="pieces of one literal type",
            fix="this is not valid Python; the backend accepted something CPython could not parse",
        )
    return _desc(
        "Constant", span, ("value", Leaf(joined)), ("literal_kind", Leaf(None))
    )


@_rule("FormattedString")
def _r_formattedstring(ctx: _Ctx, n: cst.FormattedString) -> Description:
    return _desc("JoinedStr", ctx.span(n), ("values", _children(ctx, n.parts)))


@_rule("FormattedStringText")
def _r_fstringtext(ctx: _Ctx, n: cst.FormattedStringText) -> Description:
    return _desc(
        "Constant",
        ctx.span(n),
        ("value", Leaf(n.value)),
        ("literal_kind", Leaf(None)),
    )


@_rule("FormattedStringExpression")
def _r_fstringexpr(ctx: _Ctx, n: cst.FormattedStringExpression) -> Description:
    return _desc(
        "FormattedValue",
        ctx.span(n),
        ("value", _child(ctx, n.expression)),
        ("conversion", Leaf(_conversion(n.conversion))),
        ("format_spec", _format_spec(ctx, n.format_spec)),
    )


@_rule("Attribute")
def _r_attribute(ctx: _Ctx, n: cst.Attribute) -> Description:
    return _desc(
        "Attribute",
        ctx.span(n),
        ("value", _child(ctx, n.value)),
        ("attr", Leaf(n.attr.value)),
    )


@_rule("Subscript")
def _r_subscript(ctx: _Ctx, n: cst.Subscript) -> Description:
    return _desc(
        "Subscript",
        ctx.span(n),
        ("value", _child(ctx, n.value)),
        ("slice_", _subscript_slice(ctx, n)),
    )


@_rule("Slice")
def _r_slice(ctx: _Ctx, n: cst.Slice) -> Description:
    return _desc(
        "Slice",
        ctx.span(n),
        ("lower", _maybe(ctx, n.lower)),
        ("upper", _maybe(ctx, n.upper)),
        ("step", _maybe(ctx, n.step)),
    )


@_rule("Call")
def _r_call(ctx: _Ctx, n: cst.Call) -> Description:
    args, keywords = _split_args(ctx, n.args)
    return _desc(
        "Call",
        ctx.span(n),
        ("func", _child(ctx, n.func)),
        ("args", Children(args)),
        ("keywords", Children(keywords)),
    )


@_rule("Await")
def _r_await(ctx: _Ctx, n: cst.Await) -> Description:
    return _desc("Await", ctx.span(n), ("value", _child(ctx, n.expression)))


@_rule("Yield")
def _r_yield(ctx: _Ctx, n: cst.Yield) -> Description:
    value = n.value
    if isinstance(value, cst.From):
        return _desc("YieldFrom", ctx.span(n), ("value", _child(ctx, value.item)))
    return _desc("Yield", ctx.span(n), ("value", _maybe(ctx, value)))


@_rule("Lambda")
def _r_lambda(ctx: _Ctx, n: cst.Lambda) -> Description:
    return _desc(
        "Lambda",
        ctx.span(n),
        ("params", _params(ctx, n.params)),
        ("body", _child(ctx, n.body)),
    )


@_rule("IfExp")
def _r_ifexp(ctx: _Ctx, n: cst.IfExp) -> Description:
    return _desc(
        "IfExp",
        ctx.span(n),
        ("test", _child(ctx, n.test)),
        ("body", _child(ctx, n.body)),
        ("orelse", _child(ctx, n.orelse)),
    )


@_rule("BinaryOperation")
def _r_binop(ctx: _Ctx, n: cst.BinaryOperation) -> Description:
    return _desc(
        "BinOp",
        ctx.span(n),
        ("left", _child(ctx, n.left)),
        ("op", OpLeaf(_op(_BINARY_OPS, n.operator, "binop"))),
        ("right", _child(ctx, n.right)),
    )


@_rule("UnaryOperation")
def _r_unaryop(ctx: _Ctx, n: cst.UnaryOperation) -> Description:
    return _desc(
        "UnaryOp",
        ctx.span(n),
        ("op", OpLeaf(_op(_UNARY_OPS, n.operator, "unaryop"))),
        ("operand", _child(ctx, n.expression)),
    )


@_rule("BooleanOperation")
def _r_boolop(ctx: _Ctx, n: cst.BooleanOperation) -> Description:
    operator, values = _flatten_boolop(n)
    return _desc(
        "BoolOp",
        ctx.span(n),
        ("op", OpLeaf(_op(_BOOL_OPS, operator, "boolop"))),
        ("values", _children(ctx, values)),
    )


@_rule("Comparison")
def _r_comparison(ctx: _Ctx, n: cst.Comparison) -> Description:
    return _desc(
        "Compare",
        ctx.span(n),
        ("left", _child(ctx, n.left)),
        (
            "ops",
            OpsLeaf(
                tuple(_op(_COMPARE_OPS, t.operator, "compare") for t in n.comparisons)
            ),
        ),
        (
            "comparators",
            Children(tuple(_Handle(ctx, t.comparator) for t in n.comparisons)),
        ),
    )


@_rule("NamedExpr")
def _r_namedexpr(ctx: _Ctx, n: cst.NamedExpr) -> Description:
    return _desc(
        "NamedExpr",
        ctx.span(n),
        ("target", _child(ctx, n.target)),
        ("value", _child(ctx, n.value)),
    )


@_rule("Tuple")
def _r_tuple(ctx: _Ctx, n: cst.Tuple) -> Description:
    return _desc("Tuple", _tuple_span(ctx, n), ("elts", _elements(ctx, n.elements)))


@_rule("List")
def _r_list(ctx: _Ctx, n: cst.List) -> Description:
    return _desc("List", ctx.span(n), ("elts", _elements(ctx, n.elements)))


@_rule("Set")
def _r_set(ctx: _Ctx, n: cst.Set) -> Description:
    return _desc("Set", ctx.span(n), ("elts", _elements(ctx, n.elements)))


@_rule("Dict")
def _r_dict(ctx: _Ctx, n: cst.Dict) -> Description:
    return _desc("Dict", ctx.span(n), ("items", _dict_items(ctx, n.elements)))


@_rule("StarredElement")
def _r_starredelement(ctx: _Ctx, n: cst.StarredElement) -> Description:
    return _desc("Starred", ctx.span(n), ("value", _child(ctx, n.value)))


@_rule("ListComp")
def _r_listcomp(ctx: _Ctx, n: cst.ListComp) -> Description:
    return _desc(
        "ListComp",
        ctx.span(n),
        ("elt", _child(ctx, n.elt)),
        ("generators", Children(_comp_clauses(ctx, n.for_in))),
    )


@_rule("SetComp")
def _r_setcomp(ctx: _Ctx, n: cst.SetComp) -> Description:
    return _desc(
        "SetComp",
        ctx.span(n),
        ("elt", _child(ctx, n.elt)),
        ("generators", Children(_comp_clauses(ctx, n.for_in))),
    )


@_rule("GeneratorExp")
def _r_genexp(ctx: _Ctx, n: cst.GeneratorExp) -> Description:
    return _desc(
        "GeneratorExp",
        ctx.span(n),
        ("elt", _child(ctx, n.elt)),
        ("generators", Children(_comp_clauses(ctx, n.for_in))),
    )


@_rule("DictComp")
def _r_dictcomp(ctx: _Ctx, n: cst.DictComp) -> Description:
    return _desc(
        "DictComp",
        ctx.span(n),
        ("key", _child(ctx, n.key)),
        ("value", _child(ctx, n.value)),
        ("generators", Children(_comp_clauses(ctx, n.for_in))),
    )


@_rule("CompFor")
def _r_compfor(ctx: _Ctx, n: cst.CompFor) -> Description:
    return Description(
        kind="Comprehension",
        raw_span=None,
        anchors=(_comp_for_anchor(ctx, n),),
        slots=(
            ("target", _child(ctx, n.target)),
            ("iter", _child(ctx, n.iter)),
            ("ifs", Children(tuple(_Handle(ctx, i.test) for i in n.ifs))),
            ("is_async", Leaf(n.asynchronous is not None)),
        ),
    )


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------


def _describe(ctx: _Ctx, node: cst.CSTNode) -> Description:
    rule = _RULES.get(type(node).__name__)
    if rule is None:
        vocabulary_missing(
            blame=node,
            owner="libcst_adapter._describe",
            observed=f"libcst {type(node).__name__} has no adapter rule",
            requested="an explicit rule mapping this CST shape into tree terms",
            fix="add the rule in libcst_adapter.py — never a permissive fallback",
        )
        raise AssertionError("unreachable")
    return rule(ctx, node)


class LibCSTBackend(Backend):
    """The second backend: Instagram's Rust-backed parser, behind the tree.

    Does not call CPython's ``compile()`` — which is the frame #5932's
    SIGSEGV lives in.
    """

    name = "libcst"

    def root(self, unit: SourceUnit) -> BackendNode:
        try:
            module = cst.parse_module(unit.source)
        except cst.ParserSyntaxError as err:
            # PartialParserSyntaxError (raised internally on some statement/
            # param shapes) is always upconverted to ParserSyntaxError before
            # it reaches parse_module (libcst._parser.base_parser) — this is
            # the one exception type that escapes LibCST's own parser.
            raise BackendCouldNotParse(
                backend=self.name, file=unit.filename, reason=str(err)
            ) from err
        wrapper = MetadataWrapper(module, unsafe_skip_copy=True)
        positions = wrapper.resolve(PositionProvider)
        return _Handle(_Ctx(unit, positions), module)
