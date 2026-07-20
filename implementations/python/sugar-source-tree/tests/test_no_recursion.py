"""No recursion anywhere in OUR pass.

The backend's recursive descent is the backend's (that is the #5932
crash); the tree build, walk, and corpus enumeration are stack-driven.
Executed proof: run them under a recursion limit far below the tree depth.
"""

import sys

from conftest import oracle_source_file
from sugar_source_tree import SourceFile
from sugar_source_tree.corpus import node_paths

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
    # The backend parse runs at the normal limit (its recursion is the
    # backend's own affair, #5932); OUR pass — materialize, walk — runs low.
    file = oracle_source_file(src)
    assert sum(1 for _ in _under_limit(80, lambda: list(file.root.walk()))) > DEPTH


def test_corpus_paths_enumerate_without_recursion():
    src = "total = " + " + ".join(["1"] * DEPTH) + "\n"
    root = oracle_source_file(src).root
    paths = _under_limit(80, lambda: list(node_paths(root)))
    assert len(paths) == len(list(root.walk()))
    assert len({p for p, _ in paths}) == len(paths)  # paths are unique addresses
