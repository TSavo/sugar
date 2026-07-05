// SPDX-License-Identifier: MIT OR Apache-2.0
//
// sugar-lift-rust-cargo-test-witness
//
// The cargo-test WITNESS lifter -- the proofchain-native correctness producer
// for Rust, at parity with the python pytest-witness kit.
//
// Instead of lifting a test's assertions into a symbolic consistency claim, this
// RUNS the tests: `cargo test` is the deterministic transform `k`, the code-
// under-test is `I`, the observed per-test pass/fail is `t`. The run is content-
// addressed into a witness PACKAGE with the substrate's own CID machinery
// (`blake3_512_of` over JCS).
//
// THE WITNESS-PACKAGE MODEL: one witness-package per test suite. Run the
// project's tests, capture EACH test's pass/fail, content-address each test's
// canonical body, concatenate (sorted, JSONL-with-trailing-newline) into ONE
// bundle whose cid = blake3_512(bundle bytes). The `.proof` carries ONE
// WitnessPackageMemento (a 64-byte pointer + signature over the bundle cid) plus
// ONE contract whose custom evidence pins the bundle cid.
//
// DISCHARGE has two faces, mirroring python:
//   - `verify --project` (rust witness axis): the verifier asks this kit (over
//     `sugar.plugin.resolve_witness`) to RESOLVE the bundle body; the kit
//     re-runs the suite, rebuilds the bundle, returns the bytes; the rust
//     verifier blake3's them and compares to the pinned witness_cid. The kit
//     oracle is UNTRUSTED -- it returns CONTENT, never a verdict.
//   - `prove` (custom-evidence axis): the contract carries a `custom`
//     EvidenceTerm with tool="cargo-test"; prove spawns this kit's
//     `discharge_command` (the `discharge_cli` bin), which re-runs the suite,
//     rebuilds the bundle, confirms the pinned cid reproduces AND every per-test
//     witness passed (`discharge_bundle`) -- DISCHARGED iff so, else REFUSED.
//
// Teeth: a failing test in the suite mints a `failed` witness body, so the
// bundle still reproduces (the run was honest) but `discharge_bundle` REFUSES on
// the all-passed check. You cannot witness a suite right that runs wrong.

use std::path::Path;
use std::process::Command;

use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};
use sugar_ir_symbolic::{
    atomic_, serialize::marshal_declarations, ContractDecl, EvidenceCertificate, EvidenceTerm,
};
use sugar_proof_envelope::{
    ed25519_pubkey_string, ed25519_sign_string, proof_filename, Ed25519Seed,
};

/// The DEV witness-signing seed (python `WITNESS_SIGNER_SEED` = `bytes([0x77])*32`).
/// A witness is OUR signed mark; in PRODUCTION the seed MUST come from the
/// prover's provenance key, via the env override below. This globally-known
/// default is an INTEGRITY TAG ONLY (it proves the body was not altered, not WHO
/// signed it) and is here so mementos are reproducible in tests. Set
/// `SUGAR_WITNESS_SIGNER_SEED` (64 hex chars) for an authoritative key.
pub const WITNESS_SIGNER_SEED: Ed25519Seed = [0x77u8; 32];
const SIGNER_SEED_ENV: &str = "SUGAR_WITNESS_SIGNER_SEED";

/// Explicit override wins; else the env-provided authoritative seed; else the
/// well-known dev seed (integrity tag only). Mirrors python `_resolve_signer_seed`.
fn resolve_signer_seed(seed: Option<Ed25519Seed>) -> Result<Ed25519Seed, String> {
    if let Some(s) = seed {
        return Ok(s);
    }
    if let Ok(env) = std::env::var(SIGNER_SEED_ENV) {
        let env = env.trim();
        if !env.is_empty() {
            let raw = decode_hex(env)?;
            if raw.len() != 32 {
                return Err(format!(
                    "{SIGNER_SEED_ENV} must be 64 hex chars (32 bytes); got {}",
                    raw.len()
                ));
            }
            let mut out = [0u8; 32];
            out.copy_from_slice(&raw);
            return Ok(out);
        }
    }
    Ok(WITNESS_SIGNER_SEED)
}

fn decode_hex(s: &str) -> Result<Vec<u8>, String> {
    if s.len() % 2 != 0 {
        return Err("odd-length hex".to_string());
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).map_err(|e| e.to_string()))
        .collect()
}

