from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from sugar_lift_py_tests.idd import sugar_witness_instruments
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
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    DictLiteralValue,
    ImportAliasValue,
    SetLiteralValue,
    SupportValue,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import (
    EffectWitnessSource,
    NotVerdictBearing,
    SugarRedEffectWitnessPair,
    SugarWitnessPair,
    TypedRedEffectExpectation,
    WitnessSource,
)
from sugar_lift_py_tests.witness_harness import (
    WitnessPipelineResult,
    WitnessPipelineError,
    _stage_cli_project,
    prove_verdict,
    run_lift_rpc,
    run_source_through_real_solver,
)

ROOT = Path(__file__).resolve().parents[4]
EXPECTED_UNENROLLED_SUGARS = 0
EXPECTED_SEED_CASES = 58
EXPECTED_SEED_OWNER_COUNT = 43
EXPECTED_TRIPLE_FAILURES = 0
EXPECTED_MIGRATED_SEED_NAMES = {
    "add_method_return",
    "assign_return",
    "array_literal_map_method",
    "attribute_assign_post_state_read",
    "attribute_delete_post_state_read",
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
    "joined_str_literal_return",
    "lambda_map_method",
    "list_comp_literal_domain_return",
    "membership_assertion_boolop",
    "name_return",
    "not_assertion_boolop",
    "slice_callsite",
    "literal_call_return",
    "map_method",
    "object_call_slot_callsite",
    "object_display_conversion_callsite",
    "object_equality_identity_return",
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
    "async_for_runtime_effect",
    "async_with_runtime_effect",
    "await_runtime_effect",
    "boolop_runtime_effect",
    "for_runtime_effect",
    "starred_runtime_effect",
}
EXPECTED_PINNED_FAILURE_SEED_NAMES: set[str] = set()
EXPECTED_OPT_OUT_SUGARS = {
    "AliasSugar",
    "BitwiseOpSugar",
    "CommentSugar",
    "DictCompSugar",
    "DictSugar",
    "ExprSugar",
    "ListLiteralSugar",
    "OrdByteSugar",
    "PassSugar",
    "SetCompSugar",
    "SetSugar",
    "SubscriptAssignSugar",
    "SubscriptDeleteSugar",
}
EXPECTED_TEMPORAL_OPT_OUT_SUGARS = {
    "AliasSugar",
    "BitwiseOpSugar",
    "DictSugar",
    "ListLiteralSugar",
    "OrdByteSugar",
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
    assert DictLiteralValue.non_fol_support is True
    assert current_non_fol_support_floor_names() == {
        "SupportValue",
        "ImportAliasValue",
        "DictLiteralValue",
        "SetLiteralValue",
    }
    assert SetLiteralValue.non_fol_support is True

    audit = non_fol_opt_out_audit()

    assert audit.is_zero
    assert {row.sugar_name for row in EXPECTED_NON_FOL_OPT_OUTS} == (
        EXPECTED_OPT_OUT_SUGARS
    )


def test_non_fol_opt_outs_are_owned_by_registered_sugars() -> None:
    claims = {claim.name: claim for claim in default_catalog().claims}

    for expected in EXPECTED_NON_FOL_OPT_OUTS:
        witness = claims[expected.sugar_name].witnesses()
        assert _not_verdict_marker(witness) == NotVerdictBearing(
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


def _not_verdict_marker(witness) -> NotVerdictBearing | None:
    if isinstance(witness, NotVerdictBearing):
        return witness
    if isinstance(witness, tuple):
        for item in witness:
            if isinstance(item, NotVerdictBearing):
                return item
    return None


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


def test_no_temporal_opt_out_deferrals() -> None:
    # IDD invariant: a temporal opt-out is debt, not a ledger to maintain. Every
    # sugar must carry a real witness or an honest refusal; a deferral — however
    # documented its retirement condition — is an unmet gap. Red until zero
    # sugars defer. Pinning "there are exactly 5 retirable deferrals" was the
    # green badge on that debt.
    assert temporal_opt_outs() == []


def test_temporal_opt_out_register_names_current_blockers() -> None:
    rows = temporal_opt_outs()

    assert {row.sugar_name for row in rows} == EXPECTED_TEMPORAL_OPT_OUT_SUGARS
    assert len(rows) == 7
    assert all(row.retirement_condition for row in rows)
    by_name = {row.sugar_name: row for row in rows}
    expected_needles = {
        "AliasSugar": "factory/literal_call_report.py:304",
        "BitwiseOpSugar": "prove reports undecidable",
        "DictSugar": "DictLiteralValue.project_callsite_with",
        "ListLiteralSugar": "sugar/array_literal_sugar.py:29",
        "OrdByteSugar": "illegal free var byte_s_0",
        "SubscriptAssignSugar": "array mutation probes refuse at setitem_with",
        "SubscriptDeleteSugar": "deletion-state probes still reduce",
    }
    for sugar_name, needle in expected_needles.items():
        assert needle in by_name[sugar_name].retirement_condition


def test_owner_selection_gap_rows_cite_excluding_code() -> None:
    rows = {row.sugar_name: row for row in temporal_opt_outs()}

    alias_condition = rows["AliasSugar"].retirement_condition
    assert alias_condition is not None
    assert "factory/build.py:87" in alias_condition
    assert "factory/literal_call_report.py:304" in alias_condition
    assert "sugar/alias_sugar.py:18" in alias_condition

    list_condition = rows["ListLiteralSugar"].retirement_condition
    assert list_condition is not None
    assert "claim/sugar_catalog.py:15" in list_condition
    assert "factory/build.py:174" in list_condition
    assert "sugar/array_literal_sugar.py:29" in list_condition
    assert "sugar/list_literal_sugar.py:28" in list_condition


def test_owner_selection_gap_is_not_missing_enrollment() -> None:
    catalog = default_catalog()
    claim_names = {claim.name for claim in catalog.claims}
    assert {"AliasSugar", "ArrayLiteralSugar", "ListLiteralSugar"} <= claim_names

    alias_site = next(
        site
        for site in SourceFragment.from_source(
            "import numpy as np\n", "probe.py"
        ).walk()
        if site.observed == "alias"
    )
    alias_result = build_node(
        alias_site,
        filename="probe.py",
        role=SugarRole.TERM,
        catalog=catalog,
    )
    assert alias_result.audit_row.selected == "AliasSugar"

    list_site = next(
        site
        for site in SourceFragment.from_source("[1, 2, 3]\n", "probe.py").walk()
        if site.observed == "List"
    )
    list_candidates = [
        candidate.name
        for candidate in catalog.candidates_for(SugarRole.TERM, list_site)
    ]
    assert "ArrayLiteralSugar" in list_candidates
    assert "ListLiteralSugar" in list_candidates
    list_result = build_node(
        list_site,
        filename="probe.py",
        role=SugarRole.TERM,
        catalog=catalog,
    )
    assert list_result.audit_row.selected == "ArrayLiteralSugar"


def test_alias_temporal_opt_out_reproduces_resolver_metadata_owner_blocker(
    tmp_path: Path,
) -> None:
    truthful = (
        "import numpy as np\n"
        "\n"
        "def test_alias_backed_call():\n"
        "    assert np.add(2, 3) == 5\n"
    )
    lying = truthful.replace("== 5", "== 6")

    truthful_result = run_source_through_real_solver(tmp_path / "alias-truth", truthful)
    lying_result = run_source_through_real_solver(tmp_path / "alias-lie", lying)

    assert truthful_result.verdict == "sat"
    assert lying_result.verdict == "unsat"
    assert "CallSugar" in truthful_result.selected_sugars
    assert "PrimitiveLiteralSugar" in truthful_result.selected_sugars
    assert "AliasSugar" not in truthful_result.selected_sugars
    assert "AliasSugar" not in lying_result.selected_sugars


def test_list_literal_temporal_opt_out_reproduces_shadowed_owner_blocker(
    tmp_path: Path,
) -> None:
    truthful = (
        "def A():\n"
        "    return len([1, 2, 3])\n"
        "\n"
        "def test_list_literal():\n"
        "    assert A() == 3\n"
    )
    lying = truthful.replace("== 3", "== 2")

    truthful_result = run_source_through_real_solver(tmp_path / "list-truth", truthful)
    lying_result = run_source_through_real_solver(tmp_path / "list-lie", lying)

    assert truthful_result.verdict == "sat"
    assert lying_result.verdict == "unsat"
    assert "ArrayLiteralSugar" in truthful_result.selected_sugars
    assert "BuiltinCallSugar" in truthful_result.selected_sugars
    assert "ListLiteralSugar" not in truthful_result.selected_sugars
    assert "ListLiteralSugar" not in lying_result.selected_sugars


def test_typed_red_effect_witness_accepts_right_red_and_rejects_wrong_red(
    tmp_path: Path,
) -> None:
    source = "def A(z):\n    return z and 2\n"
    right_effect = TypedRedEffectExpectation(
        effect_class="RuntimeEffect",
        reason_needle="boolean expression runtime boundary",
        blame_needle="test_witness.py:2:11",
    )
    wrong_effect = TypedRedEffectExpectation(
        effect_class="RuntimeEffect",
        reason_needle="starred expression runtime boundary",
        blame_needle="test_witness.py:2:11",
    )
    seed = SugarRedEffectWitnessPair(
        name="planted_boolop_runtime_effect",
        owner_sugar="BoolOpSugar",
        family="typed-red-effect",
        truthful=EffectWitnessSource(
            source=source,
            expectation=right_effect,
            expected_match=True,
        ),
        lying=EffectWitnessSource(
            source=source,
            expectation=wrong_effect,
            expected_match=False,
        ),
    )

    report = evaluate_seed_witnesses((seed,), tmp_path / "right-red")

    assert report.is_zero

    wrong_truth = replace(
        seed,
        truthful=replace(seed.truthful, expectation=wrong_effect, expected_match=True),
    )
    bad_report = evaluate_seed_witnesses((wrong_truth,), tmp_path / "wrong-red")

    assert bad_report.witness_triples_failing == 1
    assert [
        (failure.seed, failure.variant, failure.axis)
        for failure in bad_report.triple_failures
    ] == [("planted_boolop_runtime_effect", "truthful", "typed-red-effect")]


def _fake_witness_result(
    *, selected: tuple[str, ...], verdict: str
) -> WitnessPipelineResult:
    status = "discharged" if verdict == "sat" else "unsatisfied"
    return WitnessPipelineResult(
        lift_doc={
            "factoryAuditSummary": {
                "factoryWalk": [{"selected": sugar} for sugar in selected]
            },
            "ir": [{"kind": "fake"}],
        },
        prove_doc={"rows": [{"status": status}]},
    )


def _synthetic_seed(name: str, owner: str) -> SugarWitnessPair:
    return SugarWitnessPair(
        name=name,
        owner_sugar=owner,
        family="parallel-seed-test",
        truthful=WitnessSource(source=f"# {name} truthful", expected="sat"),
        lying=WitnessSource(source=f"# {name} lying", expected="unsat"),
    )


def test_evaluate_seed_witnesses_runs_seed_pairs_in_parallel_and_collates_by_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SUGAR_WITNESS_WORKERS", "3")
    monkeypatch.setattr(
        sugar_witness_instruments,
        "ensure_sugar_bin",
        lambda: Path("fake-sugar"),
    )
    seeds = (
        _synthetic_seed("zeta", "ZetaSugar"),
        _synthetic_seed("alpha", "AlphaSugar"),
        _synthetic_seed("middle", "MiddleSugar"),
    )
    active_total = 0
    active_by_seed: dict[str, int] = {}
    max_active_total = 0
    max_active_same_seed = 0
    lock = threading.Lock()

    def fake_run(project: Path, source: str) -> WitnessPipelineResult:
        nonlocal active_total, max_active_total, max_active_same_seed
        seed_name = project.parent.name
        variant = project.name
        with lock:
            active_total += 1
            active_by_seed[seed_name] = active_by_seed.get(seed_name, 0) + 1
            max_active_total = max(max_active_total, active_total)
            max_active_same_seed = max(max_active_same_seed, active_by_seed[seed_name])
        try:
            time.sleep({"zeta": 0.06, "alpha": 0.02, "middle": 0.04}[seed_name])
            expected = "sat" if variant == "truthful" else "unsat"
            return _fake_witness_result(selected=("<wrong-owner>",), verdict=expected)
        finally:
            with lock:
                active_total -= 1
                active_by_seed[seed_name] -= 1

    monkeypatch.setattr(
        sugar_witness_instruments,
        "run_source_through_real_solver",
        fake_run,
    )

    report = evaluate_seed_witnesses(seeds, tmp_path, catalog_count=len(seeds))

    assert max_active_total > 1
    assert max_active_same_seed == 1
    assert [
        (failure.seed, failure.variant, failure.axis)
        for failure in report.triple_failures
    ] == [
        ("alpha", "truthful", "sugar-fired"),
        ("alpha", "lying", "sugar-fired"),
        ("middle", "truthful", "sugar-fired"),
        ("middle", "lying", "sugar-fired"),
        ("zeta", "truthful", "sugar-fired"),
        ("zeta", "lying", "sugar-fired"),
    ]


def test_evaluate_seed_witness_parallel_report_matches_serial_for_planted_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        sugar_witness_instruments,
        "ensure_sugar_bin",
        lambda: Path("fake-sugar"),
    )
    seeds = (
        _synthetic_seed("beta", "BetaSugar"),
        _synthetic_seed("alpha", "AlphaSugar"),
    )

    def fake_run(project: Path, source: str) -> WitnessPipelineResult:
        selected = (
            ("<wrong-owner>",)
            if project.parent.name == "alpha"
            else (f"{project.parent.name.capitalize()}Sugar",)
        )
        expected = "sat" if project.name == "truthful" else "unsat"
        return _fake_witness_result(selected=selected, verdict=expected)

    monkeypatch.setattr(
        sugar_witness_instruments,
        "run_source_through_real_solver",
        fake_run,
    )

    monkeypatch.setenv("SUGAR_WITNESS_WORKERS", "1")
    serial = evaluate_seed_witnesses(
        seeds,
        tmp_path / "serial",
        catalog_count=len(seeds),
    )
    monkeypatch.setenv("SUGAR_WITNESS_WORKERS", "3")
    parallel = evaluate_seed_witnesses(
        seeds,
        tmp_path / "parallel",
        catalog_count=len(seeds),
    )

    assert serial.to_json() == parallel.to_json()
    assert [
        (failure.seed, failure.variant, failure.axis)
        for failure in parallel.triple_failures
    ] == [
        ("alpha", "truthful", "sugar-fired"),
        ("alpha", "lying", "sugar-fired"),
    ]


def test_evaluate_seed_witness_worker_crash_names_seed_and_variant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SUGAR_WITNESS_WORKERS", "2")
    monkeypatch.setattr(
        sugar_witness_instruments,
        "ensure_sugar_bin",
        lambda: Path("fake-sugar"),
    )
    seeds = (
        _synthetic_seed("ok", "OkSugar"),
        _synthetic_seed("bad", "BadSugar"),
    )

    def fake_run(project: Path, source: str) -> WitnessPipelineResult:
        if project.parent.name == "bad" and project.name == "truthful":
            raise RuntimeError("boom from fake worker")
        expected = "sat" if project.name == "truthful" else "unsat"
        return _fake_witness_result(selected=(project.parent.name,), verdict=expected)

    monkeypatch.setattr(
        sugar_witness_instruments,
        "run_source_through_real_solver",
        fake_run,
    )

    with pytest.raises(
        RuntimeError,
        match=("seed=bad.*variant=truthful.*owner=BadSugar.*" "boom from fake worker"),
    ):
        evaluate_seed_witnesses(seeds, tmp_path, catalog_count=len(seeds))


def test_sugar_witness_seed_triples_hit_real_solver(seed_report) -> None:
    # IDD invariant: seed coverage is a canceling pair, not a pinned magnitude.
    # Every catalog sugar must own a seed case — (catalog - seed-covered) == 0.
    # This self-updates (a 58th sugar raises both sides) and is red until full
    # coverage. Pinning seed_count / catalog_count == 57 asserted nothing about
    # correctness and forced a hand-edit on every catalog change.
    assert seed_report.catalog_count - seed_report.unique_owner_count == 0
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
    ] == []
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
        "statuses": [row.get("status") for row in result.prove_doc.get("rows", [])],
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
        "statuses": [row.get("status") for row in result.prove_doc.get("rows", [])],
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


