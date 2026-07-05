// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar derive`: z3.model-based derived-value computation.
//
// Given a BV expression tree (the walked universe body, e.g. Math.abs) and one
// or more concrete integer inputs, asks z3 what the universe COMPUTES.
//
// This is the second solver primitive, complementing `check-sat` (yes/no
// membership). The derive path emits a QF_BV query:
//   (set-logic QF_BV)
//   (declare-const a (_ BitVec 32))
//   (declare-const r (_ BitVec 32))
//   (assert (= r (ite (bvslt a #x00000000) (bvneg a) a)))  ; walked body
//   (assert (= a #x80000000))                               ; concrete input
//   (check-sat)
//   (get-value (r))                                         ; => ((r #x80000000)) = -2147483648
//
// The punchline: z3.model independently derives abs(MIN_VALUE) = -2147483648
// from the walked Math.abs body. The JDK's own AbsTests.java SWEARS the same
// value (line 110, "// Strange but true"). Two unrelated witnesses, same
// strange truth, no execution. Derived, not asserted.
//
// NO-VENDOR AXIOM: the lift is the source of truth. The bv_tree MUST come from
// the lifted universe, never from a formula the CLI hardcodes. Two sound
// sources are offered:
//   --from-proof <path>   read the int32.eq-bv-expr universe atom out of a
//                         minted .proof (the universe atom's args[1] = bv_tree).
//   --bv-expr <json>      the extracted bv_tree JSON, passed in by a caller that
//                         already pulled it from the lift/.proof (e.g. run.sh).
// There is NO built-in abs formula. If the universe atom is absent from the
// proof, `--from-proof` has nothing to derive from and REFUSES (it never falls
// back to a built-in). That refusal is the proof the chain is real.
//
// ADDITIVE: this verb is NEW. The discharge path (`sugar prove`/`sugar verify`)
// is not modified.

use std::path::PathBuf;

use clap::Parser;
use owo_colors::OwoColorize;
use serde_json::Value as Json;
use sugar_proof_envelope::ProofGraph;

use sugar_ir_compiler_smt_lib::derive_query::{
    emit_blocks_derive_query, emit_derive_query, parse_model_string,
};
use sugar_verifier::solvers::model::solve_with_model;

use crate::{OutputFlags, EXIT_OK, EXIT_SOLVER_FAIL, EXIT_USER_ERROR};

#[derive(Parser, Debug, Clone)]
pub struct ModelArgs {
    /// Read the BV expression tree from a minted .proof file.
    ///
    /// Walks the catalog's members for an `int32.eq-bv-expr` universe atom and
    /// extracts its `args[1]` (the bv_tree walked from the vendor source). This
    /// is the no-vendor-axiom path: the formula comes from the lifted universe,
    /// never from a built-in. If no universe atom is present, REFUSES.
    #[arg(long = "from-proof", conflicts_with = "bv_expr")]
    pub from_proof: Option<PathBuf>,

    /// The BV expression tree as JSON (the walked universe body).
    ///
    /// This is the `bv_tree` from an `int32.eq-bv-expr` atom, e.g.:
    ///   '{"kind":"ctor","name":"bv32.ite","args":[...]}'
    ///
    /// Intended for callers (e.g. run.sh) that already extracted the atom from
    /// the lift output / .proof. NOT a hardcoded convenience — the JSON must
    /// originate from a minted artifact.
    #[arg(long = "bv-expr", conflicts_with = "from_proof")]
    pub bv_expr: Option<String>,

    /// Base64 STRONG-TIER string derive (paper 26 seam).
    ///
    /// The `args[1]` payload JSON of a `str.eq-bv-blocks` universe atom (the
    /// per-character block equations walked from the vendor's encode body). The
    /// input bytes are baked into the payload, so `--input` is NOT used in this
    /// mode. z3 computes the output STRING from the equations — derived, not
    /// executed (e.g. encode("bar") → "YmFy").
    #[arg(long = "blocks-payload", conflicts_with_all = ["from_proof", "bv_expr"])]
    pub blocks_payload: Option<String>,

