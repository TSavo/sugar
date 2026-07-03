use std::collections::BTreeSet;
use std::process::Command;
use std::rc::Rc;
use std::time::{SystemTime, UNIX_EPOCH};

use sugar_ir_symbolic::{num, ConstValue, Sort, Term};
use sugar_lift_rust_tests::sugar::catalog::catalog_claims;
use sugar_lift_rust_tests::{
    emit_value_contract, lift_file, warrant_conjoined_with_vendor_terms, AdapterOutput,
    AssertionFactEmission, AssertionFactKind,
};

const EXPECTED_SEED_CLAIMS: usize = 79;
const EXPECTED_ENROLLMENT_FRONTIER: usize = 126;
const EXPECTED_NOT_VERDICT_BEARING_CLAIMS: usize = 2;
const EXPECTED_TEMPORAL_OPT_OUT_CLAIMS: usize = 4;
const EXPECTED_PENDING_ROUTER_WITNESS_SLOTS: usize = 0;

#[derive(Clone, Copy)]
struct WitnessPair {
    claim: &'static str,
    truthful: &'static str,
    lying: &'static str,
}

#[derive(Clone, Copy)]
struct PendingRouterWitnessSlot {
    router: &'static str,
    owner_slice: &'static str,
    truthful_slot: &'static str,
    lying_slot: &'static str,
}

fn pending_router_witness_slots() -> Vec<PendingRouterWitnessSlot> {
    Vec::new()
}

fn seed_witnesses() -> Vec<WitnessPair> {
    catalog_claims()
        .into_iter()
        .filter_map(|claim| match claim.witnesses {
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::Pair { truthful, lying } => {
                Some(WitnessPair {
                    claim: claim.name,
                    truthful,
                    lying,
                })
            }
            _ => None,
        })
        .collect()
}
fn parse(src: &str) -> syn::File {
    syn::parse_file(src).expect("witness source parses")
}

fn warranted_facts(out: &AdapterOutput) -> Vec<&AssertionFactEmission> {
    out.assertion_facts
        .iter()
        .filter(|fact| fact.kind == AssertionFactKind::Warranted && fact.claim_count > 0)
        .collect()
}

fn single_warranted_decl(out: &AdapterOutput) -> &sugar_ir_symbolic::ContractDecl {
    let facts = warranted_facts(out);
    let decls: Vec<_> = out
        .decls
        .iter()
        .filter(|decl| {
            facts
                .iter()
                .any(|fact| fact.contract_name.as_str() == decl.name)
        })
        .collect();
    assert_eq!(
        decls.len(),
        1,
        "expected exactly one claim-bearing warranted decl; facts={:?}; decls={:?}; skips={:?}",
        out.assertion_facts,
        out.decls,
        out.skip_reasons
    );
    decls[0]
}

fn inv_json(decl: &sugar_ir_symbolic::ContractDecl) -> serde_json::Value {
    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    parsed[0]["inv"].clone()
}

fn resolve_z3_from(z3_env: Option<&str>, path_env: &str) -> Result<String, String> {
    if let Some(path) = z3_env.filter(|value| !value.trim().is_empty()) {
        if Command::new(path)
            .arg("--version")
            .output()
            .map(|out| out.status.success())
            .unwrap_or(false)
        {
            return Ok(path.to_string());
        }
        return Err(format!("Z3 points at a non-executable solver: {path}"));
    }
    for dir in path_env.split(':').filter(|dir| !dir.is_empty()) {
        let candidate = std::path::Path::new(dir).join("z3");
        if candidate.is_file()
            && Command::new(&candidate)
                .arg("--version")
                .output()
                .map(|out| out.status.success())
                .unwrap_or(false)
        {
            return Ok(candidate.display().to_string());
        }
    }
    Err("sugar witness triple harness requires z3 on PATH or Z3=/path/to/z3".to_string())
}

fn z3_path_or_panic() -> String {
    let z3_env = std::env::var("Z3").ok();
    let path_env = std::env::var("PATH").unwrap_or_default();
    resolve_z3_from(z3_env.as_deref(), &path_env).unwrap_or_else(|err| panic!("{err}"))
}

