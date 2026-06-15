// coretests_sweep: measure the delta to stdlib-0.
//
// Walks a corpus of Rust test files (coretests/tests/**), runs the assertion
// lifter over each, and produces a ledger that classifies EVERY assertion
// macro invocation into exactly one of three bins:
//
//   discharged  -- lifted to a FOL atom (one invariant operand per assertion)
//   refused     -- the lifter emitted a named warning (loudly-bounded-lossy)
//   unaccounted -- seen in source but neither lifted nor warned (a SILENT DROP)
//
// 100% on stdlib == unaccounted == 0, with every refusal carrying an honest
// reason. This binary computes that number and the reason histogram (the
// remaining roadmap). It does NOT decide whether a refusal is honest vs a
// missing reduction -- that is an architect judgement made from the histogram.
//
// Usage: coretests_sweep <corpus-dir> [--json <out.json>]

use std::collections::BTreeMap;

use sugar_lift_rust_tests::closed_eval::{self, HarnessResult};
use sugar_lift_rust_tests::{
    lift_file_with_macro_imports, refusal_disposition, Disposition, LiftOptions, MacroRegistry,
    TargetCfg,
};
use syn::visit::{self, Visit};

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

/// The lifter's assertion universe: any macro whose name starts with assert or
/// debug_assert. This covers the standard six plus stdlib custom macros
/// (assert_all!, assert_none!, assert_eq_const_safe!, ...) that the lifter
/// lifts or refuses. The independent denominator must match this universe or
/// discharged would exceed it and unaccounted would go negative.
fn is_assert_macro_name(name: &str) -> bool {
    name.starts_with("assert") || name.starts_with("debug_assert")
}

/// A content CID for one assertion invocation: the macro path plus its
/// token stream, normalized. proc_macro2's Display collapses original
/// whitespace to single spaces, so two byte-different-but-token-identical
/// assertions share a CID (formatting is sugar) while a changed asserted
/// value moves it (the obligation actually changed). This is the per-member
/// identity that lets the residual diff a MULTISET (membership + multiplicity), not just a cardinality.
fn assertion_site_cid(m: &syn::Macro) -> String {
    let path = m
        .path
        .segments
        .iter()
        .map(|s| s.ident.to_string())
        .collect::<Vec<_>>()
        .join("::");
    let body = m.tokens.to_string();
    sugar_canonicalizer::blake3_512_of(format!("{path}!({body})").as_bytes())
}

/// Counts assertion-macro invocations independently of the lifter, so we can
/// reconcile against the lifter's own accounting and surface silent drops.
/// Also collects a content CID per site so the unproven set is identifiable
/// by member, not only by count.
#[derive(Default)]
struct AssertCounter {
    total: usize,
    site_cids: Vec<String>,
}

impl<'ast> Visit<'ast> for AssertCounter {
    fn visit_macro(&mut self, m: &'ast syn::Macro) {
        if let Some(seg) = m.path.segments.last() {
            if is_assert_macro_name(&seg.ident.to_string()) {
                self.total += 1;
                self.site_cids.push(assertion_site_cid(m));
            }
        }
        visit::visit_macro(self, m);
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
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: coretests_sweep <corpus-dir> [--json <out.json>]");
        std::process::exit(2);
    }
    let corpus = &args[1];
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
    let mut scan_dirs: Vec<&str> = vec![corpus.as_str()];
    scan_dirs.extend(dep_dirs.iter().map(|s| s.as_str()));
    for dir in &scan_dirs {
        for entry in walkdir::WalkDir::new(dir)
            .into_iter()
            .filter_map(|e| e.ok())
        {
            let p = entry.path();
            if p.extension().and_then(|e| e.to_str()) == Some("rs") {
                if let Ok(src) = std::fs::read_to_string(p) {
                    registry.scan_source(&src);
                }
            }
        }
    }
    eprintln!(
        "macro registry: {} definitions from source ({} trees)",
        registry.len(),
        scan_dirs.len()
    );