    /// Concrete 32-bit integer input(s) for the query.
    /// Supply one per var in the BV tree (in DFS var order).
    /// For Math.abs: one input (the argument `a`).
    /// NOT required in `--blocks-payload` mode (inputs are baked into the payload).
    #[arg(long = "input", short = 'i', required = false)]
    pub inputs: Vec<i32>,

    /// Path to z3 binary (default: "z3" on PATH).
    #[arg(long, default_value = "z3")]
    pub z3: String,

    /// Write the derive receipt JSON to this file.
    #[arg(long = "receipt-out")]
    pub receipt_out: Option<PathBuf>,

    #[command(flatten)]
    pub out: OutputFlags,
}

/// The JSON receipt structure.
#[derive(Debug, serde::Serialize)]
struct DeriveReceipt {
    /// Where the bv_tree came from (a minted .proof path, or "caller-supplied bv-expr").
    bv_tree_source: String,
    /// The BV tree JSON (the walked universe expression, extracted from the lift).
    bv_tree: Json,
    /// The BV expression as rendered SMT (with concrete inputs substituted).
    bv_expr_rendered: String,
    /// The complete SMT-LIB script sent to z3.
    smt_query: String,
    /// Concrete input(s) in order.
    inputs: Vec<i32>,
    /// The derived output value (signed i32, two's complement).
    derived_value: i32,
    /// z3's first-line verdict (must be "sat").
    verdict: String,
    /// z3's raw get-value response line.
    model_line: String,
    /// The solver binary used.
    solver: String,
    /// Wall-clock time in milliseconds.
    wall_clock_ms: u64,
}

