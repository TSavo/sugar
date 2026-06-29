"""A block is Python's indented suite (a `FunctionDef.body`, an `If.body`/`orelse`):
an ordered composite of statements. The factory's AST->stack walk must push it as a
Block so the inside-out (backwards) read has a unit to COMPOSE its statements, rather
than an external loop faking the composition.

Test-first for the missed step: the suite lands on the stack as a Block, popped AFTER
its statements (so the statements are built first, then the block composes them)."""
from __future__ import annotations

import ast

from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.source_site_stack import SourceSiteStack

FUNCTION = "def f(x):\n    'doc'\n    return x\n"


def test_stack_pushes_a_block_for_a_suite():
    sites = SourceSiteStack.from_source(FUNCTION, "f.py").sites
    assert "Block" in [s.observed for s in sites]


def test_block_is_popped_after_its_statements_inside_out():
    # pop order is the build order: a statement of the suite is built BEFORE the
    # block that composes it.
    sites = SourceSiteStack.from_source(FUNCTION, "f.py").sites
    kinds = [s.observed for s in sites]
    block_index = kinds.index("Block")
    # the block sits BEFORE its statements in the stack, so it POPS after them.
    after = kinds[block_index + 1 :]
    assert "Return" in after


def test_block_carries_its_statements_in_order():
    # nested blocks: the module body is also a suite, so target the FUNCTION's block
    # (the one holding the Return).
    sites = SourceSiteStack.from_source(FUNCTION, "f.py").sites
    block = next(
        s.node
        for s in sites
        if isinstance(s.node, Block)
        and any(isinstance(stmt, ast.Return) for stmt in s.node.body)
    )
    assert [type(stmt).__name__ for stmt in block.body] == ["Expr", "Return"]
