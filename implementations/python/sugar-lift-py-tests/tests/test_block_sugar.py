"""A block is Python's indented suite (a `FunctionDef.body`, an `If.body`/`orelse`):
an ordered composite of statements. The factory's AST->stack walk must push it as a
Block so the inside-out (backwards) read has a unit to COMPOSE its statements, rather
than an external loop faking the composition.

Test-first for the missed step: the suite lands on the stack as a Block, popped AFTER
its statements (so the statements are built first, then the block composes them)."""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment_stack import SourceFragmentStack
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


def _build_block_sugar(body_src: str):
    fn = ast.parse(f"def f(x):\n{body_src}").body[0]
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    result = build_node(
        Block.of(fn.body), filename="f.py", role=SugarRole.STATEMENT, ctx=ctx
    )
    return result.sugar, ctx


def _recursive_collect(statements: tuple, ctx: object) -> tuple:
    """The pre-#4581 collector, retained only as a bounded byte-identity oracle."""
    if not statements:
        return ()
    head, *rest = statements
    rest = tuple(rest)
    outcome = head.reduce(ctx)
    next_ctx = outcome.extend_scope(ctx)
    follow = outcome.follow()
    tail = rest if follow.keeps_rest else ()
    if follow.continues:
        tail = _recursive_collect(rest, next_ctx)
        if follow.transform is not None:
            tail = follow.transform(tail)
    return (*outcome.contribution(), *tail)


def test_stack_pushes_a_block_for_a_suite():
    sites = SourceFragmentStack.from_source(FUNCTION, "f.py").sites
    assert "Block" in [s.observed for s in sites]


def test_block_is_popped_after_its_statements_inside_out():
    # pop order is the build order: a statement of the suite is built BEFORE the
    # block that composes it.
    sites = SourceFragmentStack.from_source(FUNCTION, "f.py").sites
    kinds = [s.observed for s in sites]
    block_index = kinds.index("Block")
    # the block sits BEFORE its statements in the stack, so it POPS after them.
    after = kinds[block_index + 1 :]
    assert "Return" in after


def test_block_carries_its_statements_in_order():
    # nested blocks: the module body is also a suite, so target the FUNCTION's block
    # (the one holding the Return).
    sites = SourceFragmentStack.from_source(FUNCTION, "f.py").sites
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
    # A non-name delete remains a store-effect gap. The block's composition asks the
    # catalog, finds nothing, and the factory panics. Never an ad-hoc raise or skip.
    with pytest.raises(FactoryPanic):
        _compose_block('    "doc"\n    del obj.attr\n')


def test_block_collect_is_byte_identical_to_bounded_recursive_control():
    sugar, ctx = _build_block_sugar(
        "    x = 1\n"
        "    if x:\n"
        "        return x\n"
        "    assert x == 1\n"
        "    return x\n"
    )

    recursive = BlockValue(_recursive_collect(sugar.statements, ctx))
    iterative = complete_value(sugar.desugar(ctx), owner="block")

    assert iterative == recursive


def test_lift_file_payload_handles_five_thousand_statement_block():
    probe = textwrap.dedent("""
        import sys

        from sugar_lift_py_tests.lift_rpc import lift_file_payload

        sys.setrecursionlimit(300)
        source = "def f():\\n" + "".join(
            f"    x{i} = {i}\\n" for i in range(5_000)
        ) + "    return x4999\\n"
        payload = lift_file_payload(source, "deep.py")
        print(len(payload.ir))
        """)

    completed = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", probe],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, (
        "block follow must be heap-bounded, not C-stack-bounded; "
        f"exit={completed.returncode}\n{completed.stderr[-4000:]}"
    )


def test_lift_file_payload_handles_real_datetime_under_bounded_stack(
    cpython_311_datetime_path,
):
    """#4581 pin: real vendored datetime must lift without C-stack death.

    Pre-#4583, statement-sequence recursion made long modules fatal
    (SIGSEGV / faulthandler C-stack). The iterative block follow keeps depth
    on the heap; this subprocess keeps Python's recursion limit low so any
    reintroduction of native block-follow recursion fails loud.
    """
    probe = textwrap.dedent(f"""
        import sys
        from pathlib import Path

        from sugar_lift_py_tests.lift_rpc import lift_file_payload

        sys.setrecursionlimit(300)
        source = Path({str(cpython_311_datetime_path)!r}).read_text(encoding="utf-8")
        payload = lift_file_payload(source, "datetime.py")
        print(len(payload.ir), len(payload.source_mementos))
        """)

    completed = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", probe],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, (
        "real datetime block follow must be heap-bounded, not C-stack-bounded; "
        f"exit={completed.returncode}\n{completed.stderr[-4000:]}"
    )
    assert completed.stdout.strip() == "185 140", (
        "datetime lift receipt drifted from the #4581/#4583 pin "
        f"(ir source_mementos); got {completed.stdout!r}"
    )
