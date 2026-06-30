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
class SourceSite:
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
    def from_node(cls, node: ast.AST, filename: str) -> "SourceSite":
        # A container node (Module) has no position; it is never a site itself, only a
        # source of fragments, so default its position rather than refuse to wrap it.
        return cls(
            node=node,
            filename=filename,
            line=getattr(node, "lineno", 0),
            col=getattr(node, "col_offset", 0),
        )

    def fragments(self) -> List["SourceSite"]:
        """The immediate child fragments, in source order. A `list[stmt]` suite (a
        `body`/`orelse`) becomes ONE Block fragment (it composes its own statements);
        every other AST child is its own fragment."""
        from .block import Block

        node = self.node
        if isinstance(node, Block):
            return [SourceSite.from_node(stmt, self.filename) for stmt in node.body]
        children: List[SourceSite] = []
        for _field, value in ast.iter_fields(node):
            if _is_suite(value):
                children.append(SourceSite.from_node(Block.of(value), self.filename))
            elif isinstance(value, ast.AST):
                children.append(SourceSite.from_node(value, self.filename))
            elif isinstance(value, list):
                children.extend(
                    SourceSite.from_node(item, self.filename)
                    for item in value
                    if isinstance(item, ast.AST)
                )
        return children

    def statements(self) -> List["SourceSite"]:
        """This fragment as a series of source statements -- the statement children
        (a body's lines). A statement composes at the STATEMENT role."""
        from .block import Block

        return [
            child
            for child in self.fragments()
            if isinstance(child.node, (ast.stmt, Block))
        ]

    def terms(self) -> List["SourceSite"]:
        """This (statement or term) fragment as a series of terms -- its expression
        children. A term composes at the TERM role."""
        return [child for child in self.fragments() if isinstance(child.node, ast.expr)]

    @property
    def observed(self) -> str:
        if isinstance(self.node, ast.Constant) and isinstance(
            self.node.value,
            (int, str, bool, type(None)),
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
                f"SourceSite accessor requires {expected}, got {type(self.node).__name__}"
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

    def call_receiver(self) -> "SourceSite | None":
        """Return a SourceSite for the Attribute.value receiver, or None if not a method call."""
        self._require(ast.Call)
        if isinstance(self.node.func, ast.Attribute):  # type: ignore[attr-defined]
            return SourceSite.from_node(self.node.func.value, self.filename)  # type: ignore[attr-defined]
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

    def call_args(self) -> "list[SourceSite]":
        """Return SourceSites for each positional argument of the Call."""
        self._require(ast.Call)
        return [SourceSite.from_node(a, self.filename) for a in self.node.args]  # type: ignore[attr-defined]

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

    def binop_left(self) -> "SourceSite":
        """Return a SourceSite for the left operand of a BinOp."""
        self._require(ast.BinOp)
        return SourceSite.from_node(self.node.left, self.filename)  # type: ignore[attr-defined]

    def binop_right(self) -> "SourceSite":
        """Return a SourceSite for the right operand of a BinOp."""
        self._require(ast.BinOp)
        return SourceSite.from_node(self.node.right, self.filename)  # type: ignore[attr-defined]

    def subscript_receiver(self) -> "SourceSite":
        """Return a SourceSite for the Subscript.value (the container)."""
        self._require(ast.Subscript)
        return SourceSite.from_node(self.node.value, self.filename)  # type: ignore[attr-defined]

    def subscript_index(self) -> "SourceSite":
        """Return a SourceSite for the Subscript index, unwrapping legacy ast.Index."""
        self._require(ast.Subscript)
        idx = self.node.slice  # type: ignore[attr-defined]
        # Python < 3.9 wraps the slice in ast.Index
        if hasattr(ast, "Index") and isinstance(idx, ast.Index):
            idx = idx.value  # type: ignore[attr-defined]
        return SourceSite.from_node(idx, self.filename)

    def lambda_body(self) -> "SourceSite":
        """Return a SourceSite for the body expression of a Lambda."""
        self._require(ast.Lambda)
        return SourceSite.from_node(self.node.body, self.filename)  # type: ignore[attr-defined]

    def lambda_params(self) -> "list[str]":
        """Return the argument names for a Lambda node."""
        self._require(ast.Lambda)
        return [a.arg for a in self.node.args.args]  # type: ignore[attr-defined]

    def return_value(self) -> "SourceSite | None":
        """Return a SourceSite for the Return value, or None if bare return."""
        self._require(ast.Return)
        if self.node.value is None:  # type: ignore[attr-defined]
            return None
        return SourceSite.from_node(self.node.value, self.filename)  # type: ignore[attr-defined]

    def assign_target_name(self) -> "str | None":
        """Return the target name id for a single-Name Assign target, else None."""
        self._require(ast.Assign)
        targets = self.node.targets  # type: ignore[attr-defined]
        if len(targets) == 1 and isinstance(targets[0], ast.Name):
            return targets[0].id
        return None

    def assign_value(self) -> "SourceSite":
        """Return a SourceSite for Assign.value."""
        self._require(ast.Assign)
        return SourceSite.from_node(self.node.value, self.filename)  # type: ignore[attr-defined]

    def if_test(self) -> "SourceSite":
        """Return a SourceSite for the If test expression."""
        self._require(ast.If)
        return SourceSite.from_node(self.node.test, self.filename)  # type: ignore[attr-defined]

    def if_body(self) -> "list[SourceSite]":
        """Return SourceSites for the statements in the If body."""
        self._require(ast.If)
        return [SourceSite.from_node(s, self.filename) for s in self.node.body]  # type: ignore[attr-defined]

    def if_orelse(self) -> "list[SourceSite]":
        """Return SourceSites for the statements in the If orelse (else branch)."""
        self._require(ast.If)
        return [SourceSite.from_node(s, self.filename) for s in self.node.orelse]  # type: ignore[attr-defined]

    def function_name(self) -> str:
        """Return the name string for a FunctionDef or AsyncFunctionDef."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        return self.node.name  # type: ignore[attr-defined]

    def function_params(self) -> "list[str]":
        """Return the argument names for a FunctionDef or AsyncFunctionDef."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        return [a.arg for a in self.node.args.args]  # type: ignore[attr-defined]

    def function_body(self) -> "list[SourceSite]":
        """Return SourceSites for the statements in a FunctionDef body."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        return [SourceSite.from_node(s, self.filename) for s in self.node.body]  # type: ignore[attr-defined]

    def compare_ops(self) -> "list[str]":
        """Return the operator class names for a Compare node (e.g. ['Eq', 'Lt'])."""
        self._require(ast.Compare)
        return [type(op).__name__ for op in self.node.ops]  # type: ignore[attr-defined]

    def compare_left(self) -> "SourceSite":
        """Return a SourceSite for the left operand of a Compare."""
        self._require(ast.Compare)
        return SourceSite.from_node(self.node.left, self.filename)  # type: ignore[attr-defined]

    def compare_comparators(self) -> "list[SourceSite]":
        """Return SourceSites for each comparator on the right side of a Compare."""
        self._require(ast.Compare)
        return [SourceSite.from_node(c, self.filename) for c in self.node.comparators]  # type: ignore[attr-defined]

    def function_name(self) -> str:
        """Return the name string for a FunctionDef or AsyncFunctionDef node."""
        self._require(ast.FunctionDef, ast.AsyncFunctionDef)
        return self.node.name  # type: ignore[attr-defined]