// ---------------------------------------------------------------------------
// Code + runtime content-addressing (mirror python `code_cid` / `runtime_cid`).
// ---------------------------------------------------------------------------

/// Content-address the code under test by PROJECT-RELATIVE path + content, so the
/// same witness re-runs from any checkout of the same project. Mirrors python
/// `code_cid`: `blake3_512(join_b"\0"( rel_utf8 + b"\0" + bytes ))` over the
/// sorted code files. A PRESENT-but-EMPTY `code_files` (the code under test is
/// the installed crate, not a tracked file) hashes the empty join -- still
/// deterministic, still reconstructible.
pub fn code_cid(project_dir: &Path, code_files: &[String]) -> Result<String, String> {
    let mut sorted: Vec<String> = code_files.to_vec();
    sorted.sort();
    let mut parts: Vec<Vec<u8>> = Vec::new();
    for rel in &sorted {
        let bytes = std::fs::read(project_dir.join(rel))
            .map_err(|e| format!("read code file {rel}: {e}"))?;
        let mut part = rel.as_bytes().to_vec();
        part.push(0u8);
        part.extend_from_slice(&bytes);
        parts.push(part);
    }
    let joined = join_with_nul(&parts);
    Ok(blake3_512_of(&joined))
}

fn join_with_nul(parts: &[Vec<u8>]) -> Vec<u8> {
    let mut out = Vec::new();
    for (i, p) in parts.iter().enumerate() {
        if i > 0 {
            out.push(0u8);
        }
        out.extend_from_slice(p);
    }
    out
}

/// Pin the runtime that makes the run reproducible. Mirrors python `runtime_cid`
/// intent (a runtime pin): a stable string identifying the rust toolchain, hashed.
/// `rustc --version` output is stable per toolchain; deterministic per machine/run.
pub fn runtime_cid() -> String {
    let ver = Command::new("rustc")
        .arg("--version")
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .unwrap_or_else(|| "rustc-unknown".to_string());
    let desc = format!("rustc={ver};target={}", std::env::consts::ARCH);
    blake3_512_of(desc.as_bytes())
}

// ---------------------------------------------------------------------------
// The witness body (mirror python `_witness_value` + `witness_body`).
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Witness {
    pub code_cid: String,
    pub runtime_cid: String,
    pub test_id: String,
    pub outcome: String,         // "passed" | "failed"
    pub code_files: Vec<String>, // project-relative, sorted
    pub cid: String,
}

/// The canonical per-test body VALUE. JCS sorts keys, so code order is
/// irrelevant, but we include exactly these keys (mirror python `_witness_value`,
/// with `kind="cargo-test-witness"`):
///   kind, codeCid, codeFiles, outcome, runtimeCid, test
fn witness_value(
    code: &str,
    runtime: &str,
    test_id: &str,
    outcome: &str,
    code_files: &[String],
) -> std::sync::Arc<CValue> {
    let mut files: Vec<String> = code_files.to_vec();
    files.sort();
    CValue::object([
        ("kind", CValue::string("cargo-test-witness")),
        ("codeCid", CValue::string(code.to_string())),
        ("codeFiles", CValue::string(files.join(","))),
        ("outcome", CValue::string(outcome.to_string())),
        ("runtimeCid", CValue::string(runtime.to_string())),
        ("test", CValue::string(test_id.to_string())),
    ])
}

/// The bytes the witness CID addresses: the canonical run record. By construction
/// `blake3_512_of(witness_body(w)) == w.cid`.
pub fn witness_body(w: &Witness) -> Vec<u8> {
    encode_jcs(&witness_value(
        &w.code_cid,
        &w.runtime_cid,
        &w.test_id,
        &w.outcome,
        &w.code_files,
    ))
    .into_bytes()
}

fn make_witness(
    code: &str,
    runtime: &str,
    test_id: &str,
    outcome: &str,
    code_files: &[String],
) -> Witness {
    let mut files: Vec<String> = code_files.to_vec();
    files.sort();
    let body = encode_jcs(&witness_value(code, runtime, test_id, outcome, &files));
    let cid = blake3_512_of(body.as_bytes());
    Witness {
        code_cid: code.to_string(),
        runtime_cid: runtime.to_string(),
        test_id: test_id.to_string(),
        outcome: outcome.to_string(),
        code_files: files,
        cid,
    }
}

