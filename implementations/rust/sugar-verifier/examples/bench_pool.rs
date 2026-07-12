// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Receipt tool for #3774 warm-daemon slice: measures the pool-load +
// plan/registry-build cost the daemon amortizes by holding a resident
// `ProveContext` instead of re-running `load_pool` per `proveConsistency`
// request (which is what a cold `sugar prove` shell effectively re-pays
// every save).
//
// Usage: cargo run --release -p sugar-verifier --example bench_pool -- <project_root>
//
// HONEST SCOPE: this sandbox worktree has no pandas-scale (96MB) proof
// catalog checked out, so the numbers below are measured on whatever small
// `.proof` catalog `<project_root>` has -- they demonstrate the MECHANISM
// (cold-reload cost is real and proportional to pool size/I-O; warm reuse is
// ~free) but are NOT the pandas-scale number the mission's ~20s prove-side
// figure refers to. That number needs to be re-measured on the actual
// pandas kit project, which this worktree does not contain.
use std::time::Instant;
use sugar_verifier::runner::{build_plan_and_registry_pub, load_pool, RunnerConfig};

fn main() {
    let root = std::env::args().nth(1).expect("project root");
    let cfg = RunnerConfig {
        project_root: root.into(),
        ..Default::default()
    };

    // Cold: reload the pool + rebuild plan/registry every "request".
    let n = 20;
    let start = Instant::now();
    for _ in 0..n {
        let _pool = load_pool(&cfg);
        let _pr = build_plan_and_registry_pub(&cfg);
    }
    let cold_total = start.elapsed();

    // Warm: load once, reuse.
    let warm_start = Instant::now();
    let pool = load_pool(&cfg);
    let (plan, registry) = build_plan_and_registry_pub(&cfg);
    let first_load = warm_start.elapsed();
    let reuse_start = Instant::now();
    for _ in 0..n {
        let _ = (&pool, &plan, &registry);
    }
    let reuse_total = reuse_start.elapsed();

    println!("members={}", pool.mementos.len());
    println!(
        "cold: {} calls, total={:?}, avg={:?}",
        n,
        cold_total,
        cold_total / n
    );
    println!(
        "warm: first_load={:?}, reuse avg={:?}",
        first_load,
        reuse_total / n
    );
}
