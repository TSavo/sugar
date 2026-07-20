"""tree-sitter-python provider adapter (#5940, #5932) — candidate #4.

THE ONLY MODULE IN THIS PACKAGE THAT MAY NAME ``tree_sitter`` /
``tree_sitter_python``. Same read-only contract as the other adapters:
``parse(unit) -> handle``, and per handle a single ``describe()`` giving our
kind, our codepoint span, and our fields as slots.

Why tree-sitter is a credible fourth candidate: it is a C library with an
error-tolerant, incremental GLR-style parser (built for editors to re-parse
on every keystroke) and does not call CPython's ``compile()`` — the same
property that makes LibCST and parso immune to #5932. Its grammar is also
the closest structural match to our AST-shaped membrane of any candidate
examined: binary/boolean/comparison operator chains are ALREADY nested
left-associatively by the grammar (unlike parso's flat n-ary chains that
this package's ``parso_adapter`` must fold by hand), and most productions
expose named fields (``child_by_field_name``) instead of requiring
positional child-counting.

MAPPING NOTES
=============

- **Byte columns, like CPython — NOT like parso/LibCST.** tree-sitter's
  ``start_point``/``end_point`` report ``(row, column)`` where the column
  is a UTF-8 BYTE offset within the row, not a codepoint offset (verified:
  a non-ASCII character before a node shifts its byte column but not its
  codepoint column). This adapter reuses the exact same seam the CPython
  adapter built — ``LineTable.offset_from_byte_col`` — just fed 0-based
  rows instead of CPython's 1-based lines.
- **Grouping parens are excluded** for a ``parenthesized_expression``: the
  inner expression is unwrapped and keeps its own (narrower) span — our
  ruling. A parenthesized tuple's parens ARE part of the ``Tuple`` span
  (the one ruled exception) since a bracketed comma list is its own
  ``tuple``/``list``/... node whose span already includes the brackets.
- **Anonymous/punctuation nodes** (``(``, ``)``, ``,``, ``:``, keywords)
  are unnamed children (``is_named`` False) and are skipped everywhere
  except where their presence/absence changes meaning (e.g. ``except*``,
  ``async for``).
- **Decorators**: ``decorated_definition`` wraps ``decorator*`` plus the
  ``funcdef``/``classdef`` in a ``definition`` field; the def's span in our
  membrane starts at ``def``/``class``, excluding decorators — matches
  ``FunctionDef``/``ClassDef`` spanning from their own keyword, computed
  here by re-describing the inner definition and only widening the
  ``decorators`` slot, mirroring the LibCST/parso adapters.
- **match/case**: tree-sitter-python has first-class ``match_statement`` /
  ``case_clause`` / ``*_pattern`` grammar (unlike parso 0.8's grammar,
  which has none at all — see ``parso_adapter``'s docstring finding). This
  adapter maps the common pattern shapes; an unmapped pattern shape panics
  as a MISSING rather than a guess.

A tree-sitter shape with no rule here panics as a MISSING at the boundary.
There is no generic fallback and no attribute sniffing: an unmapped node
type is the conformance finding itself.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import tree_sitter
import tree_sitter_python as tspython

from .backend import (
    Child,
    Children,
    Description,
    Leaf as SlotLeaf,
    MaybeChild,
    OpLeaf,
    OpsLeaf,
    Provider,
    ProviderHandle,
    Slot,
)
from .nodes import SourceUnit
from .operators import Operator, operator_for
from .panic import membrane_missing
from .spans import Span

TSNode = object  # tree_sitter.Node, kept untyped at the boundary

_LANGUAGE = tree_sitter.Language(tspython.language())


def _span(unit: SourceUnit, node: TSNode) -> Span:
    table = unit.line_table
    sr, sc = node.start_point
    er, ec = node.end_point
    return Span(
        table.offset_from_byte_col(sr + 1, sc),
        table.offset_from_byte_col(er + 1, ec),
    )


_SKIP_TYPES = frozenset({"comment", "line_continuation"})


def _named(node: TSNode) -> List[TSNode]:
    return [c for c in node.children if c.is_named and c.type not in _SKIP_TYPES]


def _field(node: TSNode, name: str) -> Optional[TSNode]:
    return node.child_by_field_name(name)


def _fields(node: TSNode, name: str) -> List[TSNode]:
    return list(node.children_by_field_name(name))


def _text(unit: SourceUnit, node: TSNode) -> str:
    span = _span(unit, node)
    return unit.source[span.start:span.end]


class _Handle(ProviderHandle):
    __slots__ = ("_unit", "_node", "_desc")

    def __init__(self, unit: SourceUnit, node: TSNode) -> None:
        self._unit = unit
        self._node = node
        self._desc: Optional[Description] = None

    def describe(self) -> Description:
        if self._desc is None:
            self._desc = _describe(self._unit, self._node)
        return self._desc

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ts-handle {self._node.type} in {self._unit.filename}>"


class _Fixed(ProviderHandle):
    __slots__ = ("_desc",)

    def __init__(self, desc: Description) -> None:
        self._desc = desc

    def describe(self) -> Description:
        return self._desc


def _fixed(kind: str, raw_span: Optional[Span], slots: Tuple[Tuple[str, Slot], ...],
           anchors: Tuple[Span, ...] = ()) -> _Fixed:
    return _Fixed(Description(kind=kind, raw_span=raw_span, anchors=anchors, slots=slots))


def _h(unit: SourceUnit, node: Optional[TSNode]) -> Optional[ProviderHandle]:
    return _Handle(unit, node) if node is not None else None


_BIN_TOKEN = {
    "+": "Add", "-": "Sub", "*": "Mult", "@": "MatMult", "/": "Div",
    "%": "Mod", "**": "Pow", "<<": "LShift", ">>": "RShift", "|": "BitOr",
    "^": "BitXor", "&": "BitAnd", "//": "FloorDiv",
}
_AUG_TOKEN = {k + "=": v for k, v in _BIN_TOKEN.items()}
_UNARY_TOKEN = {"+": "UAdd", "-": "USub", "~": "Invert"}
_CMP_TOKEN = {
    "<": "Lt", ">": "Gt", "==": "Eq", ">=": "GtE", "<=": "LtE", "!=": "NotEq",
    "<>": "NotEq", "in": "In", "not in": "NotIn", "is": "Is", "is not": "IsNot",
}


def _bool_kind(node_type: str) -> str:
    return {"and": "And", "or": "Or"}[node_type]


def _bare_tuple(unit: SourceUnit, elts: Sequence[TSNode], raw_span: Optional[Span]) -> ProviderHandle:
    return _fixed("Tuple", raw_span, (("elts", Children(tuple(_h(unit, e) for e in elts))),))


def _pattern_list_targets(unit: SourceUnit, node: TSNode) -> ProviderHandle:
    """pattern_list / expression_list / tuple(without parens context) -> a
    bare-tuple target, or the single element when there is exactly one."""
    elts = _named(node)
    if len(elts) == 1:
        return _h(unit, elts[0])
    return _bare_tuple(unit, elts, None)


# --------------------------------------------------------------------------
# statement bodies
# --------------------------------------------------------------------------


def _block_stmts(unit: SourceUnit, node: Optional[TSNode]) -> Tuple[ProviderHandle, ...]:
    if node is None:
        return ()
    out = []
    for c in _named(node):
        out.append(_h(unit, c))
    return tuple(out)


# --------------------------------------------------------------------------
# module / leaves
# --------------------------------------------------------------------------


def _module(unit: SourceUnit, node: TSNode) -> Description:
    body = tuple(_h(unit, c) for c in _named(node) if c.type != "comment")
    return Description(kind="Module", raw_span=Span(0, len(unit.source)), anchors=(),
                        slots=(("body", Children(body)),))


def _expression_statement(unit: SourceUnit, node: TSNode) -> Description:
    kids = _named(node)
    if len(kids) == 1:
        return _describe(unit, kids[0])
    # bare `a; b` on one physical statement line — each named child is its
    # own small statement; the membrane has no multi-statement-line node,
    # so this shape is not constructible as a single Expr and is a MISSING.
    membrane_missing(
        owner="tree_sitter_python_adapter._expression_statement",
        observed=f"expression_statement with {len(kids)} named children",
        requested="exactly one expression",
        fix="extend the caller to flatten semicolon-joined statements before this point",
    )
    raise AssertionError("unreachable")


def _leaf_identifier(unit: SourceUnit, node: TSNode) -> Description:
    return Description(kind="Name", raw_span=_span(unit, node), anchors=(),
                        slots=(("id", SlotLeaf(_text(unit, node))),))


def _fixed_constant(span: Span, value: object, literal_kind: Optional[str] = None) -> Description:
    return Description(kind="Constant", raw_span=span, anchors=(),
                        slots=(("value", SlotLeaf(value)), ("literal_kind", SlotLeaf(literal_kind))))


def _number(unit: SourceUnit, node: TSNode) -> Description:
    import ast as _pyast
    text = _text(unit, node)
    value = _pyast.literal_eval(text)
    return _fixed_constant(_span(unit, node), value)


def _string_like(unit: SourceUnit, node: TSNode) -> Description:
    """A single `string` node: plain literal, OR an f-string container
    holding `interpolation` children — dispatch on that."""
    interpolations = [c for c in node.children if c.type == "interpolation"]
    span = _span(unit, node)
    if not interpolations:
        text = _text(unit, node)
        import ast as _pyast
        try:
            value = _pyast.literal_eval(text)
        except Exception:
            value = text
        return _fixed_constant(span, value)
    values: List[ProviderHandle] = []
    for c in node.children:
        if c.type in ("string_start", "string_end"):
            continue
        if c.type == "string_content":
            values.append(_h(unit, c))
        elif c.type == "interpolation":
            values.append(_interpolation(unit, c))
        else:
            membrane_missing(
                owner="tree_sitter_python_adapter._string_like",
                observed=f"f-string child {c.type!r} not recognized",
                requested="string_content or interpolation",
                fix="extend _string_like deliberately",
            )
    return Description(kind="JoinedStr", raw_span=span, anchors=(),
                        slots=(("values", Children(tuple(values))),))


def _concatenated_string(unit: SourceUnit, node: TSNode) -> Description:
    """Implicit adjacent-string-literal concatenation: one Constant, or a
    JoinedStr if any piece has interpolation — spanning the first piece's
    start to the last's end (spec: including inter-piece whitespace)."""
    pieces = _named(node)
    span = Span(_span(unit, pieces[0]).start, _span(unit, pieces[-1]).end)
    any_fstring = any(any(c.type == "interpolation" for c in p.children) for p in pieces)
    if not any_fstring:
        import ast as _pyast
        text = "".join(_text(unit, p) for p in pieces)
        try:
            value = _pyast.literal_eval(text)
        except Exception:
            value = unit.source[span.start:span.end]
        return _fixed_constant(span, value)
    values: List[ProviderHandle] = []
    for p in pieces:
        for c in p.children:
            if c.type in ("string_start", "string_end"):
                continue
            if c.type == "string_content":
                values.append(_h(unit, c))
            elif c.type == "interpolation":
                values.append(_interpolation(unit, c))
    return Description(kind="JoinedStr", raw_span=span, anchors=(), slots=(("values", Children(tuple(values))),))


