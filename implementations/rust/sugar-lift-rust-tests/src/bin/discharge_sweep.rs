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
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;

use serde_json::{json, Value};
use sugar_canonicalizer::{blake3_512_of, jcs_cid_of_json};
use sugar_lift_rust_tests::{
    lift_file_with_all_source_imports, AssertionFactKind, ConstSourceRegistry,
    FunctionSourceRegistry, LiftOptions, MacroRegistry, TargetCfg,
};

/// One obligation's disposition under the discharge gate.
#[derive(Debug, Clone, PartialEq, Eq)]
enum Teeth {
    Discharged {
        reflexive: bool,
    },
    Refuted,
    Undecided,
    /// The obligation compiled and entered z3, but the solver exhausted the
    /// bounded per-query budget. Counted as an undecided solver verdict, not as
    /// a silent/uncheckable drop.
    SolverTimeout,
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

fn compile_asserted_json_to_parts(
    formula: &Value,
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

/// Compile a formula to SMT-LIB and ask z3 for satisfiability, bounded by a
/// per-query timeout.
fn z3_run(formula: &Value, z3_path: &str, label: &str) -> Z3 {
    let parts = match compile_asserted_json_to_parts(formula) {
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
            Z3::Timeout => Teeth::SolverTimeout,
            Z3::Absent => Teeth::Uncheckable("z3 absent".into()),
            Z3::Error(e) => Teeth::Uncheckable(e),
        },
        // Could not prove the negation UNSAT within budget -> NOT discharged.
        Z3::Timeout => Teeth::SolverTimeout,
        Z3::Absent => Teeth::Uncheckable("z3 absent".into()),
        Z3::Error(e) => Teeth::Uncheckable(e),
    }
}

/// True iff the formula subtree mentions a panic-path atom (`name == "panic"`).
/// Mirrors the kit's `formula_mentions_panic_path` (assertion_lift.rs).
fn mentions_panic(v: &Value) -> bool {
    match v {
        Value::Object(map) => {
            if map.get("kind").and_then(Value::as_str) == Some("atomic")
                && map.get("name").and_then(Value::as_str) == Some("panic")
            {
                return true;
            }
            map.values().any(mentions_panic)
        }
        Value::Array(a) => a.iter().any(mentions_panic),
        _ => false,
    }
}

/// The VALUE-claim invariant: drop the panic-freedom conjuncts so the discharge
/// gate measures whether the asserted VALUE is proven, not whether panic-freedom
/// is. An opaque panic conjunct otherwise drags a value-teethed claim into
/// UNDECIDED -- the reason the full-inv DISCHARGED count is a lower bound on
/// value-teethedness. Returns None when nothing but panic remains.
fn value_only_inv(inv: &Value) -> Option<Value> {
    if inv.get("kind").and_then(Value::as_str) == Some("and") {
        if let Some(ops) = inv.get("operands").and_then(Value::as_array) {
            let kept: Vec<Value> = ops.iter().filter(|o| !mentions_panic(o)).cloned().collect();
            if kept.is_empty() {
                return None;
            }
            return Some(json!({ "kind": "and", "operands": kept }));
        }
    }
    if mentions_panic(inv) {
        None
    } else {
        Some(inv.clone())
    }
}

/// The sweep checks the complete formula surface owned by the declaration. Some
/// source assertion contracts are emitted as `pre` rather than `inv`; treating
/// those as no-inv is a measurement drop, not an honest solver verdict.
fn declaration_formula(decl: &Value) -> Option<Value> {
    let mut formulas = Vec::new();
    for slot in ["pre", "post", "inv"] {
        if let Some(formula) = decl.get(slot).filter(|value| !value.is_null()) {
            formulas.push(formula.clone());
        }
    }
    match formulas.len() {
        0 => None,
        1 => formulas.into_iter().next(),
        _ => Some(json!({ "kind": "and", "operands": formulas })),
    }
}

/// A coarse shape signature for a REFUTED inv, for classifying false refutations.
/// e.g. `const==const` (a stale local mis-grounded to a literal), `ctor==const`, ...
fn refuted_signature(inv: &Value) -> String {
    // The first non-panic equality atom's argument kinds.
    fn atoms(v: &Value, out: &mut Vec<Value>) {
        if v.get("kind").and_then(Value::as_str) == Some("atomic") {
            out.push(v.clone());
        } else if let Some(ops) = v.get("operands").and_then(Value::as_array) {
            for o in ops {
                atoms(o, out);
            }
        }
    }
    let mut a = Vec::new();
    atoms(inv, &mut a);
    let kind_of = |v: &Value| {
        v.get("kind")
            .and_then(Value::as_str)
            .unwrap_or("?")
            .to_string()
    };
    for atom in &a {
        if mentions_panic(atom) {
            continue;
        }
        let name = atom.get("name").and_then(Value::as_str).unwrap_or("?");
        if let Some(args) = atom.get("args").and_then(Value::as_array) {
            if args.len() == 2 {
                return format!("{name}({},{})", kind_of(&args[0]), kind_of(&args[1]));
            }
        }
        return name.to_string();
    }
    "?".to_string()
}

/// One refuted obligation, for the false-refutation breakdown. The corpus is all
/// TRUE assertions, so every REFUTED here is a false refutation (a stale/wrong lift).
#[derive(Clone)]
struct RefutedRecord {
    file: String,
    signature: String,
    /// The file carries a refused `&mut`/deref-mutation skip -- the borrow4 / T3
    /// stale-deref class (deferred). False if no such skip -> a DIFFERENT class,
    /// likely fixable now.
    mut_skip_class: bool,
}

/// One UNDECIDED obligation: lifted but congruence-only / no teeth.
/// Captures the coarse shape signature (same as refuted) and the dominant
/// blocking operation (the head symbol of the lifted term that z3 can't ground).
#[derive(Clone)]
struct UndecidedRecord {
    file: String,
    /// Same shape as `refuted_signature`: first non-panic atom arg kinds, e.g.
    /// `=(ctor,const)`, `=(var,const)`, `=(ctor,ctor)`.
    signature: String,
    /// The "head symbol" of the lifted term blocking discharge, e.g.
    /// `ctor:to_string`, `ctor:flat_map`, `ctor:collect`, `var:<name>`.
    dom_op: String,
}

/// One UNCHECKABLE obligation: lifted far enough to enter the teeth lane, but
/// the solver boundary could not produce a verdict. This is diagnostic output
/// only; the tally remains the source of truth for the silent floor.
#[derive(Clone)]
struct UncheckableRecord {
    label: String,
    contract: String,
    file: String,
    signature: String,
    dom_op: String,
    reason: String,
    offending_smt_term: String,
}

#[derive(Clone)]
struct Obligation {
    label: String,
    rel: String,
    contract: String,
    contract_doc: Value,
    inv: Value,
    source: Arc<str>,
    source_cid: String,
    file_has_mut_skip: bool,
}

impl Obligation {
    fn replay_record(
        &self,
        shadow_full: Teeth,
        shadow_value: Option<Teeth>,
    ) -> ReplayableObligationRecord {
        let record = ReplayableObligationRecord::new(
            &self.label,
            &self.rel,
            &self.contract,
            self.source.as_ref(),
            &self.contract_doc,
            &self.inv,
            shadow_full,
            shadow_value,
        );
        debug_assert_eq!(record.source_cid, self.source_cid);
        record
    }
}

/// One source-preserving obligation record for re-adjudicating the shadow
/// ledger through production CLI. The source bytes are carried with their CID:
/// replay is possible, and identity drift is visible.
#[derive(Clone)]
struct ReplayableObligationRecord {
    label: String,
    rel: String,
    contract: String,
    source: String,
    source_cid: String,
    contract_cid: String,
    formula_cid: String,
    contract_ir: Value,
    formula_ir: Value,
    shadow_full: String,
    shadow_value: Option<String>,
}

impl ReplayableObligationRecord {
    fn new(
        label: &str,
        rel: &str,
        contract: &str,
        source: &str,
        contract_ir: &Value,
        formula_ir: &Value,
        shadow_full: Teeth,
        shadow_value: Option<Teeth>,
    ) -> Self {
        Self {
            label: label.to_string(),
            rel: rel.to_string(),
            contract: contract.to_string(),
            source: source.to_string(),
            source_cid: blake3_512_of(source.as_bytes()),
            contract_cid: jcs_cid_of_json(contract_ir),
            formula_cid: jcs_cid_of_json(formula_ir),
            contract_ir: contract_ir.clone(),
            formula_ir: formula_ir.clone(),
            shadow_full: teeth_summary(&shadow_full),
            shadow_value: shadow_value.map(|teeth| teeth_summary(&teeth)),
        }
    }