// ---------------------------------------------------------------------------
// The cargo-test RUNNER + libtest text parser (the rust analog of
// run_file_witnesses). Run `cargo test` ONCE, capture stdout, parse the stable
// libtest lines.
// ---------------------------------------------------------------------------

/// A parsed (test_id, raw_outcome) from a libtest result line.
/// raw_outcome is one of "ok" | "failed" | "ignored".
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParsedTest {
    pub test_id: String,
    pub raw: String,
}

/// Parse the stable libtest text lines from a `cargo test` stdout capture:
///   `test <path> ... ok`
///   `test <path> ... FAILED`
///   `test <path> ... ignored`
/// A skip (ignored) is neither a discharge nor a refusal -- it is DROPPED here
/// (the caller never sees it), mirroring python's skip handling.
pub fn parse_cargo_test_output(stdout: &str) -> Vec<ParsedTest> {
    let mut out = Vec::new();
    for line in stdout.lines() {
        let line = line.trim_end();
        // libtest result lines: `test <path> ... <verdict>`. The doc-test runner
        // also emits `test <file> - <item> (line N) ... ok`; we accept any
        // `test ` prefix with the ` ... ` separator, keying on the path token.
        let Some(rest) = line.strip_prefix("test ") else {
            continue;
        };
        let Some(idx) = rest.rfind(" ... ") else {
            continue;
        };
        let path = rest[..idx].trim();
        let verdict = rest[idx + 5..].trim();
        // The verdict can carry a trailing benchmark/timing note (e.g.
        // `ok` or `FAILED`); take the first whitespace token.
        let verdict = verdict.split_whitespace().next().unwrap_or("");
        let raw = match verdict {
            "ok" => "ok",
            "FAILED" => "failed",
            "ignored" => "ignored",
            // Lines like the trailing `test result: ok. N passed; ...` summary do
            // NOT match the `... ` separator structure for a path, so they are
            // already excluded. Anything else is not a per-test line.
            _ => continue,
        };
        if path.is_empty() {
            continue;
        }
        out.push(ParsedTest {
            test_id: path.to_string(),
            raw: raw.to_string(),
        });
    }
    out
}

/// Translate parsed libtest results into per-test witnesses. ignored -> dropped.
/// ok -> "passed"; failed -> "failed".
fn witnesses_from_parsed(
    parsed: &[ParsedTest],
    cc: &str,
    rc: &str,
    code_files: &[String],
) -> Vec<Witness> {
    let mut out = Vec::new();
    for p in parsed {
        if p.raw == "ignored" {
            continue; // a skip is neither a discharge nor a refusal
        }
        let outcome = if p.raw == "ok" { "passed" } else { "failed" };
        out.push(make_witness(cc, rc, &p.test_id, outcome, code_files));
    }
    out
}