fn compile_asserted_json_to_parts(
    formula: &serde_json::Value,
) -> Result<sugar_ir_compiler::CompiledFormula, sugar_ir_compiler::CompileError> {
    match sugar_ir_compiler::CompilerInput::decode_json(formula.clone())? {
        sugar_ir_compiler::CompilerInput::Formula(formula) => {
            sugar_ir_compiler_smt_lib::compile_asserted_formula_to_parts(formula.formula())
        }
        _ => Err(sugar_ir_compiler::CompileError::MalformedIr(
            "asserted SMT-LIB compile expects a formula input".to_string(),
        )),
    }
}

fn z3_verdict(inv: &serde_json::Value, label: &str, z3: &str) -> bool {
    let parts = compile_asserted_json_to_parts(inv).expect("witness inv must compile to SMT-LIB");
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
    let path = std::env::temp_dir().join(format!("sugar_witness_triple_{label}.smt2"));
    std::fs::write(&path, &script).expect("write witness smt2");
    let out = Command::new(z3).arg(&path).output().expect("run z3");
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(
        !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
        "witness relation must be well-sorted:\n{stdout}\n--- {script}"
    );
    stdout.contains("sat") && !stdout.contains("unsat")
}

fn selected_claims(out: &AdapterOutput) -> BTreeSet<&'static str> {
    out.factory_audits
        .iter()
        .filter_map(|audit| audit.selected)
        .collect()
}

fn assert_witness_dispatches_to_owner(claim: &str, out: &AdapterOutput) -> Result<(), String> {
    let selected = selected_claims(out);
    if selected.contains(claim) {
        Ok(())
    } else {
        Err(format!(
            "witness expected claim `{claim}` but selected {:?}",
            selected
        ))
    }
}

#[test]
fn z3_absence_is_a_loud_harness_error() {
    let err = resolve_z3_from(None, "").expect_err("empty PATH must not silently skip z3");
    assert!(
        err.contains("requires z3"),
        "z3 absence must be a loud harness error, got {err:?}"
    );
}

#[test]
fn phase2_question_mark_ok_path_has_solver_bad_twin() {
    let z3 = z3_path_or_panic();
    let truthful = r#"
        #[test]
        fn t_question_mark_ok_good() -> Result<(), i32> {
            let x = Ok::<i32, i32>(7)?;
            assert_eq!(x, 7);
            Ok(())
        }
    "#;
    let lying = r#"
        #[test]
        fn t_question_mark_ok_bad() -> Result<(), i32> {
            let x = Ok::<i32, i32>(7)?;
            assert_eq!(x, 8);
            Ok(())
        }
    "#;
    let mut verdict_receipt = Vec::new();

    for (label, src, expected_sat) in [
        ("phase2_question_mark_ok_good", truthful, true),
        ("phase2_question_mark_ok_bad", lying, false),
    ] {
        let out = lift_file(&parse(src), &format!("sugar-witness/{label}.rs"));
        let decl = single_warranted_decl(&out);
        let got_sat = z3_verdict(&inv_json(decl), label, &z3);
        verdict_receipt.push(format!("{label}={}", if got_sat { "SAT" } else { "UNSAT" }));
        assert_eq!(
            got_sat, expected_sat,
            "{label}: expected SAT={expected_sat} got SAT={got_sat}; skips={:?}",
            out.skip_reasons
        );
    }
    println!(
        "phase2 TrySugar acceptance via lift_file -> inv_json -> z3_verdict: {}",
        verdict_receipt.join(", ")
    );
}

#[test]
fn phase2_question_mark_err_path_remains_uncaught_boundary() {
    let src = r#"
        #[test]
        fn t_question_mark_err_uncaught() -> Result<(), i32> {
            let x = Err::<i32, i32>(9)?;
            assert_eq!(x, 7);
            Ok(())
        }
    "#;
    let out = lift_file(
        &parse(src),
        "sugar-witness/phase2_question_mark_err_uncaught.rs",
    );
    assert!(
        warranted_facts(&out).is_empty(),
        "uncaught Err(_)? must not fabricate a warranted assertion; facts={:?}",
        out.assertion_facts
    );
    let rendered = format!("{:?} {:?}", out.assertion_facts, out.skip_reasons);
    assert!(
        rendered.contains("result error raise effect") || rendered.contains("ResultErr"),
        "uncaught Err(_)? should surface the typed ResultErr boundary, got {rendered}"
    );
}

