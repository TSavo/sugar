// discharge_sweep: the TEETHED ledger over the corpus.
//
// `sugar lift --report` measures COVERAGE -- how many assertion loci the kit
// `warranted` = lifted to a checkable FOL fact. Coverage runs NO solver, so it
// cannot tell a teethed obligation (one a wrong value would refute) from a
// congruence-only / opaque one (SAT for any value -- no teeth). This binary
// closes that gap: it runs the verifier's DISCHARGE GATE (negation-UNSAT, the
// `sugar-verifier::body_discharge` semantics) over every warranted obligation
// and reports the real proof split:
//
//   DISCHARGED  -- z3 proves the NEGATION UNSAT (valid: teeth, proven true).
//                  Split into `substantive` vs `reflexive` (a discharge resting
//                  only on reflexive/congruence equality -- sound but shallow,
//                  says nothing about the term's behavior).
//   REFUTED     -- z3 proves the invariant itself UNSAT (proven false).
//   UNDECIDED   -- neither: lifted but congruence-only / no teeth. This is the
//                  bucket coverage HID inside `warranted`; it is a distinct
//                  target from `unresolved` (which is not-lifted-at-all).
//   UNCHECKABLE -- the obligation did not compile to well-sorted SMT, or z3 was
//                  unavailable. Reported explicitly (finite-or-refuse): never
//                  silently rolled into a teethed bucket.
//
// It re-lifts faithfully -- same `lift_file_with_all_source_imports` + the
// corpus `target_cfg` the RPC uses -- so its warranted denominator tracks the
// official ledger. (A second lift pass: additive measurement, release-only.)
//
// Usage: discharge_sweep <corpus-dir> [--json <out.json>] [--z3 <path>]
//        (reads <corpus-dir>/.sugar/config.toml for [rust-test-assertions.target_cfg])

use std::collections::BTreeMap;
use std::path::Path;

use serde_json::{json, Value};
use sugar_lift_rust_tests::{
    lift_file_with_all_source_imports, AssertionFactKind, ConstSourceRegistry,
    FunctionSourceRegistry, LiftOptions, MacroRegistry, TargetCfg,
};

