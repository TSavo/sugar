"""A ``return``, ``break`` or ``continue`` that leaves an ``except*`` block is
refused by name (#7757).

CPython does not compile it (``SyntaxError: 'break', 'continue' and 'return'
cannot appear in an except* block``), so a source holding one is not a Python
program and has no Python answer. The tree used to construct it and complete:
it is refused where the ``try ... except*`` is constructed
(``TryStar._construct_sugar``), never completed.

What Python does compile is not refused: a ``return`` after the statement, a
``return`` in a definition nested in the block (it leaves that definition's
frame), and a ``break`` whose loop stands inside the block.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "except_star_block_exit.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _refusal(source: str) -> str:
    with pytest.raises(SugarNotWritten) as excinfo:
        _function(source).sugar().desugar(None)
    return str(excinfo.value)


def _not_this_refusal(source: str) -> None:
    """``source`` is not refused as an exit from an ``except*`` block."""
    try:
        _function(source).sugar()
    except SugarNotWritten as refusal:
        assert "inside an except* block" not in str(refusal), refusal


def test_a_return_in_an_except_star_block_is_refused_by_name() -> None:
    refusal = _refusal(
        "def f():\n"
        "    try:\n"
        "        raise ValueError('alone')\n"
        "    except* ValueError:\n"
        "        return 1\n"
    )
    assert "`return` inside an except* block" in refusal


def test_a_return_under_an_if_in_an_except_star_block_is_refused() -> None:
    refusal = _refusal(
        "def f(flag):\n"
        "    try:\n"
        "        raise ValueError('alone')\n"
        "    except* ValueError:\n"
        "        if flag:\n"
        "            return 1\n"
        "    return 2\n"
    )
    assert "`return` inside an except* block" in refusal


def test_a_break_that_leaves_an_except_star_block_is_refused() -> None:
    # Refused by name, never completed (the loop around the statement may be
    # refused by name first: either way no arm completes).
    _refusal(
        "def f(items):\n"
        "    for item in items:\n"
        "        try:\n"
        "            raise ValueError('alone')\n"
        "        except* ValueError:\n"
        "            break\n"
    )


def test_a_continue_that_leaves_an_except_star_block_is_refused() -> None:
    _refusal(
        "def f(items):\n"
        "    for item in items:\n"
        "        try:\n"
        "            raise ValueError('alone')\n"
        "        except* ValueError:\n"
        "            continue\n"
    )


def test_a_return_after_the_statement_is_not_refused() -> None:
    # The truthful twin: Python compiles it, and the function returns.
    outcome = (
        _function(
            "def f():\n"
            "    try:\n"
            "        raise ValueError('alone')\n"
            "    except* ValueError:\n"
            "        pass\n"
            "    return 1\n"
        )
        .sugar()
        .desugar(None)
    )
    assert outcome.halts() == (), outcome.exits
    assert "TermValue(value=1)" in repr(outcome.exits)


def test_a_return_in_a_definition_nested_in_the_block_is_not_refused() -> None:
    _not_this_refusal(
        "def f():\n"
        "    try:\n"
        "        raise ValueError('alone')\n"
        "    except* ValueError:\n"
        "        def inner():\n"
        "            return 1\n"
    )


def test_a_break_whose_loop_stands_in_the_block_is_not_refused() -> None:
    _not_this_refusal(
        "def f(items):\n"
        "    try:\n"
        "        raise ValueError('alone')\n"
        "    except* ValueError:\n"
        "        for item in items:\n"
        "            break\n"
    )