/// Run the project's tests ONCE and content-address EACH test as its own witness.
/// `--no-fail-fast` so a failing test does not suppress later test binaries (which
/// would change the test SET and break bundle reproduction). stdout is parsed for
/// outcomes even when the overall exit code is nonzero (a failing test makes
/// `cargo test` exit nonzero, but the run was still honest).
pub fn run_suite_witnesses(
    project_dir: &Path,
    code_files: &[String],
) -> Result<Vec<Witness>, String> {
    let cc = code_cid(project_dir, code_files)?;
    let rc = runtime_cid();
    let output = Command::new("cargo")
        .args(["test", "--no-fail-fast", "--", "--test-threads=1"])
        .current_dir(project_dir)
        .output()
        .map_err(|e| format!("spawn `cargo test`: {e}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    let parsed = parse_cargo_test_output(&stdout);
    Ok(witnesses_from_parsed(&parsed, &cc, &rc, code_files))
}

// ---------------------------------------------------------------------------
// The suite BUNDLE (mirror python `build_suite_bundle`): sort witnesses by test
// id; bundle_bytes = concat(witness_body(w) + b"\n"); bundle_cid = blake3(bytes).
// ---------------------------------------------------------------------------

/// Assemble ONE content-addressed bundle from a set of witnesses. Deterministic:
/// witnesses are sorted by test id so the bytes -- and the cid -- are reproducible.
pub fn build_bundle(witnesses: &[Witness]) -> (Vec<u8>, String, Vec<Witness>) {
    let mut ws: Vec<Witness> = witnesses.to_vec();
    ws.sort_by(|a, b| a.test_id.cmp(&b.test_id));
    let mut buf = Vec::new();
    for w in &ws {
        buf.extend_from_slice(&witness_body(w));
        buf.push(b'\n');
    }
    let cid = blake3_512_of(&buf);
    (buf, cid, ws)
}

/// Run EVERY test in the project and assemble ONE content-addressed bundle.
/// Returns (bundle_bytes, bundle_cid, witnesses).
pub fn build_suite_bundle(
    project_dir: &Path,
    code_files: &[String],
) -> Result<(Vec<u8>, String, Vec<Witness>), String> {
    let witnesses = run_suite_witnesses(project_dir, code_files)?;
    Ok(build_bundle(&witnesses))
}

// ---------------------------------------------------------------------------
// The signed WitnessPackageMemento (mirror python `witness_package_memento`).
// ---------------------------------------------------------------------------

/// The ONE memento the `.proof` carries for a WHOLE SUITE. mint reads `witness_cid`
/// / `witness_kind` / `signer` / `signature` (snake_case) via `required_str`; the
/// verifier reads `body.witness_cid` / `body.signature` / `body.outcome` (absent
/// here -> proceeds to recompute). Returned as a `serde_json::Value` so it slots
/// straight into the lift's `ir` / `witness_mementos` arrays.
pub fn witness_package_memento(
    bundle_cid: &str,
    test_files: &[String],
    code_files: &[String],
    count: usize,
    passed: usize,
    seed: Option<Ed25519Seed>,
) -> Result<serde_json::Value, String> {
    let seed = resolve_signer_seed(seed)?;
    let signer = ed25519_pubkey_string(&seed);
    let signature = ed25519_sign_string(&seed, bundle_cid.as_bytes());
    let mut tfs: Vec<String> = test_files.to_vec();
    tfs.sort();
    let mut cfs: Vec<String> = code_files.to_vec();
    cfs.sort();
    Ok(serde_json::json!({
        "kind": "witness-memento",
        "witness_cid": bundle_cid,
        "witness_kind": "cargo-test-witness-package",
        "signer": signer,
        "signature": signature,
        "test_files": tfs,
        "code_files": cfs,
        "count": count,
        "passed": passed,
    }))
}

// ---------------------------------------------------------------------------
// The lift contract (mirror python `handle_lift`): one ContractDecl named
// "witness-package:<bundle_cid>", invariant atomic("witnessed", []), custom
// evidence pinning the bundle cid.
// ---------------------------------------------------------------------------

/// The `proofData` JSON the certificate carries: compact, sorted keys, mirroring
/// python's `json.dumps(..., sort_keys=True, separators=(",", ":"))`.
pub fn witness_package_proof_data(
    bundle_cid: &str,
    test_files: &[String],
    code_files: &[String],
    count: usize,
    passed: usize,
) -> String {
    let mut tfs: Vec<String> = test_files.to_vec();
    tfs.sort();
    let mut cfs: Vec<String> = code_files.to_vec();
    cfs.sort();
    // serde_json with sorted keys: build a BTreeMap-shaped Value. serde_json
    // String/Number encode compactly; we request the substrate-standard compact
    // separators by serializing a Value with no whitespace (serde_json default).
    let v = serde_json::json!({
        "kind": "witness-package",
        "packageCid": bundle_cid,
        "testFiles": tfs,
        "codeFiles": cfs,
        "count": count,
        "passed": passed,
    });
    // serde_json::to_string sorts object keys only if the map is sorted; json!
    // preserves insertion order. To match python's sort_keys=True, round-trip
    // through a canonical key-sorted serialization.
    sorted_compact_json(&v)
}

fn witness_package_proofir_provenance(bundle_cid: &str, runtime: &str) -> serde_json::Value {
    serde_json::json!({
        "kind": "proofir-provenance",
        "nodeClass": "WitnessPackage",
        "constructionSite": {
            "tool": "cargo-test",
            "runtimeCid": runtime,
        },
        "warrants": [
            {
                "kind": "Derived",
                "floorChain": ["cargo-test-witness-package", "package-recompute"],
                "packageCid": bundle_cid,
            }
        ],
    })
}

/// Serialize a `serde_json::Value` with object keys sorted recursively and no
/// extra whitespace (separators `,`/`:`), matching python `sort_keys=True,
/// separators=(",", ":")`.
fn sorted_compact_json(v: &serde_json::Value) -> String {
    match v {
        serde_json::Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let mut s = String::from("{");
            for (i, k) in keys.iter().enumerate() {
                if i > 0 {
                    s.push(',');
                }
                s.push_str(&serde_json::to_string(k).unwrap());
                s.push(':');
                s.push_str(&sorted_compact_json(&map[*k]));
            }
            s.push('}');
            s
        }
        serde_json::Value::Array(items) => {
            let mut s = String::from("[");
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    s.push(',');
                }
                s.push_str(&sorted_compact_json(item));
            }
            s.push(']');
            s
        }
        other => serde_json::to_string(other).unwrap(),
    }
}