def _string_content(unit: SourceUnit, node: TSNode) -> Description:
    span = _span(unit, node)
    return _fixed_constant(span, unit.source[span.start:span.end])


def _interpolation(unit: SourceUnit, node: TSNode) -> ProviderHandle:
    value = _field(node, "expression")
    conv_node = _field(node, "type_conversion")
    conversion = ord(_text(unit, conv_node)[1]) if conv_node is not None else -1
    spec_node = _field(node, "format_specifier")
    format_spec: Optional[ProviderHandle] = None
    if spec_node is not None:
        spec_span = _span(unit, spec_node)
        spec_values: List[ProviderHandle] = []
        for c in spec_node.children:
            if not c.is_named:
                continue
            if c.type == "format_expression":
                inner = _field(c, "expression")
                spec_values.append(_interpolation_like(unit, c, inner))
            else:
                spec_values.append(_h(unit, c))
        format_spec = _fixed("JoinedStr", spec_span, (("values", Children(tuple(spec_values))),))
    return _fixed(
        "FormattedValue",
        _span(unit, node),
        (("value", Child(_h(unit, value))), ("conversion", SlotLeaf(conversion)),
         ("format_spec", MaybeChild(format_spec))),
    )


def _interpolation_like(unit: SourceUnit, node: TSNode, inner: TSNode) -> ProviderHandle:
    return _fixed("FormattedValue", _span(unit, node),
                  (("value", Child(_h(unit, inner))), ("conversion", SlotLeaf(-1)),
                   ("format_spec", MaybeChild(None))))


_SIMPLE_LEAF = {
    "true": lambda u, n: _fixed_constant(_span(u, n), True),
    "false": lambda u, n: _fixed_constant(_span(u, n), False),
    "none": lambda u, n: _fixed_constant(_span(u, n), None),
    "ellipsis": lambda u, n: _fixed_constant(_span(u, n), Ellipsis),
}


# --------------------------------------------------------------------------
# operators
# --------------------------------------------------------------------------


def _binary_operator(unit: SourceUnit, node: TSNode) -> Description:
    left = _field(node, "left")
    right = _field(node, "right")
    op_node = _field(node, "operator")
    kind = _BIN_TOKEN.get(op_node.type)
    if kind is None:
        membrane_missing(
            owner="tree_sitter_python_adapter._binary_operator",
            observed=f"binary operator token {op_node.type!r} not recognized",
            requested="a known binary operator token",
            fix="extend _BIN_TOKEN deliberately",
        )
    return Description(kind="BinOp", raw_span=_span(unit, node), anchors=(),
                        slots=(("left", Child(_h(unit, left))), ("op", OpLeaf(operator_for(kind))),
                               ("right", Child(_h(unit, right)))))


def _boolean_operator(unit: SourceUnit, node: TSNode) -> Description:
    kids = node.children
    op_type = next(c.type for c in kids if not c.is_named)
    values = _named(node)
    return Description(kind="BoolOp", raw_span=_span(unit, node), anchors=(),
                        slots=(("op", OpLeaf(operator_for(_bool_kind(op_type)))),
                               ("values", Children(tuple(_h(unit, v) for v in values)))))


def _not_operator(unit: SourceUnit, node: TSNode) -> Description:
    arg = _field(node, "argument")
    return Description(kind="UnaryOp", raw_span=_span(unit, node), anchors=(),
                        slots=(("op", OpLeaf(operator_for("Not"))), ("operand", Child(_h(unit, arg)))))


def _unary_operator(unit: SourceUnit, node: TSNode) -> Description:
    op_node = _field(node, "operator")
    arg = _field(node, "argument")
    kind = _UNARY_TOKEN.get(op_node.type)
    if kind is None:
        membrane_missing(
            owner="tree_sitter_python_adapter._unary_operator",
            observed=f"unary operator token {op_node.type!r} not recognized",
            requested="'+', '-', or '~'",
            fix="extend _UNARY_TOKEN deliberately",
        )
    return Description(kind="UnaryOp", raw_span=_span(unit, node), anchors=(),
                        slots=(("op", OpLeaf(operator_for(kind))), ("operand", Child(_h(unit, arg)))))


