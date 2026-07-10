"""WhileSugar — construction gap drain (Part of #3809).

Lift-probe (before):

    def f():
        while False:
            pass
        return 1
    assert f() == 1

Refuse: FactoryGap · owner=python.factory · observed=While
· requested=statement
· fix=create sugar_lift_py_tests.sugar.while.while_sugar

Mechanism: missing AST recognizer for While (empty STATEMENT catalog
candidates) — not a floor totalizer. Sibling of ForSugar: condition/body
protocol is a typed RuntimeEffect boundary until floors own the shape.

After: WhileSugar → Incomplete(RuntimeEffect(... while loop runtime boundary ...)).
"""

from __future__ import annotations

import ast

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.while_sugar import WhileSugar


def test_while_statement_is_typed_runtime_boundary() -> None:
    outcome = compose_block("    while xs:\n        pass\n    return 1\n")

    assert isinstance(outcome, Incomplete)
    assert "while loop runtime boundary" in outcome.reason
    assert "blame=f.py:2:4" in outcome.reason


def test_while_else_is_typed_runtime_boundary() -> None:
    outcome = compose_block(
        "    while xs:\n"
        "        pass\n"
        "    else:\n"
        "        pass\n"
        "    return 1\n"
    )

    assert isinstance(outcome, Incomplete)
    assert "while loop runtime boundary" in outcome.reason
    assert "with else/fallthrough" in outcome.reason


def test_while_sugar_selects_from_catalog() -> None:
    node = ast.parse("def f():\n    while True:\n        pass\n").body[0].body[0]
    site = SourceFragment.from_node(node, "while.py")
    candidates = default_catalog().candidates_for(SugarRole.STATEMENT, site)
    names = {candidate.name for candidate in candidates}

    assert "WhileSugar" in names
    assert "ForSugar" not in names

    ctx = FactoryBuildContext(filename="while.py", catalog=default_catalog())
    result = build_node(node, filename="while.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert isinstance(result.sugar, WhileSugar)
    assert result.sugar.has_else is False


def test_while_in_body_dig_no_construction_gap() -> None:
    """Body dig must not FactoryGap on While; typed red is the honest residual."""
    src = (
        "def f():\n"
        "    while False:\n"
        "        pass\n"
        "    return 1\n"
        "\n"
        "def test_a():\n"
        "    assert f() == 1\n"
    )
    try:
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
    except FactoryGap as exc:  # pragma: no cover - regression
        raise AssertionError(f"still construction gap: {exc.info}") from exc
    assert report is not None
    blob = repr(report.payload)
    assert "create sugar_lift_py_tests.sugar.while.while_sugar" not in blob
    assert "observed=While" not in blob or "sugar-gap" not in blob
