from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import List, cast

from .block import Block


def _is_suite(value) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, ast.stmt) for item in value)
    )


def _dotted_expr_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        receiver = _dotted_expr_name(node.value)
        if receiver is not None:
            return f"{receiver}.{node.attr}"
    return None


@dataclass(frozen=True)
class SourceFragment:
    """A fragment of source -- the one object the factory uses to talk to the AST.

    It holds the node and where it lives (so it owns `observed`/`blame`/the suggested
    sugar), and it knows how to DECOMPOSE itself into smaller fragments on demand:
    a function body fragments into its statements, a statement into its terms. Both
    sugar construction (build a sugar FROM a fragment) and factory reporting (read the
    fragment's source) hold the same object, so nothing is ever taken apart and zipped
    back together.
    """

    node: ast.AST
    filename: str
    line: int
    col: int
    # The file's full source text: what the fragment content-addresses its own
    # covered segment against when it emits its memento. None only for bare
    # nodes constructed without source (their memento() refuses, loudly).
    source: str | None = None

    @classmethod
    def from_node(
        cls, node: object, filename: str, source: str | None = None
    ) -> "SourceFragment":
        # A container node (Module) has no position; it is never a site itself, only a
        # source of fragments, so default its position rather than fail to wrap it.
        # Block is the factory's synthetic suite node; SourceFragment is the sole
        # gateway allowed to carry it beside real ast nodes.
        if not isinstance(node, (ast.AST, Block)):
            raise TypeError(
                f"SourceFragment.from_node requires ast.AST or Block, got "
                f"{type(node).__name__}"
            )
        return cls(
            node=cast(ast.AST, node),
            filename=filename,
            line=getattr(node, "lineno", 0),
            col=getattr(node, "col_offset", 0),
            source=source,
        )

    def memento(self):
        # The fragment EMITS its memento: the sealed wire projection -- file,
        # span, and the content address of the exact source text it covers
        # (the rust source oracle's blake3_512_of(body_text) convention).
        from sugar_lift_py_tests.canonicalizer import blake3_512_of
        from sugar_lift_py_tests.kit_rpc import SourceMementoDto
        from sugar_lift_py_tests.kit_rpc.source_span_dto import SourceSpanDto

        segment = None
        if self.source is not None:
            if isinstance(self.node, Block):
                statements = getattr(self.node, "body", [])
                segments = [
                    seg
                    for stmt in statements
                    if (seg := ast.get_source_segment(self.source, stmt)) is not None
                ]
                segment = "\n".join(segments) if segments else None
            else:
                segment = ast.get_source_segment(self.source, self.node)
        if segment is None:
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap
            from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus

            factory_panic_gap(
                owner="SourceFragment",
                blame=self.blame,
                observed=self.observed,
                requested="emit a source memento",
                fix="construct the fragment with its source text "
                "(a memento without a source_cid is decorative)",
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        return SourceMementoDto(
            file=self.filename,
            span=SourceSpanDto(
                start_line=self.line,
                start_col=self.col,
                end_line=self.end_line,
                end_col=getattr(self.node, "end_col_offset", 0) or 0,
            ),
            source_cid=blake3_512_of(segment.encode()),
        )

    def fragments(self) -> List["SourceFragment"]:
        """The immediate child fragments, in source order. A `list[stmt]` suite (a
        `body`/`orelse`) becomes ONE Block fragment (it composes its own statements);
        every other AST child is its own fragment."""
        node = self.node
        if isinstance(node, Block):
            return [SourceFragment.from_node(stmt, self.filename, source=self.source) for stmt in node.body]
        children: List[SourceFragment] = []
        for _field, value in ast.iter_fields(node):
            if _is_suite(value):
                children.append(
                    SourceFragment.from_node(Block.of(value), self.filename, source=self.source)
                )
            elif isinstance(value, ast.AST):
                children.append(SourceFragment.from_node(value, self.filename, source=self.source))
            elif isinstance(value, list):
                children.extend(
                    SourceFragment.from_node(item, self.filename, source=self.source)
                    for item in value
                    if isinstance(item, ast.AST)
                )
        return children

    def statements(self) -> List["SourceFragment"]:
        """This fragment as a series of source statements -- the statement children
        (a body's lines). A statement composes at the STATEMENT role."""
        return [
            child
            for child in self.fragments()
            if isinstance(child.node, (ast.stmt, Block))
        ]

    def terms(self) -> List["SourceFragment"]:
        """This (statement or term) fragment as a series of terms -- its expression
        children. A term composes at the TERM role."""
        return [child for child in self.fragments() if isinstance(child.node, ast.expr)]

    @property
    def observed(self) -> str:
        if isinstance(self.node, ast.Constant) and isinstance(
            self.node.value,
            (int, float, str, bool, type(None)),
        ):
            # float IS a primitive literal: the numeric type is COLLAPSED -- Int embeds in
            # Real losslessly (3 and 3.0 are the same number), so 3.0 == 3 is reflexively
            # true and there is no Int/Real split at the value level (the SMT sort is an
            # emission-time inference: stay Int unless you meet a Real, then ride up).
            return "PrimitiveLiteral"
        return type(self.node).__name__

    @property
    def blame(self) -> str:
        return f"{self.filename}:{self.line}:{self.col}"

    @property
    def suggested_sugar_module(self) -> str:
        if self.observed == "PrimitiveLiteral":
            return "sugar_lift_py_tests.sugar.primitive_literal_sugar"
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", self.observed).lower()
        return f"sugar_lift_py_tests.sugar.{name}.{name}_sugar"

    # ------------------------------------------------------------------
    # Typed decomposition accessors -- each raises if the node kind is wrong.
    # ast is intentionally contained here; callers never import ast directly.
    # ------------------------------------------------------------------

    def _require(self, *kinds):
        """Raise a clear error if self.node is not one of the given ast types."""
        if not isinstance(self.node, kinds):
            expected = "/".join(k.__name__ for k in kinds)
            raise TypeError(
                f"SourceFragment accessor requires {expected}, got {type(self.node).__name__}"
                f" at {self.blame}"
            )

    def name_id(self) -> str:
        """Return the identifier string for a Name node."""
        self._require(ast.Name)
        return self.node.id  # type: ignore[attr-defined]

    def literal_value(self):
        """Return the Python value (int|str|bool|None) for a Constant/PrimitiveLiteral node."""
        self._require(ast.Constant)
        return self.node.value  # type: ignore[attr-defined]

    def attr_name(self) -> str:
        """Return the attribute string for an Attribute node."""
        self._require(ast.Attribute)
        return self.node.attr  # type: ignore[attr-defined]

    def call_is_method_call(self) -> bool:
        """Return True if the Call's func is an Attribute (i.e. a method call)."""
        self._require(ast.Call)
        return isinstance(self.node.func, ast.Attribute)  # type: ignore[attr-defined]

    def call_receiver(self) -> "SourceFragment | None":
        """Return a SourceFragment for the Attribute.value receiver, or None if not a method call."""
        self._require(ast.Call)
        if isinstance(self.node.func, ast.Attribute):  # type: ignore[attr-defined]
            return SourceFragment.from_node(self.node.func.value, self.filename, source=self.source)  # type: ignore[attr-defined]
        return None

    def call_target_name(self) -> "str | None":
        """Return func.id (plain call) or func.attr (method call), else None."""
        self._require(ast.Call)
        func = self.node.func  # type: ignore[attr-defined]
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    def call_qualified_target_name(self) -> "str | None":
        """Return the dotted call target as written, e.g. ``np.testing.equal``.

        This is syntax, not import resolution: aliases are intentionally not expanded here.
        """
        self._require(ast.Call)
        return _dotted_expr_name(self.node.func)  # type: ignore[attr-defined]

    def call_import_target_name(
        self,
        import_aliases: "dict[str, str]",
        from_imports: "dict[str, tuple[str, str]]",
    ) -> "str | None":
        """Return the canonical imported target, if this call is import-bound.

        ``import numpy as np; np.dtype(...)`` becomes ``numpy.dtype`` and
        ``from math import sqrt; sqrt(...)`` becomes ``math.sqrt``. Local calls
        with no import binding return None.
        """
        target = self.call_qualified_target_name()
        if target is None:
            return None
        if "." in target:
            head, rest = target.split(".", 1)
            module = import_aliases.get(head)
            if module is not None:
                return f"{module}.{rest}"
        imported = from_imports.get(target)
        if imported is not None:
            module, attr = imported
            return f"{module}.{attr}"
        return None

    def call_args(self) -> "list[SourceFragment]":
        """Return SourceFragments for each positional argument of the Call."""
        self._require(ast.Call)
        return [SourceFragment.from_node(a, self.filename, source=self.source) for a in self.node.args]  # type: ignore[attr-defined]

    def set_elts(self) -> "list[SourceFragment]":
        """Return SourceFragments for each element of a Set literal (ast.Set.elts)."""
        self._require(ast.Set)
        return [SourceFragment.from_node(e, self.filename, source=self.source) for e in self.node.elts]  # type: ignore[attr-defined]

    def list_elts(self) -> "list[SourceFragment]":
        """Return SourceFragments for each element of a List literal (ast.List.elts)."""
        self._require(ast.List)
        return [SourceFragment.from_node(e, self.filename, source=self.source) for e in self.node.elts]  # type: ignore[attr-defined]

    def tuple_elts(self) -> "list[SourceFragment]":
        """Return SourceFragments for each element of a Tuple literal (ast.Tuple.elts)."""
        self._require(ast.Tuple)
        return [SourceFragment.from_node(e, self.filename, source=self.source) for e in self.node.elts]  # type: ignore[attr-defined]

    def call_arg_count(self) -> int:
        """Return the number of positional arguments."""
        self._require(ast.Call)
        return len(self.node.args)  # type: ignore[attr-defined]

    def call_has_keywords(self) -> bool:
        """Return True if the Call has any keyword arguments."""
        self._require(ast.Call)
        return bool(self.node.keywords)  # type: ignore[attr-defined]

    def operator_kind(self) -> str:
        """Return the operator class name for BinOp or UnaryOp (e.g. 'Add', 'Not')."""
        self._require(ast.BinOp, ast.UnaryOp)
        return type(self.node.op).__name__  # type: ignore[attr-defined]

    def binop_left(self) -> "SourceFragment":
        """Return a SourceFragment for the left operand of a BinOp."""
        self._require(ast.BinOp)
        return SourceFragment.from_node(self.node.left, self.filename, source=self.source)  # type: ignore[attr-defined]

    def binop_right(self) -> "SourceFragment":
        """Return a SourceFragment for the right operand of a BinOp."""
        self._require(ast.BinOp)
        return SourceFragment.from_node(self.node.right, self.filename, source=self.source)  # type: ignore[attr-defined]

    def subscript_receiver(self) -> "SourceFragment":
        """Return a SourceFragment for the Subscript.value (the container)."""
        self._require(ast.Subscript)
        return SourceFragment.from_node(self.node.value, self.filename, source=self.source)  # type: ignore[attr-defined]

    def subscript_index(self) -> "SourceFragment":
        """Return a SourceFragment for the Subscript index, unwrapping legacy ast.Index."""
        self._require(ast.Subscript)
        idx = self.node.slice  # type: ignore[attr-defined]
        # Python < 3.9 wraps the slice in ast.Index
        if hasattr(ast, "Index") and isinstance(idx, ast.Index):
            idx = idx.value  # type: ignore[attr-defined]
        return SourceFragment.from_node(idx, self.filename, source=self.source)

    def slice_lower(self) -> "SourceFragment | None":
        """Return a SourceFragment for a Slice lower bound, or None for an omitted bound."""
        self._require(ast.Slice)
        lower = self.node.lower  # type: ignore[attr-defined]
        return None if lower is None else SourceFragment.from_node(lower, self.filename, source=self.source)

    def slice_upper(self) -> "SourceFragment | None":
        """Return a SourceFragment for a Slice upper bound, or None for an omitted bound."""
        self._require(ast.Slice)
        upper = self.node.upper  # type: ignore[attr-defined]
        return None if upper is None else SourceFragment.from_node(upper, self.filename, source=self.source)

    def slice_step(self) -> "SourceFragment | None":
        """Return a SourceFragment for a Slice step bound, or None for an omitted bound."""
        self._require(ast.Slice)
        step = self.node.step  # type: ignore[attr-defined]
        return None if step is None else SourceFragment.from_node(step, self.filename, source=self.source)

    def lambda_body(self) -> "SourceFragment":
        """Return a SourceFragment for the body expression of a Lambda."""
        self._require(ast.Lambda)
        return SourceFragment.from_node(self.node.body, self.filename, source=self.source)  # type: ignore[attr-defined]

    def lambda_params(self) -> "list[str]":
        """Return the argument names for a Lambda node."""
        self._require(ast.Lambda)
        return [a.arg for a in self.node.args.args]  # type: ignore[attr-defined]

    def return_value(self) -> "SourceFragment | None":
        """Return a SourceFragment for the Return value, or None if bare return."""
        self._require(ast.Return)
        if self.node.value is None:  # type: ignore[attr-defined]
            return None
        return SourceFragment.from_node(self.node.value, self.filename, source=self.source)  # type: ignore[attr-defined]

    def assign_target_name(self) -> "str | None":
        """Return the target name id for a single-Name Assign target, else None."""
        self._require(ast.Assign)
        targets = self.node.targets  # type: ignore[attr-defined]
        if len(targets) == 1 and isinstance(targets[0], ast.Name):
            return targets[0].id
        return None

    def assign_targets(self) -> "list[SourceFragment]":
        """Return SourceFragments for each assignment target."""
        self._require(ast.Assign)
        return [
            SourceFragment.from_node(target, self.filename, source=self.source)
            for target in self.node.targets  # type: ignore[attr-defined]
        ]

    def assign_target_attribute_receiver_name(self) -> "str | None":
        """Return the receiver name for ``receiver.field = value``, else None."""
        self._require(ast.Assign)
        targets = self.node.targets  # type: ignore[attr-defined]
        if (
            len(targets) == 1
            and isinstance(targets[0], ast.Attribute)
            and isinstance(targets[0].value, ast.Name)
        ):
            return targets[0].value.id
        return None

    def assign_target_attribute_name(self) -> "str | None":
        """Return the field name for ``receiver.field = value``, else None."""
        self._require(ast.Assign)
        targets = self.node.targets  # type: ignore[attr-defined]
        if len(targets) == 1 and isinstance(targets[0], ast.Attribute):
            return targets[0].attr
        return None

    def assign_value(self) -> "SourceFragment":
        """Return a SourceFragment for Assign.value."""
        self._require(ast.Assign)
        return SourceFragment.from_node(self.node.value, self.filename, source=self.source)  # type: ignore[attr-defined]

    def delete_targets(self) -> "list[SourceFragment]":
        """Return SourceFragments for each delete target."""
        self._require(ast.Delete)
        return [
            SourceFragment.from_node(target, self.filename, source=self.source)
            for target in self.node.targets  # type: ignore[attr-defined]
        ]

    def if_test(self) -> "SourceFragment":
        """Return a SourceFragment for the If test expression."""
        self._require(ast.If)
        return SourceFragment.from_node(self.node.test, self.filename, source=self.source)  # type: ignore[attr-defined]

    def if_body(self) -> "list[SourceFragment]":
        """Return SourceFragments for the statements in the If body."""
        self._require(ast.If)
        return [SourceFragment.from_node(s, self.filename, source=self.source) for s in self.node.body]  # type: ignore[attr-defined]

    def if_orelse(self) -> "list[SourceFragment]":
        """Return SourceFragments for the statements in the If orelse (else branch)."""
        self._require(ast.If)
        return [SourceFragment.from_node(s, self.filename, source=self.source) for s in self.node.orelse]  # type: ignore[attr-defined]

    def ifexp_test(self) -> "SourceFragment":
        """Return the condition expression of an IfExp."""
        self._require(ast.IfExp)
        return SourceFragment.from_node(self.node.test, self.filename, source=self.source)  # type: ignore[attr-defined]

    def ifexp_body(self) -> "SourceFragment":
        """Return the true-branch expression of an IfExp."""
        self._require(ast.IfExp)
        return SourceFragment.from_node(self.node.body, self.filename, source=self.source)  # type: ignore[attr-defined]

    def ifexp_orelse(self) -> "SourceFragment":
        """Return the false-branch expression of an IfExp."""
        self._require(ast.IfExp)
        return SourceFragment.from_node(self.node.orelse, self.filename, source=self.source)  # type: ignore[attr-defined]

    def try_body(self) -> "SourceFragment":
        """Return a Block SourceFragment for the Try body suite."""
        from .block import Block

        self._require(ast.Try, ast.TryStar)
        body = self.node.body  # type: ignore[attr-defined]
        return SourceFragment.from_node(Block.of(body), self.filename, source=self.source)

    def try_handlers(self) -> "list[SourceFragment]":
        """Return SourceFragments for the Try except handlers."""
        self._require(ast.Try, ast.TryStar)
        return [SourceFragment.from_node(h, self.filename, source=self.source) for h in self.node.handlers]  # type: ignore[attr-defined]

    def try_orelse(self) -> "SourceFragment | None":
        """Return a Block SourceFragment for the Try else suite, if present."""
        from .block import Block

        self._require(ast.Try, ast.TryStar)
        if not self.node.orelse:  # type: ignore[attr-defined]
            return None
        return SourceFragment.from_node(Block.of(self.node.orelse), self.filename, source=self.source)  # type: ignore[attr-defined]

    def try_finalbody(self) -> "SourceFragment | None":
        """Return a Block SourceFragment for the Try finally suite, if present."""
        from .block import Block

        self._require(ast.Try, ast.TryStar)
        if not self.node.finalbody:  # type: ignore[attr-defined]
            return None
        return SourceFragment.from_node(Block.of(self.node.finalbody), self.filename, source=self.source)  # type: ignore[attr-defined]

    def except_handler_body(self) -> "SourceFragment":
        """Return a Block SourceFragment for an ExceptHandler body suite."""
        from .block import Block

        self._require(ast.ExceptHandler)
        body = self.node.body  # type: ignore[attr-defined]
        return SourceFragment.from_node(Block.of(body), self.filename, source=self.source)

    def except_handler_type_names(self) -> "tuple[str, ...] | None":
        """Return handler exception names, or None for a bare except."""
        self._require(ast.ExceptHandler)
        typ = self.node.type  # type: ignore[attr-defined]
        if typ is None:
            return None
        if isinstance(typ, ast.Tuple):
            return tuple(
                name
                for item in typ.elts
                if (name := _dotted_expr_name(item)) is not None
            )
        name = _dotted_expr_name(typ)
        if name is None:
            return ()
        return (name,)

    def except_handler_name(self) -> "str | None":
        """Return the bound exception name in `except X as name`, if any."""
        self._require(ast.ExceptHandler)
        return self.node.name  # type: ignore[attr-defined]

    def function_params(self) -> "list[str]":
        """Return the argument names for a FunctionDef or AsyncFunctionDef."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        return [a.arg for a in self.node.args.args]  # type: ignore[attr-defined]

    def function_positional_arity(self) -> "tuple[int, int]":
        """Return ``(min_args, max_args)`` for positional parameters (with defaults).

        ``want_bytes(s, encoding="utf-8", errors="strict")`` is arity (1, 3) so a
        callsite ``want_bytes(string)`` bridges instead of FactoryGap on param count.
        """
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        args = self.node.args  # type: ignore[attr-defined]
        positional = [*args.posonlyargs, *args.args]
        max_args = len(positional)
        min_args = max_args - len(args.defaults)
        return min_args, max_args

    def function_body(self) -> "list[SourceFragment]":
        """Return SourceFragments for the statements in a FunctionDef body."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        return [SourceFragment.from_node(s, self.filename, source=self.source) for s in self.node.body]  # type: ignore[attr-defined]

    def function_body_block(self) -> "SourceFragment":
        """Return the FunctionDef body as the factory's Block gateway node."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        return SourceFragment.from_node(Block.of(self.node.body), self.filename, source=self.source)  # type: ignore[attr-defined]

    def compare_ops(self) -> "list[str]":
        """Return the operator class names for a Compare node (e.g. ['Eq', 'Lt'])."""
        self._require(ast.Compare)
        return [type(op).__name__ for op in self.node.ops]  # type: ignore[attr-defined]

    def compare_left(self) -> "SourceFragment":
        """Return a SourceFragment for the left operand of a Compare."""
        self._require(ast.Compare)
        return SourceFragment.from_node(self.node.left, self.filename, source=self.source)  # type: ignore[attr-defined]

    def compare_comparators(self) -> "list[SourceFragment]":
        """Return SourceFragments for each comparator on the right side of a Compare."""
        self._require(ast.Compare)
        return [SourceFragment.from_node(c, self.filename, source=self.source) for c in self.node.comparators]  # type: ignore[attr-defined]

    def function_name(self) -> str:
        """Return the name string for a FunctionDef or AsyncFunctionDef node."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        return self.node.name  # type: ignore[attr-defined]

    def function_arg_annotations(
        self,
    ) -> "list[tuple[str, SourceFragment | None, int]]":
        """Return argument names, annotation fragments, and source lines."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        args = self.node.args  # type: ignore[attr-defined]
        all_args = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        return [
            (
                arg.arg,
                (
                    SourceFragment.from_node(arg.annotation, self.filename, source=self.source)
                    if arg.annotation is not None
                    else None
                ),
                getattr(arg, "lineno", self.line),
            )
            for arg in all_args
        ]

    def function_node(self) -> "ast.FunctionDef | ast.AsyncFunctionDef":
        """Return the underlying function node after checking its kind."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        return cast(ast.FunctionDef | ast.AsyncFunctionDef, self.node)

    def stmt_node(self) -> ast.stmt:
        """Return the underlying statement node after checking its kind."""
        if not isinstance(self.node, ast.stmt):
            raise TypeError(
                f"SourceFragment statement node required, got {type(self.node).__name__}"
                f" at {self.blame}"
            )
        return self.node

    def class_name(self) -> str:
        """Return the name string for a ClassDef node."""
        self._require(ast.ClassDef)
        return self.node.name  # type: ignore[attr-defined]

    def class_body(self) -> "list[SourceFragment]":
        """Return SourceFragments for the statements in a ClassDef body."""
        self._require(ast.ClassDef)
        return [SourceFragment.from_node(s, self.filename, source=self.source) for s in self.node.body]  # type: ignore[attr-defined]

    def class_base_names(self) -> tuple[str | None, ...]:
        """Return dotted base names for a ClassDef; None means dynamic/unnamed base."""
        self._require(ast.ClassDef)
        node = cast(ast.ClassDef, self.node)
        return tuple(_dotted_expr_name(base) for base in node.bases)

    # ------------------------------------------------------------------
    # Additional accessors added in numpy-import-sugar sweep
    # ------------------------------------------------------------------

    @classmethod
    def from_source(cls, source: str, filename: str) -> "SourceFragment":
        """Parse Python source and return the root Module SourceFragment.

        Wraps ast.parse() internally; callers never need to import ast.
        """
        tree = ast.parse(source, filename=filename)
        return cls.from_node(tree, filename, source=source)

    def has_position(self) -> bool:
        """Return True if this node has line and column position attributes."""
        return hasattr(self.node, "lineno") and hasattr(self.node, "col_offset")

    def is_statement_site(self) -> bool:
        """Return True when the fragment is a statement/suite dispatch site."""
        return isinstance(self.node, (ast.stmt, Block))

    @property
    def end_line(self) -> int:
        """The end line number of this node, or lineno if end_lineno is absent."""
        return getattr(self.node, "end_lineno", None) or getattr(self.node, "lineno", 0)

    @property
    def end_col(self) -> int:
        """The end column offset of this node, or 0 if end_col_offset is absent."""
        return getattr(self.node, "end_col_offset", None) or 0

    def source_text(self, source: str) -> "str | None":
        """Return the source substring for this node, or None if position is missing.

        Wraps ast.get_source_segment() so callers never import ast.
        """
        return ast.get_source_segment(source, self.node)

    def walk(self) -> "list[SourceFragment]":
        """Return all descendant fragments in depth-first pre-order.

        Replaces ast.walk() for callers that must not import ast.
        """
        result: list[SourceFragment] = []
        for child in self.fragments():
            result.append(child)
            result.extend(child.walk())
        return result

    def is_node_type(self, *kinds) -> bool:
        """Return True if this node is an instance of any of the given ast types.

        Replaces isinstance(node, ast.X) checks in factory and report code.
        Example: ``frag.is_node_type(ast.Lambda, ast.FunctionDef)``
        """
        return isinstance(self.node, kinds)

    # --- assert / expr-statement ------------------------------------------

    def assert_test(self) -> "SourceFragment":
        """Return a SourceFragment for the test expression of an Assert node."""
        self._require(ast.Assert)
        return SourceFragment.from_node(self.node.test, self.filename, source=self.source)  # type: ignore[attr-defined]

    def assert_has_message(self) -> bool:
        """Return True when an Assert node carries an assertion message."""
        self._require(ast.Assert)
        return self.node.msg is not None  # type: ignore[attr-defined]

    def assert_with_test(self, test: "SourceFragment") -> "SourceFragment":
        """Return this Assert as a new Assert fragment with a different test.

        This is the SourceFragment-only way to view `assert not <expr>` as
        `assert <expr>` for child assertion construction. Callers never import
        or assemble raw ast directly.
        """
        self._require(ast.Assert)
        if not isinstance(test.node, ast.expr):
            raise TypeError(
                f"SourceFragment assert test requires expr, got {type(test.node).__name__}"
                f" at {test.blame}"
            )
        node = ast.Assert(test=test.node, msg=None)
        ast.copy_location(node, self.node)
        ast.fix_missing_locations(node)
        return SourceFragment.from_node(node, self.filename, source=self.source)

    def expr_value(self) -> "SourceFragment":
        """Return a SourceFragment for the expression inside an Expr statement node."""
        self._require(ast.Expr)
        return SourceFragment.from_node(self.node.value, self.filename, source=self.source)  # type: ignore[attr-defined]

    # --- unary / bool ops -------------------------------------------------

    def unaryop_operand(self) -> "SourceFragment":
        """Return a SourceFragment for the operand of a UnaryOp node."""
        self._require(ast.UnaryOp)
        return SourceFragment.from_node(self.node.operand, self.filename, source=self.source)  # type: ignore[attr-defined]

    def boolop_op_kind(self) -> str:
        """Return 'and' or 'or' for a BoolOp node."""
        self._require(ast.BoolOp)
        return "and" if isinstance(self.node.op, ast.And) else "or"  # type: ignore[attr-defined]

    def boolop_values(self) -> "list[SourceFragment]":
        """Return the operand SourceFragments for a BoolOp node (ast.BoolOp.values)."""
        self._require(ast.BoolOp)
        return [SourceFragment.from_node(v, self.filename, source=self.source) for v in self.node.values]  # type: ignore[attr-defined]

    def dict_entries(self) -> "list[tuple[SourceFragment | None, SourceFragment]]":
        """Return key/value fragments for a Dict expression.

        A ``None`` key is Python's ``**mapping`` spread form; callers decide whether
        that shape belongs in their term vocabulary or should emit a typed effect.
        """
        self._require(ast.Dict)
        return [
            (
                None if key is None else SourceFragment.from_node(key, self.filename, source=self.source),
                SourceFragment.from_node(value, self.filename, source=self.source),
            )
            for key, value in zip(self.node.keys, self.node.values)  # type: ignore[attr-defined]
        ]

    # --- attribute --------------------------------------------------------

    def attr_receiver(self) -> "SourceFragment":
        """Return a SourceFragment for the receiver of an Attribute node (Attribute.value)."""
        self._require(ast.Attribute)
        return SourceFragment.from_node(self.node.value, self.filename, source=self.source)  # type: ignore[attr-defined]

    # --- call / keyword ---------------------------------------------------

    def call_func(self) -> "SourceFragment":
        """Return a SourceFragment for the full func expression of a Call node.

        Unlike call_receiver(), this always returns the func node regardless of
        whether it is a Name or an Attribute.
        """
        self._require(ast.Call)
        return SourceFragment.from_node(self.node.func, self.filename, source=self.source)  # type: ignore[attr-defined]

    def call_keywords(self) -> "list[SourceFragment]":
        """Return SourceFragments wrapping each ast.keyword of the Call."""
        self._require(ast.Call)
        return [SourceFragment.from_node(kw, self.filename, source=self.source) for kw in self.node.keywords]  # type: ignore[attr-defined]

    def keyword_arg_name(self) -> "str | None":
        """Return the keyword argument name string, or None for **kwargs expansion."""
        self._require(ast.keyword)
        return self.node.arg  # type: ignore[attr-defined]

    def keyword_value(self) -> "SourceFragment":
        """Return a SourceFragment for the value expression of a keyword argument."""
        self._require(ast.keyword)
        return SourceFragment.from_node(self.node.value, self.filename, source=self.source)  # type: ignore[attr-defined]

    # --- formatted string literals ----------------------------------------

    def joined_str_values(self) -> "list[SourceFragment]":
        """Return the literal/formatted child fragments of an f-string."""
        self._require(ast.JoinedStr)
        return [
            SourceFragment.from_node(value, self.filename, source=self.source)
            for value in self.node.values  # type: ignore[attr-defined]
        ]

    def joined_str_static_text(self) -> "str | None":
        """Return the f-string text when every segment is already literal text."""
        self._require(ast.JoinedStr)
        pieces: list[str] = []
        for value in self.node.values:  # type: ignore[attr-defined]
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return None
            pieces.append(value.value)
        return "".join(pieces)

    def formatted_value_value(self) -> "SourceFragment":
        """Return the expression inside an f-string formatted field."""
        self._require(ast.FormattedValue)
        value = self.node.value  # type: ignore[attr-defined]
        return SourceFragment.from_node(value, self.filename, source=self.source)

    def formatted_value_conversion(self) -> int:
        """Return the ast.FormattedValue conversion code."""
        self._require(ast.FormattedValue)
        return self.node.conversion  # type: ignore[attr-defined]

    def formatted_value_has_format_spec(self) -> bool:
        """Return True when an f-string formatted field carries a format spec."""
        self._require(ast.FormattedValue)
        return self.node.format_spec is not None  # type: ignore[attr-defined]

    def formatted_value_format_spec_static_text(self) -> "str | None":
        """Return a literal format spec, or None for no spec or a dynamic spec."""
        self._require(ast.FormattedValue)
        spec = self.node.format_spec  # type: ignore[attr-defined]
        if spec is None:
            return None
        return SourceFragment.from_node(spec, self.filename, source=self.source).joined_str_static_text()

    # --- comprehensions ----------------------------------------------------

    def listcomp_element(self) -> "SourceFragment":
        """Return the element expression produced by a list comprehension."""
        self._require(ast.ListComp)
        return SourceFragment.from_node(self.node.elt, self.filename, source=self.source)  # type: ignore[attr-defined]

    def listcomp_generators(self) -> "list[SourceFragment]":
        """Return the comprehension clauses of a list comprehension."""
        self._require(ast.ListComp)
        return [
            SourceFragment.from_node(generator, self.filename, source=self.source)
            for generator in self.node.generators  # type: ignore[attr-defined]
        ]

    def setcomp_element(self) -> "SourceFragment":
        """Return the element expression produced by a set comprehension."""
        self._require(ast.SetComp)
        return SourceFragment.from_node(self.node.elt, self.filename, source=self.source)  # type: ignore[attr-defined]

    def setcomp_generators(self) -> "list[SourceFragment]":
        """Return the comprehension clauses of a set comprehension."""
        self._require(ast.SetComp)
        return [
            SourceFragment.from_node(generator, self.filename, source=self.source)
            for generator in self.node.generators  # type: ignore[attr-defined]
        ]

    def dictcomp_key(self) -> "SourceFragment":
        """Return the key expression produced by a dict comprehension."""
        self._require(ast.DictComp)
        return SourceFragment.from_node(self.node.key, self.filename, source=self.source)  # type: ignore[attr-defined]

    def dictcomp_value(self) -> "SourceFragment":
        """Return the value expression produced by a dict comprehension."""
        self._require(ast.DictComp)
        return SourceFragment.from_node(self.node.value, self.filename, source=self.source)  # type: ignore[attr-defined]

    def dictcomp_generators(self) -> "list[SourceFragment]":
        """Return the comprehension clauses of a dict comprehension."""
        self._require(ast.DictComp)
        return [
            SourceFragment.from_node(generator, self.filename, source=self.source)
            for generator in self.node.generators  # type: ignore[attr-defined]
        ]

    def comprehension_target(self) -> "SourceFragment":
        """Return the target bound by a comprehension clause."""
        self._require(ast.comprehension)
        return SourceFragment.from_node(self.node.target, self.filename, source=self.source)  # type: ignore[attr-defined]

    def comprehension_iter(self) -> "SourceFragment":
        """Return the iterable expression of a comprehension clause."""
        self._require(ast.comprehension)
        return SourceFragment.from_node(self.node.iter, self.filename, source=self.source)  # type: ignore[attr-defined]

    def comprehension_ifs(self) -> "list[SourceFragment]":
        """Return the guard expressions of a comprehension clause."""
        self._require(ast.comprehension)
        return [
            SourceFragment.from_node(guard, self.filename, source=self.source)
            for guard in self.node.ifs  # type: ignore[attr-defined]
        ]

    def comprehension_is_async(self) -> bool:
        """Return True when the comprehension clause is async."""
        self._require(ast.comprehension)
        return bool(self.node.is_async)  # type: ignore[attr-defined]

    # --- annotated assignment ----------------------------------------------

    def annassign_target(self) -> "SourceFragment":
        """Return a SourceFragment for the target of an AnnAssign node."""
        self._require(ast.AnnAssign)
        return SourceFragment.from_node(self.node.target, self.filename, source=self.source)  # type: ignore[attr-defined]

    def annassign_annotation(self) -> "SourceFragment":
        """Return a SourceFragment for the annotation of an AnnAssign node."""
        self._require(ast.AnnAssign)
        return SourceFragment.from_node(self.node.annotation, self.filename, source=self.source)  # type: ignore[attr-defined]

    def annassign_value(self) -> "SourceFragment | None":
        """Return a SourceFragment for the optional value of an AnnAssign, or None."""
        self._require(ast.AnnAssign)
        if self.node.value is None:  # type: ignore[attr-defined]
            return None
        return SourceFragment.from_node(self.node.value, self.filename, source=self.source)  # type: ignore[attr-defined]

    def annassign_target_id(self) -> str:
        """Return the name string when an AnnAssign target is a simple Name node."""
        self._require(ast.AnnAssign)
        target = self.node.target  # type: ignore[attr-defined]
        if not isinstance(target, ast.Name):
            raise TypeError(
                f"annassign_target_id requires a Name target, got {type(target).__name__}"
                f" at {self.blame}"
            )
        return target.id

    # --- imports ----------------------------------------------------------

    def import_names(self) -> "list[tuple[str, str | None]]":
        """Return (name, asname) pairs for an Import node."""
        self._require(ast.Import)
        return [(alias.name, alias.asname) for alias in self.node.names]  # type: ignore[attr-defined]

    def importfrom_module(self) -> "str | None":
        """Return the module string for an ImportFrom node (None for bare relative imports)."""
        self._require(ast.ImportFrom)
        return self.node.module  # type: ignore[attr-defined]

    def importfrom_level(self) -> int:
        """Return the relative-import level (0 = absolute) for an ImportFrom node."""
        self._require(ast.ImportFrom)
        return self.node.level or 0  # type: ignore[attr-defined]

    def importfrom_names(self) -> "list[tuple[str, str | None]]":
        """Return (name, asname) pairs for an ImportFrom node."""
        self._require(ast.ImportFrom)
        return [(alias.name, alias.asname) for alias in self.node.names]  # type: ignore[attr-defined]

    def alias_name(self) -> str:
        """Return the imported name for an alias node."""
        self._require(ast.alias)
        return self.node.name  # type: ignore[attr-defined]

    def alias_bound_name(self) -> str:
        """Return the local binding name for an alias node."""
        self._require(ast.alias)
        return self.node.asname or self.node.name  # type: ignore[attr-defined]

    # --- function decorators ----------------------------------------------

    def function_decorators(self) -> "list[SourceFragment]":
        """Return SourceFragments for the decorators of a FunctionDef/AsyncFunctionDef."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        return [
            SourceFragment.from_node(d, self.filename, source=self.source)
            for d in self.node.decorator_list  # type: ignore[attr-defined]
        ]

    # --- augmented assignment ----------------------------------------------

    def aug_assign_target(self) -> "SourceFragment":
        """Return a SourceFragment for the target of an AugAssign node."""
        self._require(ast.AugAssign)
        return SourceFragment.from_node(self.node.target, self.filename, source=self.source)  # type: ignore[attr-defined]

    def aug_assign_value(self) -> "SourceFragment":
        """Return a SourceFragment for the value expression of an AugAssign node."""
        self._require(ast.AugAssign)
        return SourceFragment.from_node(self.node.value, self.filename, source=self.source)  # type: ignore[attr-defined]

    def aug_assign_op(self) -> str:
        """Return the operator class name for an AugAssign node (e.g. 'Add', 'Sub')."""
        self._require(ast.AugAssign)
        return type(self.node.op).__name__  # type: ignore[attr-defined]

    def aug_assign_binop(self) -> "SourceFragment":
        """Synthesize the BinOp `target <op> value` that `target <op>= value` unrolls to.

        This is the temporal rewrite that lets AugAssign become a plain assign: the
        operator then dispatches to its OWN binop sugar downstream (Add -> BinOpSugar),
        or the factory panics naming the missing one (Sub/Mult, until those exist). The
        gateway is the only place ast may be constructed.
        """
        self._require(ast.AugAssign)
        binop = ast.BinOp(
            left=self.node.target,  # type: ignore[attr-defined]
            op=self.node.op,  # type: ignore[attr-defined]
            right=self.node.value,  # type: ignore[attr-defined]
        )
        ast.copy_location(binop, self.node)
        ast.fix_missing_locations(binop)
        return SourceFragment.from_node(binop, self.filename, source=self.source)

    # --- raise ------------------------------------------------------------

    def raise_exc(self) -> "SourceFragment | None":
        """Return a SourceFragment for the exception of a Raise node, or None."""
        self._require(ast.Raise)
        if self.node.exc is None:  # type: ignore[attr-defined]
            return None
        return SourceFragment.from_node(self.node.exc, self.filename, source=self.source)  # type: ignore[attr-defined]

    # --- context managers -------------------------------------------------

    def with_item_count(self) -> int:
        """Return the number of context-manager items in a With/AsyncWith node."""
        self._require(ast.With, ast.AsyncWith)
        return len(self.node.items)  # type: ignore[attr-defined]

    def with_context_expr(self, index: int = 0) -> "SourceFragment":
        """Return the context expression for a With/AsyncWith item."""
        self._require(ast.With, ast.AsyncWith)
        item = self.node.items[index]  # type: ignore[attr-defined]
        return SourceFragment.from_node(item.context_expr, self.filename, source=self.source)

    def with_optional_vars_name(self, index: int = 0) -> "str | None":
        """Return the simple `as name` binding for a With/AsyncWith item, if any."""
        self._require(ast.With, ast.AsyncWith)
        target = self.node.items[index].optional_vars  # type: ignore[attr-defined]
        if target is None:
            return None
        if isinstance(target, ast.Name):
            return target.id
        return None

    def with_optional_vars_observed(self, index: int = 0) -> "str | None":
        """Return the optional-vars AST kind for With/AsyncWith, if present."""
        self._require(ast.With, ast.AsyncWith)
        target = self.node.items[index].optional_vars  # type: ignore[attr-defined]
        if target is None:
            return None
        return type(target).__name__

    def with_body(self) -> "SourceFragment":
        """Return a Block SourceFragment for a With/AsyncWith body suite."""
        from .block import Block

        self._require(ast.With, ast.AsyncWith)
        body = self.node.body  # type: ignore[attr-defined]
        return SourceFragment.from_node(Block.of(body), self.filename, source=self.source)

    # --- await ------------------------------------------------------------

    def await_value(self) -> "SourceFragment":
        """Return the awaited expression for an Await node."""
        self._require(ast.Await)
        return SourceFragment.from_node(self.node.value, self.filename, source=self.source)  # type: ignore[attr-defined]

    # --- for loops --------------------------------------------------------

    def for_iter(self) -> "SourceFragment":
        """Return the iterable expression for a For/AsyncFor node."""
        self._require(ast.For, ast.AsyncFor)
        return SourceFragment.from_node(self.node.iter, self.filename, source=self.source)  # type: ignore[attr-defined]

    def for_target_name(self) -> "str | None":
        """Return the simple target name for a For/AsyncFor node, if any."""
        self._require(ast.For, ast.AsyncFor)
        target = self.node.target  # type: ignore[attr-defined]
        if isinstance(target, ast.Name):
            return target.id
        return None

    def for_target_observed(self) -> str:
        """Return the AST kind for a For/AsyncFor target."""
        self._require(ast.For, ast.AsyncFor)
        return type(self.node.target).__name__  # type: ignore[attr-defined]

    def for_body(self) -> "list[SourceFragment]":
        """Return SourceFragments for the body statements of a For or AsyncFor node."""
        self._require(ast.For, ast.AsyncFor)
        return [SourceFragment.from_node(s, self.filename, source=self.source) for s in self.node.body]  # type: ignore[attr-defined]

    def for_body_block(self) -> "SourceFragment":
        """Return a Block SourceFragment for a For/AsyncFor body suite."""
        from .block import Block

        self._require(ast.For, ast.AsyncFor)
        body = self.node.body  # type: ignore[attr-defined]
        return SourceFragment.from_node(Block.of(body), self.filename, source=self.source)

    def for_orelse_count(self) -> int:
        """Return the number of else statements on a For/AsyncFor node."""
        self._require(ast.For, ast.AsyncFor)
        return len(self.node.orelse)  # type: ignore[attr-defined]

    # --- while loops ------------------------------------------------------

    def while_test(self) -> "SourceFragment":
        """Return the condition expression for a While node."""
        self._require(ast.While)
        return SourceFragment.from_node(self.node.test, self.filename, source=self.source)  # type: ignore[attr-defined]

    def while_body_block(self) -> "SourceFragment":
        """Return a Block SourceFragment for a While body suite."""
        from .block import Block

        self._require(ast.While)
        body = self.node.body  # type: ignore[attr-defined]
        return SourceFragment.from_node(Block.of(body), self.filename, source=self.source)

    def while_orelse_count(self) -> int:
        """Return the number of else statements on a While node."""
        self._require(ast.While)
        return len(self.node.orelse)  # type: ignore[attr-defined]

    def unparse(self) -> str:
        """Return a canonical source-text representation of this node (via ast.unparse).

        Replaces bare ast.unparse(node) calls so callers never import ast.
        """
        return ast.unparse(self.node)


# ---------------------------------------------------------------------------
# Module-level grammar introspection helpers.
# These let callers enumerate ast grammar classes without importing ast.
# ---------------------------------------------------------------------------


def grammar_stmt_classes() -> frozenset:
    """Return the frozenset of all concrete ast.stmt subclasses on this interpreter."""
    return frozenset(
        cls
        for name in dir(ast)
        if isinstance(cls := getattr(ast, name), type)
        and issubclass(cls, ast.stmt)
        and cls is not ast.stmt
    )


def grammar_expr_classes() -> frozenset:
    """Return the frozenset of all concrete ast.expr subclasses on this interpreter."""
    return frozenset(
        cls
        for name in dir(ast)
        if isinstance(cls := getattr(ast, name), type)
        and issubclass(cls, ast.expr)
        and cls is not ast.expr
    )
