from __future__ import annotations

import ast
from dataclasses import replace

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.idd.sugar_witness_instruments import evaluate_seed_witnesses
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.match_sugar import MatchSugar
from sugar_lift_py_tests.temporal import TemporalContext


def _match_statement(source: str, ctx: FactoryBuildContext | None = None):
    node = ast.parse(source).body[0]
    context = ctx or FactoryBuildContext(
        filename="match_case.py", catalog=default_catalog()
    )
    return build_node(
        node,
        filename="match_case.py",
        role=SugarRole.STATEMENT,
        ctx=context,
    )


def test_factory_selects_match_sugar() -> None:
    result = _match_statement("match 2:\n    case 2:\n        return 7\n")

    assert result.audit_row.selected == "MatchSugar"


def test_ground_match_selects_first_matching_literal_case() -> None:
    result = _match_statement(
        "match 2:\n"
        "    case 1:\n"
        "        return 10\n"
        "    case 2:\n"
        "        return 20\n"
        "    case _:\n"
        "        return 30\n"
    )

    outcome = result.sugar.desugar(ReduceContext.root(owner="match-test"))

    assert outcome == Complete(BlockValue((ReturnValue(TermValue(20)),)))


def test_ground_match_uses_wildcard_when_literals_do_not_match() -> None:
    result = _match_statement(
        "match 3:\n"
        "    case 1:\n"
        "        return 10\n"
        "    case _:\n"
        "        return 30\n"
    )

    outcome = result.sugar.desugar(ReduceContext.root(owner="match-test"))

    assert outcome == Complete(BlockValue((ReturnValue(TermValue(30)),)))


def test_ground_false_guard_continues_to_next_case() -> None:
    result = _match_statement(
        "match 2:\n"
        "    case 2 if False:\n"
        "        return 20\n"
        "    case _:\n"
        "        return 30\n"
    )

    outcome = result.sugar.desugar(ReduceContext.root(owner="match-test"))

    assert outcome == Complete(BlockValue((ReturnValue(TermValue(30)),)))


def test_runtime_selected_match_stays_named_and_loud() -> None:
    ctx = FactoryBuildContext(filename="match_case.py", catalog=default_catalog())
    result = _match_statement(
        "match value:\n"
        "    case 1:\n"
        "        return 10\n"
        "    case _:\n"
        "        return 20\n",
        ctx,
    )
    reduce_ctx = replace(
        ReduceContext.root(owner="match-test"),
        temporal=TemporalContext.empty().bind_value(
            "value", SymbolicValue(make_var("value"))
        ),
    )

    outcome = result.sugar.desugar(reduce_ctx)

    assert isinstance(outcome, Incomplete)
    assert type(outcome.effect).__name__ == "MatchSelectionRuntimeEffect"
    assert "runtime match selection" in outcome.reason
    assert outcome.effect.witness.site.filename == "match_case.py"


def test_ground_unsupported_pattern_stays_loud() -> None:
    result = _match_statement("match 1:\n" "    case int():\n" "        return 1\n")

    try:
        result.sugar.desugar(ReduceContext.root(owner="match-test"))
    except FactoryPanic as raised:
        assert raised.info.owner == "MatchSugar"
        assert raised.info.observed == "MatchClass"
    else:
        raise AssertionError("unsupported ground pattern must remain loud")


def test_match_witnesses_discriminate_verdict_and_genuine_runtime_effect(
    tmp_path,
) -> None:
    report = evaluate_seed_witnesses(MatchSugar.witnesses(), tmp_path)

    assert report.is_zero
