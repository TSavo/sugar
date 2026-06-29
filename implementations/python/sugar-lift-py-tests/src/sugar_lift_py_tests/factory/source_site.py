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
