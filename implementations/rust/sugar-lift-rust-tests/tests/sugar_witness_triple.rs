use std::collections::BTreeSet;
use std::process::Command;

use sugar_lift_rust_tests::sugar::catalog::catalog_claims;
use sugar_lift_rust_tests::{
    lift_file, AdapterOutput, AssertionFactEmission, AssertionFactKind, FactoryDisposition,
};

const EXPECTED_SEED_CLAIMS: usize = 13;
const EXPECTED_ENROLLMENT_FRONTIER: usize = 198;
const EXPECTED_PENDING_ROUTER_WITNESS_SLOTS: usize = 4;

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
    vec![
        PendingRouterWitnessSlot {
            router: "question_mark",
            owner_slice: "Phase2-S4",
            truthful_slot: "x? Ok path discharges through the router",
            lying_slot: "x? Err path propagates to an uncaught UNSAT twin",
        },
        PendingRouterWitnessSlot {
            router: "panic",
            owner_slice: "Phase2-S5",
            truthful_slot: "handled panic route preserves the panic-freedom fact",
            lying_slot: "uncaught panic remains a residual raise/refusal, never a fabricated fact",
        },
        PendingRouterWitnessSlot {
            router: "early_return",
            owner_slice: "Phase2-S5",
            truthful_slot: "early return in a branch routes to the handler's value",
            lying_slot: "wrong early-return value refutes through the real solver",
        },
        PendingRouterWitnessSlot {
            router: "drop",
            owner_slice: "Phase2-S6",
            truthful_slot: "no-op Drop does not perturb emitted bytes or verdict",
            lying_slot: "effectful Drop enters the effect algebra and refuses/routes explicitly",
        },
    ]
}

