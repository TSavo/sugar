from __future__ import annotations

import ast

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.outcome import Incomplete


def test_for_statement_is_typed_runtime_boundary() -> None:
    outcome = compose_block("    for x in xs:\n        pass\n    return 1\n")

    assert isinstance(outcome, Incomplete)
    assert "for loop runtime boundary" in outcome.reason
    assert "blame=f.py:2:4" in outcome.reason


def test_for_else_is_typed_runtime_boundary() -> None:
    outcome = compose_block(
        "    for x in xs:\n"
        "        pass\n"
        "    else:\n"
        "        pass\n"
        "    return 1\n"
    )

    assert isinstance(outcome, Incomplete)
    assert "for loop runtime boundary" in outcome.reason


def test_async_for_remains_owned_by_async_for_sugar() -> None:
    node = (
        ast.parse("async def f():\n    async for x in xs:\n        pass\n")
        .body[0]
        .body[0]
    )
    site = SourceFragment.from_node(node, "async_for.py")
    candidates = default_catalog().candidates_for(SugarRole.STATEMENT, site)
    names = {candidate.name for candidate in candidates}

    assert "AsyncForSugar" in names
    assert "ForSugar" not in names
