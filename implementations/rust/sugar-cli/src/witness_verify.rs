// SPDX-License-Identifier: MIT OR Apache-2.0
//
// The WITNESS VERIFY DIMENSION.
//
// Verification lives HERE, in the rust CLI. The kit oracle (python / java)
// RESOLVES a witness body over RPC; it is UNTRUSTED and must be verified. For
// each `witness-memento` in the `.proof`:
//
//   1. SIGNATURE -- rust verifies the ed25519 mark over the witness CID with the
//      substrate's own primitive (`ed25519_verify_string`), not the oracle's word.
//   2. RESOLVE + RECOMPUTE -- rust calls `sugar.plugin.resolve_witness` on the
//      kit oracle to fetch the body bytes (from the witness package, or by
//      re-running), then blake3's those bytes ITSELF and compares to the pinned
//      `witness_cid`.
//
// A body the oracle hands back that does NOT recompute to the pinned CID is a
// BROKEN ORACLE -- caught here because rust does the math anyway. Any mismatch
// refuses, loudly. Trust the recomputation, never the resolver.

use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use serde_json::{json, Value};

use sugar_canonicalizer::blake3_512_of;
use sugar_proof_envelope::{ed25519_verify_string, Signature};
use sugar_verifier::{
    MemberKind, MementoPool, VerifyEffect, WitnessVerificationCheck, WitnessVerificationOutcome,
};

/// One witness-memento's verdict from the rust verifier.
#[derive(Debug, Clone)]
pub struct WitnessVerifyResult {
    pub witness_cid: String,
    pub outcome: WitnessVerificationOutcome,
    /// The checks rust performed and passed, e.g. ["signature", "content-address:recompute"].
    pub checks: Vec<String>,
}

impl WitnessVerifyResult {
    fn verified(witness_cid: String, checks: Vec<String>, resolved_by: String) -> Self {
        Self {
            witness_cid,
            outcome: WitnessVerificationOutcome::Verified { resolved_by },
            checks,
        }
    }

    fn refused(witness_cid: String, checks: Vec<String>, check: WitnessVerificationCheck) -> Self {
        let effect = VerifyEffect::WitnessVerification {
            witness_cid: witness_cid.clone(),
            check,
        };
        Self {
            witness_cid,
            outcome: WitnessVerificationOutcome::Refused(effect),
            checks,
        }
    }

    fn broken_oracle(witness_cid: String, checks: Vec<String>, reason: String) -> Self {
        Self {
            witness_cid,
            outcome: WitnessVerificationOutcome::BrokenOracle { reason },
            checks,
        }
    }

    pub fn is_ok(&self) -> bool {
        self.outcome.is_ok()
    }

    pub fn verdict(&self) -> &'static str {
        self.outcome.verdict()
    }

    pub fn reason(&self) -> String {
        self.outcome.reason()
    }
}

/// Verify every `witness-memento` in the pool. Returns one result per witness
/// (empty when the `.proof` carries no witnesses).
#[allow(dead_code)] // Kept as the default wrapper for callers without component-plan options.
pub fn verify_witnesses(project_root: &Path, pool: &MementoPool) -> Vec<WitnessVerifyResult> {
    verify_witnesses_with_options(
        project_root,
        pool,
        crate::component_plan::ComponentPlanOptions::default(),
    )
}

