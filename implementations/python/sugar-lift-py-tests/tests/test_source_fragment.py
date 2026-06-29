"""SourceSite is THE source fragment -- the one object the factory uses to talk to the
AST. Feed it Python and it breaks down the right way: a module into its body, a body
into its statements, a statement into its terms, a term into its sub-terms. An `if`
breaks into its test term and its branch blocks -- the shape IfSugar composes."""
from __future__ import annotations

import ast

from sugar_lift_py_tests.factory.source_site import SourceSite


def _module(src: str) -> SourceSite:
    return SourceSite.from_node(ast.parse(src), "t.py")


def _function_body(src: str) -> SourceSite:
    # module -> body Block -> the def -> the def's body Block
    fn = _module(src).fragments()[0].statements()[0]
    return next(f for f in fn.fragments() if f.observed == "Block")


def test_module_fragments_into_one_body_block():
    assert [f.observed for f in _module("x = 1\n").fragments()] == ["Block"]


def test_body_breaks_into_its_statements_in_order():
    body = _module("a = 1\nb = 2\nc = 3\n").fragments()[0]
    assert [s.observed for s in body.statements()] == ["Assign", "Assign", "Assign"]


def test_statement_breaks_into_its_terms():
    # `z = x + 1` -> the target Name and the value expression
    assign = _module("z = x + 1\n").fragments()[0].statements()[0]
    assert [t.observed for t in assign.terms()] == ["Name", "BinOp"]


def test_term_breaks_into_its_subterms():
    # `x + 1` -> Name(x), the literal 1 (the operator is not a term)
    binop = _module("z = x + 1\n").fragments()[0].statements()[0].terms()[1]
    assert [t.observed for t in binop.terms()] == ["Name", "PrimitiveLiteral"]


def test_if_breaks_into_its_test_term_and_branch_blocks():
    # the exact shape IfSugar composes: a test term + a then-block + an else-block
    if_stmt = _module("if x == 0:\n    a = 1\nelse:\n    a = 2\n").fragments()[0].statements()[0]
    assert [t.observed for t in if_stmt.terms()] == ["Compare"]
    assert [s.observed for s in if_stmt.statements()] == ["Block", "Block"]


def test_a_whole_function_body_decomposes_statements_then_terms():
    body = _function_body("def f(x):\n    y = x + 1\n    return y\n")
    assert [s.observed for s in body.statements()] == ["Assign", "Return"]
    assert [t.observed for t in body.statements()[0].terms()] == ["Name", "BinOp"]
