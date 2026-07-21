"""`substitute` on the AST tree, proven at the integer literal.

substitute is the temporal mechanism, and it lives entirely in AST rewriting:
a Name is replaced by its bound node IN THE TREE before any sugar runs, so the
meaning layer (`desugar`) never consults a temporal context. This file pins the
verb's shape at its simplest node -- an integer literal -- plus the two things
that give it meaning by contrast: the Name base case, and the structural
recursion through a compound.
"""

import tempfile
from pathlib import Path

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _tree(src: str) -> SourceFile:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return SourceFile(path_source(path))


def _bind_target():
    # a real Node (the literal 3) to bind a name to
    return next(
        n for n in _tree("def g():\n    return 3\n").root.walk() if n.kind == "Constant"
    )


def test_integer_literal_is_the_inert_terminus():
    const5 = next(
        n
        for n in _tree("def f(x):\n    return x + 5\n").root.walk()
        if n.kind == "Constant"
    )
    # A literal has no children and no hole: substitute finds nothing to change
    # and returns the SAME node, whatever the scope says.
    assert const5.substitute({"x": _bind_target()}) is const5
    assert const5.substitute({}) is const5
    assert const5.value == 5


def test_name_is_the_one_base_case_that_binds():
    binop = next(
        n for n in _tree("def f(x):\n    return x + 5\n").root.walk() if n.kind == "BinOp"
    )
    three = _bind_target()
    name_x = binop.left  # capture once: the tree materializes a fresh node per access
    bound = name_x.substitute({"x": three})
    assert bound is three  # the hole swapped for its shape
    # an unbound name stands (it is a gap the sugar layer will panic on, not a
    # lookup -- substitute never invents a binding)
    assert name_x.substitute({}) is name_x


def test_compound_just_recurses():
    binop = next(
        n for n in _tree("def f(x):\n    return x + 5\n").root.walk() if n.kind == "BinOp"
    )
    rewritten = binop.substitute({"x": _bind_target()})
    assert rewritten is not binop  # rebuilt because a child changed
    assert rewritten.kind == "BinOp"
    assert rewritten.left.kind == "Constant" and rewritten.left.value == 3  # x bound
    assert rewritten.right.kind == "Constant" and rewritten.right.value == 5  # 5 inert


if __name__ == "__main__":
    test_integer_literal_is_the_inert_terminus()
    test_name_is_the_one_base_case_that_binds()
    test_compound_just_recurses()
    print("ok: substitute proven at the integer literal (inert), Name (binds), compound (recurses)")