pub fn verify_witnesses_with_options(
    project_root: &Path,
    pool: &MementoPool,
    component_plan_options: crate::component_plan::ComponentPlanOptions,
) -> Vec<WitnessVerifyResult> {
    let mut out = Vec::new();
    let resolvers = match find_resolvers(project_root, component_plan_options) {
        Ok(resolvers) => resolvers,
        Err(reason) => {
            for (_, member) in pool.witness_memento_members() {
                let witness_cid = member
                    .field("witnessCid")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                out.push(WitnessVerifyResult::refused(
                    witness_cid,
                    Vec::new(),
                    WitnessVerificationCheck::ComponentPlanFailed {
                        reason: reason.clone(),
                    },
                ));
            }
            return out;
        }
    };
    for (_, member) in pool.witness_memento_members() {
        // The envelope separates METADATA from CONTENT. Route + index by the
        // HEADER (the metadata: kind, witnessCid, signer); verify the BODY (the
        // signed content). The witness's actual run-body is resolved separately
        // from the package -- the deepest content/metadata split.
        let witness_cid = member
            .field("witnessCid")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let signer = member
            .field("signer")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        // body is kept as-is: no pool-level full-body accessor exists, and
        // the kit oracle resolver requires the whole body object.
        let body = member.body().cloned().unwrap_or(Value::Null);
        let signature = member
            .field("signature")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let mut checks: Vec<String> = Vec::new();

        // ENVELOPE INTEGRITY: the content must match its metadata. The body's
        // own witness_cid must equal the header's witnessCid, or the envelope
        // was tampered (content swapped under unchanged metadata).
        let body_cid = member
            .field("witness_cid")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if body_cid != witness_cid {
            out.push(WitnessVerifyResult::refused(
                witness_cid,
                checks,
                WitnessVerificationCheck::EnvelopeIntegrityMismatch,
            ));
            continue;
        }

        // 1. SIGNATURE -- rust's own primitive. Two witness families flow
        // through here with two signing schemes:
        //
        //   - WitnessMemento (verification witnesses from `sugar verify`):
        //     carries `observed_at`. The mark covers the SEALED POSTMARK --
        //     the {cid, observed_at} attestation payload (JCS-canonical), not
        //     the bare CID. The CID is the THEOREM-mode convergence handle
        //     (excluded from its own preimage; byte-stable across honest
        //     re-derivation); `observed_at` is a TESTIMONY-mode IO event that
        //     rides sealed alongside it. Verifying the joint payload means a
        //     tampered observed_at fails the mark even though it does not move
        //     the CID (#2022-class: the witness CID is a content-address, the
        //     timestamp is still sworn).
        //   - witness-package mementos (cargo-test / pytest suite packages):
        //     no `observed_at`; the mark covers the bare bundle CID. These
        //     keep their existing scheme.
        //
        // `witness_attestation_payload` is the single source of truth shared
        // with the mint path (cmd_verify) for the postmark bytes.
        let observed_at = member
            .field("observed_at")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let signature_ok = match (
            witness_cid.is_empty(),
            Signature::try_parse(signature.to_string()),
        ) {
            (true, _) | (_, Err(_)) => false,
            (false, Ok(signature)) if observed_at.is_empty() => {
                // Package family: mark over the bare CID (legacy scheme).
                ed25519_verify_string(signer, &signature, witness_cid.as_bytes())
            }
            (false, Ok(signature)) => {
                // WitnessMemento family: mark over the sealed {cid, observed_at}.
                let attested =
                    sugar_ir_types::witness_attestation_payload(&witness_cid, observed_at);
                ed25519_verify_string(signer, &signature, &attested)
            }
        };
        if !signature_ok {
            out.push(WitnessVerifyResult::refused(
                witness_cid,
                checks,
                WitnessVerificationCheck::InvalidSignature,
            ));
            continue;
        }
        checks.push("signature".to_string());

        // OUTCOME: a witness recording a FAILED run is not a discharge, even with
        // a valid CID + signature. Refuse it. Witnesses with no `outcome` (a poem,
        // a CI log, a compiler report) skip this check and proceed to recompute.
        if member.field("outcome").and_then(|v| v.as_str()) == Some("failed") {
            out.push(WitnessVerifyResult::refused(
                witness_cid,
                checks,
                WitnessVerificationCheck::FailedOutcome,
            ));
            continue;
        }

        // 2. RESOLVE via the kit oracle, then RECOMPUTE the CID here. Try each
        // declared resolver; ACCEPT the first whose returned body BLAKE3's to the
        // pinned witness_cid. The content-address check is the arbiter, so this is
        // sound (no kit can forge a hashing body) and order-independent: a
        // first-found scan could otherwise refuse a valid witness just because an
        // unrelated kit's manifest sorted first. If none hash, report the most
        // informative refusal seen (broken package > honest drift > resolve error).
        if resolvers.is_empty() {
            out.push(WitnessVerifyResult::refused(
                witness_cid,
                checks,
                WitnessVerificationCheck::NoResolverDeclared,
            ));
            continue;
        }
        match resolve_over_resolvers(&resolvers, project_root, &body, &witness_cid) {
            Resolution::Verified { resolved_by } => {
                checks.push(format!("content-address:{resolved_by}"));
                out.push(WitnessVerifyResult::verified(
                    witness_cid.clone(),
                    checks,
                    resolved_by,
                ));
            }
            Resolution::BrokenOracle { reason } => out.push(WitnessVerifyResult::broken_oracle(
                witness_cid.clone(),
                checks,
                reason,
            )),
            Resolution::Drift { reason } | Resolution::Unresolved { reason } => {
                out.push(WitnessVerifyResult::refused(
                    witness_cid.clone(),
                    checks,
                    WitnessVerificationCheck::ReplayRefused { reason },
                ))
            }
        }
    }
    out
}