/// Build the contract IR member (the `{"kind":"contract",...}` JSON the lift's
/// `ir` array carries) for a witness package. Mirrors python's ContractDecl +
/// EvidenceCertificate(tool="cargo-test", version=runtime_cid, formula_hash=
/// bundle_cid, proof_data=<sorted compact json>).
pub fn witness_package_contract_ir(
    bundle_cid: &str,
    runtime: &str,
    test_files: &[String],
    code_files: &[String],
    count: usize,
    passed: usize,
) -> serde_json::Value {
    let proof_data = witness_package_proof_data(bundle_cid, test_files, code_files, count, passed);
    let cert = EvidenceCertificate {
        tool: "cargo-test".to_string(),
        version: runtime.to_string(),
        formula_hash: bundle_cid.to_string(),
        proof_data,
    };
    let ev = EvidenceTerm {
        proof_type: "custom".to_string(),
        certificate: cert,
    };
    let decl = ContractDecl {
        name: format!("witness-package:{bundle_cid}"),
        pre: None,
        post: None,
        inv: Some(atomic_("witnessed", vec![])),
        out_binding: "out".to_string(),
        evidence: Some(ev),
        panic_loci: Vec::new(),
        concept_hint: None,
    };
    // marshal_declarations emits a JSON array; the single contract is element 0.
    let arr: serde_json::Value =
        serde_json::from_str(&marshal_declarations(&[decl])).expect("contract marshals to JSON");
    let mut member = arr
        .as_array()
        .and_then(|a| a.first())
        .cloned()
        .expect("one contract member");
    member
        .as_object_mut()
        .expect("contract member is an object")
        .insert(
            "proofirProvenance".to_string(),
            witness_package_proofir_provenance(bundle_cid, runtime),
        );
    member
}

// ---------------------------------------------------------------------------
// The package on disk: `.sugar/witnesses/<cid-with-colon-as-underscore>.witness`
// holding the EXACT bundle bytes (mirror python; never fail the lift on write).
// ---------------------------------------------------------------------------

/// CID -> on-disk filename (`:` -> `_`, the convention `.proof` files use).
pub fn cid_filename(cid: &str, ext: &str) -> String {
    let proof_name = proof_filename(cid);
    let stem = proof_name
        .strip_suffix(".proof")
        .expect("proof_filename emits .proof suffix");
    format!("{stem}{ext}")
}

/// Write the bundle to `.sugar/witnesses/<cid>.witness`. Returns the path on
/// success; an I/O error is returned to the caller, which mirrors python by
/// IGNORING it at lift time (the package is audit material, never fail the lift).
pub fn write_bundle_package(
    project_dir: &Path,
    bundle_cid: &str,
    bundle_bytes: &[u8],
) -> Result<std::path::PathBuf, String> {
    let dir = project_dir.join(".sugar").join("witnesses");
    std::fs::create_dir_all(&dir).map_err(|e| format!("mkdir witnesses: {e}"))?;
    let path = dir.join(cid_filename(bundle_cid, ".witness"));
    std::fs::write(&path, bundle_bytes).map_err(|e| format!("write witness package: {e}"))?;
    Ok(path)
}

