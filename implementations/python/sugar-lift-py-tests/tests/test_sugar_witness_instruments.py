from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from sugar_lift_py_tests.idd import cli
from sugar_lift_py_tests.idd.sugar_witness_instruments import (
    DEFAULT_SUGAR_WITNESS_SEEDS,
    EXPECTED_NON_FOL_OPT_OUTS,
    claim_has_witness_or_opt_out,
    collect_sugar_witness_frontier,
    current_non_fol_support_floor_names,
    evaluate_seed_witnesses,
    non_fol_opt_out_audit,
    render_text,
    seeds_from_catalog_witnesses,
    unenrolled_sugars,
)
from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.floor import ImportAliasValue, SupportValue
from sugar_lift_py_tests.sugar.witnesses import PendingWitnesses
from sugar_lift_py_tests.witness_harness import (
    WitnessPipelineError,
    prove_verdict,
    run_source_through_real_solver,
)

ROOT = Path(__file__).resolve().parents[4]
EXPECTED_UNENROLLED_SUGARS = 46
EXPECTED_SEED_CASES = 4
EXPECTED_SEED_OWNER_COUNT = 3
# Pinned by #3307: binary-dunder callsites currently emit only the stated
# assertion; the derived body/floor contradiction is missing.
EXPECTED_TRIPLE_FAILURES = 1
EXPECTED_MIGRATED_SEED_NAMES = {
    "slice_callsite",
    "literal_call_return",
    "try_body",
}
EXPECTED_PINNED_FAILURE_SEED_NAMES = {"binary_dunder_callsite"}
EXPECTED_OPT_OUT_SUGARS = {
    "AliasSugar",
    "CommentSugar",
    "SubscriptAssignSugar",
    "SubscriptDeleteSugar",
}


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
    assert "CallSugar" not in by_name
    assert "ReturnSugar" not in by_name
    assert "TrySugar" not in by_name
    assert not (EXPECTED_OPT_OUT_SUGARS & set(by_name))
    assert by_name["ProjectedEqualityAssertionSugar"].role == "assertion"
    assert by_name["AddSugar"].role == "term"


def test_catalog_witnesses_migrate_s1_seed_surface() -> None:
    seeds = seeds_from_catalog_witnesses()
    by_name = {seed.name: seed for seed in seeds}

    assert EXPECTED_MIGRATED_SEED_NAMES <= set(by_name)
    assert EXPECTED_PINNED_FAILURE_SEED_NAMES.isdisjoint(by_name)
    assert by_name["slice_callsite"].owner_sugar == "CallSugar"
    assert by_name["literal_call_return"].owner_sugar == "ReturnSugar"
    assert by_name["try_body"].owner_sugar == "TrySugar"


def test_non_fol_opt_out_is_floor_anchored_and_bidirectional() -> None:
    assert SupportValue.non_fol_support is True
    assert ImportAliasValue.non_fol_support is True
    assert current_non_fol_support_floor_names() == {
        "SupportValue",
        "ImportAliasValue",
    }

    audit = non_fol_opt_out_audit()

    assert audit.is_zero
    assert {row.sugar_name for row in EXPECTED_NON_FOL_OPT_OUTS} == (
        EXPECTED_OPT_OUT_SUGARS
    )


def test_non_fol_opt_out_audit_bad_twins() -> None:
    missing_support_pin = tuple(
        row
        for row in EXPECTED_NON_FOL_OPT_OUTS
        if row.floor_name != "SupportValue"
    )
    missing_support = non_fol_opt_out_audit(pinned=missing_support_pin)
    assert missing_support.marked_but_unpinned == ("SupportValue",)

    unmarked_pin = replace(EXPECTED_NON_FOL_OPT_OUTS[0], floor_name="TermValue")
    unmarked = non_fol_opt_out_audit(pinned=(unmarked_pin,))
    assert unmarked.pinned_but_unmarked == (unmarked_pin,)


def test_sugar_declared_social_opt_out_is_not_a_mechanism() -> None:
    class SocialOptOutOwner:
        not_verdict_bearing = True

        @classmethod
        def owns(cls, fragment) -> bool:
            return False

        @classmethod
        def build(cls, fragment, ctx):
            raise AssertionError("synthetic claim must not build")

    claim = SugarClaim(
        name="SocialOptOutSugar",
        role=SugarRole.TERM,
        owns=SocialOptOutOwner.owns,
        build=SocialOptOutOwner.build,
        witnesses=lambda: PendingWitnesses(
            sugar_name="SocialOptOutSugar",
            module=__name__,
        ),
    )

    assert claim_has_witness_or_opt_out(claim) is False


