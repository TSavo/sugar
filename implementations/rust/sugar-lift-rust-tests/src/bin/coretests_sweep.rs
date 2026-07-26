// coretests_sweep: measure the delta to stdlib-0.
//
// Walks a corpus of Rust test files (coretests/tests/**), runs the assertion
// lifter over each, and produces a ledger that classifies EVERY assertion
// surface invocation into exactly one of three bins:
//
//   discharged  -- lifted to a FOL atom (one invariant operand per assertion)
//   refused     -- the lifter emitted a named warning (loudly-bounded-lossy)
//   missing     -- seen in source but neither lifted nor warned (a SILENT DROP)
//
// 100% on stdlib == missing == 0, with every refusal carrying an honest
// reason. This binary computes that number and the reason histogram (the
// remaining roadmap). It does NOT decide whether a refusal is honest vs a
// missing reduction -- that is an architect judgement made from the histogram.
//
// Usage: coretests_sweep <corpus-dir> [--json <out.json>]

use std::collections::BTreeMap;

use sugar_lift_rust_tests::cargo_cfg::{
    cargo_cfg_options_from_lifter_args, lift_options_from_rust_build_cfg,
};
use sugar_lift_rust_tests::closed_eval::{self, HarnessResult};
use sugar_lift_rust_tests::{
    assertion_surface_census, lift_file_with_all_source_imports, refusal_disposition,
    ConstSourceRegistry, Disposition, FunctionSourceRegistry, MacroRegistry,
};
use syn::visit::{self, Visit};
use tracing::{debug, info, warn};

/// Dissolve a batch of gated stdlib-sugar asserts: count how many hold under the pinned
/// toolchain. One batched harness; on a batch COMPILE error (one bad assert sinks the
/// lot) fall back to per-assert so the rest still salvage. Non-determinism / unavailable
/// toolchain -> 0 (dissolve nothing).
/// The pinned toolchain that compiles the harness. The corpus is nightly stdlib-test
/// code (heavy `#![feature(...)]`), so the harness is compiled under the matching
/// nightly -- the same toolchain the vendor's tests assume (the named, pinned axiom).
fn harness_rustc_args() -> Vec<String> {
    vec!["run".into(), "nightly-2026-02-07".into(), "rustc".into()]
}

/// Prune `#![feature(...)]` gates the pinned nightly no longer accepts (features that
/// STABILIZED since the corpus's toolchain -- the gate is now an "unknown feature"
/// error while the method is stable, so dropping the gate is sound; behavior is
/// unchanged). Iterates until the feature prelude compiles a trivial harness.
fn prune_feature_prelude(feature_prelude: &str, dir: &std::path::Path) -> String {
    let mut feats: Vec<String> = feature_prelude
        .lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| l.to_string())
        .collect();
    let args = harness_rustc_args();
    for _ in 0..40 {
        let src = format!("{}\nfn main() {{}}\n", feats.join("\n"));
        let src_path = dir.join("feature_probe.rs");
        if std::fs::write(&src_path, &src).is_err() {
            return feats.join("\n");
        }
        let out = match std::process::Command::new("rustup")
            .args(&args)
            .arg("--edition")
            .arg("2021")
            .arg("-A")
            .arg("warnings")
            .arg(&src_path)
            .arg("-o")
            .arg(dir.join("feature_probe_bin"))
            .output()
        {
            Ok(o) => o,
            Err(_) => return feats.join("\n"),
        };
        if out.status.success() {
            return feats.join("\n");
        }
        let stderr = String::from_utf8_lossy(&out.stderr);
        // collect every `unknown feature \`X\`` and drop the matching gate line.
        let mut unknown: Vec<String> = Vec::new();
        for line in stderr.lines() {
            if let Some(idx) = line.find("unknown feature `") {
                let rest = &line[idx + "unknown feature `".len()..];
                if let Some(end) = rest.find('`') {
                    unknown.push(rest[..end].to_string());
                }
            }
        }
        if unknown.is_empty() {
            // a non-feature error -- stop pruning, return what we have.
            return feats.join("\n");
        }
        feats.retain(|l| !unknown.iter().any(|u| l.contains(&format!("feature({u})"))));
    }
    feats.join("\n")
}

fn dissolve_count(prelude: &str, setup: &str, asserts: &[String], dir: &std::path::Path) -> usize {
    if asserts.is_empty() {
        return 0;
    }
    let args = harness_rustc_args();
    match closed_eval::evaluate_asserts(prelude, setup, asserts, "rustup", &args, "2021", dir) {
        HarnessResult::Ran(held) => held.iter().filter(|&&h| h).count(),
        // Any non-clean BATCH result -- a compile error, run nondeterminism, or an
        // unavailable run -- may be caused by a SINGLE bad assert poisoning the whole
        // batch (e.g. a carried macro invocation whose expansion needs an unreachable
        // API, or one assert whose run varies). Fall back to evaluating each assert in
        // ISOLATION so the rest still dissolve. Each per-assert eval keeps its own
        // double-run determinism guard, so this only ever recovers a genuinely
        // deterministic green assert -- never a new false-discharge, only fewer lost.
        _ => asserts
            .iter()
            .filter(|a| {
                matches!(
                    closed_eval::evaluate_asserts(prelude, setup, std::slice::from_ref(a), "rustup", &args, "2021", dir),
                    HarnessResult::Ran(held) if held.first() == Some(&true)
                )
            })
            .count(),
    }
}

/// Legacy sweep denominator: any macro whose name starts with assert or
/// debug_assert. Kept while the tracing proves which residual sites are real
/// factory/accounting gaps versus prefix-only ghosts. This is diagnostic, not a
/// source of assertion semantics.
fn is_assert_macro_name(name: &str) -> bool {
    name.starts_with("assert") || name.starts_with("debug_assert")
}

fn macro_path_string(mac: &syn::Macro) -> String {
    mac.path
        .segments
        .iter()
        .map(|s| s.ident.to_string())
        .collect::<Vec<_>>()
        .join("::")
}

/// Diagnostic only: the old prefix denominator. This does not contribute to the
/// accounting identity; it tells us when a human-looking assert name is not a
/// direct factory assertion surface, so the trace can explain apparent residuals.
#[derive(Default)]
struct LegacyPrefixCounter {
    total: usize,
    not_direct_factory: usize,
}

impl<'ast> Visit<'ast> for LegacyPrefixCounter {
    fn visit_macro(&mut self, mac: &'ast syn::Macro) {
        if let Some(seg) = mac.path.segments.last() {
            let name = seg.ident.to_string();
            let prefix_counted = is_assert_macro_name(&name);
            let factory_surface = sugar_lift_rust_tests::macro_is_assertion_surface(mac);
            if prefix_counted {
                self.total += 1;
                let site_cid = sugar_lift_rust_tests::assertion_surface_site_cid(mac);
                if factory_surface {
                    tracing::trace!(
                        target: "coretests_sweep::assertion_denominator",
                        macro_name = %name,
                        macro_path = %macro_path_string(mac),
                        site_cid = %site_cid,
                        tokens = %mac.tokens,
                        "legacy prefix denominator counted a factory assertion surface"
                    );
                } else {
                    self.not_direct_factory += 1;
                    tracing::debug!(
                        target: "coretests_sweep::assertion_denominator",
                        macro_name = %name,
                        macro_path = %macro_path_string(mac),
                        site_cid = %site_cid,
                        tokens = %mac.tokens,
                        "legacy prefix denominator counted macro that the factory did not classify as a direct assertion surface"
                    );
                }
            } else if factory_surface {
                tracing::warn!(
                    target: "coretests_sweep::assertion_denominator",
                    macro_name = %name,
                    macro_path = %macro_path_string(mac),
                    tokens = %mac.tokens,
                    "factory assertion surface was not counted by the legacy prefix denominator"
                );
            }
        }
        visit::visit_macro(self, mac);
    }
}

/// Normalize a per-assertion refusal reason into a bucket key so the histogram
/// groups by failure SHAPE, not by the specific value/name that triggered it.
/// Backtick-quoted spans (the concrete got-value or symbol) are erased.
fn bucket(reason: &str) -> String {
    // Drop backtick-quoted specifics: `b"abc"`, `Foo::bar`, etc.
    let mut cleaned = String::new();
    let mut in_tick = false;
    for c in reason.chars() {
        if c == '`' {
            in_tick = !in_tick;
            continue;
        }
        if !in_tick {
            cleaned.push(c);
        }
    }
    // Drop a trailing "got ..." / "skipped: ..." specific tail.
    let head = cleaned
        .split(", got")
        .next()
        .unwrap_or(&cleaned)
        .split("; skipped:")
        .next()
        .unwrap_or(&cleaned)
        .trim()
        .to_lowercase();
    let head = head.trim_end_matches(|c: char| c == ':' || c.is_whitespace());
    let head = head.trim();
    if head.is_empty() {
        reason.trim().to_lowercase()
    } else {
        // NO TRUNCATION. The full normalized shape is the bucket key. Merging is
        // done by erasing backtick-quoted SPECIFICS (above), not by cutting the
        // string -- truncating split the call-site-inlining family across dozens
        // of per-helper-name keys and hid a 521-strong rung. Variable parts belong
        // in backticks at the emission site so they are erased here, not chopped.
        head.to_string()
    }
}

fn rel_path_for_scan_root(path: &std::path::Path, root: &str) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .to_string()
}