/// One obligation's disposition under the discharge gate.
#[derive(Debug, Clone, PartialEq, Eq)]
enum Teeth {
    Discharged { reflexive: bool },
    Refuted,
    Undecided,
    Uncheckable(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum Z3 {
    Sat,
    Unsat,
    Absent,
    /// z3 returned `unknown` or hit its per-query time budget. Finite-or-refuse:
    /// a verdict we could not compute, never silently treated as proven.
    Timeout,
    Error(String),
}

/// Per-query z3 wall-clock budget (ms). One pathological obligation (e.g. a
/// bignum nonlinear formula) must never wedge the whole corpus sweep; it times
/// out to `unknown` and is bucketed UNCHECKABLE.
const Z3_TIMEOUT_MS: u32 = 5000;

/// Compile a formula to SMT-LIB and ask z3 for satisfiability, bounded by a
/// per-query timeout.
fn z3_run(formula: &Value, z3_path: &str, label: &str) -> Z3 {
    let parts = match sugar_ir_compiler_smt_lib::compile_asserted_to_parts(formula) {
        Ok(p) => p,
        Err(e) => return Z3::Error(format!("compile: {e}")),
    };
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
    if !Path::new(z3_path).exists() {
        return Z3::Absent;
    }
    let path = std::env::temp_dir().join(format!("discharge_sweep_{label}.smt2"));
    if std::fs::write(&path, &script).is_err() {
        return Z3::Error("write smt2".into());
    }
    // `-t:<ms>` bounds each (check-sat); `timeout` returns `unknown`.
    let out = match std::process::Command::new(z3_path)
        .arg(format!("-t:{Z3_TIMEOUT_MS}"))
        .arg(&path)
        .output()
    {
        Ok(o) => o,
        Err(e) => return Z3::Error(format!("spawn z3: {e}")),
    };
    let _ = std::fs::remove_file(&path);
    let stdout = String::from_utf8_lossy(&out.stdout);
    if stdout.contains("unknown constant") {
        return Z3::Error(format!("ill-sorted: {}", stdout.trim().replace('\n', " ")));
    }
    if stdout.contains("unsat") {
        Z3::Unsat
    } else if stdout.contains("sat") {
        Z3::Sat
    } else if stdout.contains("unknown") || stdout.contains("timeout") {
        Z3::Timeout
    } else if stdout.to_lowercase().contains("error") {
        Z3::Error(format!("z3: {}", stdout.trim().replace('\n', " ")))
    } else {
        Z3::Error(format!("no verdict: {}", stdout.trim()))
    }
}

/// The discharge gate: DISCHARGED iff the NEGATION is UNSAT (validity); REFUTED
/// iff the invariant itself is UNSAT; UNDECIDED iff both are SAT (no teeth).
fn discharge_inv(inv: &Value, z3_path: &str, label: &str) -> Teeth {
    let neg = json!({ "kind": "not", "operands": [inv.clone()] });
    match z3_run(&neg, z3_path, &format!("{label}_neg")) {
        Z3::Unsat => {
            let reflexive = sugar_verifier::body_discharge::classify_discharge_method(inv)
                == sugar_verifier::body_discharge::DischargeMethod::Reflexive;
            Teeth::Discharged { reflexive }
        }
        Z3::Sat => match z3_run(inv, z3_path, &format!("{label}_pos")) {
            Z3::Unsat => Teeth::Refuted,
            Z3::Sat => Teeth::Undecided,
            Z3::Timeout => Teeth::Uncheckable("z3-timeout".into()),
            Z3::Absent => Teeth::Uncheckable("z3 absent".into()),
            Z3::Error(e) => Teeth::Uncheckable(e),
        },
        // Could not prove the negation UNSAT within budget -> NOT discharged.
        Z3::Timeout => Teeth::Uncheckable("z3-timeout".into()),
        Z3::Absent => Teeth::Uncheckable("z3 absent".into()),
        Z3::Error(e) => Teeth::Uncheckable(e),
    }
}

#[derive(Default)]
struct Tally {
    warranted_obligations: usize,
    discharged_substantive: usize,
    discharged_reflexive: usize,
    refuted: usize,
    undecided: usize,
    uncheckable: usize,
    z3_absent: usize,
    uncheckable_reasons: BTreeMap<String, usize>,
}

impl Tally {
    fn record(&mut self, t: &Teeth) {
        self.warranted_obligations += 1;
        match t {
            Teeth::Discharged { reflexive: true } => self.discharged_reflexive += 1,
            Teeth::Discharged { reflexive: false } => self.discharged_substantive += 1,
            Teeth::Refuted => self.refuted += 1,
            Teeth::Undecided => self.undecided += 1,
            Teeth::Uncheckable(reason) => {
                self.uncheckable += 1;
                if reason.contains("z3 absent") {
                    self.z3_absent += 1;
                }
                // Bucket the reason by its leading token (compile/ill-sorted/...).
                let key = reason.split(':').next().unwrap_or("other").trim().to_string();
                *self.uncheckable_reasons.entry(key).or_default() += 1;
            }
        }
    }

    fn discharged(&self) -> usize {
        self.discharged_substantive + self.discharged_reflexive
    }

    fn merge(&mut self, other: Tally) {
        self.warranted_obligations += other.warranted_obligations;
        self.discharged_substantive += other.discharged_substantive;
        self.discharged_reflexive += other.discharged_reflexive;
        self.refuted += other.refuted;
        self.undecided += other.undecided;
        self.uncheckable += other.uncheckable;
        self.z3_absent += other.z3_absent;
        for (k, v) in other.uncheckable_reasons {
            *self.uncheckable_reasons.entry(k).or_default() += v;
        }
    }
}

/// Read the corpus `target_cfg` the RPC uses, so this re-lift matches the
/// official ledger's cfg-gating. Absent/unreadable -> default options.
fn lift_options_for_corpus(corpus: &Path) -> LiftOptions {
    let config_path = corpus.join(".sugar/config.toml");
    let Ok(text) = std::fs::read_to_string(&config_path) else {
        return LiftOptions::default();
    };
    let Ok(doc) = text.parse::<toml::Value>() else {
        return LiftOptions::default();
    };
    let facts = doc
        .get("rust-test-assertions")
        .and_then(|v| v.get("target_cfg"))
        .and_then(|v| v.get("facts"))
        .and_then(|v| v.as_array());
    let Some(facts) = facts else {
        return LiftOptions::default();
    };
    let facts: Vec<String> = facts
        .iter()
        .filter_map(|v| v.as_str().map(str::to_string))
        .collect();
    match TargetCfg::from_rustc_cfg_facts(facts) {
        Ok(cfg) => LiftOptions::for_target_cfg(cfg),
        Err(_) => LiftOptions::default(),
    }
}

/// (rel, src) for every parseable `.rs` under `root`. We keep the SOURCE (Sync)
/// rather than the parsed `syn::File` (which is not Sync) so the lift phase can
/// fan out across rayon threads, re-parsing per task.
fn collect_rs_files(root: &Path) -> Vec<(String, String)> {
    let mut out = Vec::new();
    for entry in walkdir::WalkDir::new(root)
        .into_iter()
        .filter_map(Result::ok)
    {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("rs") {
            continue;
        }
        let Ok(src) = std::fs::read_to_string(path) else {
            continue;
        };
        if syn::parse_file(&src).is_err() {
            continue;
        }
        let rel = path
            .strip_prefix(root)
            .unwrap_or(path)
            .to_string_lossy()
            .into_owned();
        out.push((rel, src));
    }
    out.sort_by(|a, b| a.0.cmp(&b.0));
    out
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: discharge_sweep <corpus-dir> [--json <out.json>] [--z3 <path>]");
        std::process::exit(2);
    }
    let corpus = Path::new(&args[1]);
    let json_out = arg_value(&args, "--json");
    let z3_path = arg_value(&args, "--z3")
        .or_else(|| std::env::var("Z3").ok())
        .unwrap_or_else(|| "/usr/local/bin/z3".to_string());

    // The RPC lifts files under <corpus>/tests; mirror that file set so the
    // warranted denominator tracks the official ledger.
    let tests_dir = corpus.join("tests");
    let scan_root = if tests_dir.is_dir() {
        tests_dir
    } else {
        corpus.to_path_buf()
    };
    let files = collect_rs_files(&scan_root);
    eprintln!(
        "discharge_sweep: {} source files under {}",
        files.len(),
        scan_root.display()
    );

    // Faithful lift: cross-file const/fn registries + corpus target_cfg. The
    // registries must see every file before any file is lifted (cross-file
    // consts), so this scan is sequential; re-parsing here is cheap.
    let mut const_registry = ConstSourceRegistry::new();
    let mut fn_registry = FunctionSourceRegistry::new();
    for (rel, src) in &files {
        if let Ok(file) = syn::parse_file(src) {
            const_registry.scan_file(rel, &file);
            fn_registry.scan_file(rel, &file);
        }
    }
    let macro_imports = MacroRegistry::new();
    let options = lift_options_for_corpus(corpus);

    let z3_available = Path::new(&z3_path).exists();
    use rayon::prelude::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    // PHASE 1 (sequential lift): the kit's lift registries hold non-Sync data
    // (Rc/proc_macro tokens), so lifting cannot cross threads. We lift each file
    // in turn and collect its warranted obligations as (label, inv) JSON pairs
    // (which ARE Sync), then fan the z3 work out below. Per-file progress goes
    // to stderr so a slow lift is visible, never a silent hang.
    let total_files = files.len();
    let mut obligations: Vec<(String, Value)> = Vec::new();
    let mut no_inv_total = 0usize;
    for (fi, (rel, src)) in files.iter().enumerate() {
        let Ok(file) = syn::parse_file(src) else {
            continue;
        };
        let out = lift_file_with_all_source_imports(
            &file,
            rel,
            &options,
            &macro_imports,
            &const_registry,
            &fn_registry,
        );
        // Warranted obligations = decls backing a warranted assertion fact with
        // >=1 scalar claim (mirrors the kit's own `warranted_decls`).
        let warranted_names: std::collections::HashSet<&str> = out
            .assertion_facts
            .iter()
            .filter(|f| f.kind == AssertionFactKind::Warranted && f.claim_count > 0)
            .map(|f| f.contract_name.as_str())
            .collect();
        let mut file_obs = 0usize;
        for (idx, decl) in out.decls.iter().enumerate() {
            if !warranted_names.contains(decl.name.as_str()) {
                continue;
            }
            let doc =
                sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(decl));
            let inv = match serde_json::from_str::<Value>(&doc) {
                Ok(parsed) => parsed.get(0).and_then(|d| d.get("inv")).cloned(),
                Err(_) => None,
            };
            match inv {
                Some(inv) if !inv.is_null() => {
                    let label = format!("{}_{idx}", rel.replace(['/', '.', '-'], "_"));
                    obligations.push((label, inv));
                    file_obs += 1;
                }
                _ => no_inv_total += 1,
            }
        }
        eprintln!("  lift {}/{total_files}: {rel} -> {file_obs} obligations", fi + 1);
    }
    eprintln!(
        "discharge_sweep: {} warranted obligations to check (+{} no-inv)",
        obligations.len(),
        no_inv_total
    );