def test_sugar_witness_seed_triples_hit_real_solver(seed_report) -> None:
    assert seed_report.seed_count == EXPECTED_SEED_CASES
    assert seed_report.unique_owner_count == EXPECTED_SEED_OWNER_COUNT
    assert seed_report.catalog_count == 53
    assert seed_report.witness_triples_failing == EXPECTED_TRIPLE_FAILURES
    assert seed_report.witnesses_not_dispatching_to_owner == 0
    assert [
        (failure.seed, failure.variant, failure.axis, failure.expected, failure.observed)
        for failure in seed_report.triple_failures
    ] == [("binary_dunder_callsite", "lying", "verdict", "unsat", "sat")]
    assert seed_report.non_circularity_failures == ()


def test_binary_dunder_lying_trace_documents_missing_derived_fact(
    tmp_path: Path,
) -> None:
    seed = next(
        item
        for item in DEFAULT_SUGAR_WITNESS_SEEDS
        if item.name == "binary_dunder_callsite"
    )

    result = run_source_through_real_solver(tmp_path / "lying", seed.lying.source)

    ir = result.lift_doc["ir"]
    diagnostics = result.lift_doc["diagnostics"]
    trace = {
        "seed": seed.name,
        "variant": "lying",
        "expected": seed.lying.expected,
        "observed": result.verdict,
        "selectedSugars": result.selected_sugars,
        "ir": ir,
        "vendorConjoins": result.lift_doc.get("vendorConjoins"),
        "callEdges": result.lift_doc.get("callEdges"),
        "effects": result.lift_doc.get("effects"),
        "implications": result.lift_doc.get("implications"),
        "diagnostics": diagnostics,
        "rows": result.prove_doc.get("rows"),
    }
    print(json.dumps(trace, indent=2, sort_keys=True))

    assert result.selected_sugars == ("CallSugar",)
    assert result.verdict == "sat"
    assert len(ir) == 1
    assert ir[0]["proofirProvenance"] == {
        "kind": "proofir-provenance",
        "nodeClass": "EqualityFact",
        "constructionSite": {"path": "test_witness.py", "line": 9, "column": 4},
        "warrants": [
            {
                "kind": "Stated",
                "locus": {"path": "test_witness.py", "line": 9, "column": 4},
            }
        ],
    }
    assert result.lift_doc.get("vendorConjoins") == []
    assert result.lift_doc.get("callEdges") == []
    assert result.lift_doc.get("effects") == []
    assert result.lift_doc.get("implications") == []
    assert any(
        item.get("kind") == "dig-refusal"
        and "function universe body walker refused this body" in item.get("reason", "")
        for item in diagnostics
    )
    assert any(
        item.get("kind") == "dig-refusal"
        and "callsite floor projection refused this callee" in item.get("reason", "")
        for item in diagnostics
    )


def test_sugar_witness_non_circularity_bad_twin_names_mismatch(
    tmp_path: Path,
) -> None:
    slice_seed = next(
        seed for seed in DEFAULT_SUGAR_WITNESS_SEEDS if seed.name == "slice_callsite"
    )
    wrong_owner = replace(
        slice_seed,
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
        "non_fol_opt_out_drift": 0,
        "total": EXPECTED_UNENROLLED_SUGARS + EXPECTED_TRIPLE_FAILURES,
    }
    assert "R(unenrolled-sugars): 46" in text
    assert "R(witness-triples-failing): 1" in text
    assert "R(witnesses-not-dispatching-to-owner): 0" in text
    assert "R(non-fol-opt-out-drift): 0" in text
    assert "seed coverage: 4 seed cases, 3/53 catalog sugars" in text
    assert "AddSugar (sugar_lift_py_tests.sugar.add_sugar)" in text


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
    assert "R(unenrolled-sugars): 46" in stdout
    assert "R(witness-triples-failing): 1" in stdout
    assert "R(non-fol-opt-out-drift): 0" in stdout


def test_witness_pipeline_solver_absence_is_loud() -> None:
    with pytest.raises(WitnessPipelineError, match="no rows"):
        prove_verdict({"rows": []})
