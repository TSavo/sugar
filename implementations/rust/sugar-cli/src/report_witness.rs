// SPDX-License-Identifier: Apache-2.0
//
// Prove-report witness adapter.
//
// The report is already the bounded artifact: facts, universes, linked vendor
// posts, and solver discharges. This module writes the witness body as an
// external sidecar and places only the signed witness-memento pointer in the
// proof envelope.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, ed25519_sign_string, proof_filename, Ed25519Seed,
    MementoCid, ProofEnvelopeInput, ProofGraph, WitnessMemento,
};

#[derive(Debug, Clone)]
pub(crate) struct ReportWitnessProof {
    pub name: String,
    pub proof_cid: String,
    pub proof_file: PathBuf,
    pub witness_cid: String,
    pub evidence_cid: String,
    pub evidence_file: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct WitnessClaimKind(String);

impl WitnessClaimKind {
    pub(crate) fn new(raw: impl Into<String>) -> Result<Self, String> {
        let raw = raw.into();
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            return Err(witness_seam_refusal(
                "empty witness claim kind",
                "claimKind was empty before witness minting",
                "construct WitnessClaimKind with a non-empty protocol claim kind",
            ));
        }
        Ok(Self(trimmed.to_string()))
    }

    fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub(crate) struct WitnessToolchainScope {
    plan_cid: Option<MementoCid>,
    actual_output_cids: Vec<MementoCid>,
}

impl WitnessToolchainScope {
    pub(crate) fn try_new(
        plan_cid: Option<String>,
        actual_output_cids: Vec<String>,
    ) -> Result<Self, String> {
        if !actual_output_cids.is_empty() && plan_cid.is_none() {
            return Err(witness_seam_refusal(
                "toolchain output witness without replay plan",
                "actualOutputCids present with no planCid",
                "construct WitnessToolchainScope with Some(planCid) or leave actualOutputCids empty",
            ));
        }
        let plan_cid = plan_cid
            .map(|cid| parse_memento_cid("planCid", &cid))
            .transpose()?;
        let actual_output_cids = actual_output_cids
            .into_iter()
            .map(|cid| parse_memento_cid("actualOutputCids", &cid))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(Self {
            plan_cid,
            actual_output_cids,
        })
    }

    fn add_to_body(&self, body: &mut Json) {
        let Some(obj) = body.as_object_mut() else {
            return;
        };
        if let Some(plan_cid) = &self.plan_cid {
            obj.insert("planCid".to_string(), json!(plan_cid.to_string()));
        }
        if !self.actual_output_cids.is_empty() {
            obj.insert(
                "actualOutputCids".to_string(),
                json!(self
                    .actual_output_cids
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>()),
            );
        }
    }

    fn plan_cid_str(&self) -> Option<&str> {
        self.plan_cid.as_ref().map(MementoCid::as_str)
    }

    fn actual_output_cid_strings(&self) -> Vec<String> {
        self.actual_output_cids
            .iter()
            .map(ToString::to_string)
            .collect()
    }
}

#[derive(Debug, Clone)]
enum WitnessRef {
    Builtin(String),
    Cid(MementoCid),
}

impl WitnessRef {
    fn try_new(context: &str, raw: impl Into<String>) -> Result<Self, String> {
        let raw = raw.into();
        if raw.trim().is_empty() {
            return Err(witness_seam_refusal(
                "empty witness replay reference",
                &format!("{context} was empty before witness minting"),
                "use builtin:<name> or a blake3-512 CID reference",
            ));
        }
        if raw.starts_with("builtin:") {
            return Ok(Self::Builtin(raw));
        }
        parse_memento_cid(context, &raw).map(Self::Cid)
    }

    fn into_string(self) -> String {
        match self {
            Self::Builtin(raw) => raw,
            Self::Cid(cid) => cid.to_string(),
        }
    }
}

#[derive(Debug, Clone, Default)]
pub(crate) struct WitnessMintOptions {
    produced_by: Option<String>,
    produced_at: Option<String>,
    verifier_cid: Option<WitnessRef>,
    policy_cid: Option<WitnessRef>,
    extra_input_cids: Vec<MementoCid>,
    proof_metadata: BTreeMap<String, String>,
    toolchain_scope: WitnessToolchainScope,
}

impl WitnessMintOptions {
    pub(crate) fn with_produced_by(mut self, produced_by: impl Into<String>) -> Self {
        self.produced_by = Some(produced_by.into());
        self
    }