#[test]
fn phase2_early_return_branch_has_solver_bad_twin() {
    let z3 = z3_path_or_panic();
    let function: syn::ItemFn = syn::parse_str(
        r#"
        fn pick(flag: bool) -> i32 {
            if flag {
                return 5;
            }
            7
        }
    "#,
    )
    .expect("early-return source parses");
    let decl = emit_value_contract("pick", &function.block)
        .expect("early-return source contract emits through the route spine");
    let flag_true = bool_term(true);

    for (label, expected_out, expected_sat) in [
        ("phase2_early_return_good", 5, true),
        ("phase2_early_return_bad", 6, false),
    ] {
        let conjoined = warrant_conjoined_with_vendor_terms(
            &decl,
            &[("flag", Rc::clone(&flag_true))],
            num(expected_out),
        );
        let got_sat = z3_verdict(&inv_json(&conjoined), label, &z3);
        assert_eq!(
            got_sat, expected_sat,
            "{label}: expected SAT={expected_sat} got SAT={got_sat}; decl={conjoined:?}"
        );
    }
}

fn return_sugar_value_contract_verdict(
    src: &str,
    expected_out: i128,
    label: &str,
    z3: &str,
) -> bool {
    let parsed = parse(src);
    let function = parsed
        .items
        .iter()
        .find_map(|item| match item {
            syn::Item::Fn(function) if function.sig.ident == "pick" => Some(function),
            _ => None,
        })
        .expect("return_sugar witness must define pick");
    let decl = emit_value_contract("pick", &function.block)
        .expect("return_sugar witness must emit through the value-contract route spine");
    let conjoined =
        warrant_conjoined_with_vendor_terms(&decl, &[("flag", bool_term(true))], num(expected_out));
    z3_verdict(&inv_json(&conjoined), label, z3)
}

fn run_rust_test_source(claim: &str, kind: &str, src: &str) -> bool {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time after epoch")
        .as_nanos();
    let safe_claim = claim.replace(|c: char| !c.is_ascii_alphanumeric(), "_");
    let stem = format!(
        "sugar_witness_ground_truth_{}_{}_{}_{}",
        std::process::id(),
        nonce,
        safe_claim,
        kind
    );
    let source_path = std::env::temp_dir().join(format!("{stem}.rs"));
    let binary_path = std::env::temp_dir().join(stem);
    std::fs::write(&source_path, src).expect("write ground-truth Rust source");
    let compile = Command::new("rustc")
        .args(["--edition=2021", "--test"])
        .arg(&source_path)
        .arg("-o")
        .arg(&binary_path)
        .output()
        .expect("run rustc for ground-truth witness");
    assert!(
        compile.status.success(),
        "ground-truth Rust witness {claim}/{kind} must compile:\nstdout={}\nstderr={}",
        String::from_utf8_lossy(&compile.stdout),
        String::from_utf8_lossy(&compile.stderr)
    );
    let run = Command::new(&binary_path)
        .output()
        .expect("run ground-truth Rust test binary");
    let _ = std::fs::remove_file(&source_path);
    let _ = std::fs::remove_file(&binary_path);
    run.status.success()
}

#[test]
fn phase2_guarded_panic_branch_has_solver_bad_twin() {
    let z3 = z3_path_or_panic();
    let function: syn::ItemFn = syn::parse_str(
        r#"
        fn guarded(flag: bool) -> i32 {
            if flag {
                panic!()
            }
            7
        }
    "#,
    )
    .expect("guarded panic source parses");
    let decl = emit_value_contract("guarded", &function.block)
        .expect("guarded panic source contract emits through the route spine");
    let flag_false = bool_term(false);

    for (label, expected_out, expected_sat) in [
        ("phase2_guarded_panic_good", 7, true),
        ("phase2_guarded_panic_bad", 8, false),
    ] {
        let conjoined = warrant_conjoined_with_vendor_terms(
            &decl,
            &[("flag", Rc::clone(&flag_false))],
            num(expected_out),
        );
        let got_sat = z3_verdict(&inv_json(&conjoined), label, &z3);
        assert_eq!(
            got_sat, expected_sat,
            "{label}: expected SAT={expected_sat} got SAT={got_sat}; decl={conjoined:?}"
        );
    }
}

