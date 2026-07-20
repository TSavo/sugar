"""No recursion anywhere in OUR pass.

The provider's recursive descent is the provider's (that is the #5932
crash); the membrane build, walk, and corpus enumeration are stack-driven.
Executed proof: run them under a recursion limit far below the tree depth.
"""

import sys

from sugar_node_membrane import Membrane
from sugar_node_membrane.construct import NodePool, _build
from sugar_node_membrane.corpus import node_paths
from sugar_node_membrane.cpython_adapter import CPythonAstProvider
from sugar_node_membrane.nodes import SourceUnit

DEPTH = 2000


def _under_limit(limit, fn):
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(limit)
    try:
        return fn()
    finally:
        sys.setrecursionlimit(old)


def test_deep_binop_chain_builds_without_recursion():
    src = "total = " + " + ".join(["1"] * DEPTH) + "\n"
    # The provider parse runs at the normal limit (its recursion is the
    # provider's own affair, #5932); OUR pass — build, walk — runs low.
    unit = SourceUnit(filename="<deep>", source=src)
    handle = CPythonAstProvider().parse(unit)
    root = _under_limit(80, lambda: _build(unit, handle, NodePool()))
    assert sum(1 for _ in _under_limit(80, lambda: list(root.walk()))) > DEPTH


def test_corpus_paths_enumerate_without_recursion():
    src = "total = " + " + ".join(["1"] * DEPTH) + "\n"
    root = Membrane().parse(src)
    paths = _under_limit(80, lambda: list(node_paths(root)))
    assert len(paths) == len(list(root.walk()))
    assert len({p for p, _ in paths}) == len(paths)  # paths are unique addresses