    // PHASE 2 (parallel discharge): one z3 verdict per obligation, fanned out
    // across cores. The per-query timeout bounds any pathological obligation.
    let checked = AtomicUsize::new(0);
    let total_ob = obligations.len();
    let mut tally = obligations
        .par_iter()
        .map(|(label, inv)| {
            let t = discharge_inv(inv, &z3_path, label);
            let n = checked.fetch_add(1, Ordering::Relaxed) + 1;
            if n % 200 == 0 {
                eprintln!("  discharged {n}/{total_ob}");
            }
            t
        })
        .fold(Tally::default, |mut acc, t| {
            acc.record(&t);
            acc
        })
        .reduce(Tally::default, |mut a, b| {
            a.merge(b);
            a
        });
    for _ in 0..no_inv_total {
        tally.record(&Teeth::Uncheckable("no-inv".into()));
    }

    print_headline(&tally, z3_available, &z3_path);

    if let Some(path) = json_out {
        let obj = json!({
            "teethed_ledger": {
                "warranted_obligations": tally.warranted_obligations,
                "discharged": tally.discharged(),
                "discharged_substantive": tally.discharged_substantive,
                "discharged_reflexive": tally.discharged_reflexive,
                "refuted": tally.refuted,
                "undecided": tally.undecided,
                "uncheckable": tally.uncheckable,
                "z3_absent": tally.z3_absent,
                "uncheckable_reasons": tally.uncheckable_reasons,
            }
        });
        if let Err(e) = std::fs::write(&path, serde_json::to_string_pretty(&obj).unwrap()) {
            eprintln!("discharge_sweep: write --json {path}: {e}");
        }
    }
}