#[test]
fn phase2_uncaught_panic_remains_residual_refusal() {
    let function: syn::ItemFn = syn::parse_str(
        r#"
        fn explode() -> i32 {
            panic!()
        }
    "#,
    )
    .expect("uncaught panic source parses");
    let decl = emit_value_contract("explode", &function.block);
    assert!(
        decl.is_none(),
        "a bare panic has no normal return formula to fabricate: {decl:?}"
    );
}

#[test]
fn phase2_noop_drop_does_not_perturb_assertion_emission() {
    let without_drop = lift_file(
        &parse(
            r#"
            #[test]
            fn t_noop_drop_without() {
                assert_eq!(1 + 1, 2);
            }
        "#,
        ),
        "sugar-witness/phase2_noop_drop_without.rs",
    );
    let with_drop = lift_file(
        &parse(
            r#"
            struct NoopDrop;

            impl Drop for NoopDrop {
                fn drop(&mut self) {}
            }

            #[test]
            fn t_noop_drop_with() {
                let _guard = NoopDrop;
                assert_eq!(1 + 1, 2);
            }
        "#,
        ),
        "sugar-witness/phase2_noop_drop_with.rs",
    );

    assert_eq!(
        inv_json(single_warranted_decl(&with_drop)),
        inv_json(single_warranted_decl(&without_drop)),
        "a no-op Drop must not perturb the emitted assertion invariant; with_drop facts={:?}; skips={:?}",
        with_drop.assertion_facts,
        with_drop.skip_reasons
    );
}

fn bool_term(value: bool) -> Rc<Term> {
    Rc::new(Term::Const {
        value: ConstValue::Bool(value),
        sort: Sort::bool(),
    })
}

#[test]
fn witness_catalog_seed_frontier_is_pinned() {
    let catalog = catalog_claims();
    let seeded: BTreeSet<_> = seed_witnesses()
        .into_iter()
        .map(|pair| pair.claim)
        .collect();
    let claim_names: BTreeSet<_> = catalog.iter().map(|claim| claim.name).collect();
    for seed in &seeded {
        assert!(
            claim_names.contains(seed),
            "seed witness names non-catalog claim `{seed}`"
        );
    }
    let pending: Vec<_> = catalog
        .iter()
        .filter(|claim| claim.witnesses.is_pending())
        .collect();
    let not_verdict_bearing = catalog
        .iter()
        .filter(|claim| {
            matches!(
                claim.witnesses,
                sugar_lift_rust_tests::sugar::claim::SugarWitnesses::NotVerdictBearing { .. }
            )
        })
        .count();
    let temporal_opt_outs = catalog
        .iter()
        .filter(|claim| {
            matches!(
                claim.witnesses,
                sugar_lift_rust_tests::sugar::claim::SugarWitnesses::TemporalOptOut { .. }
            )
        })
        .count();
    for claim in catalog.iter().filter(|claim| {
        matches!(
            claim.witnesses,
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::NotVerdictBearing { .. }
        )
    }) {
        match claim.witnesses {
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::NotVerdictBearing {
                floor,
                reason,
            } => {
                assert!(
                    !floor.trim().is_empty(),
                    "NotVerdictBearing claim `{}` must name its floor",
                    claim.name
                );
                assert!(
                    !reason.trim().is_empty(),
                    "NotVerdictBearing claim `{}` must justify the opt-out",
                    claim.name
                );
            }
            _ => unreachable!(),
        }
    }
    for claim in catalog.iter().filter(|claim| {
        matches!(
            claim.witnesses,
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::TemporalOptOut { .. }
        )
    }) {
        match claim.witnesses {
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::TemporalOptOut {
                floor,
                reason,
                retirement,
            } => {
                assert!(
                    !floor.trim().is_empty(),
                    "TemporalOptOut claim `{}` must name its floor",
                    claim.name
                );
                assert!(
                    !reason.trim().is_empty(),
                    "TemporalOptOut claim `{}` must justify the opt-out",
                    claim.name
                );
                assert!(
                    !retirement.trim().is_empty(),
                    "TemporalOptOut claim `{}` must name its retirement condition",
                    claim.name
                );
            }
            _ => unreachable!(),
        }
    }
    println!(
        "R(witness-seed-claims)={} R(rust-witness-enrollment-frontier)={} R(rust-witness-not-verdict-bearing)={} R(rust-temporal-opt-outs)={}",
        seeded.len(),
        pending.len(),
        not_verdict_bearing,
        temporal_opt_outs
    );
    assert_eq!(seeded.len(), EXPECTED_SEED_CLAIMS);
    assert_eq!(pending.len(), EXPECTED_ENROLLMENT_FRONTIER);
    assert_eq!(not_verdict_bearing, EXPECTED_NOT_VERDICT_BEARING_CLAIMS);
    assert_eq!(temporal_opt_outs, EXPECTED_TEMPORAL_OPT_OUT_CLAIMS);
    assert_eq!(
        seeded.len() + pending.len() + not_verdict_bearing + temporal_opt_outs,
        catalog.len(),
        "every catalog claim must be exactly Pair, Pending, NotVerdictBearing, or TemporalOptOut"
    );
}