def _comparison_operator(unit: SourceUnit, node: TSNode) -> Description:
    kids = list(node.children)
    named = [c for c in kids if c.is_named]
    left = named[0]
    comparators = named[1:]
    op_tokens = [c for c in kids if not c.is_named]
    ops: List[Operator] = []
    for t in op_tokens:
        text = t.type if t.type not in ("is not", "not in") else t.type
        kind = _CMP_TOKEN.get(t.type)
        if kind is None:
            membrane_missing(
                owner="tree_sitter_python_adapter._comparison_operator",
                observed=f"comparison token {t.type!r} not recognized",
                requested="a known comparison operator token",
                fix="extend _CMP_TOKEN deliberately",
            )
        ops.append(operator_for(kind))
    return Description(kind="Compare", raw_span=_span(unit, node), anchors=(),
                        slots=(("left", Child(_h(unit, left))), ("ops", OpsLeaf(tuple(ops))),
                               ("comparators", Children(tuple(_h(unit, c) for c in comparators)))))


# --------------------------------------------------------------------------
# calls / subscripts / attributes
# --------------------------------------------------------------------------


def _call(unit: SourceUnit, node: TSNode) -> Description:
    func = _field(node, "function")
    arglist = _field(node, "arguments")
    args: List[ProviderHandle] = []
    keywords: List[ProviderHandle] = []
    if arglist is not None:
        if arglist.type == "generator_expression":
            args.append(_h(unit, arglist))
        else:
            for c in _named(arglist):
                if c.type == "list_splat":
                    inner = c.children[1]
                    args.append(_fixed("Starred", _span(unit, c), (("value", Child(_h(unit, inner))),)))
                elif c.type == "dictionary_splat":
                    inner = c.children[1]
                    keywords.append(_fixed("Keyword", None,
                                            (("arg", SlotLeaf(None)), ("value", Child(_h(unit, inner))))))
                elif c.type == "keyword_argument":
                    name_node = _field(c, "name")
                    value_node = _field(c, "value")
                    keywords.append(_fixed("Keyword", _span(unit, c),
                                            (("arg", SlotLeaf(_text(unit, name_node))),
                                             ("value", Child(_h(unit, value_node))))))
                else:
                    args.append(_h(unit, c))
    return Description(kind="Call", raw_span=_span(unit, node), anchors=(),
                        slots=(("func", Child(_h(unit, func))), ("args", Children(tuple(args))),
                               ("keywords", Children(tuple(keywords)))))


def _attribute(unit: SourceUnit, node: TSNode) -> Description:
    value = _field(node, "object")
    attr = _field(node, "attribute")
    return Description(kind="Attribute", raw_span=_span(unit, node), anchors=(),
                        slots=(("value", Child(_h(unit, value))), ("attr", SlotLeaf(_text(unit, attr)))))


def _subscript(unit: SourceUnit, node: TSNode) -> Description:
    value = _field(node, "value")
    subs = _fields(node, "subscript")
    if len(subs) == 1:
        slice_handle = _one_subscript_item(unit, subs[0])
    else:
        elts = tuple(_one_subscript_item(unit, s) for s in subs)
        slice_handle = _fixed("Tuple", None, (("elts", Children(elts)),))
    return Description(kind="Subscript", raw_span=_span(unit, node), anchors=(),
                        slots=(("value", Child(_h(unit, value))), ("slice_", Child(slice_handle))))


def _one_subscript_item(unit: SourceUnit, node: TSNode) -> ProviderHandle:
    if node.type != "slice":
        return _h(unit, node)
    parts = [c for c in node.children]
    segments: List[List[TSNode]] = [[]]
    for c in parts:
        if not c.is_named and c.type == ":":
            segments.append([])
        elif c.is_named:
            segments[-1].append(c)
    while len(segments) < 3:
        segments.append([])
    lower, upper, step = segments[0], segments[1], segments[2]

    def _maybe(seg: List[TSNode]) -> Slot:
        return MaybeChild(_h(unit, seg[0]) if seg else None)

    return _fixed("Slice", _span(unit, node),
                  (("lower", _maybe(lower)), ("upper", _maybe(upper)), ("step", _maybe(step))))


def _parenthesized_expression(unit: SourceUnit, node: TSNode) -> Description:
    inner = _named(node)
    if len(inner) != 1:
        membrane_missing(
            owner="tree_sitter_python_adapter._parenthesized_expression",
            observed=f"parenthesized_expression with {len(inner)} named children",
            requested="exactly one inner expression",
            fix="extend _parenthesized_expression deliberately",
        )
    return _describe(unit, inner[0])


def _tuple_expr(unit: SourceUnit, node: TSNode) -> Description:
    elts = [c for c in _named(node) if c.type != "comment"]
    return Description(kind="Tuple", raw_span=_span(unit, node), anchors=(),
                        slots=(("elts", Children(tuple(_h(unit, e) for e in elts))),))


def _list_expr(unit: SourceUnit, node: TSNode) -> Description:
    elts: List[ProviderHandle] = []
    for c in _named(node):
        if c.type == "list_splat":
            inner = c.children[1]
            elts.append(_fixed("Starred", _span(unit, c), (("value", Child(_h(unit, inner))),)))
        else:
            elts.append(_h(unit, c))
    return Description(kind="List", raw_span=_span(unit, node), anchors=(),
                        slots=(("elts", Children(tuple(elts))),))


def _set_expr(unit: SourceUnit, node: TSNode) -> Description:
    elts = tuple(_h(unit, c) for c in _named(node))
    return Description(kind="Set", raw_span=_span(unit, node), anchors=(), slots=(("elts", Children(elts)),))


def _dictionary(unit: SourceUnit, node: TSNode) -> Description:
    items: List[ProviderHandle] = []
    for c in _named(node):
        if c.type == "pair":
            key = _field(c, "key")
            value = _field(c, "value")
            items.append(_fixed("DictItem", _span(unit, c),
                                 (("key", MaybeChild(_h(unit, key))), ("value", Child(_h(unit, value))))))
        elif c.type == "dictionary_splat":
            inner = c.children[1]
            items.append(_fixed("DictItem", _span(unit, c),
                                 (("key", MaybeChild(None)), ("value", Child(_h(unit, inner))))))
        else:
            membrane_missing(
                owner="tree_sitter_python_adapter._dictionary",
                observed=f"dictionary child {c.type!r} not recognized",
                requested="pair or dictionary_splat",
                fix="extend _dictionary deliberately",
            )
    return Description(kind="Dict", raw_span=_span(unit, node), anchors=(), slots=(("items", Children(tuple(items))),))


def _comprehension_clause(unit: SourceUnit, node: TSNode) -> Description:
    """`for_in_clause` (comp_for) -> Comprehension; `if_clause` handled by
    the caller that flattens the parent list of comprehension clauses."""
    left = _field(node, "left")
    right = _field(node, "right")
    is_async = any(not c.is_named and c.type == "async" for c in node.children)
    target = _pattern_list_targets(unit, left) if left.type in ("pattern_list", "tuple_pattern") else _h(unit, left)
    return Description(kind="Comprehension", raw_span=_span(unit, node), anchors=(),
                        slots=(("target", Child(target)), ("iter", Child(_h(unit, right))),
                               ("ifs", Children(())), ("is_async", SlotLeaf(is_async))))