    fn to_json(&self) -> Value {
        json!({
            "label": self.label,
            "rel": self.rel,
            "contract": self.contract,
            "source": self.source,
            "source_cid": self.source_cid,
            "contract_cid": self.contract_cid,
            "formula_cid": self.formula_cid,
            "contract_ir": self.contract_ir,
            "formula_ir": self.formula_ir,
            "shadow_full": self.shadow_full,
            "shadow_value": self.shadow_value,
        })
    }
}

fn teeth_summary(teeth: &Teeth) -> String {
    match teeth {
        Teeth::Discharged { reflexive: true } => "discharged:reflexive".to_string(),
        Teeth::Discharged { reflexive: false } => "discharged:substantive".to_string(),
        Teeth::Refuted => "refuted".to_string(),
        Teeth::Undecided => "undecided".to_string(),
        Teeth::SolverTimeout => "solver-timeout".to_string(),
        Teeth::Uncheckable(reason) => format!("uncheckable:{reason}"),
    }
}

fn write_replayable_jsonl(
    path: &str,
    records: &[ReplayableObligationRecord],
) -> std::io::Result<()> {
    let mut lines = String::new();
    let mut records = records.to_vec();
    records.sort_by(|a, b| {
        a.rel
            .cmp(&b.rel)
            .then(a.contract.cmp(&b.contract))
            .then(a.label.cmp(&b.label))
    });
    for record in &records {
        lines.push_str(&serde_json::to_string(&record.to_json())?);
        lines.push('\n');
    }
    std::fs::write(path, lines)
}

/// Extract the dominant blocking operation from an UNDECIDED inv: the first
/// "interesting" (non-const) sub-term kind in the first non-panic atom's args.
/// Returns strings like `ctor:<name>`, `var:<name>`, `let`, `lambda`, `?`.
fn undecided_dom_op(inv: &Value) -> String {
    fn atoms(v: &Value, out: &mut Vec<Value>) {
        if v.get("kind").and_then(Value::as_str) == Some("atomic") {
            out.push(v.clone());
        } else if let Some(ops) = v.get("operands").and_then(Value::as_array) {
            for o in ops {
                atoms(o, out);
            }
        }
    }
    /// Walk a term; return the first interesting operation label.
    fn interesting(v: &Value) -> Option<String> {
        let kind = v.get("kind").and_then(Value::as_str).unwrap_or("");
        match kind {
            "ctor" => {
                let name = v.get("name").and_then(Value::as_str).unwrap_or("?");
                Some(format!("ctor:{name}"))
            }
            "call" => {
                // {kind:"call", callee:"..."} or {kind:"call", name:"..."}
                let name = v
                    .get("callee")
                    .or_else(|| v.get("name"))
                    .and_then(Value::as_str)
                    .unwrap_or("?");
                Some(format!("call:{name}"))
            }
            "var" => {
                let name = v.get("name").and_then(Value::as_str).unwrap_or("?");
                Some(format!("var:{name}"))
            }
            "let" => {
                // let-bound computation: look at the body for the real op.
                if let Some(body) = v.get("body") {
                    if let Some(r) = interesting(body) {
                        return Some(r);
                    }
                }
                Some("let".to_string())
            }
            "lambda" => Some("lambda".to_string()),
            "const" | "" => None, // concrete literal -- not the blocker
            other => {
                // Unknown / future kind: recurse into args/operands first.
                if let Some(args) = v.get("args").and_then(Value::as_array) {
                    for a in args {
                        if let Some(r) = interesting(a) {
                            return Some(r);
                        }
                    }
                }
                if let Some(ops) = v.get("operands").and_then(Value::as_array) {
                    for o in ops {
                        if let Some(r) = interesting(o) {
                            return Some(r);
                        }
                    }
                }
                Some(other.to_string())
            }
        }
    }

    let mut a = Vec::new();
    atoms(inv, &mut a);
    for atom in &a {
        if mentions_panic(atom) {
            continue;
        }
        if let Some(args) = atom.get("args").and_then(Value::as_array) {
            for arg in args {
                if let Some(op) = interesting(arg) {
                    return op;
                }
            }
        }
    }
    "?".to_string()
}

fn offending_smt_term(reason: &str) -> String {
    let Some((_, rest)) = reason.split_once("unknown constant") else {
        return String::new();
    };
    rest.trim()
        .trim_start_matches(':')
        .trim()
        .split_whitespace()
        .next()
        .unwrap_or("")
        .trim_matches(|c| c == '(' || c == ')' || c == '"' || c == '\'')
        .to_string()
}

fn tsv_field(s: &str) -> String {
    s.replace('\t', " ").replace('\n', " ").replace('\r', " ")
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
    undecided_reasons: BTreeMap<String, usize>,
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
            Teeth::SolverTimeout => {
                self.undecided += 1;
                *self
                    .undecided_reasons
                    .entry("z3-timeout".to_string())
                    .or_default() += 1;
            }
            Teeth::Uncheckable(reason) => {
                self.uncheckable += 1;
                if reason.contains("z3 absent") {
                    self.z3_absent += 1;
                }
                // Bucket the reason by its leading token (compile/ill-sorted/...).
                let key = reason
                    .split(':')
                    .next()
                    .unwrap_or("other")
                    .trim()
                    .to_string();
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
        for (k, v) in other.undecided_reasons {
            *self.undecided_reasons.entry(k).or_default() += v;
        }
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
        syn::parse_file(&src).unwrap();
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
    configure_proc_macro2_for_standalone_binary();
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        eprintln!(
            "usage: discharge_sweep <corpus-dir> [--json <out.json>] [--z3 <path>] \
             [--dump-refuted <path>] [--dump-undecided <path>] \
             [--dump-uncheckable <path>] [--dump-replayable <path>] \
             [--production-replay-limit <n>] [--production-replay-json <path>] \
             [--sugar <path>]"
        );
        std::process::exit(2);
    }
    let corpus = Path::new(&args[1]);
    let json_out = arg_value(&args, "--json");
    let dump_replayable = arg_value(&args, "--dump-replayable");
    let production_replay_limit = arg_usize(&args, "--production-replay-limit");
    let production_replay_json = arg_value(&args, "--production-replay-json");
    let sugar_path = arg_value(&args, "--sugar").map(PathBuf::from);
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
    let mut obligations: Vec<Obligation> = Vec::new();
    let mut preflight_replayable = Vec::new();
    let mut preflight_uncheckable = Vec::new();
    let mut no_inv_total = 0usize;
    for (fi, (rel, src)) in files.iter().enumerate() {
        let Ok(file) = syn::parse_file(src) else {
            continue;
        };
        let source: Arc<str> = Arc::from(src.as_str());
        let source_cid = blake3_512_of(source.as_bytes());
        let out = lift_file_with_all_source_imports(
            &file,
            rel,
            &options,
            &macro_imports,
            &const_registry,
            &fn_registry,
        );
        // Does this file carry a refused `&mut` / deref-mutation read? That is the
        // borrow4 / T3 stale-deref class (deferred) -- used to classify any false
        // refutation from this file.
        let file_has_mut_skip = out.skip_reasons.iter().any(|r| {
            let r = r.to_lowercase();
            r.contains("&mut")
                || r.contains("mutation")
                || r.contains("deref")
                || r.contains("borrow")
        });
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
            let contract_doc = match serde_json::from_str::<Value>(&doc) {
                Ok(parsed) => parsed.get(0).cloned(),
                Err(_) => None,
            };
            let inv = contract_doc.as_ref().and_then(declaration_formula);
            let label = format!("{}_{idx}", rel.replace(['/', '.', '-'], "_"));
            match inv {
                Some(inv) if !inv.is_null() => {
                    let Some(contract_doc) = contract_doc else {
                        continue;
                    };
                    obligations.push(Obligation {
                        label,
                        rel: rel.clone(),
                        contract: decl.name.clone(),
                        contract_doc,
                        inv,
                        source: Arc::clone(&source),
                        source_cid: source_cid.clone(),
                        file_has_mut_skip,
                    });
                    file_obs += 1;
                }
                _ => {
                    let formula = Value::Null;
                    let contract_doc = contract_doc.unwrap_or_else(|| {
                        json!({
                            "name": decl.name,
                            "reason": "contract JSON did not parse"
                        })
                    });
                    no_inv_total += 1;
                    preflight_replayable.push(ReplayableObligationRecord::new(
                        &label,
                        rel,
                        &decl.name,
                        source.as_ref(),
                        &contract_doc,
                        &formula,
                        Teeth::Uncheckable("no-inv".to_string()),
                        None,
                    ));
                    preflight_uncheckable.push(UncheckableRecord {
                        label,
                        contract: decl.name.clone(),
                        file: rel.clone(),
                        signature: String::new(),
                        dom_op: String::new(),
                        reason: "no-inv".to_string(),
                        offending_smt_term: String::new(),
                    });
                }
            }
        }
        eprintln!(
            "  lift {}/{total_files}: {rel} -> {file_obs} obligations",
            fi + 1
        );
    }
    eprintln!(
        "discharge_sweep: {} warranted obligations to check (+{} no-inv)",
        obligations.len(),
        no_inv_total
    );