#[derive(Default)]
struct Totals {
    files: usize,
    parse_ok: usize,
    parse_fail: usize,
    assert_macros: usize,
    test_fns_seen: usize,
    test_fns_lifted: usize,
    discharged: usize,
    // The named non-discharged total, split by disposition. `refused` =
    // terminal, closed with a source-property reason; `unclassified` = a lifter
    // limitation, i.e. WORK. `refused + unclassified` is the old "refused" count.
    refused: usize,
    unclassified: usize,
    inactive: usize,
    // Files whose lift panicked and were binned whole by the per-file panic
    // boundary. Non-zero means the ledger below is a floor, not a full reading.
    panicked_files: usize,
    // Files killed by a per-file budget, split by WHICH budget, because the two
    // name different defects and have different fixes. Same floor semantics as
    // `panicked_files`: non-zero means the counts above are a floor. A budget kill
    // is NOT an unwind -- `catch_unwind` cannot see one -- so these are counted
    // separately even though all three bin unclassified.
    //
    // `cpu_budget_exceeded`: the lift burned its CPU budget. That is unbounded work
    // in the FILE, and it is load-independent -- a starved process cannot trip it.
    // `wall_stall_timeout`: the lift sat past a generous wall budget without burning
    // its CPU budget. That is a deadlock, blocked I/O, or a child doing nothing --
    // invisible to a CPU budget precisely because it consumes no CPU.
    cpu_budget_exceeded: usize,
    wall_stall_timeout: usize,
}

/// Every counter in `Totals`, as (wire name, reader, writer). ONE list, so a field
/// added to `Totals` is serialized, parsed and merged by construction -- a new
/// counter cannot silently fail to cross the child/parent boundary.
///
/// This is the whole child/parent protocol for the scalar half of a contribution.
#[allow(clippy::type_complexity)]
const TOTALS_WIRE: &[(&str, fn(&Totals) -> usize, fn(&mut Totals, usize))] = &[
    ("files", |t| t.files, |t, v| t.files += v),
    ("parse_ok", |t| t.parse_ok, |t, v| t.parse_ok += v),
    ("parse_fail", |t| t.parse_fail, |t, v| t.parse_fail += v),
    (
        "assert_macros",
        |t| t.assert_macros,
        |t, v| t.assert_macros += v,
    ),
    (
        "test_fns_seen",
        |t| t.test_fns_seen,
        |t, v| t.test_fns_seen += v,
    ),
    (
        "test_fns_lifted",
        |t| t.test_fns_lifted,
        |t, v| t.test_fns_lifted += v,
    ),
    ("discharged", |t| t.discharged, |t, v| t.discharged += v),
    ("refused", |t| t.refused, |t, v| t.refused += v),
    (
        "unclassified",
        |t| t.unclassified,
        |t, v| t.unclassified += v,
    ),
    ("inactive", |t| t.inactive, |t, v| t.inactive += v),
    (
        "panicked_files",
        |t| t.panicked_files,
        |t, v| t.panicked_files += v,
    ),
    (
        "cpu_budget_exceeded",
        |t| t.cpu_budget_exceeded,
        |t, v| t.cpu_budget_exceeded += v,
    ),
    (
        "wall_stall_timeout",
        |t| t.wall_stall_timeout,
        |t, v| t.wall_stall_timeout += v,
    ),
];

/// One file's contribution to the sweep, as produced by a `--only <rel>` child and
/// merged by the driver. Every accumulator the per-file loop mutates appears here;
/// merging is addition for the counters and extension for the collections, so a
/// driver run and an in-process run over the same file set produce the same ledger.
#[derive(Default)]
struct FileContribution {
    totals: Totals,
    site_cids: Vec<String>,
    reasons: BTreeMap<String, usize>,
    reason_samples: BTreeMap<String, Vec<String>>,
    all_reasons: Vec<String>,
    rows: Vec<(String, usize, usize, usize, i64, bool)>,
    dissolved: usize,
}

impl FileContribution {
    fn to_json(&self) -> serde_json::Value {
        let mut totals = serde_json::Map::new();
        for (name, get, _) in TOTALS_WIRE {
            totals.insert((*name).into(), get(&self.totals).into());
        }
        let rows: Vec<serde_json::Value> = self
            .rows
            .iter()
            .map(|(rel, a, d, r, delta, ok)| {
                serde_json::json!([rel, a, d, r, delta, ok])
            })
            .collect();
        serde_json::json!({
            "totals": serde_json::Value::Object(totals),
            "site_cids": self.site_cids,
            "reasons": self.reasons,
            "reason_samples": self.reason_samples,
            "all_reasons": self.all_reasons,
            "rows": rows,
            "dissolved": self.dissolved,
        })
    }

    fn from_json(v: &serde_json::Value) -> Result<Self, String> {
        let mut c = FileContribution::default();
        let t = v.get("totals").ok_or("contribution has no `totals`")?;
        for (name, _, add) in TOTALS_WIRE {
            let n = t
                .get(*name)
                .and_then(|n| n.as_u64())
                .ok_or_else(|| format!("contribution totals missing `{name}`"))?;
            add(&mut c.totals, n as usize);
        }
        let arr = |k: &str| -> Result<&Vec<serde_json::Value>, String> {
            v.get(k)
                .and_then(|x| x.as_array())
                .ok_or_else(|| format!("contribution missing array `{k}`"))
        };
        c.site_cids = arr("site_cids")?
            .iter()
            .filter_map(|s| s.as_str().map(str::to_string))
            .collect();
        c.all_reasons = arr("all_reasons")?
            .iter()
            .filter_map(|s| s.as_str().map(str::to_string))
            .collect();
        for (k, n) in v
            .get("reasons")
            .and_then(|x| x.as_object())
            .ok_or("contribution missing `reasons`")?
        {
            c.reasons
                .insert(k.clone(), n.as_u64().unwrap_or(0) as usize);
        }
        for (k, samples) in v
            .get("reason_samples")
            .and_then(|x| x.as_object())
            .ok_or("contribution missing `reason_samples`")?
        {
            c.reason_samples.insert(
                k.clone(),
                samples
                    .as_array()
                    .map(|a| {
                        a.iter()
                            .filter_map(|s| s.as_str().map(str::to_string))
                            .collect()
                    })
                    .unwrap_or_default(),
            );
        }
        for row in arr("rows")? {
            let r = row.as_array().ok_or("contribution row is not an array")?;
            if r.len() != 6 {
                return Err(format!("contribution row has {} fields, want 6", r.len()));
            }
            c.rows.push((
                r[0].as_str().unwrap_or_default().to_string(),
                r[1].as_u64().unwrap_or(0) as usize,
                r[2].as_u64().unwrap_or(0) as usize,
                r[3].as_u64().unwrap_or(0) as usize,
                r[4].as_i64().unwrap_or(0),
                r[5].as_bool().unwrap_or(false),
            ));
        }
        c.dissolved = v.get("dissolved").and_then(|n| n.as_u64()).unwrap_or(0) as usize;
        Ok(c)
    }
}