def _comprehension_body(unit: SourceUnit, node: TSNode, elt_field: str) -> Tuple[ProviderHandle, Tuple[ProviderHandle, ...]]:
    elt = _field(node, elt_field)
    generators: List[ProviderHandle] = []
    current_desc: Optional[Description] = None
    current_ifs: List[ProviderHandle] = []
    for c in node.children:
        if c.type == "for_in_clause":
            if current_desc is not None:
                generators.append(_finish_clause(current_desc, current_ifs))
            current_desc = _comprehension_clause(unit, c)
            current_ifs = []
        elif c.type == "if_clause":
            cond = _named(c)[0]
            current_ifs.append(_h(unit, cond))
    if current_desc is not None:
        generators.append(_finish_clause(current_desc, current_ifs))
    return _h(unit, elt), tuple(generators)


def _finish_clause(desc: Description, ifs: List[ProviderHandle]) -> ProviderHandle:
    new_slots = tuple((n, Children(tuple(ifs))) if n == "ifs" else (n, s) for n, s in desc.slots)
    return _fixed(desc.kind, desc.raw_span, new_slots, desc.anchors)


def _list_comprehension(unit: SourceUnit, node: TSNode) -> Description:
    elt, gens = _comprehension_body(unit, node, "body")
    return Description(kind="ListComp", raw_span=_span(unit, node), anchors=(),
                        slots=(("elt", Child(elt)), ("generators", Children(gens))))


def _set_comprehension(unit: SourceUnit, node: TSNode) -> Description:
    elt, gens = _comprehension_body(unit, node, "body")
    return Description(kind="SetComp", raw_span=_span(unit, node), anchors=(),
                        slots=(("elt", Child(elt)), ("generators", Children(gens))))


def _generator_expression(unit: SourceUnit, node: TSNode) -> Description:
    elt, gens = _comprehension_body(unit, node, "body")
    return Description(kind="GeneratorExp", raw_span=_span(unit, node), anchors=(),
                        slots=(("elt", Child(elt)), ("generators", Children(gens))))


def _dictionary_comprehension(unit: SourceUnit, node: TSNode) -> Description:
    body = _field(node, "body")
    key = _field(body, "key")
    value = _field(body, "value")
    generators: List[ProviderHandle] = []
    current_desc: Optional[Description] = None
    current_ifs: List[ProviderHandle] = []
    for c in node.children:
        if c.type == "for_in_clause":
            if current_desc is not None:
                generators.append(_finish_clause(current_desc, current_ifs))
            current_desc = _comprehension_clause(unit, c)
            current_ifs = []
        elif c.type == "if_clause":
            current_ifs.append(_h(unit, _named(c)[0]))
    if current_desc is not None:
        generators.append(_finish_clause(current_desc, current_ifs))
    return Description(kind="DictComp", raw_span=_span(unit, node), anchors=(),
                        slots=(("key", Child(_h(unit, key))), ("value", Child(_h(unit, value))),
                               ("generators", Children(tuple(generators)))))


def _conditional_expression(unit: SourceUnit, node: TSNode) -> Description:
    named = _named(node)
    body, test, orelse = named[0], named[1], named[2]
    return Description(kind="IfExp", raw_span=_span(unit, node), anchors=(),
                        slots=(("test", Child(_h(unit, test))), ("body", Child(_h(unit, body))),
                               ("orelse", Child(_h(unit, orelse)))))


def _named_expression(unit: SourceUnit, node: TSNode) -> Description:
    name = _field(node, "name")
    value = _field(node, "value")
    return Description(kind="NamedExpr", raw_span=_span(unit, node), anchors=(),
                        slots=(("target", Child(_h(unit, name))), ("value", Child(_h(unit, value)))))


def _yield_expr(unit: SourceUnit, node: TSNode) -> Description:
    kids = node.children
    has_from = any(not c.is_named and c.type == "from" for c in kids)
    named = _named(node)
    span = _span(unit, node)
    if has_from:
        return Description(kind="YieldFrom", raw_span=span, anchors=(), slots=(("value", Child(_h(unit, named[0]))),))
    value = named[0] if named else None
    return Description(kind="Yield", raw_span=span, anchors=(), slots=(("value", MaybeChild(_h(unit, value))),))


def _await_expr(unit: SourceUnit, node: TSNode) -> Description:
    value = _named(node)[0]
    return Description(kind="Await", raw_span=_span(unit, node), anchors=(), slots=(("value", Child(_h(unit, value))),))


def _lambda(unit: SourceUnit, node: TSNode) -> Description:
    params_node = _field(node, "parameters")
    body = _field(node, "body")
    return Description(kind="Lambda", raw_span=_span(unit, node), anchors=(),
                        slots=(("params", Children(_flatten_params(unit, params_node))), ("body", Child(_h(unit, body)))))


# --------------------------------------------------------------------------
# parameters
# --------------------------------------------------------------------------


def _flatten_params(unit: SourceUnit, node: Optional[TSNode]) -> Tuple[ProviderHandle, ...]:
    if node is None:
        return ()
    params: List[ProviderHandle] = []
    seen_star = False
    seen_slash_at: Optional[int] = None
    for c in node.children:
        if not c.is_named or c.type in _SKIP_TYPES:
            continue
        if c.type == "positional_separator":
            seen_slash_at = len(params)
            continue
        if c.type == "keyword_separator":
            seen_star = True
            continue
        params.append(_one_param(unit, c, seen_star))
    if seen_slash_at is not None:
        for i in range(seen_slash_at):
            params[i] = _retag(params[i], "positional_only")
    return tuple(params)


def _retag(handle: ProviderHandle, kind: str) -> ProviderHandle:
    desc = handle.describe()
    new_slots = tuple((n, SlotLeaf(kind)) if n == "param_kind" else (n, s) for n, s in desc.slots)
    return _fixed(desc.kind, desc.raw_span, new_slots, desc.anchors)


def _one_param(unit: SourceUnit, node: TSNode, after_star: bool) -> ProviderHandle:
    span = _span(unit, node)
    if node.type == "identifier":
        return _fixed("Param", None,
                       (("name", SlotLeaf(_text(unit, node))), ("annotation", MaybeChild(None)),
                        ("default", MaybeChild(None)),
                        ("param_kind", SlotLeaf("keyword_only" if after_star else "positional_or_keyword"))),
                       anchors=(span,))
    if node.type == "list_splat_pattern":
        name_node = _named(node)[0]
        return _fixed("Param", None,
                       (("name", SlotLeaf(_text(unit, name_node))), ("annotation", MaybeChild(None)),
                        ("default", MaybeChild(None)), ("param_kind", SlotLeaf("vararg"))),
                       anchors=(_span(unit, name_node),))
    if node.type == "dictionary_splat_pattern":
        name_node = _named(node)[0]
        return _fixed("Param", None,
                       (("name", SlotLeaf(_text(unit, name_node))), ("annotation", MaybeChild(None)),
                        ("default", MaybeChild(None)), ("param_kind", SlotLeaf("kwarg"))),
                       anchors=(_span(unit, name_node),))
    if node.type == "default_parameter":
        name_node = _field(node, "name")
        value_node = _field(node, "value")
        return _fixed("Param", None,
                       (("name", SlotLeaf(_text(unit, name_node))), ("annotation", MaybeChild(None)),
                        ("default", MaybeChild(_h(unit, value_node))),
                        ("param_kind", SlotLeaf("keyword_only" if after_star else "positional_or_keyword"))),
                       anchors=(_span(unit, name_node),))
    if node.type == "typed_parameter":
        kids = list(node.children)
        name_node = kids[0]
        annotation_node = _field(node, "type")
        kind = "positional_or_keyword"
        if name_node.type == "list_splat_pattern":
            name_node = _named(name_node)[0]
            kind = "vararg"
        elif name_node.type == "dictionary_splat_pattern":
            name_node = _named(name_node)[0]
            kind = "kwarg"
        elif after_star:
            kind = "keyword_only"
        return _fixed("Param", None,
                       (("name", SlotLeaf(_text(unit, name_node))),
                        ("annotation", MaybeChild(_h(unit, annotation_node))),
                        ("default", MaybeChild(None)), ("param_kind", SlotLeaf(kind))),
                       anchors=(_span(unit, name_node),))
    if node.type == "typed_default_parameter":
        name_node = _field(node, "name")
        annotation_node = _field(node, "type")
        value_node = _field(node, "value")
        return _fixed("Param", None,
                       (("name", SlotLeaf(_text(unit, name_node))),
                        ("annotation", MaybeChild(_h(unit, annotation_node))),
                        ("default", MaybeChild(_h(unit, value_node))),
                        ("param_kind", SlotLeaf("keyword_only" if after_star else "positional_or_keyword"))),
                       anchors=(_span(unit, name_node),))
    membrane_missing(
        owner="tree_sitter_python_adapter._one_param",
        observed=f"parameter shape {node.type!r} not recognized",
        requested="a mapped parameter shape",
        fix="extend _one_param deliberately",
    )
    raise AssertionError("unreachable")