@pytest.mark.parametrize(
    ("seed_name", "truthful_rhs", "lying_rhs"),
    [
        ("builder_ctor_len_return", 1, 2),
        ("builtin_len_return", 3, 2),
        ("constant_bytes_return", ("python:bytes", "78"), ("python:bytes", "79")),
        ("divmod_subscript_return", 2, 3),
        ("format_int_return", 5, 6),
        ("object_equality_identity_return", False, True),
        ("object_equality_return", True, False),
        ("object_rich_compare_return", True, False),
        ("to_list_len_return", 2, 3),
        ("tuple_literal_subscript_return", 2, 3),
        ("tuple_unpack_assign_return", 2, 1),
    ],
)
def test_literal_call_residue_rows_emit_derived_fact_and_refute_lie(
    tmp_path: Path,
    seed_name: str,
    truthful_rhs: object,
    lying_rhs: object,
) -> None:
    seed = next(item for item in DEFAULT_SUGAR_WITNESS_SEEDS if item.name == seed_name)

    truthful = run_source_through_real_solver(
        tmp_path / f"{seed_name}-truthful", seed.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / f"{seed_name}-lying", seed.lying.source
    )

    trace = {
        "seed": seed.name,
        "truthful": {
            "expected": seed.truthful.expected,
            "observed": truthful.verdict,
            "selectedSugars": truthful.selected_sugars,
            "ir": _a_callsite_euf_rows(truthful.lift_doc),
            "diagnostics": truthful.lift_doc["diagnostics"],
            "rows": truthful.prove_doc.get("rows"),
        },
        "lying": {
            "expected": seed.lying.expected,
            "observed": lying.verdict,
            "selectedSugars": lying.selected_sugars,
            "ir": _a_callsite_euf_rows(lying.lift_doc),
            "diagnostics": lying.lift_doc["diagnostics"],
            "rows": lying.prove_doc.get("rows"),
        },
    }
    print(json.dumps(trace, indent=2, sort_keys=True))

    assert truthful.verdict == "sat"
    truthful_rows = _a_callsite_euf_rows(truthful.lift_doc)
    truthful_value_rows = [
        row for row in truthful_rows if _euf_rhs_fingerprint(row) == truthful_rhs
    ]
    assert len(truthful_value_rows) == 1
    assert _warrant_kinds(truthful_value_rows[0]) == {"Stated", "Derived"}

    assert lying.verdict == "unsat"
    lying_rows = _a_callsite_euf_rows(lying.lift_doc)
    lying_value_rows = [
        row
        for row in lying_rows
        if _euf_rhs_fingerprint(row) in {truthful_rhs, lying_rhs}
    ]
    assert len(lying_value_rows) == 2
    assert {
        _euf_rhs_fingerprint(row): _warrant_kinds(row) for row in lying_value_rows
    } == {
        truthful_rhs: {"Derived"},
        lying_rhs: {"Stated"},
    }