fn main() {
    configure_proc_macro2_for_standalone_binary();
    init_tracing();
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: coretests_sweep <corpus-dir> [--json <out.json>]");
        std::process::exit(2);
    }
    let corpus = &args[1];
    info!(corpus = %corpus, "coretests sweep start");
    let json_out = args
        .iter()
        .position(|a| a == "--json")
        .and_then(|i| args.get(i + 1))
        .cloned();
    // `--dissolve`: dissolve gated closed stdlib-sugar unit-test asserts by evaluating
    // them under the pinned toolchain (shells to rustc). Off by default (hermetic).
    let dissolve = args.iter().any(|a| a == "--dissolve");
    // `--callsite-census`: STEP-1 diagnostic. Tally, per category, why the
    // call-site-inlining residue ("reachable only via call-site inlining") is
    // blocked. Pure stderr observation through the real CallsiteSugar engine; does
    // NOT touch the headline counts / ledger JSON / CID.
    let callsite_census = args.iter().any(|a| a == "--callsite-census");
    // `--per-file-timeout <secs>`: DRIVER mode. Lift each file in a CHILD PROCESS
    // bounded by a wall clock, and merge the children's contributions. A hang is not
    // an unwind -- `catch_unwind` cannot see one -- and a thread cannot be killed in
    // Rust, so an in-process cap would leave the wedged lift burning a core and
    // contaminating every timing measured after it. A child can actually be killed.
    // Off by default: without this flag the sweep runs exactly as it always has.
    let whole_secs = |flag: &str| -> Option<u64> {
        args.iter()
            .position(|a| a == flag)
            .and_then(|i| args.get(i + 1))
            .map(|s| {
                s.parse().unwrap_or_else(|_| {
                    eprintln!("{flag} wants whole seconds, got {s:?}");
                    std::process::exit(2);
                })
            })
    };
    // `--cpu-budget <secs>` turns the driver on. `--wall-stall <secs>` is the stall
    // detector and defaults to 8x the CPU budget: generous on purpose, so a merely
    // slow file under contention trips NEITHER budget, and only a lift that is not
    // burning CPU at all trips this one.
    let cpu_budget_secs = whole_secs("--cpu-budget");
    let wall_stall_secs = whole_secs("--wall-stall");
    let per_file_timeout = cpu_budget_secs;
    // `--only <rel>`: lift ONLY this corpus-relative file. Everything else is
    // unchanged -- the macro registry is still built over the whole corpus -- so a
    // child's lift sees exactly what the in-process lift would see.
    let only: Option<String> = args
        .iter()
        .position(|a| a == "--only")
        .and_then(|i| args.get(i + 1))
        .cloned();
    // `--contribution-out <path>`: write this run's contribution as JSON instead of
    // the human report. A FILE, not stdout: the driver polls the child rather than
    // draining a pipe, and a pipe that fills would deadlock the very lift we are
    // trying to bound.
    let contribution_out: Option<String> = args
        .iter()
        .position(|a| a == "--contribution-out")
        .and_then(|i| args.get(i + 1))
        .cloned();
    let dissolve_dir = std::env::temp_dir().join("sugar_dissolve_sweep");
    if dissolve {
        let _ = std::fs::create_dir_all(&dissolve_dir);
    }
    // The corpus's crate-level `#![feature(...)]` gates: the harness must declare the
    // same gates the vendor's nightly test crate does, or unstable-method asserts
    // (`'a'.is_cased()`, ...) will not compile. Lifted verbatim from the corpus lib.rs.
    let feature_prelude = if dissolve {
        std::fs::read_to_string(std::path::Path::new(corpus).join("lib.rs"))
            .map(|s| {
                s.lines()
                    .filter(|l| l.trim_start().starts_with("#![feature("))
                    .collect::<Vec<_>>()
                    .join("\n")
            })
            .unwrap_or_default()
    } else {
        String::new()
    };
    // Prune stabilized gates once, upfront, against the pinned nightly.
    let feature_prelude = if dissolve && !feature_prelude.is_empty() {
        prune_feature_prelude(&feature_prelude, &dissolve_dir)
    } else {
        feature_prelude
    };
    let mut dissolved_total = 0usize;
    // `--deps dir1,dir2,...`: dependency SOURCE trees whose macro_rules! should
    // be in scope when expanding (we operate exclusively on source).
    let dep_dirs: Vec<String> = args
        .iter()
        .position(|a| a == "--deps")
        .and_then(|i| args.get(i + 1))
        .map(|s| s.split(',').map(|p| p.to_string()).collect())
        .unwrap_or_default();

    // Build the source-graph macro registry: every macro_rules! in the corpus
    // itself plus each dependency source tree.
    let mut registry = MacroRegistry::new();
    let mut const_registry = ConstSourceRegistry::new();
    let mut fn_registry = FunctionSourceRegistry::new();
    let mut scan_dirs: Vec<&str> = vec![corpus.as_str()];
    scan_dirs.extend(dep_dirs.iter().map(|s| s.as_str()));
    let mut scanned_rs_files = 0usize;
    for dir in &scan_dirs {
        info!(dir = %dir, "coretests sweep scanning source tree");
        for entry in walkdir::WalkDir::new(dir)
            .into_iter()
            .filter_map(|e| e.ok())
        {
            let p = entry.path();
            if p.extension().and_then(|e| e.to_str()) == Some("rs") {
                scanned_rs_files += 1;
                if scanned_rs_files == 1 || scanned_rs_files % 250 == 0 {
                    info!(
                        scanned_rs_files,
                        file = %rel_path_for_scan_root(p, dir),
                        "coretests sweep source scan progress"
                    );
                }
                if let Ok(src) = std::fs::read_to_string(p) {
                    registry.scan_source(&src);
                    const_registry.scan_source(&rel_path_for_scan_root(p, dir), &src);
                    fn_registry.scan_source(&rel_path_for_scan_root(p, dir), &src);
                }
            }
        }
    }
    eprintln!(
        "macro registry: {} definitions from source ({} trees)",
        registry.len(),
        scan_dirs.len()
    );
    info!(
        definitions = registry.len(),
        trees = scan_dirs.len(),
        "coretests sweep macro registry loaded"
    );

    // Cargo/rustc cfgs are a Rust-kit input surface. The sweep harness uses the
    // same resolver as the RPC lifter so report numbers and real lift behavior
    // do not drift. Rust-specific feature overrides are lifter args
    // (`--features-override`, `--all-features`, ...), normally supplied by the
    // kit manifest command, never interpreted by the language-agnostic CLI.
    let cfg_options = match cargo_cfg_options_from_lifter_args(&args[2..]) {
        Ok(options) => options,
        Err(error) => {
            eprintln!("warning: invalid cargo cfg args ({error}); using default cfg");
            warn!(error = %error, "coretests sweep cargo cfg arg parse failed");
            Default::default()
        }
    };
    let options = match lift_options_from_rust_build_cfg(std::path::Path::new(corpus), &cfg_options)
    {
        Ok((options, report)) => {
            eprintln!(
                "build config: {} rustc facts + {} cargo feature cfg(s)",
                report.rustc_fact_count, report.cargo_feature_count
            );
            info!(
                rustc_facts = report.rustc_fact_count,
                cargo_features = report.cargo_feature_count,
                cargo_manifest = report
                    .manifest_path
                    .as_ref()
                    .map(|p| p.display().to_string())
                    .unwrap_or_else(|| "<none>".to_string()),
                "coretests sweep build config loaded from rust kit cargo/rustc cfg"
            );
            options
        }
        Err(error) => {
            eprintln!("warning: {error}; using default cfg");
            warn!(error = %error, "coretests sweep build cfg failed; using default");
            Default::default()
        }
    };
    // Sampled before any lifting, so the receipt can state the contention the run
    // started under alongside the one it ended under.
    let load_at_start = if per_file_timeout.is_some() {
        load_average_1m()
    } else {
        None
    };
    let mut totals = Totals::default();
    let mut reasons: BTreeMap<String, usize> = BTreeMap::new();
    let mut reason_samples: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut all_reasons: Vec<String> = Vec::new();
    // Per-file rows: (path, asserts, atoms, warnings, raw-accounting delta, parse_ok)
    let mut rows: Vec<(String, usize, usize, usize, i64, bool)> = Vec::new();
    // Every assertion site's content CID across the whole corpus. Sorted +
    // hashed (dups kept) into one multiset-CID below: the identity of the assertion surface,
    // so a count-preserving swap is still a moved CID.
    let mut all_site_cids: Vec<String> = Vec::new();
    // STEP-1 census rows (only populated under --callsite-census). (file, row).
    let mut census_rows: Vec<(String, sugar_lift_rust_tests::CallsiteCensusRow)> = Vec::new();

    for entry in walkdir::WalkDir::new(corpus)
        .into_iter()
        .filter_map(|e| e.ok())
    {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("rs") {
            continue;
        }
        totals.files += 1;
        let rel = path
            .strip_prefix(corpus)
            .unwrap_or(path)
            .to_string_lossy()
            .to_string();
        // `--only`: this run lifts exactly one file. The corpus walk still happens so
        // the registry and the file numbering match a full run; every other file is
        // skipped before it contributes anything.
        if let Some(target) = &only {
            if &rel != target {
                totals.files -= 1;
                continue;
            }
        }
        if totals.files == 1 || totals.files % 100 == 0 {
            info!(
                files = totals.files,
                parse_ok = totals.parse_ok,
                discharged = totals.discharged,
                refused = totals.refused,
                unclassified = totals.unclassified,
                file = %rel,
                "coretests sweep progress"
            );
        }
        // DRIVER mode: hand this file to a bounded child and merge what comes back.
        // Placed here, before any of this file's own work, so the in-process path
        // below is reached only when we are the child (or when the flag is off) --
        // one code path produces a contribution, never two.
        if let Some(cpu_secs) = cpu_budget_secs {
            let wall_secs = wall_stall_secs.unwrap_or(cpu_secs.saturating_mul(8));
            let mut contribution =
                lift_file_in_child(&rel, corpus, &args, cpu_secs, wall_secs, &mut totals);
            // The parent already counted this file in `totals.files` above; the child
            // counted it too. Drop the child's count rather than double it.
            contribution.totals.files = 0;
            merge_contribution(
                contribution,
                &mut totals,
                &mut all_site_cids,
                &mut reasons,
                &mut reason_samples,
                &mut all_reasons,
                &mut rows,
                &mut dissolved_total,
            );
            continue;
        }
        debug!(file = %rel, "coretests sweep lifting file");

        let src = match std::fs::read_to_string(path) {
            Ok(s) => s,
            Err(_) => {
                totals.parse_fail += 1;
                warn!(file = %rel, "coretests sweep could not read file");
                rows.push((rel, 0, 0, 0, 0, false));
                continue;
            }
        };
        let file = match syn::parse_file(&src) {
            Ok(f) => f,
            Err(_) => {
                totals.parse_fail += 1;
                warn!(file = %rel, "coretests sweep could not parse file");
                rows.push((rel, 0, 0, 0, 0, false));
                continue;
            }
        };
        totals.parse_ok += 1;

        let census = assertion_surface_census(&file, &registry);
        all_site_cids.extend(census.site_cids.iter().cloned());
        // CHECKPOINT the pre-lift census before the lift can hang.
        //
        // The census is recomputable from source and is what the corpus identity is
        // built from. If this child is killed mid-lift and has written nothing, that
        // file's assertion sites vanish from the multiset CID and the sweep silently
        // reports the identity of "what finished" while calling it the identity of the
        // corpus. Measured, not hypothetical: before this checkpoint a 3-file run with
        // one timed-out file produced byte-identical CID to the 2-file run without it.
        //
        // So the surface goes to disk first and the full contribution overwrites it on
        // success. A killed child still leaves its census behind.
        if let Some(path) = &contribution_out {
            let mut partial = FileContribution::default();
            partial.totals.files = 1;
            partial.totals.parse_ok = 1;
            partial.totals.assert_macros = census.total;
            partial.site_cids = census.site_cids.clone();
            let json = serde_json::to_string(&partial.to_json()).expect("partial serializes");
            if let Err(e) = std::fs::write(path, json) {
                eprintln!("coretests sweep: could not checkpoint census to {path}: {e}");
                std::process::exit(4);
            }
        }

        let mut legacy_prefix = LegacyPrefixCounter::default();
        legacy_prefix.visit_file(&file);
        if legacy_prefix.not_direct_factory > 0 {
            debug!(
                target: "coretests_sweep::assertion_denominator",
                file = %rel,
                legacy_prefix_macros = legacy_prefix.total,
                not_direct_factory = legacy_prefix.not_direct_factory,
                assertion_surface_sites = census.total,
                "legacy prefix diagnostic found macros that are not direct factory assertion surfaces"
            );
        }

        if callsite_census {
            for row in sugar_lift_rust_tests::callsite_census(&file, &options, &registry) {
                census_rows.push((rel.clone(), row));
            }
        }
        // Per-file panic boundary. A lifter gap (`iter_terminal_gap` and friends) is a
        // deliberate `-> !` loud refusal, but without a boundary here the FIRST such file
        // aborts the process and no accounting is ever written -- one gap costs the whole
        // ledger, and every file after it goes unobserved. Bin the panicking file whole as
        // UNCLASSIFIED with the panic string as the reason (see `bin_panicked_file` for why
        // that bucket and not `refused`), so its assertions stay accounted for and `silent`
        // still cannot hide anything.
        let lifted = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            lift_file_with_all_source_imports(
                &file,
                &rel,
                &options,
                &registry,
                &const_registry,
                &fn_registry,
            )
        }));
        let out = match lifted {
            Ok(out) => out,
            Err(payload) => {
                let panic_msg = panic_payload_message(&*payload);
                warn!(
                    file = %rel,
                    panic = %panic_msg,
                    asserts = census.total,
                    "coretests sweep file panicked; binning its assertions as unclassified"
                );
                bin_panicked_file(
                    &rel,
                    &panic_msg,
                    census.total,
                    &mut totals,
                    &mut reasons,
                    &mut reason_samples,
                    &mut all_reasons,
                    &mut rows,
                );
                continue;
            }
        };
        let discharged = out.assertions_lifted;
        let refused_total = out.assertions_refused;

        totals.assert_macros += census.total;
        totals.test_fns_seen += out.seen;
        totals.test_fns_lifted += out.lifted;
        totals.discharged += discharged;

        // Split the named refusals by disposition: TERMINAL (closed with a source-
        // property reason) vs UNCLASSIFIED (a lifter limitation = work). A refusal
        // counted without a reason string, or any unrecognized reason, defaults to
        // Unclassified -- the only way into `refused` is to earn it.
        let mut file_terminal = 0usize;
        let mut file_inactive = 0usize;
        for reason in &out.skip_reasons {
            let (tag, disp) = match refusal_disposition(reason) {
                Disposition::TerminalEffect => {
                    file_terminal += 1;
                    ("[refused]", ())
                }
                Disposition::Inactive => {
                    file_inactive += 1;
                    ("[inactive]", ())
                }
                Disposition::Unclassified => ("[unclassified]", ()),
            };
            let _ = disp;
            let b = format!("{} {}", tag, bucket(reason));
            *reasons.entry(b.clone()).or_insert(0) += 1;
            let samples = reason_samples.entry(b).or_default();
            if samples.len() < 12 {
                samples.push(format!("{}: {}", rel, reason));
            }
            all_reasons.push(reason.clone());
        }
        // Reconcile against the count: any refused-without-a-reason is unclassified.
        let file_terminal = file_terminal.min(refused_total);
        let file_inactive = file_inactive.min(refused_total - file_terminal);
        let file_unclassified = refused_total - file_terminal - file_inactive;

        // STDLIB-SUGAR DISSOLUTION as a per-file EXACT PARTITION. Dissolution proves closed
        // stdlib-sugar asserts green by evaluation under the pinned toolchain. By the
        // dissolution GATE these asserts use a stdlib op the symbolic lifter cannot model,
        // so a green is NEVER in the LIFTED set -- it sits in this file's UNCLASSIFIED set
        // OR, when the assert is inside a `while` body (the only terminal context that holds
        // a dissolvable green), in the TERMINAL set. `collect_dissolvable` tags each unit
        // with `under_while`, so we know each green's ACTUAL bucket and credit it there:
        // a while-body green discharges from REFUSED (residual refusal -- dissolution wins),
        // every other green from UNCLASSIFIED. Capped per bucket so none goes negative.
        // This is EXACT (no draw-order): a non-green unclassified assert can NEVER be drawn
        // down by a while-body green, so unclassified cannot be fake-zeroed as we drive to 0.
        // Per-file total contribution stays file_terminal+file_unclassified (move, not add)
        // => SILENT and callsite-expansion accounting stay exact. Hermetic (no --dissolve):
        // greens=0 => every bucket unchanged.
        let (green_unclassified, green_while) = if dissolve {
            let units = closed_eval::collect_dissolvable(&file);
            let mut gu = 0usize;
            let mut gw = 0usize;
            for u in &units {
                let full_prelude = format!("{}\n{}", feature_prelude, u.prelude);
                let g = dissolve_count(&full_prelude, &u.setup, &u.asserts, &dissolve_dir);
                if u.under_while {
                    gw += g;
                } else {
                    gu += g;
                }
            }
            (gu, gw)
        } else {
            (0, 0)
        };
        let from_terminal = green_while.min(file_terminal);
        let from_unclassified = green_unclassified.min(file_unclassified);
        let dissolved = from_unclassified + from_terminal;
        dissolved_total += dissolved;

        totals.refused += file_terminal - from_terminal;
        totals.inactive += file_inactive;
        totals.unclassified += file_unclassified - from_unclassified;
        totals.discharged += dissolved;
        let refused = refused_total;

        // Raw-accounting delta. Positive means a real assert macro the collector
        // never reached. Negative means the source body was completed at multiple
        // callsites, creating more obligations than textual assert macros.
        let raw_delta = census.total as i64 - discharged as i64 - refused as i64;
        if raw_delta > 0 {
            warn!(
                file = %rel,
                assertion_surface_sites = census.total,
                discharged = discharged,
                refused = refused,
                missing = raw_delta,
                legacy_prefix_not_direct_factory = legacy_prefix.not_direct_factory,
                "coretests sweep file has missing assertion delta"
            );
        }
        rows.push((rel, census.total, discharged, refused, raw_delta, true));
    }
    info!(
        files = totals.files,
        parse_ok = totals.parse_ok,
        discharged = totals.discharged,
        refused = totals.refused,
        unclassified = totals.unclassified,
        inactive = totals.inactive,
        "coretests sweep lift complete"
    );

    // CHILD mode: this run exists to produce one file's contribution. Write it and
    // stop -- the human report and the corpus CID belong to the driver, which is the
    // only run that has seen the whole corpus.
    if let Some(path) = &contribution_out {
        let contribution = FileContribution {
            totals,
            site_cids: all_site_cids,
            reasons,
            reason_samples,
            all_reasons,
            rows,
            dissolved: dissolved_total,
        };
        let json = serde_json::to_string(&contribution.to_json()).expect("contribution serializes");
        if let Err(e) = std::fs::write(path, json) {
            eprintln!("coretests sweep: could not write contribution to {path}: {e}");
            std::process::exit(4);
        }
        return;
    }

    // Headline reconciliation at assertion-surface granularity. `refused + unclassified` is the
    // full named non-discharged set; only their sum reconciles against the textual
    // macro count.
    let named_non_discharged = totals.refused + totals.unclassified + totals.inactive;
    // Per-file split. A positive per-file residual is a missing assertion (the
    // true silent drop). A negative per-file residual is callsite expansion: the
    // reducer inlined a helper called from several sites, lifting one textual
    // assert as several point-wise instances. Those are different facts, so the
    // public report keeps them separate:
    //
    //   raw assertion surfaces + callsite expansion - missing assertions = obligations.
    let missing_assertions: i64 = rows.iter().map(|r| r.4.max(0)).sum();
    let callsite_expansion: i64 = rows.iter().map(|r| (-r.4).max(0)).sum();
    let accounted_obligations = totals.discharged + named_non_discharged;
    let pct = |n: usize| {
        if totals.assert_macros == 0 {
            0.0
        } else {
            100.0 * n as f64 / totals.assert_macros as f64
        }
    };

    println!("==== coretests sweep: delta to stdlib-0 ====");
    println!("corpus: {}", corpus);
    println!(
        "files: {} (parse_ok {}, parse_fail {})",
        totals.files, totals.parse_ok, totals.parse_fail
    );
    println!("assertion surface sites seen: {}", totals.assert_macros);
    println!(
        "  discharged (lifted to FOL):  {:>6}  ({:.1}%)",
        totals.discharged,
        pct(totals.discharged)
    );
    if dissolve {
        println!(
            "    of which stdlib-sugar DISSOLVED by evaluation: {:>6}",
            dissolved_total
        );
    }
    println!(
        "  refused  (TERMINAL, source): {:>6}  ({:.1}%)   <-- closed with a damn good reason",
        totals.refused,
        pct(totals.refused)
    );
    println!(
        "  unclassified (lifter WORK):  {:>6}  ({:.1}%)   <-- the real roadmap; drive to 0",
        totals.unclassified,
        pct(totals.unclassified)
    );
    println!(
        "  inactive (cfg-disabled):     {:>6}  ({:.1}%)   <-- not in this target's universe",
        totals.inactive,
        pct(totals.inactive)
    );
    println!(
        "  panicked files (LIFTER GAP): {:>6}           <-- {}",
        totals.panicked_files,
        if totals.panicked_files == 0 {
            "0 = every file's lift ran to a disposition"
        } else {
            "the buckets above are a FLOOR: these files were binned whole, unclassified"
        }
    );
    println!(
        "  cpu budget exceeded (SPIN):  {:>6}           <-- {}",
        totals.cpu_budget_exceeded,
        if totals.cpu_budget_exceeded == 0 {
            "0 = no file's lift burned its cpu budget"
        } else {
            "the buckets above are a FLOOR: unbounded work, load-independent"
        }
    );
    println!(
        "  wall stall (NO CPU BURNED):  {:>6}           <-- {}",
        totals.wall_stall_timeout,
        if totals.wall_stall_timeout == 0 {
            "0 = no file's lift stalled without burning cpu"
        } else {
            "the buckets above are a FLOOR: deadlock or blocked, not spinning"
        }
    );
    // The conditions the run was measured under, stated rather than implied. A
    // timeout row means different things at load 1 and at load 12, and the reader
    // cannot recover that afterwards.
    if let Some(secs) = per_file_timeout {
        println!(
            "  per-file budgets: cpu {secs}s / wall-stall {}s   load avg 1m: start {}  end {}",
            wall_stall_secs.unwrap_or(secs.saturating_mul(8)),
            load_at_start
                .map(|l| format!("{l:.2}"))
                .unwrap_or_else(|| "unknown".into()),
            load_average_1m()
                .map(|l| format!("{l:.2}"))
                .unwrap_or_else(|| "unknown".into()),
        );
    }
    println!(
        "  missing assertions (SILENT): {:>6}  ({:.1}%)   <-- delta target = 0",
        missing_assertions,
        pct(missing_assertions.max(0) as usize)
    );
    println!(
        "  callsite-expanded obligations:{:>5}   (source body completed at N call sites)",
        callsite_expansion
    );
    println!(
        "  accounting identity: {} raw surfaces + {} expanded - {} missing = {} accounted",
        totals.assert_macros, callsite_expansion, missing_assertions, accounted_obligations
    );
    println!(
        "test fns: seen {} / lifted {}",
        totals.test_fns_seen, totals.test_fns_lifted
    );
    println!();
    println!("---- refusal reason histogram (the roadmap) ----");
    let mut reason_vec: Vec<(&String, &usize)> = reasons.iter().collect();
    reason_vec.sort_by(|a, b| b.1.cmp(a.1));
    for (reason, count) in &reason_vec {
        println!("  {:>6}  {}", count, reason);
    }
    println!();
    println!("---- top files by missing assertions (silent drops) ----");
    let mut by_unacc: Vec<&(String, usize, usize, usize, i64, bool)> = rows.iter().collect();
    by_unacc.sort_by(|a, b| b.4.cmp(&a.4));
    for (rel, asserts, discharged, refused, unacc, ok) in by_unacc.iter().take(30) {
        if *unacc <= 0 {
            break;
        }
        println!(
            "  {:>5} silent  ({} asserts, {} discharged, {} refused){}  {}",
            unacc,
            asserts,
            discharged,
            refused,
            if *ok { "" } else { " [parse_fail]" },
            rel
        );
    }

    // The assertion-surface multiset-CID: sort the site CIDs, keep dups (order-independent, multiplicity-preserving
    // identity) and content-address the array. Recomputable from source.
    all_site_cids.sort();
    let assertion_multiset_cid = sugar_canonicalizer::jcs_cid_of_json(&serde_json::Value::Array(
        all_site_cids
            .iter()
            .map(|c| serde_json::Value::from(c.clone()))
            .collect(),
    ));
    println!("assertion multiset cid: {}", assertion_multiset_cid);

    if callsite_census {
        report_callsite_census(&census_rows);
    }

    if let Some(out_path) = json_out {
        let json = build_ledger_json(
            corpus,
            &totals,
            &reasons,
            &reason_samples,
            &all_reasons,
            &rows,
            &assertion_multiset_cid,
        );
        // The silence gets a CID: content-address the ledger over its JCS
        // canonical form (recomputable from the file: parse -> JCS -> hash),
        // so the residual is a pinned object, not a printout.
        let cid = sugar_canonicalizer::jcs_cid_of_json(&json);
        if let Err(e) = std::fs::write(&out_path, serde_json::to_string_pretty(&json).unwrap()) {
            eprintln!("failed to write {}: {}", out_path, e);
        } else if let Err(e) = std::fs::write(format!("{out_path}.cid"), &cid) {
            eprintln!("failed to write {}.cid: {}", out_path, e);
        } else {
            println!("\nwrote ledger json: {}", out_path);
            println!("ledger cid: {}", cid);
            info!(path = %out_path, cid = %cid, "coretests sweep wrote ledger");
        }
    }
}

