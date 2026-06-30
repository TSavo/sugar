from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import List


def _is_suite(value) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, ast.stmt) for item in value
    )


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

    @classmethod
    def from_node(cls, node: ast.AST, filename: str) -> "SourceFragment":
        # A container node (Module) has no position; it is never a site itself, only a
        # source of fragments, so default its position rather than refuse to wrap it.
        return cls(
            node=node,
            filename=filename,
            line=getattr(node, "lineno", 0),
            col=getattr(node, "col_offset", 0),
        )

    def fragments(self) -> List["SourceFragment"]:
        """The immediate child fragments, in source order. A `list[stmt]` suite (a
        `body`/`orelse`) becomes ONE Block fragment (it composes its own statements);
        every other AST child is its own fragment."""
        from .block import Block

        node = self.node
        if isinstance(node, Block):
            return [SourceFragment.from_node(stmt, self.filename) for stmt in node.body]
        children: List[SourceFragment] = []
        for _field, value in ast.iter_fields(node):
            if _is_suite(value):
                children.append(SourceFragment.from_node(Block.of(value), self.filename))
            elif isinstance(value, ast.AST):
                children.append(SourceFragment.from_node(value, self.filename))
            elif isinstance(value, list):
                children.extend(
                    SourceFragment.from_node(item, self.filename)
                    for item in value
                    if isinstance(item, ast.AST)
                )
        return children

    def statements(self) -> List["SourceFragment"]:
        """This fragment as a series of source statements -- the statement children
        (a body's lines). A statement composes at the STATEMENT role."""
        from .block import Block

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
            return SourceFragment.from_node(self.node.func.value, self.filename)  # type: ignore[attr-defined]
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

    def call_args(self) -> "list[SourceFragment]":
        """Return SourceFragments for each positional argument of the Call."""
        self._require(ast.Call)
        return [SourceFragment.from_node(a, self.filename) for a in self.node.args]  # type: ignore[attr-defined]

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
        return SourceFragment.from_node(self.node.left, self.filename)  # type: ignore[attr-defined]

    def binop_right(self) -> "SourceFragment":
        """Return a SourceFragment for the right operand of a BinOp."""
        self._require(ast.BinOp)
        return SourceFragment.from_node(self.node.right, self.filename)  # type: ignore[attr-defined]

    def subscript_receiver(self) -> "SourceFragment":
        """Return a SourceFragment for the Subscript.value (the container)."""
        self._require(ast.Subscript)
        return SourceFragment.from_node(self.node.value, self.filename)  # type: ignore[attr-defined]

    def subscript_index(self) -> "SourceFragment":
        """Return a SourceFragment for the Subscript index, unwrapping legacy ast.Index."""
        self._require(ast.Subscript)
        idx = self.node.slice  # type: ignore[attr-defined]
        # Python < 3.9 wraps the slice in ast.Index
        if hasattr(ast, "Index") and isinstance(idx, ast.Index):
            idx = idx.value  # type: ignore[attr-defined]
        return SourceFragment.from_node(idx, self.filename)

    def lambda_body(self) -> "SourceFragment":
        """Return a SourceFragment for the body expression of a Lambda."""
        self._require(ast.Lambda)
        return SourceFragment.from_node(self.node.body, self.filename)  # type: ignore[attr-defined]

    def lambda_params(self) -> "list[str]":
        """Return the argument names for a Lambda node."""
        self._require(ast.Lambda)
        return [a.arg for a in self.node.args.args]  # type: ignore[attr-defined]

    def return_value(self) -> "SourceFragment | None":
        """Return a SourceFragment for the Return value, or None if bare return."""
        self._require(ast.Return)
        if self.node.value is None:  # type: ignore[attr-defined]
            return None
        return SourceFragment.from_node(self.node.value, self.filename)  # type: ignore[attr-defined]

    def assign_target_name(self) -> "str | None":
        """Return the target name id for a single-Name Assign target, else None."""
        self._require(ast.Assign)
        targets = self.node.targets  # type: ignore[attr-defined]
        if len(targets) == 1 and isinstance(targets[0], ast.Name):
            return targets[0].id
        return None

    def assign_value(self) -> "SourceFragment":
        """Return a SourceFragment for Assign.value."""
        self._require(ast.Assign)
        return SourceFragment.from_node(self.node.value, self.filename)  # type: ignore[attr-defined]

    def if_test(self) -> "SourceFragment":
        """Return a SourceFragment for the If test expression."""
        self._require(ast.If)
        return SourceFragment.from_node(self.node.test, self.filename)  # type: ignore[attr-defined]

    def if_body(self) -> "list[SourceFragment]":
        """Return SourceFragments for the statements in the If body."""
        self._require(ast.If)
        return [SourceFragment.from_node(s, self.filename) for s in self.node.body]  # type: ignore[attr-defined]

    def if_orelse(self) -> "list[SourceFragment]":
        """Return SourceFragments for the statements in the If orelse (else branch)."""
        self._require(ast.If)
        return [SourceFragment.from_node(s, self.filename) for s in self.node.orelse]  # type: ignore[attr-defined]

    def function_name(self) -> str:
        """Return the name string for a FunctionDef or AsyncFunctionDef."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        return self.node.name  # type: ignore[attr-defined]

    def function_params(self) -> "list[str]":
        """Return the argument names for a FunctionDef or AsyncFunctionDef."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        return [a.arg for a in self.node.args.args]  # type: ignore[attr-defined]

    def function_body(self) -> "list[SourceFragment]":
        """Return SourceFragments for the statements in a FunctionDef body."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        return [SourceFragment.from_node(s, self.filename) for s in self.node.body]  # type: ignore[attr-defined]

    def compare_ops(self) -> "list[str]":
        """Return the operator class names for a Compare node (e.g. ['Eq', 'Lt'])."""
        self._require(ast.Compare)
        return [type(op).__name__ for op in self.node.ops]  # type: ignore[attr-defined]

    def compare_left(self) -> "SourceFragment":
        """Return a SourceFragment for the left operand of a Compare."""
        self._require(ast.Compare)
        return SourceFragment.from_node(self.node.left, self.filename)  # type: ignore[attr-defined]

    def compare_comparators(self) -> "list[SourceFragment]":
        """Return SourceFragments for each comparator on the right side of a Compare."""
        self._require(ast.Compare)
        return [SourceFragment.from_node(c, self.filename) for c in self.node.comparators]  # type: ignore[attr-defined]

    def function_name(self) -> str:
        """Return the name string for a FunctionDef or AsyncFunctionDef node."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        return self.node.name  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Additional accessors added in numpy-import-sugar sweep
    # ------------------------------------------------------------------

    @classmethod
    def from_source(cls, source: str, filename: str) -> "SourceFragment":
        """Parse Python source and return the root Module SourceFragment.

        Wraps ast.parse() internally; callers never need to import ast.
        """
        tree = ast.parse(source, filename=filename)
        return cls.from_node(tree, filename)

    def has_position(self) -> bool:
        """Return True if this node has line and column position attributes."""
        return hasattr(self.node, "lineno") and hasattr(self.node, "col_offset")

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
        return SourceFragment.from_node(self.node.test, self.filename)  # type: ignore[attr-defined]

    def expr_value(self) -> "SourceFragment":
        """Return a SourceFragment for the expression inside an Expr statement node."""
        self._require(ast.Expr)
        return SourceFragment.from_node(self.node.value, self.filename)  # type: ignore[attr-defined]

    # --- unary / bool ops -------------------------------------------------

    def unaryop_operand(self) -> "SourceFragment":
        """Return a SourceFragment for the operand of a UnaryOp node."""
        self._require(ast.UnaryOp)
        return SourceFragment.from_node(self.node.operand, self.filename)  # type: ignore[attr-defined]

    def boolop_op_kind(self) -> str:
        """Return 'and' or 'or' for a BoolOp node."""
        self._require(ast.BoolOp)
        return "and" if isinstance(self.node.op, ast.And) else "or"  # type: ignore[attr-defined]

    def boolop_values(self) -> "list[SourceFragment]":
        """Return the operand SourceFragments for a BoolOp node (ast.BoolOp.values)."""
        self._require(ast.BoolOp)
        return [SourceFragment.from_node(v, self.filename) for v in self.node.values]  # type: ignore[attr-defined]

    # --- attribute --------------------------------------------------------

    def attr_receiver(self) -> "SourceFragment":
        """Return a SourceFragment for the receiver of an Attribute node (Attribute.value)."""
        self._require(ast.Attribute)
        return SourceFragment.from_node(self.node.value, self.filename)  # type: ignore[attr-defined]

    # --- call / keyword ---------------------------------------------------

    def call_func(self) -> "SourceFragment":
        """Return a SourceFragment for the full func expression of a Call node.

        Unlike call_receiver(), this always returns the func node regardless of
        whether it is a Name or an Attribute.
        """
        self._require(ast.Call)
        return SourceFragment.from_node(self.node.func, self.filename)  # type: ignore[attr-defined]

    def call_keywords(self) -> "list[SourceFragment]":
        """Return SourceFragments wrapping each ast.keyword of the Call."""
        self._require(ast.Call)
        return [SourceFragment.from_node(kw, self.filename) for kw in self.node.keywords]  # type: ignore[attr-defined]

    def keyword_arg_name(self) -> "str | None":
        """Return the keyword argument name string, or None for **kwargs expansion."""
        self._require(ast.keyword)
        return self.node.arg  # type: ignore[attr-defined]

    def keyword_value(self) -> "SourceFragment":
        """Return a SourceFragment for the value expression of a keyword argument."""
        self._require(ast.keyword)
        return SourceFragment.from_node(self.node.value, self.filename)  # type: ignore[attr-defined]

    # --- annotated assignment ----------------------------------------------

    def annassign_target(self) -> "SourceFragment":
        """Return a SourceFragment for the target of an AnnAssign node."""
        self._require(ast.AnnAssign)
        return SourceFragment.from_node(self.node.target, self.filename)  # type: ignore[attr-defined]

    def annassign_annotation(self) -> "SourceFragment":
        """Return a SourceFragment for the annotation of an AnnAssign node."""
        self._require(ast.AnnAssign)
        return SourceFragment.from_node(self.node.annotation, self.filename)  # type: ignore[attr-defined]

    def annassign_value(self) -> "SourceFragment | None":
        """Return a SourceFragment for the optional value of an AnnAssign, or None."""
        self._require(ast.AnnAssign)
        if self.node.value is None:  # type: ignore[attr-defined]
            return None
        return SourceFragment.from_node(self.node.value, self.filename)  # type: ignore[attr-defined]

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

    # --- function decorators ----------------------------------------------

    def function_decorators(self) -> "list[SourceFragment]":
        """Return SourceFragments for the decorators of a FunctionDef/AsyncFunctionDef."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        return [
            SourceFragment.from_node(d, self.filename)
            for d in self.node.decorator_list  # type: ignore[attr-defined]
        ]

    # --- augmented assignment ----------------------------------------------

    def aug_assign_target(self) -> "SourceFragment":
        """Return a SourceFragment for the target of an AugAssign node."""
        self._require(ast.AugAssign)
        return SourceFragment.from_node(self.node.target, self.filename)  # type: ignore[attr-defined]

    def aug_assign_value(self) -> "SourceFragment":
        """Return a SourceFragment for the value expression of an AugAssign node."""
        self._require(ast.AugAssign)
        return SourceFragment.from_node(self.node.value, self.filename)  # type: ignore[attr-defined]

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
        return SourceFragment.from_node(binop, self.filename)

    # --- raise ------------------------------------------------------------

    def raise_exc(self) -> "SourceFragment | None":
        """Return a SourceFragment for the exception of a Raise node, or None."""
        self._require(ast.Raise)
        if self.node.exc is None:  # type: ignore[attr-defined]
            return None
        return SourceFragment.from_node(self.node.exc, self.filename)  # type: ignore[attr-defined]

    # --- for loops --------------------------------------------------------

    def for_body(self) -> "list[SourceFragment]":
        """Return SourceFragments for the body statements of a For or AsyncFor node."""
        self._require(ast.For, ast.AsyncFor)
        return [SourceFragment.from_node(s, self.filename) for s in self.node.body]  # type: ignore[attr-defined]

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