    pub(crate) fn with_produced_at(mut self, produced_at: impl Into<String>) -> Self {
        self.produced_at = Some(produced_at.into());
        self
    }

    pub(crate) fn with_verifier_cid(
        mut self,
        verifier_cid: impl Into<String>,
    ) -> Result<Self, String> {
        self.verifier_cid = Some(WitnessRef::try_new("verifierCid", verifier_cid)?);
        Ok(self)
    }

    pub(crate) fn with_policy_cid(mut self, policy_cid: impl Into<String>) -> Result<Self, String> {
        self.policy_cid = Some(WitnessRef::try_new("policyCid", policy_cid)?);
        Ok(self)
    }

    pub(crate) fn with_extra_input_cids(mut self, input_cids: Vec<String>) -> Result<Self, String> {
        self.extra_input_cids = input_cids
            .into_iter()
            .map(|cid| parse_memento_cid("extraInputCids", &cid))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(self)
    }

    pub(crate) fn with_proof_metadata(mut self, proof_metadata: BTreeMap<String, String>) -> Self {
        self.proof_metadata = proof_metadata;
        self
    }

    pub(crate) fn with_toolchain_scope(mut self, toolchain_scope: WitnessToolchainScope) -> Self {
        self.toolchain_scope = toolchain_scope;
        self
    }
}

#[derive(Debug, Clone)]
pub(crate) enum WitnessSource {
    Report(ReportWitnessSource),
    Command(CommandWitnessSource),
    File(FileWitnessSource),
    JsonClaim(JsonWitnessSource),
}

impl WitnessSource {
    pub(crate) fn report(project_root: &Path, report: Json, replay_pins: Json) -> Self {
        Self::Report(ReportWitnessSource {
            project_root: project_root.to_path_buf(),
            report,
            replay_pins,
        })
    }

    pub(crate) fn command(
        project_root: &Path,
        name: impl Into<String>,
        command: Vec<String>,
        evidence: Json,
    ) -> Result<Self, String> {
        if command.is_empty() {
            return Err(witness_seam_refusal(
                "command witness without a command",
                "WitnessSource::Command carried an empty command vector",
                "construct WitnessSource::Command with the configured command argv before minting",
            ));
        }
        Ok(Self::Command(CommandWitnessSource {
            project_root: project_root.to_path_buf(),
            name: checked_witness_name(name)?,
            command,
            evidence,
        }))
    }

    pub(crate) fn file(
        project_root: &Path,
        name: impl Into<String>,
        path: impl Into<String>,
        evidence: Json,
    ) -> Result<Self, String> {
        let path = path.into();
        if path.trim().is_empty() {
            return Err(witness_seam_refusal(
                "file witness without a path",
                "WitnessSource::File carried an empty project-relative path",
                "construct WitnessSource::File with the configured evidence path before minting",
            ));
        }
        Ok(Self::File(FileWitnessSource {
            project_root: project_root.to_path_buf(),
            name: checked_witness_name(name)?,
            path,
            evidence,
        }))
    }