fn seed_witnesses() -> Vec<WitnessPair> {
    vec![
        WitnessPair {
            claim: "const_if",
            truthful: r#"
                #[test]
                fn t_const_if_then_good() {
                    assert!((if 'a' as u32 <= 98 && 98 <= 'z' as u32 { 98 + 'A' as u32 - 'a' as u32 } else { 98 }) == 66);
                }
            "#,
            lying: r#"
                #[test]
                fn t_const_if_then_bad() {
                    assert!((if 'a' as u32 <= 98 && 98 <= 'z' as u32 { 98 + 'A' as u32 - 'a' as u32 } else { 98 }) == 67);
                }
            "#,
        },
        WitnessPair {
            claim: "match_value_term",
            truthful: r#"
                #[test]
                fn t_const_match_good() {
                    assert!((match 2 { 1 => 10, 2 => 20, _ => 0 }) == 20);
                }
            "#,
            lying: r#"
                #[test]
                fn t_const_match_bad() {
                    assert!((match 2 { 1 => 10, 2 => 20, _ => 0 }) == 21);
                }
            "#,
        },
        WitnessPair {
            claim: "duration_accessor",
            truthful: r#"
                #[test]
                fn t_dur_as_secs_good() {
                    assert!(Duration::from_secs(5).as_secs() == 5);
                }
            "#,
            lying: r#"
                #[test]
                fn t_dur_as_secs_bad() {
                    assert!(Duration::from_secs(5).as_secs() == 6);
                }
            "#,
        },
        WitnessPair {
            claim: "from_bool",
            truthful: r#"
                #[test]
                fn t_from_bool_good() {
                    assert_eq!(1u8, <u8>::from(true));
                }
            "#,
            lying: r#"
                #[test]
                fn t_from_bool_bad() {
                    assert_eq!(1u8, <u8>::from(false));
                }
            "#,
        },
        WitnessPair {
            claim: "assertion_surface_tuple_decomp",
            truthful: r#"
                #[test]
                fn t_tuple_decomp_good() {
                    assert_eq!(3.14159265359f32.integer_decode(), (13176795, -22, 1));
                }
            "#,
            lying: r#"
                #[test]
                fn t_tuple_decomp_bad() {
                    assert_eq!(3.14159265359f32.integer_decode(), (13176796, -22, 1));
                }
            "#,
        },
        WitnessPair {
            claim: "int_midpoint",
            truthful: r#"
                #[test]
                fn t_midpoint_good() {
                    assert_eq!(i8::midpoint(2, 5), 3);
                }
            "#,
            lying: r#"
                #[test]
                fn t_midpoint_bad() {
                    assert_eq!(i8::midpoint(2, 5), 4);
                }
            "#,
        },
        WitnessPair {
            claim: "char_literal_method",
            truthful: r#"
                #[test]
                fn t_char_method_good() {
                    assert_eq!('x'.to_ascii_uppercase(), 'X');
                }
            "#,
            lying: r#"
                #[test]
                fn t_char_method_bad() {
                    assert_eq!('x'.to_ascii_uppercase(), 'Y');
                }
            "#,
        },
        WitnessPair {
            claim: "bool_literal_method",
            truthful: r#"
                #[test]
                fn t_bool_method_good() {
                    assert_eq!(true.then_some(7_i32), Some(7_i32));
                }
            "#,
            lying: r#"
                #[test]
                fn t_bool_method_bad() {
                    assert_eq!(true.then_some(7_i32), Some(8_i32));
                }
            "#,
        },
        WitnessPair {
            claim: "monadic",
            truthful: r#"
                #[test]
                fn t_monadic_good() {
                    assert_eq!(Some(1), Some(1));
                }
            "#,
            lying: r#"
                #[test]
                fn t_monadic_bad() {
                    assert_eq!(Some(1), Some(2));
                }
            "#,
        },
        WitnessPair {
            claim: "primitive_int",
            truthful: r#"
                #[test]
                fn t_bit_width_good() {
                    assert_eq!(0b010_1100u32.bit_width(), 6);
                }
            "#,
            lying: r#"
                #[test]
                fn t_bit_width_bad() {
                    assert_eq!(0b010_1100u32.bit_width(), 7);
                }
            "#,
        },
        WitnessPair {
            claim: "range_contains",
            truthful: r#"
                #[test]
                fn t_range_contains_good() {
                    assert!((1usize..5).contains(&4));
                }
            "#,
            lying: r#"
                #[test]
                fn t_range_contains_bad() {
                    assert!((1usize..5).contains(&5));
                }
            "#,
        },
        WitnessPair {
            claim: "assertion_surface_aggregate_decomp",
            truthful: r#"
                #[test]
                fn t_collect_good() {
                    assert_eq!((0..5).collect::<Vec<_>>(), [0, 1, 2, 3, 4]);
                }
            "#,
            lying: r#"
                #[test]
                fn t_collect_bad() {
                    assert_eq!((0..5).collect::<Vec<_>>(), [0, 1, 2, 3, 9]);
                }
            "#,
        },
        WitnessPair {
            claim: "len",
            truthful: r#"
                #[test]
                fn t_len_good() {
                    assert_eq!([1, 2, 3].len(), 3);
                }
            "#,
            lying: r#"
                #[test]
                fn t_len_bad() {
                    assert_eq!([1, 2, 3].len(), 4);
                }
            "#,
        },
    ]
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

fn z3_verdict(inv: &serde_json::Value, label: &str, z3: &str) -> bool {
    let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(inv)
        .expect("witness inv must compile to SMT-LIB");
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
        .filter(|audit| audit.disposition == FactoryDisposition::Warranted)
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
    let frontier: Vec<_> = catalog
        .iter()
        .filter(|claim| !seeded.contains(claim.name))
        .collect();
    println!(
        "R(witness-seed-claims)={} R(rust-witness-enrollment-frontier)={}",
        seeded.len(),
        frontier.len()
    );
    assert_eq!(seeded.len(), EXPECTED_SEED_CLAIMS);
    assert_eq!(frontier.len(), EXPECTED_ENROLLMENT_FRONTIER);
}

#[test]
fn phase2_router_witness_bad_twin_slots_are_pinned() {
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
    assert_eq!(slots.len(), EXPECTED_PENDING_ROUTER_WITNESS_SLOTS);
}

#[test]
fn seed_witnesses_satisfy_the_triple() {
    let z3 = z3_path_or_panic();
    let mut failures = Vec::new();
    let mut owner_mismatches = Vec::new();
    for witness in seed_witnesses() {
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
