"""The authenticated Compare population never escapes terminal accounting."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.no_call_body_attribution import (
    AttributionInvariantError,
    AttributionOutcome,
    BodyProbe,
    ProducerFamily,
    attribute_body_probe,
    attribute_body_probes,
    discover_no_call_body_probes,
    pull_shared_demand_table,
    require_expected_denominators,
)
from sugar_lift_py_tests.outcome import Complete

PREVIOUSLY_UNACCOUNTED = frozenset(
    {
        "tests/arrays/categorical/test_operators.py:335:Compare",
        "tests/arrays/categorical/test_operators.py:343:Compare",
        "tests/frame/test_arithmetic.py:1221:Compare",
        "tests/frame/test_arithmetic.py:1227:Compare",
        "tests/frame/test_arithmetic.py:1679:Compare",
        "tests/frame/test_arithmetic.py:1682:Compare",
        "tests/frame/test_arithmetic.py:1692:Compare",
        "tests/frame/test_arithmetic.py:1704:Compare",
        "tests/frame/test_arithmetic.py:1707:Compare",
        "tests/frame/test_nonunique_indexes.py:204:Compare",
        "tests/indexes/categorical/test_equals.py:39:Compare",
        "tests/indexes/datetimes/test_date_range.py:348:Compare",
        "tests/indexes/datetimes/test_date_range.py:351:Compare",
        "tests/indexes/multi/test_equivalence.py:43:Compare",
        "tests/indexes/multi/test_equivalence.py:55:Compare",
        "tests/indexes/multi/test_equivalence.py:65:Compare",
        "tests/indexes/multi/test_equivalence.py:72:Compare",
        "tests/indexes/multi/test_equivalence.py:74:Compare",
        "tests/indexes/multi/test_equivalence.py:76:Compare",
        "tests/indexes/multi/test_equivalence.py:79:Compare",
        "tests/indexes/multi/test_equivalence.py:81:Compare",
        "tests/indexes/test_old_base.py:540:Compare",
        "tests/indexes/test_old_base.py:552:Compare",
        "tests/indexes/test_old_base.py:562:Compare",
        "tests/indexes/test_old_base.py:569:Compare",
        "tests/indexes/test_old_base.py:571:Compare",
        "tests/indexes/test_old_base.py:573:Compare",
        "tests/indexes/test_old_base.py:576:Compare",
        "tests/indexes/test_old_base.py:578:Compare",
        "tests/series/test_arithmetic.py:544:Compare",
        "tests/series/test_arithmetic.py:785:Compare",
        "tests/series/test_arithmetic.py:787:Compare",
        "tests/series/test_arithmetic.py:790:Compare",
        "tests/series/test_arithmetic.py:792:Compare",
    }
)


def _root_compare_has_no_call(corpus_root: Path, body_id: str) -> bool:
    relative, line_text, _ = body_id.rsplit(":", 2)
    tree = ast.parse((corpus_root / relative).read_text(encoding="utf-8"))
    matches = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare) and node.lineno == int(line_text)
    )
    assert len(matches) == 1, body_id
    return not any(isinstance(node, ast.Call) for node in ast.walk(matches[0]))


def test_one_silent_compare_completion_is_row_level_red() -> None:
    """Lying twin: no terminal testimony can never become an omitted row."""
    probe = BodyProbe(
        body_id="pandas/example.py:1:Compare",
        family=ProducerFamily.COMPARE,
        evaluator=lambda: Complete(object()),
    )

    with pytest.raises(AttributionInvariantError, match="completed without"):
        attribute_body_probe(probe)


def test_all_34_compare_completions_publish_authenticated_compare_exits(
    tmp_path: Path,
) -> None:
    corpus = authenticated_pandas_corpus()
    repo_root = Path(__file__).resolve().parents[4]
    payload = pull_shared_demand_table(repo_root, tmp_path / "demand-table.json")
    compare_inventory = require_expected_denominators(
        discover_no_call_body_probes(
            payload,
            corpus.root,
            families=frozenset({ProducerFamily.COMPARE}),
        ),
        families=frozenset({ProducerFamily.COMPARE}),
    )
    probes = tuple(
        probe for probe in compare_inventory if probe.body_id in PREVIOUSLY_UNACCOUNTED
    )

    assert {probe.body_id for probe in probes} == PREVIOUSLY_UNACCOUNTED
    assert len(probes) == 34
    assert all(
        _root_compare_has_no_call(corpus.root, body_id)
        for body_id in PREVIOUSLY_UNACCOUNTED
    )

    report = attribute_body_probes(probes)

    assert report.discrepancies == ()
    assert report.outcome_total == 34
    assert len(report.bodies) == 34
    assert all(
        body.outcome is AttributionOutcome.AUTHENTICATED_EXIT
        and body.detail == "Compare"
        for body in report.bodies
    )