fn print_headline(t: &Tally, z3_seen: bool, z3_path: &str) {
    if !z3_seen {
        println!(
            "teethed ledger: z3 UNAVAILABLE at {z3_path} -- {} warranted obligations NOT checked \
             (set Z3=<path> or --z3 <path>)",
            t.warranted_obligations
        );
        return;
    }
    let denom = t.warranted_obligations.max(1) as f64;
    let pct = |n: usize| (n as f64) * 100.0 / denom;
    println!(
        "teethed ledger: warranted_obligations={} discharged={} ({:.1}%) [substantive={} reflexive={}] \
         refuted={} undecided={} ({:.1}%) uncheckable={}",
        t.warranted_obligations,
        t.discharged(),
        pct(t.discharged()),
        t.discharged_substantive,
        t.discharged_reflexive,
        t.refuted,
        t.undecided,
        pct(t.undecided),
        t.uncheckable,
    );
    println!(
        "  DISCHARGED = z3 proves negation UNSAT (teeth, proven). UNDECIDED = lifted but \
         congruence-only / no teeth (the bucket coverage hid). REFUTED = invariant UNSAT (proven false)."
    );
    if !t.uncheckable_reasons.is_empty() {
        let mut reasons: Vec<_> = t.uncheckable_reasons.iter().collect();
        reasons.sort_by(|a, b| b.1.cmp(a.1));
        let shown: Vec<String> = reasons
            .iter()
            .take(6)
            .map(|(k, v)| format!("{k}={v}"))
            .collect();
        println!("  uncheckable by reason: {}", shown.join(" "));
    }
}

fn arg_value(args: &[String], flag: &str) -> Option<String> {
    args.iter()
        .position(|a| a == flag)
        .and_then(|i| args.get(i + 1))
        .cloned()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn inv_of(src: &str) -> Value {
        let file = syn::parse_file(src).expect("parses");
        let out = sugar_lift_rust_tests::lift_file(&file, "audit/probe.rs");
        assert_eq!(out.decls.len(), 1, "expected one decl for {src}");
        let doc =
            sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&out.decls[0]));
        let parsed: Value = serde_json::from_str(&doc).unwrap();
        parsed[0]["inv"].clone()
    }

    fn z3() -> Option<String> {
        let p = std::env::var("Z3").unwrap_or_else(|_| "/usr/local/bin/z3".to_string());
        Path::new(&p).exists().then_some(p)
    }

    // The discharge gate must give teeth the right verdicts and never DISCHARGE
    // a false claim. Skips when z3 is unavailable.
    #[test]
    fn discharge_gate_teeth_asymmetry() {
        let Some(z3) = z3() else { return };
        // Teethed: literal index. True -> discharged; false -> refuted.
        assert!(matches!(
            discharge_inv(&inv_of("#[test] fn t() { assert_eq!([7,7,7][1], 7); }"), &z3, "t1"),
            Teeth::Discharged { .. }
        ));
        assert_eq!(
            discharge_inv(&inv_of("#[test] fn t() { assert_eq!([7,7,7][1], 99); }"), &z3, "t2"),
            Teeth::Refuted
        );
        // Congruence-only / opaque shape. The CARDINAL-SIN invariant: a FALSE
        // claim must NEVER be DISCHARGED. Whether it lands UNDECIDED (no teeth
        // yet) or REFUTED (a recognizer ground it -- e.g. #2326 MaybeUninit) is
        // a coverage detail; both satisfy the guard. (Uses differing literal
        // arrays, which stay opaque congruence vars across recognizer work.)
        let false_claim = discharge_inv(
            &inv_of("#[test] fn t() { assert_eq!([7, 7, 99], [7, 7, 7]); }"),
            &z3,
            "t3",
        );
        assert!(
            !matches!(false_claim, Teeth::Discharged { .. }),
            "CARDINAL SIN: a false claim was DISCHARGED: {false_claim:?}"
        );
        assert!(
            matches!(false_claim, Teeth::Undecided | Teeth::Refuted),
            "false claim must be Undecided (no teeth) or Refuted, got {false_claim:?}"
        );
    }
}
