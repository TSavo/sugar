// SPDX-License-Identifier: Apache-2.0
//
// Rust round-trip: read back a directory of .proof files, walk the
// six-stage pipeline up through enumerate_callsites, and assert
// callsite resolution works (resolve_target succeeds for every
// enumerated callsite).
//
// Used to verify that the Rust verifier consumes its own kit's
// published .proof bytes. Cross-language round-trip with C++/Go/TS
// follows once the parallel hash-widening agents land their cuts.

use std::path::PathBuf;
use std::process::ExitCode;

use sugar_verifier::{resolve_target, Runner, RunnerConfig};

fn main() -> ExitCode {
    let argv: Vec<String> = std::env::args().collect();
    let project_root = if argv.len() >= 2 {
        PathBuf::from(&argv[1])
    } else {
        PathBuf::from(".")
    };

    let cfg = RunnerConfig {
        project_root: project_root.clone(),
        z3_path: std::env::var("SUGAR_Z3").unwrap_or_else(|_| "z3".into()),
        ..Default::default()
    };
    let runner = Runner::new(cfg);
    let (pool, callsites) = runner.run_load_and_enumerate();

    println!("  loaded mementos: {}", pool.mementos.len());
    println!(
        "  bridges by sourceSymbol: {}",
        pool.bridges_by_symbol.len()
    );
    println!("  enumerated callsites: {}", callsites.len());
    if !pool.load_errors.is_empty() {
        eprintln!("LOAD ERRORS:");
        for e in &pool.load_errors {
            eprintln!("  - {}: {}", e.proof_path, e.reason);
        }
        return ExitCode::from(1);
    }

    let mut resolved_ok = 0;
    for cs in &callsites {
        match resolve_target::run(cs, &pool) {
            Ok(_) => resolved_ok += 1,
            Err(e) => {
                eprintln!(
                    "RESOLVE FAILED for callsite {}@{}: {e}",
                    cs.bridge_ir_name,
                    cs.property_cid
                        .as_ref()
                        .map(|cid| cid.as_ref())
                        .unwrap_or("<none>")
                );
            }
        }
    }
    println!(
        "  resolved {} of {} callsites",
        resolved_ok,
        callsites.len()
    );
    if resolved_ok != callsites.len() {
        return ExitCode::from(1);
    }
    println!("  Rust round-trip: OK");
    ExitCode::SUCCESS
}