# --------------------------------------------------------------------------
# statements
# --------------------------------------------------------------------------


def _assignment(unit: SourceUnit, node: TSNode) -> Description:
    left = _field(node, "left")
    right = _field(node, "right")
    type_node = _field(node, "type")
    span = _span(unit, node)
    if type_node is not None:
        return Description(kind="AnnAssign", raw_span=span, anchors=(),
                            slots=(("target", Child(_h(unit, left))), ("annotation", Child(_h(unit, type_node))),
                                   ("value", MaybeChild(_h(unit, right))), ("simple", SlotLeaf(True))))
    targets = [left]
    value_node = right
    while value_node is not None and value_node.type == "assignment":
        targets.append(_field(value_node, "left"))
        value_node = _field(value_node, "right")
    target_handles = tuple(_target_handle(unit, t) for t in targets)
    return Description(kind="Assign", raw_span=span, anchors=(),
                        slots=(("targets", Children(target_handles)), ("value", Child(_h(unit, value_node)))))


def _target_handle(unit: SourceUnit, node: TSNode) -> ProviderHandle:
    if node.type in ("pattern_list", "expression_list"):
        elts = _named(node)
        if len(elts) == 1:
            return _target_handle(unit, elts[0])
        return _fixed("Tuple", None, (("elts", Children(tuple(_target_handle(unit, e) for e in elts))),))
    if node.type == "tuple_pattern":
        elts = _named(node)
        return _fixed("Tuple", _span(unit, node), (("elts", Children(tuple(_target_handle(unit, e) for e in elts))),))
    if node.type == "list_pattern":
        elts = _named(node)
        return _fixed("List", _span(unit, node), (("elts", Children(tuple(_target_handle(unit, e) for e in elts))),))
    if node.type == "list_splat_pattern":
        inner = _named(node)[0]
        return _fixed("Starred", _span(unit, node), (("value", Child(_target_handle(unit, inner))),))
    return _h(unit, node)


def _augmented_assignment(unit: SourceUnit, node: TSNode) -> Description:
    left = _field(node, "left")
    right = _field(node, "right")
    op_node = _field(node, "operator")
    kind = _AUG_TOKEN.get(op_node.type)
    if kind is None:
        membrane_missing(
            owner="tree_sitter_python_adapter._augmented_assignment",
            observed=f"augmented assignment token {op_node.type!r} not recognized",
            requested="a known augmented assignment token",
            fix="extend _AUG_TOKEN deliberately",
        )
    return Description(kind="AugAssign", raw_span=_span(unit, node), anchors=(),
                        slots=(("target", Child(_h(unit, left))), ("op", OpLeaf(operator_for(kind))),
                               ("value", Child(_h(unit, right)))))


def _return_statement(unit: SourceUnit, node: TSNode) -> Description:
    named = _named(node)
    value: Optional[ProviderHandle] = None
    if named:
        if len(named) > 1:
            value = _bare_tuple(unit, named, None)
        else:
            value = _h(unit, named[0])
    return Description(kind="Return", raw_span=_span(unit, node), anchors=(), slots=(("value", MaybeChild(value)),))


def _delete_statement(unit: SourceUnit, node: TSNode) -> Description:
    named = _named(node)
    inner = named[0]
    elts = _named(inner) if inner.type == "expression_list" else [inner]
    return Description(kind="Delete", raw_span=_span(unit, node), anchors=(),
                        slots=(("targets", Children(tuple(_h(unit, e) for e in elts))),))


def _raise_statement(unit: SourceUnit, node: TSNode) -> Description:
    exc = _field(node, None) if False else None
    named = [c for c in node.children if c.is_named]
    cause = _field(node, "cause")
    exc_node = named[0] if named and named[0] is not cause else None
    if named and cause is not None and named[0] is cause:
        exc_node = None
    elif named:
        exc_node = named[0]
    return Description(kind="Raise", raw_span=_span(unit, node), anchors=(),
                        slots=(("exc", MaybeChild(_h(unit, exc_node))), ("cause", MaybeChild(_h(unit, cause)))))


def _assert_statement(unit: SourceUnit, node: TSNode) -> Description:
    named = _named(node)
    test = named[0]
    msg = named[1] if len(named) > 1 else None
    return Description(kind="Assert", raw_span=_span(unit, node), anchors=(),
                        slots=(("test", Child(_h(unit, test))), ("msg", MaybeChild(_h(unit, msg)))))


def _global_statement(unit: SourceUnit, node: TSNode) -> Description:
    names = tuple(_text(unit, c) for c in _named(node))
    return Description(kind="Global", raw_span=_span(unit, node), anchors=(), slots=(("names", SlotLeaf(names)),))


def _nonlocal_statement(unit: SourceUnit, node: TSNode) -> Description:
    names = tuple(_text(unit, c) for c in _named(node))
    return Description(kind="Nonlocal", raw_span=_span(unit, node), anchors=(), slots=(("names", SlotLeaf(names)),))


def _if_statement(unit: SourceUnit, node: TSNode) -> Description:
    test = _field(node, "condition")
    body = _block_stmts(unit, _field(node, "consequence"))
    alt = _field(node, "alternative")
    orelse: Tuple[ProviderHandle, ...]
    if alt is None:
        orelse = ()
    elif alt.type == "elif_clause":
        orelse = (_elif_handle(unit, alt),)
    else:  # else_clause
        orelse = _block_stmts(unit, _field(alt, "body"))
    return Description(kind="If", raw_span=_span(unit, node), anchors=(),
                        slots=(("test", Child(_h(unit, test))), ("body", Children(body)), ("orelse", Children(orelse))))


def _elif_handle(unit: SourceUnit, node: TSNode) -> ProviderHandle:
    test = _field(node, "condition")
    body = _block_stmts(unit, _field(node, "consequence"))
    alt = _field(node, "alternative")
    if alt is None:
        orelse: Tuple[ProviderHandle, ...] = ()
    elif alt.type == "elif_clause":
        orelse = (_elif_handle(unit, alt),)
    else:
        orelse = _block_stmts(unit, _field(alt, "body"))
    return _fixed("If", _span(unit, node),
                  (("test", Child(_h(unit, test))), ("body", Children(body)), ("orelse", Children(orelse))))