    // PHASE 2 (parallel discharge): one z3 verdict per obligation, fanned out
    // across cores. The per-query timeout bounds any pathological obligation.
    // Two ledgers: FULL inv, and the panic-filtered VALUE-claim inv (the extra z3
    // runs ONLY when the obligation actually carries a panic conjunct). REFUTED
    // obligations are classified (the corpus is all-true -> every one is a false
    // refutation).
    let checked = AtomicUsize::new(0);
    let total_ob = obligations.len();
    let acc = obligations
        .par_iter()
        .map(|obligation| {
            let full = discharge_inv(&obligation.inv, &z3_path, &obligation.label);
            // Value-claim teeth: reuse FULL when no panic conjunct (no extra z3).
            let value = match value_only_inv(&obligation.inv) {
                Some(vi) if vi != obligation.inv => Some(discharge_inv(
                    &vi,
                    &z3_path,
                    &format!("{}_v", obligation.label),
                )),
                Some(_) => Some(full.clone()),
                None => None, // panic-only obligation -- no value claim to teeth
            };
            let replayable = obligation.replay_record(full.clone(), value.clone());
            let refuted = matches!(full, Teeth::Refuted).then(|| RefutedRecord {
                file: obligation.rel.clone(),
                signature: refuted_signature(&obligation.inv),
                mut_skip_class: obligation.file_has_mut_skip,
            });
            let undecided =
                matches!(full, Teeth::Undecided | Teeth::SolverTimeout).then(|| UndecidedRecord {
                    file: obligation.rel.clone(),
                    signature: refuted_signature(&obligation.inv),
                    dom_op: undecided_dom_op(&obligation.inv),
                });
            let uncheckable = match &full {
                Teeth::Uncheckable(reason) => Some(UncheckableRecord {
                    label: obligation.label.clone(),
                    contract: obligation.contract.clone(),
                    file: obligation.rel.clone(),
                    signature: refuted_signature(&obligation.inv),
                    dom_op: undecided_dom_op(&obligation.inv),
                    reason: reason.clone(),
                    offending_smt_term: offending_smt_term(reason),
                }),
                _ => None,
            };
            let n = checked.fetch_add(1, Ordering::Relaxed) + 1;
            if n % 500 == 0 {
                eprintln!("  discharged {n}/{total_ob}");
            }
            (full, value, refuted, undecided, uncheckable, replayable)
        })
        .fold(
            Acc::default,
            |mut acc, (full, value, refuted, undecided, uncheckable, replayable)| {
                acc.full.record(&full);
                if let Some(v) = &value {
                    acc.value.record(v);
                }
                if let Some(r) = refuted {
                    acc.refuted.push(r);
                }
                if let Some(u) = undecided {
                    acc.undecided.push(u);
                }
                if let Some(u) = uncheckable {
                    acc.uncheckable.push(u);
                }
                acc.replayable.push(replayable);
                acc
            },
        )
        .reduce(Acc::default, |mut a, b| {
            a.merge(b);
            a
        });
    let mut acc = acc;
    for _ in 0..no_inv_total {
        acc.full.record(&Teeth::Uncheckable("no-inv".into()));
    }
    acc.uncheckable.extend(preflight_uncheckable);
    acc.replayable.extend(preflight_replayable);