    pub(crate) fn json_claim(
        name: impl Into<String>,
        claim_kind: WitnessClaimKind,
        claim_body: Json,
        evidence: Json,
    ) -> Result<Self, String> {
        Ok(Self::JsonClaim(JsonWitnessSource {
            name: checked_witness_name(name)?,
            claim_kind,
            claim_body,
            evidence,
        }))
    }
}

#[derive(Debug, Clone)]
pub(crate) struct ReportWitnessSource {
    project_root: PathBuf,
    report: Json,
    replay_pins: Json,
}

#[derive(Debug, Clone)]
pub(crate) struct CommandWitnessSource {
    project_root: PathBuf,
    name: String,
    command: Vec<String>,
    evidence: Json,
}

#[derive(Debug, Clone)]
pub(crate) struct FileWitnessSource {
    project_root: PathBuf,
    name: String,
    path: String,
    evidence: Json,
}

#[derive(Debug, Clone)]
pub(crate) struct JsonWitnessSource {
    name: String,
    claim_kind: WitnessClaimKind,
    claim_body: Json,
    evidence: Json,
}

#[derive(Debug, Clone)]
pub(crate) struct WitnessBundle {
    source: WitnessSource,
    options: WitnessMintOptions,
}

impl WitnessBundle {
    pub(crate) fn from_source(
        source: WitnessSource,
        options: WitnessMintOptions,
    ) -> Result<Self, String> {
        Ok(Self { source, options })
    }
}

struct PreparedWitness {
    name: String,
    claim_kind: WitnessClaimKind,
    claim_body: Json,
    evidence: Json,
}

pub(crate) fn mint_witness_bundle(
    bundle: WitnessBundle,
    out_dir: &Path,
) -> Result<ReportWitnessProof, String> {
    let PreparedWitness {
        name,
        claim_kind,
        claim_body,
        evidence,
    } = prepare_witness(bundle.source)?;
    let claim_kind = claim_kind.as_str();
    let WitnessMintOptions {
        produced_by,
        produced_at,
        verifier_cid,
        policy_cid,
        extra_input_cids,
        proof_metadata,
        toolchain_scope,
    } = bundle.options;

    let claim_body_cid = jcs_cid(&claim_body);
    let evidence_root_cid = jcs_cid(&evidence);
    let verifier_cid = verifier_cid
        .map(WitnessRef::into_string)
        .unwrap_or_else(|| format!("builtin:{claim_kind}"));
    let policy_cid = policy_cid
        .map(WitnessRef::into_string)
        .unwrap_or_else(|| format!("builtin:{claim_kind}-policy"));
    let mut witness_body = json!({
        "kind": "sugar-json-witness-body",
        "schemaVersion": "1",
        "claimKind": claim_kind,
        "claimBodyCid": claim_body_cid,
        "evidenceRootCid": evidence_root_cid,
        "verifierCid": verifier_cid,
        "policyCid": policy_cid,
        "claimBody": claim_body,
        "evidence": evidence,
    });
    toolchain_scope.add_to_body(&mut witness_body);
    let witness_cid = jcs_cid(&witness_body);
    let mut input_cids = collect_cid_strings(&witness_body)?;
    for cid in extra_input_cids {
        input_cids.insert(cid.to_string());
    }
    input_cids.insert(claim_body_cid.clone());
    input_cids.insert(evidence_root_cid.clone());
    let input_cids: Vec<String> = input_cids.into_iter().collect();
    let produced_by = produced_by.unwrap_or_else(|| format!("sugar-witness:{name}"));
    let produced_at = produced_at
        .unwrap_or_else(|| chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true));
    let signer_seed = deterministic_signer_seed(&produced_by);
    let signer = ed25519_pubkey_string(&signer_seed);
    let signature = ed25519_sign_string(&signer_seed, witness_cid.as_bytes());

    let mut witness_pointer = json!({
        "body": {
            "kind": "witness-memento",
            "schemaVersion": "1",
            "witness_cid": witness_cid,
            "witness_kind": claim_kind,
            "signer": signer,
            "signature": signature,
            "claimBodyCid": claim_body_cid,
            "evidenceRootCid": evidence_root_cid,
            "verifierCid": verifier_cid,
            "policyCid": policy_cid,
            "inputCids": input_cids,
            "producedBy": produced_by,
            "producedAt": produced_at,
        },
        "header": {
            "kind": "witness-memento",
            "signer": signer,
            "witnessCid": witness_cid,
            "witnessKind": claim_kind,
        },
        "schemaVersion": "1",
    });
    if let Some(body) = witness_pointer
        .get_mut("body")
        .and_then(serde_json::Value::as_object_mut)
    {
        if let Some(plan_cid) = toolchain_scope.plan_cid_str() {
            body.insert("planCid".to_string(), json!(plan_cid));
        }
        let actual_output_cids = toolchain_scope.actual_output_cid_strings();
        if !actual_output_cids.is_empty() {
            body.insert("actualOutputCids".to_string(), json!(actual_output_cids));
        }
    }
    let witness_pointer_bytes = encode_jcs(&json_to_cvalue(&witness_pointer));
    let witness_pointer_cid = blake3_512_of(witness_pointer_bytes.as_bytes());
    let witness_memento = WitnessMemento::new(witness_pointer_bytes.into_bytes());
    assert_eq!(
        witness_memento.cid().as_str(),
        witness_pointer_cid,
        "witness pointer CID disagrees with WitnessMemento"
    );
    let mut graph = ProofGraph::new();
    graph.push_witness(witness_memento);
    let mut metadata = BTreeMap::new();
    metadata.insert("sugar.witness.name".into(), name.to_string());
    metadata.insert("sugar.witness.claimKind".into(), claim_kind.to_string());
    metadata.insert(
        "sugar.witness.evidenceCid".into(),
        evidence_root_cid.clone(),
    );
    metadata.insert("sugar.witness.witnessCid".into(), witness_cid.clone());
    metadata.extend(proof_metadata);