// ---------------------------------------------------------------------------
// Discharge (mirror python `discharge_bundle`): re-run the suite, rebuild the
// bundle, confirm the pinned cid reproduces AND every per-test witness passed.
// ---------------------------------------------------------------------------

/// (verdict, reason) where verdict is "DISCHARGED" | "REFUSED".
pub fn discharge_bundle(
    bundle_cid: &str,
    code_files: &[String],
    project_dir: &Path,
) -> (String, String) {
    let (_, cid, witnesses) = match build_suite_bundle(project_dir, code_files) {
        Ok(t) => t,
        Err(e) => return ("REFUSED".to_string(), format!("discharge error: {e}")),
    };
    let n = witnesses.len();
    if cid != bundle_cid {
        return (
            "REFUSED".to_string(),
            format!(
                "suite did not reproduce the pinned bundle: recomputed {}... != pinned {}... ({n} tests re-run)",
                short(&cid),
                short(bundle_cid)
            ),
        );
    }
    let failed: Vec<&str> = witnesses
        .iter()
        .filter(|w| w.outcome != "passed")
        .map(|w| w.test_id.as_str())
        .collect();
    if !failed.is_empty() {
        let shown: Vec<&str> = failed.iter().take(6).copied().collect();
        let more = if failed.len() > 6 {
            format!(" (+{} more)", failed.len() - 6)
        } else {
            String::new()
        };
        return (
            "REFUSED".to_string(),
            format!(
                "bundle reproduced but {}/{n} tests failed: {}{more}",
                failed.len(),
                shown.join(", ")
            ),
        );
    }
    (
        "DISCHARGED".to_string(),
        format!("suite re-ran; all {n} per-test witnesses reproduced and passed"),
    )
}

fn short(cid: &str) -> String {
    cid.chars().take(28).collect()
}

// ---------------------------------------------------------------------------
// resolve_witness recompute (mirror python `handle_resolve_witness` recompute
// arm): re-run the suite, rebuild the bundle, ERROR if recomputed cid != pinned,
// else return the bundle bytes.
// ---------------------------------------------------------------------------

/// Recompute the bundle body for a `cargo-test-witness-package` memento. Returns
/// the bundle bytes if the recomputed cid matches `pinned_cid`, else an error.
pub fn recompute_bundle_body(
    project_dir: &Path,
    code_files: &[String],
    pinned_cid: &str,
) -> Result<Vec<u8>, String> {
    let (buf, rcid, _) = build_suite_bundle(project_dir, code_files)?;
    if rcid != pinned_cid {
        return Err(format!(
            "witness package did not reproduce: recomputed {rcid}, pinned {pinned_cid}"
        ));
    }
    Ok(buf)
}

/// Base64-encode bytes for the resolve_witness `body_b64` reply.
pub fn b64(bytes: &[u8]) -> String {
    B64.encode(bytes)
}

// ---------------------------------------------------------------------------
// PER-TEST recompute (mirror python `run_and_witness` + the per-test recompute
// arm of `handle_resolve_witness`). The suite path is whole-suite; this is the
// rust analog of pytest-witness's single-test re-run. A per-test cid here equals
// the same test's line inside the suite bundle BY CONSTRUCTION: the body is a
// pure function of (code_cid, runtime_cid, test_id, outcome, code_files), and
// `--exact` emits a libtest path token byte-identical to the suite run's (the
// `make_witness` constructor + `parse_cargo_test_output` parser are shared).
// ---------------------------------------------------------------------------