    // `--rustc-cfg`: resolve target cfgs (target_has_atomic, target_family,
    // absence of loom/fuzzing, ...) from real `rustc --print cfg` facts -- a
    // declared build configuration, from the compiler, not a guess.
    // `--feature NAME` (repeatable): declare an enabled crate feature.
    let use_rustc_cfg = args.iter().any(|a| a == "--rustc-cfg");
    let features: Vec<String> = args
        .iter()
        .enumerate()
        .filter(|(_, a)| a.as_str() == "--feature")
        .filter_map(|(i, _)| args.get(i + 1).cloned())
        .collect();
    let options = if use_rustc_cfg || !features.is_empty() {
        let mut cfg_text = String::new();
        if use_rustc_cfg {
            match std::process::Command::new("rustc")
                .args(["--print", "cfg"])
                .output()
            {
                Ok(o) if o.status.success() => {
                    cfg_text.push_str(&String::from_utf8_lossy(&o.stdout));
                }
                _ => eprintln!("warning: `rustc --print cfg` failed; target cfgs stay ambiguous"),
            }
        }
        for f in &features {
            cfg_text.push_str(&format!("\nfeature=\"{f}\"\n"));
        }
        match TargetCfg::from_rustc_cfg_text(&cfg_text) {
            Ok(cfg) => {
                eprintln!(
                    "build config: rustc facts + {} declared feature(s)",
                    features.len()
                );
                LiftOptions::for_target_cfg(cfg)
            }
            Err(e) => {
                eprintln!("warning: cfg parse failed ({e}); using default");
                LiftOptions::default()
            }
        }
    } else {
        LiftOptions::default()
    };
    let mut totals = Totals::default();
    let mut reasons: BTreeMap<String, usize> = BTreeMap::new();
    let mut reason_samples: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut all_reasons: Vec<String> = Vec::new();
    // Per-file rows: (path, asserts, atoms, warnings, unaccounted, parse_ok)
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

        let src = match std::fs::read_to_string(path) {
            Ok(s) => s,
            Err(_) => {
                totals.parse_fail += 1;
                rows.push((rel, 0, 0, 0, 0, false));
                continue;
            }
        };
        let file = match syn::parse_file(&src) {
            Ok(f) => f,
            Err(_) => {
                totals.parse_fail += 1;
                rows.push((rel, 0, 0, 0, 0, false));
                continue;
            }
        };
        totals.parse_ok += 1;

        let mut counter = AssertCounter::default();
        counter.visit_file(&file);
        all_site_cids.extend(counter.site_cids.iter().cloned());

        if callsite_census {
            for row in sugar_lift_rust_tests::callsite_census(&file, &options, &registry) {
                census_rows.push((rel.clone(), row));
            }
        }
        let out = lift_file_with_macro_imports(&file, &rel, &options, &registry);
        let discharged = out.assertions_lifted;
        let refused_total = out.assertions_refused;

        totals.assert_macros += counter.total;
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
                Disposition::Refused => {
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
        // => SILENT and net unaccounted invariant. Hermetic (no --dissolve): greens=0 =>
        // every bucket unchanged.
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

        // Silent drop: a real assert macro the collector never reached (nested
        // in control flow) -- neither lifted nor refused with a reason.
        let unaccounted = counter.total as i64 - discharged as i64 - refused as i64;
        rows.push((rel, counter.total, discharged, refused, unaccounted, true));
    }

    // Headline reconciliation at macro granularity. `refused + unclassified` is the
    // full named non-discharged set; only their sum reconciles against the textual
    // macro count.
    let named_non_discharged = totals.refused + totals.unclassified + totals.inactive;
    let unaccounted = totals.assert_macros as i64
        - totals.discharged as i64
        - named_non_discharged as i64;
    // Per-file split. A positive per-file residual is a genuinely unreached
    // assertion (the true silent drop). A negative per-file residual is
    // inlining inflation: the reducer inlined a helper called from several
    // sites, lifting one textual assert as several point-wise instances, so
    // discharged exceeds the textual count. The net headline mixes the two, so
    // we report the genuinely-unreached sum separately as the real delta.
    let genuinely_unreached: i64 = rows.iter().map(|r| r.4.max(0)).sum();
    let inlining_inflation: i64 = rows.iter().map(|r| (-r.4).max(0)).sum();
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
    println!("assertion macros seen: {}", totals.assert_macros);
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
        "  unaccounted (net):           {:>6}  ({:.1}%)",
        unaccounted,
        pct(unaccounted.max(0) as usize)
    );
    println!(
        "  genuinely unreached (SILENT):{:>6}  ({:.1}%)   <-- delta target = 0",
        genuinely_unreached,
        pct(genuinely_unreached.max(0) as usize)
    );
    println!(
        "  inlining inflation:          {:>6}   (helper inlined at N call sites)",
        inlining_inflation
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
    println!("---- top files by unaccounted (silent drops) ----");
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
            unaccounted,
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
        }
    }
}

