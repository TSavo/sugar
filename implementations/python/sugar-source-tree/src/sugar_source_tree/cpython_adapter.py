"""CPython ``ast`` backend adapter.

THE ONLY MODULE IN THIS PACKAGE THAT MAY NAME ``ast``. Everything it hands
up is a read-only ``BackendNode`` describing itself in tree terms:
our kinds, our field names, our codepoint spans. CPython's 1-based-line /
UTF-8-byte-column convention is normalized here, once, via
``LineTable.offset_from_byte_col``, and never travels further.

Nothing is ever written onto an ``ast`` node (no stamping). Where CPython
supplies no position (``comprehension``, ``match_case``, ``withitem``,
parameters-with-defaults), the description carries ``raw_span=None`` plus
anchor spans, and the builder takes the envelope per the span spec.

Where CPython's shape vocabulary differs from ours, translation happens
here: ``arguments`` is flattened into ``Param`` handles with defaults
re-associated; ``Dict`` becomes ``DictItem`` pairs; operator nodes become
``Operator`` singletons; ``ctx`` (Load/Store/Del) and ``type_comment`` are
not part of our inventory and are not materialized.

An ``ast`` shape this adapter does not recognize panics as a MISSING at the
boundary — never a permissive fallback.

Source ``ast.parse`` cannot parse at all (a syntax error, or a null byte —
``ValueError`` on some CPython versions, ``SyntaxError`` on others; both
mean the same thing: this text is not valid Python) is never let through as
CPython's own exception type. It is re-raised as ``BackendCouldNotParse``
(backend.py) — the tree's own name for "the backend declined this
input" — so no caller above this module ever needs to know CPython is
behind the tree today.
"""

from __future__ import annotations

import ast
from typing import Optional, Tuple

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
from .panic import vocabulary_missing
from .spans import Span


def _op(node: ast.AST) -> Operator:
    return operator_for(type(node).__name__)


class _Handle(BackendNode):
    """Read-only view of one ast node (or synthetic constituent)."""

    __slots__ = ("_unit", "_node", "_desc")

    def __init__(self, unit: SourceUnit, node: ast.AST) -> None:
        self._unit = unit
        self._node = node
        self._desc: Optional[Description] = None

    def describe(self) -> Description:
        if self._desc is None:
            self._desc = _describe(self._unit, self._node)
        return self._desc

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ast-handle {type(self._node).__name__} in {self._unit.filename}>"


class _ParamHandle(BackendNode):
    """Synthetic constituent: one formal parameter with its default."""

    __slots__ = ("_unit", "_arg", "_default", "_kind", "_desc")

    def __init__(
        self,
        unit: SourceUnit,
        arg: ast.arg,
        default: Optional[ast.expr],
        param_kind: str,
    ) -> None:
        self._unit = unit
        self._arg = arg
        self._default = default
        self._kind = param_kind
        self._desc: Optional[Description] = None

    def describe(self) -> Description:
        if self._desc is None:
            unit = self._unit
            slots: Tuple[Tuple[str, Slot], ...] = (
                ("name", Leaf(self._arg.arg)),
                (
                    "annotation",
                    MaybeChild(
                        _Handle(unit, self._arg.annotation)
                        if self._arg.annotation is not None
                        else None
                    ),
                ),
                (
                    "default",
                    MaybeChild(
                        _Handle(unit, self._default)
                        if self._default is not None
                        else None
                    ),
                ),
                ("param_kind", Leaf(self._kind)),
            )
            # Anchor: the name(+annotation) token span; envelope adds default.
            self._desc = Description(
                kind="Param",
                raw_span=None,
                anchors=(_node_span(unit, self._arg),),
                slots=slots,
            )
        return self._desc

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ast-param-handle {self._arg.arg!r} in {self._unit.filename}>"


class _FormatSpecHandle(_Handle):
    """A format spec inside an f-string replacement field.

    CPython positions the spec ``JoinedStr`` starting at the ``:``. Our
    ruling (spans.py): the colon is the delimiter introducing the spec,
    not part of it — the spec spans the text after the colon.
    """

    def describe(self) -> Description:
        if self._desc is None:
            base = _describe(self._unit, self._node)
            raw = base.raw_span
            if raw is not None and self._unit.source[raw.start : raw.start + 1] == ":":
                raw = Span(raw.start + 1, raw.end)
            self._desc = Description(
                kind=base.kind, raw_span=raw, anchors=base.anchors, slots=base.slots
            )
        return self._desc


