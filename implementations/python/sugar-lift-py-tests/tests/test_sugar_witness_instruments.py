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
    LoopControlValue,
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
    mint_and_prove,
    prove_verdict,
    run_lift_rpc,
    run_source_through_real_solver,
)

ROOT = Path(__file__).resolve().parents[4]
EXPECTED_UNENROLLED_SUGARS = 0
EXPECTED_SEED_CASES = 61
EXPECTED_SEED_OWNER_COUNT = 43
EXPECTED_TRIPLE_FAILURES = 0
EXPECTED_MIGRATED_SEED_NAMES = {
    "add_method_return",
    "callsite_add_dig_return",
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
    "subscript_assign_post_state_read",
    "subscript_delete_post_state_read",
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
    "BreakSugar",
    "ContinueSugar",
    "ExprSugar",
    "PassSugar",
}
EXPECTED_TEMPORAL_OPT_OUT_SUGARS: set[str] = set()


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

            def desugar(self, ctx=None):
                raise AssertionError("synthetic sugar must not desugar")


def test_catalog_witnesses_migrate_s1_seed_surface() -> None:
    seeds = seeds_from_catalog_witnesses()

    assert seeds == DEFAULT_SUGAR_WITNESS_SEEDS
    assert all(seed.owner_sugar for seed in seeds)
    assert len(seeds) >= len({seed.owner_sugar for seed in seeds})


def test_non_fol_opt_out_is_floor_anchored_and_bidirectional() -> None:
    assert SupportValue.non_fol_support is True
    assert ImportAliasValue.non_fol_support is False
    assert DictLiteralValue.non_fol_support is False
    assert LoopControlValue.non_fol_support is True
    assert current_non_fol_support_floor_names() == {
        "SupportValue",
        "LoopControlValue",
    }
    assert SetLiteralValue.non_fol_support is False

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
        new=SocialOptOutOwner.build,
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
    assert temporal_opt_outs() == ()


def test_temporal_opt_out_register_names_current_blockers() -> None:
    rows = temporal_opt_outs()

    assert {row.sugar_name for row in rows} == EXPECTED_TEMPORAL_OPT_OUT_SUGARS
    assert len(rows) == 0


def test_register_to_zero_dispatch_surfaces_are_not_missing_enrollment() -> None:
    catalog = default_catalog()
    claim_names = {claim.name for claim in catalog.claims}
    assert {"AliasSugar", "ListLiteralSugar", "DictLiteralSugar"} <= claim_names

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
    assert list_candidates == ["ListLiteralSugar"]
    list_result = build_node(
        list_site,
        filename="probe.py",
        role=SugarRole.TERM,
        catalog=catalog,
    )
    assert list_result.audit_row.selected == "ListLiteralSugar"


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
    assert truthful_result.lift_doc["callEdges"] == [
        {
            "kind": "call-edge",
            "sourceContract": "test_alias_backed_call",
            "targetSymbol": "call:numpy.add",
        }
    ]
    assertion = next(
        row for row in truthful_result.lift_doc["ir"] if row["kind"] == "contract"
    )
    assert assertion["inv"]["kind"] == "and"
    assert [atom["name"] for atom in assertion["inv"]["operands"]] == ["=", "="]