@pytest.mark.parametrize(
    "seed_name",
    ["truthy_assertion_boolop", "isinstance_assertion_boolop"],
)
def test_boolop_literal_residue_lie_lowers_to_concrete_false_operand(
    tmp_path: Path,
    seed_name: str,
) -> None:
    seed = next(item for item in DEFAULT_SUGAR_WITNESS_SEEDS if item.name == seed_name)
    project = tmp_path / seed_name
    _stage_cli_project(project, seed.lying.source)

    lift_doc = run_lift_rpc(project)
    assertion = _single_assertion_contract(lift_doc)
    trace = {
        "seed": seed_name,
        "assertion": assertion,
        "diagnostics": lift_doc["diagnostics"],
    }
    print(json.dumps(trace, indent=2, sort_keys=True))

    assert _formula_contains_eq_value(assertion["inv"], False, True)


def test_call_truth_boolop_residue_emits_local_call_derived_fact(
    tmp_path: Path,
) -> None:
    seed = next(
        item
        for item in DEFAULT_SUGAR_WITNESS_SEEDS
        if item.name == "call_truth_assertion_boolop"
    )
    project = tmp_path / "call_truth_assertion_boolop"
    _stage_cli_project(project, seed.lying.source)

    lift_doc = run_lift_rpc(project)
    assertion = _single_assertion_contract(lift_doc)
    rows = _a_callsite_euf_rows(lift_doc)
    trace = {
        "seed": seed.name,
        "assertion": assertion,
        "ir": rows,
        "diagnostics": lift_doc["diagnostics"],
    }
    print(json.dumps(trace, indent=2, sort_keys=True))

    assert _formula_contains_call_truth(assertion["inv"], "call:A", 2)
    assert len(rows) == 1
    assert _euf_rhs_fingerprint(rows[0]) is False
    assert _warrant_kinds(rows[0]) == {"Derived"}