/// Re-run EXACTLY ONE test (`cargo test <test_id> -- --exact`) and content-address
/// it as its own Witness. Mirrors python `run_and_witness` for a single node id:
///   - `code_cid` is recomputed from `code_files` (binding to the pinned code),
///   - `runtime_cid()` pins the toolchain,
///   - the outcome is read from the libtest line via the SHARED parser,
///   - the Witness is built via the SHARED `make_witness`, so its cid equals the
///     same test's bundle line.
/// stdout is parsed regardless of exit code (a failing single test exits nonzero,
/// but the line is still on stdout -- mirror `run_suite_witnesses`). If the test
/// is GONE (no matching parsed line: removed/renamed/ambiguous), a `failed`
/// witness is returned (python `run_and_witness` parity) so the verifier REFUSES
/// rather than inventing a pass. NOTE: if `test_id` resolves in two binaries,
/// `--exact` runs both and the FIRST parsed match wins -- a pre-existing
/// ambiguity in the suite model the showcase fixtures do not hit.
pub fn run_one_test_witness(
    project_dir: &Path,
    test_id: &str,
    code_files: &[String],
) -> Result<Witness, String> {
    let cc = code_cid(project_dir, code_files)?;
    let rc = runtime_cid();
    let output = Command::new("cargo")
        .args(["test", test_id, "--", "--exact"])
        .current_dir(project_dir)
        .output()
        .map_err(|e| format!("spawn `cargo test {test_id} -- --exact`: {e}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    let parsed = parse_cargo_test_output(&stdout);
    // Match the EXACT test id (`--exact` may still surface filtered-out summary
    // lines, but those never parse as a path token). Drop ignored.
    for p in &parsed {
        if p.test_id == test_id && p.raw != "ignored" {
            let outcome = if p.raw == "ok" { "passed" } else { "failed" };
            return Ok(make_witness(&cc, &rc, test_id, outcome, code_files));
        }
    }
    // Test gone -> a non-reproducing `failed` witness (verify refuses, not invents).
    Ok(make_witness(&cc, &rc, test_id, "failed", code_files))
}

/// Reconstruct the per-test probe Witness from memento fields. Pure: the body is a
/// function of (code_cid, runtime_cid, test, outcome, code_files), so a CONSISTENT
/// memento reconstructs to its pinned cid. Mirrors python's `probe` Witness.
fn probe_witness(
    pinned_cid: &str,
    code_cid: &str,
    runtime_cid: &str,
    test_id: &str,
    outcome: &str,
    code_files: &[String],
) -> Witness {
    let mut files: Vec<String> = code_files.to_vec();
    files.sort();
    Witness {
        code_cid: code_cid.to_string(),
        runtime_cid: runtime_cid.to_string(),
        test_id: test_id.to_string(),
        outcome: outcome.to_string(),
        code_files: files,
        cid: pinned_cid.to_string(),
    }
}

/// PER-TEST recompute with the mandatory anti-tamper PRE-CHECK. Mirrors python's
/// per-test recompute arm BYTE-FOR-BYTE:
///   1. reconstruct the probe Witness from the memento's fields,
///   2. ANTI-TAMPER: if `blake3_512_of(witness_body(probe)) != pinned_cid`,
///      return Err WITHOUT running anything (never execute a path from a memento
///      that doesn't hash to its own cid -- a security property),
///   3. re-run the single pinned test via `runner`, rebuild the body, return it.
/// The re-run body (NOT the probe body) is returned: a now-`failed` test yields a
/// `failed` body so the verifier's reproduction check refuses -- that's the teeth.
/// The `runner` is injected so tests can prove the guard fires BEFORE execution
/// without nesting a real `cargo test`; production passes `run_one_test_witness`.
pub fn recompute_one_test_body<R>(
    pinned_cid: &str,
    code_cid: &str,
    runtime_cid: &str,
    test_id: &str,
    outcome: &str,
    code_files: &[String],
    runner: R,
) -> Result<Vec<u8>, String>
where
    R: FnOnce(&str, &[String]) -> Result<Witness, String>,
{
    let probe = probe_witness(
        pinned_cid,
        code_cid,
        runtime_cid,
        test_id,
        outcome,
        code_files,
    );
    // PRE-CHECK BEFORE ANY EXECUTION. Byte-for-byte the python guard message.
    if blake3_512_of(&witness_body(&probe)) != pinned_cid {
        return Err(format!(
            "memento fields do not reconstruct witness_cid {pinned_cid}; \
             refusing to re-run a tampered memento"
        ));
    }
    let w = runner(test_id, code_files)?;
    Ok(witness_body(&w))
}

// ---------------------------------------------------------------------------
// Source-tree discovery: the lift's code_files / test_files split. Code files are
// the crate's non-test .rs sources; test_files is a STABLE identifier for the
// suite (what resolve_witness needs to re-run -- the crate dir).
// ---------------------------------------------------------------------------

/// Collect project-relative `.rs` paths under `src/` and `tests/`, skipping
/// `target/`. Code files = src/*.rs; test_files = a stable suite identifier
/// (the crate dir name) -- the recompute primitive re-runs the whole crate, so
/// the per-file split only feeds `code_cid` (binding) and the memento metadata.
pub fn discover_rust_files(project_dir: &Path) -> (Vec<String>, Vec<String>) {
    let mut code_files = Vec::new();
    let mut have_tests = false;
    collect_rs(project_dir, project_dir, &mut code_files, &mut have_tests);
    code_files.sort();
    // test_files: a stable identifier for the suite. The crate's manifest dir
    // name is enough -- recompute re-runs the whole crate regardless. Use "." as
    // the project-relative suite handle so it is checkout-independent.
    let test_files = vec![".".to_string()];
    let _ = have_tests;
    (code_files, test_files)
}

fn collect_rs(root: &Path, dir: &Path, out: &mut Vec<String>, have_tests: &mut bool) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().to_string();
        if path.is_dir() {
            if matches!(name.as_str(), "target" | ".git" | ".sugar") {
                continue;
            }
            if name == "tests" {
                *have_tests = true;
            }
            collect_rs(root, &path, out, have_tests);
        } else if name.ends_with(".rs") {
            if let Ok(rel) = path.strip_prefix(root) {
                let rel = rel.to_string_lossy().to_string();
                // tests/ and benches/ are test harnesses, not code-under-test.
                let is_test_path = rel.starts_with("tests/")
                    || rel.starts_with("tests\\")
                    || rel.contains("/tests/")
                    || name.starts_with("test_");
                if is_test_path {
                    *have_tests = true;
                } else {
                    out.push(rel);
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// A helper the lift bin uses: build the whole lift result (contract IR member +
// memento) from a freshly-run suite. Returns (ir_members, mementos).
// ---------------------------------------------------------------------------

pub struct LiftResult {
    pub ir: Vec<serde_json::Value>,
    pub mementos: Vec<serde_json::Value>,
    pub bundle_cid: String,
    pub bundle_bytes: Vec<u8>,
    pub count: usize,
    pub passed: usize,
}

/// Run the suite, build the bundle, and assemble the lift's IR members + memento.
/// Mirrors python `handle_lift` for the witness-package case.
pub fn lift_project(project_dir: &Path) -> Result<Option<LiftResult>, String> {
    let (code_files, test_files) = discover_rust_files(project_dir);
    let (bundle_bytes, bundle_cid, witnesses) = build_suite_bundle(project_dir, &code_files)?;
    if witnesses.is_empty() {
        // No tests -> no witness package (python emits nothing when test_rels empty).
        return Ok(None);
    }
    let passed = witnesses.iter().filter(|w| w.outcome == "passed").count();
    let count = witnesses.len();
    let rc = runtime_cid();
    let contract =
        witness_package_contract_ir(&bundle_cid, &rc, &test_files, &code_files, count, passed);
    let memento =
        witness_package_memento(&bundle_cid, &test_files, &code_files, count, passed, None)?;
    Ok(Some(LiftResult {
        ir: vec![contract, memento.clone()],
        mementos: vec![memento],
        bundle_cid,
        bundle_bytes,
        count,
        passed,
    }))
}

// A small re-export so bins don't pull canonicalizer directly.
pub fn blake3_of(bytes: &[u8]) -> String {
    blake3_512_of(bytes)
}

/// Read the proofData JSON out of a serialized custom-evidence EvidenceTerm (the
/// shape `prove` writes to the temp `.proof` and hands the discharge bin):
///   {"kind":"evidence","proofType":"custom","certificate":{...,"proofData":"<json>"}}
pub fn parse_evidence_proof_data(evidence_json: &str) -> Result<serde_json::Value, String> {
    let env: serde_json::Value =
        serde_json::from_str(evidence_json).map_err(|e| format!("parse evidence: {e}"))?;
    let pd = env
        .get("certificate")
        .and_then(|c| c.get("proofData"))
        .and_then(|v| v.as_str())
        .ok_or("evidence missing certificate.proofData")?;
    serde_json::from_str(pd).map_err(|e| format!("parse proofData: {e}"))
}

// Used by tests + bins to map the memento's snake_case fields.
pub fn memento_str_list(memento: &serde_json::Value, key: &str) -> Vec<String> {
    memento
        .get(key)
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(test)]
mod tests;