    let proof = build_proof_envelope(&ProofEnvelopeInput {
        name: format!("@sugar/witness/{name}"),
        version: "0.1.0".into(),
        binary_cid: None,
        metadata: Some(metadata),
        graph,
        signer_cid: ed25519_pubkey_string(&signer_seed),
        signer_seed,
        declared_at: produced_at,
    });

    std::fs::create_dir_all(out_dir).map_err(|e| format!("mkdir {}: {e}", out_dir.display()))?;
    let proof_file = out_dir.join(proof_filename(&proof.cid));
    std::fs::write(&proof_file, &proof.bytes)
        .map_err(|e| format!("write {}: {e}", proof_file.display()))?;
    let evidence_file = out_dir.join(format!(
        "{}-{}.json",
        sanitize_filename(&name),
        witness_cid.trim_start_matches("blake3-512:")
    ));
    let evidence_bytes = serde_json::to_vec_pretty(&witness_body)
        .map_err(|e| format!("serialize report witness body: {e}"))?;
    std::fs::write(&evidence_file, [&evidence_bytes[..], b"\n"].concat())
        .map_err(|e| format!("write {}: {e}", evidence_file.display()))?;

    Ok(ReportWitnessProof {
        name: name.to_string(),
        proof_cid: proof.cid,
        proof_file,
        witness_cid,
        evidence_cid: evidence_root_cid,
        evidence_file,
    })
}

fn prepare_witness(source: WitnessSource) -> Result<PreparedWitness, String> {
    match source {
        WitnessSource::Report(source) => {
            let summary = json!({
                "totalCallsites": source.report.get("totalCallsites").cloned().unwrap_or(Json::Null),
                "discharged": source.report.get("discharged").cloned().unwrap_or(Json::Null),
                "violations": source.report.get("violations").cloned().unwrap_or(Json::Null),
                "refused": source.report.get("refused").cloned().unwrap_or(Json::Null),
                "loadErrors": source
                    .report
                    .get("loadErrors")
                    .and_then(Json::as_array)
                    .map(|a| a.len())
                    .unwrap_or(0),
            });
            let report_cid = jcs_cid(&source.report);
            let replay_pins_cid = jcs_cid(&source.replay_pins);
            let evidence = json!({
                "kind": "sugar-prove-report-evidence",
                "schemaVersion": "1",
                "reportCid": report_cid,
                "replayPinsCid": replay_pins_cid,
                "report": source.report,
                "replayPins": source.replay_pins,
            });
            let claim_body = json!({
                "kind": "sugar-prove-report-witness",
                "schemaVersion": "1",
                "reportCid": report_cid,
                "replayPinsCid": replay_pins_cid,
                "project": source.project_root.display().to_string(),
                "summary": summary,
            });
            Ok(PreparedWitness {
                name: "prove-report".to_string(),
                claim_kind: WitnessClaimKind::new("sugar-prove-report-witness")?,
                claim_body,
                evidence,
            })
        }
        WitnessSource::Command(source) => {
            let claim_body = json!({
                "kind": "sugar-command-witness",
                "schemaVersion": "1",
                "name": &source.name,
                "command": &source.command,
                "project": source.project_root.display().to_string(),
            });
            Ok(PreparedWitness {
                name: source.name,
                claim_kind: WitnessClaimKind::new("sugar-command-witness")?,
                claim_body,
                evidence: source.evidence,
            })
        }
        WitnessSource::File(source) => {
            let claim_body = json!({
                "kind": "sugar-file-witness",
                "schemaVersion": "1",
                "name": &source.name,
                "path": &source.path,
                "project": source.project_root.display().to_string(),
            });
            Ok(PreparedWitness {
                name: source.name,
                claim_kind: WitnessClaimKind::new("sugar-file-witness")?,
                claim_body,
                evidence: source.evidence,
            })
        }
        WitnessSource::JsonClaim(source) => Ok(PreparedWitness {
            name: source.name,
            claim_kind: source.claim_kind,
            claim_body: source.claim_body,
            evidence: source.evidence,
        }),
    }
}