class _DictItemHandle(BackendNode):
    """Synthetic constituent: one key/value entry of a Dict display."""

    __slots__ = ("_unit", "_key", "_value", "_desc")

    def __init__(
        self, unit: SourceUnit, key: Optional[ast.expr], value: ast.expr
    ) -> None:
        self._unit = unit
        self._key = key
        self._value = value
        self._desc: Optional[Description] = None

    def describe(self) -> Description:
        if self._desc is None:
            unit = self._unit
            self._desc = Description(
                kind="DictItem",
                raw_span=None,
                anchors=(),
                slots=(
                    (
                        "key",
                        MaybeChild(
                            _Handle(unit, self._key) if self._key is not None else None
                        ),
                    ),
                    ("value", Child(_Handle(unit, self._value))),
                ),
            )
        return self._desc

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ast-dictitem-handle in {self._unit.filename}>"


def _node_span(unit: SourceUnit, node: ast.AST) -> Span:
    """CPython position -> our codepoint Span. The one byte->codepoint seam."""
    lineno = getattr(node, "lineno", None)
    end_lineno = getattr(node, "end_lineno", None)
    if lineno is None or end_lineno is None:
        vocabulary_missing(
            owner="cpython_adapter._node_span",
            observed=f"ast.{type(node).__name__} without a position",
            requested="a positioned node, or a describe() rule marking it envelope-spanned",
            fix="add an explicit rule for this kind; never invent a span",
        )
    table = unit.line_table
    start = table.offset_from_byte_col(lineno, node.col_offset)
    end = table.offset_from_byte_col(end_lineno, node.end_col_offset)
    return Span(start, end)


def _flatten_params(
    unit: SourceUnit, arguments: ast.arguments
) -> Tuple[BackendNode, ...]:
    """ast.arguments -> ordered Param handles with defaults re-associated."""
    params: list[BackendNode] = []
    positional = list(arguments.posonlyargs) + list(arguments.args)
    defaults = list(arguments.defaults)
    # defaults right-align against the positional parameters
    pad: list[Optional[ast.expr]] = [None] * (len(positional) - len(defaults))
    pos_defaults = pad + defaults
    for i, arg in enumerate(arguments.posonlyargs):
        params.append(_ParamHandle(unit, arg, pos_defaults[i], "positional_only"))
    base = len(arguments.posonlyargs)
    for i, arg in enumerate(arguments.args):
        params.append(
            _ParamHandle(unit, arg, pos_defaults[base + i], "positional_or_keyword")
        )
    if arguments.vararg is not None:
        params.append(_ParamHandle(unit, arguments.vararg, None, "vararg"))
    for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        params.append(_ParamHandle(unit, arg, default, "keyword_only"))
    if arguments.kwarg is not None:
        params.append(_ParamHandle(unit, arguments.kwarg, None, "kwarg"))
    return tuple(params)


# ast field names whose contents are not part of our node inventory.
_DROPPED_FIELDS = frozenset({"ctx", "type_comment", "type_ignores"})

# our-field-name overrides, per ast kind, applied in the generic path
_FIELD_RENAMES: dict[str, dict[str, str]] = {
    "FunctionDef": {"decorator_list": "decorators"},
    "AsyncFunctionDef": {"decorator_list": "decorators"},
    "ClassDef": {"decorator_list": "decorators"},
    "Subscript": {"slice": "slice_"},
    "ExceptHandler": {"type": "type_"},
    "MatchClass": {"cls": "cls_"},
    "Constant": {"kind": "literal_kind"},
    "alias": {},
}

# ast kind -> our kind, where they differ
_KIND_RENAMES = {
    "alias": "ImportAlias",
    "keyword": "Keyword",
    "comprehension": "Comprehension",
    "withitem": "WithItem",
    "match_case": "MatchCase",
}


def _comprehension_for_anchor(unit: SourceUnit, comp: ast.comprehension) -> Span:
    """The clause's ``for`` (or ``async for``) keyword start, found by a
    pure backscan of the source from the target: between the keyword and
    its target only whitespace can occur."""
    table = unit.line_table
    target_start = table.offset_from_byte_col(
        comp.target.lineno, comp.target.col_offset
    )
    src = unit.source
    j = target_start
    while j > 0 and src[j - 1].isspace():
        j -= 1
    if src[max(0, j - 3) : j] != "for":
        vocabulary_missing(
            owner="cpython_adapter._comprehension_for_anchor",
            observed=f"no 'for' keyword immediately before comprehension target at {target_start}",
            requested="'for' (optionally 'async for') preceding the target",
            fix="the backscan rule is wrong for this shape; extend it deliberately",
        )
    for_start = j - 3
    k = for_start
    while k > 0 and src[k - 1].isspace():
        k -= 1
    if src[max(0, k - 5) : k] == "async":
        for_start = k - 5
    return Span(for_start, for_start)

# kinds the backend does not position: envelope-spanned per the spec
_ENVELOPE_KINDS = frozenset({"comprehension", "withitem", "match_case"})