fn configure_proc_macro2_for_standalone_binary() {
    // This executable parses and rewrites tokens, but it is not a procedural
    // macro and therefore never has rustc's proc-macro bridge available.
    // Avoid proc-macro2's runtime bridge detection selecting compiler-backed
    // spans on newer toolchains; those spans panic as soon as they touch the
    // inactive bridge.
    proc_macro2::fallback::force();
}

fn init_tracing() {
    let filter = if std::env::var_os("RUST_LOG").is_some() {
        tracing_subscriber::EnvFilter::builder()
            .with_default_directive(tracing_subscriber::filter::LevelFilter::WARN.into())
            .from_env_lossy()
    } else {
        tracing_subscriber::EnvFilter::new("warn,coretests_sweep=info,sugar_lift_rust_tests=info")
    };
    if let Ok(path) = std::env::var("SUGAR_LOG_FILE") {
        match std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
        {
            Ok(file) => {
                tracing_subscriber::fmt()
                    .with_writer(file)
                    .with_ansi(false)
                    .with_env_filter(filter)
                    .init();
            }
            Err(error) => {
                eprintln!(
                    "warning: could not open SUGAR_LOG_FILE {path}: {error}; logging to stderr"
                );
                tracing_subscriber::fmt()
                    .with_writer(std::io::stderr)
                    .with_env_filter(filter)
                    .init();
            }
        }
    } else {
        tracing_subscriber::fmt()
            .with_writer(std::io::stderr)
            .with_env_filter(filter)
            .init();
    }
}