fn checked_witness_name(name: impl Into<String>) -> Result<String, String> {
    let name = name.into();
    let trimmed = name.trim();
    if trimmed.is_empty() {
        return Err(witness_seam_refusal(
            "empty witness name",
            "witness name was empty before witness minting",
            "construct WitnessSource with a non-empty configured witness name",
        ));
    }
    Ok(trimmed.to_string())
}

fn witness_seam_refusal(crime: &str, illegal_shape: &str, replacement: &str) -> String {
    format!(
        "crime: {crime}; owner: sugar-cli::report_witness; illegal shape: {illegal_shape}; replacement: {replacement}"
    )
}

fn parse_memento_cid(context: &str, value: &str) -> Result<MementoCid, String> {
    MementoCid::try_parse(value.to_string()).map_err(|raw| {
        witness_seam_refusal(
            "invalid witness replay CID",
            &format!("{context} must be a blake3-512 CID with 128 hex characters, got `{raw}`"),
            "construct WitnessBundle inputs from valid blake3-512 CID strings before minting",
        )
    })
}

fn collect_cid_strings(value: &Json) -> Result<BTreeSet<String>, String> {
    let mut out = BTreeSet::new();
    collect_cid_strings_inner("$", value, &mut out)?;
    Ok(out)
}

fn collect_cid_strings_inner(
    path: &str,
    value: &Json,
    out: &mut BTreeSet<String>,
) -> Result<(), String> {
    match value {
        Json::String(s) if s.strip_prefix("blake3-512:").is_some() => {
            out.insert(parse_memento_cid(path, s)?.to_string());
        }
        Json::Array(items) => {
            for (idx, item) in items.iter().enumerate() {
                collect_cid_strings_inner(&format!("{path}[{idx}]"), item, out)?;
            }
        }
        Json::Object(obj) => {
            for (key, value) in obj {
                collect_cid_strings_inner(&format!("{path}.{key}"), value, out)?;
            }
        }
        _ => {}
    }
    Ok(())
}

fn jcs_cid(value: &Json) -> String {
    let canonical = json_to_cvalue(value);
    blake3_512_of(encode_jcs(canonical.as_ref()).as_bytes())
}

fn deterministic_signer_seed(principal: &str) -> Ed25519Seed {
    let digest = blake3_512_of(format!("sugar-signer:{principal}").as_bytes());
    let hex = digest.trim_start_matches("blake3-512:");
    let mut seed = [0u8; 32];
    for i in 0..32 {
        seed[i] = u8::from_str_radix(&hex[i * 2..i * 2 + 2], 16).unwrap_or(0);
    }
    seed
}

fn sanitize_filename(name: &str) -> String {
    name.chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '-'
            }
        })
        .collect()
}