def _binary_dunder_euf_rows(lift_doc: dict) -> list[dict]:
    return _euf_rows(lift_doc)


def _euf_rows(lift_doc: dict) -> list[dict]:
    return [
        row
        for row in lift_doc["ir"]
        if isinstance(row, dict) and row.get("name") == "A#euf#c:call:A()::assertion"
    ]


def _a_callsite_euf_rows(lift_doc: dict) -> list[dict]:
    return [
        row
        for row in lift_doc["ir"]
        if isinstance(row, dict)
        and row.get("name", "").startswith("A#euf#c:call:A(")
        and row.get("name", "").endswith("::assertion")
    ]


def _warrant_kinds(row: dict) -> set[str]:
    return {warrant["kind"] for warrant in row["proofirProvenance"]["warrants"]}


def _euf_rhs_values(rows: list[dict]) -> list[int]:
    return sorted(_euf_rhs_value(row) for row in rows)


def _euf_rhs_value(row: dict) -> int:
    return row["inv"]["args"][1]["value"]


def _euf_rhs_fingerprint(row: dict) -> object:
    rhs = row["inv"]["args"][1]
    if rhs.get("kind") == "const":
        return rhs["value"]
    if rhs.get("kind") == "ctor":
        args = rhs.get("args", ())
        if rhs.get("name") == "python:bytes" and len(args) == 1:
            return ("python:bytes", args[0]["value"])
        return (rhs.get("name"), tuple(json.dumps(arg, sort_keys=True) for arg in args))
    return json.dumps(rhs, sort_keys=True)