pub fn run(args: ModelArgs) -> u8 {
    // ── Base64 STRONG-TIER string derive (paper 26 seam) ──────────────────
    // The payload carries the per-character block equations AND the input bytes,
    // so z3 computes the output STRING directly. Derived, not executed.
    if let Some(ref payload) = args.blocks_payload {
        return run_blocks_derive(&args, payload);
    }

    if args.inputs.is_empty() {
        eprintln!(
            "{}: --input is required (one per bv-tree var) unless using --blocks-payload",
            "error".red().bold()
        );
        return EXIT_USER_ERROR;
    }

    // Resolve the BV tree JSON. It MUST come from the lifted universe — either
    // read out of a minted .proof, or passed in by a caller that already did so.
    // There is no built-in formula.
    let (bv_tree, bv_tree_source): (Json, String) = if let Some(ref proof_path) = args.from_proof {
        match extract_bv_tree_from_proof(proof_path) {
            Ok(tree) => (
                tree,
                format!(
                    "minted .proof: {} (int32.eq-bv-expr universe atom, args[1])",
                    proof_path.display()
                ),
            ),
            Err(e) => {
                eprintln!(
                    "{}: could not extract universe bv_tree from {}: {e}",
                    "refused".red().bold(),
                    proof_path.display()
                );
                eprintln!(
                    "  the proof carries no int32.eq-bv-expr universe atom; there is nothing to derive from."
                );
                eprintln!("  (no built-in formula exists — the lift is the only source of truth.)");
                return EXIT_USER_ERROR;
            }
        }
    } else if let Some(ref json_str) = args.bv_expr {
        match serde_json::from_str(json_str) {
            Ok(v) => (
                v,
                "caller-supplied --bv-expr (extracted from lift/.proof)".to_string(),
            ),
            Err(e) => {
                eprintln!("{}: --bv-expr JSON parse error: {e}", "error".red().bold());
                return EXIT_USER_ERROR;
            }
        }
    } else {
        eprintln!(
            "{}: supply --from-proof <path> or --bv-expr <json> (extracted from a minted universe)",
            "error".red().bold()
        );
        return EXIT_USER_ERROR;
    };

    // Emit the derive query.
    let dq = match emit_derive_query(&bv_tree, &args.inputs) {
        Ok(q) => q,
        Err(e) => {
            eprintln!(
                "{}: derive query emission failed: {e}",
                "error".red().bold()
            );
            return EXIT_USER_ERROR;
        }
    };

    if !args.out.quiet {
        eprintln!("[sugar derive] bv_tree source: {bv_tree_source}");
        eprintln!("[sugar derive] SMT query:\n{}", dq.smt);
    }

    // Run z3 with model extraction.
    let result = solve_with_model(&args.z3, &dq.smt, &dq.result_var, None);

    if !result.error.is_empty() {
        eprintln!("{}: solver error: {}", "error".red().bold(), result.error);
        return EXIT_SOLVER_FAIL;
    }

    if result.timed_out {
        eprintln!("{}: z3 timed out", "error".red().bold());
        return EXIT_SOLVER_FAIL;
    }

    if result.verdict_line != "sat" {
        eprintln!(
            "{}: z3 returned {:?} (expected sat); the derive query is unsatisfiable or errored",
            "error".red().bold(),
            result.verdict_line
        );
        eprintln!("raw stdout:\n{}", result.raw_stdout);
        return EXIT_SOLVER_FAIL;
    }

    let derived = match result.derived_value {
        Some(v) => v,
        None => {
            eprintln!(
                "{}: z3 returned sat but model value could not be parsed from: {:?}",
                "error".red().bold(),
                result.raw_stdout
            );
            return EXIT_SOLVER_FAIL;
        }
    };

    // Extract the model line (second non-empty line of z3 stdout).
    let model_line = result
        .raw_stdout
        .lines()
        .map(|l| l.trim_end_matches('\r'))
        .filter(|l| !l.is_empty())
        .nth(1)
        .unwrap_or("")
        .to_string();

    let receipt = DeriveReceipt {
        bv_tree_source: bv_tree_source.clone(),
        bv_tree: bv_tree.clone(),
        bv_expr_rendered: dq.bv_expr_rendered.clone(),
        smt_query: dq.smt.clone(),
        inputs: args.inputs.clone(),
        derived_value: derived,
        verdict: result.verdict_line.clone(),
        model_line: model_line.clone(),
        solver: args.z3.clone(),
        wall_clock_ms: result.wall_clock.as_millis() as u64,
    };

    // Write receipt file if requested.
    if let Some(ref path) = args.receipt_out {
        let json_str = match serde_json::to_string_pretty(&receipt) {
            Ok(s) => s,
            Err(e) => {
                eprintln!("{}: receipt serialization: {e}", "error".red().bold());
                return EXIT_SOLVER_FAIL;
            }
        };
        if let Err(e) = std::fs::write(path, &json_str) {
            eprintln!(
                "{}: writing receipt to {:?}: {e}",
                "error".red().bold(),
                path
            );
            return EXIT_SOLVER_FAIL;
        }
    }

    if args.out.json {
        println!(
            "{}",
            serde_json::to_string_pretty(&receipt).unwrap_or_default()
        );
    } else {
        println!();
        println!("  {}", "z3.model derive result".bold());
        println!("  bv_tree from : {bv_tree_source}");
        println!(
            "  input(s)     : {}",
            args.inputs
                .iter()
                .map(|v| v.to_string())
                .collect::<Vec<_>>()
                .join(", ")
        );
        println!("  bv_expr      : {}", dq.bv_expr_rendered);
        println!("  z3 verdict   : {}", result.verdict_line.green().bold());
        println!("  z3 model     : {model_line}");
        println!("  derived value: {}", derived.to_string().green().bold());
        println!();
        println!(
            "  {} z3.model DERIVES {} from the lifted universe body — derived, not executed.",
            "PASS".green().bold(),
            derived.to_string().green().bold()
        );
        println!();
        if let Some(ref path) = args.receipt_out {
            println!("  receipt written to: {path:?}");
        }
    }

    EXIT_OK
}