    print_headline(&acc.full, &acc.value, z3_available, &z3_path);
    print_refuted_breakdown(&acc.refuted);

    if let Some(path) = dump_replayable {
        if let Err(e) = write_replayable_jsonl(&path, &acc.replayable) {
            eprintln!("discharge_sweep: write --dump-replayable {path}: {e}");
        }
    }

    let production_replay = production_replay_limit.map(|limit| {
        production_replay_subset(
            &acc.replayable,
            limit,
            &z3_path,
            sugar_path.as_deref(),
            production_replay_json.as_deref(),
        )
    });

    if let Some(path) = arg_value(&args, "--dump-refuted") {
        let mut lines = String::from("file\tsignature\tmut_skip_class\n");
        let mut recs = acc.refuted.clone();
        recs.sort_by(|a, b| a.file.cmp(&b.file).then(a.signature.cmp(&b.signature)));
        for r in &recs {
            lines.push_str(&format!(
                "{}\t{}\t{}\n",
                r.file, r.signature, r.mut_skip_class
            ));
        }
        if let Err(e) = std::fs::write(&path, lines) {
            eprintln!("discharge_sweep: write --dump-refuted {path}: {e}");
        }
    }

    if let Some(path) = arg_value(&args, "--dump-undecided") {
        let mut lines = String::from("file\tsignature\tdom_op\n");
        let mut recs = acc.undecided.clone();
        recs.sort_by(|a, b| {
            a.dom_op
                .cmp(&b.dom_op)
                .then(a.signature.cmp(&b.signature))
                .then(a.file.cmp(&b.file))
        });
        for r in &recs {
            lines.push_str(&format!("{}\t{}\t{}\n", r.file, r.signature, r.dom_op));
        }
        if let Err(e) = std::fs::write(&path, lines) {
            eprintln!("discharge_sweep: write --dump-undecided {path}: {e}");
        }
    }

    if let Some(path) = arg_value(&args, "--dump-uncheckable") {
        let mut lines =
            String::from("file\tlabel\tcontract\tsignature\tdom_op\treason\toffending_smt_term\n");
        let mut recs = acc.uncheckable.clone();
        recs.sort_by(|a, b| {
            a.reason
                .cmp(&b.reason)
                .then(a.dom_op.cmp(&b.dom_op))
                .then(a.signature.cmp(&b.signature))
                .then(a.file.cmp(&b.file))
                .then(a.label.cmp(&b.label))
        });
        for r in &recs {
            lines.push_str(&format!(
                "{}\t{}\t{}\t{}\t{}\t{}\t{}\n",
                tsv_field(&r.file),
                tsv_field(&r.label),
                tsv_field(&r.contract),
                tsv_field(&r.signature),
                tsv_field(&r.dom_op),
                tsv_field(&r.reason),
                tsv_field(&r.offending_smt_term),
            ));
        }
        if let Err(e) = std::fs::write(&path, lines) {
            eprintln!("discharge_sweep: write --dump-uncheckable {path}: {e}");
        }
    }

    if let Some(path) = json_out {
        let f = &acc.full;
        let v = &acc.value;
        let mut_class = acc.refuted.iter().filter(|r| r.mut_skip_class).count();
        let obj = json!({
            "teethed_ledger": {
                "warranted_obligations": f.warranted_obligations,
                "replayable_obligations": acc.replayable.len(),
                "discharged": f.discharged(),
                "discharged_substantive": f.discharged_substantive,
                "discharged_reflexive": f.discharged_reflexive,
                "refuted": f.refuted,
                "undecided": f.undecided,
                "uncheckable": f.uncheckable,
                "z3_absent": f.z3_absent,
                "undecided_reasons": f.undecided_reasons,
                "uncheckable_reasons": f.uncheckable_reasons,
                // Panic-filtered VALUE-claim teethedness (drops panic-freedom
                // conjuncts): the honest "how much of the value is proven".
                "value_obligations": v.warranted_obligations,
                "value_discharged": v.discharged(),
                "value_discharged_substantive": v.discharged_substantive,
                "value_refuted": v.refuted,
                "value_undecided": v.undecided,
                // False-refutation breakdown (corpus is all-true).
                "refuted_mut_skip_class": mut_class,
                "refuted_other_class": f.refuted.saturating_sub(mut_class),
                "production_replay": production_replay,
            }
        });
        if let Err(e) = std::fs::write(&path, serde_json::to_string_pretty(&obj).unwrap()) {
            eprintln!("discharge_sweep: write --json {path}: {e}");
        }
    }
}

