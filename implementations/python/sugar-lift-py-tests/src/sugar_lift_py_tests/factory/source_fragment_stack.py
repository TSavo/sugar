from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import List, Optional

from .source_fragment import SourceFragment


@dataclass
class SourceFragmentStack:
    sites: List[SourceFragment]

    @classmethod
    def from_source(cls, source: str, filename: str) -> "SourceFragmentStack":
        tree = ast.parse(source, filename=filename)
        sites: List[SourceFragment] = []
        cls._push(SourceFragment.from_node(tree, filename), sites)
        return cls(sites)

    @classmethod
    def _push(cls, site: SourceFragment, sites: List[SourceFragment]) -> None:
        # A site is pushed BEFORE the fragments it decomposes into, so it pops AFTER
        # them: the children build first (inside), then their parent composes them
        # (out). The fragment owns the decomposition -- the walk just recurses it.
        if hasattr(site.node, "lineno") and hasattr(site.node, "col_offset"):
            sites.append(site)
        for fragment in site.fragments():
            cls._push(fragment, sites)

    def pop(self) -> Optional[SourceFragment]:
        if not self.sites:
            return None
        return self.sites.pop()
