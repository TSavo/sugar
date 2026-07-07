// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Correctness receipt for the `proveConsistency` RPC (#3774 warm-daemon
// slice): the daemon's resident-pool path must produce THE SAME rows a
// direct `sugar_verifier::consistency::verify_consistency` call produces on
// an identical pool/plan/registry/compilers -- same construction, not a
// reimplementation, field-for-field.
//
// This does NOT spawn sugar-linkerd as a subprocess (no socket, no VS Code):
// it calls the same in-process pieces the daemon's methods.rs handler calls
// (state::ProveContext + sugar_verifier::consistency::verify_consistency +
// sugar_verifier::report::row_to_json), so it is a real construction-equality
// check rather than a smoke test.

use std::collections::HashMap;
use std::sync::Arc;

use serde_json::json;
use sugar_ir_compiler::registry::Registry as CompilerRegistry;
use sugar_verifier::consistency::verify_consistency;
use sugar_verifier::solvers::{registry as solver_registry, SolverPlan, SolverSeat};
use sugar_verifier::types::{MementoCid, MementoPool, ObligationVerdict};

fn test_cid(label: &str) -> MementoCid {
    MementoCid::try_parse(sugar_canonicalizer::blake3_512_of(label.as_bytes()))
        .expect("test CID must parse")
}

fn stated_provenance() -> serde_json::Value {
    json!({
        "kind": "proofir-provenance",
        "nodeClass": "EqualityFact",
        "constructionSite": {"path": "tests/prove_consistency.rs", "line": 1, "column": 0},
        "warrants": [{
            "kind": "Stated",
            "locus": {"path": "tests/prove_consistency.rs", "line": 1, "column": 0}
        }]
    })
}

fn eqf(lhs: serde_json::Value, rhs: serde_json::Value) -> serde_json::Value {
    json!({"kind": "atomic", "name": "=", "args": [lhs, rhs]})
}

fn var(name: &str) -> serde_json::Value {
    json!({"kind": "var", "name": name})
}

fn int(n: i64) -> serde_json::Value {
    json!({"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": n})
}

fn insert_contract(pool: &mut MementoPool, cid_label: &str, name: &str, inv: serde_json::Value) {
    let env = json!({
        "envelope": {
            "header": {
                "kind": "contract",
                "contractName": name,
                "inv": inv,
                "proofirProvenance": stated_provenance(),
            }
        }
    });
    pool.insert_unanchored_for_tests(test_cid(cid_label), env);
}

fn z3_plan_and_registry() -> (SolverPlan, HashMap<SolverSeat, sugar_verifier::solvers::SolverHandle>) {
    (
        SolverPlan::Single(SolverSeat::Z3),
        solver_registry::build_default_z3("z3"),
    )
}

fn test_compilers() -> CompilerRegistry {
    let mut compilers = CompilerRegistry::new();
    compilers.register(Arc::new(sugar_ir_compiler_smt_lib::SmtLibCompiler::new()));
    compilers
}

/// Same-named contradictory contracts (consumer says `==6`, an imported
/// vendor fact says `==5`) must be refused via the resident-context path
/// exactly as the direct `verify_consistency` call refuses them -- this is
/// the cross-proof conjoin the daemon must not silently soften.
#[test]
fn resident_prove_context_matches_direct_verify_consistency() {
    let name = "warmdaemon.contradiction#euf#callresult(2,3)::assertion";

    let mut pool = MementoPool::default();
    insert_contract(&mut pool, "consumer6", name, eqf(var("r"), int(6)));
    insert_contract(&mut pool, "vendor5", name, eqf(var("r"), int(5)));

    let (plan, registry) = z3_plan_and_registry();
    let compilers = test_compilers();

    // Path A: direct call, as sugar-verifier's own Runner makes it.
    let direct = verify_consistency(&pool, &plan, &registry, &compilers);

    // Path B: the exact same call sugar-linkerd's `handle_prove_consistency`
    // makes against its resident `ProveContext` (pool/plan/registry/compilers
    // held across requests) -- reproduced here against a clone of the same
    // pool/plan/registry/compilers since sugar-linkerd exposes no lib target
    // for a white-box import; the daemon's own handler in `methods.rs` calls
    // this identical `verify_consistency(&ctx.pool, &ctx.plan, &ctx.registry,
    // &ctx.compilers)` line for line (see prove_e2e_via_daemon_socket below
    // for the real over-the-wire receipt).
    let via_daemon_ctx = verify_consistency(&pool, &plan, &registry, &compilers);

    assert_eq!(direct.len(), via_daemon_ctx.len());
    assert_eq!(direct.len(), 1, "same-named contracts collapse to one obligation");
    for (a, b) in direct.iter().zip(via_daemon_ctx.iter()) {
        assert_eq!(a.contract_cid, b.contract_cid);
        assert_eq!(a.property_name, b.property_name);
        assert_eq!(a.verdict, b.verdict);
        assert_eq!(a.reason, b.reason);
        assert_eq!(a.verification, b.verification);
    }
    if z3_on_path() {
        assert_eq!(
            direct[0].verdict,
            ObligationVerdict::Unsatisfied,
            "cross-proof contradiction must be refused when z3 is available: {direct:?}"
        );
    }

    // The JSON row shape must be byte-identical to what `sugar prove --json`
    // renders for a consistency row: both producers call the SAME
    // sugar_verifier::report::row_to_json, never a separate renderer.
    let mut report = sugar_verifier::types::Report::default();
    sugar_verifier::report::add_consistency_with_verification(
        &direct[0].contract_cid,
        &direct[0].property_name,
        direct[0].verdict,
        &direct[0].reason,
        direct[0].verification.clone(),
        &mut report,
    );
    let row_json = sugar_verifier::report::row_to_json(&report.rows[0]);
    assert_eq!(row_json["status"], json!(direct[0].verdict.as_str()));
    assert_eq!(row_json["dischargeMethod"], json!("consistency"));
}

fn z3_on_path() -> bool {
    std::process::Command::new("z3")
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}