def _describe(unit: SourceUnit, node: ast.AST) -> Description:
    ast_kind = type(node).__name__
    kind = _KIND_RENAMES.get(ast_kind, ast_kind)
    renames = _FIELD_RENAMES.get(ast_kind, {})
    slots: list[Tuple[str, Slot]] = []

    if isinstance(node, ast.Module):
        return Description(
            kind="Module",
            raw_span=Span(0, len(unit.source)),
            anchors=(),
            slots=(
                (
                    "body",
                    Children(tuple(_Handle(unit, stmt) for stmt in node.body)),
                ),
            ),
        )

    if isinstance(node, ast.FormattedValue):
        spec_slot: Slot = MaybeChild(
            _FormatSpecHandle(unit, node.format_spec)
            if node.format_spec is not None
            else None
        )
        return Description(
            kind="FormattedValue",
            raw_span=_node_span(unit, node),
            anchors=(),
            slots=(
                ("value", Child(_Handle(unit, node.value))),
                ("conversion", Leaf(node.conversion)),
                ("format_spec", spec_slot),
            ),
        )

    if isinstance(node, ast.Dict):
        items = tuple(
            _DictItemHandle(unit, key, value)
            for key, value in zip(node.keys, node.values)
        )
        return Description(
            kind="Dict",
            raw_span=_node_span(unit, node),
            anchors=(),
            slots=(("items", Children(items)),),
        )

    for field_name, value in ast.iter_fields(node):
        if field_name in _DROPPED_FIELDS:
            continue
        our_name = renames.get(field_name, field_name)
        if field_name == "args" and isinstance(value, ast.arguments):
            slots.append(("params", Children(_flatten_params(unit, value))))
            continue
        if field_name == "ops" and isinstance(node, ast.Compare):
            slots.append(("ops", OpsLeaf(tuple(_op(op) for op in value))))
            continue
        if isinstance(value, (ast.boolop, ast.operator, ast.unaryop)):
            slots.append((our_name, OpLeaf(_op(value))))
            continue
        if isinstance(value, ast.AST):
            slots.append((our_name, Child(_Handle(unit, value))))
            continue
        if isinstance(value, list):
            if value and all(isinstance(item, str) for item in value):
                # Global.names / Nonlocal.names / MatchClass.kwd_attrs
                slots.append((our_name, Leaf(tuple(value))))
                continue
            if all(isinstance(item, ast.AST) for item in value):
                slots.append(
                    (
                        our_name,
                        Children(tuple(_Handle(unit, item) for item in value)),
                    )
                )
                continue
            vocabulary_missing(
                owner="cpython_adapter._describe",
                observed=(
                    f"ast.{ast_kind}.{field_name} list with unhandled item "
                    f"types {sorted({type(i).__name__ for i in value})}"
                ),
                requested="a homogeneous node list or a string list",
                fix="add an explicit translation rule for this field; never guess",
            )
        if value is None:
            # optional child vs absent leaf: both surface as MaybeChild/Leaf.
            # Membrane classes type the field; None means structural absence.
            slots.append((our_name, MaybeChild(None)))
            continue
        slots.append((our_name, Leaf(value)))

    anchors: Tuple[Span, ...] = ()
    if ast_kind in _ENVELOPE_KINDS:
        raw_span: Optional[Span] = None
        if isinstance(node, ast.comprehension):
            anchors = (_comprehension_for_anchor(unit, node),)
    else:
        raw_span = _node_span(unit, node)

    return Description(kind=kind, raw_span=raw_span, anchors=anchors, slots=tuple(slots))


class CPythonAstBackend(Backend):
    """The reference backend: CPython's own parser, behind the tree."""

    name = "cpython-ast"

    def fingerprint(self) -> str:
        """CPython's ``ast`` produces a version-dependent node stream (e.g. the
        empty ``Constant("")`` it staples into a nested f-string format spec on
        3.12 but not 3.14), so the interpreter IS this backend's version-of-
        record. Key the golden on it: same source, same interpreter -> same
        tree; a new interpreter is faithfully its own pin."""
        import sys

        v = sys.version_info
        return f"{self.name}-{sys.implementation.name}-{v.major}.{v.minor}"

    def root(self, unit: SourceUnit) -> BackendNode:
        try:
            tree = ast.parse(unit.source, filename=unit.filename)
        except (SyntaxError, ValueError) as err:
            # SyntaxError: the ordinary parse failure (including TabError,
            # IndentationError). ValueError: some CPython versions raise it
            # instead of SyntaxError for a null byte in the source. Both are
            # CPython declining this text — never let either escape as-is.
            raise BackendCouldNotParse(
                backend=self.name, file=unit.filename, reason=str(err)
            ) from err
        return _Handle(unit, tree)