/// Combined parallel accumulator: full-inv ledger, value-claim ledger, and the
/// list of (false) refutations + undecided records for classification.
#[derive(Default)]
struct Acc {
    full: Tally,
    value: Tally,
    refuted: Vec<RefutedRecord>,
    undecided: Vec<UndecidedRecord>,
    uncheckable: Vec<UncheckableRecord>,
    replayable: Vec<ReplayableObligationRecord>,
}

impl Acc {
    fn merge(&mut self, other: Acc) {
        self.full.merge(other.full);
        self.value.merge(other.value);
        self.refuted.extend(other.refuted);
        self.undecided.extend(other.undecided);
        self.uncheckable.extend(other.uncheckable);
        self.replayable.extend(other.replayable);
    }
}

fn print_refuted_breakdown(refuted: &[RefutedRecord]) {
    if refuted.is_empty() {
        println!("  REFUTED breakdown: 0 -- no false refutations (the floor holds).");
        return;
    }
    let mut_class = refuted.iter().filter(|r| r.mut_skip_class).count();
    let other = refuted.len() - mut_class;
    println!(
        "  FALSE REFUTATIONS = {} (all-true corpus -> every refutation is a stale/wrong lift; floor target 0):",
        refuted.len()
    );
    println!(
        "    {mut_class} stale-&mut/deref class (borrow4 / T3, deferred #6/#16); {other} OTHER class (NOT T3 -- candidates fixable now)"
    );
    let mut by_sig: BTreeMap<String, usize> = BTreeMap::new();
    let mut by_file: BTreeMap<String, usize> = BTreeMap::new();
    for r in refuted {
        *by_sig.entry(r.signature.clone()).or_default() += 1;
        *by_file.entry(r.file.clone()).or_default() += 1;
    }
    let mut sigs: Vec<_> = by_sig.into_iter().collect();
    sigs.sort_by(|a, b| b.1.cmp(&a.1));
    println!(
        "    by inv shape: {}",
        sigs.iter()
            .map(|(k, v)| format!("{k}={v}"))
            .collect::<Vec<_>>()
            .join(" ")
    );
    let mut filz: Vec<_> = by_file.into_iter().collect();
    filz.sort_by(|a, b| b.1.cmp(&a.1));
    println!(
        "    by file (top): {}",
        filz.iter()
            .take(8)
            .map(|(k, v)| format!("{k}={v}"))
            .collect::<Vec<_>>()
            .join(" ")
    );
}

fn print_headline(t: &Tally, v: &Tally, z3_seen: bool, z3_path: &str) {
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
    // Panic-filtered VALUE-claim ledger: the honest "how much of the VALUE is
    // proven" (full-inv discharged is a lower bound -- an opaque panic-freedom
    // conjunct drags a value-teethed claim into UNDECIDED).
    let vdenom = v.warranted_obligations.max(1) as f64;
    println!(
        "  value-claim (panic-filtered): obligations={} discharged={} ({:.1}%) [substantive={}] \
         refuted={} undecided={}",
        v.warranted_obligations,
        v.discharged(),
        (v.discharged() as f64) * 100.0 / vdenom,
        v.discharged_substantive,
        v.refuted,
        v.undecided,
    );
    println!(
        "  DISCHARGED = z3 proves negation UNSAT (teeth, proven). UNDECIDED = lifted but \
         congruence-only / no teeth (the bucket coverage hid). REFUTED = invariant UNSAT (proven false)."
    );
    if !t.undecided_reasons.is_empty() {
        let mut reasons: Vec<_> = t.undecided_reasons.iter().collect();
        reasons.sort_by(|a, b| b.1.cmp(a.1).then(a.0.cmp(b.0)));
        let shown: Vec<String> = reasons
            .into_iter()
            .map(|(k, v)| format!("{k}={v}"))
            .collect();
        println!("  undecided by reason: {}", shown.join(" "));
    }
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

fn arg_usize(args: &[String], flag: &str) -> Option<usize> {
    arg_value(args, flag).map(|raw| {
        raw.parse::<usize>().unwrap_or_else(|err| {
            eprintln!("discharge_sweep: {flag} must be a positive integer, got `{raw}`: {err}");
            std::process::exit(2);
        })
    })
}

fn rust_workspace() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-lift-rust-tests has a workspace parent")
        .to_path_buf()
}

fn configure_proc_macro2_for_standalone_binary() {
    // This executable parses and rewrites tokens, but it is not a procedural
    // macro and therefore never has rustc's proc-macro bridge available.
    // Avoid proc-macro2's runtime bridge detection selecting compiler-backed
    // spans on newer toolchains; those spans panic as soon as they touch the
    // inactive bridge. Mixed fallback/compiler backends also turn large
    // for_replay expansions into allocator/stack crashes (#4591).
    proc_macro2::fallback::force();
}

fn toml_string(value: &str) -> String {
    format!("\"{}\"", value.replace('\\', "\\\\").replace('"', "\\\""))
}