/// True when the pool carries at least one `witness-memento`.
pub fn has_witnesses(pool: &MementoPool) -> bool {
    pool.has_member_kind(MemberKind::WitnessMemento)
}

/// Scan `.sugar/lift/*/manifest.toml` for EVERY kit that declares a
/// `resolve_witness_command`, returning each as (argv, working_dir, method). We
/// return all of them, not the first found, because the resolver is not chosen
/// blindly by directory order: each witness picks the resolver whose body BLAKE3's
/// to its pinned CID (see `verify_witnesses`). A wrong kit cannot forge a hashing
/// body, so trying each is sound and removes the order-dependence a single
/// first-found scan would have in a multi-kit project.
fn find_resolvers(
    project_root: &Path,
    component_plan_options: crate::component_plan::ComponentPlanOptions,
) -> Result<Vec<(Vec<String>, Option<PathBuf>, String)>, String> {
    let lift_dir = project_root.join(".sugar").join("lift");
    let mut found = Vec::new();
    if let Ok(entries) = std::fs::read_dir(&lift_dir) {
        for entry in entries.flatten() {
            let manifest = entry.path().join("manifest.toml");
            if !manifest.exists() {
                continue;
            }
            if let Some(r) = parse_resolve_command(&manifest, project_root) {
                found.push(r);
            }
        }
    }
    let component_plan = crate::component_plan::plan_workspace_with_options(
        project_root,
        crate::component_plan::PlanIntent::Verify,
        component_plan_options,
    );
    if let Some(diagnostic) = crate::component_plan::first_error_diagnostic(&component_plan) {
        return Err(diagnostic.message.clone());
    }
    for manifest in component_plan.lift_manifests {
        if manifest.resolve_witness_command.is_empty() {
            continue;
        }
        found.push((
            manifest.resolve_witness_command,
            crate::component_plan::resolve_project_relative_working_dir(
                project_root,
                manifest.working_dir.as_ref(),
            )
            .or_else(|| Some(project_root.to_path_buf())),
            manifest
                .resolve_witness_method
                .unwrap_or_else(|| "sugar.plugin.resolve_witness".to_string()),
        ));
    }
    Ok(found)
}

/// Minimal TOML read for the `resolve_witness_command` array + `working_dir`,
/// mirroring cmd_prove's manifest parser (multi-line arrays, `#` comments).
fn parse_resolve_command(
    manifest: &Path,
    project_root: &Path,
) -> Option<(Vec<String>, Option<PathBuf>, String)> {
    let text = std::fs::read_to_string(manifest).ok()?;
    let strip = |l: &str| -> String {
        match l.find('#') {
            Some(p) => l[..p].to_string(),
            None => l.to_string(),
        }
    };
    let raw: Vec<String> = text.lines().map(|l| strip(l).trim().to_string()).collect();
    let mut argv: Vec<String> = Vec::new();
    let mut working_dir: Option<PathBuf> = None;
    let mut method: Option<String> = None;
    let mut i = 0;
    while i < raw.len() {
        let line = raw[i].clone();
        i += 1;
        if line.is_empty() || line.starts_with('[') {
            continue;
        }
        let Some(eq) = line.find('=') else { continue };
        let key = line[..eq].trim().to_string();
        let mut val = line[eq + 1..].trim().to_string();
        if val.starts_with('[') && !val.contains(']') {
            while i < raw.len() && !val.contains(']') {
                val.push(' ');
                val.push_str(&raw[i]);
                i += 1;
            }
        }
        match key.as_str() {
            "resolve_witness_command" => {
                let inner = val.trim_matches(|c| c == '[' || c == ']');
                argv = inner
                    .split(',')
                    .map(|s| s.trim().trim_matches('"').to_string())
                    .filter(|s| !s.is_empty())
                    .collect();
            }
            "working_dir" => {
                let p = PathBuf::from(val.trim_matches('"'));
                working_dir = Some(if p.is_absolute() {
                    p
                } else {
                    project_root.join(p)
                });
            }
            "resolve_witness_method" => {
                method = Some(val.trim_matches('"').to_string());
            }
            _ => {}
        }
    }
    if argv.is_empty() {
        return None;
    }
    Some((
        argv,
        working_dir.or_else(|| Some(project_root.to_path_buf())),
        // Honor the manifest's declared method; default to the canonical one.
        method.unwrap_or_else(|| "sugar.plugin.resolve_witness".to_string()),
    ))
}

