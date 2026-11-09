"""``FunctionDef._owns_yield`` asks each node of the constructed graph once.

The constructed graph is a DAG: a substituted body shares subgraphs across
statements. Walking it as a tree re-asked every shared subgraph once per path,
which is exponential in sharing depth and put
``pandas/core/groupby/generic.py`` over the 300 s recensus ceiling.

Twins:
  truthful — a suspension reachable only through shared subgraphs is found,
             and a graph with N distinct nodes costs N asks, not 2**N;
  lying    — a shared graph with no suspension answers False in the same N
             asks, and a suspension owned by a nested callable is not this
             body's.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.nodes import FunctionDef, Node, Yield
from sugar_source_tree.tree import SourceFile

_DEPTH = 64


class _SharedNode(Node):
    """A graph node whose only content is its child edges."""

    def _child_edges(self):
        self.asked[0] += 1
        return self.edges


def _shared(edges: tuple, asked: list[int]) -> _SharedNode:
    node = object.__new__(_SharedNode)
    object.__setattr__(node, "edges", edges)
    object.__setattr__(node, "asked", asked)
    return node


def _diamond_chain(leaf, asked: list[int]) -> _SharedNode:
    """``_DEPTH`` layers; each layer reaches the next along two edges.

    Distinct nodes: ``_DEPTH``. Distinct root-to-leaf paths: ``2**_DEPTH``.
    """
    edges = () if leaf is None else (("left", None, leaf), ("right", None, leaf))
    node = _shared(edges, asked)
    for _ in range(_DEPTH - 1):
        node = _shared((("left", None, node), ("right", None, node)), asked)
    return node


def _function(source: str):
    directory = Path(tempfile.mkdtemp())
    path = directory / "specimen.py"
    path.write_text(source, encoding="utf-8")
    tree = SourceFile(
        path_source(str(path)),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    return next(node for node in tree.nodes() if node.kind == "FunctionDef")


def _a_yield() -> Yield:
    function = _function("def f():\n    yield 1\n")
    return next(node for node in function.walk() if isinstance(node, Yield))


def test_suspension_behind_shared_subgraphs_is_found_in_linear_asks() -> None:
    asked = [0]
    root = _diamond_chain(_a_yield(), asked)
    assert FunctionDef._owns_yield((root,)) is True
    assert asked[0] == _DEPTH


def test_shared_graph_without_suspension_is_false_in_linear_asks() -> None:
    asked = [0]
    root = _diamond_chain(None, asked)
    # The same statement object twice: the second is not asked again.
    assert FunctionDef._owns_yield((root, root)) is False
    assert asked[0] == _DEPTH


def test_source_body_owns_its_own_suspension() -> None:
    assert FunctionDef._owns_yield(_function("def f():\n    yield 1\n").body)
    nested_in_expression = _function(
        "def f(a):\n    x = [a, (yield a)]\n    return x\n"
    )
    assert FunctionDef._owns_yield(nested_in_expression.body)
    delegating = _function("def f(a):\n    yield from a\n")
    assert FunctionDef._owns_yield(delegating.body)


def test_nested_callable_suspension_is_not_this_bodys() -> None:
    plain = _function("def f(a):\n    x = [a]\n    return x\n")
    assert FunctionDef._owns_yield(plain.body) is False

    nested_def = _function(
        "def f():\n    def g():\n        yield 1\n    return g\n"
    )
    assert nested_def.name == "f"
    assert FunctionDef._owns_yield(nested_def.body) is False

    nested_lambda = _function("def f():\n    return lambda: (yield)\n")
    assert FunctionDef._owns_yield(nested_lambda.body) is False
