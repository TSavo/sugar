"""A block is Python's indented suite (a `FunctionDef.body`, an `If.body`/`orelse`):
an ordered composite of statements. The factory's AST->stack walk must push it as a
Block so the inside-out (backwards) read has a unit to COMPOSE its statements, rather
than an external loop faking the composition.

Test-first for the missed step: the suite lands on the stack as a Block, popped AFTER
its statements (so the statements are built first, then the block composes them)."""
from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_site_stack import SourceSiteStack
from sugar_lift_py_tests.floor import BlockValue
from sugar_lift_py_tests.outcome import complete_value

FUNCTION = "def f(x):\n    'doc'\n    return x\n"


def _compose_block(body_src: str):
    """Compose a function-body suite through the factory at the STATEMENT role: the
    factory dispatches the Block to BlockSugar, which composes the statements."""
    fn = ast.parse(f"def f(x):\n{body_src}").body[0]
    block = Block.of(fn.body)
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    result = build_node(block, filename="f.py", role=SugarRole.STATEMENT, ctx=ctx)
    return complete_value(result.sugar.desugar(ctx), owner="block")


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


def test_block_sugar_absorbs_comments_into_an_empty_block():
    # a body of only comments composes to an empty block -- each comment is Support
    # and contributes nothing.
    assert _compose_block('    "doc one"\n    "doc two"\n') == BlockValue(())


def test_block_sugar_panics_on_a_statement_with_no_sugar_yet():
    # an augmented assignment has no statement sugar yet -> the block's composition
    # asks the catalog, finds nothing, and the factory panics (names the next sugar).
    # Never an ad-hoc raise, never a silent skip.
    with pytest.raises(FactoryGap):
        _compose_block('    "doc"\n    x += 1\n')
