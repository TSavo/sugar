from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import List, Optional

from .block import Block
from .source_site import SourceSite


def _is_suite(value) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, ast.stmt) for item in value
    )


@dataclass
class SourceSiteStack:
    sites: List[SourceSite]

    @classmethod
    def from_source(cls, source: str, filename: str) -> "SourceSiteStack":
        tree = ast.parse(source, filename=filename)
        sites = []
        cls._push_tree(tree, filename, sites)
        return cls(sites)

    @classmethod
    def _push_tree(cls, node: ast.AST, filename: str, sites: List[SourceSite]) -> None:
        if hasattr(node, "lineno") and hasattr(node, "col_offset"):
            sites.append(SourceSite.from_node(node, filename))
        # Walk fields, not iter_child_nodes, so a SUITE (a `list[stmt]` field like
        # `body`/`orelse`) is pushed as a Block BEFORE its statements. Pushed before
        # -> popped after: the statements build first (inside), then the block
        # composes them (out). Every other child recurses as before.
        for _field, value in ast.iter_fields(node):
            if _is_suite(value):
                block = Block.of(value)
                sites.append(SourceSite.from_node(block, filename))
                for stmt in value:
                    cls._push_tree(stmt, filename, sites)
            elif isinstance(value, ast.AST):
                cls._push_tree(value, filename, sites)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        cls._push_tree(item, filename, sites)

    def pop(self) -> Optional[SourceSite]:
        if not self.sites:
            return None
        return self.sites.pop()