def _while_statement(unit: SourceUnit, node: TSNode) -> Description:
    test = _field(node, "condition")
    body = _block_stmts(unit, _field(node, "body"))
    alt = _field(node, "alternative")
    orelse = _block_stmts(unit, _field(alt, "body")) if alt is not None else ()
    return Description(kind="While", raw_span=_span(unit, node), anchors=(),
                        slots=(("test", Child(_h(unit, test))), ("body", Children(body)), ("orelse", Children(orelse))))


def _for_statement(unit: SourceUnit, node: TSNode) -> Description:
    left = _field(node, "left")
    right = _field(node, "right")
    target = _target_handle(unit, left)
    it = right if right.type != "expression_list" else None
    iter_handle = _pattern_list_targets(unit, right) if it is None else _h(unit, right)
    body = _block_stmts(unit, _field(node, "body"))
    alt = _field(node, "alternative")
    orelse = _block_stmts(unit, _field(alt, "body")) if alt is not None else ()
    kind = "AsyncFor" if any(not c.is_named and c.type == "async" for c in node.children) else "For"
    return Description(kind=kind, raw_span=_span(unit, node), anchors=(),
                        slots=(("target", Child(target)), ("iter", Child(iter_handle)),
                               ("body", Children(body)), ("orelse", Children(orelse))))


def _with_statement(unit: SourceUnit, node: TSNode) -> Description:
    clause = _field(node, None) if False else None
    with_clause = next(c for c in node.children if c.type == "with_clause")
    items: List[ProviderHandle] = []
    for it in _named(with_clause):
        if it.type != "with_item":
            continue
        value = _field(it, "value")
        if value.type == "as_pattern":
            ctx = _named(value)[0]
            alias = _field(value, "alias")
            alias_inner = _named(alias)[0] if alias is not None else None
            items.append(_fixed("WithItem", _span(unit, it),
                                 (("context_expr", Child(_h(unit, ctx))),
                                  ("optional_vars", MaybeChild(_h(unit, alias_inner))))))
        else:
            items.append(_fixed("WithItem", _span(unit, it),
                                 (("context_expr", Child(_h(unit, value))), ("optional_vars", MaybeChild(None)))))
    body = _block_stmts(unit, _field(node, "body"))
    kind = "AsyncWith" if any(not c.is_named and c.type == "async" for c in node.children) else "With"
    return Description(kind=kind, raw_span=_span(unit, node), anchors=(),
                        slots=(("items", Children(tuple(items))), ("body", Children(body))))


def _try_statement(unit: SourceUnit, node: TSNode) -> Description:
    body = _block_stmts(unit, _field(node, "body"))
    handlers: List[ProviderHandle] = []
    orelse: Tuple[ProviderHandle, ...] = ()
    finalbody: Tuple[ProviderHandle, ...] = ()
    is_star = False
    for c in node.children:
        if c.type == "except_clause":
            if any(not k.is_named and k.type == "*" for k in c.children):
                is_star = True
            value = _field(c, "value")
            exc_type: Optional[TSNode] = None
            exc_name: Optional[str] = None
            if value is not None:
                if value.type == "as_pattern":
                    exc_type = _named(value)[0]
                    alias = _field(value, "alias")
                    exc_name = _text(unit, _named(alias)[0]) if alias is not None else None
                else:
                    exc_type = value
            handler_body = _block_stmts(unit, next(k for k in c.children if k.type == "block"))
            handlers.append(_fixed(
                "ExceptHandler", _span(unit, c),
                (("type_", MaybeChild(_h(unit, exc_type))), ("name", SlotLeaf(exc_name)),
                 ("body", Children(handler_body))),
            ))
        elif c.type == "else_clause":
            orelse = _block_stmts(unit, _field(c, "body"))
        elif c.type == "finally_clause":
            finalbody = _block_stmts(unit, next(k for k in c.children if k.type == "block"))
    kind = "TryStar" if is_star else "Try"
    return Description(kind=kind, raw_span=_span(unit, node), anchors=(),
                        slots=(("body", Children(body)), ("handlers", Children(tuple(handlers))),
                               ("orelse", Children(orelse)), ("finalbody", Children(finalbody))))


def _function_definition(unit: SourceUnit, node: TSNode) -> Description:
    name = _text(unit, _field(node, "name"))
    params = _flatten_params(unit, _field(node, "parameters"))
    returns = _field(node, "return_type")
    body = _block_stmts(unit, _field(node, "body"))
    kind = "AsyncFunctionDef" if any(not c.is_named and c.type == "async" for c in node.children) else "FunctionDef"
    return Description(kind=kind, raw_span=_span(unit, node), anchors=(),
                        slots=(("name", SlotLeaf(name)), ("params", Children(params)), ("body", Children(body)),
                               ("decorators", Children(())),
                               ("returns", MaybeChild(_h(unit, returns))), ("type_params", Children(()))))


def _class_definition(unit: SourceUnit, node: TSNode) -> Description:
    name = _text(unit, _field(node, "name"))
    supers = _field(node, "superclasses")
    bases: List[ProviderHandle] = []
    keywords: List[ProviderHandle] = []
    if supers is not None:
        for c in _named(supers):
            if c.type == "keyword_argument":
                name_node = _field(c, "name")
                value_node = _field(c, "value")
                keywords.append(_fixed("Keyword", _span(unit, c),
                                        (("arg", SlotLeaf(_text(unit, name_node))), ("value", Child(_h(unit, value_node))))))
            elif c.type == "list_splat":
                inner = c.children[1]
                bases.append(_fixed("Starred", _span(unit, c), (("value", Child(_h(unit, inner))),)))
            elif c.type == "dictionary_splat":
                inner = c.children[1]
                keywords.append(_fixed("Keyword", None, (("arg", SlotLeaf(None)), ("value", Child(_h(unit, inner))))))
            else:
                bases.append(_h(unit, c))
    body = _block_stmts(unit, _field(node, "body"))
    return Description(kind="ClassDef", raw_span=_span(unit, node), anchors=(),
                        slots=(("name", SlotLeaf(name)), ("bases", Children(tuple(bases))),
                               ("keywords", Children(tuple(keywords))), ("body", Children(body)),
                               ("decorators", Children(())), ("type_params", Children(()))))


def _decorated_definition(unit: SourceUnit, node: TSNode) -> Description:
    decorators = [c for c in node.children if c.type == "decorator"]
    dec_handles = tuple(_h(unit, _named(d)[0]) for d in decorators)
    inner = _field(node, "definition")
    base = _describe(unit, inner)
    span = Span(_span(unit, node).start, base.raw_span.end)
    new_slots = tuple((n, Children(dec_handles)) if n == "decorators" else (n, s) for n, s in base.slots)
    return Description(kind=base.kind, raw_span=span, anchors=(), slots=new_slots)


def _import_statement(unit: SourceUnit, node: TSNode) -> Description:
    names = []
    for c in node.children:
        if not c.is_named or c.type in _SKIP_TYPES:
            continue
        names.append(_import_alias(unit, c))
    return Description(kind="Import", raw_span=_span(unit, node), anchors=(), slots=(("names", Children(tuple(names))),))


def _import_alias(unit: SourceUnit, node: TSNode) -> ProviderHandle:
    if node.type == "aliased_import":
        name_node = _field(node, "name")
        alias_node = _field(node, "alias")
        return _fixed("ImportAlias", _span(unit, node),
                      (("name", SlotLeaf(_dotted_str(unit, name_node))), ("asname", SlotLeaf(_text(unit, alias_node)))))
    return _fixed("ImportAlias", _span(unit, node), (("name", SlotLeaf(_dotted_str(unit, node))), ("asname", SlotLeaf(None))))