/// STEP-1 CENSUS REPORT (stderr). For every recognized call-site-inlining site,
/// report the category of its residue. A helper that COMMITS at any site is drained
/// (its asserts discharged); a helper that bails at every site is blocked, and the
/// category names the blocker shape (the roadmap rung). Per-helper rows let us map
/// the 112 "reachable only" asserts back to their cause.
fn report_callsite_census(rows: &[(String, sugar_lift_rust_tests::CallsiteCensusRow)]) {
    use std::collections::BTreeMap;
    use sugar_lift_rust_tests::CallsiteCensusRow;

    // Per helper: did ANY call site commit it? and the bail categories observed.
    #[derive(Default)]
    struct HelperAgg {
        committed_anywhere: bool,
        categories: BTreeMap<String, usize>,
        max_added_unclassified: usize,
        sample: Vec<String>,
        sites: usize,
    }
    let mut by_helper: BTreeMap<String, HelperAgg> = BTreeMap::new();
    for (_file, row) in rows {
        let CallsiteCensusRow {
            helper,
            category,
            added_unclassified,
            sample_reasons,
            committed,
        } = row;
        let agg = by_helper.entry(helper.clone()).or_default();
        agg.sites += 1;
        if *committed {
            agg.committed_anywhere = true;
        } else {
            *agg.categories.entry(format!("{category:?}")).or_insert(0) += 1;
            agg.max_added_unclassified = agg.max_added_unclassified.max(*added_unclassified);
            for s in sample_reasons {
                if agg.sample.len() < 4 && !agg.sample.contains(s) {
                    agg.sample.push(s.clone());
                }
            }
        }
    }

    // Headline category tally over BLOCKED helpers (committed-nowhere): one count per
    // helper, by its dominant bail category (the first observed non-empty bucket).
    let mut blocked_by_cat: BTreeMap<String, usize> = BTreeMap::new();
    let mut committed = 0usize;
    let mut blocked = 0usize;
    for (_h, agg) in &by_helper {
        if agg.committed_anywhere {
            committed += 1;
            continue;
        }
        blocked += 1;
        if let Some((cat, _)) = agg.categories.iter().max_by_key(|(_, n)| **n) {
            *blocked_by_cat.entry(cat.clone()).or_insert(0) += 1;
        }
    }

    eprintln!();
    eprintln!("==== STEP-1 callsite-inlining census (diagnostic) ====");
    eprintln!(
        "recognized helper call sites: {} (distinct helpers: {})",
        rows.len(),
        by_helper.len()
    );
    eprintln!("  committed (drained) helpers:  {committed}");
    eprintln!("  blocked helpers:              {blocked}");
    eprintln!("  -- blocked-helper category histogram (one per blocked helper) --");
    for (cat, n) in &blocked_by_cat {
        eprintln!("     {n:>4}  {cat}");
    }
    eprintln!("  -- per-blocked-helper detail --");
    for (h, agg) in &by_helper {
        if agg.committed_anywhere {
            continue;
        }
        let cats: Vec<String> = agg
            .categories
            .iter()
            .map(|(c, n)| format!("{c}×{n}"))
            .collect();
        eprintln!(
            "     {h}: sites={} max_added_unclassified={} [{}]",
            agg.sites,
            agg.max_added_unclassified,
            cats.join(", ")
        );
        for s in &agg.sample {
            eprintln!("         · {s}");
        }
    }
    // Also surface helpers committed at one site but with no-arg-call only (drained).
    let drained: Vec<&String> = by_helper
        .iter()
        .filter(|(_, a)| a.committed_anywhere)
        .map(|(h, _)| h)
        .collect();
    eprintln!("  -- committed (drained) helpers: {} --", drained.len());
    for h in drained {
        eprintln!("     {h}");
    }
    eprintln!("==== end census ====");
}

/// Which budget killed a child. The two are separate axes in the ledger because
/// they name different defects: unbounded work in the file versus a lift that is
/// not running at all.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum KillCause {
    CpuBudget,
    WallStall,
}

impl KillCause {
    fn axis(self) -> &'static str {
        match self {
            KillCause::CpuBudget => "cpu_budget_exceeded",
            KillCause::WallStall => "wall_stall_timeout",
        }
    }
}

/// CPU seconds a live process has burned, via `ps`. Used to classify a timeout.
///
/// A wall clock cannot tell a hang from starvation; CPU time can, and the kernel
/// already tracks it. A file that burns its bound in CPU is spinning no matter what
/// else is on the box. A file that sat starved accrues CPU slowly and its row says
/// so. This is read just before the kill, while the process still exists.
///
/// `ps` rather than `getrusage`: `libc` is not a dependency of this crate and one
/// spawn on the timeout path -- which is rare and already expensive -- is not worth
/// adding one for. `None` if `ps` is unavailable or its output does not parse; the
/// timeout is still recorded, just without the classifying evidence.
fn process_cpu_seconds(pid: u32) -> Option<f64> {
    let out = std::process::Command::new("ps")
        .args(["-o", "time=", "-p", &pid.to_string()])
        .output()
        .ok()?;
    let raw = String::from_utf8_lossy(&out.stdout);
    let field = raw.trim();
    if field.is_empty() {
        return None;
    }
    // `[[dd-]hh:]mm:ss[.ff]`, most-significant first once split on ':' and '-'.
    let (days, rest) = match field.split_once('-') {
        Some((d, r)) => (d.parse::<f64>().ok()?, r),
        None => (0.0, field),
    };
    let mut secs = 0.0;
    for part in rest.split(':') {
        secs = secs * 60.0 + part.parse::<f64>().ok()?;
    }
    Some(days * 86_400.0 + secs)
}

