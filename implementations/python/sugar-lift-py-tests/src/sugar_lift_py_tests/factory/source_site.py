from __future__ import annotations

import ast
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSite:
    node: ast.AST
    filename: str
    line: int
    col: int

    @classmethod
    def from_node(cls, node: ast.AST, filename: str) -> "SourceSite":
        return cls(
            node=node,
            filename=filename,
            line=getattr(node, "lineno"),
            col=getattr(node, "col_offset"),
        )

    @property
    def observed(self) -> str:
        return type(self.node).__name__

    @property
    def blame(self) -> str:
        return f"{self.filename}:{self.line}:{self.col}"

    @property
    def suggested_sugar_module(self) -> str:
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", self.observed).lower()
        return f"sugar_lift_py_tests.sugar.{name}.{name}_sugar"