def _dotted_str(unit: SourceUnit, node: TSNode) -> str:
    return _text(unit, node)


def _import_from_statement(unit: SourceUnit, node: TSNode) -> Description:
    module_node = _field(node, "module_name")
    level = 0
    module: Optional[str] = None
    if module_node is not None:
        if module_node.type == "relative_import":
            prefix = _field(module_node, None) if False else next(
                (c for c in module_node.children if c.type == "import_prefix"), None
            )
            if prefix is not None:
                level = sum(1 for c in prefix.children if c.type == ".")
            dotted = next((c for c in module_node.children if c.type == "dotted_name"), None)
            module = _text(unit, dotted) if dotted is not None else None
        else:
            module = _dotted_str(unit, module_node)
    names_nodes = _fields(node, "name")
    star_node = next((c for c in node.children if not c.is_named and c.type == "*"), None)
    if star_node is not None:
        names = (_fixed("ImportAlias", _span(unit, star_node),
                         (("name", SlotLeaf("*")), ("asname", SlotLeaf(None)))),)
    else:
        names = tuple(_import_alias(unit, n) for n in names_nodes)
    return Description(kind="ImportFrom", raw_span=_span(unit, node), anchors=(),
                        slots=(("module", SlotLeaf(module)), ("names", Children(names)), ("level", SlotLeaf(level))))


def _dotted_name_expr(unit: SourceUnit, node: TSNode) -> ProviderHandle:
    """`a.b.c` used as an expression (e.g. a match-pattern class name), built
    as nested Attribute over its identifier parts — only reachable here for
    a bare dotted_name that never went through the normal atom_expr/trailer
    fold (match patterns hold it directly, not inside an atom_expr)."""
    parts = [c for c in node.children if c.type == "identifier"]
    acc: ProviderHandle = _h(unit, parts[0])
    start = _span(unit, parts[0]).start
    for p in parts[1:]:
        end = _span(unit, p).end
        acc = _fixed("Attribute", Span(start, end), (("value", Child(acc)), ("attr", SlotLeaf(_text(unit, p)))))
    return acc


def _generic_type(unit: SourceUnit, node: TSNode) -> Description:
    """`Name[Args]` in annotation position (e.g. ``Generic[T]``, ``list[int]``
    written where the grammar treats it as a type rather than an expression)
    — same shape as a subscript, mapped the same way."""
    kids = _named(node)
    base = kids[0]
    type_params = kids[1]
    items = [c for c in type_params.children if c.is_named and c.type != "comment"]
    if len(items) == 1:
        slice_handle = _one_subscript_item(unit, items[0])
    else:
        slice_handle = _fixed("Tuple", None, (("elts", Children(tuple(_one_subscript_item(unit, i) for i in items))),))
    return Description(kind="Subscript", raw_span=_span(unit, node), anchors=(),
                        slots=(("value", Child(_h(unit, base))), ("slice_", Child(slice_handle))))


def _type_alias_statement(unit: SourceUnit, node: TSNode) -> Description:
    # PEP 695 `type X = int` / `type X[T] = list[T]`. Generic `[T]` type
    # parameters are not further destructured here (rare in this corpus);
    # an alias with them still constructs, just with an empty type_params.
    left = _field(node, "left")
    right = _field(node, "right")
    name_expr = _named(left)[0] if left.type not in ("identifier",) else left
    return Description(kind="TypeAlias", raw_span=_span(unit, node), anchors=(),
                        slots=(("name", Child(_h(unit, name_expr))), ("type_params", Children(())),
                               ("value", Child(_h(unit, _named(right)[0] if right.type == "type" else right)))))


def _future_import_statement(unit: SourceUnit, node: TSNode) -> Description:
    names = tuple(_import_alias(unit, n) for n in _fields(node, "name"))
    return Description(kind="ImportFrom", raw_span=_span(unit, node), anchors=(),
                        slots=(("module", SlotLeaf("__future__")), ("names", Children(names)), ("level", SlotLeaf(0))))


def _match_statement(unit: SourceUnit, node: TSNode) -> Description:
    subject = _field(node, "subject")
    block = next(c for c in node.children if c.type == "block")
    cases = []
    for c in block.children:
        if c.type != "case_clause":
            continue
        cases.append(_case_clause(unit, c))
    return Description(kind="Match", raw_span=_span(unit, node), anchors=(),
                        slots=(("subject", Child(_h(unit, subject))), ("cases", Children(tuple(cases)))))


def _case_clause(unit: SourceUnit, node: TSNode) -> ProviderHandle:
    # tree-sitter-python does not expose a 'pattern' field on case_clause;
    # the pattern(s) are the case_pattern named children preceding 'if'/':'.
    pattern_nodes = [c for c in node.children if c.type == "case_pattern"]
    guard = _field(node, "guard")
    body_node = _field(node, "consequence")
    body = _block_stmts(unit, body_node)
    if len(pattern_nodes) == 1:
        pattern = _pattern(unit, pattern_nodes[0])
    else:
        pat_span = Span(_span(unit, pattern_nodes[0]).start, _span(unit, pattern_nodes[-1]).end)
        pattern = _fixed("MatchSequence", pat_span,
                          (("patterns", Children(tuple(_pattern(unit, p) for p in pattern_nodes))),))
    guard_cond = _named(guard)[0] if guard is not None else None
    return _fixed("MatchCase", _span(unit, node),
                  (("pattern", Child(pattern)), ("guard", MaybeChild(_h(unit, guard_cond))),
                   ("body", Children(body))))