/// Classify a timeout from CPU-vs-wall, so the row carries the evidence instead of
/// a caveat.
///
/// A wall clock alone cannot tell a hang from starvation, and on a shared box that
/// ambiguity lands in the published number: at load ~12 a file that never had the
/// CPU looks identical to one spinning. CPU time separates them, because a process
/// burning a core is burning it regardless of what else is running.
///
/// The 0.5 threshold is a deliberate policy choice, not a measurement: at or above
/// half a core sustained across the whole bound, the lift is doing real work and the
/// bound is a statement about the FILE. Below it, the bound is a statement about the
/// BOX, and the row says so rather than quietly counting as a hang.
fn classify_timeout(cpu_secs: Option<f64>, wall_secs: f64) -> String {
    match cpu_secs {
        // `wall <= 0` cannot classify anything; fall through to "unavailable" rather
        // than divide by it.
        Some(cpu) if wall_secs > 0.0 && cpu / wall_secs >= 0.5 => {
            format!("SPINNING (cpu {cpu:.0}s of {wall_secs:.0}s wall)")
        }
        Some(cpu) if wall_secs > 0.0 => format!(
            "STARVED, bound not attributable to this file (cpu {cpu:.0}s of {wall_secs:.0}s wall)"
        ),
        _ => "cpu time unavailable".to_string(),
    }
}

/// The 1-minute load average, for the sweep receipt. A timeout row is only
/// interpretable against the contention it was measured under, so the run states
/// the conditions rather than implying them.
fn load_average_1m() -> Option<f64> {
    let out = std::process::Command::new("sysctl")
        .args(["-n", "vm.loadavg"])
        .output()
        .ok()?;
    // `{ 12.41 11.58 13.91 }`
    String::from_utf8_lossy(&out.stdout)
        .split_whitespace()
        .nth(1)
        .and_then(|s| s.parse().ok())
}

/// Merge one file's contribution into the sweep accumulators. Addition for the
/// counters, extension for the collections -- the same mutations the in-process
/// loop makes, applied from the wire instead of from local state.
#[allow(clippy::too_many_arguments)]
fn merge_contribution(
    c: FileContribution,
    totals: &mut Totals,
    all_site_cids: &mut Vec<String>,
    reasons: &mut BTreeMap<String, usize>,
    reason_samples: &mut BTreeMap<String, Vec<String>>,
    all_reasons: &mut Vec<String>,
    rows: &mut Vec<(String, usize, usize, usize, i64, bool)>,
    dissolved_total: &mut usize,
) {
    for (_, get, add) in TOTALS_WIRE {
        add(totals, get(&c.totals));
    }
    all_site_cids.extend(c.site_cids);
    for (k, n) in c.reasons {
        *reasons.entry(k).or_insert(0) += n;
    }
    for (k, samples) in c.reason_samples {
        let dst = reason_samples.entry(k).or_default();
        for s in samples {
            // Same cap the in-process path applies, so the sample set does not
            // depend on whether the run was driven or in-process.
            if dst.len() < 12 {
                dst.push(s);
            }
        }
    }
    all_reasons.extend(c.all_reasons);
    rows.extend(c.rows);
    *dissolved_total += c.dissolved;
}

/// Lift one file in a CHILD PROCESS bounded by a wall clock, and return its
/// contribution.
///
/// The bound is the whole point: `num/int_sqrt.rs` ran 28m30s at ~90% CPU without
/// reaching a verdict, so this is live computation, not a deadlock, and nothing
/// cooperative will stop it. A killed child stops.
///
/// On timeout the file is binned like a panic -- whole, UNCLASSIFIED, reason named --
/// following `discharge_sweep`'s rule that a timeout is counted UNDECIDED and never
/// as "cannot be checked" (`solver_timeout_is_counted_undecided_not_uncheckable`).
/// It is counted in `timed_out_files` rather than `panicked_files` because the two
/// have different mechanisms and different fixes.
fn lift_file_in_child(
    rel: &str,
    corpus: &str,
    args: &[String],
    cpu_budget_secs: u64,
    wall_stall_secs: u64,
    totals: &mut Totals,
) -> FileContribution {
    let out_path = std::env::temp_dir().join(format!(
        "coretests_sweep_contribution_{}_{}.json",
        std::process::id(),
        rel.replace(['/', '\\', '.'], "_")
    ));
    let _ = std::fs::remove_file(&out_path);
    let exe = match std::env::current_exe() {
        Ok(e) => e,
        Err(e) => {
            // Cannot find ourselves to re-exec: that is a broken run, not a result.
            eprintln!("coretests sweep: cannot resolve current exe for --only child: {e}");
            std::process::exit(4);
        }
    };
    let mut cmd = std::process::Command::new(exe);
    cmd.arg(corpus)
        .arg("--only")
        .arg(rel)
        .arg("--contribution-out")
        .arg(&out_path);
    // Carry through the flags that change what a lift MEANS, so a child measures the
    // same thing the parent would have. `--per-file-timeout` is deliberately NOT
    // carried: the child is the bounded unit, and passing it on would recurse.
    for flag in ["--rustc-cfg", "--dissolve", "--callsite-census"] {
        if args.iter().any(|a| a == flag) {
            cmd.arg(flag);
        }
    }
    if let Some(i) = args.iter().position(|a| a == "--deps") {
        if let Some(v) = args.get(i + 1) {
            cmd.arg("--deps").arg(v);
        }
    }
    let started = std::time::Instant::now();
    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("coretests sweep: cannot spawn --only child for {rel}: {e}");
            std::process::exit(4);
        }
    };
    // DUAL BUDGETS. Neither alone is sufficient:
    //
    //   CPU budget  catches a spinning lift (`num/int_sqrt.rs`) and CANNOT be tripped
    //               by contention -- a starved process accrues CPU slowly. This is
    //               what makes the verdict independent of what else is on the box.
    //   wall stall  catches deadlock, blocked I/O, or a child consuming no CPU at
    //               all -- which the CPU budget can never see, because the whole
    //               signature of that failure is that no CPU is burned.
    //
    // The wall budget is deliberately generous: it is a stall detector, not a
    // performance bound, so a merely slow file under load is killed by neither.
    let cpu_budget = cpu_budget_secs as f64;
    let wall_deadline = std::time::Duration::from_secs(wall_stall_secs);
    let mut cpu_at_kill: Option<f64> = None;
    let mut kill_cause: Option<KillCause> = None;
    // `ps` is a spawn per sample, so sample on an interval rather than every poll.
    let mut last_cpu_sample = std::time::Instant::now();
    let mut last_cpu_seen: Option<f64> = None;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) => {
                if last_cpu_sample.elapsed() >= std::time::Duration::from_secs(2) {
                    last_cpu_sample = std::time::Instant::now();
                    last_cpu_seen = process_cpu_seconds(child.id());
                    if let Some(cpu) = last_cpu_seen {
                        if cpu >= cpu_budget {
                            cpu_at_kill = Some(cpu);
                            kill_cause = Some(KillCause::CpuBudget);
                            let _ = child.kill();
                            let _ = child.wait();
                            break None;
                        }
                    }
                }
                if started.elapsed() >= wall_deadline {
                    cpu_at_kill = process_cpu_seconds(child.id()).or(last_cpu_seen);
                    kill_cause = Some(KillCause::WallStall);
                    let _ = child.kill();
                    let _ = child.wait();
                    break None;
                }
                std::thread::sleep(std::time::Duration::from_millis(50));
            }
            Err(e) => {
                eprintln!("coretests sweep: cannot wait on --only child for {rel}: {e}");
                let _ = child.kill();
                break None;
            }
        }
    };
    let elapsed = started.elapsed();

    if status.is_none() {
        let wall = elapsed.as_secs_f64();
        let cause = kill_cause.unwrap_or(KillCause::WallStall);
        let verdict = classify_timeout(cpu_at_kill, wall);
        warn!(
            file = %rel,
            budget = %cause.axis(),
            cpu_budget_secs,
            wall_stall_secs,
            wall_secs = wall,
            cpu_secs = cpu_at_kill,
            verdict = %verdict,
            load_1m = load_average_1m(),
            "coretests sweep file exceeded a per-file budget; killed and binned as unclassified"
        );
        // Recover the census the child checkpointed BEFORE it started lifting. That
        // surface is real and recomputable from source; losing it would drop the file's
        // sites out of the corpus multiset CID and quietly redefine the identity as
        // "whatever finished in time".
        let mut c = std::fs::read_to_string(&out_path)
            .ok()
            .and_then(|raw| serde_json::from_str::<serde_json::Value>(&raw).ok())
            .and_then(|v| FileContribution::from_json(&v).ok())
            .unwrap_or_default();
        let _ = std::fs::remove_file(&out_path);
        // The checkpoint carries the surface; the disposition is ours to write. Bin the
        // whole surface UNCLASSIFIED with the timeout named, exactly as a panic binned
        // whole -- the kill landed before any per-assert disposition existed, so which
        // assertions the hang belongs to is not known.
        let census_total = c.totals.assert_macros;
        c.totals.files = 1;
        c.totals.parse_ok = 1;
        match cause {
            KillCause::CpuBudget => c.totals.cpu_budget_exceeded = 1,
            KillCause::WallStall => c.totals.wall_stall_timeout = 1,
        }
        c.totals.unclassified += census_total;
        let reason = match cause {
            KillCause::CpuBudget => {
                format!("lift cpu budget exceeded: burned {cpu_budget_secs}s cpu")
            }
            KillCause::WallStall => {
                format!("lift wall stall: {wall_stall_secs}s wall without burning its cpu budget")
            }
        };
        let b = format!("[unclassified] {}", bucket(&reason));
        // One reason per assertion when the surface is known, so `all_reasons` stays
        // one-per-assertion and the histogram sums to the bucket.
        let named = census_total.max(1);
        *c.reasons.entry(b.clone()).or_insert(0) += named;
        // The per-file sample carries the classification, so a reader of the ledger
        // can tell a real hang from a contention artifact without re-running anything.
        c.reason_samples
            .entry(b)
            .or_default()
            .push(format!("{rel}: {reason} -- {verdict}"));
        for _ in 0..named {
            c.all_reasons.push(reason.clone());
        }
        // `raw_delta = 0`: nothing was silently dropped, the surface is accounted as
        // unclassified. `parse_ok = true`: the file parsed, then its lift ran long.
        c.rows
            .push((rel.to_string(), census_total, 0, census_total, 0, true));
        return c;
    }

    let status = status.expect("checked above");
    let raw = std::fs::read_to_string(&out_path);
    let _ = std::fs::remove_file(&out_path);
    let raw = match raw {
        Ok(r) => r,
        Err(e) => {
            // The child exited without leaving a contribution. That is a broken run,
            // not a zero: exiting loudly beats folding a silent nothing into the ledger.
            eprintln!(
                "coretests sweep: --only child for {rel} exited {status} without a \
                 contribution ({e}); refusing to fold a silent nothing into the ledger"
            );
            std::process::exit(4);
        }
    };
    let value: serde_json::Value = match serde_json::from_str(&raw) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("coretests sweep: --only child for {rel} wrote unparseable contribution: {e}");
            std::process::exit(4);
        }
    };
    match FileContribution::from_json(&value) {
        Ok(c) => {
            debug!(file = %rel, secs = elapsed.as_secs_f64(), "coretests sweep child finished");
            let _ = totals;
            c
        }
        Err(e) => {
            eprintln!("coretests sweep: --only child for {rel} wrote a contribution we cannot merge: {e}");
            std::process::exit(4);
        }
    }
}

