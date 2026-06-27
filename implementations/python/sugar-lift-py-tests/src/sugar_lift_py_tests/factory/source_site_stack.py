from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import List, Optional

from .source_site import SourceSite


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
        for child in ast.iter_child_nodes(node):
            cls._push_tree(child, filename, sites)

    def pop(self) -> Optional[SourceSite]:
        if not self.sites:
            return None
        return self.sites.pop()
