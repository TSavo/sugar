"""parso backend adapter (#5940, #5932) — candidate #3.

THE ONLY MODULE IN THIS PACKAGE THAT MAY NAME ``parso``. Same read-only
contract as ``cpython_adapter`` / ``libcst_adapter``: ``parse(unit) ->
handle``, and per handle a single ``describe()`` giving our kind, our
codepoint span, and our fields as slots.

Why parso is a credible third candidate: it is pure Python (no C extension,
no ``compile()``, cannot SIGSEGV the way #5932 isolated CPython's own
``ast.parse`` doing), has explicit *error recovery* (it is what Jedi and
``black``'s blib2to3 fork use to parse code with syntax errors), and its
positions are already codepoint columns — matching our span spec exactly,
with no byte->codepoint seam to build (see spans.py; same property as
LibCST, the opposite of CPython's UTF-8 byte columns).

MAPPING NOTES — parso is a raw CST (blib2to3/lib2to3 family grammar), NOT
AST-shaped. Concretely, versus ``ast``/our tree:

- parso collapses any grammar node with exactly one child down to that
  child (no wrapper). This does a lot of our unwrapping for free: a bare
  name expression is never wrapped in ``test``/``or_test``/... at all.
- Binary operator chains (``arith_expr``, ``term``, ``expr``, ``xor_expr``,
  ``and_expr``, ``shift_expr``) are FLAT n-ary nodes (operand, op, operand,
  op, operand, ...) that we must fold pairwise, left-associative, into
  nested ``BinOp`` — ast is strictly binary. Each intermediate fold's span
  is [first-operand-start, this-step's-right-operand-end], never the whole
  chain's span except at the final fold.
- ``or_test`` / ``and_test`` are already flat n-ary matching our
  ``BoolOp.values`` directly — no folding needed, and every operator in one
  such node is provably the same (mixed precedence is expressed as nesting
  a different node type, not multiple operators in one flat list).
- ``comparison`` is flat n-ary matching ``Compare`` directly: alternating
  operand / ``comp_op``-or-single-token / operand.
- Grouping parens live inside an ``atom`` node (``'(' testlist_comp ')'``)
  and are never included in the inner expression's own span — matching our
  ruling — with the one ruled exception: a parenthesized tuple display's
  parens ARE part of the ``Tuple`` span, so that one case takes the atom's
  own span explicitly rather than the envelope of its elements.
- ``atom_expr`` is ``['await'] atom trailer*`` — we fold trailers
  (``.NAME``, ``(...)``, ``[...]``) into nested ``Attribute`` / ``Call`` /
  ``Subscript``, spanning from the atom's start to each trailer's own end
  (already correct for CPython's multi-line-call ruling, since the
  trailer's own span already reaches its closing token).
- A subscript's comma list becomes a synthetic bare ``Tuple`` (no
  parens/brackets of its own) exactly as CPython's own post-3.9 ``ast``
  does for ``arr[i, j]`` — envelope-spanned over its elements.
- f-strings (``fstring`` / ``fstring_expr`` / ``fstring_format_spec``) are
  parso's own first-class grammar (not a lexer hack); translated to
  ``JoinedStr`` / ``FormattedValue`` per the same rulings as the other two
  adapters.
- ``match_stmt`` / patterns: parso 0.8's grammar supports PEP 634, but this
  adapter's pattern coverage is intentionally partial — see the panics in
  ``_pattern`` below. An unhandled pattern shape is a MISSING, not a guess.

A parso shape with no rule here panics as a MISSING at the boundary. There
is no generic fallback and no ``getattr`` sniffing on children: an unmapped
CST node/shape is the conformance finding itself.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import parso
from parso.tree import BaseNode, Leaf

from .backend import (
    Child,
    Children,
    Description,
    Leaf as SlotLeaf,
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
from .panic import vocabulary_missing
from .spans import Span

ParsoNode = object  # parso.tree.NodeOrLeaf, kept untyped at the boundary


def _is_leaf(node: ParsoNode) -> bool:
    return isinstance(node, Leaf)


def _span(unit: SourceUnit, node: ParsoNode) -> Span:
    table = unit.line_table
    sl, sc = node.start_pos
    el, ec = node.end_pos
    return Span(table.offset(sl, sc), table.offset(el, ec))


def _kids(node: ParsoNode) -> List[ParsoNode]:
    return list(getattr(node, "children", ()))


class _Handle(BackendNode):
    """Read-only view of one real parso node."""

    __slots__ = ("_unit", "_node", "_desc")

    def __init__(self, unit: SourceUnit, node: ParsoNode) -> None:
        self._unit = unit
        self._node = node
        self._desc: Optional[Description] = None

    @property
    def minting_unit(self):
        """Parsed out of this unit's text, so its span is that unit's."""
        return self._unit

    def describe(self) -> Description:
        if self._desc is None:
            self._desc = _describe(self._unit, self._node)
        return self._desc

    def __repr__(self) -> str:  # pragma: no cover
        t = getattr(self._node, "type", "?")
        return f"<parso-handle {t} in {self._unit.filename}>"


class _Fixed(BackendNode):
    """A synthetic constituent: precomputed Description, no single backing
    node (a fold step, a flattened tuple, a folded trailer chain, ...)."""

    __slots__ = ("_desc",)

    def __init__(self, desc: Description) -> None:
        self._desc = desc

    def describe(self) -> Description:
        return self._desc

    def __repr__(self) -> str:  # pragma: no cover
        return f"<parso-fixed {self._desc.kind}>"


def _fixed(
    kind: str,
    raw_span: Optional[Span],
    slots: Tuple[Tuple[str, Slot], ...],
    anchors: Tuple[Span, ...] = (),
) -> _Fixed:
    return _Fixed(
        Description(kind=kind, raw_span=raw_span, anchors=anchors, slots=slots)
    )


def _h(unit: SourceUnit, node: ParsoNode) -> BackendNode:
    return _Handle(unit, node)


# --------------------------------------------------------------------------
# Binary operator token -> our Operator kind
# --------------------------------------------------------------------------

_BIN_TOKEN = {
    "+": "Add",
    "-": "Sub",
    "*": "Mult",
    "@": "MatMult",
    "/": "Div",
    "%": "Mod",
    "**": "Pow",
    "<<": "LShift",
    ">>": "RShift",
    "|": "BitOr",
    "^": "BitXor",
    "&": "BitAnd",
    "//": "FloorDiv",
}
_AUG_TOKEN = {
    "+=": "Add",
    "-=": "Sub",
    "*=": "Mult",
    "@=": "MatMult",
    "/=": "Div",
    "%=": "Mod",
    "**=": "Pow",
    "<<=": "LShift",
    ">>=": "RShift",
    "|=": "BitOr",
    "^=": "BitXor",
    "&=": "BitAnd",
    "//=": "FloorDiv",
}
_UNARY_TOKEN = {"+": "UAdd", "-": "USub", "~": "Invert"}
_CMP_TOKEN = {
    "<": "Lt",
    ">": "Gt",
    "==": "Eq",
    ">=": "GtE",
    "<=": "LtE",
    "<>": "NotEq",
    "!=": "NotEq",
}


def _cmp_op(node: ParsoNode) -> Operator:
    if node.type == "comp_op":
        text = " ".join(c.value for c in _kids(node))
        if text == "not in":
            return operator_for("NotIn", blame=node)
        if text == "is not":
            return operator_for("IsNot", blame=node)
        vocabulary_missing(
            blame=node,
            owner="parso_adapter._cmp_op",
            observed=f"comp_op token {text!r} not recognized",
            requested="one of: not in, is not",
            fix="extend the comp_op mapping deliberately",
        )
    text = node.value
    if text == "in":
        return operator_for("In", blame=node)
    if text == "is":
        return operator_for("Is", blame=node)
    kind = _CMP_TOKEN.get(text)
    if kind is None:
        vocabulary_missing(
            blame=node,
            owner="parso_adapter._cmp_op",
            observed=f"comparison token {text!r} not recognized",
            requested="a known comparison operator token",
            fix="extend _CMP_TOKEN deliberately",
        )
    return operator_for(kind, blame=node)


# --------------------------------------------------------------------------
# Folds
# --------------------------------------------------------------------------


def _fold_binop(unit: SourceUnit, node: ParsoNode) -> BackendNode:
    """Flat n-ary chain (arith_expr/term/expr/xor_expr/and_expr/shift_expr)
    -> nested left-associative BinOp handles."""
    kids = _kids(node)
    first_start = _span(unit, kids[0]).start
    acc = _h(unit, kids[0])
    i = 1
    while i < len(kids):
        op_tok = kids[i]
        right_node = kids[i + 1]
        kind = _BIN_TOKEN.get(op_tok.value)
        if kind is None:
            vocabulary_missing(
                blame=op_tok,
                owner="parso_adapter._fold_binop",
                observed=f"binary operator token {op_tok.value!r} not recognized",
                requested="a known binary operator token",
                fix="extend _BIN_TOKEN deliberately",
            )
        right = _h(unit, right_node)
        end = _span(unit, right_node).end
        acc = _fixed(
            "BinOp",
            Span(first_start, end),
            (
                ("left", Child(acc)),
                ("op", OpLeaf(operator_for(kind, blame=op_tok))),
                ("right", Child(right)),
            ),
        )
        i += 2
    return acc


def _boolop(unit: SourceUnit, node: ParsoNode, op_kind: str) -> Description:
    values = tuple(_h(unit, c) for c in _kids(node) if not _is_leaf(c))
    return Description(
        kind="BoolOp",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("op", OpLeaf(operator_for(op_kind, blame=node))),
            ("values", Children(values)),
        ),
    )


def _compare(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    left = _h(unit, kids[0])
    ops: List[Operator] = []
    comparators: List[BackendNode] = []
    i = 1
    while i < len(kids):
        ops.append(_cmp_op(kids[i]))
        comparators.append(_h(unit, kids[i + 1]))
        i += 2
    return Description(
        kind="Compare",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("left", Child(left)),
            ("ops", OpsLeaf(tuple(ops))),
            ("comparators", Children(tuple(comparators))),
        ),
    )


def _bare_tuple(
    unit: SourceUnit, elts: Sequence[ParsoNode], unit_span: Optional[Span] = None
) -> BackendNode:
    handles = tuple(_h(unit, e) for e in elts)
    return _fixed("Tuple", unit_span, (("elts", Children(handles)),))


def _strip_commas(kids: Sequence[ParsoNode]) -> List[ParsoNode]:
    return [c for c in kids if not (_is_leaf(c) and c.value == ",")]


# --------------------------------------------------------------------------
# atom / trailer folding
# --------------------------------------------------------------------------


def _keyword_str(kids: Sequence[ParsoNode], value: str) -> bool:
    return any(_is_leaf(c) and c.value == value for c in kids)


def _string_piece_kind(node: ParsoNode) -> str:
    # 'string' leaf, or 'fstring' node (first-class in parso >= 0.8)
    if _is_leaf(node):
        return "string"
    if node.type == "fstring":
        return "fstring"
    return "other"


def _constant_prefix_kind(text: str) -> Optional[str]:
    lowered = text.lower()
    i = 0
    while i < len(lowered) and lowered[i] not in ("'", '"'):
        i += 1
    return lowered[:i] if i else ""


def _join_string_pieces(unit: SourceUnit, pieces: Sequence[ParsoNode]) -> BackendNode:
    """Implicit string concatenation: one Constant, or JoinedStr if any
    piece is an f-string. Spans the first piece's start to the last's end
    (spec: including inter-piece whitespace/newlines)."""
    start = _span(unit, pieces[0]).start
    end = _span(unit, pieces[-1]).end
    span = Span(start, end)
    if any(_string_piece_kind(p) == "fstring" for p in pieces):
        values: List[BackendNode] = []
        for p in pieces:
            if _string_piece_kind(p) == "fstring":
                values.extend(_fstring_values(unit, p))
            else:
                values.append(_constant_leaf(unit, p))
        return _fixed("JoinedStr", span, (("values", Children(tuple(values))),))
    # plain string(s): concatenate python-literal values
    import ast as _pyast  # value decoding only — never structure; see docstring

    text = "".join(
        unit.source[_span(unit, p).start : _span(unit, p).end] for p in pieces
    )
    try:
        value = _pyast.literal_eval(text)
    except Exception:
        value = unit.source[start:end]
    return _fixed_constant(span, value)


# _Fixed has no _replace_value; build Constant directly instead.
def _fixed_constant(
    span: Span, value: object, literal_kind: Optional[str] = None
) -> BackendNode:
    return _fixed(
        "Constant",
        span,
        (("value", SlotLeaf(value)), ("literal_kind", SlotLeaf(literal_kind))),
    )


def _constant_leaf(unit: SourceUnit, node: ParsoNode) -> BackendNode:
    span = _span(unit, node)
    text = unit.source[span.start : span.end]
    if node.type == "number":
        import ast as _pyast

        value = _pyast.literal_eval(text)
        return _fixed_constant(span, value)
    if node.type == "string":
        import ast as _pyast

        try:
            value = _pyast.literal_eval(text)
        except Exception:
            value = text
        return _fixed_constant(span, value)
    if node.type == "keyword" and node.value in ("None", "True", "False"):
        value = {"None": None, "True": True, "False": False}[node.value]
        return _fixed_constant(span, value)
    if node.type == "operator" and node.value == "...":
        return _fixed_constant(span, Ellipsis)
    vocabulary_missing(
        blame=node,
        owner="parso_adapter._constant_leaf",
        observed=f"leaf {node.type}:{node.value!r} is not a recognized literal",
        requested="number, string, None/True/False, or Ellipsis",
        fix="extend _constant_leaf deliberately",
    )
    raise AssertionError("unreachable")


def _fstring_values(unit: SourceUnit, node: ParsoNode) -> List[BackendNode]:
    out: List[BackendNode] = []
    for c in _kids(node):
        if c.type == "fstring_string":
            span = _span(unit, c)
            out.append(_fixed_constant(span, unit.source[span.start : span.end]))
        elif c.type == "fstring_expr":
            out.append(_h(unit, c))
        elif c.type in ("fstring_start", "fstring_end"):
            continue
        else:
            vocabulary_missing(
                blame=c,
                owner="parso_adapter._fstring_values",
                observed=f"fstring child {c.type!r} not recognized",
                requested="fstring_string or fstring_expr",
                fix="extend _fstring_values deliberately",
            )
    return out


def _describe_fstring_expr(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = [c for c in _kids(node) if not (_is_leaf(c) and c.value in ("{", "}"))]
    # kids[0] is the value expression; optional '=' debug spec, '!' conversion,
    # ':' format_spec follow. Conversion / debug specifiers are rare in numpy
    # /pandas source; unrecognized trailing tokens panic rather than guess.
    value = kids[0]
    conversion = -1
    format_spec: Optional[ParsoNode] = None
    i = 1
    while i < len(kids):
        c = kids[i]
        if _is_leaf(c) and c.value == "!":
            conv_name = kids[i + 1]
            conversion = ord(conv_name.value)
            i += 2
            continue
        if c.type == "fstring_conversion":
            conv_kids = _kids(c)
            conv_name = conv_kids[-1]
            conversion = ord(conv_name.value)
            i += 1
            continue
        if c.type == "fstring_format_spec":
            format_spec = c
            i += 1
            continue
        vocabulary_missing(
            blame=c,
            owner="parso_adapter._describe_fstring_expr",
            observed=f"fstring_expr trailing token {c!r} not recognized",
            requested="'!' conversion or format spec",
            fix="extend _describe_fstring_expr deliberately",
        )
    format_spec_slot: Slot
    if format_spec is not None:
        spec_span = _span(unit, format_spec)
        spec_values = _fstring_values(unit, format_spec)
        format_spec_slot = MaybeChild(
            _fixed("JoinedStr", spec_span, (("values", Children(tuple(spec_values))),))
        )
    else:
        format_spec_slot = MaybeChild(None)
    return Description(
        kind="FormattedValue",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("value", Child(_h(unit, value))),
            ("conversion", SlotLeaf(conversion)),
            ("format_spec", format_spec_slot),
        ),
    )


def _fold_trailers(
    unit: SourceUnit,
    atom: ParsoNode,
    trailers: Sequence[ParsoNode],
    has_await: bool,
    await_start: Optional[int],
) -> BackendNode:
    base_start = _span(unit, atom).start
    acc: BackendNode = _h(unit, atom)
    for tr in trailers:
        tk = _kids(tr)
        first = tk[0]
        end = _span(unit, tr).end
        if first.value == ".":
            name_node = tk[1]
            acc = _fixed(
                "Attribute",
                Span(base_start, end),
                (("value", Child(acc)), ("attr", SlotLeaf(name_node.value))),
            )
        elif first.value == "(":
            args, keywords = _call_args(unit, tk[1:-1])
            acc = _fixed(
                "Call",
                Span(base_start, end),
                (
                    ("func", Child(acc)),
                    ("args", Children(tuple(args))),
                    ("keywords", Children(tuple(keywords))),
                ),
            )
        elif first.value == "[":
            slice_handle = _subscript_slice(unit, tk[1:-1])
            acc = _fixed(
                "Subscript",
                Span(base_start, end),
                (("value", Child(acc)), ("slice_", Child(slice_handle))),
            )
        else:
            vocabulary_missing(
                blame=trailer,
                owner="parso_adapter._fold_trailers",
                observed=f"trailer starting with {first.value!r} not recognized",
                requested="'.', '(' or '['",
                fix="extend _fold_trailers deliberately",
            )
    if has_await:
        acc = _fixed(
            "Await",
            Span(await_start, end if trailers else _span(unit, atom).end),
            (("value", Child(acc)),),
        )
    return acc


def _call_args(
    unit: SourceUnit, inner: Sequence[ParsoNode]
) -> Tuple[List[BackendNode], List[BackendNode]]:
    if len(inner) == 1 and inner[0].type == "arglist":
        inner = _kids(inner[0])
    inner = _strip_commas(inner)
    if (
        len(inner) == 1
        and inner[0].type == "argument"
        and any(c.type in ("comp_for", "sync_comp_for") for c in _kids(inner[0]))
    ):
        # bare generator expression as the sole call argument
        ik = _kids(inner[0])
        genexp = _genexp(unit, ik[0], ik[1:])
        return [genexp], []
    args: List[BackendNode] = []
    keywords: List[BackendNode] = []
    for item in inner:
        if item.type == "argument":
            ik = _kids(item)
            if _is_leaf(ik[0]) and ik[0].value == "**":
                keywords.append(
                    _fixed(
                        "Keyword",
                        None,
                        (("arg", SlotLeaf(None)), ("value", Child(_h(unit, ik[1])))),
                    )
                )
            elif _is_leaf(ik[0]) and ik[0].value == "*":
                args.append(
                    _fixed(
                        "Starred",
                        Span(_span(unit, item).start, _span(unit, item).end),
                        (("value", Child(_h(unit, ik[1]))),),
                    )
                )
            elif len(ik) >= 2 and _is_leaf(ik[1]) and ik[1].value == "=":
                keywords.append(
                    _fixed(
                        "Keyword",
                        Span(_span(unit, item).start, _span(unit, item).end),
                        (
                            ("arg", SlotLeaf(ik[0].value)),
                            ("value", Child(_h(unit, ik[2]))),
                        ),
                    )
                )
            else:
                vocabulary_missing(
                    blame=item,
                    owner="parso_adapter._call_args",
                    observed=f"argument shape {[c.type for c in ik]!r} not recognized",
                    requested="*expr, **expr, name=expr, or a comprehension argument",
                    fix="extend _call_args deliberately",
                )
        elif _is_leaf(item) and item.value == "*":
            continue  # handled as part of an 'argument' pairing above in real grammars
        elif item.type == "star_expr":
            sk = _kids(item)
            args.append(
                _fixed(
                    "Starred", _span(unit, item), (("value", Child(_h(unit, sk[1]))),)
                )
            )
        else:
            args.append(_h(unit, item))
    return args, keywords


def _subscript_slice(unit: SourceUnit, inner: Sequence[ParsoNode]) -> BackendNode:
    if len(inner) == 1 and inner[0].type == "subscriptlist":
        inner = _kids(inner[0])
    items = _strip_commas(inner)
    if len(items) == 1:
        return _one_subscript_item(unit, items[0])
    handles = tuple(_one_subscript_item(unit, it) for it in items)
    return _fixed("Tuple", None, (("elts", Children(handles)),))


def _one_subscript_item(unit: SourceUnit, node: ParsoNode) -> BackendNode:
    if node.type != "subscript":
        return _h(unit, node)
    # a slice: split on ':' leaves, flattening one level of 'sliceop'
    flat: List[ParsoNode] = []
    for c in _kids(node):
        if c.type == "sliceop":
            flat.extend(_kids(c))
        else:
            flat.append(c)
    segments: List[List[ParsoNode]] = [[]]
    for c in flat:
        if _is_leaf(c) and c.value == ":":
            segments.append([])
        else:
            segments[-1].append(c)
    while len(segments) < 3:
        segments.append([])
    lower, upper, step = segments[0], segments[1], segments[2]
    for seg in (lower, upper, step):
        if len(seg) > 1:
            vocabulary_missing(
                blame=seg[0],
                owner="parso_adapter._one_subscript_item",
                observed=f"slice segment with {len(seg)} nodes",
                requested="zero or one expression per slice segment",
                fix="extend the slice segment scan deliberately",
            )

    def _maybe(seg: List[ParsoNode]) -> Slot:
        return MaybeChild(_h(unit, seg[0]) if seg else None)

    return _fixed(
        "Slice",
        _span(unit, node),
        (("lower", _maybe(lower)), ("upper", _maybe(upper)), ("step", _maybe(step))),
    )


# --------------------------------------------------------------------------
# parameters
# --------------------------------------------------------------------------


def _flatten_params(
    unit: SourceUnit, node: Optional[ParsoNode]
) -> Tuple[BackendNode, ...]:
    if node is None:
        return ()
    if node.type == "param":
        return (_one_param(unit, node, "positional_or_keyword"),)
    if node.type == "tfpdef":
        # a lone annotated param with no default collapses past 'param' too
        # when it is the function's ONLY parameter.
        return (_one_param(unit, node, "positional_or_keyword"),)
    if node.type == "name":
        # a single plain (no annotation, no default) parameter collapses all
        # the way down to a bare Name leaf when it is the only parameter.
        return (
            _fixed(
                "Param",
                None,
                (
                    ("name", SlotLeaf(node.value)),
                    ("annotation", MaybeChild(None)),
                    ("default", MaybeChild(None)),
                    ("param_kind", SlotLeaf("positional_or_keyword")),
                ),
                anchors=(_span(unit, node),),
            ),
        )
    kids = _kids(node)
    if node.type == "parameters":
        kids = kids[1:-1]  # drop '(' ')'
    params: List[BackendNode] = []
    mode = "positional_or_keyword"
    for c in kids:
        if _is_leaf(c) and c.value == ",":
            continue
        if _is_leaf(c) and c.value == "/":
            for p in params:
                pass  # positional-only marker: retroactive tagging not needed —
                # every param before '/' was already emitted; re-tag them.
            params = [
                (
                    p
                    if p.describe().slots[3][1].value != "positional_or_keyword"
                    else _retag(p, "positional_only")
                )
                for p in params
            ]
            continue
        if _is_leaf(c) and c.value == "*":
            mode = "keyword_only"
            continue
        if c.type == "param":
            pk = _kids(c)
            if _is_leaf(pk[0]) and pk[0].value == "*":
                params.append(_one_param(unit, c, "vararg"))
                mode = "keyword_only"
            elif _is_leaf(pk[0]) and pk[0].value == "**":
                params.append(_one_param(unit, c, "kwarg"))
            else:
                params.append(_one_param(unit, c, mode))
    return tuple(params)


def _retag(handle: BackendNode, kind: str) -> BackendNode:
    desc = handle.describe()
    new_slots = tuple(
        (name, SlotLeaf(kind)) if name == "param_kind" else (name, slot)
        for name, slot in desc.slots
    )
    return _fixed(desc.kind, desc.raw_span, new_slots, desc.anchors)


def _one_param(unit: SourceUnit, node: ParsoNode, kind: str) -> BackendNode:
    kids = _kids(node)
    if kind in ("vararg", "kwarg"):
        kids = kids[1:]  # drop '*'/'**'
    if kids and kids[0].type == "tfpdef":
        # `NAME ':' annotation` collapses into its own 'tfpdef' node when the
        # param has no default (e.g. an annotated *args/**kwargs, or a plain
        # annotated positional param) — splice it back into a flat sequence.
        kids = _kids(kids[0]) + kids[1:]
    name_node = kids[0]
    name_span = _span(unit, name_node)
    annotation: Optional[ParsoNode] = None
    default: Optional[ParsoNode] = None
    i = 1
    while i < len(kids):
        c = kids[i]
        if _is_leaf(c) and c.value == ":":
            annotation = kids[i + 1]
            i += 2
        elif _is_leaf(c) and c.value == "=":
            default = kids[i + 1]
            i += 2
        else:
            i += 1
    anchor_end = name_span.end
    return _fixed(
        "Param",
        None,
        (
            ("name", SlotLeaf(name_node.value)),
            (
                "annotation",
                MaybeChild(_h(unit, annotation) if annotation is not None else None),
            ),
            ("default", MaybeChild(_h(unit, default) if default is not None else None)),
            ("param_kind", SlotLeaf(kind)),
        ),
        anchors=(Span(name_span.start, anchor_end),),
    )


# --------------------------------------------------------------------------
# suite / block flattening
# --------------------------------------------------------------------------


def _stmts(unit: SourceUnit, node: ParsoNode) -> Tuple[BackendNode, ...]:
    """Flatten a 'suite' (or, for one-liners, the bare simple_stmt/compound
    stmt already sitting where a suite would be) into a tuple of statement
    handles, dropping NEWLINE/INDENT/DEDENT and unwrapping simple_stmt."""
    out: List[BackendNode] = []
    if node.type == "suite":
        for c in _kids(node):
            if c.type in ("newline", "indent", "dedent"):
                continue
            out.extend(_stmt_handles(unit, c))
    else:
        out.extend(_stmt_handles(unit, node))
    return tuple(out)


def _stmt_handles(unit: SourceUnit, node: ParsoNode) -> List[BackendNode]:
    if node.type == "simple_stmt":
        out = []
        for c in _kids(node):
            if _is_leaf(c) and c.value in (";", "\n") or c.type == "newline":
                continue
            out.append(_h(unit, c))
        return out
    return [_h(unit, node)]


def _body_of(unit: SourceUnit, node: ParsoNode) -> Tuple[BackendNode, ...]:
    """The ':' suite/simple_stmt trailing a compound statement header."""
    kids = _kids(node)
    return _stmts(unit, kids[-1])


# --------------------------------------------------------------------------
# top-level dispatch
# --------------------------------------------------------------------------


def _describe(unit: SourceUnit, node: ParsoNode) -> Description:
    if _is_leaf(node):
        return _describe_leaf(unit, node)
    t = node.type
    fn = _DISPATCH.get(t)
    if fn is not None:
        return fn(unit, node)
    vocabulary_missing(
        blame=node,
        owner="parso_adapter._describe",
        observed=f"parso node type {t!r} has no translation rule",
        requested="a mapped statement/expression shape",
        fix="add a translation rule for this parso node type; never guess",
    )
    raise AssertionError("unreachable")


def _describe_leaf(unit: SourceUnit, node: ParsoNode) -> Description:
    if node.type == "name":
        return Description(
            kind="Name",
            raw_span=_span(unit, node),
            anchors=(),
            slots=(("id", SlotLeaf(node.value)),),
        )
    if node.type in ("number", "string"):
        d = _constant_leaf(unit, node)
        return d.describe()
    if node.type == "keyword" and node.value in ("None", "True", "False"):
        return _constant_leaf(unit, node).describe()
    if node.type == "operator" and node.value == "...":
        return _constant_leaf(unit, node).describe()
    if node.type == "fstring":
        return _fixed(
            "JoinedStr",
            _span(unit, node),
            (("values", Children(tuple(_fstring_values(unit, node)))),),
        ).describe()
    if node.type == "keyword" and node.value == "pass":
        return Description(
            kind="Pass", raw_span=_span(unit, node), anchors=(), slots=()
        )
    if node.type == "keyword" and node.value == "break":
        return Description(
            kind="Break", raw_span=_span(unit, node), anchors=(), slots=()
        )
    if node.type == "keyword" and node.value == "continue":
        return Description(
            kind="Continue", raw_span=_span(unit, node), anchors=(), slots=()
        )
    if node.type == "keyword" and node.value == "return":
        # bare `return` with no value: parso collapses the return_stmt
        # wrapper down to just this keyword leaf (single-child collapsing).
        return Description(
            kind="Return",
            raw_span=_span(unit, node),
            anchors=(),
            slots=(("value", MaybeChild(None)),),
        )
    if node.type == "keyword" and node.value == "raise":
        return Description(
            kind="Raise",
            raw_span=_span(unit, node),
            anchors=(),
            slots=(("exc", MaybeChild(None)), ("cause", MaybeChild(None))),
        )
    if node.type == "keyword" and node.value == "yield":
        return Description(
            kind="Yield",
            raw_span=_span(unit, node),
            anchors=(),
            slots=(("value", MaybeChild(None)),),
        )
    if node.type == "operator" and node.value == ":":
        # bare `a[:]`: subscript's slice collapses to just the ':' leaf.
        return Description(
            kind="Slice",
            raw_span=_span(unit, node),
            anchors=(),
            slots=(
                ("lower", MaybeChild(None)),
                ("upper", MaybeChild(None)),
                ("step", MaybeChild(None)),
            ),
        )
    vocabulary_missing(
        blame=node,
        owner="parso_adapter._describe_leaf",
        observed=f"leaf {node.type}:{node.value!r} has no translation rule",
        requested="a mapped leaf shape",
        fix="add a translation rule for this leaf; never guess",
    )
    raise AssertionError("unreachable")


def _module(unit: SourceUnit, node: ParsoNode) -> Description:
    body: List[BackendNode] = []
    for c in _kids(node):
        if c.type in ("endmarker", "newline"):
            continue
        body.extend(_stmt_handles(unit, c))
    return Description(
        kind="Module",
        raw_span=Span(0, len(unit.source)),
        anchors=(),
        slots=(("body", Children(tuple(body))),),
    )


def _atom(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    first = kids[0]
    if _is_leaf(first) and first.value == "(":
        if len(kids) == 2:  # '()' empty tuple
            return _bare_tuple(unit, (), _span(unit, node)).describe()
        inner = kids[1]
        if inner.type == "yield_expr":
            return _describe(unit, inner)
        if inner.type == "testlist_comp":
            ik = _kids(inner)
            if (
                len(ik) >= 2
                and ik[1].type == "comp_for"
                or (len(ik) >= 2 and ik[1].type == "sync_comp_for")
            ):
                return _genexp(unit, ik[0], ik[1:]).describe()
            elts = _strip_commas(ik)
            has_trailing_comma = _is_leaf(ik[-1]) and ik[-1].value == ","
            if len(elts) == 1 and not has_trailing_comma:
                # a merely-parenthesized single expression: parens excluded
                return _describe(unit, elts[0])
            return _bare_tuple(unit, elts, _span(unit, node)).describe()
        # a single parenthesized expression
        return _describe(unit, inner)
    if _is_leaf(first) and first.value == "[":
        if len(kids) == 2:
            return Description(
                kind="List",
                raw_span=_span(unit, node),
                anchors=(),
                slots=(("elts", Children(())),),
            )
        inner = kids[1]
        if inner.type in ("testlist_comp",):
            ik = _kids(inner)
            if len(ik) >= 2 and ik[1].type in ("comp_for", "sync_comp_for"):
                elt = _h(unit, ik[0])
                gens = _comp_clauses(unit, ik[1:])
                return Description(
                    kind="ListComp",
                    raw_span=_span(unit, node),
                    anchors=(),
                    slots=(("elt", Child(elt)), ("generators", Children(gens))),
                )
            elts = _strip_commas(ik)
            return Description(
                kind="List",
                raw_span=_span(unit, node),
                anchors=(),
                slots=(("elts", Children(tuple(_h(unit, e) for e in elts))),),
            )
        return Description(
            kind="List",
            raw_span=_span(unit, node),
            anchors=(),
            slots=(("elts", Children((_h(unit, inner),))),),
        )
    if _is_leaf(first) and first.value == "{":
        if len(kids) == 2:
            return Description(
                kind="Dict",
                raw_span=_span(unit, node),
                anchors=(),
                slots=(("items", Children(())),),
            )
        return _dictorset(unit, node, kids[1])
    if first.type == "fstring":
        return _describe(unit, first)
    vocabulary_missing(
        blame=node,
        owner="parso_adapter._atom",
        observed=f"atom starting with {getattr(first, 'value', first.type)!r} not recognized",
        requested="'(', '[', '{' grouping, or an fstring",
        fix="extend _atom deliberately",
    )
    raise AssertionError("unreachable")


def _dictorset(unit: SourceUnit, atom_node: ParsoNode, inner: ParsoNode) -> Description:
    span = _span(unit, atom_node)
    if inner.type == "dictorsetmaker":
        ik = _kids(inner)
        has_colon = any(_is_leaf(c) and c.value == ":" for c in ik)
        has_comp = any(c.type in ("comp_for", "sync_comp_for") for c in ik)
        if has_colon and has_comp:
            colon_i = next(
                i for i, c in enumerate(ik) if _is_leaf(c) and c.value == ":"
            )
            key = _h(unit, ik[0])
            value = _h(unit, ik[colon_i + 1])
            gens = _comp_clauses(unit, ik[colon_i + 2 :])
            return Description(
                kind="DictComp",
                raw_span=span,
                anchors=(),
                slots=(
                    ("key", Child(key)),
                    ("value", Child(value)),
                    ("generators", Children(gens)),
                ),
            )
        if has_colon:
            items: List[BackendNode] = []
            i = 0
            while i < len(ik):
                c = ik[i]
                if _is_leaf(c) and c.value == ",":
                    i += 1
                    continue
                if _is_leaf(c) and c.value == "**":
                    items.append(
                        _fixed(
                            "DictItem",
                            None,
                            (
                                ("key", MaybeChild(None)),
                                ("value", Child(_h(unit, ik[i + 1]))),
                            ),
                        )
                    )
                    i += 2
                    continue
                key_n = c
                value_n = ik[i + 2]
                items.append(
                    _fixed(
                        "DictItem",
                        None,
                        (
                            ("key", MaybeChild(_h(unit, key_n))),
                            ("value", Child(_h(unit, value_n))),
                        ),
                    )
                )
                i += 3
            return Description(
                kind="Dict",
                raw_span=span,
                anchors=(),
                slots=(("items", Children(tuple(items))),),
            )
        if has_comp:
            elt = _h(unit, ik[0])
            gens = _comp_clauses(unit, ik[1:])
            return Description(
                kind="SetComp",
                raw_span=span,
                anchors=(),
                slots=(("elt", Child(elt)), ("generators", Children(gens))),
            )
        elts = _strip_commas(ik)
        return Description(
            kind="Set",
            raw_span=span,
            anchors=(),
            slots=(("elts", Children(tuple(_h(unit, e) for e in elts))),),
        )
    # single element -> a one-item set
    return Description(
        kind="Set",
        raw_span=span,
        anchors=(),
        slots=(("elts", Children((_h(unit, inner),))),),
    )


def _comp_clauses(
    unit: SourceUnit, nodes: Sequence[ParsoNode]
) -> Tuple[BackendNode, ...]:
    out: List[BackendNode] = []
    for n in nodes:
        if n.type in ("comp_for", "sync_comp_for"):
            out.append(_h(unit, n))
        elif n.type == "comp_if":
            # folded into the preceding Comprehension's ifs by _comprehension
            continue
        else:
            vocabulary_missing(
                blame=n,
                owner="parso_adapter._comp_clauses",
                observed=f"comprehension clause child {n.type!r} not recognized",
                requested="comp_for/sync_comp_for or comp_if",
                fix="extend _comp_clauses deliberately",
            )
    return tuple(out)


def _comprehension(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    is_async = _is_leaf(kids[0]) and kids[0].value == "async"
    if is_async:
        kids = kids[1:]
    # kids: 'for' exprlist 'in' or_test [comp_iter]
    target_n = kids[1]
    iter_n = kids[3]
    ifs: List[BackendNode] = []
    rest = kids[4:]
    for r in rest:
        r2 = r
        while r2.type == "comp_iter":
            r2 = _kids(r2)[0]
        if r2.type == "comp_if":
            ik = _kids(r2)
            ifs.append(_h(unit, ik[1]))
            # a comp_if may itself carry a further comp_iter (chained ifs/for)
            if len(ik) > 2:
                vocabulary_missing(
                    blame=r2,
                    owner="parso_adapter._comprehension",
                    observed="comp_if with a nested comp_iter tail not yet folded",
                    requested="a flattened ifs/for chain",
                    fix="extend _comprehension to fold chained comp_iter tails",
                )
        elif r2.type in ("comp_for", "sync_comp_for"):
            vocabulary_missing(
                blame=r2,
                owner="parso_adapter._comprehension",
                observed="chained 'for ... for ...' clause not yet folded into a flat generators list",
                requested="each comp_for as its own top-level Comprehension",
                fix="extend the caller to walk comp_iter tails, not just this node",
            )
    target = target_n if target_n.type != "exprlist" else None
    if target is None:
        elts = _strip_commas(_kids(target_n))
        target_handle: BackendNode = _bare_tuple(unit, elts)
    else:
        target_handle = _h(unit, target_n)
    return Description(
        kind="Comprehension",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("target", Child(target_handle)),
            ("iter", Child(_h(unit, iter_n))),
            ("ifs", Children(tuple(ifs))),
            ("is_async", SlotLeaf(is_async)),
        ),
    )


def _genexp(
    unit: SourceUnit, elt_node: ParsoNode, clause_nodes: Sequence[ParsoNode]
) -> BackendNode:
    elt = _h(unit, elt_node)
    gens = _comp_clauses(unit, clause_nodes)
    return _fixed(
        "GeneratorExp", None, (("elt", Child(elt)), ("generators", Children(gens)))
    )


# ---- statements -----------------------------------------------------------


def _expr_stmt(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    span = _span(unit, node)
    # annotated assignment: NAME ':' test ['=' test]
    colon_idx = next(
        (i for i, c in enumerate(kids) if _is_leaf(c) and c.value == ":"), None
    )
    if colon_idx is not None:
        target = _h(unit, kids[0])
        annotation = _h(unit, kids[colon_idx + 1])
        value = None
        if len(kids) > colon_idx + 2:
            value = _h(unit, kids[colon_idx + 3])
        return Description(
            kind="AnnAssign",
            raw_span=span,
            anchors=(),
            slots=(
                ("target", Child(target)),
                ("annotation", Child(annotation)),
                ("value", MaybeChild(value)),
                ("simple", SlotLeaf(True)),
            ),
        )
    if len(kids) == 1:
        return _describe(unit, kids[0])
    op = kids[1]
    if not _is_leaf(op) and op.type == "annassign":
        # parso wraps `: annotation [= value]` in one annassign node.
        ann_kids = _kids(op)  # [':', annotation] or [':', annotation, '=', value]
        value = _h(unit, ann_kids[3]) if len(ann_kids) > 3 else None
        return Description(
            kind="AnnAssign",
            raw_span=span,
            anchors=(),
            slots=(
                ("target", Child(_h(unit, kids[0]))),
                ("annotation", Child(_h(unit, ann_kids[1]))),
                ("value", MaybeChild(value)),
                ("simple", SlotLeaf(True)),
            ),
        )
    if not _is_leaf(op):
        vocabulary_missing(
            blame=op,
            owner="parso_adapter._expr_stmt",
            observed=f"expr_stmt second child is a {op.type!r} node, not an operator leaf",
            requested="'=', an augmented-assignment operator, or annassign",
            fix="extend _expr_stmt deliberately",
        )
    if op.value == "=":
        targets = [kids[0]] + [kids[i] for i in range(2, len(kids) - 1, 2)]
        value = kids[-1]
        return Description(
            kind="Assign",
            raw_span=span,
            anchors=(),
            slots=(
                ("targets", Children(tuple(_h(unit, t) for t in targets))),
                ("value", Child(_h(unit, value))),
            ),
        )
    aug_kind = _AUG_TOKEN.get(op.value)
    if aug_kind is None:
        vocabulary_missing(
            blame=op,
            owner="parso_adapter._expr_stmt",
            observed=f"expr_stmt operator {op.value!r} not recognized",
            requested="'=' (chained) or an augmented-assignment token",
            fix="extend _expr_stmt deliberately",
        )
    return Description(
        kind="AugAssign",
        raw_span=span,
        anchors=(),
        slots=(
            ("target", Child(_h(unit, kids[0]))),
            ("op", OpLeaf(operator_for(aug_kind, blame=op))),
            ("value", Child(_h(unit, kids[2]))),
        ),
    )


def _return_stmt(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    value = _h(unit, kids[1]) if len(kids) > 1 else None
    return Description(
        kind="Return",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(("value", MaybeChild(value)),),
    )


def _yield_expr(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    span = _span(unit, node)
    if len(kids) == 1:
        return Description(
            kind="Yield",
            raw_span=span,
            anchors=(),
            slots=(("value", MaybeChild(None)),),
        )
    arg = kids[1]
    if arg.type == "yield_arg":
        ak = _kids(arg)
        return Description(
            kind="YieldFrom",
            raw_span=span,
            anchors=(),
            slots=(("value", Child(_h(unit, ak[1]))),),
        )
    if arg.type == "testlist_star_expr" or arg.type == "testlist":
        elts = _strip_commas(_kids(arg))
        value = _bare_tuple(unit, elts) if len(elts) > 1 else _h(unit, elts[0])
        return Description(
            kind="Yield",
            raw_span=span,
            anchors=(),
            slots=(("value", MaybeChild(value)),),
        )
    return Description(
        kind="Yield",
        raw_span=span,
        anchors=(),
        slots=(("value", MaybeChild(_h(unit, arg))),),
    )


def _raise_stmt(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    exc = cause = None
    if len(kids) > 1:
        exc = kids[1]
        if len(kids) > 2:
            cause = kids[3]
    return Description(
        kind="Raise",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("exc", MaybeChild(_h(unit, exc) if exc is not None else None)),
            ("cause", MaybeChild(_h(unit, cause) if cause is not None else None)),
        ),
    )


def _del_stmt(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    target = kids[1]
    if target.type == "exprlist":
        elts = _strip_commas(_kids(target))
    else:
        elts = [target]
    return Description(
        kind="Delete",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(("targets", Children(tuple(_h(unit, e) for e in elts))),),
    )


def _import_name(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    dotted = kids[1]
    names = _dotted_as_names(unit, dotted)
    return Description(
        kind="Import",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(("names", Children(names)),),
    )


def _dotted_name_str(node: ParsoNode) -> str:
    if node.type == "dotted_name":
        return "".join(
            c.value for c in _kids(node) if not (_is_leaf(c) and c.value == ".")
        )
    return node.value


def _dotted_as_names(unit: SourceUnit, node: ParsoNode) -> Tuple[BackendNode, ...]:
    if node.type == "dotted_as_names":
        items = _strip_commas(_kids(node))
    else:
        items = [node]
    out = []
    for it in items:
        out.append(_dotted_as_name(unit, it))
    return tuple(out)


def _dotted_as_name(unit: SourceUnit, node: ParsoNode) -> BackendNode:
    if node.type == "dotted_as_name":
        k = _kids(node)
        name = _dotted_name_str(k[0])
        asname = k[2].value
    else:
        name = _dotted_name_str(node)
        asname = None
    return _fixed(
        "ImportAlias",
        _span(unit, node),
        (("name", SlotLeaf(name)), ("asname", SlotLeaf(asname))),
    )


def _import_from(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    i = 1
    level = 0
    module: Optional[str] = None
    while i < len(kids) and (_is_leaf(kids[i]) and kids[i].value in (".", "...")):
        level += len(kids[i].value)
        i += 1
    if i < len(kids) and not (_is_leaf(kids[i]) and kids[i].value == "import"):
        module = _dotted_name_str(kids[i])
        i += 1
    assert _is_leaf(kids[i]) and kids[i].value == "import"
    i += 1
    if _is_leaf(kids[i]) and kids[i].value == "*":
        names = (
            _fixed(
                "ImportAlias",
                _span(unit, kids[i]),
                (("name", SlotLeaf("*")), ("asname", SlotLeaf(None))),
            ),
        )
    elif _is_leaf(kids[i]) and kids[i].value == "(":
        names = _import_as_names(unit, kids[i + 1])
    else:
        names = _import_as_names(unit, kids[i])
    return Description(
        kind="ImportFrom",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("module", SlotLeaf(module)),
            ("names", Children(names)),
            ("level", SlotLeaf(level)),
        ),
    )


def _import_as_names(unit: SourceUnit, node: ParsoNode) -> Tuple[BackendNode, ...]:
    if node.type == "import_as_names":
        items = _strip_commas(_kids(node))
    else:
        items = [node]
    out = []
    for it in items:
        if it.type == "import_as_name":
            k = _kids(it)
            out.append(
                _fixed(
                    "ImportAlias",
                    _span(unit, it),
                    (("name", SlotLeaf(k[0].value)), ("asname", SlotLeaf(k[2].value))),
                )
            )
        else:
            out.append(
                _fixed(
                    "ImportAlias",
                    _span(unit, it),
                    (("name", SlotLeaf(it.value)), ("asname", SlotLeaf(None))),
                )
            )
    return tuple(out)


def _global_stmt(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _strip_commas(_kids(node)[1:])
    return Description(
        kind="Global",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(("names", SlotLeaf(tuple(k.value for k in kids))),),
    )


def _nonlocal_stmt(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _strip_commas(_kids(node)[1:])
    return Description(
        kind="Nonlocal",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(("names", SlotLeaf(tuple(k.value for k in kids))),),
    )


def _assert_stmt(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    test = _h(unit, kids[1])
    msg = _h(unit, kids[3]) if len(kids) > 3 else None
    return Description(
        kind="Assert",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(("test", Child(test)), ("msg", MaybeChild(msg))),
    )


def _if_stmt(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    # if TEST ':' suite (elif TEST ':' suite)* (else ':' suite)?
    return _if_chain(unit, kids, 0, _span(unit, node))


def _if_chain(
    unit: SourceUnit, kids: List[ParsoNode], i: int, outer_span: Span
) -> Description:
    keyword = kids[i]
    test = _h(unit, kids[i + 1])
    body = _stmts(unit, kids[i + 3])
    j = i + 4
    if j < len(kids) and kids[j].type == "keyword" and kids[j].value == "elif":
        orelse: Tuple[BackendNode, ...] = (_fixed_if_chain(unit, kids, j, outer_span),)
    elif j < len(kids) and kids[j].type == "keyword" and kids[j].value == "else":
        orelse = _stmts(unit, kids[j + 2])
    else:
        orelse = ()
    span = Span(_span(unit, keyword).start, outer_span.end) if i > 0 else outer_span
    return Description(
        kind="If",
        raw_span=span,
        anchors=(),
        slots=(
            ("test", Child(test)),
            ("body", Children(body)),
            ("orelse", Children(orelse)),
        ),
    )


def _fixed_if_chain(
    unit: SourceUnit, kids: List[ParsoNode], i: int, outer_span: Span
) -> BackendNode:
    d = _if_chain(unit, kids, i, outer_span)
    return _fixed(d.kind, d.raw_span, d.slots, d.anchors)


def _while_stmt(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    test = _h(unit, kids[1])
    body = _stmts(unit, kids[3])
    orelse: Tuple[BackendNode, ...] = ()
    if len(kids) > 4:
        orelse = _stmts(unit, kids[6])
    return Description(
        kind="While",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("test", Child(test)),
            ("body", Children(body)),
            ("orelse", Children(orelse)),
        ),
    )


def _for_stmt(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    target_n = kids[1]
    if target_n.type == "exprlist":
        elts = _strip_commas(_kids(target_n))
        target = _bare_tuple(unit, elts) if len(elts) > 1 else _h(unit, elts[0])
    else:
        target = _h(unit, target_n)
    iter_n = kids[3]
    if iter_n.type == "testlist":
        elts = _strip_commas(_kids(iter_n))
        iter_handle: BackendNode = _bare_tuple(unit, elts)
    else:
        iter_handle = _h(unit, iter_n)
    body = _stmts(unit, kids[5])
    orelse: Tuple[BackendNode, ...] = ()
    if len(kids) > 6:
        orelse = _stmts(unit, kids[8])
    return Description(
        kind="For",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("target", Child(target)),
            ("iter", Child(iter_handle)),
            ("body", Children(body)),
            ("orelse", Children(orelse)),
        ),
    )


def _try_stmt(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    body = _stmts(unit, kids[2])
    handlers: List[BackendNode] = []
    orelse: Tuple[BackendNode, ...] = ()
    finalbody: Tuple[BackendNode, ...] = ()
    is_star = False
    i = 3
    while i < len(kids):
        c = kids[i]
        if c.type == "except_clause":
            ek = _kids(c)
            j = 1
            exc_type = None
            exc_name = None
            if j < len(ek) and _is_leaf(ek[j]) and ek[j].value == "*":
                is_star = True
                j += 1
            if j < len(ek):
                exc_type = ek[j]
                j += 1
            if j < len(ek) and _is_leaf(ek[j]) and ek[j].value == "as":
                exc_name = ek[j + 1].value
            handler_body = _stmts(unit, kids[i + 2])
            handlers.append(
                _fixed(
                    "ExceptHandler",
                    _span(unit, c).envelope(_span(unit, kids[i + 2])),
                    (
                        (
                            "type_",
                            MaybeChild(
                                _h(unit, exc_type) if exc_type is not None else None
                            ),
                        ),
                        ("name", SlotLeaf(exc_name)),
                        ("body", Children(handler_body)),
                    ),
                )
            )
            i += 3
        elif c.type == "keyword" and c.value == "else":
            orelse = _stmts(unit, kids[i + 2])
            i += 3
        elif c.type == "keyword" and c.value == "finally":
            finalbody = _stmts(unit, kids[i + 2])
            i += 3
        else:
            i += 1
    kind = "TryStar" if is_star else "Try"
    return Description(
        kind=kind,
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("body", Children(body)),
            ("handlers", Children(tuple(handlers))),
            ("orelse", Children(orelse)),
            ("finalbody", Children(finalbody)),
        ),
    )


def _with_stmt(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    items_nodes = [c for c in kids[1:-2] if not (_is_leaf(c) and c.value == ",")]
    items: List[BackendNode] = []
    for it in items_nodes:
        if it.type == "with_item":
            ik = _kids(it)
            ctx = _h(unit, ik[0])
            var = _h(unit, ik[2]) if len(ik) > 2 else None
            items.append(
                _fixed(
                    "WithItem",
                    _span(unit, it),
                    (("context_expr", Child(ctx)), ("optional_vars", MaybeChild(var))),
                )
            )
        else:
            items.append(
                _fixed(
                    "WithItem",
                    _span(unit, it),
                    (
                        ("context_expr", Child(_h(unit, it))),
                        ("optional_vars", MaybeChild(None)),
                    ),
                )
            )
    body = _stmts(unit, kids[-1])
    return Description(
        kind="With",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(("items", Children(tuple(items))), ("body", Children(body))),
    )


def _funcdef(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    name = kids[1].value
    idx = 2
    if kids[idx].type in ("typeparams",):
        idx += (
            1  # PEP 695 generic params: not further destructured (rare in this corpus)
        )
    params_node = kids[idx]
    idx += 1
    returns = None
    if _is_leaf(kids[idx]) and kids[idx].value == "->":
        returns = kids[idx + 1]
        idx += 2
    body = _stmts(unit, kids[-1])
    return Description(
        kind="FunctionDef",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("name", SlotLeaf(name)),
            ("binding_target", Child(_h(unit, kids[1]))),
            ("params", Children(_flatten_params(unit, params_node))),
            ("body", Children(body)),
            ("decorators", Children(())),
            ("returns", MaybeChild(_h(unit, returns) if returns is not None else None)),
            ("type_params", Children(())),
        ),
    )


def _classdef(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    name = kids[1].value
    bases: Tuple[BackendNode, ...] = ()
    keywords: Tuple[BackendNode, ...] = ()
    idx = 2
    if idx < len(kids) and _is_leaf(kids[idx]) and kids[idx].value == "(":
        if not (_is_leaf(kids[idx + 1]) and kids[idx + 1].value == ")"):
            arglist_kids = (
                _kids(kids[idx + 1])
                if kids[idx + 1].type == "arglist"
                else [kids[idx + 1]]
            )
            b, kw = _call_args(unit, arglist_kids)
            bases, keywords = tuple(b), tuple(kw)
    body = _stmts(unit, kids[-1])
    return Description(
        kind="ClassDef",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("name", SlotLeaf(name)),
            ("bases", Children(bases)),
            ("keywords", Children(keywords)),
            ("body", Children(body)),
            ("decorators", Children(())),
            ("type_params", Children(())),
        ),
    )


def _decorated(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    decorators = [c for c in kids[:-1] if c.type == "decorator"]
    dec_handles = tuple(_h(unit, _kids(d)[1]) for d in decorators)
    target = kids[-1]
    if target.type == "async_funcdef":
        base = _funcdef(unit, _kids(target)[1])
        kind = "AsyncFunctionDef"
        span = Span(_span(unit, target).start, base.raw_span.end)
    else:
        base = _describe(unit, target)
        kind = base.kind
        span = base.raw_span
    new_slots = tuple(
        (name, Children(dec_handles)) if name == "decorators" else (name, slot)
        for name, slot in base.slots
    )
    return Description(kind=kind, raw_span=span, anchors=(), slots=new_slots)


def _async_stmt(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    inner = kids[1]
    span = _span(unit, node)
    if inner.type == "funcdef":
        base = _funcdef(unit, inner)
        return Description(
            kind="AsyncFunctionDef", raw_span=span, anchors=(), slots=base.slots
        )
    if inner.type == "for_stmt":
        base = _for_stmt(unit, inner)
        return Description(kind="AsyncFor", raw_span=span, anchors=(), slots=base.slots)
    if inner.type == "with_stmt":
        base = _with_stmt(unit, inner)
        return Description(
            kind="AsyncWith", raw_span=span, anchors=(), slots=base.slots
        )
    vocabulary_missing(
        blame=inner,
        owner="parso_adapter._async_stmt",
        observed=f"async_stmt wrapping {inner.type!r} not recognized",
        requested="funcdef, for_stmt, or with_stmt",
        fix="extend _async_stmt deliberately",
    )
    raise AssertionError("unreachable")


def _lambdef(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    params_node = None
    body_node = kids[-1]
    if len(kids) > 3:
        params_node = kids[1]
    return Description(
        kind="Lambda",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("params", Children(_flatten_params(unit, params_node))),
            ("body", Child(_h(unit, body_node))),
        ),
    )


def _ternary(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    body = _h(unit, kids[0])
    test = _h(unit, kids[2])
    orelse = _h(unit, kids[4])
    return Description(
        kind="IfExp",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(("test", Child(test)), ("body", Child(body)), ("orelse", Child(orelse))),
    )


def _namedexpr(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    return Description(
        kind="NamedExpr",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("target", Child(_h(unit, kids[0]))),
            ("value", Child(_h(unit, kids[2]))),
        ),
    )


def _not_test(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    return Description(
        kind="UnaryOp",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("op", OpLeaf(operator_for("Not", blame=node))),
            ("operand", Child(_h(unit, kids[1]))),
        ),
    )


def _factor(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    kind = _UNARY_TOKEN.get(kids[0].value)
    if kind is None:
        vocabulary_missing(
            blame=kids[0],
            owner="parso_adapter._factor",
            observed=f"unary token {kids[0].value!r} not recognized",
            requested="'+', '-', or '~'",
            fix="extend _UNARY_TOKEN deliberately",
        )
    return Description(
        kind="UnaryOp",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("op", OpLeaf(operator_for(kind, blame=kids[0]))),
            ("operand", Child(_h(unit, kids[1]))),
        ),
    )


def _power(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    left = _h(unit, kids[0])
    right = _h(unit, kids[2])
    return Description(
        kind="BinOp",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(
            ("left", Child(left)),
            ("op", OpLeaf(operator_for("Pow", blame=node))),
            ("right", Child(right)),
        ),
    )


def _star_expr(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    return Description(
        kind="Starred",
        raw_span=_span(unit, node),
        anchors=(),
        slots=(("value", Child(_h(unit, kids[1]))),),
    )


def _atom_expr(unit: SourceUnit, node: ParsoNode) -> Description:
    kids = _kids(node)
    has_await = _is_leaf(kids[0]) and kids[0].value == "await"
    await_start = _span(unit, kids[0]).start if has_await else None
    atom = kids[1] if has_await else kids[0]
    trailers = kids[2:] if has_await else kids[1:]
    handle = _fold_trailers(unit, atom, trailers, has_await, await_start)
    return handle.describe()


def _bare_tuple_node(unit: SourceUnit, node: ParsoNode) -> Description:
    elts = _strip_commas(_kids(node))
    return _bare_tuple(
        unit, elts, _span(unit, node)
    ).describe()  # note: overridden below for envelope


_DISPATCH = {
    "file_input": _module,
    "atom": _atom,
    "atom_expr": _atom_expr,
    "power": _power,
    "factor": _factor,
    "not_test": _not_test,
    "and_test": lambda u, n: _boolop(u, n, "And"),
    "or_test": lambda u, n: _boolop(u, n, "Or"),
    "comparison": _compare,
    "expr": lambda u, n: _fold_binop(u, n).describe(),
    "xor_expr": lambda u, n: _fold_binop(u, n).describe(),
    "and_expr": lambda u, n: _fold_binop(u, n).describe(),
    "shift_expr": lambda u, n: _fold_binop(u, n).describe(),
    "arith_expr": lambda u, n: _fold_binop(u, n).describe(),
    "term": lambda u, n: _fold_binop(u, n).describe(),
    "star_expr": _star_expr,
    "test": _ternary,
    "namedexpr_test": _namedexpr,
    "lambdef": _lambdef,
    "lambdef_nocond": _lambdef,
    "comp_for": _comprehension,
    "sync_comp_for": _comprehension,
    "fstring_expr": _describe_fstring_expr,
    "strings": lambda u, n: _join_string_pieces(u, _kids(n)).describe(),
    "fstring": lambda u, n: _fixed(
        "JoinedStr", _span(u, n), (("values", Children(tuple(_fstring_values(u, n)))),)
    ).describe(),
    "expr_stmt": _expr_stmt,
    "return_stmt": _return_stmt,
    "yield_expr": _yield_expr,
    "raise_stmt": _raise_stmt,
    "del_stmt": _del_stmt,
    "import_name": _import_name,
    "import_from": _import_from,
    "global_stmt": _global_stmt,
    "nonlocal_stmt": _nonlocal_stmt,
    "assert_stmt": _assert_stmt,
    "if_stmt": _if_stmt,
    "while_stmt": _while_stmt,
    "for_stmt": _for_stmt,
    "try_stmt": _try_stmt,
    "with_stmt": _with_stmt,
    "funcdef": _funcdef,
    "classdef": _classdef,
    "decorated": _decorated,
    "async_stmt": _async_stmt,
    "async_funcdef": lambda u, n: _funcdef(u, _kids(n)[1]),
    "testlist_star_expr": _bare_tuple_node,
    "testlist": _bare_tuple_node,
    "exprlist": _bare_tuple_node,
}


class ParsoBackend(Backend):
    """parso: pure-Python, error-recovering — the third candidate backend."""

    name = "parso"

    def __init__(self, version: str = "3.12") -> None:
        self._grammar = parso.load_grammar(version=version)

    def root(self, unit: SourceUnit) -> BackendNode:
        # parso's own parse-failure exception (ParserSyntaxError, NOT a
        # SyntaxError subclass) never escapes as-is: it is translated to
        # BackendCouldNotParse, the contract's own type, like every adapter.
        try:
            module = self._grammar.parse(unit.source, error_recovery=False)
        except parso.parser.ParserSyntaxError as err:
            raise BackendCouldNotParse(
                backend=self.name, file=unit.filename, reason=str(err)
            ) from err
        return _Handle(unit, module)