/// The panic payload's message, flattened to one line so it survives a reason
/// histogram row. A non-string payload is NAMED, never dropped silently.
fn panic_payload_message(payload: &(dyn std::any::Any + Send)) -> String {
    payload
        .downcast_ref::<String>()
        .map(String::as_str)
        .or_else(|| payload.downcast_ref::<&str>().copied())
        .unwrap_or("<non-string panic payload>")
        .replace('\n', " ")
}

/// Bin a file whose lift PANICKED, whole, into the ledger.
///
/// UNCLASSIFIED, not `refused`. `refused` is reserved for a terminal close with a
/// source-property reason, and the sweep cannot show that here: the panic unwound
/// before any per-assert disposition existed, so we do not know which of this file's
/// assertions the gap actually hit. Unclassified is the honest bucket -- it says
/// "work", it keeps the gap loud in the gate rather than parked in an earned-refusal
/// bucket, and it holds the `silent = 0` identity because the assertions stay counted.
///
/// Extracted from the sweep loop so the BINNING is testable, not just the field it
/// writes: `panic_bins_unclassified_not_refused` below is the tooth on that choice.
#[allow(clippy::too_many_arguments)]
fn bin_panicked_file(
    rel: &str,
    panic_msg: &str,
    census_total: usize,
    totals: &mut Totals,
    reasons: &mut BTreeMap<String, usize>,
    reason_samples: &mut BTreeMap<String, Vec<String>>,
    all_reasons: &mut Vec<String>,
    rows: &mut Vec<(String, usize, usize, usize, i64, bool)>,
) {
    let reason = format!("lifter panic: {panic_msg}");
    totals.assert_macros += census_total;
    totals.unclassified += census_total;
    totals.panicked_files += 1;
    let b = format!("[unclassified] {}", bucket(&reason));
    *reasons.entry(b.clone()).or_insert(0) += census_total;
    let samples = reason_samples.entry(b).or_default();
    if samples.len() < 12 {
        samples.push(format!("{rel}: {reason}"));
    }
    for _ in 0..census_total {
        all_reasons.push(reason.clone());
    }
    // `parse_ok = true`: this file PARSED and then panicked during the lift. Those are
    // two different failures and the flag only means the first one -- reporting
    // `[parse_fail]` here would name the wrong defect in the top-files table.
    // `raw_delta = 0` keeps `missing_assertions` unmoved: nothing was silently dropped.
    rows.push((rel.to_string(), census_total, 0, census_total, 0, true));
}