def test_list_literal_shape_has_one_verdict_bearing_owner(
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
    ctor_names = _ctor_names(truthful_result.lift_doc["ir"])
    assert "array" in ctor_names
    assert "call:len" in ctor_names


def test_dict_literal_entry_equality_discharges_and_refutes(tmp_path: Path) -> None:
    truthful = (
        "def A():\n"
        "    return {1: 2}\n"
        "\n"
        "def test_dict_literal():\n"
        "    assert A() == {1: 2}\n"
    )
    lying = truthful.replace("assert A() == {1: 2}", "assert A() == {1: 3}")

    truthful_result = run_source_through_real_solver(tmp_path / "dict-truth", truthful)
    lying_result = run_source_through_real_solver(tmp_path / "dict-lie", lying)

    assert truthful_result.verdict == "sat"
    assert lying_result.verdict == "unsat"
    assert "DictLiteralSugar" in truthful_result.selected_sugars
    assert "DictLiteralSugar" in lying_result.selected_sugars


def test_bitwise_literal_fold_witness_discharges_and_refutes(tmp_path: Path) -> None:
    prefix = "def A(z):\n    return 3 & 1\n\n"
    truthful = prefix + "def test_a():\n    assert A(0) == 1\n"
    lying = prefix + "def test_a():\n    assert A(0) == 0\n"

    truthful_result = run_source_through_real_solver(
        tmp_path / "bitwise-literal-truth", truthful
    )
    lying_result = run_source_through_real_solver(
        tmp_path / "bitwise-literal-lie", lying
    )

    trace = {
        "truthful": {
            "verdict": truthful_result.verdict,
            "selectedSugars": truthful_result.selected_sugars,
            "ir": _euf_rows(truthful_result.lift_doc),
            "rows": truthful_result.prove_doc.get("rows"),
        },
        "lying": {
            "verdict": lying_result.verdict,
            "selectedSugars": lying_result.selected_sugars,
            "ir": _euf_rows(lying_result.lift_doc),
            "rows": lying_result.prove_doc.get("rows"),
        },
    }
    print(json.dumps(trace, indent=2, sort_keys=True))

    assert "RuntimeBitwiseOpSugar" in truthful_result.selected_sugars
    assert truthful_result.verdict == "sat"
    assert _prove_statuses(truthful_result.prove_doc) == ["discharged"]

    assert "RuntimeBitwiseOpSugar" in lying_result.selected_sugars
    assert lying_result.verdict == "unsat"
    assert _prove_statuses(lying_result.prove_doc) == ["unsatisfied"]


def test_bitwise_symbolic_witness_preserves_int_term_without_number_supersort(
    tmp_path: Path,
) -> None:
    prefix = "def A(z):\n    return z & 3\n\n"
    truthful = prefix + "def test_a():\n    assert A(6) == 2\n"
    lying = prefix + "def test_a():\n    assert A(6) == 1\n"

    truthful_result = run_source_through_real_solver(
        tmp_path / "bitwise-symbolic-truth", truthful
    )
    lying_result = run_source_through_real_solver(
        tmp_path / "bitwise-symbolic-lie", lying
    )

    truthful_contract = next(
        row
        for row in truthful_result.lift_doc["ir"]
        if row.get("kind") == "function-contract"
    )
    lying_contract = next(
        row
        for row in lying_result.lift_doc["ir"]
        if row.get("kind") == "function-contract"
    )
    trace = {
        "truthful": {
            "verdict": truthful_result.verdict,
            "selectedSugars": truthful_result.selected_sugars,
            "universePost": truthful_contract["post"],
            "ir": _a_callsite_euf_rows(truthful_result.lift_doc),
            "rows": truthful_result.prove_doc.get("rows"),
        },
        "lying": {
            "verdict": lying_result.verdict,
            "selectedSugars": lying_result.selected_sugars,
            "universePost": lying_contract["post"],
            "ir": _a_callsite_euf_rows(lying_result.lift_doc),
            "rows": lying_result.prove_doc.get("rows"),
        },
    }
    print(json.dumps(trace, indent=2, sort_keys=True))

    assert "RuntimeBitwiseOpSugar" in truthful_result.selected_sugars
    assert truthful_contract["post"] == lying_contract["post"]
    assert truthful_contract["formals"] == ["z"]
    assert _ctor_names(truthful_contract["post"]) == {"&"}
    assert "Number" not in json.dumps(truthful_contract)

    assert truthful_result.verdict == "sat"
    assert _prove_statuses(truthful_result.prove_doc) == ["discharged"]

    assert "RuntimeBitwiseOpSugar" in lying_result.selected_sugars
    # #4394: the grounded Int bitwise constructor must refute this lie.
    assert lying_result.verdict == "unsat"
    assert _prove_statuses(lying_result.prove_doc) == ["unsatisfied"]


def test_subscript_assignment_post_state_witness_discharges_and_refutes(
    tmp_path: Path,
) -> None:
    prefix = (
        "def A(z):\n" "    xs = [1, 2, 3]\n" "    xs[1] = 9\n" "    return xs[1]\n" "\n"
    )
    truthful = prefix + "def test_a():\n    assert A(0) == 9\n"
    lying = prefix + "def test_a():\n    assert A(0) == 2\n"

    truthful_result = run_source_through_real_solver(
        tmp_path / "subscript-assign-truth", truthful
    )
    lying_result = run_source_through_real_solver(
        tmp_path / "subscript-assign-lie", lying
    )

    trace = {
        "truthful": {
            "verdict": truthful_result.verdict,
            "selectedSugars": truthful_result.selected_sugars,
            "ir": _euf_rows(truthful_result.lift_doc),
            "rows": truthful_result.prove_doc.get("rows"),
        },
        "lying": {
            "verdict": lying_result.verdict,
            "selectedSugars": lying_result.selected_sugars,
            "ir": _euf_rows(lying_result.lift_doc),
            "rows": lying_result.prove_doc.get("rows"),
        },
    }
    print(json.dumps(trace, indent=2, sort_keys=True))

    assert "SubscriptAssignSugar" in truthful_result.selected_sugars
    assert truthful_result.verdict == "sat"
    assert _linked_post_rhs_values(truthful_result.prove_doc) == [9]
    assert _prove_statuses(truthful_result.prove_doc) == ["discharged"]
    assert "single constraint has no sibling" not in _prove_reasons(
        truthful_result.prove_doc
    )

    assert "SubscriptAssignSugar" in lying_result.selected_sugars
    assert lying_result.verdict == "unsat"
    assert _linked_post_rhs_values(lying_result.prove_doc) == [9]
    assert _prove_statuses(lying_result.prove_doc) == ["unsatisfied"]
    assert _prove_reason_contains_values(lying_result.prove_doc, {2, 9})


def test_subscript_delete_post_state_witness_discharges_and_refutes(
    tmp_path: Path,
) -> None:
    prefix = (
        "def A(z):\n" "    xs = [1, 2, 3]\n" "    del xs[1]\n" "    return xs[1]\n" "\n"
    )
    truthful = prefix + "def test_a():\n    assert A(0) == 3\n"
    lying = prefix + "def test_a():\n    assert A(0) == 2\n"

    truthful_result = run_source_through_real_solver(
        tmp_path / "subscript-delete-truth", truthful
    )
    lying_result = run_source_through_real_solver(
        tmp_path / "subscript-delete-lie", lying
    )

    trace = {
        "truthful": {
            "verdict": truthful_result.verdict,
            "selectedSugars": truthful_result.selected_sugars,
            "ir": _euf_rows(truthful_result.lift_doc),
            "rows": truthful_result.prove_doc.get("rows"),
        },
        "lying": {
            "verdict": lying_result.verdict,
            "selectedSugars": lying_result.selected_sugars,
            "ir": _euf_rows(lying_result.lift_doc),
            "rows": lying_result.prove_doc.get("rows"),
        },
    }
    print(json.dumps(trace, indent=2, sort_keys=True))

    assert "SubscriptDeleteSugar" in truthful_result.selected_sugars
    assert truthful_result.verdict == "sat"
    assert _linked_post_rhs_values(truthful_result.prove_doc) == [3]
    assert _prove_statuses(truthful_result.prove_doc) == ["discharged"]
    assert "single constraint has no sibling" not in _prove_reasons(
        truthful_result.prove_doc
    )

    assert "SubscriptDeleteSugar" in lying_result.selected_sugars
    assert lying_result.verdict == "unsat"
    assert _linked_post_rhs_values(lying_result.prove_doc) == [3]
    assert _prove_statuses(lying_result.prove_doc) == ["unsatisfied"]
    assert _prove_reason_contains_values(lying_result.prove_doc, {2, 3})


def test_typed_red_effect_witness_accepts_right_red_and_rejects_wrong_red(
    tmp_path: Path,
) -> None:
    source = "def A(z):\n    return os.exit(0)\n"
    right_effect = TypedRedEffectExpectation(
        effect_class="OSExitRuntimeEffect",
        reason_needle="OS exit runtime boundary",
        blame_needle="test_witness.py:2:11",
    )
    wrong_effect = TypedRedEffectExpectation(
        effect_class="OSExitRuntimeEffect",
        reason_needle="starred expression runtime boundary",
        blame_needle="test_witness.py:2:11",
    )
    seed = SugarRedEffectWitnessPair(
        name="planted_boolop_runtime_effect",
        owner_sugar="OsSugar",
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


def test_evaluate_seed_witness_worker_failure_is_named_without_aborting_corpus(
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
        selected = f"{project.parent.name.capitalize()}Sugar"
        return _fake_witness_result(selected=(selected,), verdict=expected)

    monkeypatch.setattr(
        sugar_witness_instruments,
        "run_source_through_real_solver",
        fake_run,
    )

    report = evaluate_seed_witnesses(seeds, tmp_path, catalog_count=len(seeds))

    assert [
        (
            failure.seed,
            failure.owner_sugar,
            failure.variant,
            failure.axis,
            failure.observed,
        )
        for failure in report.triple_failures
    ] == [("bad", "BadSugar", "truthful", "pipeline", "boom from fake worker")]


def test_duplicate_seed_names_use_independent_work_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SUGAR_WITNESS_WORKERS", "2")
    monkeypatch.setattr(
        sugar_witness_instruments,
        "ensure_sugar_bin",
        lambda: Path("fake-sugar"),
    )
    projects: list[Path] = []

    def fake_run(project: Path, source: str) -> WitnessPipelineResult:
        projects.append(project)
        expected = "sat" if project.name == "truthful" else "unsat"
        return _fake_witness_result(selected=("SameSugar",), verdict=expected)

    monkeypatch.setattr(
        sugar_witness_instruments,
        "run_source_through_real_solver",
        fake_run,
    )
    seed = _synthetic_seed("same", "SameSugar")

    report = evaluate_seed_witnesses(
        (seed, seed), tmp_path, catalog_count=1
    )

    assert report.is_zero
    assert len(set(projects)) == 4


def test_assert_witness_pair_states_one_proof_bearing_callsite(tmp_path: Path) -> None:
    seed = next(
        item for item in DEFAULT_SUGAR_WITNESS_SEEDS if item.name == "assert_return"
    )

    report = evaluate_seed_witnesses((seed,), tmp_path, catalog_count=1)

    assert report.is_zero


def test_sugar_witness_seed_triples_hit_real_solver(seed_report) -> None:
    # IDD invariant: seed coverage is a canceling pair, not a pinned magnitude.
    # Every catalog sugar must own a seed case — (catalog - seed-covered) == 0.
    # This self-updates (a 58th sugar raises both sides) and is red until full
    # coverage. Pinning seed_count / catalog_count == 57 asserted nothing about
    # correctness and forced a hand-edit on every catalog change.
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
    # #4395: the live catalog seed must retain explicit EUF residue teeth.
    seed = next(
        item
        for item in DEFAULT_SUGAR_WITNESS_SEEDS
        if item.name == "divmod_dunder_return"
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

    assert "DivmodDunderCallSugar" in truthful.selected_sugars
    assert truthful.verdict == "sat"
    truthful_rows = _binary_dunder_euf_rows(truthful.lift_doc)
    assert len(truthful_rows) == 1
    assert _euf_rhs_values(truthful_rows) == [1]
    assert _warrant_kinds(truthful_rows[0]) == {"Stated", "Derived"}

    assert "DivmodDunderCallSugar" in lying.selected_sugars
    assert lying.verdict == "unsat"
    lying_rows = _binary_dunder_euf_rows(lying.lift_doc)
    assert len(lying_rows) == 2
    assert _euf_rhs_values(lying_rows) == [1, 2]
    assert {_euf_rhs_value(row): _warrant_kinds(row) for row in lying_rows} == {
        1: {"Derived"},
        2: {"Stated"},
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
    # Post-#4035: DigBoundary soft rows are gone. Effectful multi-statement
    # dunders are typed red (RuntimeEffect Incomplete) — no Derived companion
    # fabricated from the print-side-effect body. Stated-only is the pin.
    assert "Derived" not in _warrant_kinds(rows[0])


def test_display_conversion_trace_emits_derived_fact_and_refutes_lie(
    tmp_path: Path,
) -> None:
    # #4400: the live format seed currently exposes the typed lifter crash.
    seed = next(
        item
        for item in DEFAULT_SUGAR_WITNESS_SEEDS
        if item.name == "format_dunder_return"
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

    assert "FormatDunderCallSugar" in truthful.selected_sugars
    assert truthful.verdict == "sat"
    truthful_rows = _euf_rows(truthful.lift_doc)
    assert len(truthful_rows) == 1
    assert _euf_rhs_values(truthful_rows) == [20]
    assert _warrant_kinds(truthful_rows[0]) == {"Stated", "Derived"}

    assert "FormatDunderCallSugar" in lying.selected_sugars
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
    # Post-#4035: DigBoundary soft rows are gone. Effectful __repr__ (print) is
    # typed red — no Derived companion fabricated. Stated-only is the pin.
    assert "Derived" not in _warrant_kinds(rows[0])


@pytest.mark.parametrize(
    ("seed_name", "truthful_rhs", "lying_rhs"),
    [
        ("len_return", 3, 4),
        ("subscript_return", 20, 21),
        ("tuple_unpack_assign_return", 5, 6),
    ],
)
def test_literal_call_residue_rows_emit_derived_fact_and_refute_lie(
    tmp_path: Path,
    seed_name: str,
    truthful_rhs: object,
    lying_rhs: object,
) -> None:
    # #4395: current catalog witnesses must retain explicit EUF residue teeth.
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


def test_solver_timeout_is_typed_not_logical_undecidable(
    tmp_path: Path,
) -> None:
    seed = next(
        item
        for item in DEFAULT_SUGAR_WITNESS_SEEDS
        if item.name == "tuple_unpack_assign_return"
    )
    project = tmp_path / "solver-timeout"
    _stage_cli_project(project, seed.truthful.source)
    config = project / ".sugar" / "config.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "timeout_seconds = 10", "timeout_seconds = 0"
        ),
        encoding="utf-8",
    )

    result = mint_and_prove(project)

    rows = result.prove_doc.get("rows", [])
    statuses = [row.get("status") for row in rows]
    trace = {
        "seed": seed.name,
        "statuses": statuses,
        "rows": rows,
    }
    print(json.dumps(trace, indent=2, sort_keys=True))

    assert result.verdict == "solver-timeout"
    assert statuses == ["solver-timeout"]
    assert "undecidable" not in statuses
    verification = rows[0]["verification"]
    invocation = verification["solverInvocations"][0]
    assert invocation["verdict"] == "solver-timeout"
    assert invocation["exit"]["kind"] == "timeout"
    assert invocation["exit"]["timedOut"] is True
    assert "timeout after" in rows[0]["reason"]


@pytest.mark.parametrize(
    "seed_name",
    ["bool_op_return"],
)
def test_boolop_literal_residue_lie_lowers_to_concrete_false_operand(
    tmp_path: Path,
    seed_name: str,
) -> None:
    # #4398: retain the assertion-contract requirement while grounding is red.
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
    # #4398: retain the derived-call requirement while grounding is red.
    seed = next(
        item
        for item in DEFAULT_SUGAR_WITNESS_SEEDS
        if item.name == "call_return"
    )
    project = tmp_path / "call_return"
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


def _single_int32_eq_bv_expr_atom(lift_doc: dict) -> dict:
    atoms = [
        atom
        for row in lift_doc["ir"]
        if isinstance(row, dict)
        for atom in _walk_atoms(row)
        if atom.get("name") == "int32.eq-bv-expr"
    ]
    assert len(atoms) == 1, json.dumps(lift_doc["ir"], indent=2, sort_keys=True)
    return atoms[0]


def _single_linked_int32_eq_bv_expr_atom(prove_doc: dict) -> dict:
    atoms = [
        atom
        for row in prove_doc.get("rows", [])
        if isinstance(row, dict)
        for post in row.get("verification", {}).get("linkedPosts", [])
        if isinstance(post, dict)
        for atom in _walk_atoms(post.get("instantiatedPost"))
        if atom.get("name") == "int32.eq-bv-expr"
    ]
    assert len(atoms) == 1, json.dumps(prove_doc, indent=2, sort_keys=True)
    return atoms[0]


def _walk_atoms(node) -> list[dict]:
    if isinstance(node, dict):
        found = [node] if node.get("kind") == "atomic" else []
        for value in node.values():
            found.extend(_walk_atoms(value))
        return found
    if isinstance(node, list):
        found: list[dict] = []
        for item in node:
            found.extend(_walk_atoms(item))
        return found
    return []


def _ctor_names(node) -> set[str]:
    if isinstance(node, dict):
        names = {node["name"]} if node.get("kind") == "ctor" else set()
        for value in node.values():
            names.update(_ctor_names(value))
        return names
    if isinstance(node, list):
        names: set[str] = set()
        for item in node:
            names.update(_ctor_names(item))
        return names
    return set()


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


def _linked_post_rhs_values(prove_doc: dict) -> list[int]:
    values: list[int] = []
    for row in prove_doc.get("rows", []):
        verification = row.get("verification")
        if not isinstance(verification, dict):
            continue
        for post in verification.get("linkedPosts", []):
            instantiated = post.get("instantiatedPost", {})
            args = instantiated.get("args", [])
            if len(args) >= 2 and isinstance(args[1], dict):
                values.append(args[1].get("value"))
    return sorted(value for value in values if isinstance(value, int))


def _prove_statuses(prove_doc: dict) -> list[str]:
    return [
        status
        for row in prove_doc.get("rows", [])
        if isinstance((status := row.get("status")), str)
    ]


def _prove_reasons(prove_doc: dict) -> str:
    return "\n".join(
        reason
        for row in prove_doc.get("rows", [])
        if isinstance((reason := row.get("reason")), str)
    )


def _prove_reason_contains_values(prove_doc: dict, values: set[int]) -> bool:
    reasons = _prove_reasons(prove_doc)
    return all(f'"value":{value}' in reasons for value in values)


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
        seed
        for seed in DEFAULT_SUGAR_WITNESS_SEEDS
        if seed.name == "general_slice_return"
    )
    wrong_owner = replace(
        slice_seed,
        owner_sugar="TrySugar",
    )

    report = evaluate_seed_witnesses((wrong_owner,), tmp_path)

    assert report.witness_triples_failing == 1
    assert report.witnesses_not_dispatching_to_owner == 2
    mismatch = report.non_circularity_failures[0]
    assert mismatch.seed == "general_slice_return"
    assert mismatch.expected_sugar == "TrySugar"
    assert "SliceSubscriptSugar" in mismatch.selected_sugars
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
        "temporal_opt_outs": 0,
        "total": 0,
    }
    assert "R(unenrolled-sugars): 0" in text
    assert "R(witness-triples-failing): 0" in text
    assert "R(witnesses-not-dispatching-to-owner): 0" in text
    assert "R(non-fol-opt-out-drift): 0" in text
    assert "R(temporal-opt-outs): 0" in text
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
    stdout = capsys.readouterr().out
    assert "R(unenrolled-sugars): 0" in stdout
    assert "R(witness-triples-failing): 0" in stdout
    assert "R(non-fol-opt-out-drift): 0" in stdout
    assert "R(temporal-opt-outs): 0" in stdout
    assert status == 0


def test_witness_pipeline_solver_absence_is_loud() -> None:
    with pytest.raises(WitnessPipelineError, match="no rows"):
        prove_verdict({"rows": []})