def _single_assertion_contract(lift_doc: dict) -> dict:
    rows = [
        row
        for row in lift_doc["ir"]
        if isinstance(row, dict)
        and row.get("kind") == "contract"
        and row.get("name", "").startswith("test_witness::test_a::assert:")
    ]
    assert len(rows) == 1
    return rows[0]


def _formula_contains_eq_value(formula: dict, left: object, right: object) -> bool:
    if formula.get("kind") == "atomic" and formula.get("name") == "=":
        args = formula.get("args", ())
        return len(args) == 2 and [arg.get("value") for arg in args] == [left, right]
    return any(
        isinstance(operand, dict) and _formula_contains_eq_value(operand, left, right)
        for operand in formula.get("operands", ())
    )


def _formula_contains_call_truth(formula: dict, callee_name: str, arg: int) -> bool:
    if formula.get("kind") == "atomic" and formula.get("name") == "=":
        args = formula.get("args", ())
        if len(args) != 2:
            return False
        call, truth = args
        return (
            call.get("kind") == "ctor"
            and call.get("name") == callee_name
            and call.get("args")
            == [
                {
                    "kind": "const",
                    "sort": {"kind": "primitive", "name": "Int"},
                    "value": arg,
                }
            ]
            and truth
            == {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Bool"},
                "value": True,
            }
        )
    return any(
        isinstance(operand, dict)
        and _formula_contains_call_truth(operand, callee_name, arg)
        for operand in formula.get("operands", ())
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
        "temporal_opt_outs": 7,
        "total": 7,
    }
    assert "R(unenrolled-sugars): 0" in text
    assert "R(witness-triples-failing): 0" in text
    assert "R(witnesses-not-dispatching-to-owner): 0" in text
    assert "R(non-fol-opt-out-drift): 0" in text
    assert "R(temporal-opt-outs): 7" in text
    assert "unenrolled sugars:" not in text


def test_sugar_witness_cli_exits_clean_only_when_residue_is_zero(
    seed_report,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    report = collect_sugar_witness_frontier(ROOT, seed_report=seed_report)
    monkeypatch.setattr(cli, "collect_sugar_witness_frontier", lambda root: report)

    status = cli.main(["--root", str(ROOT), "--sugar-witness-frontier"])

    # IDD invariant: the frontier exits clean only when every residue is zero.
    # Red until the temporal-opt-out debt is actually retired — not pinned at 5.
    stdout = capsys.readouterr().out
    assert "R(unenrolled-sugars): 0" in stdout
    assert "R(witness-triples-failing): 0" in stdout
    assert "R(non-fol-opt-out-drift): 0" in stdout
    assert "R(temporal-opt-outs): 7" in stdout
    assert status == 1


def test_witness_pipeline_solver_absence_is_loud() -> None:
    with pytest.raises(WitnessPipelineError, match="no rows"):
        prove_verdict({"rows": []})
