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

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SubstituteNotWritten
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
        n
        for n in _tree("def f(x):\n    return x + 5\n").root.walk()
        if n.kind == "BinOp"
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
        n
        for n in _tree("def f(x):\n    return x + 5\n").root.walk()
        if n.kind == "BinOp"
    )
    rewritten = binop.substitute({"x": _bind_target()})
    assert rewritten is not binop  # rebuilt because a child changed
    assert rewritten.kind == "BinOp"
    assert rewritten.left.kind == "Constant" and rewritten.left.value == 3  # x bound
    assert rewritten.right.kind == "Constant" and rewritten.right.value == 5  # 5 inert


def test_function_masks_its_parameter():
    # def f(x): return x -- the parameter x is HELD OUT of the body's scope, so
    # an outer x cannot capture it. The read becomes its declaration-owned
    # FormalRef rather than retaining a generic Name.
    fx = next(_tree("def f(x):\n    return x\n").functions())
    substituted = fx.substitute({"x": _bind_target()})
    ref = next(node for node in substituted.walk() if node.kind == "FormalRef")
    assert ref.coordinate.declared_name == "x"
    # def g(): return x -- no parameter shadows it, so the FREE x DOES substitute.
    g = next(_tree("def g():\n    return x\n").functions())
    gsub = g.substitute({"x": _bind_target()})
    ret = next(n for n in gsub.walk() if n.kind == "Return")
    assert ret.value.kind == "Constant" and ret.value.value == 3


def test_a_block_threads_its_assignments():
    # x = 5; return x -- the assignment binds x for the REST of the block, so
    # substitute inlines it: `return x` becomes `return 5`. This is the temporal
    # that used to live in ctx.temporal, now pure tree rewriting: the block
    # threads each binding forward as it walks its statements.
    f = next(_tree("def f():\n    x = 5\n    return x\n").functions())
    ret = next(n for n in f.substitute({}).walk() if n.kind == "Return")
    assert ret.value.kind == "Constant" and ret.value.value == 5
    # a rebind shadows for the tail (single-assignment): y = 1; y = 2; return y -> 2
    g = next(_tree("def g():\n    y = 1\n    y = 2\n    return y\n").functions())
    retg = next(n for n in g.substitute({}).walk() if n.kind == "Return")
    assert retg.value.value == 2


def test_binders_mask_their_bound_names():
    # for x in xs: return x -- the loop target x is masked for the body, so an
    # outer x cannot capture it; the parameter read is coordinate-bearing.
    forfn = next(_tree("def f(xs):\n    for x in xs:\n        return x\n").functions())
    substituted = forfn.substitute({"x": _bind_target()})
    ref = next(node for node in substituted.walk() if node.kind == "FormalRef")
    assert ref.coordinate.declared_name == "xs"
    # lambda z: z + 1 -- the parameter z is masked for the body.
    lam = next(
        n for n in _tree("g = lambda z: z + z\n").root.walk() if n.kind == "Lambda"
    )
    substituted_lambda = lam.substitute({"z": _bind_target()})
    assert substituted_lambda is not lam  # shadow proves substitution ran
    assert substituted_lambda.body.left.id == "z"
    assert substituted_lambda.body.right.id == "z"
    # [i for i in xs] -- the comprehension loop var i is masked (no capture);
    # a free var in the element substitutes.
    c1 = next(
        n for n in _tree("a = [i for i in xs]\n").root.walk() if n.kind == "ListComp"
    )
    assert c1.substitute({"i": _bind_target()}) is c1
    c2 = next(
        n for n in _tree("a = [y for i in xs]\n").root.walk() if n.kind == "ListComp"
    )
    assert c2.substitute({"y": _bind_target()}).elt.value == 3


def test_the_base_is_loud_for_an_unwritten_node():
    # Every concrete node now writes substitute (the grammar drain is complete),
    # so the guarantee is proven by construction. The enforcement mechanism
    # itself still stands: the abstract base PANICS rather than silently
    # recursing -- a newly-added node that forgets to override cannot capture
    # quietly. Reach past the concrete override to the base to witness it.
    from sugar_source_tree.nodes import Node

    node = next(_tree("def f(x):\n    return x + 5\n").root.walk())
    with pytest.raises(SubstituteNotWritten):
        Node.substitute(node, {})


def test_aug_assign_rebinds_to_the_operation():
    # x = 1; x += 2; return x -- the augmented assignment rebinds x to `x + 2`,
    # reading the OLD x (1) from the threaded scope, so `return x` inlines to
    # `return 1 + 2`. Temporal, pure tree rewriting.
    f = next(_tree("def f():\n    x = 1\n    x += 2\n    return x\n").functions())
    ret = next(n for n in f.substitute({}).walk() if n.kind == "Return")
    assert ret.value.kind == "BinOp"
    assert ret.value.left.value == 1 and ret.value.right.value == 2


def test_walrus_binding_leaks_to_the_block():
    # y = (x := 5); return x -- the walrus binds x for the rest of the block,
    # so `return x` inlines to `return 5` even though x is only named inside
    # the assignment's rhs expression.
    f = next(_tree("def f():\n    y = (x := 5)\n    return x\n").functions())
    ret = next(n for n in f.substitute({}).walk() if n.kind == "Return")
    assert ret.value.kind == "Constant" and ret.value.value == 5


if __name__ == "__main__":
    test_integer_literal_is_the_inert_terminus()
    test_name_is_the_one_base_case_that_binds()
    test_compound_just_recurses()
    test_function_masks_its_parameter()
    test_binders_mask_their_bound_names()
    test_the_base_is_loud_for_an_unwritten_node()
    test_aug_assign_rebinds_to_the_operation()
    test_walrus_binding_leaks_to_the_block()
    print(
        "ok: substitute -- literal inert, Name binds, compound recurses, "
        "FunctionDef masks its parameter, unwritten binder panics"
    )