/// The outcome of trying every declared resolver against one witness.
#[derive(Debug)]
enum Resolution {
    /// A resolver returned a body whose BLAKE3 equals the pinned witness_cid.
    Verified { resolved_by: String },
    /// A package paired this CID with bytes that do NOT hash to it (tampered
    /// package / broken oracle), and nothing else verified.
    BrokenOracle { reason: String },
    /// An honest re-run reproduced a different CID (the proof is stale / drifted).
    Drift { reason: String },
    /// No resolver could hand back any usable body (all errored).
    Unresolved { reason: String },
}

/// Try each declared resolver against one witness; ACCEPT the first whose returned
/// body BLAKE3's to the pinned `witness_cid`. The content-address check is the
/// arbiter, so this is sound (no kit can forge a hashing body) and
/// order-independent: a first-found scan could otherwise refuse a valid witness
/// just because an unrelated kit's manifest sorted first. If none hash, report the
/// most informative refusal seen (broken package > honest drift > resolve error).
fn resolve_over_resolvers(
    resolvers: &[(Vec<String>, Option<PathBuf>, String)],
    project_root: &Path,
    body: &Value,
    witness_cid: &str,
) -> Resolution {
    let mut broken_oracle: Option<String> = None;
    let mut drift: Option<String> = None;
    let mut errors: Vec<String> = Vec::new();
    for (argv, working_dir, method) in resolvers {
        match resolve_body(argv, working_dir.as_deref(), method, project_root, body) {
            Ok((resolved_by, bytes)) => {
                let computed = blake3_512_of(&bytes);
                if computed == witness_cid {
                    return Resolution::Verified { resolved_by };
                } else if resolved_by == "package" {
                    broken_oracle.get_or_insert(format!(
                        "package content computes to {computed}, not the pinned {witness_cid} \
                         -- broken oracle / tampered package; rust recomputed the CID and refused"
                    ));
                } else {
                    drift.get_or_insert(format!(
                        "witness did not reproduce (re-run drifted): computed {computed} != \
                         pinned {witness_cid} -- the oracle was honest, the proof is stale"
                    ));
                }
            }
            Err(e) => errors.push(e),
        }
    }
    if let Some(reason) = broken_oracle {
        Resolution::BrokenOracle { reason }
    } else if let Some(reason) = drift {
        Resolution::Drift { reason }
    } else {
        Resolution::Unresolved {
            reason: format!("could not resolve witness body: {}", errors.join("; ")),
        }
    }
}