fn sugar_binary(sugar_path: Option<&Path>) -> Result<PathBuf, String> {
    if let Some(path) = sugar_path {
        if path.is_file() {
            return path
                .canonicalize()
                .map_err(|err| format!("canonicalize --sugar {}: {err}", path.display()));
        }
        return Err(format!("--sugar path is not a file: {}", path.display()));
    }
    let workspace = rust_workspace();
    let repo = workspace.parent().and_then(Path::parent).ok_or_else(|| {
        "crime=production replay without sugar CLI; owner=discharge_sweep; \
             illegal shape=rust workspace is not under implementations/rust; \
             replacement=run discharge_sweep from a checked-out sugar repo"
            .to_string()
    })?;
    let profile = if cfg!(debug_assertions) {
        "debug"
    } else {
        "release"
    };
    let output = Command::new(repo.join("bin/sugarbin"))
        .arg("--profile")
        .arg(profile)
        .output()
        .map_err(|err| format!("spawn bin/sugarbin: {err}"))?;
    if !output.status.success() {
        return Err(format!(
            "crime=production replay without sugar CLI; owner=discharge_sweep; \
             illegal shape=bin/sugarbin could not resolve active-profile sugar binary; \
             replacement=repair the sugarbin handoff path before this harness\n\
             status={}\nstdout:\n{}\nstderr:\n{}",
            output.status,
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    let path = String::from_utf8(output.stdout)
        .map_err(|err| format!("bin/sugarbin emitted non-utf8 path: {err}"))?
        .trim()
        .to_owned();
    let candidate = PathBuf::from(path);
    if candidate.is_file() {
        return candidate
            .canonicalize()
            .map_err(|err| format!("canonicalize sugar {}: {err}", candidate.display()));
    }
    Err(format!(
        "crime=production replay without sugar CLI; owner=discharge_sweep; \
         illegal shape=bin/sugarbin returned missing binary at {}; \
         replacement=repair the sugarbin handoff path or pass --sugar",
        candidate.display()
    ))
}

fn unique_replay_project() -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("system time after epoch")
        .as_nanos();
    let dir = std::env::temp_dir().join(format!(
        "discharge-sweep-production-replay-{}-{stamp}",
        std::process::id()
    ));
    std::fs::create_dir_all(&dir).expect("mkdir production replay project");
    dir
}

fn write_production_replay_project(
    project: &Path,
    records: &[ReplayableObligationRecord],
) -> Result<(), String> {
    let workspace = rust_workspace();
    std::fs::create_dir_all(project.join("tests")).map_err(|err| format!("mkdir tests: {err}"))?;
    std::fs::create_dir_all(project.join(".sugar/lift/rust-test-assertions"))
        .map_err(|err| format!("mkdir lift: {err}"))?;
    std::fs::create_dir_all(project.join(".sugar/components/rust-test-assertions"))
        .map_err(|err| format!("mkdir component: {err}"))?;
    std::fs::create_dir_all(project.join(".sugar/ir-compilers/smt-lib"))
        .map_err(|err| format!("mkdir compiler: {err}"))?;

    let mut sources: BTreeMap<&str, (&str, &str)> = BTreeMap::new();
    for record in records {
        match sources.get(record.rel.as_str()) {
            Some((seen_cid, _)) if *seen_cid != record.source_cid => {
                return Err(format!(
                    "rel `{}` maps to multiple source CIDs: {} and {}",
                    record.rel, seen_cid, record.source_cid
                ));
            }
            Some(_) => {}
            None => {
                sources.insert(&record.rel, (&record.source_cid, &record.source));
            }
        }
    }
    for (rel, (_, source)) in sources {
        let dest = project.join("tests").join(rel);
        if let Some(parent) = dest.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|err| format!("mkdir {}: {err}", parent.display()))?;
        }
        std::fs::write(&dest, source).map_err(|err| format!("write {}: {err}", dest.display()))?;
    }

    let lean_project = workspace
        .parent()
        .and_then(Path::parent)
        .expect("rust workspace lives under implementations/rust")
        .join("tools/portfolio/lean-mathlib");
    std::fs::write(
        project.join(".sugar/config.toml"),
        format!(r#"[[plugins]]
name = "rust-test-assertions-lift"
kind = "lift"
surface = "rust-test-assertions"
emit = "ir-document"

[platform_profile]
language = "rust"
library = "discharge-sweep-production-replay"
version = "rustc 1.96.0"

[solvers]
mode = "first-wins"
portfolio = ["maude", "z3", "cvc5", "vampire", "coq", "lean"]

[solvers.maude]
binary = "maude"
ir_compiler = "maude"
timeout_seconds = 30
ceta_gate = true
ceta_binary = "ceta"
termination_prover = "aprove"
confluence_checker = "csi"

[solvers.z3]
binary = "z3"
ir_compiler = "smt-lib-v2.6"
flags = ["-smt2", "-in"]
timeout_seconds = 30
version = "4.x"

[solvers.cvc5]
binary = "cvc5"
ir_compiler = "smt-lib-v2.6"
flags = ["--lang=smt2", "--produce-models"]
timeout_seconds = 30

[solvers.vampire]
binary = "vampire"
ir_compiler = "smt-lib-v2.6"
flags = ["--input_syntax", "smtlib2", "--output_mode", "smtcomp"]
timeout_seconds = 30

[solvers.coq]
binary = "coqc"
ir_compiler = "coq"
timeout_seconds = 60

[solvers.lean]
binary = "lake"
ir_compiler = "lean"
timeout_seconds = 60
lake_project = "{lean_project}"

[rust-test-assertions.target_cfg]
target = "x86_64-apple-darwin"
facts = ["test", "debug_assertions", "target_arch=\"x86_64\"", "target_pointer_width=\"64\"", "target_os=\"macos\"", "unix"]
"#, lean_project = lean_project.display()),
    )
    .map_err(|err| format!("write .sugar/config.toml: {err}"))?;

    std::fs::write(
        project.join(".sugar/lift/rust-test-assertions/manifest.toml"),
        format!(
            r#"name = "rust-test-assertions-lift"
version = "0.1.0"
protocol_version = "pep/1.7.0"
kind = "lift"
command = ["cargo", "run", "-p", "sugar-lift-rust-tests", "--bin", "rust_test_assertions_rpc", "--quiet", "--"]
working_dir = "{ws}"

[capabilities]
authoring_surfaces = ["rust-test-assertions"]
ir_version = "v1.1.0"
emits_signed_mementos = false
"#,
            ws = workspace.display()
        ),
    )
    .map_err(|err| format!("write lift manifest: {err}"))?;

    let component_script = project
        .join(".sugar/components/rust-test-assertions")
        .join("component.sh");
    let initialize_response = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "name": "rust-test-assertions-component",
            "protocol_version": "sugar-component/1",
            "capabilities": {}
        }
    })
    .to_string();
    let plan_response = json!({
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "decision": "claim",
            "plugins": [{
                "name": "rust-test-assertions-lift",
                "kind": "lift",
                "surface": "rust-test-assertions",
                "emit": "ir-document"
            }],
            "lift_manifests": [{
                "surface": "rust-test-assertions",
                "name": "rust-test-assertions-lift",
                "version": "0.1.0",
                "protocol_version": "pep/1.7.0",
                "command": [
                    "cargo",
                    "run",
                    "-p",
                    "sugar-lift-rust-tests",
                    "--bin",
                    "rust_test_assertions_rpc",
                    "--quiet",
                    "--"
                ],
                "working_dir": workspace.display().to_string()
            }],
            "diagnostics": [{
                "level": "info",
                "message": "rust-test-assertions component planned"
            }]
        }
    })
    .to_string();
    let shutdown_response = json!({"jsonrpc": "2.0", "id": 3, "result": null}).to_string();
    std::fs::write(
        &component_script,
        format!(
            r#"while IFS= read -r line; do
  case "$line" in
    *'"method":"initialize"'*)
      printf '%s\n' '{initialize_response}'
      ;;
    *'"method":"sugar.component.plan"'*)
      printf '%s\n' '{plan_response}'
      ;;
    *'"method":"shutdown"'*)
      printf '%s\n' '{shutdown_response}'
      exit 0
      ;;
  esac