/// Receipt for a strong-tier string derive.
#[derive(Debug, serde::Serialize)]
struct BlocksDeriveReceipt {
    payload_source: String,
    smt_query: String,
    derived_string: String,
    verdict: String,
    model_line: String,
    solver: String,
}

/// Run the Base64 strong-tier string derive: build the block-equation query,
/// run z3, parse the derived output string, and report it.
fn run_blocks_derive(args: &ModelArgs, payload_json: &str) -> u8 {
    // Validate the payload is JSON before handing it on (named refusal).
    if serde_json::from_str::<Json>(payload_json).is_err() {
        eprintln!(
            "{}: --blocks-payload is not valid JSON",
            "error".red().bold()
        );
        return EXIT_USER_ERROR;
    }
    let dq = match emit_blocks_derive_query(payload_json) {
        Ok(q) => q,
        Err(e) => {
            eprintln!(
                "{}: blocks derive emission failed: {e}",
                "error".red().bold()
            );
            return EXIT_USER_ERROR;
        }
    };

    if !args.out.quiet {
        eprintln!("[sugar derive] strong-tier block payload");
        eprintln!("[sugar derive] SMT query:\n{}", dq.smt);
    }

    // Run z3 directly: this query returns a String model, not an i32, so we do
    // not route through solve_with_model (which parses a bitvector).
    use std::io::Write;
    use std::process::{Command, Stdio};
    let mut child = match Command::new(&args.z3)
        .args(["-smt2", "-in"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(c) => c,
        Err(e) => {
            eprintln!(
                "{}: could not spawn z3 ({}): {e}",
                "error".red().bold(),
                args.z3
            );
            return EXIT_SOLVER_FAIL;
        }
    };
    if let Some(stdin) = child.stdin.as_mut() {
        if let Err(e) = stdin.write_all(dq.smt.as_bytes()) {
            eprintln!("{}: writing to z3 stdin: {e}", "error".red().bold());
            return EXIT_SOLVER_FAIL;
        }
    }
    let out = match child.wait_with_output() {
        Ok(o) => o,
        Err(e) => {
            eprintln!("{}: z3 wait failed: {e}", "error".red().bold());
            return EXIT_SOLVER_FAIL;
        }
    };
    let stdout = String::from_utf8_lossy(&out.stdout);
    let lines: Vec<&str> = stdout
        .lines()
        .map(|l| l.trim_end_matches('\r').trim())
        .filter(|l| !l.is_empty())
        .collect();

    let verdict = lines.first().copied().unwrap_or("").to_string();
    if verdict != "sat" {
        eprintln!(
            "{}: z3 returned {:?} (expected sat) for the block-equation derive",
            "error".red().bold(),
            verdict
        );
        eprintln!("raw stdout:\n{stdout}");
        return EXIT_SOLVER_FAIL;
    }
    let model_line = lines.get(1).copied().unwrap_or("").to_string();
    let derived = match parse_model_string(&model_line, &dq.result_var) {
        Some(s) => s,
        None => {
            eprintln!(
                "{}: z3 returned sat but the derived string could not be parsed from: {:?}",
                "error".red().bold(),
                model_line
            );
            return EXIT_SOLVER_FAIL;
        }
    };

    let receipt = BlocksDeriveReceipt {
        payload_source: "caller-supplied --blocks-payload (extracted from lift/.proof)".to_string(),
        smt_query: dq.smt.clone(),
        derived_string: derived.clone(),
        verdict: verdict.clone(),
        model_line: model_line.clone(),
        solver: args.z3.clone(),
    };

    if let Some(ref path) = args.receipt_out {
        match serde_json::to_string_pretty(&receipt) {
            Ok(s) => {
                if let Err(e) = std::fs::write(path, &s) {
                    eprintln!(
                        "{}: writing receipt to {:?}: {e}",
                        "error".red().bold(),
                        path
                    );
                    return EXIT_SOLVER_FAIL;
                }
            }
            Err(e) => {
                eprintln!("{}: receipt serialization: {e}", "error".red().bold());
                return EXIT_SOLVER_FAIL;
            }
        }
    }

    if args.out.json {
        println!(
            "{}",
            serde_json::to_string_pretty(&receipt).unwrap_or_default()
        );
    } else {
        println!();
        println!("  {}", "z3.model strong-tier string derive".bold());
        println!("  z3 verdict     : {}", verdict.green().bold());
        println!("  z3 model       : {model_line}");
        println!(
            "  derived string : {}",
            format!("\"{derived}\"").green().bold()
        );
        println!();
        println!(
            "  {} z3.model DERIVES {} from the walked block equations — derived, not executed.",
            "PASS".green().bold(),
            format!("\"{derived}\"").green().bold()
        );
        println!();
        if let Some(ref path) = args.receipt_out {
            println!("  receipt written to: {path:?}");
        }
    }

    EXIT_OK
}

/// Read a minted .proof catalog and extract the bv_tree (args[1]) of the first
/// `int32.eq-bv-expr` universe atom found in any member.
///
/// Returns an error (REFUSE) if the proof carries no such atom — there is no
/// built-in fallback. This is the no-vendor-axiom guard: the bv_tree is only
/// ever the lifted universe expression.
fn extract_bv_tree_from_proof(path: &PathBuf) -> Result<Json, String> {
    let bytes = std::fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let graph =
        ProofGraph::read(&bytes).map_err(|e| format!("CBOR decode {}: {e}", path.display()))?;

    // Collect EVERY int32.eq-bv-expr universe bv_tree across all members. We
    // never first-match: ambiguity must refuse. Note one universe is often
    // lifted at several call-sites (e.g. abs(5), abs(-5), abs(MIN)) — those
    // carry the SAME bv_tree (only the call-site subject differs). The choice
    // that matters is the DISTINCT universe DEFINITION. So we dedup by structure
    // and require exactly one distinct bv_tree.
    let mut trees: Vec<Json> = Vec::new();
    for view in graph.members_view() {
        let parsed: Json = match serde_json::from_slice(view.bytes()) {
            Ok(v) => v,
            Err(_) => continue,
        };
        collect_universe_bv_trees(&parsed, &mut trees);
    }

    // Dedup by canonical (sorted-key) JSON: same definition tree -> one entry.
    let mut distinct: Vec<Json> = Vec::new();
    for t in trees {
        let key = canonical_json(&t);
        if !distinct.iter().any(|d| canonical_json(d) == key) {
            distinct.push(t);
        }
    }

    match distinct.len() {
        0 => Err("no int32.eq-bv-expr universe atom in any catalog member".to_string()),
        1 => Ok(distinct.into_iter().next().unwrap()),
        n => Err(format!(
            "ambiguous: {n} distinct int32.eq-bv-expr universe definitions in proof, \
             cannot choose; refusing rather than pick arbitrarily"
        )),
    }
}

/// Canonical (deterministic, sorted-key) JSON string for structural comparison.
fn canonical_json(v: &Json) -> String {
    match v {
        Json::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let parts: Vec<String> = keys
                .iter()
                .map(|k| format!("{:?}:{}", k, canonical_json(&map[*k])))
                .collect();
            format!("{{{}}}", parts.join(","))
        }
        Json::Array(arr) => {
            let parts: Vec<String> = arr.iter().map(canonical_json).collect();
            format!("[{}]", parts.join(","))
        }
        other => other.to_string(),
    }
}