#[test]
fn phase2_router_witness_bad_twin_registry_is_armed_at_zero() {
    let slots = pending_router_witness_slots();
    let names = slots
        .iter()
        .map(|slot| slot.router)
        .collect::<BTreeSet<_>>();
    assert_eq!(
        names.len(),
        slots.len(),
        "router witness slots must be uniquely named"
    );
    for slot in &slots {
        assert!(
            !slot.truthful_slot.trim().is_empty() && !slot.lying_slot.trim().is_empty(),
            "router {} must reserve both truthful and lying bad-twin slots",
            slot.router
        );
    }
    println!(
        "R(routers-without-witness-bad-twin)={} pending={:?}",
        slots.len(),
        slots
            .iter()
            .map(|slot| format!("{}:{}", slot.owner_slice, slot.router))
            .collect::<Vec<_>>()
    );
    assert!(
        slots.is_empty(),
        "Phase 2 router witness registry is armed at stable zero; new pending slot(s) must land with truthful+lying bad twins: {:?}",
        slots
            .iter()
            .map(|slot| format!("{}:{}", slot.owner_slice, slot.router))
            .collect::<Vec<_>>()
    );
    assert_eq!(slots.len(), EXPECTED_PENDING_ROUTER_WITNESS_SLOTS);
}

#[test]
fn seed_witnesses_satisfy_the_triple() {
    let z3 = z3_path_or_panic();
    let mut failures = Vec::new();
    let mut owner_mismatches = Vec::new();
    for witness in seed_witnesses() {
        if witness.claim == "return_sugar" {
            for (kind, src, expected_out, expected_sat) in [
                ("truthful", witness.truthful, 5, true),
                ("lying", witness.lying, 6, false),
            ] {
                let label = format!("{}_{}", witness.claim, kind);
                let got_sat = return_sugar_value_contract_verdict(src, expected_out, &label, &z3);
                if got_sat != expected_sat {
                    failures.push(format!(
                        "{label}: expected SAT={expected_sat} got SAT={got_sat}"
                    ));
                }
            }
            continue;
        }
        for (kind, src, expected_sat) in [
            ("truthful", witness.truthful, true),
            ("lying", witness.lying, false),
        ] {
            let label = format!("{}_{}", witness.claim, kind);
            let out = lift_file(&parse(src), &format!("sugar-witness/{label}.rs"));
            if let Err(err) = assert_witness_dispatches_to_owner(witness.claim, &out) {
                owner_mismatches.push(format!("{label}: {err}"));
                continue;
            }
            let decl = single_warranted_decl(&out);
            let got_sat = z3_verdict(&inv_json(decl), &label, &z3);
            if got_sat != expected_sat {
                failures.push(format!(
                    "{label}: expected SAT={expected_sat} got SAT={got_sat}"
                ));
            }
        }
    }
    println!(
        "R(witness-triples-failing)={} R(witnesses-not-dispatching-to-owner)={}",
        failures.len(),
        owner_mismatches.len()
    );
    assert!(owner_mismatches.is_empty(), "{owner_mismatches:#?}");
    assert!(failures.is_empty(), "{failures:#?}");
}

#[test]
fn corrected_s8_pairs_match_real_rust_semantics() {
    let witnesses = seed_witnesses();
    for claim in ["const_item", "fold", "map", "return_sugar"] {
        let witness = witnesses
            .iter()
            .find(|witness| witness.claim == claim)
            .unwrap_or_else(|| panic!("{claim} must be enrolled as a seed witness"));
        let truthful = run_rust_test_source(claim, "truthful", witness.truthful);
        let lying = run_rust_test_source(claim, "lying", witness.lying);
        println!(
            "ground-truth Rust semantics: {claim}/truthful={} {claim}/lying={}",
            if truthful { "PASS" } else { "FAIL" },
            if lying { "PASS" } else { "FAIL" }
        );
        assert!(truthful, "{claim} truthful witness must pass as real Rust");
        assert!(!lying, "{claim} lying witness must fail as real Rust");
    }
}

