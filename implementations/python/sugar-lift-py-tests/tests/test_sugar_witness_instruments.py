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
    temporal_opt_outs,
    unenrolled_sugars,
)
from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import ImportAliasValue, SupportValue
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing
from sugar_lift_py_tests.witness_harness import (
    WitnessPipelineError,
    prove_verdict,
    run_source_through_real_solver,
)

ROOT = Path(__file__).resolve().parents[4]
EXPECTED_UNENROLLED_SUGARS = 0
EXPECTED_SEED_CASES = 53
EXPECTED_SEED_OWNER_COUNT = 41
# #3333: display-conversion callsites must emit the derived body/floor fact so
# its lying witness leaves the S4 residue set.
EXPECTED_TRIPLE_FAILURES = 13
EXPECTED_MIGRATED_SEED_NAMES = {
    "add_method_return",
    "assign_return",
    "array_literal_map_method",
    "attribute_return",
    "aug_assign_return",
    "binop_return",
    "block_return",
    "boolop_assertion_literal",
    "builder_ctor_len_return",
    "builtin_len_return",
    "builtin_divmod_callsite",
    "builtin_hash_callsite",
    "builtin_len_callsite",
    "call_truth_assertion_boolop",
    "chained_comparison_literal",
    "comparison_assertion_boolop",
    "constant_bytes_return",
    "divmod_subscript_return",
    "format_int_return",
    "identity_assertion_boolop",
    "if_return",
    "isinstance_assertion_boolop",
    "lambda_map_method",
    "membership_assertion_boolop",
    "name_return",
    "not_assertion_boolop",
    "slice_callsite",
    "literal_call_return",
    "map_method",
    "object_call_slot_callsite",
    "object_display_conversion_callsite",
    "object_equality_return",
    "object_getitem_callsite",
    "object_next_callsite",
    "object_rich_compare_return",
    "object_rich_compare_callsite",
    "primitive_literal_return",
    "projected_equality_assertion_boolop",
    "raise_try_return",
    "slice_string_return",
    "string_subscript_return",
    "to_list_len_return",
    "try_body",
    "try_except_raise",
    "try_finally_inert",
    "try_finally_override",
    "truthy_assertion_boolop",
    "tuple_assign_return",
    "tuple_literal_subscript_return",
    "tuple_unpack_assign_return",
    "unary_op_return",
    "with_return",
}
EXPECTED_PINNED_FAILURE_SEED_NAMES = {
    "builder_ctor_len_return",
    "builtin_len_return",
    "call_truth_assertion_boolop",
    "constant_bytes_return",
    "divmod_subscript_return",
    "format_int_return",
    "isinstance_assertion_boolop",
    "object_equality_return",
    "object_rich_compare_return",
    "to_list_len_return",
    "truthy_assertion_boolop",
    "tuple_literal_subscript_return",
    "tuple_unpack_assign_return",
}
EXPECTED_OPT_OUT_SUGARS = {
    "AliasSugar",
    "AsyncForSugar",
    "AsyncWithSugar",
    "AttributeAssignSugar",
    "AttributeDeleteSugar",
    "AwaitSugar",
    "BitwiseOpSugar",
    "CommentSugar",
    "ListLiteralSugar",
    "OrdByteSugar",
    "SubscriptAssignSugar",
    "SubscriptDeleteSugar",
}
EXPECTED_TEMPORAL_OPT_OUT_SUGARS = {
    "AttributeAssignSugar",
    "AttributeDeleteSugar",
    "BitwiseOpSugar",
    "OrdByteSugar",
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
    assert by_name == {}
    assert "CallSugar" not in by_name
    assert "ReturnSugar" not in by_name
    assert "TrySugar" not in by_name
    assert "ArrayLiteralSugar" not in by_name
    assert "LambdaSugar" not in by_name
    assert "MapSugar" not in by_name
    assert "ChainedComparisonAssertionSugar" not in by_name
    assert "AddSugar" not in by_name
    assert "ProjectedEqualityAssertionSugar" not in by_name
    assert "TupleUnpackAssignSugar" not in by_name
    assert not (EXPECTED_OPT_OUT_SUGARS & set(by_name))


def test_role_gate_rejects_unenrolled_sugar_at_class_definition() -> None:
    with pytest.raises(TypeError, match="UnenrolledPlantedSugar.*witnesses"):

        class UnenrolledPlantedSugar(Sugar, role=SugarRole.TERM):
            @classmethod
            def owns(cls, fragment) -> bool:
                return False

            @classmethod
            def build(cls, fragment, ctx):
                raise AssertionError("synthetic sugar must not build")

            def desugar(self, ctx):
                raise AssertionError("synthetic sugar must not desugar")


def test_catalog_witnesses_migrate_s1_seed_surface() -> None:
    seeds = seeds_from_catalog_witnesses()
    by_name = {seed.name: seed for seed in seeds}

    assert EXPECTED_MIGRATED_SEED_NAMES <= set(by_name)
    assert EXPECTED_PINNED_FAILURE_SEED_NAMES <= set(by_name)
    assert by_name["slice_callsite"].owner_sugar == "CallSugar"
    assert by_name["literal_call_return"].owner_sugar == "ReturnSugar"
    assert by_name["try_body"].owner_sugar == "TrySugar"
    assert by_name["array_literal_map_method"].owner_sugar == "ArrayLiteralSugar"
    assert by_name["lambda_map_method"].owner_sugar == "LambdaSugar"
    assert by_name["map_method"].owner_sugar == "MapSugar"
    assert by_name["chained_comparison_literal"].owner_sugar == (
        "ChainedComparisonAssertionSugar"
    )


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


def test_non_fol_opt_outs_are_owned_by_registered_sugars() -> None:
    claims = {claim.name: claim for claim in default_catalog().claims}

    for expected in EXPECTED_NON_FOL_OPT_OUTS:
        witness = claims[expected.sugar_name].witnesses()
        assert witness == NotVerdictBearing(
            sugar_name=expected.sugar_name,
            floor_name=expected.floor_name,
            reason=expected.reason,
        )


def test_non_fol_opt_out_audit_bad_twins() -> None:
    missing_support_pin = tuple(
        row for row in EXPECTED_NON_FOL_OPT_OUTS if row.floor_name != "SupportValue"
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
        witnesses=lambda: NotVerdictBearing(
            sugar_name="SocialOptOutSugar",
            floor_name="SupportValue",
            reason="social opt-out flag is not a typed floor-backed pin",
        ),
    )

    assert claim_has_witness_or_opt_out(claim) is False


def test_temporal_opt_outs_are_pinned_as_retirable_deferrals() -> None:
    rows = temporal_opt_outs()

    assert {row.sugar_name for row in rows} == EXPECTED_TEMPORAL_OPT_OUT_SUGARS
    assert len(rows) == 4
    assert all(row.retirement_condition for row in rows)
    assert {
        row.sugar_name
        for row in EXPECTED_NON_FOL_OPT_OUTS
        if row.retirement_condition is None
    } == EXPECTED_OPT_OUT_SUGARS - EXPECTED_TEMPORAL_OPT_OUT_SUGARS


def test_sugar_witness_seed_triples_hit_real_solver(seed_report) -> None:
    assert seed_report.seed_count == EXPECTED_SEED_CASES
    assert seed_report.unique_owner_count == EXPECTED_SEED_OWNER_COUNT
    assert seed_report.catalog_count == 53
    assert seed_report.witness_triples_failing == EXPECTED_TRIPLE_FAILURES
    assert seed_report.witnesses_not_dispatching_to_owner == 0
    assert [
        (
            failure.seed,
            failure.variant,
            failure.axis,
            failure.expected,
            failure.observed,
        )
        for failure in seed_report.triple_failures
    ] == [
        ("builder_ctor_len_return", "lying", "verdict", "unsat", "sat"),
        ("builtin_len_return", "lying", "verdict", "unsat", "sat"),
        ("call_truth_assertion_boolop", "lying", "verdict", "unsat", "sat"),
        ("constant_bytes_return", "lying", "verdict", "unsat", "sat"),
        ("divmod_subscript_return", "lying", "verdict", "unsat", "sat"),
        ("format_int_return", "lying", "verdict", "unsat", "sat"),
        ("isinstance_assertion_boolop", "lying", "verdict", "unsat", "sat"),
        ("object_equality_return", "lying", "verdict", "unsat", "sat"),
        ("object_rich_compare_return", "lying", "verdict", "unsat", "sat"),
        ("to_list_len_return", "lying", "verdict", "unsat", "sat"),
        ("truthy_assertion_boolop", "lying", "verdict", "unsat", "sat"),
        ("tuple_literal_subscript_return", "lying", "verdict", "unsat", "sat"),
        ("tuple_unpack_assign_return", "lying", "verdict", "unsat", "sat"),
    ]
    assert seed_report.non_circularity_failures == ()


def test_binary_dunder_trace_emits_derived_fact_and_refutes_lie(
    tmp_path: Path,
) -> None:
    seed = next(
        item
        for item in DEFAULT_SUGAR_WITNESS_SEEDS
        if item.name == "binary_dunder_callsite"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", seed.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", seed.lying.source)

    trace = {
        "seed": seed.name,
        "truthful": {
            "expected": seed.truthful.expected,
            "observed": truthful.verdict,
            "selectedSugars": truthful.selected_sugars,
            "ir": _binary_dunder_euf_rows(truthful.lift_doc),
            "rows": truthful.prove_doc.get("rows"),
        },
        "lying": {
            "expected": seed.lying.expected,
            "observed": lying.verdict,
            "selectedSugars": lying.selected_sugars,
            "ir": _binary_dunder_euf_rows(lying.lift_doc),
            "rows": lying.prove_doc.get("rows"),
        },
    }
    print(json.dumps(trace, indent=2, sort_keys=True))

    assert "CallSugar" in truthful.selected_sugars
    assert truthful.verdict == "sat"
    truthful_rows = _binary_dunder_euf_rows(truthful.lift_doc)
    assert len(truthful_rows) == 1
    assert _euf_rhs_values(truthful_rows) == [20]
    assert _warrant_kinds(truthful_rows[0]) == {"Stated", "Derived"}

    assert "CallSugar" in lying.selected_sugars
    assert lying.verdict == "unsat"
    lying_rows = _binary_dunder_euf_rows(lying.lift_doc)
    assert len(lying_rows) == 2
    assert _euf_rhs_values(lying_rows) == [10, 20]
    assert {_euf_rhs_value(row): _warrant_kinds(row) for row in lying_rows} == {
        10: {"Stated"},
        20: {"Derived"},
    }


def test_effectful_binary_dunder_body_refuses_without_fabricated_derived_fact(
    tmp_path: Path,
) -> None:
    source = (
        "class X:\n"
        "    def __init__(self, y):\n"
        "        self.x = y\n"
        "    def __add__(self, other):\n"
        "        print(other.x)\n"
        "        return other.x\n"
        "def A():\n"
        "    return [10, 20, 30][X(0) + X(1)]\n"
        "def test_a():\n"
        "    assert A() == 10\n"
    )

    result = run_source_through_real_solver(tmp_path / "effectful", source)
    trace = {
        "variant": "effectful-dunder",
        "observed": result.verdict,
        "ir": _binary_dunder_euf_rows(result.lift_doc),
        "diagnostics": result.lift_doc["diagnostics"],
        "rows": result.prove_doc.get("rows"),
    }
    print(json.dumps(trace, indent=2, sort_keys=True))

    rows = _binary_dunder_euf_rows(result.lift_doc)
    assert len(rows) == 1
    assert _warrant_kinds(rows[0]) == {"Stated"}
    assert any(
        item.get("kind") == "dig-refusal"
        and "callsite floor projection refused this callee" in item.get("reason", "")
        for item in result.lift_doc["diagnostics"]
    )


def test_display_conversion_trace_emits_derived_fact_and_refutes_lie(
    tmp_path: Path,
) -> None:
    seed = next(
        item
        for item in DEFAULT_SUGAR_WITNESS_SEEDS
        if item.name == "object_display_conversion_callsite"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", seed.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", seed.lying.source)

    trace = {
        "seed": seed.name,
        "truthful": {
            "expected": seed.truthful.expected,
            "observed": truthful.verdict,
            "selectedSugars": truthful.selected_sugars,
            "ir": _euf_rows(truthful.lift_doc),
            "rows": truthful.prove_doc.get("rows"),
        },
        "lying": {
            "expected": seed.lying.expected,
            "observed": lying.verdict,
            "selectedSugars": lying.selected_sugars,
            "ir": _euf_rows(lying.lift_doc),
            "rows": lying.prove_doc.get("rows"),
        },
    }
    print(json.dumps(trace, indent=2, sort_keys=True))

    assert "CallSugar" in truthful.selected_sugars
    assert truthful.verdict == "sat"
    truthful_rows = _euf_rows(truthful.lift_doc)
    assert len(truthful_rows) == 1
    assert _euf_rhs_values(truthful_rows) == [20]
    assert _warrant_kinds(truthful_rows[0]) == {"Stated", "Derived"}

    assert "CallSugar" in lying.selected_sugars
    assert lying.verdict == "unsat"
    lying_rows = _euf_rows(lying.lift_doc)
    assert len(lying_rows) == 2
    assert _euf_rhs_values(lying_rows) == [10, 20]
    assert {_euf_rhs_value(row): _warrant_kinds(row) for row in lying_rows} == {
        10: {"Stated"},
        20: {"Derived"},
    }


def test_effectful_display_conversion_refuses_without_fabricated_derived_fact(
    tmp_path: Path,
) -> None:
    source = (
        "class Box:\n"
        "    def __repr__(self):\n"
        "        print('side effect')\n"
        "        return 'one'\n"
        "def A():\n"
        "    return [10, 20, 30][repr(Box()) == 'one']\n"
        "def test_a():\n"
        "    assert A() == 20\n"
    )

    result = run_source_through_real_solver(tmp_path / "effectful-display", source)
    trace = {
        "variant": "effectful-display-conversion",
        "observed": result.verdict,
        "ir": _euf_rows(result.lift_doc),
        "diagnostics": result.lift_doc["diagnostics"],
        "rows": result.prove_doc.get("rows"),
    }
    print(json.dumps(trace, indent=2, sort_keys=True))

    rows = _euf_rows(result.lift_doc)
    assert len(rows) == 1
    assert _warrant_kinds(rows[0]) == {"Stated"}
    assert any(
        item.get("kind") == "dig-refusal"
        and "callsite floor projection refused this callee" in item.get("reason", "")
        for item in result.lift_doc["diagnostics"]
    )


def _binary_dunder_euf_rows(lift_doc: dict) -> list[dict]:
    return _euf_rows(lift_doc)


def _euf_rows(lift_doc: dict) -> list[dict]:
    return [
        row
        for row in lift_doc["ir"]
        if isinstance(row, dict) and row.get("name") == "A#euf#c:call:A()::assertion"
    ]


def _warrant_kinds(row: dict) -> set[str]:
    return {warrant["kind"] for warrant in row["proofirProvenance"]["warrants"]}


def _euf_rhs_values(rows: list[dict]) -> list[int]:
    return sorted(_euf_rhs_value(row) for row in rows)


def _euf_rhs_value(row: dict) -> int:
    return row["inv"]["args"][1]["value"]


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
    assert "CallSugar" in mismatch.selected_sugars
    assert "TrySugar" not in mismatch.selected_sugars
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
        "temporal_opt_outs": len(EXPECTED_TEMPORAL_OPT_OUT_SUGARS),
        "total": EXPECTED_UNENROLLED_SUGARS
        + EXPECTED_TRIPLE_FAILURES
        + len(EXPECTED_TEMPORAL_OPT_OUT_SUGARS),
    }
    assert "R(unenrolled-sugars): 0" in text
    assert "R(witness-triples-failing): 13" in text
    assert "R(witnesses-not-dispatching-to-owner): 0" in text
    assert "R(non-fol-opt-out-drift): 0" in text
    assert "R(temporal-opt-outs): 4" in text
    assert "seed coverage: 53 seed cases, 41/53 catalog sugars" in text
    assert "unenrolled sugars:" not in text
    assert "temporal opt-outs:" in text


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
    assert "R(unenrolled-sugars): 0" in stdout
    assert "R(witness-triples-failing): 13" in stdout
    assert "R(non-fol-opt-out-drift): 0" in stdout
    assert "R(temporal-opt-outs): 4" in stdout


def test_witness_pipeline_solver_absence_is_loud() -> None:
    with pytest.raises(WitnessPipelineError, match="no rows"):
        prove_verdict({"rows": []})