/// Recursively collect the `args[1]` (bv_tree) of EVERY `int32.eq-bv-expr` atom
/// reachable from `node`, appending each to `out`. The atom shape (per the lift)
/// is `{"kind":"atomic","name":"int32.eq-bv-expr","args":[<subject>, <bv_tree>]}`.
fn collect_universe_bv_trees(node: &Json, out: &mut Vec<Json>) {
    match node {
        Json::Object(obj) => {
            if obj.get("name").and_then(|n| n.as_str()) == Some("int32.eq-bv-expr") {
                if let Some(args) = obj.get("args").and_then(|a| a.as_array()) {
                    if args.len() == 2 {
                        out.push(args[1].clone());
                    }
                }
            }
            for (_k, v) in obj {
                collect_universe_bv_trees(v, out);
            }
        }
        Json::Array(arr) => {
            for v in arr {
                collect_universe_bv_trees(v, out);
            }
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Build a member-body-shaped node carrying an int32.eq-bv-expr atom whose
    // subject is call:abs(<subj_val>) and whose bv_tree is the given ite.
    fn member_with_universe(subj_val: i64, bv_tree: Json) -> Json {
        serde_json::json!({
            "header": {
                "inv": {
                    "kind": "and",
                    "operands": [
                        {"kind": "atomic", "name": "=", "args": []},
                        {
                            "kind": "atomic",
                            "name": "int32.eq-bv-expr",
                            "args": [
                                {"kind": "ctor", "name": "call:abs", "args": [
                                    {"kind": "const", "value": subj_val}
                                ]},
                                bv_tree
                            ]
                        }
                    ]
                }
            }
        })
    }

    fn abs_tree() -> Json {
        serde_json::json!({"kind": "ctor", "name": "bv32.ite", "args": [
            {"kind": "ctor", "name": "bv32.slt", "args": [
                {"kind": "var", "name": "a"}, {"kind": "const", "value": 0}]},
            {"kind": "ctor", "name": "bv32.neg", "args": [{"kind": "var", "name": "a"}]},
            {"kind": "var", "name": "a"}
        ]})
    }

    #[test]
    fn collect_universe_bv_trees_pulls_args1() {
        let body = member_with_universe(-5, abs_tree());
        let mut out = Vec::new();
        collect_universe_bv_trees(&body, &mut out);
        assert_eq!(out.len(), 1, "should collect exactly one bv_tree");
        assert_eq!(
            out[0]["name"], "bv32.ite",
            "must collect args[1] (the bv_tree)"
        );
    }

    #[test]
    fn collect_universe_bv_trees_absent_yields_empty() {
        let body = serde_json::json!({
            "header": {"inv": {"kind": "atomic", "name": "=", "args": []}}
        });
        let mut out = Vec::new();
        collect_universe_bv_trees(&body, &mut out);
        assert!(
            out.is_empty(),
            "no universe atom -> empty (the refuse path)"
        );
    }

    #[test]
    fn same_universe_at_multiple_callsites_dedups_to_one() {
        // Three atoms, SAME bv_tree, different subject literals (the real abs
        // proof shape). Canonical dedup must collapse them to one distinct tree.
        let trees = vec![abs_tree(), abs_tree(), abs_tree()];
        let mut distinct: Vec<Json> = Vec::new();
        for t in trees {
            let key = canonical_json(&t);
            if !distinct.iter().any(|d| canonical_json(d) == key) {
                distinct.push(t);
            }
        }
        assert_eq!(
            distinct.len(),
            1,
            "same definition at N call-sites = one distinct tree"
        );
    }

    #[test]
    fn two_distinct_universes_are_not_deduped() {
        // Two genuinely different definitions must remain distinct (=> refuse).
        let abs = abs_tree();
        let neg_only = serde_json::json!({"kind": "ctor", "name": "bv32.neg",
            "args": [{"kind": "var", "name": "a"}]});
        let mut distinct: Vec<Json> = Vec::new();
        for t in [abs, neg_only] {
            let key = canonical_json(&t);
            if !distinct.iter().any(|d| canonical_json(d) == key) {
                distinct.push(t);
            }
        }
        assert_eq!(
            distinct.len(),
            2,
            "two different definitions stay distinct -> ambiguous"
        );
    }

    #[test]
    fn extract_refuses_on_ambiguous_proof() {
        // A real CBOR catalog carrying TWO members with DIFFERENT universe
        // definitions must refuse, not first-match. We build the catalog with
        // the same encoder the minter uses so extract_bv_tree_from_proof reads it.
        let body_abs = member_with_universe(-5, abs_tree());
        let body_neg = member_with_universe(
            -5,
            serde_json::json!(
            {"kind": "ctor", "name": "bv32.neg", "args": [{"kind": "var", "name": "a"}]}),
        );
        let proof_bytes = encode_two_member_catalog(&body_abs, &body_neg);
        let dir = std::env::temp_dir();
        let path = dir.join(format!(
            "sugar-derive-ambiguous-{}.proof",
            std::process::id()
        ));
        std::fs::write(&path, &proof_bytes).expect("write tmp proof");
        let r = extract_bv_tree_from_proof(&path);
        let _ = std::fs::remove_file(&path);
        let err = r.expect_err("ambiguous proof must refuse");
        assert!(
            err.contains("ambiguous") && err.contains("2 distinct"),
            "refusal must name the ambiguity, got: {err}"
        );
    }

    // Encode a minimal CBOR catalog with two members, mirroring the on-disk
    // shape that `decode` expects: a map with a `members` map of CID -> bstr
    // (the JCS-JSON member body bytes).
    fn encode_two_member_catalog(m1: &Json, m2: &Json) -> Vec<u8> {
        use sugar_canonicalizer::blake3_512_of;
        let b1 = serde_json::to_vec(m1).unwrap();
        let b2 = serde_json::to_vec(m2).unwrap();
        let c1 = blake3_512_of(&b1);
        let c2 = blake3_512_of(&b2);
        // Hand-roll deterministic CBOR: { "members": { c1: b1, c2: b2 } }.
        let mut out = Vec::new();
        // map(1)
        out.push(0xA1);
        cbor_tstr(&mut out, "members");
        // map(2)
        out.push(0xA2);
        cbor_tstr(&mut out, &c1);
        cbor_bstr(&mut out, &b1);
        cbor_tstr(&mut out, &c2);
        cbor_bstr(&mut out, &b2);
        out
    }

    fn cbor_len_header(out: &mut Vec<u8>, major: u8, len: usize) {
        let m = major << 5;
        if len < 24 {
            out.push(m | (len as u8));
        } else if len < 256 {
            out.push(m | 24);
            out.push(len as u8);
        } else if len < 65536 {
            out.push(m | 25);
            out.push((len >> 8) as u8);
            out.push((len & 0xff) as u8);
        } else {
            out.push(m | 26);
            out.push((len >> 24) as u8);
            out.push((len >> 16) as u8);
            out.push((len >> 8) as u8);
            out.push((len & 0xff) as u8);
        }
    }

    fn cbor_tstr(out: &mut Vec<u8>, s: &str) {
        cbor_len_header(out, 3, s.len());
        out.extend_from_slice(s.as_bytes());
    }

    fn cbor_bstr(out: &mut Vec<u8>, b: &[u8]) {
        cbor_len_header(out, 2, b.len());
        out.extend_from_slice(b);
    }

    #[test]
    fn extracted_abs_tree_drives_a_derive_query() {
        // The bv_tree as it appears under args[1] in a minted proof (note the
        // `sort` field on const nodes — we read `value`, ignoring `sort`).
        let bv_tree = serde_json::json!({
            "kind": "ctor",
            "name": "bv32.ite",
            "args": [
                {"kind": "ctor", "name": "bv32.slt", "args": [
                    {"kind": "var", "name": "a"},
                    {"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": 0}
                ]},
                {"kind": "ctor", "name": "bv32.neg", "args": [{"kind": "var", "name": "a"}]},
                {"kind": "var", "name": "a"}
            ]
        });
        let dq = emit_derive_query(&bv_tree, &[i32::MIN]).expect("emit");
        let rv = &dq.result_var;
        assert!(dq.smt.contains(&format!("(get-value ({rv}))")));
        assert!(dq.smt.contains("(assert (= a #x80000000))"));
        assert!(dq.smt.contains(&format!(
            "(assert (= {rv} (ite (bvslt a #x00000000) (bvneg a) a)))"
        )));
    }
}