/// The sweep ledger as a JSON value: the total accounting (every assertion
/// binned into discharged/refused/missing or expanded through callsites), the
/// reason histogram, and the per-file rows. Pure so the shape -- and the CID
/// over it -- is testable.
#[allow(clippy::too_many_arguments)]
fn build_ledger_json(
    corpus: &str,
    totals: &Totals,
    reasons: &BTreeMap<String, usize>,
    reason_samples: &BTreeMap<String, Vec<String>>,
    all_reasons: &[String],
    rows: &[(String, usize, usize, usize, i64, bool)],
    assertion_multiset_cid: &str,
) -> serde_json::Value {
    let missing_assertions: i64 = rows.iter().map(|r| r.4.max(0)).sum();
    let callsite_expansion: i64 = rows.iter().map(|r| (-r.4).max(0)).sum();
    let mut obj = serde_json::Map::new();
    obj.insert("corpus".into(), corpus.into());
    obj.insert("files".into(), totals.files.into());
    obj.insert("parse_ok".into(), totals.parse_ok.into());
    obj.insert("parse_fail".into(), totals.parse_fail.into());
    obj.insert("assert_macros".into(), totals.assert_macros.into());
    obj.insert("discharged".into(), totals.discharged.into());
    obj.insert("refused".into(), totals.refused.into());
    obj.insert("unclassified".into(), totals.unclassified.into());
    obj.insert("inactive".into(), totals.inactive.into());
    // Non-zero => the buckets above are a FLOOR. Emitted unconditionally so a
    // reader of the ledger alone can tell a full reading from a floored one.
    obj.insert("panicked_files".into(), totals.panicked_files.into());
    // Same floor semantics as `panicked_files`, different mechanism: a killed lift,
    // not an unwind. Emitted unconditionally for the same reason.
    obj.insert(
        "cpu_budget_exceeded".into(),
        totals.cpu_budget_exceeded.into(),
    );
    obj.insert(
        "wall_stall_timeout".into(),
        totals.wall_stall_timeout.into(),
    );
    obj.insert("missing_assertions".into(), missing_assertions.into());
    obj.insert("callsite_expansion".into(), callsite_expansion.into());
    obj.insert(
        "assertion_multiset_cid".into(),
        assertion_multiset_cid.into(),
    );
    let reason_obj: serde_json::Map<String, serde_json::Value> = reasons
        .iter()
        .map(|(k, v)| (k.clone(), serde_json::Value::from(*v)))
        .collect();
    obj.insert("reasons".into(), serde_json::Value::Object(reason_obj));
    let sample_obj: serde_json::Map<String, serde_json::Value> = reason_samples
        .iter()
        .map(|(k, v)| {
            (
                k.clone(),
                serde_json::Value::Array(
                    v.iter()
                        .map(|s| serde_json::Value::from(s.clone()))
                        .collect(),
                ),
            )
        })
        .collect();
    obj.insert(
        "reason_samples".into(),
        serde_json::Value::Object(sample_obj),
    );
    obj.insert(
        "all_reasons".into(),
        serde_json::Value::Array(
            all_reasons
                .iter()
                .map(|s| serde_json::Value::from(s.clone()))
                .collect(),
        ),
    );
    let file_arr: Vec<serde_json::Value> = rows
        .iter()
        .map(|(rel, asserts, discharged, refused, unacc, ok)| {
            let mut m = serde_json::Map::new();
            m.insert("file".into(), rel.clone().into());
            m.insert("asserts".into(), (*asserts).into());
            m.insert("discharged".into(), (*discharged).into());
            m.insert("refused".into(), (*refused).into());
            m.insert("missing_assertions".into(), (*unacc).max(0).into());
            m.insert("callsite_expansion".into(), (-*unacc).max(0).into());
            m.insert("parse_ok".into(), (*ok).into());
            serde_json::Value::Object(m)
        })
        .collect();
    obj.insert("per_file".into(), serde_json::Value::Array(file_arr));
    serde_json::Value::Object(obj)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn standalone_sweep_forces_proc_macro2_fallback() {
        configure_proc_macro2_for_standalone_binary();

        let _ = proc_macro2::Span::call_site();
        let _: proc_macro2::TokenStream = "assert!(true)".parse().unwrap();
    }

    fn fixture() -> (
        Totals,
        BTreeMap<String, usize>,
        BTreeMap<String, Vec<String>>,
        Vec<String>,
        Vec<(String, usize, usize, usize, i64, bool)>,
    ) {
        let totals = Totals {
            files: 2,
            parse_ok: 2,
            parse_fail: 0,
            assert_macros: 5,
            test_fns_seen: 3,
            test_fns_lifted: 3,
            discharged: 3,
            refused: 1,
            unclassified: 1,
            inactive: 0,
            panicked_files: 0,
            cpu_budget_exceeded: 0,
            wall_stall_timeout: 0,
        };
        let reasons = BTreeMap::from([("closure argument".to_string(), 2usize)]);
        let samples = BTreeMap::from([(
            "closure argument".to_string(),
            vec!["a.rs: closure argument `|x| x`".to_string()],
        )]);
        let all = vec!["closure argument `|x| x`".to_string(); 2];
        let rows = vec![
            ("a.rs".to_string(), 3, 2, 1, 0i64, true),
            ("b.rs".to_string(), 2, 1, 1, 0i64, true),
        ];
        (totals, reasons, samples, all, rows)
    }

    #[test]
    fn ledger_json_is_deterministic_and_carries_the_residual_fields() {
        let (totals, reasons, samples, all, rows) = fixture();
        let v1 = build_ledger_json("corpus", &totals, &reasons, &samples, &all, &rows, "x");
        let v2 = build_ledger_json("corpus", &totals, &reasons, &samples, &all, &rows, "x");
        assert_eq!(v1, v2);
        // exactly the fields `sugar diff --ledger-*` reads for the residual axis.
        for field in [
            "assert_macros",
            "discharged",
            "refused",
            "missing_assertions",
            "callsite_expansion",
        ] {
            assert!(v1.get(field).and_then(|n| n.as_i64()).is_some(), "{field}");
        }
        assert!(v1.get("unaccounted").is_none());
    }

    #[test]
    fn ledger_json_splits_missing_from_callsite_expansion() {
        let (mut totals, reasons, samples, all, _) = fixture();
        totals.assert_macros = 3;
        totals.discharged = 4;
        totals.refused = 1;
        totals.unclassified = 0;
        totals.inactive = 0;
        let rows = vec![
            ("missing.rs".to_string(), 3, 1, 1, 1i64, true),
            ("inlined.rs".to_string(), 0, 3, 0, -3i64, true),
        ];
        let v = build_ledger_json("corpus", &totals, &reasons, &samples, &all, &rows, "x");
        assert_eq!(
            v.get("missing_assertions").and_then(|n| n.as_i64()),
            Some(1)
        );
        assert_eq!(
            v.get("callsite_expansion").and_then(|n| n.as_i64()),
            Some(3)
        );
        assert!(v.get("unaccounted").is_none());
    }

    // THE TOOTH on the timeout classification. The SPINNING branch is exercised by
    // the real corpus (`num/int_sqrt.rs` reports `cpu 20s of 20s wall`); the STARVED
    // branch is the one that only fires on a loaded box, which is exactly the
    // condition you cannot summon on demand -- so it gets tested here rather than
    // shipped on the strength of the branch next to it having worked once.
    #[test]
    fn timeout_verdict_separates_a_hang_from_a_starved_run() {
        // Burning a full core for the whole bound: the file is the problem.
        assert!(classify_timeout(Some(300.0), 300.0).starts_with("SPINNING"));
        // Half a core sustained is still real work -- the threshold is inclusive.
        assert!(classify_timeout(Some(150.0), 300.0).starts_with("SPINNING"));
        // Barely scheduled: the bound describes the BOX, and the row must say so
        // rather than let contention be published as a hang.
        let starved = classify_timeout(Some(12.0), 300.0);
        assert!(starved.starts_with("STARVED"), "{starved}");
        assert!(starved.contains("not attributable to this file"), "{starved}");
        // No evidence is its own answer, never a silent "spinning".
        assert_eq!(classify_timeout(None, 300.0), "cpu time unavailable");
        // A zero/negative wall cannot classify and must not divide.
        assert_eq!(classify_timeout(Some(1.0), 0.0), "cpu time unavailable");
    }

    // THE TOOTH on the bucket choice. The PR this landed in rests on "unclassified,
    // not refused", and until this existed nothing enforced it: mutating the bin to
    // `totals.refused += census_total` left every other test green. Drives a panicking
    // file through the real binning and asserts the whole counter set, so a silent
    // re-bin to `refused` -- or a dropped `panicked_files` increment, or a lost
    // assertion -- goes red here.
    #[test]
    fn panic_bins_unclassified_not_refused() {
        let mut totals = Totals::default();
        let mut reasons = BTreeMap::new();
        let mut samples = BTreeMap::new();
        let mut all = Vec::new();
        let mut rows = Vec::new();

        bin_panicked_file(
            "num/ops.rs",
            "enumerate did not reach a lawful floor: inner reduced to non-sequence",
            74,
            &mut totals,
            &mut reasons,
            &mut samples,
            &mut all,
            &mut rows,
        );

        // The bucket choice itself.
        assert_eq!(totals.unclassified, 74, "panic must bin UNCLASSIFIED");
        assert_eq!(totals.refused, 0, "a panic is NOT an earned refusal");
        assert_eq!(totals.discharged, 0);
        assert_eq!(totals.inactive, 0);
        // The floor marker, and the surface conservation that keeps `silent` at 0.
        assert_eq!(totals.panicked_files, 1);
        assert_eq!(totals.assert_macros, 74, "the file's surface stays counted");
        assert_eq!(all.len(), 74, "one named reason per assertion");
        assert!(all[0].starts_with("lifter panic: "));
        // Every reason row is tagged unclassified, never refused.
        assert!(
            reasons.keys().all(|k| k.starts_with("[unclassified] ")),
            "{reasons:?}"
        );
        assert_eq!(reasons.values().sum::<usize>(), 74);
        // The row: parsed fine, panicked in the lift, nothing silently dropped.
        let (rel, asserts, discharged, refused, raw_delta, parse_ok) = &rows[0];
        assert_eq!(rel, "num/ops.rs");
        assert_eq!((*asserts, *discharged, *refused), (74, 0, 74));
        assert_eq!(*raw_delta, 0, "raw_delta 0 keeps missing_assertions unmoved");
        assert!(*parse_ok, "the file PARSED; it panicked during the lift");
    }

    // A ledger that floored some files must SAY so on its face. Without this
    // field a reader cannot tell "every lift ran" from "seven lifts panicked
    // and their whole surface was binned", and the two ledgers otherwise look
    // alike -- the counts just sit lower.
    #[test]
    fn ledger_json_always_carries_panicked_files() {
        let (mut totals, reasons, samples, all, rows) = fixture();
        let v = build_ledger_json("corpus", &totals, &reasons, &samples, &all, &rows, "x");
        assert_eq!(v.get("panicked_files").and_then(|n| n.as_u64()), Some(0));
        totals.panicked_files = 7;
        let v = build_ledger_json("corpus", &totals, &reasons, &samples, &all, &rows, "x");
        assert_eq!(v.get("panicked_files").and_then(|n| n.as_u64()), Some(7));
    }

    #[test]
    fn ledger_cid_is_blake3_512_tagged_and_stable() {
        let (totals, reasons, samples, all, rows) = fixture();
        let v = build_ledger_json("corpus", &totals, &reasons, &samples, &all, &rows, "");
        let cid = sugar_canonicalizer::jcs_cid_of_json(&v);
        assert!(cid.starts_with("blake3-512:"), "{cid}");
        assert_eq!(cid, sugar_canonicalizer::jcs_cid_of_json(&v));
    }

    // --- per-silence identity: the unproven set must be diffable by member,
    // not just by cardinality. Each assertion site gets a content CID so a
    // count-preserving swap (one assertion out, a decoy in) is visible. ---

    fn mac(src: &str) -> syn::Macro {
        match syn::parse_str::<syn::Expr>(src).expect("parse expr") {
            syn::Expr::Macro(m) => m.mac,
            _ => panic!("not a macro invocation"),
        }
    }

    #[test]
    fn site_cid_is_whitespace_insensitive_but_value_sensitive() {
        let base = sugar_lift_rust_tests::assertion_surface_site_cid(&mac("assert_eq!(a, 2)"));
        let spaced = sugar_lift_rust_tests::assertion_surface_site_cid(&mac("assert_eq!(a ,   2)"));
        let revalued = sugar_lift_rust_tests::assertion_surface_site_cid(&mac("assert_eq!(a, 3)"));
        assert!(base.starts_with("blake3-512:"), "{base}");
        assert_eq!(base, spaced, "whitespace must not move the site cid");
        assert_ne!(base, revalued, "a changed asserted value must move it");
    }

    #[test]
    fn site_cid_distinguishes_macro_path() {
        assert_ne!(
            sugar_lift_rust_tests::assertion_surface_site_cid(&mac("assert!(a)")),
            sugar_lift_rust_tests::assertion_surface_site_cid(&mac("debug_assert!(a)")),
            "assert! and debug_assert! are different obligations"
        );
    }

    #[test]
    fn assertion_surface_census_collects_one_site_cid_per_assertion() {
        let file: syn::File =
            syn::parse_str("fn t() { assert!(a); assert_eq!(b, 1); }").expect("parse file");
        let census = sugar_lift_rust_tests::assertion_surface_census(
            &file,
            &sugar_lift_rust_tests::MacroRegistry::new(),
        );
        assert_eq!(census.total, 2);
        assert_eq!(
            census.site_cids.len(),
            2,
            "one site cid per assertion surface"
        );
    }

    #[test]
    fn assertion_surface_census_learns_source_macro_shape_without_prefix() {
        let file: syn::File = syn::parse_str(
            r#"
macro_rules! check {
    ($value:expr) => { assert_eq!($value, 1); };
}
fn t() { check!(x); }
"#,
        )
        .expect("parse file");
        let census = sugar_lift_rust_tests::assertion_surface_census(
            &file,
            &sugar_lift_rust_tests::MacroRegistry::new(),
        );
        assert_eq!(census.total, 1);
        assert_eq!(census.site_cids.len(), 1);
    }

    #[test]
    fn assertion_surface_census_learns_pub_macro_shape_without_prefix() {
        let file: syn::File = syn::parse_str(
            r#"
pub macro check($value:expr) {
    assert_eq!($value, 1);
}
fn t() { check!(x); }
"#,
        )
        .expect("parse file");
        let census = sugar_lift_rust_tests::assertion_surface_census(
            &file,
            &sugar_lift_rust_tests::MacroRegistry::new(),
        );
        assert_eq!(census.total, 1);
        assert_eq!(census.site_cids.len(), 1);
    }

    #[test]
    fn assertion_surface_census_learns_panic_locus_macro_shape_without_prefix() {
        let file: syn::File = syn::parse_str(
            r#"
macro_rules! check_zero {
    ($value:expr) => {{
        match $value {
            0 => {}
            _ => { panic!(); }
        }
    }};
}
fn t() { check_zero!(x); }
"#,
        )
        .expect("parse file");
        let census = sugar_lift_rust_tests::assertion_surface_census(
            &file,
            &sugar_lift_rust_tests::MacroRegistry::new(),
        );
        assert_eq!(census.total, 1);
        assert_eq!(census.site_cids.len(), 1);
    }

    #[test]
    fn ledger_carries_assertion_multiset_cid() {
        let (totals, reasons, samples, all, rows) = fixture();
        let set_cid = "blake3-512:abc";
        let v = build_ledger_json("corpus", &totals, &reasons, &samples, &all, &rows, set_cid);
        assert_eq!(
            v.get("assertion_multiset_cid").and_then(|s| s.as_str()),
            Some(set_cid)
        );
    }
}