/// Spawn the kit oracle and call `sugar.plugin.resolve_witness`, returning
/// (resolved_by, body_bytes). The oracle returns CONTENT, not a verdict; the
/// caller recomputes the CID.
fn resolve_body(
    argv: &[String],
    working_dir: Option<&Path>,
    method: &str,
    project_root: &Path,
    memento_body: &Value,
) -> Result<(String, Vec<u8>), String> {
    if argv.is_empty() {
        return Err("empty resolver argv".to_string());
    }
    let abs_root = std::fs::canonicalize(project_root)
        .unwrap_or_else(|_| project_root.to_path_buf())
        .display()
        .to_string();
    let package_dir = project_root.join(".sugar").join("witnesses");
    let mut params = json!({
        "memento": memento_body,
        "workspace_root": abs_root,
    });
    if package_dir.exists() {
        params["package_dir"] = json!(package_dir.display().to_string());
    }
    let req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    });

    let mut cmd = Command::new(&argv[0]);
    cmd.args(&argv[1..]);
    cmd.arg("--rpc");
    if let Some(wd) = working_dir {
        cmd.current_dir(wd);
    }
    cmd.stdin(Stdio::piped());
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::null());
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("spawn resolver {}: {e}", argv[0]))?;
    {
        // TAKE stdin and DROP it after writing, so the kit's read loop sees EOF,
        // breaks, and closes stdout -- otherwise rust blocks reading to EOF while
        // the kit blocks reading the next request line (deadlock).
        let mut stdin = child.stdin.take().ok_or("resolver stdin unavailable")?;
        let line = serde_json::to_string(&req).map_err(|e| e.to_string())?;
        stdin
            .write_all(line.as_bytes())
            .and_then(|_| stdin.write_all(b"\n"))
            .map_err(|e| format!("write resolver stdin: {e}"))?;
        // stdin dropped here -> EOF to the kit.
    }
    // Read stdout on a worker thread and bound the wait with a TIMEOUT: even with
    // stdin dropped (EOF), a misbehaving kit could ignore it and hang. On timeout
    // we kill the child and refuse, rather than block verify forever.
    let stdout = child.stdout.take().ok_or("resolver stdout unavailable")?;
    let (tx, rx) = std::sync::mpsc::channel::<Option<Value>>();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        let mut last_reply: Option<Value> = None;
        for line in reader.lines().map_while(Result::ok) {
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            if let Ok(v) = serde_json::from_str::<Value>(trimmed) {
                if v.get("result").is_some() || v.get("error").is_some() {
                    last_reply = Some(v);
                }
            }
        }
        let _ = tx.send(last_reply);
    });
    const RESOLVER_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(120);
    let reply = match rx.recv_timeout(RESOLVER_TIMEOUT) {
        Ok(r) => r,
        Err(_) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!(
                "resolver `{}` timed out after {}s",
                argv[0],
                RESOLVER_TIMEOUT.as_secs()
            ));
        }
    };
    let _ = child.wait();
    let reply = reply.ok_or("resolver produced no JSON-RPC reply")?;
    if let Some(err) = reply.get("error") {
        let msg = err
            .get("message")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        return Err(VerifyEffect::WitnessOracleResolution {
            resolver: argv.first().cloned(),
            message: msg.to_string(),
        }
        .to_string());
    }
    let result = reply.get("result").ok_or("reply missing `result`")?;
    let body_b64 = result
        .get("body_b64")
        .and_then(|v| v.as_str())
        .ok_or("resolve_witness result missing `body_b64`")?;
    let resolved_by = result
        .get("resolved_by")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown")
        .to_string();
    let bytes = B64
        .decode(body_b64)
        .map_err(|e| format!("decode body_b64: {e}"))?;
    Ok((resolved_by, bytes))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    // A hermetic fake resolver: an `sh -c` command that drains stdin (so rust's
    // EOF-after-write handshake completes) and prints one canned JSON-RPC reply.
    // No kit, no network -- it exercises resolve_over_resolvers' selection logic.
    fn fake_resolver(reply: &str) -> (Vec<String>, Option<PathBuf>, String) {
        let script = format!("cat >/dev/null 2>&1; printf '%s\\n' '{reply}'");
        (
            vec!["sh".to_string(), "-c".to_string(), script],
            None,
            "sugar.plugin.resolve_witness".to_string(),
        )
    }

    // A `result` reply handing back `body` as a package-resolved body.
    fn good_reply(body: &[u8]) -> String {
        format!(
            r#"{{"jsonrpc":"2.0","id":1,"result":{{"resolved_by":"package","body_b64":"{}"}}}}"#,
            B64.encode(body)
        )
    }

    // POSITIVE: one resolver hands back the pinned body -> verified.
    #[test]
    fn single_resolver_verifies_a_matching_body() {
        let body = b"the witnessed run body";
        let cid = blake3_512_of(body);
        let resolvers = vec![fake_resolver(&good_reply(body))];
        let res = resolve_over_resolvers(&resolvers, &std::env::temp_dir(), &json!({}), &cid);
        assert!(matches!(res, Resolution::Verified { .. }), "got {res:?}");
    }

    // DISCRIMINATION (the finding): the first resolver cannot resolve, the second
    // can. A first-found scan would refuse; selection-by-content-address verifies.
    // Both orders must verify -- the choice is the hash, not directory order.
    #[test]
    fn second_resolver_verifies_when_the_first_cannot() {
        let body = b"the witnessed run body";
        let cid = blake3_512_of(body);
        let bad = fake_resolver(r#"{"jsonrpc":"2.0","id":1,"error":{"message":"unrelated kit"}}"#);
        let good = fake_resolver(&good_reply(body));
        let forward = resolve_over_resolvers(
            &[bad.clone(), good.clone()],
            &std::env::temp_dir(),
            &json!({}),
            &cid,
        );
        assert!(
            matches!(forward, Resolution::Verified { .. }),
            "bad-then-good must verify; got {forward:?}"
        );
        let reverse = resolve_over_resolvers(&[good, bad], &std::env::temp_dir(), &json!({}), &cid);
        assert!(
            matches!(reverse, Resolution::Verified { .. }),
            "good-then-bad must verify; got {reverse:?}"
        );
    }

    // STRUCTURAL: no resolver returns a body that hashes to the pinned CID. Wrong
    // bytes under a "package" label is a BROKEN ORACLE refusal, never a verify --
    // a wrong kit cannot forge a hashing body.
    #[test]
    fn wrong_bytes_under_package_label_is_refused_not_verified() {
        let body = b"the witnessed run body";
        let cid = blake3_512_of(body);
        let err = fake_resolver(r#"{"jsonrpc":"2.0","id":1,"error":{"message":"nope"}}"#);
        let wrong = fake_resolver(&good_reply(b"not the witnessed body"));
        let res = resolve_over_resolvers(&[err, wrong], &std::env::temp_dir(), &json!({}), &cid);
        assert!(
            matches!(res, Resolution::BrokenOracle { .. }),
            "wrong bytes must refuse; got {res:?}"
        );
    }

    // ------- SIGNATURE GATE: the SEALED POSTMARK (#2022-class) -------
    //
    // The gate in `verify_witnesses` chooses its scheme on the presence of
    // `observed_at`. These tests exercise that exact predicate end-to-end with
    // the real ed25519 primitives, mirroring the inline logic.

    use sugar_proof_envelope::{
        ed25519_pubkey_string, ed25519_sign_string, Ed25519Seed, Signature,
    };

    const TEST_SEED: Ed25519Seed = [7u8; 32];

    /// The exact signature predicate `verify_witnesses` applies (kept in sync).
    fn signature_ok(witness_cid: &str, observed_at: &str, signer: &str, signature: &str) -> bool {
        let Ok(signature) = Signature::try_parse(signature.to_string()) else {
            return false;
        };
        if witness_cid.is_empty() {
            false
        } else if observed_at.is_empty() {
            ed25519_verify_string(signer, &signature, witness_cid.as_bytes())
        } else {
            let attested = sugar_ir_types::witness_attestation_payload(witness_cid, observed_at);
            ed25519_verify_string(signer, &signature, &attested)
        }
    }

    // POSITIVE: a WitnessMemento-family mark (signed over {cid, observed_at})
    // verifies, and is INDEPENDENT of observed_at being baked into the CID --
    // the CID is the stable discharge handle, the postmark rides sealed.
    #[test]
    fn witness_memento_postmark_signature_verifies() {
        let cid = format!("blake3-512:{}", "a".repeat(128));
        let observed_at = "2026-06-11T12:00:00.000Z";
        let signer = ed25519_pubkey_string(&TEST_SEED);
        let payload = sugar_ir_types::witness_attestation_payload(&cid, observed_at);
        let signature = ed25519_sign_string(&TEST_SEED, &payload);
        assert!(
            signature_ok(&cid, observed_at, &signer, &signature),
            "an honest {{cid, observed_at}} postmark must verify"
        );
    }

    // THE TEETH: tamper observed_at and the mark NO LONGER verifies, even though
    // the CID (the discharge handle) is unchanged. The timestamp is still sworn.
    #[test]
    fn tampered_observed_at_fails_signature_verification() {
        let cid = format!("blake3-512:{}", "a".repeat(128));
        let observed_at = "2026-06-11T12:00:00.000Z";
        let signer = ed25519_pubkey_string(&TEST_SEED);
        let payload = sugar_ir_types::witness_attestation_payload(&cid, observed_at);
        let signature = ed25519_sign_string(&TEST_SEED, &payload);

        // Same signature, same (unchanged) CID, but a forged later timestamp.
        let tampered_observed_at = "2026-06-11T13:00:00.000Z";
        assert!(
            !signature_ok(&cid, tampered_observed_at, &signer, &signature),
            "a tampered observed_at must FAIL the mark -- the postmark is sealed \
             under the signature, not free-floating"
        );
    }

    // NON-REGRESSION: the package family (no observed_at) keeps the bare-CID
    // scheme. A mark over the bundle CID still verifies, and a payload-scheme
    // verification is NOT applied to it.
    #[test]
    fn package_family_bare_cid_signature_still_verifies() {
        let cid = format!("blake3-512:{}", "b".repeat(128));
        let signer = ed25519_pubkey_string(&TEST_SEED);
        let signature = ed25519_sign_string(&TEST_SEED, cid.as_bytes());
        assert!(
            signature_ok(&cid, "", &signer, &signature),
            "a package-family mark over the bare bundle CID must still verify"
        );
    }
}
