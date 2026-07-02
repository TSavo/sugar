from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sugar_lift_py_tests.idd import cli
from sugar_lift_py_tests.idd.sugar_witness_instruments import (
    DEFAULT_SUGAR_WITNESS_SEEDS,
    collect_sugar_witness_frontier,
    evaluate_seed_witnesses,
    render_text,
    unenrolled_sugars,
)
from sugar_lift_py_tests.witness_harness import WitnessPipelineError, prove_verdict

ROOT = Path(__file__).resolve().parents[4]
EXPECTED_UNENROLLED_SUGARS = 53
EXPECTED_SEED_CASES = 4
EXPECTED_SEED_OWNER_COUNT = 3
EXPECTED_TRIPLE_FAILURES = 1


@pytest.fixture(scope="module")
def seed_report(tmp_path_factory: pytest.TempPathFactory):
    return evaluate_seed_witnesses(
        DEFAULT_SUGAR_WITNESS_SEEDS,
        tmp_path_factory.mktemp("sugar-witness-seeds"),
    )


def test_sugar_witness_enrollment_auditor_pins_catalog_baseline() -> None:
    offenders = unenrolled_sugars()

    assert len(offenders) == EXPECTED_UNENROLLED_SUGARS
    by_name = {offender.name: offender for offender in offenders}
    assert by_name["TrySugar"].module == "sugar_lift_py_tests.sugar.try_sugar"
    assert by_name["ProjectedEqualityAssertionSugar"].role == "assertion"
    assert by_name["CallSugar"].role == "term"


def test_sugar_witness_seed_triples_hit_real_solver(seed_report) -> None:
    assert seed_report.seed_count == EXPECTED_SEED_CASES
    assert seed_report.unique_owner_count == EXPECTED_SEED_OWNER_COUNT
    assert seed_report.catalog_count == EXPECTED_UNENROLLED_SUGARS
    assert seed_report.witness_triples_failing == EXPECTED_TRIPLE_FAILURES
    assert seed_report.witnesses_not_dispatching_to_owner == 0
    assert [
        (failure.seed, failure.variant, failure.axis, failure.expected, failure.observed)
        for failure in seed_report.triple_failures
    ] == [("binary_dunder_callsite", "lying", "verdict", "unsat", "sat")]
    assert seed_report.non_circularity_failures == ()


def test_sugar_witness_non_circularity_bad_twin_names_mismatch(
    tmp_path: Path,
) -> None:
    wrong_owner = replace(
        DEFAULT_SUGAR_WITNESS_SEEDS[0],
        owner_sugar="TrySugar",
    )

    report = evaluate_seed_witnesses((wrong_owner,), tmp_path)

    assert report.witness_triples_failing == 1
    assert report.witnesses_not_dispatching_to_owner == 2
    mismatch = report.non_circularity_failures[0]
    assert mismatch.seed == "slice_callsite"
    assert mismatch.expected_sugar == "TrySugar"
    assert mismatch.selected_sugars == ("CallSugar", "CallSugar")
    assert report.triple_failures[0].axis == "sugar-fired"


def test_sugar_witness_frontier_renders_all_three_vectors(
    seed_report,
) -> None:
    report = collect_sugar_witness_frontier(ROOT, seed_report=seed_report)
    text = render_text(report)

    assert seed_report.witness_triples_failing == EXPECTED_TRIPLE_FAILURES
    assert report.to_json()["r"] == {
        "unenrolled_sugars": EXPECTED_UNENROLLED_SUGARS,
        "witness_triples_failing": EXPECTED_TRIPLE_FAILURES,
        "witnesses_not_dispatching_to_owner": 0,
        "total": EXPECTED_UNENROLLED_SUGARS + EXPECTED_TRIPLE_FAILURES,
    }
    assert "R(unenrolled-sugars): 53" in text
    assert "R(witness-triples-failing): 1" in text
    assert "R(witnesses-not-dispatching-to-owner): 0" in text
    assert "seed coverage: 4 seed cases, 3/53 catalog sugars" in text
    assert "TrySugar (sugar_lift_py_tests.sugar.try_sugar)" in text


def test_sugar_witness_cli_exits_red_with_current_enrollment_frontier(
    seed_report,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    report = collect_sugar_witness_frontier(ROOT, seed_report=seed_report)
    monkeypatch.setattr(cli, "collect_sugar_witness_frontier", lambda root: report)

    status = cli.main(["--root", str(ROOT), "--sugar-witness-frontier"])

    assert status == 1
    stdout = capsys.readouterr().out
    assert "R(unenrolled-sugars): 53" in stdout
    assert "R(witness-triples-failing): 1" in stdout


def test_witness_pipeline_solver_absence_is_loud() -> None:
    with pytest.raises(WitnessPipelineError, match="no rows"):
        prove_verdict({"rows": []})