done
"#
        ),
    )
    .map_err(|err| format!("write component script: {err}"))?;
    std::fs::write(
        project.join(".sugar/components/rust-test-assertions/manifest.toml"),
        format!(
            "name = \"rust-test-assertions-component\"\nprotocol_version = \"sugar-component/1\"\ncommand = [\"/bin/sh\", {}]\n",
            toml_string(&component_script.display().to_string())
        ),
    )
    .map_err(|err| format!("write component manifest: {err}"))?;

    std::fs::write(
        project.join(".sugar/ir-compilers/smt-lib/manifest.toml"),
        format!(
            r#"name = "smt-lib-reference"
version = "0.1.0"
protocol_version = "sugar-ir-compiler/1"
command = ["cargo", "run", "-p", "sugar-ir-compiler-smt-lib", "--bin", "sugar-ir-smt-lib", "--quiet", "--"]
working_dir = "{ws}"
dialects = ["smt-lib-v2.6"]
"#,
            ws = workspace.display()
        ),
    )
    .map_err(|err| format!("write compiler manifest: {err}"))?;
    Ok(())
}

fn production_rows(project: &Path, sugar: &Path, z3: &str) -> Result<Vec<Value>, String> {
    let mint = Command::new(sugar)
        .current_dir(project)
        .arg("mint")
        .arg("--out")
        .arg(project)
        .arg("--quiet")
        .output()
        .map_err(|err| format!("spawn sugar mint: {err}"))?;
    if !mint.status.success() {
        return Err(format!(
            "sugar mint failed\nstdout:\n{}\nstderr:\n{}",
            String::from_utf8_lossy(&mint.stdout),
            String::from_utf8_lossy(&mint.stderr)
        ));
    }
    let prove = Command::new(sugar)
        .current_dir(project)
        .arg("prove")
        .arg(".")
        .arg("--json")
        .arg("--z3")
        .arg(z3)
        .output()
        .map_err(|err| format!("spawn sugar prove: {err}"))?;
    if prove.stdout.is_empty() {
        return Err(format!(
            "sugar prove produced no JSON\nstatus={}\nstdout:\n{}\nstderr:\n{}",
            prove.status,
            String::from_utf8_lossy(&prove.stdout),
            String::from_utf8_lossy(&prove.stderr)
        ));
    }
    let stdout = String::from_utf8_lossy(&prove.stdout);
    let doc: Value = serde_json::from_str(&stdout).map_err(|err| {
        format!(
            "sugar prove returned malformed JSON: {err}\nstdout:\n{stdout}\nstderr:\n{}",
            String::from_utf8_lossy(&prove.stderr)
        )
    })?;
    Ok(doc["rows"]
        .as_array()
        .ok_or_else(|| format!("sugar prove JSON has no rows: {doc:#}"))?
        .clone())
}

fn statuses_for_record(rows: &[Value], record: &ReplayableObligationRecord) -> Vec<String> {
    let rel_needle = format!("tests/{}", record.rel);
    let mut contract_statuses = rows
        .iter()
        .filter(|row| {
            row["property"]
                .as_str()
                .map(|property| property.contains(&record.contract))
                .unwrap_or(false)
        })
        .filter_map(|row| row["status"].as_str().map(str::to_string))
        .collect::<Vec<_>>();
    if contract_statuses.is_empty() {
        contract_statuses = rows
            .iter()
            .filter(|row| {
                row["property"]
                    .as_str()
                    .map(|property| property.contains(&rel_needle))
                    .unwrap_or(false)
            })
            .filter_map(|row| row["status"].as_str().map(str::to_string))
            .collect::<Vec<_>>();
    }
    let mut statuses = contract_statuses;
    statuses.sort();
    statuses.dedup();
    statuses
}

fn production_direction(statuses: &[String]) -> Option<&'static str> {
    if statuses.iter().any(|status| status == "unsatisfied") {
        Some("refuted")
    } else if !statuses.is_empty() && statuses.iter().all(|status| status == "discharged") {
        Some("discharged")
    } else {
        None
    }
}

fn replay_classification(record: &ReplayableObligationRecord, statuses: &[String]) -> &'static str {
    match (record.shadow_full.as_str(), production_direction(statuses)) {
        ("refuted", Some("discharged")) => "active-disagreement",
        (shadow, Some("refuted")) if shadow.starts_with("discharged:") => "active-disagreement",
        (_, None) => "coverage-gap",
        _ => "agreement-or-nondirectional",
    }
}

fn production_replay_subset(
    records: &[ReplayableObligationRecord],
    limit: usize,
    z3: &str,
    sugar_path: Option<&Path>,
    output_path: Option<&str>,
) -> Value {
    let mut selected = records.to_vec();
    selected.sort_by(|a, b| {
        a.rel
            .cmp(&b.rel)
            .then(a.contract.cmp(&b.contract))
            .then(a.label.cmp(&b.label))
    });
    selected.truncate(limit);
    if selected.is_empty() {
        return json!({
            "checked": 0,
            "active_disagreements": 0,
            "coverage_gaps": 0,
            "rows": [],
        });
    }
    let result = (|| -> Result<Value, String> {
        let sugar = sugar_binary(sugar_path)?;
        let project = unique_replay_project();
        write_production_replay_project(&project, &selected)?;
        let rows = production_rows(&project, &sugar, z3)?;
        let mut active = 0usize;
        let mut coverage = 0usize;
        let mut replay_rows = Vec::new();
        for record in &selected {
            let statuses = statuses_for_record(&rows, record);
            let classification = replay_classification(record, &statuses);
            if classification == "active-disagreement" {
                active += 1;
            } else if classification == "coverage-gap" {
                coverage += 1;
            }
            replay_rows.push(json!({
                "label": record.label,
                "rel": record.rel,
                "contract": record.contract,
                "source_cid": record.source_cid,
                "contract_cid": record.contract_cid,
                "formula_cid": record.formula_cid,
                "shadow_full": record.shadow_full,
                "production_statuses": statuses,
                "classification": classification,
            }));
        }
        Ok(json!({
            "authority": "source-to-sugar-cli",
            "project": project.display().to_string(),
            "checked": selected.len(),
            "active_disagreements": active,
            "coverage_gaps": coverage,
            "production_row_count": rows.len(),
            "rows": replay_rows,
        }))
    })();
    let value = match result {
        Ok(value) => value,
        Err(err) => json!({
            "authority": "source-to-sugar-cli",
            "checked": 0,
            "active_disagreements": 0,
            "coverage_gaps": 0,
            "error": err,
        }),
    };
    if let Some(path) = output_path {
        if let Err(err) = std::fs::write(path, serde_json::to_string_pretty(&value).unwrap()) {
            eprintln!("discharge_sweep: write --production-replay-json {path}: {err}");
        }
    }
    let checked = value["checked"].as_u64().unwrap_or(0);
    let active = value["active_disagreements"].as_u64().unwrap_or(0);
    let coverage = value["coverage_gaps"].as_u64().unwrap_or(0);
    eprintln!(
        "discharge_sweep production replay: checked={checked} active_disagreements={active} coverage_gaps={coverage}"
    );
    value
}