fn json_to_cvalue(j: &Json) -> Arc<CValue> {
    match j {
        Json::Null => CValue::null(),
        Json::Bool(b) => CValue::boolean(*b),
        Json::Number(n) => {
            if let Some(i) = n.as_i64() {
                CValue::integer(i128::from(i))
            } else if let Some(u) = n.as_u64() {
                CValue::integer(i128::from(u))
            } else {
                CValue::string(n.to_string())
            }
        }
        Json::String(s) => CValue::string(s.clone()),
        Json::Array(items) => CValue::array(items.iter().map(json_to_cvalue).collect()),
        Json::Object(obj) => CValue::object(
            obj.iter()
                .map(|(k, v)| (k.clone(), json_to_cvalue(v)))
                .collect::<Vec<_>>(),
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valid_cid(fill: char) -> String {
        format!("blake3-512:{}", fill.to_string().repeat(128))
    }

    fn report_bundle(project_root: &Path, report: &Json, replay_pins: &Json) -> WitnessBundle {
        WitnessBundle::from_source(
            WitnessSource::report(project_root, report.clone(), replay_pins.clone()),
            WitnessMintOptions::default(),
        )
        .expect("report source becomes bundle")
    }

    fn mint_report_for_test(
        project_root: &Path,
        report: &Json,
        replay_pins: &Json,
        out_dir: &Path,
    ) -> Result<ReportWitnessProof, String> {
        mint_witness_bundle(report_bundle(project_root, report, replay_pins), out_dir)
    }

    fn mint_json_for_test(
        name: &str,
        claim_kind: &str,
        claim_body: &Json,
        evidence: &Json,
        out_dir: &Path,
        options: WitnessMintOptions,
    ) -> Result<ReportWitnessProof, String> {
        let source = WitnessSource::json_claim(
            name,
            WitnessClaimKind::new(claim_kind)?,
            claim_body.clone(),
            evidence.clone(),
        )?;
        mint_witness_bundle(WitnessBundle::from_source(source, options)?, out_dir)
    }

    #[test]
    fn witness_bundle_preserves_independent_cids_sidecar_and_signature() {
        let temp = tempfile::tempdir().expect("tempdir");
        let report = json!({
            "totalCallsites": 0,
            "discharged": 1,
            "violations": 0,
            "refused": 0,
            "rows": [{
                "propertyCid": valid_cid('a'),
                "verification": {
                    "kind": "consistency",
                    "linkedPosts": [{
                        "targetProofCid": valid_cid('b')
                    }]
                }
            }],
            "loadErrors": []
        });
        let replay_pins = json!({
            "kind": "sugar-prove-replay-pins",
            "schemaVersion": "1",
            "solvers": []
        });
        let bundle = WitnessBundle::from_source(
            WitnessSource::report(Path::new("/tmp/project"), report, replay_pins),
            WitnessMintOptions::default(),
        )
        .expect("report source becomes a typed witness bundle");

        let minted = mint_witness_bundle(bundle, temp.path()).expect("typed bundle minted");
        let witness_body: Json = serde_json::from_slice(
            &std::fs::read(&minted.evidence_file).expect("read evidence sidecar"),
        )
        .expect("parse evidence sidecar");
        let claim_cid = witness_body
            .pointer("/claimBodyCid")
            .and_then(Json::as_str)
            .expect("claim body CID");
        let evidence_cid = witness_body
            .pointer("/evidenceRootCid")
            .and_then(Json::as_str)
            .expect("evidence root CID");
        assert_ne!(
            claim_cid, evidence_cid,
            "claim and evidence must remain independently addressed"
        );
        assert_eq!(
            jcs_cid(&witness_body),
            minted.witness_cid,
            "the external sidecar bytes must remain witness-CID addressed"
        );
        assert_eq!(
            witness_body.get("claimBody").map(jcs_cid).as_deref(),
            Some(claim_cid),
            "claimBodyCid must address claimBody independently"
        );
        assert_eq!(
            witness_body.get("evidence").map(jcs_cid).as_deref(),
            Some(evidence_cid),
            "evidenceRootCid must address evidence independently"
        );

        let proof_bytes = std::fs::read(&minted.proof_file).expect("read witness proof");
        let graph = ProofGraph::read(&proof_bytes).expect("decode proof");
        let view = graph.members_view().next().expect("member view");
        let envelope: Json = serde_json::from_slice(view.bytes()).expect("member JSON");
        let input_cids = envelope
            .pointer("/body/inputCids")
            .and_then(Json::as_array)
            .expect("input CIDs");
        assert!(
            input_cids.iter().any(|cid| cid.as_str() == Some(claim_cid))
                && input_cids
                    .iter()
                    .any(|cid| cid.as_str() == Some(evidence_cid)),
            "claimBodyCid and evidenceRootCid must both be replay inputs: {envelope:#}"
        );
        let signer = view.field("signer").expect("signer field");
        let signature = view.field("signature").expect("signature field");
        let signature =
            sugar_proof_envelope::Signature::try_parse(signature).expect("signature parses");
        assert!(
            sugar_proof_envelope::ed25519_verify_string(
                &signer,
                &signature,
                minted.witness_cid.as_bytes()
            ),
            "signature must cover the witness CID"
        );
    }

    #[test]
    fn toolchain_scope_requires_plan_cid_before_minting() {
        let err = WitnessToolchainScope::try_new(None, vec![valid_cid('d')])
            .expect_err("actual outputs must be scoped to a plan");

        assert!(
            err.contains("crime:")
                && err.contains("owner: sugar-cli::report_witness")
                && err.contains("actualOutputCids")
                && err.contains("planCid")
                && err.contains("WitnessToolchainScope"),
            "refusal must name crime/owner/illegal shape/replacement: {err}"
        );
    }

    #[test]
    fn typed_toolchain_scope_lowers_to_pointer_and_sidecar() {
        let temp = tempfile::tempdir().expect("tempdir");
        let plan_cid = valid_cid('c');
        let output_cid = valid_cid('d');
        let scope =
            WitnessToolchainScope::try_new(Some(plan_cid.clone()), vec![output_cid.clone()])
                .expect("plan-scoped outputs are legal");
        let options = WitnessMintOptions {
            toolchain_scope: scope,
            produced_by: Some("sugar-witness:test".to_string()),
            produced_at: Some("2026-07-02T00:00:00.000Z".to_string()),
            ..WitnessMintOptions::default()
        };
        let bundle = WitnessBundle::from_source(
            WitnessSource::json_claim(
                "toolchain",
                WitnessClaimKind::new("toolchain-run").expect("claim kind"),
                json!({"kind": "toolchain-run"}),
                json!({"kind": "toolchain-evidence"}),
            )
            .expect("json claim source"),
            options,
        )
        .expect("json claim source becomes a typed bundle");

        let minted = mint_witness_bundle(bundle, temp.path()).expect("toolchain witness minted");
        let proof_bytes = std::fs::read(&minted.proof_file).expect("read witness proof");
        let graph = ProofGraph::read(&proof_bytes).expect("decode proof");
        let view = graph.members_view().next().expect("member view");
        let envelope: Json = serde_json::from_slice(view.bytes()).expect("member JSON");

        assert_eq!(view.field("planCid").as_deref(), Some(plan_cid.as_str()));
        assert_eq!(
            envelope
                .pointer("/body/actualOutputCids/0")
                .and_then(Json::as_str),
            Some(output_cid.as_str())
        );

        let body: Json = serde_json::from_slice(
            &std::fs::read(&minted.evidence_file).expect("read witness body"),
        )
        .expect("parse witness body");
        assert_eq!(
            body.pointer("/planCid").and_then(Json::as_str),
            Some(plan_cid.as_str())
        );
        assert_eq!(
            body.pointer("/actualOutputCids/0").and_then(Json::as_str),
            Some(output_cid.as_str())
        );
    }

    #[test]
    fn prove_report_mints_witness_proof_bundle() {
        let temp = tempfile::tempdir().expect("tempdir");
        let report = json!({
            "totalCallsites": 0,
            "discharged": 1,
            "violations": 0,
            "refused": 0,
            "rows": [{
                "propertyCid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "verification": {
                    "kind": "consistency",
                    "linkedPosts": [{
                        "targetProofCid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                    }]
                }
            }],
            "loadErrors": []
        });

        let replay_pins = json!({
            "kind": "sugar-prove-replay-pins",
            "schemaVersion": "1",
            "solvers": []
        });
        let minted = mint_report_for_test(
            Path::new("/tmp/project"),
            &report,
            &replay_pins,
            temp.path(),
        )
        .expect("report witness minted");

        assert!(minted.proof_cid.starts_with("blake3-512:"));
        assert!(minted.witness_cid.starts_with("blake3-512:"));
        assert!(minted.evidence_cid.starts_with("blake3-512:"));
        assert!(minted.proof_file.exists());
        assert!(minted.evidence_file.exists());
    }

    #[test]
    fn json_witness_refuses_bad_prefix_extra_input_cid() {
        let temp = tempfile::tempdir().expect("tempdir");
        let options = WitnessMintOptions::default()
            .with_extra_input_cids(vec!["sha512:not-a-sugar-cid".to_string()])
            .expect_err("bad extra input CID prefix must refuse");

        assert!(
            options.contains("extraInputCids") && options.contains("sha512:not-a-sugar-cid"),
            "unexpected error: {options}"
        );

        let err = mint_json_for_test(
            "toolchain",
            "toolchain-run",
            &json!({"kind": "toolchain-run"}),
            &json!({"kind": "toolchain-evidence"}),
            temp.path(),
            WitnessMintOptions::default(),
        )
        .expect("base typed witness still mints after typed CID refusal is tested");
        assert!(err.proof_cid.starts_with("blake3-512:"));
    }

    #[test]
    fn json_witness_refuses_bad_hex_nested_cid() {
        let temp = tempfile::tempdir().expect("tempdir");
        let bad = format!("blake3-512:{}g", "a".repeat(127));
        let err = mint_json_for_test(
            "toolchain",
            "toolchain-run",
            &json!({"kind": "toolchain-run", "subjectCid": bad}),
            &json!({"kind": "toolchain-evidence"}),
            temp.path(),
            WitnessMintOptions::default(),
        )
        .expect_err("bad nested Sugar CID hex must refuse");

        assert!(
            err.contains("subjectCid") && err.contains("blake3-512:"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn prove_report_witness_proof_contains_pointer_not_body() {
        let temp = tempfile::tempdir().expect("tempdir");
        let report = json!({
            "totalCallsites": 0,
            "discharged": 1,
            "violations": 0,
            "refused": 0,
            "rows": [],
            "loadErrors": []
        });
        let replay_pins = json!({
            "kind": "sugar-prove-replay-pins",
            "schemaVersion": "1",
            "solvers": []
        });
        let minted = mint_report_for_test(
            Path::new("/tmp/project"),
            &report,
            &replay_pins,
            temp.path(),
        )
        .expect("report witness minted");

        let proof_bytes = std::fs::read(&minted.proof_file).expect("read witness proof");
        let graph = ProofGraph::read(&proof_bytes).expect("decode proof");
        assert_eq!(graph.members_view().count(), 1);
        let view = graph.members_view().next().expect("member view");
        let envelope: Json = serde_json::from_slice(view.bytes()).expect("member JSON");

        assert_eq!(
            view.kind(),
            Some(sugar_proof_envelope::MemberKind::WitnessMemento)
        );
        assert_eq!(
            view.field("witnessCid").as_deref(),
            Some(minted.witness_cid.as_str())
        );
        assert_eq!(
            view.field("evidenceRootCid").as_deref(),
            Some(minted.evidence_cid.as_str())
        );
        assert!(
            envelope.pointer("/metadata/evidence").is_none()
                && envelope.pointer("/metadata/claimBody").is_none()
                && envelope.pointer("/body/evidence").is_none()
                && envelope.pointer("/body/report").is_none(),
            "witness proof must carry only the structured pointer, not the witness body: {envelope:#}"
        );
    }

    #[test]
    fn toolchain_output_witness_requires_plan_cid() {
        let temp = tempfile::tempdir().expect("tempdir");
        let err = WitnessToolchainScope::try_new(None, vec![valid_cid('a')])
            .expect_err("toolchain output witnesses must be scoped to a plan");
        assert!(err.contains("planCid"), "{err}");

        let minted = mint_json_for_test(
            "toolchain",
            "toolchain-run",
            &json!({"kind": "toolchain-run"}),
            &json!({"kind": "toolchain-evidence"}),
            temp.path(),
            WitnessMintOptions::default(),
        )
        .expect("unscoped witness with no actual outputs still mints");
        assert!(minted.proof_cid.starts_with("blake3-512:"));
    }

    #[test]
    fn toolchain_output_witness_carries_plan_scope_in_pointer_and_body() {
        let temp = tempfile::tempdir().expect("tempdir");
        let plan_cid = valid_cid('c');
        let output_cid = valid_cid('d');
        let scope =
            WitnessToolchainScope::try_new(Some(plan_cid.clone()), vec![output_cid.clone()])
                .expect("toolchain scope");
        let minted = mint_json_for_test(
            "toolchain",
            "toolchain-run",
            &json!({"kind": "toolchain-run"}),
            &json!({"kind": "toolchain-evidence"}),
            temp.path(),
            WitnessMintOptions::default().with_toolchain_scope(scope),
        )
        .expect("toolchain witness minted");

        let proof_bytes = std::fs::read(&minted.proof_file).expect("read witness proof");
        let graph = ProofGraph::read(&proof_bytes).expect("decode proof");
        let view = graph.members_view().next().expect("member view");
        let envelope: Json = serde_json::from_slice(view.bytes()).expect("member JSON");

        assert_eq!(view.field("planCid").as_deref(), Some(plan_cid.as_str()));
        assert_eq!(
            envelope
                .pointer("/body/actualOutputCids/0")
                .and_then(Json::as_str),
            Some(output_cid.as_str())
        );

        let body: Json = serde_json::from_slice(
            &std::fs::read(&minted.evidence_file).expect("read witness body"),
        )
        .expect("parse witness body");
        assert_eq!(
            body.pointer("/planCid").and_then(Json::as_str),
            Some(plan_cid.as_str())
        );
        assert_eq!(
            body.pointer("/actualOutputCids/0").and_then(Json::as_str),
            Some(output_cid.as_str())
        );
    }
}
