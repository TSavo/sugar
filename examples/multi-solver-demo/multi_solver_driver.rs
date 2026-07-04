// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Multi-solver demo. Drives the verifier four times against the same
// fixture obligation -- one run per mode (single, chain, portfolio
// first-wins, portfolio consensus, dispatch). Uses `stub:` solvers so
// the demo runs in CI with no Z3 / cvc5 / bitwuzla installed.
//
// Spec: protocol/specs/2026-04-30-multi-solver-protocol.md
//
// Run with:
//   cargo run --release -p sugar-verifier --example multi_solver_demo
//
// The driver is self-contained: it builds an in-memory SolversConfig
// for each mode, calls run_plan against a tiny fixture SMT script and
// prints the report shape.

use std::time::Duration;

use sugar_ir_compiler::CompilerInput;
use sugar_verifier::solvers::{
    plan::{run_plan, Registry},
    registry, SolverPlan, SolversConfig,
};
use sugar_verifier::types::ObligationVerdict;

fn fixture_smt() -> String {
    // Trivial unsat: assert (not (=> true true)) -> unsat.
    // The stub solvers ignore the script body; this is here for
    // anyone running with a real solver binary.
    "(set-logic ALL)\n(assert (not (=> true true)))\n(check-sat)\n".into()
}

fn header(name: &str) {
    println!("\n=== mode: {} ===", name);
}

fn print_report(
    verdict: ObligationVerdict,
    reason: &str,
    invs: &[sugar_verifier::solvers::plan::SolverInvocation],
) {
    println!("  verdict: {}", verdict.as_str());
    println!("  reason : {}", reason);
    println!("  per-solver invocations:");
    for inv in invs {
        println!(
            "    - solver={:<14} version={:<10} verdict={:<13} wall_ms={:>4} timed_out={}",
            inv.result.solver_name,
            inv.result.solver_version,
            inv.result.verdict.as_str(),
            inv.result.wall_clock.as_millis(),
            inv.result.timed_out
        );
    }
}

fn run_mode(name: &str, toml_body: &str) {
    header(name);
    let cfg = SolversConfig::from_toml(toml_body).expect("parse toml");
    let plan = SolverPlan::from_config(&cfg);
    let registry: Registry = registry::build(&cfg);
    let smt = fixture_smt();
    let formula = serde_json::json!({
        "kind":"atomic","name":">",
        "args":[{"kind":"var","name":"n"},{"kind":"const","value":0}]
    });
    let formula = CompilerInput::decode_json(formula).expect("demo formula decodes");
    let started = std::time::Instant::now();
    let (verdict, reason, invs) = run_plan(&plan, &registry, &smt, Some(&formula));
    let elapsed = started.elapsed();
    print_report(verdict, &reason, &invs);
    println!("  total wall : {}ms", elapsed.as_millis());
}

fn main() {
    println!("sugar multi-solver demo");
    println!("--------------------------");
    println!("Each mode below uses stub solvers so CI passes without z3 / cvc5 /");
    println!("bitwuzla installed. Swap `binary = \"stub:...\"` for a real binary");
    println!("path in `.sugar/config.toml` to drive real solvers.");

    run_mode(
        "single (default)",
        r#"
[solvers]
default = "z3"

[solvers.z3]
binary = "stub:unsat"
version = "4.13.0"
"#,
    );

    run_mode(
        "chain",
        r#"
[solvers]
chain = ["z3", "cvc5"]

[solvers.z3]
binary = "stub:undecidable"
timeout_seconds = 1

[solvers.cvc5]
binary = "stub:unsat"
"#,
    );

    run_mode(
        "portfolio first-wins",
        r#"
[solvers]
portfolio = ["z3", "cvc5", "bitwuzla"]
mode = "first-wins"

[solvers.z3]
binary = "stub:unsat"

[solvers.cvc5]
binary = "stub:unsat"

[solvers.bitwuzla]
binary = "stub:unsat"
"#,
    );

    run_mode(
        "portfolio consensus (agree)",
        r#"
[solvers]
portfolio = ["z3", "cvc5"]
mode = "consensus"

[solvers.z3]
binary = "stub:unsat"

[solvers.cvc5]
binary = "stub:unsat"
"#,
    );

    run_mode(
        "portfolio consensus (DISAGREEMENT)",
        r#"
[solvers]
portfolio = ["z3", "cvc5"]
mode = "consensus"

[solvers.z3]
binary = "stub:unsat"

[solvers.cvc5]
binary = "stub:sat"
"#,
    );

    run_mode(
        "per-fragment dispatch",
        r#"
[solvers]
[solvers.dispatch]
strings = "cvc5"
bitvectors = "bitwuzla"
"linear-arithmetic" = "z3"
default = "z3"

[solvers.z3]
binary = "stub:unsat"

[solvers.cvc5]
binary = "stub:undecidable"

[solvers.bitwuzla]
binary = "stub:undecidable"
"#,
    );

    // Suppress unused-import diagnostics on Duration in CI test builds.
    let _ = Duration::from_secs(0);

    println!("\ndone.");
}