#[cfg(test)]
mod tests {
    use super::*;
    use sugar_canonicalizer::{blake3_512_of, jcs_cid_of_json, BLAKE3_512_PREFIX};

    #[test]
    fn standalone_discharge_sweep_forces_proc_macro2_fallback() {
        configure_proc_macro2_for_standalone_binary();

        let _ = proc_macro2::Span::call_site();
        let _: proc_macro2::TokenStream = "assert!(true)".parse().unwrap();
    }

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

    #[test]
    fn replayable_obligation_record_pins_source_contract_and_formula_identity() {
        let source = "fn claim() { assert_eq!(1 + 1, 2); }\n";
        let formula = json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "const", "sort": "Int", "value": 2},
                {"kind": "const", "sort": "Int", "value": 2}
            ]
        });
        let contract_doc = json!({
            "name": "claim",
            "inv": formula.clone()
        });

        let record = ReplayableObligationRecord::new(
            "tests_arith_rs_0",
            "arith.rs",
            "claim",
            source,
            &contract_doc,
            &formula,
            Teeth::Discharged { reflexive: false },
            None,
        );

        assert_eq!(record.source, source);
        assert_eq!(record.source_cid, blake3_512_of(source.as_bytes()));
        assert_eq!(record.contract_cid, jcs_cid_of_json(&contract_doc));
        assert_eq!(record.formula_cid, jcs_cid_of_json(&formula));
        assert!(record.source_cid.starts_with(BLAKE3_512_PREFIX));
        assert!(record.contract_cid.starts_with(BLAKE3_512_PREFIX));
        assert!(record.formula_cid.starts_with(BLAKE3_512_PREFIX));
    }

    #[test]
    fn production_status_matching_prefers_contract_identity_before_file_fallback() {
        let source = "fn claim_a() { assert_eq!(1, 1); }\nfn claim_b() { assert_eq!(2, 2); }\n";
        let formula = json!({"kind": "const", "sort": "Bool", "value": true});
        let contract_doc = json!({"name": "claim_a", "inv": formula.clone()});
        let record = ReplayableObligationRecord::new(
            "tests_multi_rs_0",
            "multi.rs",
            "claim_a",
            source,
            &contract_doc,
            &formula,
            Teeth::Discharged { reflexive: false },
            None,
        );
        let rows = vec![
            json!({"property": "tests/multi.rs::claim_a", "status": "discharged"}),
            json!({"property": "tests/multi.rs::claim_b", "status": "refused"}),
        ];

        assert_eq!(statuses_for_record(&rows, &record), vec!["discharged"]);

        let fallback_rows = vec![json!({"property": "tests/multi.rs", "status": "refused"})];
        assert_eq!(
            statuses_for_record(&fallback_rows, &record),
            vec!["refused"]
        );
    }

    #[test]
    fn solver_timeout_is_counted_undecided_not_uncheckable() {
        let mut tally = Tally::default();
        tally.record(&Teeth::SolverTimeout);
        assert_eq!(tally.undecided, 1);
        assert_eq!(tally.uncheckable, 0);
        assert_eq!(tally.undecided_reasons.get("z3-timeout"), Some(&1));
    }

    #[test]
    fn declaration_formula_uses_pre_post_and_inv_slots() {
        let pre = json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                { "kind": "const", "value": 1, "sort": { "kind": "primitive", "name": "Int" } },
                { "kind": "const", "value": 1, "sort": { "kind": "primitive", "name": "Int" } }
            ]
        });
        let post = json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                { "kind": "const", "value": 2, "sort": { "kind": "primitive", "name": "Int" } },
                { "kind": "const", "value": 2, "sort": { "kind": "primitive", "name": "Int" } }
            ]
        });
        let inv = json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                { "kind": "const", "value": 3, "sort": { "kind": "primitive", "name": "Int" } },
                { "kind": "const", "value": 3, "sort": { "kind": "primitive", "name": "Int" } }
            ]
        });
        let pre_only = json!({
            "kind": "contract",
            "name": "source-pre",
            "outBinding": "out",
            "pre": pre
        });
        assert_eq!(
            declaration_formula(&pre_only).expect("pre is a checkable formula"),
            pre_only["pre"]
        );

        let all_slots = json!({
            "kind": "contract",
            "name": "source-complete",
            "outBinding": "out",
            "pre": pre_only["pre"].clone(),
            "post": post,
            "inv": inv
        });
        assert_eq!(
            declaration_formula(&all_slots).expect("formula slots are checkable"),
            json!({
                "kind": "and",
                "operands": [
                    all_slots["pre"].clone(),
                    all_slots["post"].clone(),
                    all_slots["inv"].clone()
                ]
            })
        );
        assert!(declaration_formula(&json!({
            "kind": "contract",
            "name": "empty",
            "outBinding": "out"
        }))
        .is_none());
    }

    // The discharge gate must give teeth the right verdicts and never DISCHARGE
    // a false claim. Skips when z3 is unavailable.
    #[test]
    fn discharge_gate_teeth_asymmetry() {
        let Some(z3) = z3() else { return };
        // Teethed: literal index. True -> discharged; false -> refuted.
        assert!(matches!(
            discharge_inv(
                &inv_of("#[test] fn t() { assert_eq!([7,7,7][1], 7); }"),
                &z3,
                "t1"
            ),
            Teeth::Discharged { .. }
        ));
        assert_eq!(
            discharge_inv(
                &inv_of("#[test] fn t() { assert_eq!([7,7,7][1], 99); }"),
                &z3,
                "t2"
            ),
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