#[test]
fn s9_batch1_pairs_match_real_rust_semantics() {
    let witnesses = seed_witnesses();
    let claims = [
        "term_literal",
        "const_block",
        "const",
        "binop",
        "bv_binop",
        "constraint_bool_bitwise",
        "unary",
        "wrapping_neg",
        "int_pow",
        "int_sqrt",
        "cast_term",
        "option_predicate",
        "result_predicate",
        "option_unwrap",
        "is_empty",
        "is_sorted",
        "str_method",
        "to_string",
        "constraint_string_predicate",
        "constraint_char_literal_method",
        "slice_accessor",
        "slice_search",
        "range_accessor",
        "range_term",
        "sizeof",
        "offset_of",
        "duration_value",
        "into",
        "nonzero_new",
        "nonzero_assoc_const",
        "nonzero_get",
        "float_literal_method",
    ];
    for claim in claims {
        let witness = witnesses
            .iter()
            .find(|witness| witness.claim == claim)
            .unwrap_or_else(|| panic!("{claim} must be enrolled as a seed witness"));
        let truthful = run_rust_test_source(claim, "truthful", witness.truthful);
        let lying = run_rust_test_source(claim, "lying", witness.lying);
        println!(
            "ground-truth Rust semantics: {claim}/truthful={} {claim}/lying={}",
            if truthful { "PASS" } else { "FAIL" },
            if lying { "PASS" } else { "FAIL" }
        );
        assert!(truthful, "{claim} truthful witness must pass as real Rust");
        assert!(!lying, "{claim} lying witness must fail as real Rust");
    }
}

#[test]
fn s9_batch2_pairs_match_real_rust_semantics() {
    let witnesses = seed_witnesses();
    let claims = [
        "concat_macro",
        "assertion_surface_relation_macro",
        "assertion_surface_bounded_literal_macro",
        "macro_assertion_surface",
        "assertion_surface_assert_macro",
        "constraint_bool_expr",
        "constraint_tuple_decomp",
        "string_add",
        "index",
        "maybe_uninit_new",
        "maybe_uninit_zeroed",
        "mem_zeroed",
        "try_from",
        "constraint_literal_ip_addr_property",
        "dyn_any",
        "cstr",
        "array_try_from",
        "literal_tuple_producer",
        "array_repeat",
        "format_macro",
        "block_term",
        "partition_point",
        "option_adaptor",
        "transparent_term",
        "value_if",
        "cell_refcell",
        "literal",
        "const_composite",
        "primitive_int_tuple_producer",
        "slice_search_assertion_surface",
    ];
    for claim in claims {
        let witness = witnesses
            .iter()
            .find(|witness| witness.claim == claim)
            .unwrap_or_else(|| panic!("{claim} must be enrolled as a seed witness"));
        let truthful = run_rust_test_source(claim, "truthful", witness.truthful);
        let lying = run_rust_test_source(claim, "lying", witness.lying);
        println!(
            "ground-truth Rust semantics: {claim}/truthful={} {claim}/lying={}",
            if truthful { "PASS" } else { "FAIL" },
            if lying { "PASS" } else { "FAIL" }
        );
        assert!(truthful, "{claim} truthful witness must pass as real Rust");
        assert!(!lying, "{claim} lying witness must fail as real Rust");
    }
}

#[test]
fn assertion_one_names_owner_mismatch() {
    let witness = seed_witnesses()
        .into_iter()
        .find(|pair| pair.claim == "from_bool")
        .expect("from_bool seed exists");
    let out = lift_file(
        &parse(witness.truthful),
        "sugar-witness/misattributed_from_bool.rs",
    );
    let err = assert_witness_dispatches_to_owner("duration_accessor", &out)
        .expect_err("wrong owner must be named as an assertion-1 mismatch");
    assert!(
        err.contains("duration_accessor") && err.contains("from_bool"),
        "mismatch should name expected and selected claims, got {err}"
    );
}