/// STEP-1 CENSUS REPORT (stderr). For every recognized call-site-inlining site,
/// report the category of its residue. A helper that COMMITS at any site is drained
/// (its asserts discharged); a helper that bails at every site is blocked, and the
/// category names the blocker shape (the roadmap rung). Per-helper rows let us map
/// the 112 "reachable only" asserts back to their cause.
fn report_callsite_census(rows: &[(String, sugar_lift_rust_tests::CallsiteCensusRow)]) {
    use sugar_lift_rust_tests::CallsiteCensusRow;
    use std::collections::BTreeMap;

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

/// The sweep ledger as a JSON value: the total accounting (every assertion
/// binned into discharged/refused/unaccounted), the reason histogram, and the
/// per-file rows. Pure so the shape -- and the CID over it -- is testable.
#[allow(clippy::too_many_arguments)]
fn build_ledger_json(
    corpus: &str,
    totals: &Totals,
    unaccounted: i64,
    reasons: &BTreeMap<String, usize>,
    reason_samples: &BTreeMap<String, Vec<String>>,
    all_reasons: &[String],
    rows: &[(String, usize, usize, usize, i64, bool)],
    assertion_multiset_cid: &str,
) -> serde_json::Value {
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
    obj.insert("unaccounted".into(), unaccounted.into());
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
            m.insert("unaccounted".into(), (*unacc).into());
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
        let v1 = build_ledger_json("corpus", &totals, 0, &reasons, &samples, &all, &rows, "x");
        let v2 = build_ledger_json("corpus", &totals, 0, &reasons, &samples, &all, &rows, "x");
        assert_eq!(v1, v2);
        // exactly the fields `sugar diff --ledger-*` reads for the residual axis.
        for field in ["assert_macros", "discharged", "refused", "unaccounted"] {
            assert!(v1.get(field).and_then(|n| n.as_i64()).is_some(), "{field}");
        }
    }

    #[test]
    fn ledger_cid_is_blake3_512_tagged_and_stable() {
        let (totals, reasons, samples, all, rows) = fixture();
        let v = build_ledger_json("corpus", &totals, 0, &reasons, &samples, &all, &rows, "");
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
        let base = assertion_site_cid(&mac("assert_eq!(a, 2)"));
        let spaced = assertion_site_cid(&mac("assert_eq!(a ,   2)"));
        let revalued = assertion_site_cid(&mac("assert_eq!(a, 3)"));
        assert!(base.starts_with("blake3-512:"), "{base}");
        assert_eq!(base, spaced, "whitespace must not move the site cid");
        assert_ne!(base, revalued, "a changed asserted value must move it");
    }

    #[test]
    fn site_cid_distinguishes_macro_path() {
        assert_ne!(
            assertion_site_cid(&mac("assert!(a)")),
            assertion_site_cid(&mac("debug_assert!(a)")),
            "assert! and debug_assert! are different obligations"
        );
    }

    #[test]
    fn assert_counter_collects_one_site_cid_per_assertion() {
        let file: syn::File =
            syn::parse_str("fn t() { assert!(a); assert_eq!(b, 1); }").expect("parse file");
        let mut c = AssertCounter::default();
        c.visit_file(&file);
        assert_eq!(c.total, 2);
        assert_eq!(c.site_cids.len(), 2, "one site cid per assertion macro");
    }

    #[test]
    fn ledger_carries_assertion_multiset_cid() {
        let (totals, reasons, samples, all, rows) = fixture();
        let set_cid = "blake3-512:abc";
        let v = build_ledger_json(
            "corpus", &totals, 0, &reasons, &samples, &all, &rows, set_cid,
        );
        assert_eq!(
            v.get("assertion_multiset_cid").and_then(|s| s.as_str()),
            Some(set_cid)
        );
    }
}