def _pattern(unit: SourceUnit, node: TSNode) -> ProviderHandle:
    if node.type == "case_pattern":
        inner = _named(node)
        if len(inner) == 1:
            return _pattern(unit, inner[0])
        return _fixed("MatchSequence", _span(unit, node),
                       (("patterns", Children(tuple(_pattern(unit, p) for p in inner))),))
    span = _span(unit, node)
    if node.type == "_":
        return _fixed("MatchAs", span, (("pattern", MaybeChild(None)), ("name", SlotLeaf(None))))
    if node.type in ("integer", "float", "true", "false", "none", "string", "complex_pattern", "unary_operator",
                      "concatenated_string"):
        return _h(unit, node) if node.type != "true" and node.type != "false" and node.type != "none" else _Fixed(_SIMPLE_LEAF[node.type](unit, node))
    if node.type == "identifier":
        return _fixed("MatchAs", span, (("pattern", MaybeChild(None)), ("name", SlotLeaf(_text(unit, node)))))
    if node.type in ("dotted_name", "attribute"):
        return _fixed("MatchValue", span, (("value", Child(_h(unit, node))),))
    if node.type in ("list_pattern", "tuple_pattern"):
        items = []
        for c in _named(node):
            items.append(_pattern_item(unit, c))
        return _fixed("MatchSequence", span, (("patterns", Children(tuple(items))),))
    if node.type == "splat_pattern":
        inner = _named(node)
        name = _text(unit, inner[0]) if inner else None
        return _fixed("MatchStar", span, (("name", SlotLeaf(name)),))
    if node.type == "as_pattern":
        inner = _named(node)[0]
        target = _field(node, "alias") or (node.children[-1] if node.children else None)
        target_name = None
        tn = _fields(node, "alias")
        if tn:
            tgt = tn[0]
            target_name = _text(unit, _named(tgt)[0] if tgt.type == "as_pattern_target" else tgt)
        return _fixed("MatchAs", span, (("pattern", MaybeChild(_pattern(unit, inner))), ("name", SlotLeaf(target_name))))
    if node.type == "union_pattern":
        items = [_pattern(unit, c) for c in _named(node)]
        return _fixed("MatchOr", span, (("patterns", Children(tuple(items))),))
    if node.type == "class_pattern":
        cls_node = _named(node)[0]
        positional: List[ProviderHandle] = []
        kwd_attrs: List[str] = []
        kwd_patterns: List[ProviderHandle] = []
        for raw in _named(node)[1:]:
            # each argument is wrapped in its own case_pattern
            c = _named(raw)[0] if raw.type == "case_pattern" else raw
            if c.type == "keyword_pattern":
                kn = _named(c)[0]
                kv = _named(c)[1]
                kwd_attrs.append(_text(unit, kn))
                kwd_patterns.append(_pattern_item(unit, kv))
            else:
                positional.append(_pattern_item(unit, c))
        return _fixed("MatchClass", span,
                      (("cls_", Child(_h(unit, cls_node))), ("patterns", Children(tuple(positional))),
                       ("kwd_attrs", SlotLeaf(tuple(kwd_attrs))), ("kwd_patterns", Children(tuple(kwd_patterns)))))
    if node.type == "dict_pattern":
        keys: List[ProviderHandle] = []
        patterns: List[ProviderHandle] = []
        rest: Optional[str] = None
        kids = list(node.children)
        i = 0
        while i < len(kids):
            c = kids[i]
            if not c.is_named:
                i += 1
                continue
            if c.type == "splat_pattern":
                inner = _named(c)
                rest = _text(unit, inner[0]) if inner else None
                i += 1
                continue
            key_node = c
            # next named child is the value pattern (case_pattern)
            j = i + 1
            while j < len(kids) and not kids[j].is_named:
                j += 1
            value_node = kids[j]
            keys.append(_h(unit, key_node))
            patterns.append(_pattern_item(unit, value_node))
            i = j + 1
        return _fixed("MatchMapping", span,
                      (("keys", Children(tuple(keys))), ("patterns", Children(tuple(patterns))), ("rest", SlotLeaf(rest))))
    membrane_missing(
        owner="tree_sitter_python_adapter._pattern",
        observed=f"case pattern shape {node.type!r} not recognized",
        requested="a mapped match-pattern shape",
        fix="extend _pattern deliberately",
    )
    raise AssertionError("unreachable")


def _pattern_item(unit: SourceUnit, node: TSNode) -> ProviderHandle:
    if node.type == "case_pattern":
        return _pattern(unit, node)
    return _pattern(unit, node)


# --------------------------------------------------------------------------
# top-level dispatch
# --------------------------------------------------------------------------


_LEAF_DISPATCH = {
    "identifier": _leaf_identifier,
    "integer": _number,
    "float": _number,
    "string": _string_like,
    "string_content": _string_content,
    "concatenated_string": _concatenated_string,
}


def _describe(unit: SourceUnit, node: TSNode) -> Description:
    t = node.type
    if not node.is_named:
        membrane_missing(
            owner="tree_sitter_python_adapter._describe",
            observed=f"unnamed/punctuation node {t!r} reached the dispatcher",
            requested="a named grammar node",
            fix="filter this token out one level up",
        )
    if t in _SIMPLE_LEAF:
        return _SIMPLE_LEAF[t](unit, node)
    leaf_fn = _LEAF_DISPATCH.get(t)
    if leaf_fn is not None:
        return leaf_fn(unit, node)
    fn = _DISPATCH.get(t)
    if fn is not None:
        return fn(unit, node)
    membrane_missing(
        owner="tree_sitter_python_adapter._describe",
        observed=f"tree-sitter node type {t!r} has no translation rule",
        requested="a mapped statement/expression shape",
        fix="add a translation rule for this node type; never guess",
    )
    raise AssertionError("unreachable")


_DISPATCH = {
    "module": _module,
    "expression_statement": _expression_statement,
    "assignment": _assignment,
    "augmented_assignment": _augmented_assignment,
    "return_statement": _return_statement,
    "delete_statement": _delete_statement,
    "raise_statement": _raise_statement,
    "assert_statement": _assert_statement,
    "global_statement": _global_statement,
    "nonlocal_statement": _nonlocal_statement,
    "pass_statement": lambda u, n: Description(kind="Pass", raw_span=_span(u, n), anchors=(), slots=()),
    "break_statement": lambda u, n: Description(kind="Break", raw_span=_span(u, n), anchors=(), slots=()),
    "continue_statement": lambda u, n: Description(kind="Continue", raw_span=_span(u, n), anchors=(), slots=()),
    "if_statement": _if_statement,
    "while_statement": _while_statement,
    "for_statement": _for_statement,
    "with_statement": _with_statement,
    "try_statement": _try_statement,
    "function_definition": _function_definition,
    "class_definition": _class_definition,
    "decorated_definition": _decorated_definition,
    "import_statement": _import_statement,
    "import_from_statement": _import_from_statement,
    "match_statement": _match_statement,
    "binary_operator": _binary_operator,
    "boolean_operator": _boolean_operator,
    "not_operator": _not_operator,
    "unary_operator": _unary_operator,
    "comparison_operator": _comparison_operator,
    "call": _call,
    "attribute": _attribute,
    "subscript": _subscript,
    "parenthesized_expression": _parenthesized_expression,
    "tuple": _tuple_expr,
    "list": _list_expr,
    "set": _set_expr,
    "dictionary": _dictionary,
    "list_comprehension": _list_comprehension,
    "set_comprehension": _set_comprehension,
    "dictionary_comprehension": _dictionary_comprehension,
    "generator_expression": _generator_expression,
    "conditional_expression": _conditional_expression,
    "named_expression": _named_expression,
    "yield": _yield_expr,
    "await": _await_expr,
    "lambda": _lambda,
    "pattern_list": lambda u, n: _pattern_list_targets(u, n).describe(),
    "expression_list": lambda u, n: _pattern_list_targets(u, n).describe(),
    "type": lambda u, n: _describe(u, _named(n)[0]),
    "type_alias_statement": _type_alias_statement,
    "future_import_statement": _future_import_statement,
    "dotted_name": lambda u, n: _dotted_name_expr(u, n).describe(),
    "generic_type": _generic_type,
    "splat_type": lambda u, n: Description(
        kind="Starred", raw_span=_span(u, n), anchors=(),
        slots=(("value", Child(_h(u, _named(n)[0]))),),
    ),
    "list_splat": lambda u, n: Description(
        kind="Starred", raw_span=_span(u, n), anchors=(),
        slots=(("value", Child(_h(u, _named(n)[0]))),),
    ),
    # PEP 604 `X | Y` written in annotation position parses as its own
    # 'union_type' node rather than a binary_operator (the '|' expression
    # form still goes through binary_operator/BinOp as usual) — same shape.
    "union_type": lambda u, n: Description(
        kind="BinOp", raw_span=_span(u, n), anchors=(),
        slots=(("left", Child(_h(u, _named(n)[0]))), ("op", OpLeaf(operator_for("BitOr"))),
               ("right", Child(_h(u, _named(n)[1])))),
    ),
}


class TreeSitterPythonProvider(Provider):
    """tree-sitter-python: C, incremental — the fourth candidate provider."""

    name = "tree-sitter-python"

    def __init__(self) -> None:
        self._parser = tree_sitter.Parser(_LANGUAGE)

    def parse(self, unit: SourceUnit) -> ProviderHandle:
        tree = self._parser.parse(unit.source.encode("utf-8"))
        root = tree.root_node
        if root.has_error:
            raise SyntaxError(
                f"tree-sitter-python reported a parse error in {unit.filename}"
            )
        return _Handle(unit, root)
