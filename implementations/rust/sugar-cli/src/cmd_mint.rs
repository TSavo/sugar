// SPDX-License-Identifier: Apache-2.0
//
// `sugar mint`: the lift-plugin protocol dispatcher.
//
// Architecture (substrate-as-only-mint-pipeline):
//
//   One Rust CLI; N language kits. The CLI is the sole mint pipeline for
//   every kit: including the rust kit itself. Rust is NOT special-cased.
//   Every kit exposes a lifter binary that speaks the lift-protocol RPC
//   (`initialize` + `lift`). The CLI drives that RPC, receives a
//   `proof-envelope` response, and then:
//
//     1. Writes the `.proof` file to the output directory.
//
//   The lift protocol (`initialize` + `lift`) is distinct from the LSP
//   parse protocol (`initialize` + `parse`). The former is for mint; the
//   latter is for editor diagnostics. This dispatcher calls the lifter,
//   NOT the LSP.
//
// Spec: protocol/specs/2026-04-30-lift-plugin-protocol.md (draft for v1.2.0).
//       protocol/specs/2026-05-02-bundle-attestation-protocol.md
//       spec #94 §2 (contractSetCid in signed body)
//
// Response shapes: `proof-envelope` and `ir-document` are supported in v1.
// Shape (b) `signed-mementos` is spec'd but unimplemented; adding it is
// additive, requires no client breakage.
//
// Missing-lifter behavior: when a manifest declares a binary that does
// not exist yet (ENOENT on spawn), mint produces a well-formed
// attestation with contractSetCid = EMPTY_SET_CID (the BLAKE3-512 of
// JCS(`[]`)). This surfaces the gap at the per-kit lifter level without
// failing the substrate pipeline. Any other spawn failure (wrong
// permissions, exit > 0) is a hard error.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use base64::Engine;
use clap::Parser;
use owo_colors::OwoColorize;
use serde_json::{json, Value};
use tracing::{debug, info, warn};

use libsugar::core::{
    address, Boundary, Cid, Dialect, Domain, DomainClaim, DomainKind, FunctionContractDomain,
    HashMapInputCatalog, Input, InputCatalog, Kit, KitError, Path as CorePath, PathAlgebra,
    PathDocument, Term, Verb, Verdict,
};
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};
use sugar_claim_envelope::{
    body_discharge_policy_from_fields, compute_contract_set_cid, contract_cid, mint_authority,
    mint_bridge, mint_contract_with_body_cid, mint_implication, Authoring,
    BodyDischargePolicyWarning, BridgeCallsite, MintAuthorityArgs, MintBridgeArgs,
    MintContractArgs, MintImplicationArgs,
};
use sugar_ir_types::Sort;
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, proof_filename, AssertionSurfaceMemento,
    AtomMemento, AuthorityMemento, AuthorityMementoRef, BridgeMemento, ClaimContractMemento,
    ContractBody, ContractMementoRef, Ed25519Seed, FactoryWalkMemento, FlatAtom,
    ImplicationMemento, LibrarySugarBindingMemento, PlanMemento, ProofEnvelopeInput, ProofGraph,
    SourceMemento, WitnessMemento,
};

use crate::lift_plugin::{self, LiftPluginError, LiftPluginOptions};
use crate::project_config::{
    read_project_config, read_user_config, KitAliasEntry, PluginEntry, ProjectConfig,
};
use crate::OutputFlags;
use crate::{EXIT_OK, EXIT_USER_ERROR, EXIT_VERIFY_FAIL};

// ---------------------------------------------------------------------------
// Foundation signing constants
// ---------------------------------------------------------------------------

fn log_body_discharge_policy_warnings(
    context: &str,
    contract: &str,
    warnings: &[BodyDischargePolicyWarning],
) {
    for warning in warnings {
        match warning {
            BodyDischargePolicyWarning::Disagreement {
                legacy_eligible,
                legacy_reason,
                policy_eligible,
                policy_reason,
            } => warn!(
                context = %context,
                contract = %contract,
                legacy_eligible = *legacy_eligible,
                legacy_reason = ?legacy_reason,
                policy_eligible = *policy_eligible,
                policy_reason = ?policy_reason,
                "body-discharge-disagreement: dischargePolicy/bodyDischarge* disagree; using legacy bodyDischarge*"
            ),
            BodyDischargePolicyWarning::Malformed { reason } => warn!(
                context = %context,
                contract = %contract,
                reason = %reason,
                "body-discharge-malformed: ignoring malformed dischargePolicy"
            ),
        }
    }
}

/// Publicly-known dev signer seed. Makes `.proof` CIDs reproducible across
/// machines; it is NOT an authenticity claim (the seed is a public constant).
const DEV_SIGNER_SEED: Ed25519Seed = [0x42u8; 32];

fn json_type_name(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "boolean",
        Value::Number(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}

/// Result of resolving a project/user configured `--kit=<alias>`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct KitResolution {
    pub(crate) project_root: PathBuf,
    pub(crate) surface: String,
    pub(crate) lang_key: String,
}

/// Resolve `--kit=<name>` from project/user config. There is no built-in
/// kit catalog: a shortcut only exists when `[[kits]]` declares it.
pub(crate) fn resolve_kit(kit: &str) -> Option<(PathBuf, String, String)> {
    let config_root = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let project_cfg = read_project_config(&config_root);
    let user_cfg = read_user_config();
    resolve_kit_from_configs(kit, &config_root, &project_cfg, &user_cfg)
        .map(|resolved| (resolved.project_root, resolved.surface, resolved.lang_key))
}

pub(crate) fn resolve_kit_from_configs(
    kit: &str,
    config_root: &Path,
    project_cfg: &ProjectConfig,
    user_cfg: &ProjectConfig,
) -> Option<KitResolution> {
    project_cfg
        .kits
        .iter()
        .find(|entry| entry.alias == kit)
        .or_else(|| user_cfg.kits.iter().find(|entry| entry.alias == kit))
        .map(|entry| kit_resolution_from_entry(config_root, entry))
}

pub(crate) fn configured_kit_alias_names() -> Vec<String> {
    let config_root = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let project_cfg = read_project_config(&config_root);
    let user_cfg = read_user_config();
    configured_kit_alias_names_from_configs(&project_cfg, &user_cfg)
}

pub(crate) fn configured_kit_alias_names_from_configs(
    project_cfg: &ProjectConfig,
    user_cfg: &ProjectConfig,
) -> Vec<String> {
    let mut names = Vec::new();
    for entry in project_cfg.kits.iter().chain(user_cfg.kits.iter()) {
        if !names.iter().any(|name| name == &entry.alias) {
            names.push(entry.alias.clone());
        }
    }
    names
}

pub(crate) fn format_unknown_kit_error(kit: &str, aliases: &[String]) -> String {
    if aliases.is_empty() {
        format!(
            "{}: unknown kit `{}`; no kit aliases configured in .sugar/config.toml or user config",
            "error".red().bold(),
            kit
        )
    } else {
        format!(
            "{}: unknown kit `{}`; configured kit aliases: {}",
            "error".red().bold(),
            kit,
            aliases.join(", ")
        )
    }
}

fn kit_resolution_from_entry(config_root: &Path, entry: &KitAliasEntry) -> KitResolution {
    let configured_project = PathBuf::from(&entry.project);
    let project_root = if configured_project.is_absolute() {
        configured_project
    } else {
        config_root.join(configured_project)
    };

    KitResolution {
        project_root,
        surface: entry.surface.clone(),
        lang_key: entry.lang.clone(),
    }
}

/// Result of a successful mint transform.
#[derive(Debug, Clone)]
struct DispatchResult {
    filename_cid: String,
    contract_set_cid: String,
    bytes_written: usize,
    proof_file: Option<PathBuf>,
    lift_result: Value,
}

/// One per-plugin response collected during multi-plugin dispatch. The
/// `surface` is carried for diagnostics; the `response` is the raw
/// JSON-RPC result the plugin returned (either `kind: "ir-document"` or
/// `kind: "proof-envelope"` per the lift-plugin protocol).
#[derive(Debug, Clone)]
struct PerPluginDispatch {
    surface: String,
    response: Value,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
struct OracleObservation {
    requested: bool,
    reachable: bool,
    ready: bool,
    attempted: u64,
    resolved: u64,
}

#[derive(Debug, Clone)]
struct PreparedLiftStep {
    surface: String,
    lift_request: Value,
}

#[derive(Debug, Clone)]
struct MintedIrDocument {
    bytes: Vec<u8>,
    filename_cid: String,
    contract_set_cid: String,
    contract_bindings: Vec<Value>,
}

/// Merge N per-plugin lift responses into one canonical `kind:
/// "ir-document"` value. The union concatenates each plugin's `ir`
/// array; diagnostics likewise. Every plugin in a multi-plugin path
/// MUST emit `kind: "ir-document"` — proof-envelope responses are
/// already self-signed bundles and can't be folded into a fresh mint.
/// The substrate-honest failure is to reject the mix loudly.
///
/// Cross-plugin name collisions are deduplicated by name. With
/// content-addressed names (CID-suffixed by each plugin's lifter),
/// a name collision means byte-identical canonical IR, which is
/// safe to dedup — same identity, same content, same minted memento
/// downstream. The same primitive `mint_proof` uses internally.
/// Shape-invariant dedup key for an IR-document entry: the BLAKE3-512 of its
/// canonical (JCS) content. Two entries collapse iff their CONTENT is identical
/// -- never merely because they share a `name`. This is the addressing rule of
/// the whole system: identity is the CID of the shape, names are sugar. Using
/// the canonical bytes (key-sorted, encoding-normalized) makes the key stable
/// across surfaces that may serialize the same shape with different key order.
fn canonical_dedup_key(item: &Value) -> String {
    canonical_json_cid(item)
}

fn canonical_json_cid(item: &Value) -> String {
    let cvalue = json_to_cvalue(item);
    blake3_512_of(encode_jcs(cvalue.as_ref()).as_bytes())
}

fn merge_ir_document_responses(per_plugin: Vec<PerPluginDispatch>) -> Result<Value, String> {
    let mut merged_ir: Vec<Value> = Vec::new();
    let mut merged_diagnostics: Vec<Value> = Vec::new();
    let mut merged_implications: Vec<Value> = Vec::new();
    let mut merged_authorities: Vec<Value> = Vec::new();
    let mut merged_witnesses: Vec<Value> = Vec::new();
    let mut merged_source_mementos: Vec<Value> = Vec::new();
    let mut saw_source_mementos = false;
    let mut merged_plan_mementos: Vec<Value> = Vec::new();
    let mut saw_source_ledger = false;
    let mut merged_source_ledger: BTreeMap<String, i64> = BTreeMap::new();
    let mut saw_source_audits = false;
    let mut merged_source_audits: Vec<Value> = Vec::new();
    let mut saw_factory_audits = false;
    let mut merged_factory_audits: Vec<Value> = Vec::new();
    let mut saw_assertion_surface_audits = false;
    let mut merged_assertion_surface_audits: Vec<Value> = Vec::new();
    let mut saw_call_edges = false;
    let mut merged_call_edges: Vec<Value> = Vec::new();
    let mut saw_vendor_conjoins = false;
    let mut merged_vendor_conjoins: Vec<Value> = Vec::new();
    let mut merged_factory_summary = MergedFactoryAuditSummary::default();
    let mut oracle_observation = OracleObservation::default();
    // Content-shape dedup keys (NOT names). See `canonical_dedup_key`.
    let mut seen_content: std::collections::HashSet<String> = std::collections::HashSet::new();
    let mut seen_implications: std::collections::HashSet<String> = std::collections::HashSet::new();
    let mut seen_authorities: std::collections::HashSet<String> = std::collections::HashSet::new();
    for entry in per_plugin {
        assert_oracle_ready_if_requested(&entry.surface, &entry.response)?;
        let plugin_oracle = oracle_observation_from_lift(&entry.response);
        oracle_observation.requested |= plugin_oracle.requested;
        oracle_observation.reachable |= plugin_oracle.reachable;
        oracle_observation.ready |= plugin_oracle.ready;
        oracle_observation.attempted += plugin_oracle.attempted;
        oracle_observation.resolved += plugin_oracle.resolved;

        let kind = entry
            .response
            .get("kind")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if kind != "ir-document" {
            return Err(format!(
                "multi-plugin mint requires every lift plugin to emit `kind: \"ir-document\"`; \
                 plugin for surface `{}` emitted `kind: \"{}\"`",
                entry.surface, kind
            ));
        }
        if let Some(arr) = entry.response.get("ir").and_then(|v| v.as_array()) {
            for item in arr {
                // Dedup by CONTENT, never by `name`. Names are sugar: a
                // contract's identity is its SHAPE, addressed by CID. Two
                // surfaces can legitimately emit two DIFFERENT-shaped contracts
                // that happen to share a name -- the rust-bind sugar binding
                // emits a POST-ONLY `option_unwrap`, while rust-fn-contracts
                // emits a PRE-BEARING `option_unwrap` (formals + `pre =
                // is_some(opt)`). Keying dedup on `name` dropped the
                // pre-bearing one and silently published the post-only shell,
                // which then vacuous-passed every `unwrap` panic obligation (a
                // false "cannot panic"). Dedup on the canonical content bytes:
                // byte-identical entries across surfaces collapse (the real
                // intent), but distinct shapes both survive regardless of name.
                let dedup_key = canonical_dedup_key(item);
                if seen_content.insert(dedup_key) {
                    merged_ir.push(item.clone());
                }
            }
        }
        if let Some(arr) = entry.response.get("diagnostics").and_then(|v| v.as_array()) {
            merged_diagnostics.extend(arr.iter().cloned());
        }
        if let Some(arr) = entry
            .response
            .get("implications")
            .and_then(|v| v.as_array())
        {
            for item in arr {
                let key = item
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                if key.is_empty() || seen_implications.insert(key) {
                    merged_implications.push(item.clone());
                }
            }
        }
        if let Some(arr) = entry.response.get("authorities").and_then(|v| v.as_array()) {
            for item in arr {
                let key = item
                    .get("id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                if key.is_empty() || seen_authorities.insert(key) {
                    merged_authorities.push(item.clone());
                }
            }
        }
        if let Some(arr) = entry.response.get("witnesses").and_then(|v| v.as_array()) {
            merged_witnesses.extend(arr.iter().cloned());
        }
        if let Some(ledger) = entry
            .response
            .get("sourceLedger")
            .and_then(Value::as_object)
        {
            saw_source_ledger = true;
            merge_source_ledger(&mut merged_source_ledger, ledger);
        }
        if let Some(arr) = entry
            .response
            .get("sourceAudits")
            .or_else(|| entry.response.get("source_audits"))
            .and_then(Value::as_array)
        {
            saw_source_audits = true;
            merged_source_audits.extend(arr.iter().cloned());
        }
        if let Some(arr) = entry
            .response
            .get("factoryAudits")
            .or_else(|| entry.response.get("factory_audits"))
            .and_then(Value::as_array)
        {
            saw_factory_audits = true;
            merged_factory_audits.extend(arr.iter().cloned());
        }
        if let Some(arr) = entry
            .response
            .get("assertionSurfaceAudits")
            .or_else(|| entry.response.get("assertion_surface_audits"))
            .and_then(Value::as_array)
        {
            saw_assertion_surface_audits = true;
            merged_assertion_surface_audits.extend(arr.iter().cloned());
        }
        if let Some(arr) = entry
            .response
            .get("callEdges")
            .or_else(|| entry.response.get("call_edges"))
            .and_then(Value::as_array)
        {
            saw_call_edges = true;
            merged_call_edges.extend(arr.iter().cloned());
        }
        if let Some(arr) = entry
            .response
            .get("vendorConjoins")
            .or_else(|| entry.response.get("vendor_conjoins"))
            .or_else(|| entry.response.get("linkerConjoins"))
            .or_else(|| entry.response.get("linker_conjoins"))
            .and_then(Value::as_array)
        {
            saw_vendor_conjoins = true;
            merged_vendor_conjoins.extend(arr.iter().cloned());
        }
        merged_factory_summary.merge(entry.response.get("factoryAuditSummary"));
        if let Some(arr) = entry
            .response
            .get("sourceMementos")
            .or_else(|| entry.response.get("source_mementos"))
            .and_then(|v| v.as_array())
        {
            saw_source_mementos = true;
            merged_source_mementos.extend(arr.iter().cloned());
        }
        if let Some(arr) = entry
            .response
            .get("planMementos")
            .or_else(|| entry.response.get("plan_mementos"))
            .and_then(|v| v.as_array())
        {
            merged_plan_mementos.extend(arr.iter().cloned());
        }
    }
    let bridges_emitted = merged_ir
        .iter()
        .filter(|entry| entry.get("kind").and_then(|v| v.as_str()) == Some("bridge"))
        .count() as u64;
    let lift_gaps = merged_diagnostics
        .iter()
        .filter(|entry| entry.get("kind").and_then(|v| v.as_str()) == Some("lift-gap"))
        .count() as u64;
    let mut merged = json!({
        "kind": "ir-document",
        "ir": merged_ir,
        "diagnostics": merged_diagnostics,
        "bridges_emitted": bridges_emitted,
        "lift_gaps": lift_gaps,
        "oracle_requested": oracle_observation.requested,
        "oracle_reachable": oracle_observation.reachable,
        "oracle_ready": oracle_observation.ready,
        "receivers_attempted": oracle_observation.attempted,
        "receivers_resolved": oracle_observation.resolved,
    });
    if !merged_implications.is_empty() {
        merged["implications"] = Value::Array(merged_implications);
    }
    if !merged_authorities.is_empty() {
        merged["authorities"] = Value::Array(merged_authorities);
    }
    if !merged_witnesses.is_empty() {
        merged["witnesses"] = Value::Array(merged_witnesses);
    }
    if saw_source_ledger {
        merged["sourceLedger"] = Value::Object(source_ledger_object(merged_source_ledger));
    }
    if saw_source_audits {
        merged["sourceAudits"] = Value::Array(merged_source_audits);
    }
    if saw_factory_audits {
        merged["factoryAudits"] = Value::Array(merged_factory_audits);
    }
    if let Some(summary) = merged_factory_summary.into_value() {
        merged["factoryAuditSummary"] = summary;
    }
    if saw_assertion_surface_audits {
        merged["assertionSurfaceAudits"] = Value::Array(merged_assertion_surface_audits);
    }
    if saw_call_edges {
        merged["callEdges"] = Value::Array(merged_call_edges);
    }
    if saw_vendor_conjoins {
        merged["vendorConjoins"] = Value::Array(merged_vendor_conjoins);
    }
    if saw_source_mementos {
        merged["sourceMementos"] = Value::Array(merged_source_mementos);
    }
    if !merged_plan_mementos.is_empty() {
        merged["planMementos"] = Value::Array(merged_plan_mementos);
    }
    Ok(merged)
}

#[derive(Debug, Default)]
struct MergedFactoryAuditSummary {
    saw: bool,
    emitted_rows: i64,
    warranted: i64,
    refused: i64,
    support: i64,
    unresolved: i64,
    unresolved_sites: Vec<Value>,
    factory_walk: Vec<Value>,
}

impl MergedFactoryAuditSummary {
    fn merge(&mut self, summary: Option<&Value>) {
        let Some(summary) = summary else {
            return;
        };
        self.saw = true;
        self.emitted_rows += json_i64(summary.get("emittedRows"));
        if let Some(status_counts) = summary.get("statusCounts") {
            self.warranted += json_i64(status_counts.get("warranted"));
            self.refused += json_i64(status_counts.get("refused"));
            self.support += json_i64(status_counts.get("support"));
            self.unresolved += json_i64(status_counts.get("unresolved"));
        }
        if let Some(rows) = summary.get("unresolvedSites").and_then(Value::as_array) {
            self.unresolved_sites.extend(rows.iter().cloned());
        }
        if let Some(rows) = summary.get("factoryWalk").and_then(Value::as_array) {
            self.factory_walk.extend(rows.iter().cloned());
        }
    }

    fn into_value(self) -> Option<Value> {
        self.saw.then(|| {
            json!({
                "emittedRows": self.emitted_rows,
                "statusCounts": {
                    "warranted": self.warranted,
                    "refused": self.refused,
                    "support": self.support,
                    "unresolved": self.unresolved,
                },
                "unresolvedSites": self.unresolved_sites,
                "factoryWalk": self.factory_walk,
            })
        })
    }
}

fn json_i64(value: Option<&Value>) -> i64 {
    value
        .and_then(Value::as_i64)
        .or_else(|| value.and_then(Value::as_u64).map(|value| value as i64))
        .unwrap_or(0)
}

fn merge_source_ledger(
    merged: &mut BTreeMap<String, i64>,
    ledger: &serde_json::Map<String, Value>,
) {
    for key in [
        "source_loci",
        "source_warranted",
        "source_support",
        "source_refused",
        "source_inactive",
        "source_refuted",
        "unclassified_source",
    ] {
        *merged.entry(key.to_string()).or_default() += json_i64(ledger.get(key));
    }
    let unresolved = ledger
        .get("source_unresolved")
        .map(|value| json_i64(Some(value)))
        .unwrap_or_else(|| json_i64(ledger.get("unclassified_source")));
    *merged.entry("source_unresolved".to_string()).or_default() += unresolved;
}

fn source_ledger_object(merged: BTreeMap<String, i64>) -> serde_json::Map<String, Value> {
    let mut object = serde_json::Map::new();
    for key in [
        "source_loci",
        "source_warranted",
        "source_support",
        "source_refused",
        "source_inactive",
        "source_refuted",
        "source_unresolved",
        "unclassified_source",
    ] {
        object.insert(
            key.to_string(),
            Value::Number(serde_json::Number::from(
                merged.get(key).copied().unwrap_or(0),
            )),
        );
    }
    object
}

fn oracle_observation_from_lift(lift: &Value) -> OracleObservation {
    let nested = lift.get("oracle");
    OracleObservation {
        requested: nested
            .and_then(|v| v.get("requested"))
            .and_then(Value::as_bool)
            .or_else(|| lift.get("oracle_requested").and_then(Value::as_bool))
            .unwrap_or(false),
        reachable: nested
            .and_then(|v| v.get("reachable"))
            .and_then(Value::as_bool)
            .or_else(|| lift.get("oracle_reachable").and_then(Value::as_bool))
            .unwrap_or(false),
        ready: nested
            .and_then(|v| v.get("ready"))
            .and_then(Value::as_bool)
            .or_else(|| lift.get("oracle_ready").and_then(Value::as_bool))
            .unwrap_or(false),
        attempted: nested
            .and_then(|v| v.get("attempted"))
            .and_then(Value::as_u64)
            .or_else(|| lift.get("receivers_attempted").and_then(Value::as_u64))
            .unwrap_or(0),
        resolved: nested
            .and_then(|v| v.get("resolved"))
            .and_then(Value::as_u64)
            .or_else(|| lift.get("receivers_resolved").and_then(Value::as_u64))
            .unwrap_or(0),
    }
}

fn assert_oracle_ready_if_requested(surface: &str, lift: &Value) -> Result<(), String> {
    let oracle = oracle_observation_from_lift(lift);
    if oracle.requested && oracle.attempted > 0 && !oracle.ready {
        return Err(format!(
            "lift surface `{surface}` requested rust-analyzer oracle and found {} receiver query candidate(s), but sugar-linkerd did not report rust-analyzer ready; refusing to mint a syntactic-only proof",
            oracle.attempted
        ));
    }
    Ok(())
}

#[derive(Debug, Clone, Default)]
struct MintKit {
    inputs: HashMapInputCatalog,
}

#[derive(Debug, Clone)]
struct MintSession {
    claim: DomainClaim,
    result: DispatchResult,
    surface: String,
    out_dir: PathBuf,
}

#[derive(Debug, Clone)]
struct MintPathInput {
    input: Input,
    inputs: HashMapInputCatalog,
}

impl MintKit {
    fn new(inputs: HashMapInputCatalog) -> Self {
        Self { inputs }
    }

    fn path<'a>(&self, input: &'a Input) -> Result<&'a CorePath, KitError> {
        let Input::Path(path) = input else {
            return Err(KitError::UnsupportedInput {
                dialect: self.dialect(),
                message: "mint expects Input::Path containing the composed mint algebra"
                    .to_string(),
            });
        };
        Ok(path.as_ref())
    }

    fn transform_session(&self, input: &Input) -> Result<MintSession, KitError> {
        let path = self.path(input)?;
        let ordered_steps = path
            .ordered_steps()
            .map_err(|error| KitError::Transformation(error.to_string()))?;
        let mint_step = path
            .terminal_steps()
            .into_iter()
            .find(|step| step.name == "mint" || step.kit == "sugar-mint")
            .ok_or_else(|| {
                KitError::Transformation("mint path missing terminal `mint` step".to_string())
            })?;
        // Collect ALL lift-plugin predecessors of the mint step. The path
        // executor handles arbitrary dependency fan-in; the substrate's
        // multi-plugin orchestration is just N lift steps + 1 mint step,
        // with `depends_on` carrying the dependency structure. Each lift
        // step represents one `[[plugins]]` entry from config.toml.
        let lift_steps: Vec<&PathAlgebra> = ordered_steps
            .iter()
            .copied()
            .filter(|step| {
                mint_step.depends_on.iter().any(|name| name == &step.name)
                    && step.kit.starts_with("lift-plugin:")
            })
            .collect();
        if lift_steps.is_empty() {
            return Err(KitError::Transformation(
                "mint path terminal step must depend on at least one lift-plugin step".to_string(),
            ));
        }

        let mint_request = self.path_step_spec(mint_step, "mint path mint step")?;
        // The project root (where `.sugar/` lives) is the canonical
        // location for manifest discovery, regardless of any per-plugin
        // workspace_override. Read it from the mint_request so it stays
        // stable across all lift steps in the path.
        let project_root_for_manifests = PathBuf::from(
            required_str(&mint_request, "projectRoot", "mint path mint step")
                .map_err(KitError::Transformation)?,
        );
        let out_dir = PathBuf::from(
            required_str(&mint_request, "outDir", "mint path mint step")
                .map_err(KitError::Transformation)?,
        );
        let quiet = mint_request
            .get("options")
            .and_then(|options| options.get("quiet"))
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let toolchain_plan = mint_request.get("toolchainPlan").cloned();

        // Prepare lift steps, then phase them. Producer surfaces emit
        // contracts/sugars; consumer surfaces, such as rust-implications,
        // depend on the producers' minted contract CIDs and must run second.
        let mut producer_steps: Vec<PreparedLiftStep> = Vec::new();
        let mut consumer_steps: Vec<PreparedLiftStep> = Vec::new();
        let mut surface_for_session: Option<String> = None;
        for lift_step in &lift_steps {
            let lift_request = self.path_step_spec(lift_step, "mint path lift step")?;
            let surface = required_str(&lift_request, "surface", "mint path lift step")
                .map_err(KitError::Transformation)?
                .to_string();
            if surface_for_session.is_none() {
                surface_for_session = Some(surface.clone());
            }
            let prepared = PreparedLiftStep {
                surface,
                lift_request,
            };
            if lift_plugin::surface_phase(&project_root_for_manifests, &prepared.surface)
                == "consumer"
            {
                consumer_steps.push(prepared);
            } else {
                producer_steps.push(prepared);
            }
        }

        let mut per_plugin: Vec<PerPluginDispatch> = Vec::with_capacity(lift_steps.len());
        let mut producer_responses: Vec<PerPluginDispatch> =
            Vec::with_capacity(producer_steps.len());
        let mut combined_lift_claim: Option<DomainClaim> = None;

        for step in &producer_steps {
            let lift_options = lift_options_from_request(&step.lift_request, Vec::new());
            let session = match lift_plugin::dispatch_lift(
                &project_root_for_manifests,
                &step.surface,
                lift_options,
                quiet,
            ) {
                Ok(session) => session,
                Err(LiftPluginError::MissingBinary { binary }) => {
                    if !quiet {
                        println!(
                            "{}: lifter binary `{}` not found: producing empty-set attestation",
                            "warn".yellow().bold(),
                            binary
                        );
                    }
                    let empty_cid = compute_contract_set_cid(vec![]);
                    let result = DispatchResult {
                        filename_cid: String::new(),
                        contract_set_cid: empty_cid,
                        bytes_written: 0,
                        proof_file: None,
                        lift_result: json!({
                            "kind": "empty-set",
                            "reason": "lifter binary not found",
                            "binary": binary,
                        }),
                    };
                    let claim = mint_result_claim(input, None, &result)?;
                    return Ok(MintSession {
                        claim,
                        result,
                        surface: step.surface.clone(),
                        out_dir,
                    });
                }
                Err(LiftPluginError::Refused(refusal)) => {
                    return Err(KitError::Transformation(format!(
                        "{}: {}",
                        refusal.header.failure_kind, refusal.header.failure_detail
                    )))
                }
                Err(LiftPluginError::Failed(error)) => return Err(KitError::Transformation(error)),
            };

            let response = session.response().clone();
            assert_oracle_ready_if_requested(&step.surface, &response)
                .map_err(KitError::Transformation)?;
            // Carry forward the first plugin's lift_claim as the
            // session's lift claim. (Future: aggregate claims into a
            // composite — out of scope for the multi-plugin landing.)
            if combined_lift_claim.is_none() {
                combined_lift_claim = Some(session.claim);
            }
            let dispatched = PerPluginDispatch {
                surface: step.surface.clone(),
                response,
            };
            producer_responses.push(dispatched.clone());
            per_plugin.push(dispatched);
        }

        let contract_bindings = if consumer_steps.is_empty() {
            Vec::new()
        } else {
            let mut bindings = contract_bindings_from_producer_responses(
                &producer_responses,
                &project_root_for_manifests,
                &out_dir,
                quiet,
            )
            .map_err(KitError::Transformation)?;
            // Dependency-proof bridging, one level up the crate graph: harvest
            // contracts published by dependency proofs already in
            // `.sugar/imports/` (libsugar, the rust stdlib shim, ...) and
            // forward them alongside this crate's own producer contracts. The
            // implication lifter then emits a bridge for each cross-crate /
            // stdlib call site instead of leaving it a vacuous lift-gap.
            //
            // Precedence under (crate, leaf) matching: a dependency's `foo` and
            // this crate's `foo` are DISTINCT keys (different crate), so both
            // are forwarded and the implication lifter routes each call site to
            // the contract in the crate it actually resolved. The only true
            // duplicate is a dependency contract sharing BOTH library AND leaf
            // with a producer contract (e.g. vendoring this very crate's own
            // proof); drop just that, since it would key-collide. This is what
            // lets the 6 same-leaf-different-crate dependency contracts that the
            // bare-name filter used to drop be forwarded and bridged correctly.
            let intra_keys: std::collections::HashSet<(String, String)> = bindings
                .iter()
                .filter_map(|b| {
                    let name = b.get("name").and_then(|v| v.as_str())?.to_string();
                    let lib = b
                        .get("library")
                        .and_then(|v| v.as_str())
                        .unwrap_or_default()
                        .to_string();
                    Some((lib, name))
                })
                .collect();
            let dep_bindings =
                contract_bindings_from_dependency_proofs(&project_root_for_manifests);
            let dep_total = dep_bindings.len();
            debug!(
                dep_total = dep_total,
                intra_keys = intra_keys.len(),
                "mint: harvested dependency proof contracts"
            );
            let dep_kept: Vec<Value> = dep_bindings
                .into_iter()
                .filter(|b| {
                    let Some(name) = b.get("name").and_then(|v| v.as_str()).map(String::from)
                    else {
                        return false;
                    };
                    let lib = b
                        .get("library")
                        .and_then(|v| v.as_str())
                        .unwrap_or_default()
                        .to_string();
                    !intra_keys.contains(&(lib, name))
                })
                .collect();
            let dep_dropped = dep_total - dep_kept.len();
            info!(
                dep_forwarded = dep_kept.len(),
                dep_dropped = dep_dropped,
                "mint: dependency contracts forwarded for cross-crate bridging"
            );
            if dep_dropped > 0 {
                debug!(
                    dep_dropped = dep_dropped,
                    "mint: dependency contracts dropped (same crate AND leaf as producer contract)"
                );
            }
            if !quiet && dep_total > 0 {
                println!(
                    "{}: {} dependency contract(s) forwarded for cross-crate bridging, {} dropped (same crate AND leaf as a producer contract)",
                    "deps".green().bold(),
                    dep_kept.len(),
                    dep_dropped
                );
            }
            bindings.extend(dep_kept);
            bindings
        };

        for step in &consumer_steps {
            let lift_options =
                lift_options_from_request(&step.lift_request, contract_bindings.clone());
            debug!(
                surface = %step.surface,
                contract_bindings = contract_bindings.len(),
                "mint: dispatching lift to surface"
            );
            let session = match lift_plugin::dispatch_lift(
                &project_root_for_manifests,
                &step.surface,
                lift_options,
                quiet,
            ) {
                Ok(session) => {
                    debug!(surface = %step.surface, "mint: lift dispatch succeeded");
                    session
                }
                Err(LiftPluginError::MissingBinary { binary }) => {
                    if !quiet {
                        println!(
                            "{}: lifter binary `{}` not found: producing empty-set attestation",
                            "warn".yellow().bold(),
                            binary
                        );
                    }
                    let empty_cid = compute_contract_set_cid(vec![]);
                    let result = DispatchResult {
                        filename_cid: String::new(),
                        contract_set_cid: empty_cid,
                        bytes_written: 0,
                        proof_file: None,
                        lift_result: json!({
                            "kind": "empty-set",
                            "reason": "lifter binary not found",
                            "binary": binary,
                        }),
                    };
                    let claim = mint_result_claim(input, None, &result)?;
                    return Ok(MintSession {
                        claim,
                        result,
                        surface: step.surface.clone(),
                        out_dir,
                    });
                }
                Err(LiftPluginError::Refused(refusal)) => {
                    return Err(KitError::Transformation(format!(
                        "{}: {}",
                        refusal.header.failure_kind, refusal.header.failure_detail
                    )))
                }
                Err(LiftPluginError::Failed(error)) => return Err(KitError::Transformation(error)),
            };

            let response = session.response().clone();
            assert_oracle_ready_if_requested(&step.surface, &response)
                .map_err(KitError::Transformation)?;
            if combined_lift_claim.is_none() {
                combined_lift_claim = Some(session.claim);
            }
            per_plugin.push(PerPluginDispatch {
                surface: step.surface.clone(),
                response,
            });
        }

        let plan_memento = toolchain_plan
            .map(|plan| finalize_toolchain_plan_memento(plan, &per_plugin))
            .transpose()
            .map_err(KitError::Transformation)?;
        let mut merged_lift_response = if per_plugin.len() == 1 {
            // Single-plugin path: pass the response through unchanged so
            // proof-envelope and ir-document both work as before.
            per_plugin.into_iter().next().unwrap().response
        } else {
            // Multi-plugin path: every plugin MUST emit `kind:
            // "ir-document"`. proof-envelope responses can't be merged
            // (they're already self-signed bundles); the substrate-honest
            // failure is to reject the mix loudly.
            merge_ir_document_responses(per_plugin).map_err(KitError::Transformation)?
        };
        if let Some(plan_memento) = plan_memento {
            if merged_lift_response
                .get("kind")
                .and_then(|value| value.as_str())
                == Some("ir-document")
            {
                let mut plan_mementos = merged_lift_response
                    .get("planMementos")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default();
                plan_mementos.push(plan_memento);
                merged_lift_response["planMementos"] = Value::Array(plan_mementos);
                debug!("mint: attached toolchain plan memento to ir-document");
            } else {
                warn!(
                    kind = merged_lift_response
                        .get("kind")
                        .and_then(|value| value.as_str())
                        .unwrap_or("<missing>"),
                    "mint: toolchain plan memento not attached to non-ir-document response"
                );
            }
        }
        let result = mint_lift_response(
            &project_root_for_manifests,
            &out_dir,
            quiet,
            merged_lift_response,
        )
        .map_err(KitError::Transformation)?;
        let claim = mint_result_claim(input, combined_lift_claim.as_ref(), &result)?;
        Ok(MintSession {
            claim,
            result,
            surface: surface_for_session.expect("invariant: at least one lift step dispatched"),
            out_dir,
        })
    }

    fn path_step_spec(&self, step: &PathAlgebra, context: &str) -> Result<Value, KitError> {
        let cid = step
            .inputs
            .first()
            .ok_or_else(|| KitError::UnsupportedInput {
                dialect: Dialect::Other(step.kit.clone()),
                message: format!("{context} must carry at least one input CID"),
            })?;
        match self.inputs.get_input(cid) {
            Some(Input::Spec(value)) => Ok(value.clone()),
            Some(_) => Err(KitError::UnsupportedInput {
                dialect: Dialect::Other(step.kit.clone()),
                message: format!("{context} input `{cid}` must resolve to Input::Spec"),
            }),
            None => Err(KitError::UnsupportedInput {
                dialect: Dialect::Other(step.kit.clone()),
                message: format!("{context} input `{cid}` is not materialized"),
            }),
        }
    }
}

fn lift_options_from_request(
    lift_request: &Value,
    contract_bindings: Vec<Value>,
) -> LiftPluginOptions {
    LiftPluginOptions {
        identify_only: lift_request
            .get("options")
            .and_then(|options| options.get("identifyOnly"))
            .and_then(Value::as_bool)
            .unwrap_or(false),
        library_bindings: lift_request
            .get("options")
            .and_then(|options| options.get("layer"))
            .and_then(Value::as_str)
            .is_some_and(|layer| layer == "library-bindings"),
        workspace_override: lift_request
            .get("options")
            .and_then(|options| options.get("workspaceOverride"))
            .and_then(Value::as_str)
            .map(|s| s.to_string()),
        emit: lift_request
            .get("options")
            .and_then(|options| options.get("emit"))
            .and_then(Value::as_str)
            .map(|s| s.to_string()),
        layer: lift_request
            .get("options")
            .and_then(|options| options.get("layer"))
            .and_then(Value::as_str)
            .map(|s| s.to_string()),
        report_summary: lift_request
            .get("options")
            .and_then(|options| options.get("reportSummary"))
            .and_then(Value::as_bool)
            .unwrap_or(false),
        contract_bindings,
    }
}

fn finalize_toolchain_plan_memento(
    mut plan: Value,
    outputs: &[PerPluginDispatch],
) -> Result<Value, String> {
    let obj = plan
        .as_object_mut()
        .ok_or_else(|| "`toolchainPlan` must be an object".to_string())?;
    obj.entry("kind".to_string())
        .or_insert_with(|| json!("component-plan"));
    if obj.get("kind").and_then(Value::as_str) != Some("component-plan") {
        return Err("`toolchainPlan.kind` must be `component-plan`".to_string());
    }
    obj.entry("schemaVersion".to_string())
        .or_insert_with(|| json!("1"));
    obj.remove("planCid");
    obj.remove("cid");

    let tool_outputs: Vec<Value> = outputs
        .iter()
        .map(|output| {
            let output_cid = canonical_json_cid(&output.response);
            json!({
                "surface": output.surface,
                "actualOutputCid": output_cid,
            })
        })
        .collect();
    let expected_output_cids: Vec<Value> = tool_outputs
        .iter()
        .filter_map(|output| output.get("actualOutputCid").and_then(Value::as_str))
        .map(|cid| json!(cid))
        .collect();
    obj.insert("toolOutputs".to_string(), Value::Array(tool_outputs));
    obj.insert(
        "expectedOutputCids".to_string(),
        Value::Array(expected_output_cids),
    );
    Ok(plan)
}

fn has_nontrivial_pre_json(pre: &Value) -> bool {
    if pre.is_null() {
        return false;
    }
    !(pre.get("kind").and_then(|v| v.as_str()) == Some("atomic")
        && pre.get("name").and_then(|v| v.as_str()) == Some("true"))
}

fn contract_bindings_from_producer_responses(
    producer_responses: &[PerPluginDispatch],
    project_root: &Path,
    out_dir: &Path,
    quiet: bool,
) -> Result<Vec<Value>, String> {
    if producer_responses.is_empty() {
        return Ok(Vec::new());
    }
    let lift_response = if producer_responses.len() == 1 {
        producer_responses[0].response.clone()
    } else {
        merge_ir_document_responses(producer_responses.to_vec())?
    };
    let kind = lift_response
        .get("kind")
        .and_then(|v| v.as_str())
        .ok_or("producer lift response missing `kind` field")?;
    if kind != "ir-document" {
        return Err(format!(
            "consumer lift surfaces require producer ir-documents; producer response kind was `{kind}`"
        ));
    }
    let ir = lift_response
        .get("ir")
        .and_then(|v| v.as_array())
        .ok_or("producer ir-document response missing `ir` array")?;
    let authorities = lift_response.get("authorities").and_then(|v| v.as_array());
    let implications = lift_response.get("implications").and_then(|v| v.as_array());
    let witnesses = lift_response.get("witnesses").and_then(|v| v.as_array());
    Ok(mint_ir_document(
        ir,
        authorities,
        implications,
        witnesses,
        project_root,
        out_dir,
        quiet,
    )?
    .contract_bindings)
}

/// Harvest contract bindings from dependency proofs already loaded under
/// `<project_root>/.sugar/imports/`. This is the M×N bridge model one
/// level up the crate graph: a dependency crate (libsugar, the rust
/// stdlib shim, ...) publishes its contracts as a `.proof`, the consumer's
/// pool loads it, and the implication lifter — handed these (name, cid,
/// body_bearing) bindings alongside the project's own — emits a bridge for
/// each cross-crate / stdlib call site instead of leaving it a lift-gap that
/// vacuous-passes. `body_bearing` (carries a `pre` or `post`, not just an
/// `inv`) lets the lifter prefer a dischargeable dependency contract over a
/// witnessed-fact one for the same callee. Returns empty when imports/ holds
/// no dependency proofs.
/// The dependency .proof CIDs this project conjoins against: the CID-named
/// bundles under `.sugar/imports/`. Returned sorted+deduped so the vendor
/// tie (recorded in the bundle's metadata) is a deterministic, order-
/// independent commitment to the dependency set. The CID IS the filename
/// (the loader requires CID-named imports), so the basename minus `.proof`
/// is the dependency bundle's identity verbatim -- no decode needed.
fn read_conjoined_import_cids(project_root: &Path) -> Vec<String> {
    let imports_dir = project_root.join(".sugar").join("imports");
    let mut cids = std::collections::BTreeSet::new();
    if let Ok(entries) = std::fs::read_dir(&imports_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) == Some("proof") {
                if let Some(stem) = path.file_stem().and_then(|s| s.to_str()) {
                    if stem.starts_with("blake3-512:") {
                        cids.insert(stem.to_string());
                    }
                }
            }
        }
    }
    cids.into_iter().collect()
}

fn contract_bindings_from_dependency_proofs(project_root: &Path) -> Vec<Value> {
    // Scope strictly to declared dependency proofs under `.sugar/imports/`.
    // (`load_all_proofs::run` recursively walks the WHOLE crate tree, which
    // would slurp stale proofs under target/, examples/, the crate's own
    // freshly-minted output, etc. — we want only what the kit author placed
    // in imports/ as a dependency.)
    let imports_dir = project_root.join(".sugar").join("imports");
    let mut proof_files = Vec::new();
    if let Ok(entries) = std::fs::read_dir(&imports_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) == Some("proof") {
                proof_files.push(path);
            }
        }
    }
    if proof_files.is_empty() {
        return Vec::new();
    }
    let mut pool = sugar_verifier::types::MementoPool::default();
    sugar_verifier::load_all_proofs::load_files_into_pool(&proof_files, &mut pool);

    // member CID -> the `.proof` bundle CID it was loaded from. This is the
    // `targetProofCid` a cross-crate bridge must pin so the verifier enforces
    // ConsequentBundlePinned (the contract member MUST come from THIS bundle,
    // not a same-named poisoned shim). `bundle_members` is bundleCid ->
    // {memberCid}; invert it.
    let mut member_to_bundle: std::collections::BTreeMap<&str, &str> =
        std::collections::BTreeMap::new();
    for (bundle, members) in &pool.bundle_members {
        for m in members {
            member_to_bundle.insert(m.as_str(), bundle.as_str());
        }
    }

    // Iterate mementos directly rather than `pool.name_to_cid`: that index is
    // first-writer-wins, so when a dependency publishes BOTH a test-lifted
    // `inv` contract and a body-bearing `pre`/`post` function-contract for the
    // same name (both land as `kind:"contract"` mementos), the index can pin
    // the vacuous one. We resolve the same-name collision here in favour of
    // the body-bearing contract, mirroring the implication lifter's tiebreak,
    // so cross-crate bridges target a dischargeable contract.
    //
    // `contract_cid` is the memento map key = the attestation CID the verifier
    // indexes `pool.mementos` by, exactly as the intra-crate binding path uses
    // (see the `contracts_by_name` -> `contract_bindings` map below).
    // Keyed by (library, leaf), NOT leaf alone: two dependency crates can each
    // publish a contract with the same leaf (e.g. both have `new`), and Tier-1
    // matching distinguishes them by crate. Keying by leaf only would collapse
    // them into one and lose the very disambiguation this exists for.
    let mut by_key: std::collections::BTreeMap<
        (Option<String>, String),
        (
            String,
            bool,
            bool,
            bool,
            Option<String>,
            bool,
            Option<String>,
        ),
    > = std::collections::BTreeMap::new();
    for (cid, env) in &pool.mementos {
        if pool.member_kind(cid) != Some("contract") {
            continue;
        }
        let name = match pool
            .member_field(cid, "contractName")
            .or_else(|| pool.member_field(cid, "name"))
            .and_then(|v| v.as_str())
        {
            Some(n) => n.to_string(),
            None => continue,
        };
        let body_policy = body_discharge_policy_from_fields(
            pool.member_field(cid, "bodyDischargeEligible")
                .or_else(|| pool.member_field(cid, "body_discharge_eligible")),
            pool.member_field(cid, "bodyDischargeRefusalReason")
                .or_else(|| pool.member_field(cid, "body_discharge_refusal_reason")),
            pool.member_field(cid, "dischargePolicy"),
        );
        log_body_discharge_policy_warnings(
            "mint-dependency-contract-binding",
            &name,
            &body_policy.warnings,
        );
        let body_discharge_eligible = body_policy.body_discharge_eligible;
        let body_discharge_refusal_reason = body_policy.body_discharge_refusal_reason;
        // The dependency crate this contract belongs to (the lifter stamped it
        // at mint, the CLI forwards it opaquely).
        let library = pool
            .member_field(cid, "library")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(|s| s.to_string());
        let resolved_body = pool.resolve_contract_body(env);
        let has_pre = resolved_body
            .as_ref()
            .and_then(|body| body.get("pre"))
            .is_some_and(has_nontrivial_pre_json);
        let has_post = pool.member_field(cid, "postHash").is_some();
        let body_bearing = (has_pre || has_post) && body_discharge_eligible;
        let bundle = member_to_bundle.get(cid.as_str()).map(|b| b.to_string());
        let key = (library, name);
        // SELECTION PREFERENCE (most to least preferred):
        //   1. Eligible non-trivial-PRE contracts: the ONLY shape that can prove
        //      a partial cannot panic.
        //   2. Body-discharge-ineligible contracts: this preserves explicit
        //      totality axioms over post-only duplicates so the lifter can route
        //      them to the honesty boundary instead of silently picking an
        //      eligible shell.
        //   3. Other body-bearing (post-only) contracts over inv-only.
        // Names are not identity here -- two shapes share a name (post-only
        // sugar `option_unwrap` and pre-bearing fn-contract `option_unwrap`)
        // and we must select the dischargeable one deterministically.
        let rank = |has_pre: bool, body_bearing: bool, eligible: bool| -> u8 {
            if has_pre && eligible {
                3
            } else if !eligible {
                2
            } else if body_bearing {
                1
            } else {
                0
            }
        };
        let new_rank = rank(has_pre, body_bearing, body_discharge_eligible);
        let take = match by_key.get(&key) {
            None => true,
            Some((_, incumbent_bb, incumbent_has_pre, _, _, incumbent_eligible, _)) => {
                new_rank > rank(*incumbent_has_pre, *incumbent_bb, *incumbent_eligible)
            }
        };
        if take {
            by_key.insert(
                key,
                (
                    cid.to_string(),
                    body_bearing,
                    has_pre,
                    has_post,
                    bundle,
                    body_discharge_eligible,
                    body_discharge_refusal_reason,
                ),
            );
        }
    }
    by_key
        .into_iter()
        .map(
            |(
                (library, name),
                (
                    cid,
                    body_bearing,
                    has_pre,
                    has_post,
                    bundle,
                    body_discharge_eligible,
                    body_discharge_refusal_reason,
                ),
            )| {
                json!({
                    "name": name,
                    "contract_cid": cid,
                    "body_bearing": body_bearing,
                    "has_pre": has_pre,
                    "has_post": has_post,
                    "bodyDischargeEligible": body_discharge_eligible,
                    "bodyDischargeRefusalReason": body_discharge_refusal_reason,
                    // The dependency bundle CID: the bridge pins this so the
                    // verifier resolves the target contract from THIS proof only.
                    "target_proof_cid": bundle,
                    // The crate this dependency contract belongs to: the lifter
                    // keys the call site by (crate, leaf) to match it.
                    "library": library,
                })
            },
        )
        .collect()
}

impl Kit for MintKit {
    fn dialect(&self) -> Dialect {
        Dialect::Other("sugar-mint".to_string())
    }

    fn transform(&self, input: &Input) -> Result<DomainClaim, KitError> {
        self.transform_session(input).map(|session| session.claim)
    }

    fn prove(&self, claim: DomainClaim) -> Result<DomainClaim, KitError> {
        Ok(claim)
    }

    fn parse(&self, input: &Input) -> Result<Term, KitError> {
        let session = self.transform_session(input)?;
        Ok(Term::Const {
            value: dispatch_result_to_value(&session.result),
            sort: Sort::Primitive {
                name: "MintResult".to_string(),
            },
        })
    }

    fn serialize(&self, term: &Term) -> Result<Input, KitError> {
        Ok(Input::Term(term.clone()))
    }
}

fn dispatch(
    project_root: &Path,
    surface: &str,
    out_dir: &Path,
    quiet: bool,
    library_bindings: bool,
) -> Result<MintSession, String> {
    let mint_input = mint_input(project_root, surface, out_dir, quiet, library_bindings);
    MintKit::new(mint_input.inputs)
        .transform_session(&mint_input.input)
        .map_err(|error| error.to_string())
}

/// Multi-plugin dispatch: builds a fan-in mint path with N lift steps
/// (one per declared `[[plugins]]` entry) feeding into one mint terminal
/// step. Delegates to the same `MintKit::transform_session` as
/// single-plugin dispatch — the substrate's path executor and the
/// MintKit's predecessor-fan-in logic handle the rest. The user-facing
/// wrapper for projects whose `.sugar/config.toml` declares
/// `[[plugins]]`.
fn dispatch_multi(
    project_root: &Path,
    plugins: &[PluginEntry],
    out_dir: &Path,
    quiet: bool,
    library_bindings: bool,
) -> Result<MintSession, String> {
    let mint_input = mint_input_multi(project_root, plugins, out_dir, quiet, library_bindings);
    MintKit::new(mint_input.inputs)
        .transform_session(&mint_input.input)
        .map_err(|error| error.to_string())
}

pub(crate) fn mint_lift_plugins_for_report(
    project_root: &Path,
    plugins: &[PluginEntry],
    out_dir: &Path,
    library_bindings: bool,
) -> Result<Option<PathBuf>, String> {
    let session = dispatch_multi(project_root, plugins, out_dir, true, library_bindings)?;
    Ok(session.result.proof_file)
}

pub(crate) fn lift_plugins_response_for_report(
    project_root: &Path,
    plugins: &[PluginEntry],
    out_dir: &Path,
    library_bindings: bool,
    report_summary: bool,
) -> Result<Value, String> {
    let mut producer_plugins = Vec::new();
    let mut consumer_plugins = Vec::new();
    for plugin in plugins {
        if lift_plugin::surface_phase(project_root, &plugin.surface) == "consumer" {
            consumer_plugins.push(plugin);
        } else {
            producer_plugins.push(plugin);
        }
    }
    let report_summary_for_lift = report_summary && consumer_plugins.is_empty();

    let mut per_plugin: Vec<PerPluginDispatch> = Vec::with_capacity(plugins.len());
    let mut producer_responses: Vec<PerPluginDispatch> = Vec::with_capacity(producer_plugins.len());
    for plugin in producer_plugins {
        let response = dispatch_report_lift_plugin(
            project_root,
            plugin,
            Vec::new(),
            library_bindings,
            report_summary_for_lift,
        )?;
        let dispatched = PerPluginDispatch {
            surface: plugin.surface.clone(),
            response,
        };
        producer_responses.push(dispatched.clone());
        per_plugin.push(dispatched);
    }

    let contract_bindings = if consumer_plugins.is_empty() {
        Vec::new()
    } else {
        consumer_contract_bindings_from_producers(&producer_responses, project_root, out_dir, true)?
    };
    for plugin in consumer_plugins {
        let response = dispatch_report_lift_plugin(
            project_root,
            plugin,
            contract_bindings.clone(),
            library_bindings,
            false,
        )?;
        per_plugin.push(PerPluginDispatch {
            surface: plugin.surface.clone(),
            response,
        });
    }

    let plan_memento = finalize_toolchain_plan_memento(
        toolchain_plan_seed(project_root, plugins, report_toolchain_plan_steps(plugins)),
        &per_plugin,
    )?;
    let mut response = match per_plugin.len() {
        0 => Err("lift report graph has no lift plugins".to_string()),
        1 => Ok(per_plugin.into_iter().next().unwrap().response),
        _ => merge_ir_document_responses(per_plugin),
    }?;
    if response.get("kind").and_then(Value::as_str) == Some("ir-document") {
        let mut plan_mementos = response
            .get("planMementos")
            .or_else(|| response.get("plan_mementos"))
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        plan_mementos.push(plan_memento);
        response["planMementos"] = Value::Array(plan_mementos);
    }
    Ok(response)
}

fn report_toolchain_plan_steps(plugins: &[PluginEntry]) -> Vec<Value> {
    let mut steps = plugins
        .iter()
        .enumerate()
        .map(|(idx, plugin)| {
            json!({
                "name": if plugins.len() == 1 { "lift".to_string() } else { format!("lift_{idx}") },
                "role": "lift",
                "kit": format!("lift-plugin:{}", plugin.surface),
                "surface": plugin.surface,
                "verb": "transform",
                "dependsOn": [],
            })
        })
        .collect::<Vec<_>>();
    steps.push(json!({
        "name": "report",
        "role": "report",
        "kit": "sugar-lift-report",
        "verb": "render",
        "dependsOn": plugins
            .iter()
            .enumerate()
            .map(|(idx, _)| if plugins.len() == 1 { "lift".to_string() } else { format!("lift_{idx}") })
            .collect::<Vec<_>>(),
    }));
    steps
}

fn dispatch_report_lift_plugin(
    project_root: &Path,
    plugin: &PluginEntry,
    contract_bindings: Vec<Value>,
    library_bindings: bool,
    report_summary: bool,
) -> Result<Value, String> {
    let lift_options = LiftPluginOptions {
        workspace_override: plugin.workspace_override.clone(),
        emit: plugin.emit.clone(),
        layer: plugin.layer.clone(),
        library_bindings,
        report_summary,
        contract_bindings,
        ..Default::default()
    };
    lift_plugin::dispatch_lift(project_root, &plugin.surface, lift_options, true)
        .map(|session| {
            let mut response = session.response().clone();
            prefix_workspace_override_source_files(
                &mut response,
                plugin.workspace_override.as_deref(),
            );
            response
        })
        .map_err(|error| match error {
            LiftPluginError::MissingBinary { binary } => {
                format!("lifter binary `{binary}` not found")
            }
            LiftPluginError::Refused(refusal) => format!(
                "{}: {}",
                refusal.header.failure_kind, refusal.header.failure_detail
            ),
            LiftPluginError::Failed(error) => error,
        })
}

fn prefix_workspace_override_source_files(response: &mut Value, workspace_override: Option<&str>) {
    let Some(prefix) = report_source_prefix(workspace_override) else {
        return;
    };
    prefix_relative_file_fields(response, &prefix);
}

fn report_source_prefix(workspace_override: Option<&str>) -> Option<String> {
    let raw = workspace_override?.trim();
    if raw.is_empty() || raw == "." {
        return None;
    }
    let normalized = raw.replace('\\', "/").trim_end_matches('/').to_string();
    (!normalized.is_empty()).then_some(normalized)
}

fn prefix_relative_file_fields(value: &mut Value, prefix: &str) {
    match value {
        Value::Object(object) => {
            if let Some(Value::String(file)) = object.get_mut("file") {
                *file = prefixed_report_source_file(file, prefix);
            }
            for child in object.values_mut() {
                prefix_relative_file_fields(child, prefix);
            }
        }
        Value::Array(items) => {
            for child in items {
                prefix_relative_file_fields(child, prefix);
            }
        }
        _ => {}
    }
}

fn prefixed_report_source_file(file: &str, prefix: &str) -> String {
    let normalized = file.replace('\\', "/");
    if normalized.trim().is_empty() || Path::new(&normalized).is_absolute() {
        return normalized;
    }
    let relative = normalized.trim_start_matches("./");
    if relative == prefix || relative.starts_with(&format!("{prefix}/")) {
        return relative.to_string();
    }
    format!("{prefix}/{relative}")
}

fn consumer_contract_bindings_from_producers(
    producer_responses: &[PerPluginDispatch],
    project_root: &Path,
    out_dir: &Path,
    quiet: bool,
) -> Result<Vec<Value>, String> {
    let mut bindings = contract_bindings_from_producer_responses(
        producer_responses,
        project_root,
        out_dir,
        quiet,
    )?;
    let intra_keys: std::collections::HashSet<(String, String)> = bindings
        .iter()
        .filter_map(|binding| {
            let name = binding.get("name").and_then(Value::as_str)?.to_string();
            let library = binding
                .get("library")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string();
            Some((library, name))
        })
        .collect();
    let dep_bindings = contract_bindings_from_dependency_proofs(project_root);
    let dep_kept = dep_bindings
        .into_iter()
        .filter(|binding| {
            let Some(name) = binding
                .get("name")
                .and_then(Value::as_str)
                .map(String::from)
            else {
                return false;
            };
            let library = binding
                .get("library")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string();
            !intra_keys.contains(&(library, name))
        })
        .collect::<Vec<_>>();
    bindings.extend(dep_kept);
    Ok(bindings)
}

fn dispatch_path(project_root: &Path, path_file: &Path) -> Result<MintSession, String> {
    let path = path_under(project_root, path_file);
    let text = std::fs::read_to_string(&path)
        .map_err(|error| format!("read mint path document {}: {error}", path.display()))?;
    let document: PathDocument = serde_json::from_str(&text)
        .map_err(|error| format!("parse mint path document {}: {error}", path.display()))?;
    let mut inputs = HashMapInputCatalog::default();
    for (cid, input) in document
        .materialized_inputs()
        .map_err(|error| format!("invalid mint path document {}: {error}", path.display()))?
    {
        inputs.put(cid, input);
    }
    MintKit::new(inputs)
        .transform_session(&Input::Path(Box::new(document.path)))
        .map_err(|error| error.to_string())
}

fn path_under(project_root: &Path, path: &Path) -> PathBuf {
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        project_root.join(path)
    }
}

fn mint_input(
    project_root: &Path,
    surface: &str,
    out_dir: &Path,
    quiet: bool,
    library_bindings: bool,
) -> MintPathInput {
    let entry = PluginEntry {
        name: None,
        kind: Some("lift".to_string()),
        surface: surface.to_string(),
        workspace_override: None,
        emit: None,
        layer: None,
    };
    mint_input_multi(
        project_root,
        std::slice::from_ref(&entry),
        out_dir,
        quiet,
        library_bindings,
    )
}

/// Build a mint path with N lift steps (one per declared `[[plugins]]`
/// entry from config.toml) feeding into a single mint terminal step.
/// The path executor walks each lift step's `Kit::transform(Input) ->
/// DomainClaim` independently; mint depends on all of them by name and
/// collects/merges their outputs at the envelope mint stage. This is
/// the substrate's path-native answer to multi-plugin orchestration:
/// the dispatch lives in the path algebra, not in side-channel CLI
/// loops. Single-surface callers route here with a 1-element slice.
fn mint_input_multi(
    project_root: &Path,
    plugins: &[PluginEntry],
    out_dir: &Path,
    quiet: bool,
    library_bindings: bool,
) -> MintPathInput {
    let mut inputs = HashMapInputCatalog::default();
    let mut algebra: Vec<PathAlgebra> = Vec::with_capacity(plugins.len() + 1);
    let mut lift_step_names: Vec<String> = Vec::with_capacity(plugins.len());
    let mut plan_path_steps: Vec<Value> = Vec::with_capacity(plugins.len() + 1);

    for (idx, plugin) in plugins.iter().enumerate() {
        let lift_input = Input::Spec(lift_plugin::build_lift_params(
            project_root,
            &plugin.surface,
            LiftPluginOptions {
                identify_only: false,
                library_bindings,
                workspace_override: plugin.workspace_override.clone(),
                emit: plugin.emit.clone(),
                layer: plugin.layer.clone(),
                report_summary: false,
                contract_bindings: Vec::new(),
            },
        ));
        let lift_input_cid = address(&lift_input);
        inputs.put(lift_input_cid.clone(), lift_input);
        let lift_step_name = if plugins.len() == 1 {
            // Preserve the historic single-step name `lift` so any
            // path-document fixtures or external tooling keyed on it
            // keep working.
            "lift".to_string()
        } else {
            format!("lift_{idx}")
        };
        let lift_kit = format!("lift-plugin:{}", plugin.surface);
        plan_path_steps.push(json!({
            "name": lift_step_name.clone(),
            "role": "lift",
            "kit": lift_kit.clone(),
            "surface": plugin.surface.clone(),
            "verb": "transform",
            "inputCids": [lift_input_cid.to_string()],
            "dependsOn": [],
        }));
        algebra.push(PathAlgebra {
            name: lift_step_name.clone(),
            kit: lift_kit,
            inputs: vec![lift_input_cid],
            depends_on: vec![],
            verb: Verb::Transform,
        });
        lift_step_names.push(lift_step_name);
    }

    let surface_for_mint = plugins
        .first()
        .map(|p| p.surface.clone())
        .unwrap_or_default();
    let mint_dependencies = lift_step_names.clone();
    plan_path_steps.push(json!({
        "name": "mint",
        "role": "mint",
        "kit": "sugar-mint",
        "verb": "transform",
        "dependsOn": mint_dependencies,
    }));
    let toolchain_plan = toolchain_plan_seed(project_root, plugins, plan_path_steps);
    let mint_input = Input::Spec(json!({
        "projectRoot": project_root.display().to_string(),
        "surface": surface_for_mint,
        "outDir": out_dir.display().to_string(),
        "toolchainPlan": toolchain_plan,
        "options": {
            "quiet": quiet
        }
    }));
    let mint_input_cid = address(&mint_input);
    inputs.put(mint_input_cid.clone(), mint_input);

    algebra.push(PathAlgebra {
        name: "mint".to_string(),
        kit: "sugar-mint".to_string(),
        inputs: vec![mint_input_cid],
        depends_on: lift_step_names,
        verb: Verb::Transform,
    });

    MintPathInput {
        input: Input::Path(Box::new(CorePath { algebra })),
        inputs,
    }
}

fn toolchain_plan_seed(
    project_root: &Path,
    plugins: &[PluginEntry],
    path_steps: Vec<Value>,
) -> Value {
    let plugin_entries: Vec<Value> = plugins
        .iter()
        .map(|plugin| {
            json!({
                "name": plugin.name,
                "kind": plugin.kind,
                "surface": plugin.surface,
                "workspaceOverride": plugin.workspace_override,
                "emit": plugin.emit,
                "layer": plugin.layer,
            })
        })
        .collect();
    let component_plan = crate::component_plan::plan_workspace(
        project_root,
        crate::component_plan::PlanIntent::Lift,
    );
    let mut plan_atoms = plan_atoms_for_plugins(project_root, plugins);
    plan_atoms.extend(support_plan_atoms_for_component_plan(
        project_root,
        plugins,
        &component_plan,
    ));
    json!({
        "kind": "component-plan",
        "schemaVersion": "1",
        "workspaceRoot": project_root.display().to_string(),
        "planning": {
            "source": "component-discovery",
        },
        "plugins": plugin_entries,
        "planAtoms": plan_atoms,
        "pathSteps": path_steps,
    })
}

fn plan_atoms_for_plugins(project_root: &Path, plugins: &[PluginEntry]) -> Vec<Value> {
    plugins
        .iter()
        .map(|plugin| plan_atom_for_plugin(project_root, plugin))
        .collect()
}

fn plan_atom_for_plugin(project_root: &Path, plugin: &PluginEntry) -> Value {
    let manifest = lift_plugin::find_manifest_for_surface(project_root, &plugin.surface);
    let (manifest_name, version, protocol_version, command, working_dir, phase, method) =
        match manifest {
            Ok(manifest) => {
                let working_dir = lift_plugin::resolved_working_dir_for(project_root, &manifest);
                (
                    Some(manifest.name),
                    manifest.version,
                    manifest.protocol_version,
                    manifest.command,
                    working_dir,
                    manifest.phase,
                    manifest.method,
                )
            }
            Err(error) => (
                None,
                None,
                None,
                Vec::new(),
                None,
                None,
                Some(format!("manifest resolution failed: {error}")),
            ),
        };
    let binary = command
        .first()
        .map(|program| plan_binary_identity(project_root, working_dir.as_deref(), program));
    json!({
        "kind": "plan-atom",
        "schemaVersion": "1",
        "atomKind": "lifter-binary",
        "role": plan_role_for_plugin(plugin, phase.as_deref()),
        "surface": plugin.surface.clone(),
        "pluginName": plugin.display_name(),
        "manifestName": manifest_name,
        "version": version,
        "protocolVersion": protocol_version,
        "command": command,
        "method": method,
        "phase": phase,
        "workspaceOverride": plugin.workspace_override.clone(),
        "emit": plugin.emit.clone(),
        "layer": plugin.layer.clone(),
        "binary": binary,
        "participation": "executed",
    })
}

fn support_plan_atoms_for_component_plan(
    project_root: &Path,
    active_plugins: &[PluginEntry],
    component_plan: &crate::component_plan::ComponentPlan,
) -> Vec<Value> {
    let active_surfaces = active_plugins
        .iter()
        .map(|plugin| plugin.surface.as_str())
        .collect::<BTreeSet<_>>();
    let mut atoms = Vec::new();
    let mut seen = BTreeSet::new();

    for plugin in active_plugins {
        let mut atom = plan_atom_for_plugin(project_root, plugin);
        atom["atomKind"] = json!("source-oracle");
        atom["role"] = json!("source-oracle");
        atom["pluginName"] = json!(format!("{} source oracle", plugin.display_name()));
        push_unique_plan_atom(&mut atoms, &mut seen, atom);
    }

    push_unique_plan_atom(
        &mut atoms,
        &mut seen,
        factory_report_plan_atom(project_root),
    );

    for plugin in &component_plan.plugins {
        if active_surfaces.contains(plugin.surface.as_str()) {
            continue;
        }
        let phase = planned_phase_for_plugin(component_plan, &plugin.surface);
        if plan_role_for_plugin(plugin, phase.as_deref()) != "witness-oracle" {
            continue;
        }
        let mut atom = plan_atom_for_plugin(project_root, plugin);
        atom["participation"] = json!("available");
        push_unique_plan_atom(&mut atoms, &mut seen, atom);
    }

    for compiler in &component_plan.ir_compilers {
        push_unique_plan_atom(
            &mut atoms,
            &mut seen,
            proofir_compiler_plan_atom(project_root, compiler),
        );
    }

    atoms
}

fn push_unique_plan_atom(atoms: &mut Vec<Value>, seen: &mut BTreeSet<String>, atom: Value) {
    let key = format!(
        "{}\0{}\0{}",
        atom.get("role").and_then(Value::as_str).unwrap_or(""),
        atom.get("surface").and_then(Value::as_str).unwrap_or(""),
        atom.get("pluginName").and_then(Value::as_str).unwrap_or(""),
    );
    if seen.insert(key) {
        atoms.push(atom);
    }
}

fn factory_report_plan_atom(project_root: &Path) -> Value {
    let program = std::env::current_exe()
        .ok()
        .map(|path| path.display().to_string())
        .unwrap_or_else(|| "sugar".to_string());
    json!({
        "kind": "plan-atom",
        "schemaVersion": "1",
        "atomKind": "factory-report",
        "role": "factory-report",
        "pluginName": "sugar-lift-report",
        "version": env!("CARGO_PKG_VERSION"),
        "command": [program.clone()],
        "binary": plan_binary_identity(project_root, None, &program),
        "participation": "executed",
    })
}

fn planned_phase_for_plugin(
    component_plan: &crate::component_plan::ComponentPlan,
    surface: &str,
) -> Option<String> {
    component_plan
        .lift_manifests
        .iter()
        .find(|manifest| manifest.surface == surface)
        .and_then(|manifest| manifest.phase.clone())
}

fn proofir_compiler_plan_atom(
    project_root: &Path,
    compiler: &crate::component_plan::PlannedIrCompiler,
) -> Value {
    let binary = compiler.command.first().map(|program| {
        plan_binary_identity(project_root, compiler.working_dir.as_deref(), program)
    });
    json!({
        "kind": "plan-atom",
        "schemaVersion": "1",
        "atomKind": "proofir-compiler",
        "role": "proofir-compiler",
        "pluginName": compiler.name.clone(),
        "manifestName": compiler.name.clone(),
        "version": compiler.version.clone(),
        "protocolVersion": compiler.protocol_version.clone(),
        "command": compiler.command.clone(),
        "workspaceOverride": compiler.working_dir.as_ref().map(|path| path.display().to_string()),
        "dialects": compiler.dialects.clone(),
        "supportedSorts": compiler.supported_sorts.clone(),
        "supportedPredicates": compiler.supported_predicates.clone(),
        "binary": binary,
        "participation": "available",
    })
}

fn plan_binary_identity(project_root: &Path, working_dir: Option<&Path>, program: &str) -> Value {
    let resolved = resolve_plan_binary_path(project_root, working_dir, program);
    let binary_cid = resolved
        .as_ref()
        .and_then(|path| std::fs::read(path).ok())
        .map(|bytes| blake3_512_of(&bytes));
    json!({
        "program": program,
        "path": resolved
            .as_ref()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| program.to_string()),
        "cid": binary_cid,
    })
}

fn resolve_plan_binary_path(
    project_root: &Path,
    working_dir: Option<&Path>,
    program: &str,
) -> Option<PathBuf> {
    let program_path = PathBuf::from(program);
    if program_path.is_absolute() && program_path.exists() {
        return Some(program_path.canonicalize().unwrap_or(program_path));
    }

    let mut bases = Vec::new();
    if let Some(working_dir) = working_dir {
        bases.push(working_dir.to_path_buf());
    }
    bases.push(project_root.to_path_buf());
    if let Ok(current) = std::env::current_dir() {
        bases.push(current);
    }
    for base in bases {
        let candidate = base.join(program);
        if candidate.exists() {
            return Some(candidate.canonicalize().unwrap_or(candidate));
        }
    }

    if !program.contains('/') && !program.contains('\\') {
        if let Some(paths) = std::env::var_os("PATH") {
            for base in std::env::split_paths(&paths) {
                let candidate = base.join(program);
                if candidate.exists() {
                    return Some(candidate.canonicalize().unwrap_or(candidate));
                }
            }
        }
    }
    None
}

fn plan_role_for_plugin(plugin: &PluginEntry, phase: Option<&str>) -> &'static str {
    match plugin.surface.as_str() {
        "rust-test-assertions" => "unit-test-assertions",
        "rust-fn-contracts" => "body-universes",
        "rust-implications" => "implications",
        "rust-cargo-test-witness" => "witness-oracle",
        _ if phase == Some("consumer") => "consumer",
        _ => "lifter",
    }
}

fn mint_lift_response(
    project_root: &Path,
    out_dir: &Path,
    quiet: bool,
    lift_resp: Value,
) -> Result<DispatchResult, String> {
    let kind = lift_resp
        .get("kind")
        .and_then(|v| v.as_str())
        .ok_or("lift response missing `kind` field")?;
    match kind {
        "proof-envelope" => {
            let filename_cid = lift_resp
                .get("filename_cid")
                .and_then(|v| v.as_str())
                .ok_or("missing filename_cid")?
                .to_string();
            let contract_set_cid = lift_resp
                .get("contract_set_cid")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let bytes_b64 = lift_resp
                .get("bytes_base64")
                .and_then(|v| v.as_str())
                .ok_or("missing bytes_base64")?;
            let bytes = base64::engine::general_purpose::STANDARD
                .decode(bytes_b64)
                .map_err(|e| format!("decode bytes_base64: {e}"))?;

            std::fs::create_dir_all(out_dir)
                .map_err(|e| format!("mkdir {}: {e}", out_dir.display()))?;
            let out_path = out_dir.join(proof_filename(&filename_cid));
            std::fs::write(&out_path, &bytes)
                .map_err(|e| format!("write {}: {e}", out_path.display()))?;

            print_lift_diagnostics(&lift_resp, quiet);

            Ok(DispatchResult {
                filename_cid,
                contract_set_cid,
                bytes_written: bytes.len(),
                proof_file: Some(out_path),
                lift_result: redact_lift_result(lift_resp),
            })
        }
        "ir-document" => {
            let ir = lift_resp
                .get("ir")
                .and_then(|v| v.as_array())
                .ok_or("ir-document response missing `ir` array")?;

            let authorities = lift_resp.get("authorities").and_then(|v| v.as_array());
            let implications = lift_resp.get("implications").and_then(|v| v.as_array());
            let witnesses = lift_resp.get("witnesses").and_then(|v| v.as_array());
            let source_mementos = lift_resp
                .get("sourceMementos")
                .or_else(|| lift_resp.get("source_mementos"))
                .and_then(|v| v.as_array());
            let plan_mementos = lift_resp
                .get("planMementos")
                .or_else(|| lift_resp.get("plan_mementos"))
                .and_then(|v| v.as_array());
            let factory_walk = lift_resp
                .get("factoryAuditSummary")
                .and_then(|summary| summary.get("factoryWalk"))
                .and_then(Value::as_array);
            let assertion_surface_audits = lift_resp
                .get("assertionSurfaceAudits")
                .or_else(|| lift_resp.get("assertion_surface_audits"))
                .and_then(Value::as_array);
            debug!(
                ir_entries = ir.len(),
                "mint: minting ir-document into .proof bundle"
            );
            let minted = mint_ir_document_with_source_and_plan_mementos(
                ir,
                source_mementos,
                plan_mementos,
                factory_walk,
                assertion_surface_audits,
                authorities,
                implications,
                witnesses,
                &project_root,
                out_dir,
                quiet,
            )?;

            info!(
                filename_cid = %minted.filename_cid,
                contract_set_cid = %minted.contract_set_cid,
                bytes = minted.bytes.len(),
                "mint: .proof bundle minted"
            );
            std::fs::create_dir_all(out_dir)
                .map_err(|e| format!("mkdir {}: {e}", out_dir.display()))?;
            let out_path = out_dir.join(proof_filename(&minted.filename_cid));
            std::fs::write(&out_path, &minted.bytes)
                .map_err(|e| format!("write {}: {e}", out_path.display()))?;
            debug!(out_path = %out_path.display(), "mint: .proof file written");

            print_lift_diagnostics(&lift_resp, quiet);

            Ok(DispatchResult {
                filename_cid: minted.filename_cid,
                contract_set_cid: minted.contract_set_cid,
                bytes_written: minted.bytes.len(),
                proof_file: Some(out_path),
                lift_result: lift_resp,
            })
        }
        other => Err(format!(
            "unsupported response shape `{other}`; expected `proof-envelope` or `ir-document`",
        )),
    }
}

fn redact_lift_result(mut lift_resp: Value) -> Value {
    if let Some(obj) = lift_resp.as_object_mut() {
        if obj.contains_key("bytes_base64") {
            obj.insert(
                "bytes_base64".to_string(),
                Value::String("<redacted>".to_string()),
            );
        }
    }
    lift_resp
}

fn print_lift_diagnostics(lift_resp: &Value, quiet: bool) {
    if quiet {
        return;
    }
    let Some(diags) = lift_resp.get("diagnostics").and_then(|v| v.as_array()) else {
        return;
    };
    for diagnostic in diags {
        if let Some(rendered) = render_lift_diagnostic(diagnostic) {
            println!("{}: {rendered}", "note".dimmed());
        }
    }
}

fn render_lift_diagnostic(diagnostic: &Value) -> Option<String> {
    if let Some(s) = diagnostic.as_str().filter(|s| !s.is_empty()) {
        return Some(s.to_string());
    }
    let Some(obj) = diagnostic.as_object() else {
        return None;
    };
    let kind = obj
        .get("kind")
        .and_then(|v| v.as_str())
        .unwrap_or("diagnostic");
    let mut rendered = kind.to_string();
    if let Some(reason) = obj.get("reason").and_then(|v| v.as_str()) {
        rendered.push_str(": ");
        rendered.push_str(reason);
    }
    if let Some(callee) = obj.get("callee").and_then(|v| v.as_str()) {
        rendered.push_str(": ");
        rendered.push_str(callee);
    }
    if let Some(file) = obj.get("file").and_then(|v| v.as_str()) {
        rendered.push_str(" at ");
        rendered.push_str(file);
        if let Some(line) = obj.get("line").and_then(|v| v.as_i64()) {
            rendered.push(':');
            rendered.push_str(&line.to_string());
            if let Some(col) = obj.get("col").and_then(|v| v.as_i64()) {
                rendered.push(':');
                rendered.push_str(&col.to_string());
            }
        }
    }
    if rendered == "diagnostic" {
        serde_json::to_string(diagnostic).ok()
    } else {
        Some(rendered)
    }
}

fn mint_result_claim(
    input: &Input,
    lift_claim: Option<&DomainClaim>,
    result: &DispatchResult,
) -> Result<DomainClaim, KitError> {
    let value = dispatch_result_to_value(result);
    let term = Term::Const {
        value,
        sort: Sort::Primitive {
            name: "MintResult".to_string(),
        },
    };
    let contract = FunctionContractDomain
        .project(&term, &Boundary::default())
        .map_err(|error| KitError::Transformation(error.to_string()))?;
    let to = if result.filename_cid.is_empty() {
        address(&term)
    } else {
        Cid::parse(result.filename_cid.clone()).unwrap_or_else(|_| address(&term))
    };
    let result_cid = address(&term);
    let premises = lift_claim
        .map(|claim| vec![claim.cid()])
        .unwrap_or_default();

    Ok(DomainClaim {
        domain: DomainKind::Other("sugar-mint".to_string()),
        contract,
        artifacts: vec![result_cid],
        from: vec![address(input)],
        premises,
        to,
        witness: None,
        payload: Some(term),
        verdict: Verdict::Unresolved,
        attestation: None,
    })
}

fn dispatch_result_to_value(result: &DispatchResult) -> Value {
    let oracle = oracle_observation_from_lift(&result.lift_result);
    json!({
        "kind": "mint-result",
        "filenameCid": result.filename_cid,
        "contractSetCid": result.contract_set_cid,
        "bytesWritten": result.bytes_written,
        "proofFile": result.proof_file.as_ref().map(|path| path.display().to_string()),
        "oracle": {
            "requested": oracle.requested,
            "reachable": oracle.reachable,
            "ready": oracle.ready,
            "attempted": oracle.attempted,
            "resolved": oracle.resolved,
        },
        "lift": result.lift_result,
    })
}

// ---------------------------------------------------------------------------
// ir-document → proof-envelope minting
// ---------------------------------------------------------------------------

/// #1358 / #1355: Fill `family` and `library_version` on each IR entry from
/// the project's platform_profile when the entry doesn't already pin those
/// axes via @sugar / @boundary annotation. ANNOTATION WINS: an entry whose
/// emission already includes a family or library_version (because walk_rpc
/// pulled it from the source annotation) keeps that value verbatim.
///
/// Applies to all per-concept memento kinds:
///   - library-sugar-binding-entry
///   - realization-memento
///
/// Refusal-memento is intentionally not stamped — refusals are about a
/// concept that DIDN'T close in this surface; the realization-tuple axes
/// don't apply (the realization didn't happen).
pub(crate) fn stamp_platform_profile(
    entries: &mut Vec<Value>,
    profile: &crate::project_config::PlatformProfile,
) {
    for entry in entries.iter_mut() {
        let kind = entry.get("kind").and_then(|v| v.as_str()).unwrap_or("");
        if kind != "library-sugar-binding-entry" {
            continue;
        }
        let Some(obj) = entry.as_object_mut() else {
            continue;
        };
        if let Some(family) = &profile.family {
            if !obj.contains_key("family") {
                obj.insert("family".to_string(), Value::String(family.clone()));
            }
        }
        if let Some(version) = &profile.version {
            if !obj.contains_key("library_version") {
                obj.insert(
                    "library_version".to_string(),
                    Value::String(version.clone()),
                );
            }
        }
    }
}

fn parse_bridge_callsite(
    decl: &Value,
    source_symbol: &str,
) -> Result<Option<BridgeCallsite>, String> {
    let Some(callsite) = decl.get("callsite") else {
        return Ok(None);
    };
    let object = callsite.as_object().ok_or_else(|| {
        format!(
            "bridge `{source_symbol}`: callsite must be an object, got {}",
            json_type_name(callsite)
        )
    })?;
    let panic_site = match object.get("panicSite") {
        Some(value) => value.as_bool().ok_or_else(|| {
            format!(
                "bridge `{source_symbol}`: callsite.panicSite must be a boolean, got {}",
                json_type_name(value)
            )
        })?,
        None => false,
    };
    let file = match object.get("file") {
        Some(value) => {
            let file = value.as_str().filter(|s| !s.is_empty()).ok_or_else(|| {
                format!(
                    "bridge `{source_symbol}`: callsite.file must be a non-empty string, got {}",
                    json_type_name(value)
                )
            })?;
            Some(file.to_string())
        }
        None => None,
    };
    let line = match object.get("start_line").or_else(|| object.get("line")) {
        Some(value) => Some(value.as_i64().ok_or_else(|| {
            format!(
                "bridge `{source_symbol}`: callsite.line must be an integer, got {}",
                json_type_name(value)
            )
        })?),
        None => None,
    };
    let formal_actuals = match object.get("formalActuals") {
        Some(value) => {
            if !value.is_object() {
                return Err(format!(
                    "bridge `{source_symbol}`: callsite.formalActuals must be an object, got {}",
                    json_type_name(value)
                ));
            }
            Some(json_to_cvalue(value))
        }
        None => None,
    };

    Ok(Some(BridgeCallsite {
        panic_site,
        file,
        line,
        formal_actuals,
    }))
}

fn mint_bridge_from_decl(
    decl: &Value,
    produced_at: &str,
    signer_seed: Ed25519Seed,
) -> Result<(String, Vec<u8>), String> {
    let source_symbol = decl
        .get("sourceSymbol")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .ok_or("bridge ir entry missing `sourceSymbol`")?;
    let target_contract_cid = decl
        .get("targetContractCid")
        .or_else(|| decl.get("sourceContractCid"))
        .or_else(|| decl.pointer("/target/cid"))
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .ok_or("bridge ir entry missing `targetContractCid`")?;
    let source_layer = decl
        .get("sourceLayer")
        .and_then(|v| v.as_str())
        .unwrap_or("source");
    let target_layer = decl
        .get("targetLayer")
        .and_then(|v| v.as_str())
        .unwrap_or("kit");
    // Forward pin: a cross-bundle (dependency-proof) target carries its
    // bundle CID here; an intra-bundle target carries none (self-pinned).
    let target_proof_cid = decl
        .get("targetProofCid")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string());
    // Carry the lifter's call-site provenance (panicSite/file/line) into the
    // bridge memento. Without this the verifier reads panic_site=false on every
    // minted panic leaf and the panic-safe discharge path is never entered.
    let callsite = parse_bridge_callsite(decl, source_symbol)?;
    let bridge = mint_bridge(&MintBridgeArgs {
        produced_by: "sugar-cli".to_string(),
        produced_at: produced_at.to_string(),
        source_symbol: source_symbol.to_string(),
        source_layer: source_layer.to_string(),
        target_contract: ContractMementoRef::new(target_contract_cid.to_string()),
        target_layer: target_layer.to_string(),
        ir_arg_sorts: vec![],
        ir_return_sort: String::new(),
        notes: "implication-lifted callsite bridge".to_string(),
        signer_seed,
        target_proof_cid,
        callsite,
    });
    Ok((bridge.cid, bridge.canonical_bytes))
}

#[cfg(test)]
use sugar_proof_envelope::{member_field, member_kind, Member};

#[cfg(test)]
fn mint_from_ir_document(
    ir: &[Value],
    authorities: Option<&Vec<Value>>,
    implications: Option<&Vec<Value>>,
    witnesses: Option<&Vec<Value>>,
    project_root: &Path,
    out_dir: &Path,
    quiet: bool,
) -> Result<(Vec<u8>, String, String), String> {
    let minted = mint_ir_document(
        ir,
        authorities,
        implications,
        witnesses,
        project_root,
        out_dir,
        quiet,
    )?;
    Ok((minted.bytes, minted.filename_cid, minted.contract_set_cid))
}

fn mint_ir_document(
    ir: &[Value],
    authorities: Option<&Vec<Value>>,
    implications: Option<&Vec<Value>>,
    witnesses: Option<&Vec<Value>>,
    project_root: &Path,
    out_dir: &Path,
    quiet: bool,
) -> Result<MintedIrDocument, String> {
    mint_ir_document_with_source_mementos(
        ir,
        None,
        None,
        authorities,
        implications,
        witnesses,
        project_root,
        out_dir,
        quiet,
    )
}

fn mint_ir_document_with_source_mementos(
    ir: &[Value],
    source_mementos: Option<&Vec<Value>>,
    factory_walk: Option<&Vec<Value>>,
    authorities: Option<&Vec<Value>>,
    implications: Option<&Vec<Value>>,
    witnesses: Option<&Vec<Value>>,
    project_root: &Path,
    out_dir: &Path,
    quiet: bool,
) -> Result<MintedIrDocument, String> {
    mint_ir_document_with_source_and_plan_mementos(
        ir,
        source_mementos,
        None,
        factory_walk,
        None,
        authorities,
        implications,
        witnesses,
        project_root,
        out_dir,
        quiet,
    )
}

fn mint_ir_document_with_source_and_plan_mementos(
    ir: &[Value],
    source_mementos: Option<&Vec<Value>>,
    plan_mementos: Option<&Vec<Value>>,
    factory_walk: Option<&Vec<Value>>,
    assertion_surface_audits: Option<&Vec<Value>>,
    authorities: Option<&Vec<Value>>,
    implications: Option<&Vec<Value>>,
    witnesses: Option<&Vec<Value>>,
    project_root: &Path,
    out_dir: &Path,
    quiet: bool,
) -> Result<MintedIrDocument, String> {
    use std::collections::BTreeMap;

    #[derive(Clone)]
    struct AuthorityRef {
        cid: String,
        seed: Ed25519Seed,
        principal: String,
    }

    struct MintedContractRef {
        contract_name: String,
        attestation_cid: String,
        pre_hash: Option<String>,
        post_hash: Option<String>,
        inv_hash: Option<String>,
        pre_body: Option<Value>,
        post_body: Option<Value>,
        has_nontrivial_pre: bool,
        body_discharge_eligible: bool,
        body_discharge_refusal_reason: Option<String>,
        library: Option<String>,
        bridge_source_symbol: Option<String>,
        formals: Option<Vec<String>>,
        formal_sorts: Option<Vec<Value>>,
    }

    impl MintedContractRef {
        fn slot_hash(&self, slot: &str) -> Option<&str> {
            match slot {
                "pre" => self.pre_hash.as_deref(),
                "post" => self.post_hash.as_deref(),
                "inv" => self.inv_hash.as_deref(),
                _ => None,
            }
        }
    }

    let mut proof_graph = ProofGraph::new();
    let mut proof_member_cids: BTreeSet<String> = BTreeSet::new();
    macro_rules! push_graph_memento {
        ($type:ident, $push:ident, $expected_cid:expr, $bytes:expr) => {{
            let expected_cid = $expected_cid.to_string();
            let memento = $type::new($bytes);
            assert_eq!(
                memento.cid().as_str(),
                expected_cid,
                "{} CID disagrees with its typed memento identity",
                stringify!($type)
            );
            if proof_member_cids.insert(memento.cid().as_str().to_string()) {
                proof_graph.$push(memento);
            }
        }};
    }
    let mut authorities_by_id: BTreeMap<String, AuthorityRef> = BTreeMap::new();
    let mut proof_authority: Option<AuthorityRef> = None;
    // Contracts indexed by their CONTENT CID, never by name. Two distinct
    // shapes that share a name (post-only sugar `option_unwrap` vs pre-bearing
    // fn-contract `option_unwrap`) are DIFFERENT contracts with DIFFERENT CIDs;
    // both must coexist. A name->CIDs index is derived only where a name lookup
    // is genuinely required (mint-time implication wiring), and it is
    // multi-valued precisely because a name is not an identity.
    let mut contracts_by_cid: BTreeMap<String, MintedContractRef> = BTreeMap::new();
    let mut cids_by_name: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut content_cids: Vec<String> = Vec::new();
    let default_signer_seed: Ed25519Seed = DEV_SIGNER_SEED;
    let produced_at = "2026-05-03T18:00:00Z".to_string();
    // The SEMANTIC library this project's contracts represent, from its
    // `platform_profile.library`. This is the crate a consumer's call resolves
    // to: `std` for the rust-std shim, `libsugar` for libsugar, the crate
    // name for an ordinary kit. It is the fallback library tag for every
    // contract the lifter did not stamp (sugar/test contracts, and any surface
    // without rust-fn-contracts). Sourcing it here, not from the Cargo package
    // name, is what lets the shim's std method-call contracts (to_string, len,
    // ...) carry `std` and match a receiver-typed call resolved to std.
    let project_library: Option<String> = read_project_config(project_root)
        .platform_profile
        .and_then(|p| p.library)
        .filter(|s| !s.is_empty());
    let witness_cids_by_contract =
        emit_witnesses_by_contract(witnesses, project_root, out_dir, quiet)?;

    if let Some(source_mementos) = source_mementos {
        for source_memento in source_mementos {
            let (cid, bytes) = mint_source_memento(source_memento, None)?;
            push_graph_memento!(SourceMemento, push_source, cid.as_str(), bytes);
        }
    }

    if let Some(factory_walk) = factory_walk {
        for row in factory_walk {
            let (cid, bytes) = mint_factory_walk_memento(row)?;
            push_graph_memento!(FactoryWalkMemento, push_factory_walk, cid.as_str(), bytes);
        }
    }

    if let Some(assertion_surface_audits) = assertion_surface_audits {
        for row in assertion_surface_audits {
            let (cid, bytes) = mint_assertion_surface_memento(row)?;
            push_graph_memento!(
                AssertionSurfaceMemento,
                push_assertion_surface,
                cid.as_str(),
                bytes
            );
        }
    }

    if let Some(plan_mementos) = plan_mementos {
        for plan_memento in plan_mementos {
            let (cid, bytes, plan_atoms) = mint_plan_memento(plan_memento)?;
            for atom in plan_atoms {
                proof_graph.register_atom(atom);
            }
            push_graph_memento!(PlanMemento, push_plan, cid.as_str(), bytes);
        }
    }

    if let Some(authorities) = authorities {
        for authority in authorities {
            let id = required_str(authority, "id", "authority")?;
            let principal = optional_str(authority, "principal").unwrap_or(id);
            let scope_kind = required_str(authority, "scopeKind", id)?;
            let scope = required_str(authority, "scope", id)?;
            let seed = deterministic_signer_seed(principal);
            let key = ed25519_pubkey_string(&seed);
            let parent_id = optional_str(authority, "parent")
                .or_else(|| optional_str(authority, "issuer"))
                .or_else(|| optional_str(authority, "parentAuthority"));
            let parent = match parent_id {
                Some(parent_id) => Some(authorities_by_id.get(parent_id).ok_or_else(|| {
                    format!("authority `{id}` references missing parent `{parent_id}`")
                })?),
                None => None,
            };
            let parent_authority =
                parent.map(|parent| AuthorityMementoRef::new(parent.cid.clone()));
            let signer_seed = parent.map(|parent| parent.seed).unwrap_or(seed);
            let args = MintAuthorityArgs {
                principal: principal.to_string(),
                key: key.clone(),
                scope_kind: scope_kind.to_string(),
                scope: scope.to_string(),
                parent_authority,
                produced_by: "sugar-cli".to_string(),
                produced_at: produced_at.clone(),
                signer_seed,
            };
            let minted =
                mint_authority(&args).map_err(|e| format!("mint authority `{id}`: {e}"))?;
            let authority_ref = AuthorityRef {
                cid: minted.cid.clone(),
                seed,
                principal: principal.to_string(),
            };
            if scope_kind == "proof" && proof_authority.is_none() {
                proof_authority = Some(authority_ref.clone());
            }
            if authorities_by_id
                .insert(id.to_string(), authority_ref)
                .is_some()
            {
                return Err(format!("duplicate authority `{id}`"));
            }
            push_graph_memento!(
                AuthorityMemento,
                push_authority,
                minted.cid.as_str(),
                minted.canonical_bytes
            );
        }
    }

    // Cross-file consistency conjoin (CLI-side, language-neutral).
    //
    // When the kit lifts a multi-file project, same-named EUF contracts from
    // DIFFERENT source files land as separate `ir` entries. Within a single
    // file the kit already coalesces them (e.g. layer2.py
    // `_coalesce_same_named_decls`), but that coalesce only runs per-file.
    // Without this pre-pass, `mint_ir_document` would mint TWO separate
    // contracts — each individually SAT — and the consistency pass checks
    // them independently, hiding the conjunction `=(t,1) ∧ =(t,2)` that
    // would be UNSAT.
    //
    // Scope: ONLY inv-only contracts (inv present, no nontrivial pre, no
    // post).  Bridge-bearing and pre/post contracts are NOT merged here;
    // they have different invariants about uniqueness that this transform
    // must not disturb (see merge_ir_document_responses comments).
    //
    // Algorithm (mirrors coalesce_decls_by_name / _coalesce_same_named_decls):
    //   - Group contract decls by name.  First-seen order preserved.
    //   - Identical-content same-name decls: dedup (one copy, not double-conjoin).
    //   - Distinct-content same-name inv-only decls: conjoin invs into
    //     `{"kind":"and","operands":[...]}`, flattening nested `and` nodes
    //     and deduping operands by JCS-canonical key.
    //   - Non-inv-only same-name decls: keep only the first (existing behaviour).
    // Non-contract ir entries (bridge, implication, etc.) pass through untouched.
    let ir_coalesced: Vec<Value> = {
        // Maps name -> (first_decl_index_in_ir_coalesced_so_far, is_inv_only, accumulated_inv_operands)
        // We work in two passes: first build the grouped structure, then emit.
        struct InvOnlyGroup {
            /// Clone of the first decl (template for out_binding, outBinding, etc.)
            template: Value,
            /// Canonical JCS keys of operands already added (for dedup)
            operand_keys: Vec<String>,
            /// The operand `serde_json::Value` list (in order, deduped)
            operands: Vec<Value>,
        }
        let mut inv_only_groups: std::collections::BTreeMap<String, InvOnlyGroup> =
            std::collections::BTreeMap::new();
        // Passthrough bucket: non-contract entries, and contract entries
        // that are NOT inv-only (pre/post-bearing or function-contract).
        // We preserve original order via a combined stream.
        enum CoalesceEntry {
            InvOnly(String),    // name key -> resolved from inv_only_groups
            Passthrough(Value), // emitted as-is
        }
        let mut stream: Vec<CoalesceEntry> = Vec::new();
        let mut inv_only_name_emitted: std::collections::HashSet<String> =
            std::collections::HashSet::new();

        for decl in ir {
            let kind = decl.get("kind").and_then(|v| v.as_str()).unwrap_or("");
            if kind != "contract" {
                // Non-contract (bridge, library-sugar-binding-entry, etc.) → passthrough
                stream.push(CoalesceEntry::Passthrough(decl.clone()));
                continue;
            }
            let name = decl
                .get("name")
                .or_else(|| decl.get("symbol"))
                .or_else(|| decl.get("fn_name"))
                .or_else(|| decl.get("fnName"))
                .and_then(|v| v.as_str())
                .unwrap_or("unnamed")
                .to_string();

            // A contract is inv-only if: has inv, no pre/precondition, no post/postcondition,
            // and kind == "contract" (not "function-contract").
            // `has_nontrivial_pre_json` is the same gate used in the main loop.
            let pre_val = decl.get("pre").or_else(|| decl.get("precondition"));
            let post_val = decl.get("post").or_else(|| decl.get("postcondition"));
            let inv_val = decl.get("inv").or_else(|| decl.get("invariant"));
            let is_inv_only = inv_val.is_some()
                && !pre_val.is_some_and(has_nontrivial_pre_json)
                && post_val.is_none();

            if !is_inv_only {
                // Pre/post-bearing contract → pass through untouched regardless of name
                stream.push(CoalesceEntry::Passthrough(decl.clone()));
                continue;
            }

            // inv-only contract — accumulate into the group for this name.
            let inv = inv_val.expect("inv_val is_some checked above");

            // Compute a canonical key for this operand to dedup byte-identical invs.
            let operand_key = encode_jcs(json_to_cvalue(inv).as_ref());

            if let Some(group) = inv_only_groups.get_mut(&name) {
                // Add this operand only if it is not already present (dedup by canonical bytes).
                if !group.operand_keys.iter().any(|k| k == &operand_key) {
                    group.operand_keys.push(operand_key);
                    group.operands.push(inv.clone());
                }
                // The stream slot was already added when the first decl for this name arrived.
            } else {
                // First decl for this name: create the group and add the stream slot.
                let group = InvOnlyGroup {
                    template: decl.clone(),
                    operand_keys: vec![operand_key],
                    operands: vec![inv.clone()],
                };
                inv_only_groups.insert(name.clone(), group);
                if inv_only_name_emitted.insert(name.clone()) {
                    stream.push(CoalesceEntry::InvOnly(name));
                }
            }
        }

        // Resolve the stream into the final coalesced IR.
        let mut result: Vec<Value> = Vec::with_capacity(ir.len());
        for entry in stream {
            match entry {
                CoalesceEntry::Passthrough(v) => result.push(v),
                CoalesceEntry::InvOnly(name) => {
                    if let Some(mut group) = inv_only_groups.remove(&name) {
                        // Build the (possibly conjoined) inv.
                        let merged_inv = if group.operands.len() == 1 {
                            group.operands.remove(0)
                        } else {
                            // Flatten any top-level `and` operands from each
                            // individual inv into a single flat `and` list,
                            // then dedup by canonical key.
                            let mut flat_operands: Vec<Value> = Vec::new();
                            let mut flat_keys: Vec<String> = Vec::new();
                            for op in group.operands {
                                // If this operand is itself `{kind:"and", operands:[...]}`,
                                // flatten its children rather than nesting another `and`.
                                let is_and = op.get("kind").and_then(|v| v.as_str()) == Some("and");
                                let children: Vec<Value> = if is_and {
                                    op.get("operands")
                                        .and_then(|v| v.as_array())
                                        .cloned()
                                        .unwrap_or_default()
                                } else {
                                    vec![op]
                                };
                                for child in children {
                                    let key = encode_jcs(json_to_cvalue(&child).as_ref());
                                    if !flat_keys.iter().any(|k| k == &key) {
                                        flat_keys.push(key);
                                        flat_operands.push(child);
                                    }
                                }
                            }
                            match flat_operands.len() {
                                0 => Value::Null,
                                1 => flat_operands.remove(0),
                                _ => json!({"kind": "and", "operands": flat_operands}),
                            }
                        };
                        // Emit the merged decl: clone the template and replace inv.
                        let mut merged_decl = group.template.clone();
                        if let Some(obj) = merged_decl.as_object_mut() {
                            obj.insert("inv".to_string(), merged_inv);
                            // Remove the alternate key if present (use canonical "inv").
                            obj.shift_remove("invariant");
                        }
                        result.push(merged_decl);
                    }
                }
            }
        }
        result
    };
    let ir = &ir_coalesced;

    for decl in ir {
        let kind = decl.get("kind").and_then(|v| v.as_str()).unwrap_or("");
        if kind != "contract" && kind != "function-contract" {
            continue;
        }

        let name = decl
            .get("name")
            .or_else(|| decl.get("symbol"))
            .or_else(|| decl.get("fn_name"))
            .or_else(|| decl.get("fnName"))
            .and_then(|v| v.as_str())
            .unwrap_or("unnamed")
            .to_string();
        let out_binding = decl
            .get("outBinding")
            .or_else(|| decl.get("out_binding"))
            .and_then(|v| v.as_str())
            .unwrap_or("out")
            .to_string();
        let pre_decl = decl.get("pre").or_else(|| decl.get("precondition"));
        let pre_body = pre_decl.cloned();
        let has_nontrivial_pre = pre_decl.is_some_and(has_nontrivial_pre_json);
        let pre = pre_decl.map(json_to_cvalue);
        let post_decl = decl.get("post").or_else(|| decl.get("postcondition"));
        let post_body = post_decl.cloned();
        let post = post_decl.map(json_to_cvalue);
        let inv = decl
            .get("inv")
            .or_else(|| decl.get("invariant"))
            .map(json_to_cvalue);

        if pre.is_none() && post.is_none() && inv.is_none() {
            continue;
        }

        // Body-derived op-contract slots (#1436/#1440): a `function-contract`
        // decl carries the function's `formals` (+ `formalSorts`), lifted by
        // walk / JavaSourceLifter from the method body. Carry them through so
        // the minted `kind:"contract"` memento's header bears them and
        // `body_discharge::CatalogResolver` can resolve the body-obligation.
        // Non-function `contract` decls have no formals; the vecs stay empty
        // and the minted bytes are unchanged.
        let formals_json = decl.get("formals").and_then(|v| v.as_array());
        let formals: Vec<String> = formals_json
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();
        let formals_binding = formals_json.map(|_| formals.clone());
        let formal_sorts_binding = decl
            .get("formalSorts")
            .or_else(|| decl.get("formal_sorts"))
            .and_then(|v| v.as_array())
            .cloned();
        let formal_sorts: Vec<std::sync::Arc<sugar_canonicalizer::Value>> = decl
            .get("formalSorts")
            .or_else(|| decl.get("formal_sorts"))
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().map(json_to_cvalue).collect())
            .unwrap_or_default();
        // PANIC-LOCUS PRESERVATION (#1745): the lifter stamps each panic-leaf
        // call's `{argTerm, file, line, col, callee}` on the function-contract
        // decl (walk_rpc `collect_panic_loci`). Carry them through verbatim so
        // the contract memento's header bears them and the verifier can
        // attribute each `method:unwrap` obligation to its own source line.
        // Carried as opaque provenance: the CLI does not interpret the terms.
        let panic_loci_value = decl.get("panicLoci").or_else(|| decl.get("panic_loci"));
        let panic_loci: Vec<Arc<CValue>> = match panic_loci_value {
            Some(Value::Array(arr)) => arr.iter().map(json_to_cvalue).collect(),
            Some(value) => {
                return Err(format!(
                    "contract `{name}`: panicLoci must be an array, got {}",
                    json_type_name(value)
                ));
            }
            None => Vec::new(),
        };
        let class_shapes_value = decl.get("classShapes").or_else(|| decl.get("class_shapes"));
        let class_shapes: Vec<Arc<CValue>> = match class_shapes_value {
            Some(Value::Array(arr)) => arr.iter().map(json_to_cvalue).collect(),
            Some(value) => {
                return Err(format!(
                    "contract `{name}`: classShapes must be an array, got {}",
                    json_type_name(value)
                ));
            }
            None => Vec::new(),
        };
        let source_warrants_value = decl
            .get("sourceWarrants")
            .or_else(|| decl.get("source_warrants"));
        match source_warrants_value {
            Some(Value::Array(arr)) => {
                for source_memento in arr {
                    let (cid, bytes) = mint_source_memento(source_memento, Some(&name))?;
                    push_graph_memento!(SourceMemento, push_source, cid.as_str(), bytes);
                }
            }
            Some(value) => {
                return Err(format!(
                    "contract `{name}`: sourceWarrants must be an array, got {}",
                    json_type_name(value)
                ));
            }
            None => {}
        }
        let body_policy = body_discharge_policy_from_fields(
            decl.get("bodyDischargeEligible")
                .or_else(|| decl.get("body_discharge_eligible")),
            decl.get("bodyDischargeRefusalReason")
                .or_else(|| decl.get("body_discharge_refusal_reason")),
            decl.get("dischargePolicy"),
        );
        log_body_discharge_policy_warnings("mint-ir-contract-decl", &name, &body_policy.warnings);
        let body_discharge_eligible = body_policy.body_discharge_eligible;
        let body_discharge_refusal_reason = body_policy.body_discharge_refusal_reason;
        // A bridge is written only when this contract is a body-bearing
        // function target: it carries a `post` AND an explicit `formals`
        // field. Presence is the marker, not non-emptiness: zero-arg
        // functions carry `formals: []` and are still body-bearing. The
        // bridge's `sourceSymbol` is the function's bare name as it appears
        // in harvested call ctors. For a v1 function contract the harvested
        // ctor uses the bare ident, so prefer the explicit
        // `bridgeSourceSymbol` if the lifter set one, else the function's
        // simple name.
        let bridge_source_symbol: Option<String> = if kind == "function-contract"
            && post.is_some()
            && formals_json.is_some()
            && body_discharge_eligible
        {
            Some(
                decl.get("bridgeSourceSymbol")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string())
                    .unwrap_or_else(|| simple_function_symbol(&name)),
            )
        } else {
            None
        };
        let authority = optional_str(decl, "authority")
            .map(|authority_id| {
                authorities_by_id.get(authority_id).ok_or_else(|| {
                    format!("contract `{name}` references missing authority `{authority_id}`")
                })
            })
            .transpose()?;
        let mut input_cids = string_array(decl, "inputCids", &name)?;
        if let Some(witness_cids) = witness_cids_by_contract.get(&name) {
            input_cids.extend(witness_cids.iter().cloned());
        }
        if let Some(authority) = authority {
            input_cids.push(authority.cid.clone());
        }
        let emit_empty_formals =
            kind == "function-contract" && formals_json.is_some() && formals.is_empty();
        let signer_seed = authority
            .map(|authority| authority.seed)
            .unwrap_or(default_signer_seed);
        let produced_by = authority
            .map(|authority| authority.principal.clone())
            .unwrap_or_else(|| "sugar-cli".to_string());

        // Tier-1 crate tag (Tier 2b enabler): the SEMANTIC library the kit
        // declares in `platform_profile.library` WINS. For the rust-std shim
        // that is `std` -- the crate a consumer's `opt.unwrap()` resolves to,
        // via the rust-analyzer oracle (`std`), and the key a cross-crate bridge
        // looks the target up by.
        //
        // The kit's rust-fn-contracts surface stamps each contract's `library`
        // with the CARGO PACKAGE NAME (`sugar_shim_rust_std`), which is NOT
        // the semantic library. Letting that stamp win split the shim's
        // `option_unwrap` across two keys: the PRE-bearing fn-contract under
        // `(sugar_shim_rust_std, option_unwrap)` and the post-only sugar
        // contract under `(std, option_unwrap)`. A call resolved to `std` then
        // found ONLY the post-only shell and vacuous-passed. So the declared
        // semantic library takes precedence; the per-decl stamp is the fallback
        // for kits that declare no `platform_profile.library`. Forwarded
        // OPAQUELY onto the contract metadata; the CLI does not interpret it.
        let library = project_library.clone().or_else(|| {
            decl.get("library")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(|s| s.to_string())
        });

        let args = MintContractArgs {
            contract_name: name,
            pre,
            post,
            inv,
            // Thread the lifted declaration's execution-witness EvidenceTerm (if
            // any) into the minted contract memento so `prove` can discharge it
            // by recompute. Omitted when absent -> non-witness contracts unchanged.
            evidence_term: decl.get("evidence").map(json_to_cvalue),
            out_binding,
            produced_by,
            produced_at: produced_at.clone(),
            input_cids,
            authoring: Authoring::Lift {
                lifter: "ir-document".to_string(),
                evidence: "minted from ir-document RPC response".to_string(),
                source_cid: None,
            },
            signer_seed,
            formals,
            emit_empty_formals,
            formal_sorts,
            library: library.clone(),
            body_discharge_eligible,
            body_discharge_refusal_reason: body_discharge_refusal_reason.clone(),
            panic_loci,
            class_shapes,
            source_warrants: Vec::new(),
        };

        let ccid = contract_cid(&args);
        let pre_hash = args.pre.as_ref().map(formula_hash);
        let post_hash = args.post.as_ref().map(formula_hash);
        let inv_hash = args.inv.as_ref().map(formula_hash);
        content_cids.push(ccid.clone());

        let contract_body = register_contract_body_graph(
            &mut proof_graph,
            args.pre.as_ref(),
            args.post.as_ref(),
            args.inv.as_ref(),
        )
        .map_err(|e| format!("contract `{}`: {e}", args.contract_name))?;
        let body_cid = contract_body.cid().as_str().to_string();
        let m = mint_contract_with_body_cid(&args, Some(&body_cid))
            .map_err(|e| format!("mint contract: {e}"))?;

        // Production bridge-writer (#1436/#1440, PR-23): for a body-derived
        // function contract, AUTOMATICALLY mint the bridge that points a
        // harvested call at this contract's body-obligation. This is the
        // pipeline that was missing -- `bind_function_bridge` existed but no
        // production verb called it, so verify could only reach the seam via
        // hand-built test bundles. The bridge's `targetContractCid` is this
        // contract's ATTESTATION CID (`m.cid`, the member key the verifier
        // indexes `pool.mementos` by), so `CatalogResolver` resolves the
        // chain. Language-neutral: it operates on the protocol's fields, not
        // on any source language.
        if let Some(source_symbol) = bridge_source_symbol.clone() {
            let bridge = mint_bridge(&MintBridgeArgs {
                produced_by: "sugar-cli".to_string(),
                produced_at: produced_at.clone(),
                source_symbol,
                source_layer: "source".to_string(),
                target_contract: ContractMementoRef::new(m.cid.clone()),
                target_layer: "kit".to_string(),
                ir_arg_sorts: vec![],
                ir_return_sort: String::new(),
                notes: "auto-minted body-discharge bridge (PR-23)".to_string(),
                signer_seed,
                // Self-pinned: this contract is a co-member of the very bundle
                // being minted, so there is no external bundle CID to name
                // (and it can't reference its own not-yet-computed CID). The
                // verifier enforces same-bundle co-membership for the None case.
                target_proof_cid: None,
                // Function-level body-discharge bridge, not a per-call panic
                // site: no call-site provenance to carry.
                callsite: None,
            });
            push_graph_memento!(
                BridgeMemento,
                push_bridge,
                bridge.cid.as_str(),
                bridge.canonical_bytes
            );
        }

        // Index by CONTENT CID. A re-emission of a byte-identical contract
        // (same CID) is a genuine no-op dedup, not an error: the merge dedup
        // already collapses identical shapes, and `members` `or_insert` is
        // idempotent. Two DIFFERENT shapes sharing a name now both land here
        // under their distinct CIDs -- which is the whole point.
        contracts_by_cid
            .entry(m.cid.clone())
            .or_insert(MintedContractRef {
                contract_name: args.contract_name.clone(),
                attestation_cid: m.cid.clone(),
                pre_hash,
                post_hash,
                inv_hash,
                pre_body,
                post_body,
                has_nontrivial_pre,
                body_discharge_eligible,
                body_discharge_refusal_reason,
                library,
                bridge_source_symbol,
                formals: formals_binding,
                formal_sorts: formal_sorts_binding,
            });
        let name_cids = cids_by_name.entry(args.contract_name.clone()).or_default();
        if !name_cids.contains(&m.cid) {
            name_cids.push(m.cid.clone());
        }

        push_graph_memento!(
            ClaimContractMemento,
            push_claim_contract,
            m.cid.as_str(),
            m.canonical_bytes
        );
    }

    // #1358 / #1355: stamp the project's platform_profile onto each
    // realization-bearing IR entry so absent annotation axes get filled in
    // from the shim's single declarative profile. Annotation pins always
    // win; this only fills floating axes.
    let cfg = read_project_config(project_root);
    if let Some(profile) = cfg.platform_profile.as_ref() {
        let mut stamped: Vec<Value> = ir.iter().cloned().collect();
        stamp_platform_profile(&mut stamped, profile);
        for decl in &stamped {
            match decl.get("kind").and_then(|v| v.as_str()) {
                Some("library-sugar-binding-entry") => {
                    let (cid, bytes) = mint_library_sugar_binding_entry(decl)?;
                    push_graph_memento!(
                        LibrarySugarBindingMemento,
                        push_library_sugar_binding,
                        cid.as_str(),
                        bytes
                    );
                }
                Some("witness-memento") => {
                    let (cid, bytes) = mint_witness_memento(decl)?;
                    push_graph_memento!(WitnessMemento, push_witness, cid.as_str(), bytes);
                }
                Some("bridge") => {
                    let (cid, bytes) =
                        mint_bridge_from_decl(decl, &produced_at, default_signer_seed)?;
                    push_graph_memento!(BridgeMemento, push_bridge, cid.as_str(), bytes);
                }
                _ => {}
            }
        }
    } else {
        for decl in ir {
            match decl.get("kind").and_then(|v| v.as_str()) {
                Some("library-sugar-binding-entry") => {
                    let (cid, bytes) = mint_library_sugar_binding_entry(decl)?;
                    push_graph_memento!(
                        LibrarySugarBindingMemento,
                        push_library_sugar_binding,
                        cid.as_str(),
                        bytes
                    );
                }
                Some("witness-memento") => {
                    let (cid, bytes) = mint_witness_memento(decl)?;
                    push_graph_memento!(WitnessMemento, push_witness, cid.as_str(), bytes);
                }
                Some("bridge") => {
                    let (cid, bytes) =
                        mint_bridge_from_decl(decl, &produced_at, default_signer_seed)?;
                    push_graph_memento!(BridgeMemento, push_bridge, cid.as_str(), bytes);
                }
                _ => {}
            }
        }
    }

    if proof_member_cids.is_empty() {
        return Err("no contracts to mint".to_string());
    }

    if let Some(implications) = implications {
        for implication in implications {
            let name = implication
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or("unnamed-implication");
            let antecedent_name = required_str(implication, "antecedent", name)?;
            let consequent_name = required_str(implication, "consequent", name)?;
            let antecedent_slot = optional_str(implication, "antecedentSlot").unwrap_or("post");
            let consequent_slot = optional_str(implication, "consequentSlot").unwrap_or("post");

            // Resolve a contract by name to its CONTENT CID, then index by CID.
            // A name may now resolve to several distinct shapes; pick the one
            // that actually carries the slot this implication references (e.g.
            // a `post`-slot antecedent needs the contract whose CID carries a
            // post). This keeps name a convenience for authoring while identity
            // stays the CID. Ambiguity that the slot does not resolve is a hard
            // error, never a silent pick.
            let resolve_by_slot = |ref_name: &str, slot: &str| -> Option<&MintedContractRef> {
                cids_by_name.get(ref_name).and_then(|cids| {
                    cids.iter()
                        .filter_map(|cid| contracts_by_cid.get(cid))
                        .find(|c| c.slot_hash(slot).is_some())
                        // Fall back to the first shape under this name when the
                        // slot is absent everywhere (the error is raised below
                        // on the missing slot, with a clear message).
                        .or_else(|| cids.first().and_then(|cid| contracts_by_cid.get(cid)))
                })
            };
            let antecedent =
                resolve_by_slot(antecedent_name, antecedent_slot).ok_or_else(|| {
                    format!("implication `{name}` references missing contract `{antecedent_name}`")
                })?;
            let consequent =
                resolve_by_slot(consequent_name, consequent_slot).ok_or_else(|| {
                    format!("implication `{name}` references missing contract `{consequent_name}`")
                })?;
            let antecedent_hash = antecedent.slot_hash(antecedent_slot).ok_or_else(|| {
                format!(
                    "implication `{name}` references missing slot `{antecedent_slot}` on contract `{antecedent_name}`"
                )
            })?;
            let consequent_hash = consequent.slot_hash(consequent_slot).ok_or_else(|| {
                format!(
                    "implication `{name}` references missing slot `{consequent_slot}` on contract `{consequent_name}`"
                )
            })?;
            let authority = optional_str(implication, "authority")
                .map(|authority_id| {
                    authorities_by_id.get(authority_id).ok_or_else(|| {
                        format!(
                            "implication `{name}` references missing authority `{authority_id}`"
                        )
                    })
                })
                .transpose()?;
            let additional_inputs = authority
                .map(|authority| vec![AuthorityMementoRef::new(authority.cid.clone())])
                .unwrap_or_default();
            let signer_seed = authority
                .map(|authority| authority.seed)
                .unwrap_or(default_signer_seed);
            let produced_by = authority
                .map(|authority| authority.principal.clone())
                .unwrap_or_else(|| "sugar-cli".to_string());

            let args = MintImplicationArgs {
                produced_by,
                produced_at: produced_at.clone(),
                antecedent_hash: antecedent_hash.to_string(),
                consequent_hash: consequent_hash.to_string(),
                antecedent: ContractMementoRef::new(antecedent.attestation_cid.clone()),
                consequent: ContractMementoRef::new(consequent.attestation_cid.clone()),
                additional_inputs,
                antecedent_slot: antecedent_slot.to_string(),
                consequent_slot: consequent_slot.to_string(),
                prover: optional_str(implication, "prover")
                    .unwrap_or("bridgeworks-white-room")
                    .to_string(),
                prover_run_ms: implication
                    .get("proverRunMs")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0),
                smt_lib_input: optional_str(implication, "solverInput")
                    .or_else(|| optional_str(implication, "smtLibInput"))
                    .unwrap_or("")
                    .to_string(),
                proof_witness: optional_str(implication, "proofWitness")
                    .unwrap_or(name)
                    .to_string(),
                signer_seed,
            };

            let m = mint_implication(&args);
            push_graph_memento!(
                ImplicationMemento,
                push_implication,
                m.cid.as_str(),
                m.canonical_bytes
            );
        }
    }

    let contract_set_cid = compute_contract_set_cid(content_cids);
    let contract_bindings: Vec<Value> = contracts_by_cid
        .values()
        .map(|contract| {
            // One binding per distinct CONTRACT SHAPE (CID), not per name. When
            // a name has both a post-only sugar shape and a pre-bearing
            // fn-contract shape, BOTH bindings are emitted here; the implication
            // lifter's `contracts_by_key` then upgrades to the body-bearing one
            // (never downgrades), so a call site bridges to the dischargeable
            // contract instead of vacuous-passing against the post-only shell.
            //
            // body_bearing distinguishes a production function-contract
            // (carries a derived `pre` and/or `post` -> a call site has a
            // real obligation to discharge) from a test-lifted witnessed
            // fact (carries only `inv` -> nothing for a general call site
            // to prove).
            let name = &contract.contract_name;
            let has_pre = contract.has_nontrivial_pre;
            let has_post = contract.post_hash.is_some();
            let body_bearing = (has_pre || has_post) && contract.body_discharge_eligible;
            let mut binding = json!({
                "name": name,
                "contract_cid": contract.attestation_cid.clone(),
                "body_bearing": body_bearing,
                "has_pre": has_pre,
                "has_post": has_post,
                "bodyDischargeEligible": contract.body_discharge_eligible,
                "bodyDischargeRefusalReason": contract.body_discharge_refusal_reason.clone(),
                "bridgeSourceSymbol": contract.bridge_source_symbol.clone(),
                // Crate tag (Tier 1): lets the implication lifter key this
                // producer contract by (crate, leaf). Omitted when the lifter
                // did not stamp one (the matcher then defaults to the current
                // crate, which is correct for a producer contract).
                "library": contract.library.clone(),
            });
            if let Some(formals) = &contract.formals {
                binding["formals"] = json!(formals);
            }
            if let Some(formal_sorts) = &contract.formal_sorts {
                binding["formalSorts"] = Value::Array(formal_sorts.clone());
            }
            if let Some(pre) = &contract.pre_body {
                binding["pre"] = pre.clone();
            }
            if let Some(post) = &contract.post_body {
                binding["post"] = post.clone();
            }
            binding
        })
        .collect();

    let (proof_signer, proof_signer_seed) = if let Some(authority) = proof_authority {
        (authority.cid, authority.seed)
    } else {
        (
            ed25519_pubkey_string(&default_signer_seed),
            default_signer_seed,
        )
    };

    // THE VENDOR TIE: record the set of dependency .proof CIDs this bundle was
    // conjoined against (the bundles in .sugar/imports/). The conjoining itself
    // happens in the verification pool by name-coalesce; this metadata records
    // WHICH dep bundle CIDs were in that pool, so the vendor bundle's IDENTITY
    // commits to its dependency set. Change a dep's bytes -> its CID changes ->
    // this manifest changes -> the vendor's bundle CID changes. The tie is
    // recompute-not-trust: re-mint against the same imports yields the same CID,
    // against a different dep yields a different one. Sorted+deduped for a
    // deterministic, order-independent commitment. Metadata is in the envelope
    // CID but non-normative (verifiers don't use it for logic) -- exactly right,
    // since the verdict already came from the conjoined pool; this only ties the
    // identity to the dependency set.
    let conjoined_imports = read_conjoined_import_cids(project_root);
    let metadata = if conjoined_imports.is_empty() {
        None
    } else {
        let mut m = std::collections::BTreeMap::new();
        m.insert(
            "sugar.conjoinedImports".to_string(),
            conjoined_imports.join(","),
        );
        Some(m)
    };

    let proof_input = ProofEnvelopeInput {
        name: "ir-document".to_string(),
        version: "1.0.0".to_string(),
        binary_cid: None,
        metadata,
        graph: proof_graph,
        signer_cid: proof_signer,
        signer_seed: proof_signer_seed,
        declared_at: produced_at,
    };

    let built = build_proof_envelope(&proof_input);

    Ok(MintedIrDocument {
        bytes: built.bytes,
        filename_cid: built.cid,
        contract_set_cid,
        contract_bindings,
    })
}

fn mint_library_sugar_binding_entry(decl: &Value) -> Result<(String, Vec<u8>), String> {
    let target_language = required_str(decl, "target_language", "library-sugar-binding-entry")?;
    let target_library_tag =
        required_str(decl, "target_library_tag", "library-sugar-binding-entry")?;
    // Identity is symbol-keyed when a library symbol exists; otherwise the
    // canonical op CID is the sole operator identity.
    let symbol = decl
        .get("symbol")
        .and_then(|v| v.as_str())
        .filter(|s| !s.trim().is_empty());
    let op_cid = decl
        .get("op_cid")
        .or_else(|| decl.get("opCid"))
        .and_then(|v| v.as_str())
        .filter(|s| !s.trim().is_empty());
    if symbol.is_none() && op_cid.is_none() {
        return Err("`library-sugar-binding-entry` missing `symbol` or `op_cid`".to_string());
    }
    let signature_shape_cid =
        required_str(decl, "signature_shape_cid", "library-sugar-binding-entry")?;
    let body_source = decl
        .get("body_source")
        .ok_or_else(|| "`library-sugar-binding-entry` missing `body_source`".to_string())?;
    let source_cid = required_str(body_source, "source_cid", "body_source")?;

    let mut header = serde_json::Map::new();
    header.insert("bodySourceCid".to_string(), json!(source_cid));
    header.insert("kind".to_string(), json!("library-sugar-binding-entry"));
    if let Some(op_cid) = op_cid {
        header.insert("opCid".to_string(), json!(op_cid));
    }
    header.insert("signatureShapeCid".to_string(), json!(signature_shape_cid));
    if let Some(symbol) = symbol {
        header.insert("symbol".to_string(), json!(symbol));
    }
    header.insert("targetLanguage".to_string(), json!(target_language));
    header.insert("targetLibraryTag".to_string(), json!(target_library_tag));

    let envelope = json!({
        "body": decl,
        "header": Value::Object(header),
        "schemaVersion": "1",
    });
    let canonical = encode_jcs(&json_to_cvalue(&envelope));
    let cid = blake3_512_of(canonical.as_bytes());
    Ok((cid, canonical.into_bytes()))
}

/// Mint a `witness-memento` into the envelope: the kit's SIGNED POINTER to a
/// witness (test run, CI log, compiler report, poem -- arbitrary content), CID +
/// signature, ZERO body. The body lives in a separately-deployed witness package.
/// The rust verifier enumerates these, RPC-resolves each body from the kit
/// oracle, blake3's the bytes itself, and audits against `witnessCid` -- so the
/// .proof carries only the signed identity, not the run record.
fn mint_witness_memento(decl: &Value) -> Result<(String, Vec<u8>), String> {
    let witness_cid = required_str(decl, "witness_cid", "witness-memento")?;
    let signer = required_str(decl, "signer", "witness-memento")?;
    let signature = required_str(decl, "signature", "witness-memento")?;
    // Fail closed on EMPTY load-bearing fields. `required_str` enforces presence
    // but not non-emptiness; an empty witnessCid/signer/signature is not a witness.
    for (field, value) in [
        ("witness_cid", witness_cid),
        ("signer", signer),
        ("signature", signature),
    ] {
        if value.trim().is_empty() {
            return Err(format!("`witness-memento` missing non-empty `{field}`"));
        }
    }
    let witness_kind = optional_str(decl, "witness_kind").unwrap_or("witness");
    let envelope = json!({
        "body": decl,
        "header": {
            "kind": "witness-memento",
            "signer": signer,
            "witnessCid": witness_cid,
            "witnessKind": witness_kind,
        },
        "schemaVersion": "1",
    });
    let canonical = encode_jcs(&json_to_cvalue(&envelope));
    let cid = blake3_512_of(canonical.as_bytes());
    Ok((cid, canonical.into_bytes()))
}

fn mint_plan_memento(decl: &Value) -> Result<(String, Vec<u8>, Vec<FlatAtom>), String> {
    let mut body = decl
        .get("plan_memento")
        .or_else(|| decl.get("planMemento"))
        .cloned()
        .unwrap_or_else(|| decl.clone());
    let raw_plan_atoms = body
        .as_object_mut()
        .ok_or_else(|| "`plan-memento` must be an object".to_string())?
        .remove("planAtoms")
        .or_else(|| {
            body.as_object_mut()
                .and_then(|object| object.remove("plan_atoms"))
        });
    let mut plan_atoms = Vec::new();
    let mut plan_atom_refs = Vec::new();
    if let Some(raw_plan_atoms) = raw_plan_atoms {
        let raw_plan_atoms = raw_plan_atoms
            .as_array()
            .ok_or_else(|| "`plan-memento.planAtoms` must be an array".to_string())?;
        for raw_atom in raw_plan_atoms {
            let mut atom = raw_atom
                .get("planAtom")
                .or_else(|| raw_atom.get("plan_atom"))
                .cloned()
                .unwrap_or_else(|| raw_atom.clone());
            let atom_obj = atom
                .as_object_mut()
                .ok_or_else(|| "`plan-memento.planAtoms[]` must be an object".to_string())?;
            atom_obj
                .entry("kind".to_string())
                .or_insert_with(|| json!("plan-atom"));
            if atom_obj.get("kind").and_then(Value::as_str) != Some("plan-atom") {
                return Err("`plan-memento.planAtoms[].kind` must be `plan-atom`".to_string());
            }
            atom_obj
                .entry("schemaVersion".to_string())
                .or_insert_with(|| json!("1"));
            let flat_atom = FlatAtom::new(json_to_cvalue(&atom));
            let atom_cid = flat_atom.cid().as_str().to_string();
            plan_atom_refs.push(json!({
                "kind": "atom-memento",
                "atomCid": atom_cid,
            }));
            plan_atoms.push(flat_atom);
        }
    }

    let body_obj = body
        .as_object_mut()
        .ok_or_else(|| "`plan-memento` must be an object".to_string())?;
    if !plan_atom_refs.is_empty() {
        let plan_atom_cids = plan_atom_refs
            .iter()
            .filter_map(|reference| reference.get("atomCid").and_then(Value::as_str))
            .map(|cid| json!(cid))
            .collect::<Vec<_>>();
        body_obj.insert("planAtoms".to_string(), Value::Array(plan_atom_refs));
        body_obj.insert("planAtomCids".to_string(), Value::Array(plan_atom_cids));
    }
    body_obj
        .entry("kind".to_string())
        .or_insert_with(|| json!("component-plan"));
    if body_obj.get("kind").and_then(Value::as_str) != Some("component-plan") {
        return Err("`plan-memento.kind` must be `component-plan`".to_string());
    }
    body_obj
        .entry("schemaVersion".to_string())
        .or_insert_with(|| json!("1"));
    let expected = body_obj
        .get("expectedOutputCids")
        .or_else(|| body_obj.get("expected_output_cids"))
        .and_then(Value::as_array)
        .ok_or_else(|| "`plan-memento` missing `expectedOutputCids` array".to_string())?;
    for cid in expected {
        let cid = cid.as_str().ok_or_else(|| {
            "`plan-memento.expectedOutputCids` entries must be strings".to_string()
        })?;
        if !cid.starts_with("blake3-512:") {
            return Err(format!(
                "`plan-memento.expectedOutputCids` entry must be a prefixed CID, got `{cid}`"
            ));
        }
    }

    let plan_canonical = encode_jcs(&json_to_cvalue(&body));
    let plan_cid = blake3_512_of(plan_canonical.as_bytes());
    let envelope = json!({
        "body": body,
        "header": {
            "kind": "plan-memento",
            "planCid": plan_cid,
        },
        "schemaVersion": "1",
    });
    let canonical = encode_jcs(&json_to_cvalue(&envelope));
    let cid = blake3_512_of(canonical.as_bytes());
    Ok((cid, canonical.into_bytes(), plan_atoms))
}

fn mint_source_memento(
    decl: &Value,
    default_contract_name: Option<&str>,
) -> Result<(String, Vec<u8>), String> {
    let mut body = decl
        .get("source_memento")
        .or_else(|| decl.get("sourceMemento"))
        .cloned()
        .unwrap_or_else(|| decl.clone());
    let body_obj = body
        .as_object_mut()
        .ok_or_else(|| "`source-memento` must be an object".to_string())?;
    body_obj
        .entry("kind".to_string())
        .or_insert_with(|| json!("source-memento"));
    if body_obj.get("kind").and_then(Value::as_str) != Some("source-memento") {
        return Err("`source-memento.kind` must be `source-memento`".to_string());
    }
    for forbidden in ["body_text", "ast_template", "bodyText", "astTemplate"] {
        if body_obj.contains_key(forbidden) {
            return Err(format!(
                "`source-memento` must be lean; forbidden inline field `{forbidden}` present"
            ));
        }
    }
    for field in [
        "role",
        "universe_kind",
        "table_name",
        "contractName",
        "claimName",
        "eufName",
    ] {
        if !body_obj.contains_key(field) {
            if let Some(value) = decl.get(field).cloned() {
                body_obj.insert(field.to_string(), value);
            }
        }
    }
    if let Some(contract_name) = default_contract_name {
        body_obj
            .entry("contractName".to_string())
            .or_insert_with(|| json!(contract_name));
        body_obj
            .entry("claimName".to_string())
            .or_insert_with(|| json!(contract_name));
    }
    let source_cid = body_obj
        .get("source_cid")
        .or_else(|| body_obj.get("sourceCid"))
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| "`source-memento` missing non-empty `source_cid`".to_string())?
        .to_string();

    let mut header = serde_json::Map::new();
    header.insert("kind".to_string(), json!("source-memento"));
    header.insert("sourceCid".to_string(), json!(source_cid));
    for (header_field, body_field) in [
        ("claimName", "claimName"),
        ("contractName", "contractName"),
        ("eufName", "eufName"),
        ("file", "file"),
        ("role", "role"),
        ("sourceFunctionName", "source_function_name"),
        ("universeKind", "universe_kind"),
    ] {
        if let Some(value) = body_obj.get(body_field).cloned() {
            header.insert(header_field.to_string(), value);
        }
    }

    let envelope = json!({
        "body": body,
        "header": Value::Object(header),
        "schemaVersion": "1",
    });
    let canonical = encode_jcs(&json_to_cvalue(&envelope));
    let cid = blake3_512_of(canonical.as_bytes());
    Ok((cid, canonical.into_bytes()))
}

fn mint_factory_walk_memento(row: &Value) -> Result<(String, Vec<u8>), String> {
    let mut body = row
        .as_object()
        .cloned()
        .ok_or_else(|| "`factory-walk-row` must be an object".to_string())?;
    for forbidden in ["source", "term", "site"] {
        if body.contains_key(forbidden) {
            return Err(format!(
                "`factory-walk-row` must carry SourceMemento pins only; forbidden inline field `{forbidden}` present"
            ));
        }
    }
    if !body.contains_key("sourceMemento") {
        return Err("`factory-walk-row` missing `sourceMemento`".to_string());
    }
    body.entry("kind".to_string())
        .or_insert_with(|| json!("factory-walk-row"));
    if body.get("kind").and_then(Value::as_str) != Some("factory-walk-row") {
        return Err("`factory-walk-row.kind` must be `factory-walk-row`".to_string());
    }

    let source_memento = body
        .get("sourceMemento")
        .and_then(Value::as_object)
        .ok_or_else(|| "`factory-walk-row.sourceMemento` must be an object".to_string())?;
    let mut header = serde_json::Map::new();
    header.insert("kind".to_string(), json!("factory-walk-memento"));
    for field in ["file", "line", "status", "verdict", "output", "selected"] {
        if let Some(value) = body.get(field).cloned() {
            header.insert(field.to_string(), value);
        }
    }
    for (header_field, body_field) in [
        ("sourceFunctionName", "sourceFunctionName"),
        ("sourceFunctionName", "source_function_name"),
        ("contractName", "contractName"),
        ("contractName", "contract_name"),
        ("claimName", "claimName"),
        ("claimName", "claim_name"),
    ] {
        if !header.contains_key(header_field) {
            if let Some(value) = source_memento.get(body_field).cloned() {
                header.insert(header_field.to_string(), value);
            }
        }
    }

    let envelope = json!({
        "body": Value::Object(body),
        "header": Value::Object(header),
        "schemaVersion": "1",
    });
    let canonical = encode_jcs(&json_to_cvalue(&envelope));
    let cid = blake3_512_of(canonical.as_bytes());
    Ok((cid, canonical.into_bytes()))
}

fn mint_assertion_surface_memento(row: &Value) -> Result<(String, Vec<u8>), String> {
    let mut body = row
        .as_object()
        .cloned()
        .ok_or_else(|| "`assertion-surface-audit` must be an object".to_string())?;
    for forbidden in [
        "source",
        "term",
        "site",
        "body_text",
        "ast_template",
        "bodyText",
        "astTemplate",
    ] {
        if body.contains_key(forbidden) {
            return Err(format!(
                "`assertion-surface-audit` must carry SourceMemento pins only; forbidden inline field `{forbidden}` present"
            ));
        }
    }
    body.entry("kind".to_string())
        .or_insert_with(|| json!("assertion-surface-audit"));
    if body.get("kind").and_then(Value::as_str) != Some("assertion-surface-audit") {
        return Err("`assertion-surface-audit.kind` must be `assertion-surface-audit`".to_string());
    }

    let mut header = serde_json::Map::new();
    header.insert("kind".to_string(), json!("assertion-surface-memento"));
    for field in [
        "surface",
        "file",
        "line",
        "col",
        "status",
        "sourceStatus",
        "assertionSource",
    ] {
        if let Some(value) = body.get(field).cloned() {
            header.insert(field.to_string(), value);
        }
    }
    if let Some(source_memento) = body.get("sourceMemento").and_then(Value::as_object) {
        for (header_field, body_field) in [
            ("sourceCid", "source_cid"),
            ("sourceCid", "sourceCid"),
            ("claimName", "claimName"),
            ("contractName", "contractName"),
            ("sourceFunctionName", "sourceFunctionName"),
            ("sourceFunctionName", "source_function_name"),
        ] {
            if !header.contains_key(header_field) {
                if let Some(value) = source_memento.get(body_field).cloned() {
                    header.insert(header_field.to_string(), value);
                }
            }
        }
    }
    if !header.contains_key("contractName") {
        if let Some(contract) = body
            .get("facts")
            .and_then(Value::as_array)
            .and_then(|facts| facts.first())
            .and_then(|fact| {
                fact.get("contract")
                    .or_else(|| fact.get("contractName"))
                    .or_else(|| fact.get("contract_name"))
            })
            .cloned()
        {
            header.insert("contractName".to_string(), contract);
        }
    }

    let envelope = json!({
        "body": Value::Object(body),
        "header": Value::Object(header),
        "schemaVersion": "1",
    });
    let canonical = encode_jcs(&json_to_cvalue(&envelope));
    let cid = blake3_512_of(canonical.as_bytes());
    Ok((cid, canonical.into_bytes()))
}

/// Reduce a function-contract `fnName` to the bare symbol a harvested call
/// ctor uses. Rust walk emits the bare ident already (`double`), so this is
/// the identity. Java's `JavaSourceLifter` emits a fully-qualified mangled
/// name (`com.example.Foo.doubleIt(int)`); the harvested junit assertion
/// ctor is the bare method name (`doubleIt`). Strip any parameter
/// signature, then take the last dot-segment. This is the bridge
/// `sourceSymbol`, which must equal the call ctor name for
/// `enumerate_callsites` to match.
fn simple_function_symbol(fn_name: &str) -> String {
    let without_params = fn_name.split('(').next().unwrap_or(fn_name);
    without_params
        .rsplit('.')
        .next()
        .unwrap_or(without_params)
        .to_string()
}

fn optional_str<'a>(value: &'a Value, field: &str) -> Option<&'a str> {
    value.get(field).and_then(|v| v.as_str())
}

fn required_str<'a>(value: &'a Value, field: &str, context: &str) -> Result<&'a str, String> {
    optional_str(value, field).ok_or_else(|| format!("`{context}` missing `{field}`"))
}

fn formula_hash(formula: &Arc<CValue>) -> String {
    blake3_512_of(encode_jcs(formula).as_bytes())
}

fn register_contract_body_graph(
    proof_graph: &mut ProofGraph,
    pre: Option<&Arc<CValue>>,
    post: Option<&Arc<CValue>>,
    inv: Option<&Arc<CValue>>,
) -> Result<ContractBody, String> {
    let mut slots: Vec<(&'static str, AtomMemento)> = Vec::new();
    if let Some(formula) = pre {
        slots.push((
            "pre",
            proof_graph.register_atom(FlatAtom::new(formula.clone())),
        ));
    }
    if let Some(formula) = post {
        slots.push((
            "post",
            proof_graph.register_atom(FlatAtom::new(formula.clone())),
        ));
    }
    if let Some(formula) = inv {
        slots.push((
            "inv",
            proof_graph.register_atom(FlatAtom::new(formula.clone())),
        ));
    }
    if slots.is_empty() {
        return Err("contract body graph requires at least one formula slot".to_string());
    }

    let slot_refs = slots
        .iter()
        .map(|(slot, atom)| (*slot, atom))
        .collect::<Vec<_>>();
    Ok(proof_graph.register_body(ContractBody::from_slots(slot_refs)))
}

fn string_array(value: &Value, field: &str, context: &str) -> Result<Vec<String>, String> {
    let Some(values) = value.get(field) else {
        return Ok(Vec::new());
    };
    let array = values
        .as_array()
        .ok_or_else(|| format!("`{context}` field `{field}` must be an array"))?;
    array
        .iter()
        .map(|entry| {
            entry
                .as_str()
                .map(str::to_string)
                .ok_or_else(|| format!("`{context}` field `{field}` must contain only strings"))
        })
        .collect()
}

fn emit_witnesses_by_contract(
    witnesses: Option<&Vec<Value>>,
    project_root: &Path,
    out_dir: &Path,
    quiet: bool,
) -> Result<BTreeMap<String, Vec<String>>, String> {
    let mut by_contract: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let Some(witnesses) = witnesses else {
        return Ok(by_contract);
    };
    for witness in witnesses {
        let attach_to = required_str(witness, "attachTo", "witness requirement")?;
        let emitted =
            crate::cmd_emit::emit_witness_requirement(project_root, witness, out_dir, quiet)
                .map_err(|e| format!("ORP witness failed: {attach_to}\n{e}"))?;
        by_contract
            .entry(attach_to.to_string())
            .or_default()
            .push(emitted.filename_cid);
    }
    Ok(by_contract)
}

fn deterministic_signer_seed(principal: &str) -> Ed25519Seed {
    let digest = blake3_512_of(format!("sugar-signer:{principal}").as_bytes());
    let hex = digest
        .strip_prefix("blake3-512:")
        .expect("blake3_512_of returns tagged digest");
    let mut seed = [0u8; 32];
    for (idx, slot) in seed.iter_mut().enumerate() {
        let hi = hex_nibble(hex.as_bytes()[idx * 2]);
        let lo = hex_nibble(hex.as_bytes()[idx * 2 + 1]);
        *slot = (hi << 4) | lo;
    }
    seed
}

fn hex_nibble(byte: u8) -> u8 {
    match byte {
        b'0'..=b'9' => byte - b'0',
        b'a'..=b'f' => byte - b'a' + 10,
        b'A'..=b'F' => byte - b'A' + 10,
        _ => 0,
    }
}

/// Convert `serde_json::Value` to `sugar_canonicalizer::Value`.
fn json_to_cvalue(j: &Value) -> Arc<CValue> {
    match j {
        Value::Null => CValue::null(),
        Value::Bool(b) => CValue::boolean(*b),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                CValue::integer(i128::from(i))
            } else if let Some(u) = n.as_u64() {
                CValue::integer(i128::from(u))
            } else if let Some(f) = n.as_f64() {
                CValue::integer(f as i128)
            } else {
                CValue::integer(0)
            }
        }
        Value::String(s) => CValue::string(s.clone()),
        Value::Array(items) => {
            let v: Vec<_> = items.iter().map(|x| json_to_cvalue(x)).collect();
            CValue::array(v)
        }
        Value::Object(map) => {
            let entries: Vec<(String, Arc<CValue>)> = map
                .iter()
                .map(|(k, v)| (k.clone(), json_to_cvalue(v)))
                .collect();
            CValue::object(entries)
        }
    }
}

// ---------------------------------------------------------------------------
// MintArgs + run
// ---------------------------------------------------------------------------

#[derive(Parser, Debug, Clone)]
pub struct MintArgs {
    /// Project root containing `.sugar/config.toml`. Defaults to current dir.
    #[arg(long)]
    pub project: Option<PathBuf>,
    /// Project-configured kit shortcut from `[[kits]]` in `.sugar/config.toml`
    /// or user config.
    #[arg(long, conflicts_with = "project")]
    pub kit: Option<String>,
    /// Override the authoring surface (otherwise read from config or derived from --kit).
    #[arg(long)]
    pub surface: Option<String>,
    /// Ask the configured lifter for proof-producing host-language library-sugar bindings.
    #[arg(long)]
    pub library_bindings: bool,
    /// Output directory for the produced `.proof` file. Defaults to current dir.
    #[arg(long)]
    pub out: Option<PathBuf>,
    #[command(flatten)]
    pub flags: OutputFlags,
}

pub fn run(args: MintArgs) -> u8 {
    let _span = tracing::info_span!("cmd_mint").entered();
    info!(
        kit = args.kit.as_deref().unwrap_or("(none)"),
        surface = args.surface.as_deref().unwrap_or("(none)"),
        "mint: starting"
    );
    // Resolve (project_root, surface) from --kit or --project.
    let (project_root, derived_surface, _lang_key) = if let Some(kit) = &args.kit {
        let config_root = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let alias_project_cfg = read_project_config(&config_root);
        let alias_user_cfg = read_user_config();
        match resolve_kit_from_configs(kit, &config_root, &alias_project_cfg, &alias_user_cfg) {
            Some(resolved) => (
                resolved.project_root,
                Some(resolved.surface),
                Some(resolved.lang_key),
            ),
            None => {
                let aliases =
                    configured_kit_alias_names_from_configs(&alias_project_cfg, &alias_user_cfg);
                eprintln!("{}", format_unknown_kit_error(kit, &aliases));
                return EXIT_USER_ERROR;
            }
        }
    } else {
        let path = args.project.clone().unwrap_or_else(|| PathBuf::from("."));
        (path, None, None)
    };

    if !project_root.exists() {
        eprintln!(
            "{}: project not found: {}",
            "error".red().bold(),
            project_root.display()
        );
        return EXIT_USER_ERROR;
    }

    let project_cfg = read_project_config(&project_root);
    let user_cfg = read_user_config();
    let configured_path = if args.kit.is_none() && args.surface.is_none() && args.out.is_none() {
        project_cfg
            .path_for("mint")
            .or_else(|| user_cfg.path_for("mint"))
    } else {
        None
    };

    let session = if let Some(path_file) = configured_path {
        dispatch_path(&project_root, Path::new(&path_file))
    } else if args.surface.is_none()
        && derived_surface.is_none()
        && project_cfg.plugins.iter().any(PluginEntry::is_lift_plugin)
    {
        let lift_plugins = project_cfg
            .plugins
            .iter()
            .filter(|plugin| plugin.is_lift_plugin())
            .cloned()
            .collect::<Vec<_>>();
        // Multi-plugin path: config.toml declared lift `[[plugins]]` and
        // the user didn't override with a single `--surface` or `--kit`.
        // Build a fan-in path with one lift step per declared plugin and
        // one terminal mint step depending on all of them. The path
        // executor walks each plugin's k(I)=t independently; mint merges
        // their ir-documents at the envelope-mint stage.
        if !args.flags.quiet {
            println!(
                "{}: {} plugin(s) declared: {}",
                "config".green().bold(),
                lift_plugins.len(),
                lift_plugins
                    .iter()
                    .map(|p| p.display_name().to_string())
                    .collect::<Vec<_>>()
                    .join(", ")
            );
        }
        let out_dir = args.out.clone().unwrap_or_else(|| project_root.clone());
        dispatch_multi(
            &project_root,
            &lift_plugins,
            &out_dir,
            args.flags.quiet,
            args.library_bindings,
        )
    } else if args.surface.is_none()
        && derived_surface.is_none()
        && project_cfg
            .surface_for("lift")
            .or_else(|| user_cfg.surface_for("lift"))
            .is_none()
    {
        let component_plan = crate::component_plan::plan_workspace(
            &project_root,
            crate::component_plan::PlanIntent::Lift,
        );
        let lift_plugins = component_plan
            .plugins
            .iter()
            .filter(|plugin| plugin.is_lift_plugin())
            .cloned()
            .collect::<Vec<_>>();
        if lift_plugins.is_empty() {
            if let Some(diagnostic) = component_plan.diagnostics.iter().find(|diagnostic| {
                matches!(
                    diagnostic.level,
                    crate::component_plan::DiagnosticLevel::Error
                )
            }) {
                eprintln!("{}: {}", "error".red().bold(), diagnostic.message);
            } else {
                eprintln!(
                    "{}: no lift surface configured. Set [[plugins]] or [authoring] surface in .sugar/config.toml, pass --surface/--kit, or install a Sugar kit component for this workspace.",
                    "error".red().bold()
                );
            }
            return EXIT_USER_ERROR;
        }
        if !args.flags.quiet {
            println!(
                "{}: {} component plugin(s) discovered: {}",
                "discover".green().bold(),
                lift_plugins.len(),
                lift_plugins
                    .iter()
                    .map(|p| p.display_name().to_string())
                    .collect::<Vec<_>>()
                    .join(", ")
            );
        }
        let out_dir = args.out.clone().unwrap_or_else(|| project_root.clone());
        dispatch_multi(
            &project_root,
            &lift_plugins,
            &out_dir,
            args.flags.quiet,
            args.library_bindings,
        )
    } else {
        // Resolve surface: --surface > --kit derived > project config > user config.
        let surface = if let Some(s) = args.surface.clone() {
            s
        } else if let Some(s) = derived_surface {
            s
        } else {
            match project_cfg
                .surface_for("lift")
                .or_else(|| user_cfg.surface_for("lift"))
            {
                Some(s) => s,
                None => {
                    eprintln!(
                        "{}: no lift surface configured. Set [[plugins]] or [authoring] surface in .sugar/config.toml, or pass --surface/--kit.",
                        "error".red().bold()
                    );
                    return EXIT_USER_ERROR;
                }
            }
        };

        let out_dir = args.out.clone().unwrap_or_else(|| project_root.clone());
        dispatch(
            &project_root,
            &surface,
            &out_dir,
            args.flags.quiet,
            args.library_bindings,
        )
    };

    match session {
        Ok(session) => {
            let result = session.result;
            let contract_set_cid = if result.contract_set_cid.is_empty() {
                compute_contract_set_cid(vec![])
            } else {
                result.contract_set_cid.clone()
            };

            if args.flags.json {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&json!({
                        "ok": true,
                        "project": &project_root,
                        "surface": &session.surface,
                        "filenameCid": &result.filename_cid,
                        "contractSetCid": &contract_set_cid,
                        "bytesWritten": result.bytes_written,
                        "proofFile": &result.proof_file,
                        "lift": &result.lift_result,
                    }))
                    .expect("serialize mint JSON")
                );
            } else if !args.flags.quiet {
                println!();
                if !result.filename_cid.is_empty() {
                    println!("  catalog CID:        {}", result.filename_cid);
                }
                println!("  contractSetCid:     {contract_set_cid}");
                if result.bytes_written > 0 {
                    println!("  proof bytes:        {}", result.bytes_written);
                    if let Some(proof_file) = &result.proof_file {
                        println!("  .proof file:        {}", proof_file.display());
                    } else {
                        println!(
                            "  .proof file:        {}",
                            session
                                .out_dir
                                .join(proof_filename(&result.filename_cid))
                                .display()
                        );
                    }
                } else {
                    println!("  (no .proof written: lifter binary not found)");
                }
            } else {
                // Quiet mode: first line = bundle CID, second line = contractSetCid.
                // The Makefile captures contractSetCid via grep.
                if !result.filename_cid.is_empty() {
                    println!("{}", result.filename_cid);
                }
                println!("contractSetCid: {contract_set_cid}");
            }

            EXIT_OK
        }
        Err(e) => {
            eprintln!("{}: {e}", "error".red().bold());
            EXIT_VERIFY_FAIL
        }
    }
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::project_config::PlatformProfile;
    use libsugar::panic_freedom;

    fn temp_workspace(name: &str) -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("system clock")
            .as_nanos();
        let root = std::env::temp_dir().join(format!("{name}_{nanos}"));
        std::fs::create_dir_all(&root).expect("create temp workspace");
        root
    }

    // -----------------------------------------------------------------
    // #1358 / #1355: stamp_platform_profile fills absent fields from
    // the project's platform_profile (per-shim default). Annotation-pinned
    // fields are NEVER overwritten — annotation wins.
    // -----------------------------------------------------------------

    fn sql_profile() -> PlatformProfile {
        PlatformProfile {
            language: Some("rust".to_string()),
            family: Some("family:sql".to_string()),
            library: Some("rusqlite".to_string()),
            version: Some("0.39.0".to_string()),
        }
    }

    #[test]
    fn stamp_fills_absent_family_and_version_on_library_sugar_binding_entry() {
        let mut entries = vec![json!({
            "kind": "library-sugar-binding-entry",
            "op_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "target_library_tag": "rusqlite",
        })];
        stamp_platform_profile(&mut entries, &sql_profile());
        let e = &entries[0];
        assert_eq!(e["family"], "family:sql");
        assert_eq!(e["library_version"], "0.39.0");
    }

    #[test]
    fn stamp_preserves_annotation_pinned_family_and_version() {
        // Annotation wins — profile MUST NOT overwrite.
        let mut entries = vec![json!({
            "kind": "library-sugar-binding-entry",
            "op_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "target_library_tag": "rusqlite",
            "family": "family:sql-experimental",
            "library_version": "0.40.0-rc1",
        })];
        stamp_platform_profile(&mut entries, &sql_profile());
        let e = &entries[0];
        assert_eq!(
            e["family"], "family:sql-experimental",
            "annotation family preserved"
        );
        assert_eq!(
            e["library_version"], "0.40.0-rc1",
            "annotation version preserved"
        );
    }

    #[test]
    fn stamp_with_partial_profile_only_fills_pinned_axes() {
        // Profile floats `library`; only family + version get stamped.
        let profile = PlatformProfile {
            language: Some("rust".to_string()),
            family: Some("family:hash".to_string()),
            library: None,
            version: Some("1".to_string()),
        };
        let mut entries = vec![json!({
            "kind": "library-sugar-binding-entry",
            "op_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "target_library_tag": "blake3",
        })];
        stamp_platform_profile(&mut entries, &profile);
        let e = &entries[0];
        assert_eq!(e["family"], "family:hash");
        assert_eq!(e["library_version"], "1");
        // library not present in profile → not stamped → entry's
        // target_library_tag unchanged (annotation already had "blake3").
        assert_eq!(e["target_library_tag"], "blake3");
    }

    #[test]
    fn stamp_with_empty_profile_is_no_op() {
        let profile = PlatformProfile::default();
        let mut entries = vec![json!({
            "kind": "library-sugar-binding-entry",
            "op_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "target_library_tag": "bar",
        })];
        stamp_platform_profile(&mut entries, &profile);
        let e = &entries[0];
        assert!(e.get("family").is_none(), "no family stamped");
        assert!(e.get("library_version").is_none(), "no version stamped");
    }

    #[test]
    fn mint_library_sugar_binding_entry_preserves_op_cid_when_present() {
        let (_cid, bytes) = mint_library_sugar_binding_entry(&json!({
            "kind": "library-sugar-binding-entry",
            "target_language": "python",
            "target_library_tag": "numpy",
            "symbol": "numpy.add",
            "op_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "signature_shape_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "body_source": {
                "source_cid": "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
            }
        }))
        .expect("mint library sugar binding entry");
        let envelope: Value = serde_json::from_slice(&bytes).expect("canonical JSON envelope");

        assert_eq!(
            envelope["header"]["opCid"],
            "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        );
        assert_eq!(
            envelope["body"]["op_cid"],
            "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        );
    }

    #[test]
    fn resolve_kit_reads_project_config_aliases() {
        use crate::project_config::{KitAliasEntry, ProjectConfig};

        let project_cfg = ProjectConfig {
            kits: vec![KitAliasEntry {
                alias: "rust-local".to_string(),
                project: "implementations/rust".to_string(),
                surface: "rust-contracts-crate".to_string(),
                lang: "rust".to_string(),
            }],
            ..ProjectConfig::default()
        };
        let user_cfg = ProjectConfig::default();

        let resolved = resolve_kit_from_configs(
            "rust-local",
            Path::new("/workspace"),
            &project_cfg,
            &user_cfg,
        )
        .expect("configured kit alias must resolve");

        assert_eq!(
            resolved.project_root,
            PathBuf::from("/workspace/implementations/rust")
        );
        assert_eq!(resolved.surface, "rust-contracts-crate");
        assert_eq!(resolved.lang_key, "rust");
    }

    #[test]
    fn resolve_kit_falls_back_to_user_config_aliases() {
        use crate::project_config::{KitAliasEntry, ProjectConfig};

        let project_cfg = ProjectConfig::default();
        let user_cfg = ProjectConfig {
            kits: vec![KitAliasEntry {
                alias: "external".to_string(),
                project: "/opt/sugar/external-kit".to_string(),
                surface: "external-lift".to_string(),
                lang: "external".to_string(),
            }],
            ..ProjectConfig::default()
        };

        let resolved =
            resolve_kit_from_configs("external", Path::new("/workspace"), &project_cfg, &user_cfg)
                .expect("user configured kit alias must resolve");

        assert_eq!(
            resolved.project_root,
            PathBuf::from("/opt/sugar/external-kit")
        );
        assert_eq!(resolved.surface, "external-lift");
        assert_eq!(resolved.lang_key, "external");
    }

    #[test]
    fn resolve_kit_project_config_overrides_user_config_aliases() {
        use crate::project_config::{KitAliasEntry, ProjectConfig};

        let project_cfg = ProjectConfig {
            kits: vec![KitAliasEntry {
                alias: "java".to_string(),
                project: "implementations/java".to_string(),
                surface: "java-testng".to_string(),
                lang: "java".to_string(),
            }],
            ..ProjectConfig::default()
        };
        let user_cfg = ProjectConfig {
            kits: vec![KitAliasEntry {
                alias: "java".to_string(),
                project: "/opt/sugar/java".to_string(),
                surface: "java-user".to_string(),
                lang: "java-user".to_string(),
            }],
            ..ProjectConfig::default()
        };

        let resolved =
            resolve_kit_from_configs("java", Path::new("/workspace"), &project_cfg, &user_cfg)
                .expect("project alias must win");

        assert_eq!(
            resolved.project_root,
            PathBuf::from("/workspace/implementations/java")
        );
        assert_eq!(resolved.surface, "java-testng");
        assert_eq!(resolved.lang_key, "java");
    }

    #[test]
    fn resolve_kit_unknown_returns_none_without_builtin_fallback() {
        use crate::project_config::ProjectConfig;

        assert!(resolve_kit_from_configs(
            "rust",
            Path::new("/workspace"),
            &ProjectConfig::default(),
            &ProjectConfig::default()
        )
        .is_none());
    }

    #[test]
    fn dispatch_lift_params_source_paths_non_empty() {
        // C3 (verify_c3_lift_request_well_formed) requires source_paths to be
        // a non-empty array. Sending [] was the bug fixed in issue #166.
        let root = PathBuf::from(".");
        let params =
            crate::lift_plugin::build_lift_params(&root, "rust", LiftPluginOptions::default());
        let paths = params["source_paths"]
            .as_array()
            .expect("source_paths must be an array");
        assert!(
            !paths.is_empty(),
            "source_paths must not be empty: was C3 violation (issue #166)"
        );
        assert_eq!(paths[0].as_str(), Some("."), "first entry should be '.'");
    }

    #[test]
    fn dispatch_lift_params_has_surface_and_options() {
        let root = PathBuf::from(".");
        let params =
            crate::lift_plugin::build_lift_params(&root, "go", LiftPluginOptions::default());
        assert_eq!(params["surface"].as_str(), Some("go"));
        assert_eq!(params["config_path"].as_str(), Some(".sugar/config.toml"));
        assert!(
            params["workspace_root"].as_str().is_some(),
            "workspace_root should be present for lifters that resolve source through the project root"
        );
        assert_eq!(params["options"]["layer"].as_str(), Some("all"));
    }

    #[test]
    fn mint_input_is_a_composed_path() {
        let input = mint_input(
            std::path::Path::new("."),
            "rust",
            std::path::Path::new("out"),
            true,
            false,
        );
        let Input::Path(path) = input.input else {
            panic!("mint command input must be a composed path");
        };

        let lift = path.step("lift").expect("lift algebra step");
        let mint = path.step("mint").expect("mint algebra step");
        assert_eq!(lift.kit, "lift-plugin:rust");
        assert_eq!(mint.kit, "sugar-mint");
        assert_eq!(lift.inputs.len(), 1);
        assert_eq!(mint.inputs.len(), 1);
        assert_eq!(mint.depends_on, vec!["lift".to_string()]);
        assert!(path.cid().as_str().starts_with("blake3-512:"));
    }

    #[test]
    fn mint_input_can_request_library_binding_layer() {
        let input = mint_input(
            std::path::Path::new("."),
            "python-source",
            std::path::Path::new("out"),
            true,
            true,
        );
        let Input::Path(path) = input.input else {
            panic!("mint command input must be a composed path");
        };
        let lift = path.step("lift").expect("lift algebra step");
        let lift_spec = input
            .inputs
            .get_input(&lift.inputs[0])
            .expect("lift input spec materialized");
        let Input::Spec(lift_spec) = lift_spec else {
            panic!("lift input must be an Input::Spec");
        };

        assert_eq!(
            lift_spec["options"]["layer"].as_str(),
            Some("library-bindings")
        );
    }

    #[test]
    fn mint_transform_rejects_invalid_path_algebra() {
        let input = Input::Path(Box::new(CorePath {
            algebra: vec![
                PathAlgebra {
                    name: "lift".to_string(),
                    kit: "lift-plugin:rust".to_string(),
                    inputs: vec![address(&Input::Spec(json!({
                        "surface": "rust",
                        "workspace_root": "."
                    })))],
                    depends_on: vec![],
                    verb: Verb::Transform,
                },
                PathAlgebra {
                    name: "mint".to_string(),
                    kit: "sugar-mint".to_string(),
                    inputs: vec![address(&Input::Spec(json!({
                        "outDir": "out"
                    })))],
                    depends_on: vec!["lift".to_string(), "missing".to_string()],
                    verb: Verb::Transform,
                },
            ],
        }));

        let error = MintKit::default()
            .transform(&input)
            .expect_err("invalid path algebra should be rejected before transport")
            .to_string();
        assert!(
            error.contains("missing step `missing`"),
            "unexpected error: {error}"
        );
    }

    #[test]
    fn mint_from_ir_document_accepts_library_sugar_binding_without_contracts() {
        let ir = vec![json!({
            "body_source": {
                "file": "src/shims/requests.py",
                "source_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "span": {"start_line": 1, "start_col": 0, "end_line": 6, "end_col": 0}
            },
            "op_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "kind": "library-sugar-binding-entry",
            "loss_record_contribution": {"form": "literal", "value": {"entries": []}},
            "param_names": ["url"],
            "param_types": ["str"],
            "return_type": "int",
            "signature_shape_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "source_function_name": "fetch_status",
            "target_language": "python",
            "target_library_tag": "requests",
            "term_shape": null,
            "term_shape_cid": null
        })];

        let (bytes, filename_cid, contract_set_cid) =
            mint_from_ir_document(&ir, None, None, None, Path::new("."), Path::new("."), true)
                .expect("library-sugar-only ir-document must mint without contracts");

        assert!(!bytes.is_empty());
        assert!(filename_cid.starts_with("blake3-512:"));
        assert_eq!(contract_set_cid, compute_contract_set_cid(vec![]));

        let graph = ProofGraph::read(&bytes).expect("decode proof");
        let all_members: Vec<_> = graph.members_view().collect();
        assert_eq!(all_members.len(), 1);
        let view = all_members
            .into_iter()
            .next()
            .expect("library binding member");
        assert_eq!(view.kind().as_deref(), Some("library-sugar-binding-entry"));
        let envelope: Value = serde_json::from_slice(view.bytes()).expect("member JSON");
        let Ok(Member::LibrarySugarBindingEntry(lsbe)) = Member::from_value(&envelope) else {
            panic!("expected library-sugar-binding-entry member");
        };
        assert_eq!(lsbe.target_library_tag.as_str(), "requests");
    }

    #[test]
    fn mint_from_ir_document_accepts_contract_decl_shape() {
        let ir = vec![json!({
            "kind": "contract",
            "symbol": "accept",
            "invariant": {
                "kind": "atomic",
                "name": "eq",
                "args": [
                    {"kind": "var", "name": "value"},
                    {"kind": "const", "value": 42, "sort": {"kind": "primitive", "name": "Int"}}
                ]
            }
        })];

        let (bytes, filename_cid, contract_set_cid) =
            mint_from_ir_document(&ir, None, None, None, Path::new("."), Path::new("."), true)
                .expect("mint bug-zoo style ir-document");
        assert!(!bytes.is_empty());
        assert!(filename_cid.starts_with("blake3-512:"));
        assert!(contract_set_cid.starts_with("blake3-512:"));
        let proof_path = PathBuf::from(format!("{filename_cid}.proof"));
        let report = sugar_verifier::proof_conformance::validate_proof_bytes(&proof_path, &bytes);
        assert!(
            report.errors.is_empty(),
            "minted ir-document proof should inspect cleanly: {:?}",
            report.errors
        );
    }

    #[test]
    fn mint_from_ir_document_emits_contract_body_graph_for_loader() {
        let root = temp_workspace("mint_ir_document_contract_body_graph");
        let out_dir = root.join("out");
        std::fs::create_dir_all(&out_dir).expect("create out dir");
        let ir = vec![json!({
            "kind": "contract",
            "name": "body_graph_contract",
            "outBinding": "result",
            "post": {
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "var", "name": "result"},
                    {"kind": "const", "value": 7, "sort": {"kind": "primitive", "name": "Int"}}
                ]
            }
        })];

        let minted = mint_ir_document(&ir, None, None, None, &root, &out_dir, true).expect("mint");
        let graph = ProofGraph::read(&minted.bytes).expect("decode proof");
        let header = contract_header(&graph, "body_graph_contract");
        let body_cid = header
            .get("bodyCid")
            .and_then(|value| value.as_str())
            .expect("contract header carries bodyCid");
        assert!(
            header.get("post").is_none(),
            "contract formulas must live in catalog body/atoms, not inline header fields"
        );
        assert!(
            graph.bodies().any(|b| b.cid().as_str() == body_cid),
            "catalog body map must contain contract bodyCid {body_cid}"
        );

        let proof_path = root.join(format!("{}.proof", minted.filename_cid));
        std::fs::write(&proof_path, &minted.bytes).expect("write proof");
        let mut pool = sugar_verifier::types::MementoPool::default();
        sugar_verifier::load_all_proofs::load_files_into_pool(&[proof_path], &mut pool);
        assert!(
            pool.load_errors.is_empty(),
            "minted proof must load without body graph errors: {:?}",
            pool.load_errors
        );
        let env = pool
            .mementos
            .values()
            .find(|env| {
                member_field(env, "name").and_then(|value| value.as_str())
                    == Some("body_graph_contract")
            })
            .expect("loaded contract memento");
        let resolved = pool
            .resolve_contract_body(env)
            .expect("resolve graph-backed contract body");
        assert!(
            resolved.get("post").is_some_and(|post| post.is_object()),
            "semantic post must resolve from catalog body/atoms"
        );

        let _ = std::fs::remove_dir_all(root);
    }

    fn function_contract_with_panic_loci(panic_loci: Option<Value>) -> Vec<Value> {
        let mut decl = json!({
            "kind": "function-contract",
            "fn_name": "panic_locus_subject",
            "formals": ["v"],
            "formalSorts": [{"kind": "primitive", "name": "JsonValue"}],
            "outBinding": "result",
            "post": {
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "var", "name": "result"},
                    {
                        "kind": "ctor",
                        "name": "to_string",
                        "args": [{"kind": "var", "name": "v"}]
                    }
                ]
            }
        });
        if let Some(panic_loci) = panic_loci {
            decl["panicLoci"] = panic_loci;
        }
        vec![decl]
    }

    fn sample_panic_locus() -> Value {
        json!({
            "argTerm": {
                "kind": "ctor",
                "name": "to_string",
                "args": [{"kind": "var", "name": "v"}]
            },
            "file": "src/lib.rs",
            "line": 25,
            "col": 30,
            "callee": panic_freedom::METHOD_UNWRAP
        })
    }

    fn contract_header(graph: &ProofGraph, name: &str) -> Value {
        graph
            .members_view()
            .find_map(|view| {
                let is_contract = view.kind().as_deref() == Some("contract");
                let has_name = view.field("name").as_deref() == Some(name)
                    || view.field("contractName").as_deref() == Some(name);
                (is_contract && has_name).then(|| {
                    let envelope = view.json();
                    envelope.get("header").expect("contract header").clone()
                })
            })
            .unwrap_or_else(|| panic!("contract header `{name}` not found"))
    }

    fn source_memento_members(graph: &ProofGraph) -> Vec<Value> {
        graph.sources().map(|view| view.json()).collect()
    }

    fn plan_memento_members(graph: &ProofGraph) -> Vec<Value> {
        graph.plans().map(|view| view.json()).collect()
    }

    fn factory_walk_memento_members(graph: &ProofGraph) -> Vec<Value> {
        graph
            .members_view()
            .filter(|v| v.kind().as_deref() == Some("factory-walk-memento"))
            .map(|view| view.json())
            .collect()
    }

    fn minted_panic_locus_contract_header(panic_loci: Option<Value>) -> Value {
        let (bytes, _, _) = mint_from_ir_document(
            &function_contract_with_panic_loci(panic_loci),
            None,
            None,
            None,
            Path::new("."),
            Path::new("."),
            true,
        )
        .expect("mint function contract");
        let graph = ProofGraph::read(&bytes).expect("decode proof");
        contract_header(&graph, "panic_locus_subject")
    }

    fn bridge_header(graph: &ProofGraph) -> Value {
        graph
            .bridges()
            .find_map(|view| {
                let env = view.json();
                env.pointer("/header").cloned()
            })
            .expect("bridge header")
    }

    fn explicit_bridge_ir_with_callsite(callsite: Option<Value>) -> Vec<Value> {
        let target_cid = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let mut bridge = json!({
            "kind": "bridge",
            "name": "intra-body:rust:callee@src/lib.rs:2:4",
            "schemaVersion": "1",
            "sourceContractCid": target_cid,
            "sourceLayer": "rust",
            "sourceSymbol": "callee",
            "target": {"cid": target_cid, "kind": "contract"},
            "targetContractCid": target_cid,
            "targetLayer": "rust-tests"
        });
        if let Some(callsite) = callsite {
            bridge["callsite"] = callsite;
        }
        vec![
            json!({
                "kind": "contract",
                "name": "callee@src/lib.rs:1:1",
                "outBinding": "out",
                "post": {"kind": "atomic", "name": "producer_post", "args": []}
            }),
            bridge,
        ]
    }

    #[test]
    fn mint_ir_document_absent_panic_loci_yields_empty_header() {
        let header = minted_panic_locus_contract_header(None);
        assert!(
            header.get("panicLoci").is_none(),
            "absent panicLoci must omit the provenance header: {header:#}"
        );
    }

    fn assert_malformed_panic_loci_fails_closed(panic_loci: Value) {
        let error = mint_from_ir_document(
            &function_contract_with_panic_loci(Some(panic_loci)),
            None,
            None,
            None,
            Path::new("."),
            Path::new("."),
            true,
        )
        .expect_err("present malformed panicLoci must fail closed");
        assert!(
            error.contains("panicLoci must be an array"),
            "error should come from the panicLoci extraction check, got: {error}"
        );
    }

    #[test]
    fn mint_ir_document_rejects_string_panic_loci() {
        assert_malformed_panic_loci_fails_closed(json!("not-an-array"));
    }

    #[test]
    fn mint_ir_document_rejects_number_panic_loci() {
        assert_malformed_panic_loci_fails_closed(json!(42));
    }

    #[test]
    fn mint_ir_document_rejects_object_panic_loci() {
        assert_malformed_panic_loci_fails_closed(json!({"argTerm": {"kind": "var", "name": "x"}}));
    }

    #[test]
    fn mint_ir_document_rejects_null_panic_loci() {
        assert_malformed_panic_loci_fails_closed(Value::Null);
    }

    #[test]
    fn mint_ir_document_well_formed_panic_loci_threads_through_header() {
        let locus = sample_panic_locus();
        let header = minted_panic_locus_contract_header(Some(json!([locus.clone()])));
        let panic_loci = header
            .get("panicLoci")
            .and_then(|value| value.as_array())
            .expect("well-formed panicLoci must be preserved");
        assert_eq!(panic_loci, &[locus]);
        assert_eq!(panic_loci[0]["callee"], panic_freedom::METHOD_UNWRAP);
        assert_ne!(
            panic_loci[0]["callee"], "concept:panic-freedom.leaf.unwrap",
            "Rust v1 mint writer must not emit the unwrap leaf concept alias"
        );
    }

    fn assert_malformed_bridge_callsite_fails_closed(callsite: Value, expected: &str) {
        let error = mint_from_ir_document(
            &explicit_bridge_ir_with_callsite(Some(callsite)),
            None,
            None,
            None,
            Path::new("."),
            Path::new("."),
            true,
        )
        .expect_err("present malformed bridge callsite must fail closed");
        assert!(
            error.contains(expected),
            "error should contain `{expected}`, got: {error}"
        );
    }

    #[test]
    fn mint_ir_document_rejects_non_object_bridge_callsite() {
        assert_malformed_bridge_callsite_fails_closed(
            json!("not-an-object"),
            "callsite must be an object",
        );
    }

    #[test]
    fn mint_ir_document_rejects_non_bool_bridge_panic_site() {
        assert_malformed_bridge_callsite_fails_closed(
            json!({"panicSite": "true", "file": "src/lib.rs", "line": 25}),
            "callsite.panicSite must be a boolean",
        );
    }

    #[test]
    fn mint_ir_document_rejects_non_string_bridge_file() {
        assert_malformed_bridge_callsite_fails_closed(
            json!({"panicSite": true, "file": 12, "line": 25}),
            "callsite.file must be a non-empty string",
        );
    }

    #[test]
    fn mint_ir_document_rejects_non_integer_bridge_line() {
        assert_malformed_bridge_callsite_fails_closed(
            json!({"panicSite": true, "file": "src/lib.rs", "line": "25"}),
            "callsite.line must be an integer",
        );
    }

    #[test]
    fn mint_ir_document_rejects_non_object_bridge_formal_actuals() {
        assert_malformed_bridge_callsite_fails_closed(
            json!({"panicSite": true, "formalActuals": []}),
            "callsite.formalActuals must be an object",
        );
    }

    #[test]
    fn mint_ir_document_well_formed_bridge_callsite_threads_through_header() {
        let (bytes, _, _) = mint_from_ir_document(
            &explicit_bridge_ir_with_callsite(Some(json!({
                "panicSite": true,
                "file": "src/lib.rs",
                "line": 25,
                "formalActuals": {
                    "radix": {
                        "kind": "const",
                        "value": 16,
                        "sort": {"kind": "primitive", "name": "Int"}
                    }
                }
            }))),
            None,
            None,
            None,
            Path::new("."),
            Path::new("."),
            true,
        )
        .expect("well-formed bridge callsite must mint");
        let graph = ProofGraph::read(&bytes).expect("decode proof");
        let header = bridge_header(&graph);
        assert_eq!(
            header.get("callsite"),
            Some(&json!({
                "panicSite": true,
                "file": "src/lib.rs",
                "start_line": 25,
                "formalActuals": {
                    "radix": {
                        "kind": "const",
                        "value": 16,
                        "sort": {"kind": "primitive", "name": "Int"}
                    }
                }
            }))
        );
    }

    #[test]
    fn mint_from_ir_document_mints_implication_mementos() {
        let ir = vec![
            json!({
                "kind": "contract",
                "name": "lower.claim",
                "outBinding": "out",
                "post": {"kind": "atomic", "name": "lower_holds", "args": []}
            }),
            json!({
                "kind": "contract",
                "name": "upper.claim",
                "outBinding": "out",
                "post": {"kind": "atomic", "name": "upper_holds", "args": []}
            }),
        ];
        let implications = vec![json!({
            "name": "lower-implies-upper",
            "antecedent": "lower.claim",
            "consequent": "upper.claim",
            "antecedentSlot": "post",
            "consequentSlot": "post"
        })];

        let (bytes, _, _) = mint_from_ir_document(
            &ir,
            None,
            Some(&implications),
            None,
            Path::new("."),
            Path::new("."),
            true,
        )
        .expect("mint contracts plus implication");
        let graph = ProofGraph::read(&bytes).expect("decode proof");
        let all_members: Vec<_> = graph.members_view().collect();

        assert_eq!(all_members.len(), 3);

        let mut contract_count = 0;
        let mut implication_count = 0;
        for view in &all_members {
            match view.kind().as_deref() {
                Some("contract") => contract_count += 1,
                Some("implication") => {
                    implication_count += 1;
                    let envelope = view.json();
                    let Ok(Member::Implication(imp)) = Member::from_value(&envelope) else {
                        panic!("expected implication member");
                    };
                    let inputs = imp.input_cids.as_ref().expect("implication inputCids");
                    assert_eq!(inputs.len(), 2);
                }
                other => panic!("unexpected member kind {other:?}"),
            }
        }

        assert_eq!(contract_count, 2);
        assert_eq!(implication_count, 1);
    }

    #[test]
    fn merge_ir_document_responses_preserves_implications_from_lifters() {
        let merged = merge_ir_document_responses(vec![
            PerPluginDispatch {
                surface: "zig-tests".to_string(),
                response: json!({
                    "kind": "ir-document",
                    "ir": [{
                        "kind": "contract",
                        "name": "zig.assertion",
                        "inv": {"kind": "atomic", "name": "=", "args": []}
                    }],
                    "diagnostics": []
                }),
            },
            PerPluginDispatch {
                surface: "zig-implications".to_string(),
                response: json!({
                    "kind": "ir-document",
                    "ir": [],
                    "implications": [{
                        "name": "zig.assertion.scope",
                        "antecedent": "zig.assertion",
                        "consequent": "zig.assertion",
                        "antecedentSlot": "inv",
                        "consequentSlot": "inv"
                    }],
                    "diagnostics": []
                }),
            },
        ])
        .expect("merge ir-documents");

        assert_eq!(merged["ir"].as_array().expect("ir").len(), 1);
        assert_eq!(
            merged["implications"]
                .as_array()
                .expect("implications")
                .len(),
            1,
            "merged ir-document must keep implication-lifter output: {merged}"
        );
    }

    #[test]
    fn dispatch_result_to_value_propagates_oracle_observation_from_lift() {
        let result = DispatchResult {
            filename_cid: "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".to_string(),
            contract_set_cid: "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb".to_string(),
            bytes_written: 42,
            proof_file: None,
            lift_result: json!({
                "kind": "ir-document",
                "ir": [],
                "diagnostics": [],
                "oracle_requested": true,
                "oracle_reachable": true,
                "oracle_ready": true,
                "receivers_attempted": 7,
                "receivers_resolved": 3
            }),
        };

        let value = dispatch_result_to_value(&result);

        assert_eq!(
            value["oracle"],
            json!({
                "requested": true,
                "reachable": true,
                "ready": true,
                "attempted": 7,
                "resolved": 3
            })
        );
    }

    #[test]
    fn requested_oracle_not_ready_refuses_mint() {
        let lift = json!({
            "kind": "ir-document",
            "ir": [],
            "diagnostics": [],
            "oracle_requested": true,
            "oracle_reachable": true,
            "oracle_ready": false,
            "receivers_attempted": 7,
            "receivers_resolved": 0
        });

        let err = assert_oracle_ready_if_requested("rust-implications", &lift)
            .expect_err("requested oracle with candidates must fail when not ready");
        assert!(
            err.contains("did not report rust-analyzer ready"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn ready_oracle_with_zero_resolutions_remains_honest_refusal() {
        let lift = json!({
            "kind": "ir-document",
            "ir": [],
            "diagnostics": [],
            "oracle_requested": true,
            "oracle_reachable": true,
            "oracle_ready": true,
            "receivers_attempted": 7,
            "receivers_resolved": 0
        });

        assert_oracle_ready_if_requested("rust-implications", &lift)
            .expect("ready oracle may honestly refuse every candidate");
    }

    #[test]
    fn mint_from_ir_document_mints_explicit_bridge_entries() {
        let target_cid = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let ir = vec![
            json!({
                "kind": "contract",
                "name": "callee@src/lib.rs:1:1",
                "outBinding": "out",
                "post": {"kind": "atomic", "name": "producer_post", "args": []}
            }),
            json!({
                "kind": "bridge",
                "name": "intra-body:rust:callee@src/lib.rs:2:4",
                "schemaVersion": "1",
                "sourceContractCid": target_cid,
                "sourceLayer": "rust",
                "sourceSymbol": "callee",
                "target": {"cid": target_cid, "kind": "contract"},
                "targetContractCid": target_cid,
                "targetLayer": "rust-tests"
            }),
        ];

        let (bytes, _, _) =
            mint_from_ir_document(&ir, None, None, None, Path::new("."), Path::new("."), true)
                .expect("mint contract plus explicit bridge");
        let graph = ProofGraph::read(&bytes).expect("decode proof");

        let mut contract_count = 0;
        let mut bridge_count = 0;
        for view in graph.members_view() {
            match view.kind().as_deref() {
                Some("contract") => contract_count += 1,
                Some("bridge") => {
                    bridge_count += 1;
                    assert_eq!(view.field("targetContractCid").as_deref(), Some(target_cid));
                    assert_eq!(view.field("sourceSymbol").as_deref(), Some("callee"));
                }
                other => panic!("unexpected member kind {other:?}"),
            }
        }

        assert_eq!(contract_count, 1);
        assert_eq!(bridge_count, 1);
    }

    #[test]
    fn mint_ir_document_ties_conjoined_imports_into_bundle_identity() {
        use std::fs;
        let root = temp_workspace("mint_import_tie");
        let out_dir = root.join("out");
        fs::create_dir_all(&out_dir).expect("out");
        let imports = root.join(".sugar").join("imports");
        fs::create_dir_all(&imports).expect("imports");
        // Two dependency bundles, CID-named (the filename CID IS the identity
        // the loader uses; content is irrelevant to the tie).
        let dep_a = "blake3-512:aaaa";
        let dep_b = "blake3-512:bbbb";
        fs::write(imports.join(format!("{dep_a}.proof")), b"x").unwrap();
        fs::write(imports.join(format!("{dep_b}.proof")), b"y").unwrap();

        let ir = vec![json!({
            "kind": "contract",
            "name": "c",
            "outBinding": "out",
            "post": {"kind": "atomic", "name": "p", "args": []}
        })];
        let minted = mint_ir_document(&ir, None, None, None, &root, &out_dir, true).expect("mint");

        // The tie is recorded in the bundle metadata, sorted+deduped.
        let catalog =
            sugar_proof_envelope::ProofCatalog::read(&minted.bytes).expect("read catalog");
        let conjoined = catalog
            .metadata
            .get("sugar.conjoinedImports")
            .expect("conjoinedImports metadata");
        assert_eq!(conjoined, &format!("{dep_a},{dep_b}"), "sorted dep CID set");

        // THE DIFFERENTIAL: change the dependency set -> the vendor bundle CID
        // MUST move. This is the a->b->c identity's enforcement: a bundle
        // commits to the exact deps it was conjoined against.
        fs::remove_file(imports.join(format!("{dep_b}.proof"))).unwrap();
        fs::write(imports.join("blake3-512:cccc.proof"), b"z").unwrap();
        let minted2 =
            mint_ir_document(&ir, None, None, None, &root, &out_dir, true).expect("mint2");
        assert_ne!(
            minted.filename_cid, minted2.filename_cid,
            "a changed dependency set must change the vendor bundle CID"
        );

        // And re-mint against the SAME dependency set -> identical CID
        // (recompute-not-trust: the tie is deterministic).
        let minted3 =
            mint_ir_document(&ir, None, None, None, &root, &out_dir, true).expect("mint3");
        assert_eq!(
            minted2.filename_cid, minted3.filename_cid,
            "same dependency set must yield the same vendor bundle CID"
        );

        // No imports -> no tie (metadata absent), so leaf bundles are unaffected.
        let leaf_root = temp_workspace("mint_import_tie_leaf");
        fs::create_dir_all(leaf_root.join("out")).unwrap();
        let leaf = mint_ir_document(
            &ir,
            None,
            None,
            None,
            &leaf_root,
            &leaf_root.join("out"),
            true,
        )
        .expect("leaf mint");
        let leaf_cat =
            sugar_proof_envelope::ProofCatalog::read(&leaf.bytes).expect("read leaf catalog");
        assert!(
            leaf_cat.metadata.is_empty(),
            "a leaf with no imports carries no conjoined-imports tie"
        );
    }

    #[test]
    fn mint_ir_document_forwards_contract_library_to_metadata_and_bindings() {
        let root = temp_workspace("mint_contract_library_forward");
        let out_dir = root.join("out");
        std::fs::create_dir_all(&out_dir).expect("create out dir");
        let ir = vec![json!({
            "kind": "contract",
            "name": "qualified.callee",
            "library": "libsugar",
            "outBinding": "out",
            "post": {"kind": "atomic", "name": "qualified_post", "args": []}
        })];

        let minted = mint_ir_document(&ir, None, None, None, &root, &out_dir, true)
            .expect("mint ir-document");

        let binding = minted
            .contract_bindings
            .iter()
            .find(|binding| binding["name"] == "qualified.callee")
            .expect("producer binding");
        assert_eq!(binding["library"], "libsugar");

        let graph = ProofGraph::read(&minted.bytes).expect("decode proof");
        let view = graph
            .members_view()
            .find(|v| {
                v.field("name").as_deref() == Some("qualified.callee")
                    || v.field("contractName").as_deref() == Some("qualified.callee")
            })
            .expect("contract envelope");
        assert_eq!(
            view.json()
                .pointer("/metadata/library")
                .and_then(|v| v.as_str()),
            Some("libsugar")
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn mint_ir_document_mints_contract_source_warrants_as_envelope_members() {
        let root = temp_workspace("mint_contract_source_warrants_envelope");
        let out_dir = root.join("out");
        std::fs::create_dir_all(&out_dir).expect("create out dir");
        let contract_name = "Codec.encode#euf#c:callresult_encode_a1(s:bar)::assertion";
        let source_warrant = json!({
            "kind": "source-memento",
            "role": "java.strong-universe",
            "file": "src/Codec.java",
            "source_function_name": "encode",
            "source_cid": format!("blake3-512:{}", "a".repeat(128)),
            "template_cid": format!("blake3-512:{}", "b".repeat(128)),
            "span": {"start_line": 10, "start_col": 4, "end_line": 14, "end_col": 5},
            "param_names": ["input"]
        });
        let ir = vec![json!({
            "kind": "contract",
            "name": contract_name,
            "outBinding": "out",
            "inv": {"kind": "atomic", "name": "str.chars-in-set", "args": []},
            "sourceWarrants": [source_warrant]
        })];

        let minted = mint_ir_document(&ir, None, None, None, &root, &out_dir, true)
            .expect("mint ir-document");
        let graph = ProofGraph::read(&minted.bytes).expect("decode proof");
        let header = contract_header(&graph, contract_name);
        assert!(
            header.get("sourceWarrants").is_none(),
            "source mementos belong in the proof envelope, not the contract header: {header:#?}"
        );

        let mementos = source_memento_members(&graph);
        assert_eq!(mementos.len(), 1);
        let memento = &mementos[0];
        let Ok(Member::SourceMemento(sm)) = Member::from_value(memento) else {
            panic!(
                "expected source-memento member, got {:?}",
                memento.get("kind")
            );
        };
        assert_eq!(sm.contract_name.as_deref(), Some(contract_name));
        assert_eq!(sm.claim_name.as_deref(), Some(contract_name));
        assert_eq!(sm.role.as_deref(), Some("java.strong-universe"));
        assert_eq!(sm.file.as_deref(), Some("src/Codec.java"));
        assert_eq!(
            memento.pointer("/body/source_cid").and_then(|v| v.as_str()),
            Some(format!("blake3-512:{}", "a".repeat(128)).as_str())
        );
        assert!(
            memento.pointer("/body/body_text").is_none()
                && memento.pointer("/body/ast_template").is_none(),
            "source mementos must be lean, not decompressed source: {memento:#?}"
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn mint_ir_document_mints_top_level_source_mementos_as_envelope_members() {
        let root = temp_workspace("mint_top_level_source_mementos_envelope");
        let out_dir = root.join("out");
        std::fs::create_dir_all(&out_dir).expect("create out dir");
        let source_mementos = vec![json!({
            "kind": "source-memento",
            "role": "java.fact",
            "file": "src/test/java/CodecTest.java",
            "source_function_name": "encodeBase64_fixedpoint",
            "source_cid": format!("blake3-512:{}", "c".repeat(128)),
            "template_cid": format!("blake3-512:{}", "d".repeat(128)),
            "claimName": "Codec.encode#euf#c:callresult_encode_a1(s:bar)::assertion",
            "span": {"start_line": 44, "start_col": 8, "end_line": 44, "end_col": 48}
        })];
        let ir = vec![json!({
            "kind": "contract",
            "name": "Codec.encode#euf#c:callresult_encode_a1(s:bar)::assertion",
            "outBinding": "out",
            "inv": {"kind": "atomic", "name": "=", "args": []}
        })];

        let minted = mint_ir_document_with_source_mementos(
            &ir,
            Some(&source_mementos),
            None,
            None,
            None,
            None,
            &root,
            &out_dir,
            true,
        )
        .expect("mint ir-document");
        let graph = ProofGraph::read(&minted.bytes).expect("decode proof");
        let mementos = source_memento_members(&graph);
        assert_eq!(mementos.len(), 1);
        let memento = &mementos[0];
        let Ok(Member::SourceMemento(sm)) = Member::from_value(memento) else {
            panic!("expected source-memento member");
        };
        assert_eq!(
            sm.claim_name.as_deref(),
            Some("Codec.encode#euf#c:callresult_encode_a1(s:bar)::assertion")
        );
        assert_eq!(sm.role.as_deref(), Some("java.fact"));
        assert_eq!(
            sm.source_cid.as_str(),
            format!("blake3-512:{}", "c".repeat(128)).as_str()
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn mint_plan_memento_addresses_the_letter_and_the_envelope() {
        let plan = json!({
            "kind": "component-plan",
            "schemaVersion": "1",
            "workspaceRoot": "/workspace",
            "expectedOutputCids": [
                format!("blake3-512:{}", "a".repeat(128))
            ],
            "components": [{
                "name": "rust-kit",
                "responseCid": format!("blake3-512:{}", "b".repeat(128))
            }]
        });

        let (member_cid, bytes, plan_atoms) = mint_plan_memento(&plan).expect("mint plan memento");
        let envelope: Value = serde_json::from_slice(&bytes).expect("canonical plan memento JSON");
        let body_canonical = encode_jcs(json_to_cvalue(&plan).as_ref());
        let body_cid = blake3_512_of(body_canonical.as_bytes());
        let envelope_canonical = encode_jcs(json_to_cvalue(&envelope).as_ref());

        assert!(plan_atoms.is_empty());
        let Ok(Member::PlanMemento(pm)) = Member::from_value(&envelope) else {
            panic!(
                "expected plan-memento member, got {:?}",
                envelope.get("kind")
            );
        };
        assert_eq!(
            pm.plan_cid.as_str(),
            body_cid.as_str(),
            "the letter CID belongs in the envelope header"
        );
        assert_eq!(
            envelope
                .pointer("/body/expectedOutputCids/0")
                .and_then(Value::as_str),
            Some(format!("blake3-512:{}", "a".repeat(128)).as_str())
        );
        assert_eq!(
            member_cid,
            blake3_512_of(envelope_canonical.as_bytes()),
            "the catalog member CID addresses the envelope bytes"
        );
    }

    #[test]
    fn mint_plan_memento_lowers_plan_atoms_before_the_memento() {
        let plan_atom = json!({
            "kind": "plan-atom",
            "schemaVersion": "1",
            "atomKind": "lifter-binary",
            "role": "unit-test-assertions",
            "surface": "rust-test-assertions",
            "version": "0.1.0",
            "binary": {
                "path": "/bin/rust_test_assertions_rpc",
                "cid": format!("blake3-512:{}", "d".repeat(128))
            }
        });
        let plan = json!({
            "kind": "component-plan",
            "schemaVersion": "1",
            "workspaceRoot": "/workspace",
            "planAtoms": [plan_atom.clone()],
            "expectedOutputCids": [
                format!("blake3-512:{}", "a".repeat(128))
            ]
        });

        let (_member_cid, bytes, plan_atoms) =
            mint_plan_memento(&plan).expect("mint plan atom memento");
        let envelope: Value = serde_json::from_slice(&bytes).expect("canonical plan memento JSON");
        let expected_atom = FlatAtom::new(json_to_cvalue(&plan_atom));

        assert_eq!(plan_atoms.len(), 1);
        assert_eq!(plan_atoms[0].cid().as_str(), expected_atom.cid().as_str());
        assert_eq!(
            envelope
                .pointer("/body/planAtoms/0/kind")
                .and_then(Value::as_str),
            Some("atom-memento"),
            "plan memento body must pin atom refs, not inline plan atom bodies"
        );
        assert_eq!(
            envelope
                .pointer("/body/planAtoms/0/atomCid")
                .and_then(Value::as_str),
            Some(expected_atom.cid().as_str())
        );
    }

    #[test]
    fn mint_ir_document_mints_top_level_plan_mementos_as_envelope_members() {
        let root = temp_workspace("mint_top_level_plan_mementos_envelope");
        let out_dir = root.join("out");
        std::fs::create_dir_all(&out_dir).expect("create out dir");
        let plan_mementos = vec![json!({
            "kind": "component-plan",
            "schemaVersion": "1",
            "workspaceRoot": root.display().to_string(),
            "expectedOutputCids": [
                format!("blake3-512:{}", "c".repeat(128))
            ],
            "toolOutputs": [{
                "surface": "rust-test-assertions",
                "actualOutputCid": format!("blake3-512:{}", "c".repeat(128))
            }]
        })];
        let ir = vec![json!({
            "kind": "contract",
            "name": "plan.member.assertion",
            "outBinding": "out",
            "inv": {"kind": "atomic", "name": "=", "args": []}
        })];

        let minted = mint_ir_document_with_source_and_plan_mementos(
            &ir,
            None,
            Some(&plan_mementos),
            None,
            None,
            None,
            None,
            None,
            &root,
            &out_dir,
            true,
        )
        .expect("mint ir-document");
        let graph = ProofGraph::read(&minted.bytes).expect("decode proof");
        let mementos = plan_memento_members(&graph);
        assert_eq!(mementos.len(), 1);
        let memento = &mementos[0];
        assert!(
            matches!(Member::from_value(memento), Ok(Member::PlanMemento(_))),
            "expected plan-memento member, got {:?}",
            memento.get("kind")
        );
        assert_eq!(
            memento
                .pointer("/body/toolOutputs/0/surface")
                .and_then(Value::as_str),
            Some("rust-test-assertions")
        );
        assert_eq!(
            memento
                .pointer("/body/expectedOutputCids/0")
                .and_then(Value::as_str),
            Some(format!("blake3-512:{}", "c".repeat(128)).as_str())
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn mint_lift_response_mints_factory_walk_rows_as_envelope_members() {
        let root = temp_workspace("mint_factory_walk_mementos_envelope");
        let out_dir = root.join("out");
        std::fs::create_dir_all(&out_dir).expect("create out dir");
        let source_memento = json!({
            "kind": "source-memento",
            "role": "rust-fn-contracts",
            "file": "src/encode.rs",
            "sourceFunctionName": "encoded_len",
            "source_cid": format!("blake3-512:{}", "a".repeat(128)),
            "template_cid": format!("blake3-512:{}", "b".repeat(128)),
            "span": {"start_line": 92, "start_col": 4, "end_line": 92, "end_col": 29}
        });
        let lift_response = json!({
            "kind": "ir-document",
            "ir": [{
                "kind": "contract",
                "name": "encoded_len",
                "outBinding": "result",
                "post": {
                    "kind": "atomic",
                    "name": "=",
                    "args": [
                        {"kind": "var", "name": "rem"},
                        {"kind": "ctor", "name": "%", "args": [
                            {"kind": "var", "name": "bytes_len"},
                            {"kind": "const", "value": 3, "sort": {"name": "Int"}}
                        ]}
                    ]
                }
            }],
            "factoryAuditSummary": {
                "emittedRows": 1,
                "statusCounts": {
                    "warranted": 1,
                    "refused": 0,
                    "support": 0,
                    "unresolved": 0
                },
                "unresolvedSites": [],
                "factoryWalk": [{
                    "file": "src/encode.rs",
                    "line": 92,
                    "requested_role": "FunctionBodyConstraint",
                    "ast_kind": "stmt",
                    "selected": "function_contract_body_post",
                    "status": "warranted",
                    "verdict": "complete",
                    "output": "constraints",
                    "sourceMemento": source_memento,
                    "emittedFormula": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "rem"},
                            {"kind": "ctor", "name": "%", "args": [
                                {"kind": "var", "name": "bytes_len"},
                                {"kind": "const", "value": 3, "sort": {"name": "Int"}}
                            ]}
                        ]
                    }
                }]
            }
        });

        let result =
            mint_lift_response(&root, &out_dir, true, lift_response).expect("mint lift response");
        let proof_file = result.proof_file.expect("proof path");
        let proof_bytes = std::fs::read(&proof_file).expect("read proof");
        let graph = ProofGraph::read(&proof_bytes).expect("decode proof");
        let mementos = factory_walk_memento_members(&graph);

        assert_eq!(mementos.len(), 1);
        let memento = &mementos[0];
        assert!(
            matches!(
                Member::from_value(memento),
                Ok(Member::FactoryWalkMemento(_))
            ),
            "expected factory-walk-memento member, got {:?}",
            memento.get("kind")
        );
        assert_eq!(
            memento.pointer("/body/kind").and_then(Value::as_str),
            Some("factory-walk-row")
        );
        assert_eq!(
            memento
                .pointer("/body/sourceMemento/sourceFunctionName")
                .and_then(Value::as_str),
            Some("encoded_len")
        );
        assert_eq!(
            memento
                .pointer("/body/emittedFormula/args/0/name")
                .and_then(Value::as_str),
            Some("rem")
        );
        assert!(memento.pointer("/body/source").is_none());
        assert!(memento.pointer("/body/term").is_none());
        assert!(memento.pointer("/body/site").is_none());

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn mint_ir_document_stores_plan_atoms_in_catalog_atoms() {
        let root = temp_workspace("mint_plan_atoms_catalog");
        let out_dir = root.join("out");
        std::fs::create_dir_all(&out_dir).expect("create out dir");
        let plan_atom = json!({
            "kind": "plan-atom",
            "schemaVersion": "1",
            "atomKind": "lifter-binary",
            "role": "body-universes",
            "surface": "rust-fn-contracts",
            "version": "0.1.0",
            "binary": {
                "path": "/bin/sugar-walk-rpc",
                "cid": format!("blake3-512:{}", "e".repeat(128))
            }
        });
        let expected_atom = FlatAtom::new(json_to_cvalue(&plan_atom));
        let plan_mementos = vec![json!({
            "kind": "component-plan",
            "schemaVersion": "1",
            "workspaceRoot": root.display().to_string(),
            "planAtoms": [plan_atom],
            "expectedOutputCids": [
                format!("blake3-512:{}", "c".repeat(128))
            ]
        })];
        let ir = vec![json!({
            "kind": "contract",
            "name": "plan.atom.assertion",
            "outBinding": "out",
            "inv": {"kind": "atomic", "name": "=", "args": []}
        })];

        let minted = mint_ir_document_with_source_and_plan_mementos(
            &ir,
            None,
            Some(&plan_mementos),
            None,
            None,
            None,
            None,
            None,
            &root,
            &out_dir,
            true,
        )
        .expect("mint ir-document");
        let graph = ProofGraph::read(&minted.bytes).expect("decode proof");
        let stored_json: Value = graph
            .atoms()
            .find(|a| a.cid().as_str() == expected_atom.cid().as_str())
            .map(|a| serde_json::from_slice(a.bytes()).expect("plan atom json"))
            .expect("plan atom is stored in catalog atoms");
        assert_eq!(stored_json["kind"], "plan-atom");
        assert_eq!(stored_json["surface"], "rust-fn-contracts");
        let memento = plan_memento_members(&graph).pop().expect("plan memento");
        assert_eq!(
            memento
                .pointer("/body/planAtoms/0/atomCid")
                .and_then(Value::as_str),
            Some(expected_atom.cid().as_str())
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn finalize_toolchain_plan_adds_output_cids_to_the_letter_not_self_cids() {
        let base = json!({
            "kind": "component-plan",
            "schemaVersion": "1",
            "workspaceRoot": "/workspace",
            "planning": {"source": "configured"},
            "plugins": [{
                "kind": "lift",
                "surface": "rust-test-assertions"
            }]
        });
        let outputs = vec![PerPluginDispatch {
            surface: "rust-test-assertions".to_string(),
            response: json!({
                "kind": "ir-document",
                "ir": [],
                "diagnostics": []
            }),
        }];

        let finalized =
            finalize_toolchain_plan_memento(base, &outputs).expect("finalize toolchain plan");
        let response_cid = canonical_json_cid(&outputs[0].response);

        assert_eq!(
            finalized
                .pointer("/expectedOutputCids/0")
                .and_then(Value::as_str),
            Some(response_cid.as_str())
        );
        assert_eq!(
            finalized
                .pointer("/toolOutputs/0/actualOutputCid")
                .and_then(Value::as_str),
            Some(response_cid.as_str())
        );
        assert!(
            finalized.get("planCid").is_none(),
            "the letter must not contain its own CID; the envelope header carries it"
        );
    }

    #[test]
    fn mint_path_input_threads_toolchain_plan_seed() {
        let root = temp_workspace("mint_path_toolchain_plan_seed");
        let out_dir = root.join("out");
        std::fs::create_dir_all(&out_dir).expect("create out dir");
        let plugin = PluginEntry {
            name: Some("rust-lift".to_string()),
            kind: Some("lift".to_string()),
            surface: "rust-test-assertions".to_string(),
            workspace_override: None,
            emit: Some("ir-document".to_string()),
            layer: None,
        };

        let input = mint_input_multi(&root, &[plugin], &out_dir, true, false);
        let path = match &input.input {
            Input::Path(path) => path,
            other => panic!("expected path input, got {other:?}"),
        };
        let lift_step = path
            .algebra
            .iter()
            .find(|step| step.name == "lift")
            .expect("lift step");
        let lift_input_cid = lift_step
            .inputs
            .first()
            .map(ToString::to_string)
            .expect("lift input cid");
        let mint_step = path
            .algebra
            .iter()
            .find(|step| step.name == "mint")
            .expect("mint step");
        let mint_input_cid = mint_step.inputs.first().expect("mint input cid");
        let spec = match input.inputs.get_input(mint_input_cid) {
            Some(Input::Spec(value)) => value,
            other => panic!("expected mint spec, got {other:?}"),
        };

        assert_eq!(
            spec.pointer("/toolchainPlan/kind").and_then(Value::as_str),
            Some("component-plan")
        );
        assert_eq!(
            spec.pointer("/toolchainPlan/plugins/0/surface")
                .and_then(Value::as_str),
            Some("rust-test-assertions")
        );
        assert_eq!(
            spec.pointer("/toolchainPlan/pathSteps/0/name")
                .and_then(Value::as_str),
            Some("lift")
        );
        assert_eq!(
            spec.pointer("/toolchainPlan/pathSteps/0/kit")
                .and_then(Value::as_str),
            Some("lift-plugin:rust-test-assertions")
        );
        assert_eq!(
            spec.pointer("/toolchainPlan/pathSteps/0/inputCids/0")
                .and_then(Value::as_str),
            Some(lift_input_cid.as_str())
        );
        assert_eq!(
            spec.pointer("/toolchainPlan/pathSteps/1/name")
                .and_then(Value::as_str),
            Some("mint")
        );
        assert_eq!(
            spec.pointer("/toolchainPlan/pathSteps/1/dependsOn/0")
                .and_then(Value::as_str),
            Some("lift")
        );
        assert!(
            spec.pointer("/toolchainPlan/pathSteps/1/inputCids").is_none(),
            "the mint step input carries the plan letter, so it cannot be pinned inside the same letter"
        );
        assert!(
            spec.pointer("/toolchainPlan/expectedOutputCids").is_none(),
            "expected output CIDs are added after lifter outputs exist"
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn mint_ir_document_forwards_bridge_source_symbol_to_bindings() {
        let root = temp_workspace("mint_contract_bridge_source_symbol_forward");
        let out_dir = root.join("out");
        std::fs::create_dir_all(&out_dir).expect("create out dir");
        let ir = vec![json!({
            "kind": "function-contract",
            "name": "Widget::run",
            "bridgeSourceSymbol": "run",
            "formals": ["self"],
            "formalSorts": [{"kind": "primitive", "name": "unit"}],
            "returnSort": {"kind": "primitive", "name": "unit"},
            "pre": {"kind": "atomic", "name": "ready", "args": []},
            "post": {"kind": "atomic", "name": "true", "args": []},
            "bodyDischargeEligible": true
        })];

        let minted = mint_ir_document(&ir, None, None, None, &root, &out_dir, true)
            .expect("mint ir-document");
        let binding = minted
            .contract_bindings
            .iter()
            .find(|binding| binding["name"] == "Widget::run")
            .expect("producer binding");
        assert_eq!(binding["bridgeSourceSymbol"], "run");
        assert_eq!(binding["formals"], json!(["self"]));
        assert_eq!(
            binding["formalSorts"],
            json!([{"kind": "primitive", "name": "unit"}])
        );
        assert_eq!(
            binding["pre"],
            json!({"kind": "atomic", "name": "ready", "args": []})
        );
        assert_eq!(
            binding["post"],
            json!({"kind": "atomic", "name": "true", "args": []})
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn mint_ir_document_marks_only_nontrivial_pre_as_has_pre() {
        let root = temp_workspace("mint_contract_has_pre");
        let out_dir = root.join("out");
        std::fs::create_dir_all(&out_dir).expect("create out dir");
        let ir = vec![
            json!({
                "kind": "contract",
                "name": "trivial_pre",
                "outBinding": "out",
                "pre": {"kind": "atomic", "name": "true", "args": []}
            }),
            json!({
                "kind": "contract",
                "name": "guarded_pre",
                "outBinding": "out",
                "pre": {"kind": "atomic", "name": "is_some", "args": []}
            }),
        ];

        let minted = mint_ir_document(&ir, None, None, None, &root, &out_dir, true)
            .expect("mint ir-document");
        let by_name = |name: &str| {
            minted
                .contract_bindings
                .iter()
                .find(|binding| binding["name"] == name)
                .unwrap_or_else(|| {
                    panic!(
                        "missing binding `{name}` in {:#?}",
                        minted.contract_bindings
                    )
                })
        };

        assert_eq!(by_name("trivial_pre")["has_pre"], false);
        assert_eq!(by_name("trivial_pre")["body_bearing"], false);
        assert_eq!(by_name("guarded_pre")["has_pre"], true);
        assert_eq!(by_name("guarded_pre")["body_bearing"], true);

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn dependency_contract_bindings_keep_same_leaf_different_libraries() {
        let root = temp_workspace("dependency_contract_library_bindings");
        let imports_dir = root.join(".sugar").join("imports");
        std::fs::create_dir_all(&imports_dir).expect("create imports dir");

        for library in ["lib_a", "lib_b"] {
            let ir = vec![json!({
                "kind": "contract",
                "name": "same_leaf",
                "library": library,
                "outBinding": "out",
                "post": {"kind": "atomic", "name": "same_leaf_post", "args": []}
            })];
            let minted = mint_ir_document(&ir, None, None, None, &root, &root, true)
                .expect("mint dependency proof");
            // Name the proof by its content CID (blake3-512:...), as production
            // `.sugar/imports/` does: the loader rejects non-CID filenames
            // ("v1.1.0 requires blake3-512:"). Each library yields distinct
            // bytes -> distinct CID -> a separate proof file.
            let fname = format!("{}.proof", minted.filename_cid);
            std::fs::write(imports_dir.join(fname), minted.bytes).expect("write dependency proof");
        }

        let mut bindings = contract_bindings_from_dependency_proofs(&root);
        bindings.sort_by_key(|binding| {
            binding
                .get("library")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string()
        });

        let libraries: Vec<&str> = bindings
            .iter()
            .filter_map(|binding| binding.get("library").and_then(|v| v.as_str()))
            .collect();
        assert_eq!(libraries, vec!["lib_a", "lib_b"]);
        assert_eq!(
            bindings
                .iter()
                .filter(|binding| binding["name"] == "same_leaf")
                .count(),
            2
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn dependency_contract_bindings_accept_discharge_policy_body_reduction_refused() {
        let root = temp_workspace("dependency_contract_discharge_policy_refused");
        let imports_dir = root.join(".sugar").join("imports");
        std::fs::create_dir_all(&imports_dir).expect("create imports dir");
        // Use mint_from_ir_document so the proof carries a body-graph-backed
        // contract (bodyCid present); the new load_catalog_bytes rejects the old
        // inline (ClaimContractMemento / no bodyCid) format.
        let ir = vec![json!({
            "kind": "contract",
            "name": "new_policy_dep",
            "outBinding": "result",
            "post": {
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "var", "name": "result"},
                    {"kind": "var", "name": "x"}
                ]
            },
            "library": "dep_lib",
            "dischargePolicy": {
                "bodyReduction": {
                    "status": "refused",
                    "reason": "totality-axiom"
                }
            }
        })];
        let (proof_bytes, proof_cid, _) =
            mint_from_ir_document(&ir, None, None, None, &root, &root, false)
                .expect("mint dependency proof");
        std::fs::write(imports_dir.join(format!("{proof_cid}.proof")), &proof_bytes)
            .expect("write dependency proof");

        let bindings = contract_bindings_from_dependency_proofs(&root);
        let binding = bindings
            .iter()
            .find(|binding| binding["name"] == "new_policy_dep")
            .unwrap_or_else(|| panic!("missing new_policy_dep binding: {bindings:#?}"));

        assert_eq!(binding["bodyDischargeEligible"], false);
        assert_eq!(binding["bodyDischargeRefusalReason"], "totality-axiom");

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn mint_ir_document_accepts_discharge_policy_body_reduction_refused() {
        let root = temp_workspace("mint_ir_document_discharge_policy_refused");
        let out_dir = root.join("out");
        std::fs::create_dir_all(&out_dir).expect("create out dir");
        let ir = vec![json!({
            "kind": "function-contract",
            "name": "totality_axiom",
            "outBinding": "result",
            "formals": ["x"],
            "post": {
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "var", "name": "result"},
                    {"kind": "var", "name": "x"}
                ]
            },
            "dischargePolicy": {
                "bodyReduction": {
                    "status": "refused",
                    "reason": "totality-axiom"
                }
            }
        })];

        let minted = mint_ir_document(&ir, None, None, None, &root, &out_dir, true).expect("mint");
        let binding = minted
            .contract_bindings
            .iter()
            .find(|binding| binding["name"] == "totality_axiom")
            .unwrap_or_else(|| {
                panic!(
                    "missing totality_axiom binding: {:#?}",
                    minted.contract_bindings
                )
            });

        assert_eq!(binding["bodyDischargeEligible"], false);
        assert_eq!(binding["bodyDischargeRefusalReason"], "totality-axiom");

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn mint_from_ir_document_links_contract_to_authority_memento() {
        let ir = vec![json!({
            "kind": "contract",
            "name": "checked_add_u8.postcondition",
            "outBinding": "out",
            "authority": "bridgeworks.software",
            "post": {"kind": "atomic", "name": "checked_add_u8.postcondition", "args": []}
        })];
        let authorities = vec![
            json!({
                "id": "bridgeworks.root",
                "principal": "bridgeworks.root",
                "scopeKind": "proof",
                "scope": "authority-backed-test"
            }),
            json!({
                "id": "bridgeworks.software",
                "principal": "bridgeworks.software",
                "scopeKind": "contract",
                "scope": "checked_add_u8.postcondition",
                "parent": "bridgeworks.root"
            }),
        ];

        let (bytes, filename_cid, _) = mint_from_ir_document(
            &ir,
            Some(&authorities),
            None,
            None,
            Path::new("."),
            Path::new("."),
            true,
        )
        .expect("mint authority plus contract");
        let proof_path = PathBuf::from(format!("{filename_cid}.proof"));
        let report = sugar_verifier::proof_conformance::validate_proof_bytes(&proof_path, &bytes);
        assert!(
            report.errors.is_empty(),
            "authority-backed proof should inspect cleanly: {:?}",
            report.errors
        );

        let catalog = sugar_proof_envelope::ProofCatalog::read(&bytes).expect("read proof catalog");
        let proof_signer = catalog.signer.as_str();
        assert!(proof_signer.starts_with("blake3-512:"));

        let mut authority = None;
        let mut authority_member_cid = None;
        let mut contract = None;
        for view in catalog.graph.members_view() {
            let cid = view.cid().as_str();
            let envelope = view.json();
            match member_kind(&envelope) {
                Some("authority")
                    if member_field(&envelope, "principal").and_then(|v| v.as_str())
                        == Some("bridgeworks.software") =>
                {
                    authority_member_cid = Some(cid.to_string());
                    authority = Some(envelope);
                }
                Some("contract") => contract = Some(envelope),
                _ => {}
            }
        }
        let authority = authority.expect("authority memento");
        let authority_member_cid = authority_member_cid.expect("authority member cid");
        let contract = contract.expect("contract memento");
        let authority_key = member_field(&authority, "key")
            .and_then(|v| v.as_str())
            .expect("authority key");
        assert_eq!(
            member_field(&contract, "inputCids")
                .and_then(|v| v.as_array())
                .and_then(|a| a.first())
                .and_then(|v| v.as_str()),
            Some(authority_member_cid.as_str())
        );
        assert_eq!(
            sugar_proof_envelope::member_signer(&contract).and_then(|v| v.as_str()),
            Some(authority_key)
        );
    }

    #[test]
    fn mint_from_ir_document_rejects_implication_missing_contract() {
        let ir = vec![json!({
            "kind": "contract",
            "name": "upper.claim",
            "outBinding": "out",
            "post": {"kind": "atomic", "name": "upper_holds", "args": []}
        })];
        let implications = vec![json!({
            "name": "lower-implies-upper",
            "antecedent": "lower.claim",
            "consequent": "upper.claim",
            "antecedentSlot": "post",
            "consequentSlot": "post"
        })];

        let err = mint_from_ir_document(
            &ir,
            None,
            Some(&implications),
            None,
            Path::new("."),
            Path::new("."),
            true,
        )
        .expect_err("missing antecedent should fail");

        assert!(err.contains("lower.claim"), "error was: {err}");
    }

    #[test]
    fn empty_set_cid_is_stable() {
        // Verify compute_contract_set_cid([]) is stable across calls.
        let a = compute_contract_set_cid(vec![]);
        let b = compute_contract_set_cid(vec![]);
        assert_eq!(a, b);
        assert!(a.starts_with("blake3-512:"));
        // Print so the integration test can verify against the pinned value.
        eprintln!("empty-set CID = {a}");
    }

    // ── Cross-file inv-only conjoin regression (permanent) ─────────────────
    // When two IR entries share the SAME name and are both inv-only (inv
    // present, no pre/post), the pre-pass must conjoin them into ONE contract
    // with `inv = and(inv_a, inv_b)`.  Without the pre-pass, both contracts
    // land in the bundle as separate mementos; the consistency pass checks
    // them individually (each SAT) and the cross-file contradiction is hidden.
    //
    // These tests verify the pre-pass at the unit level so the verifier-level
    // behaviour (REFUSED on the conjoined inv) is a separate concern.
    //
    // Soundness invariant: bridge-bearing (pre/post) contracts with the same
    // name must NOT be merged — they represent different function contracts.

    fn inv_const(val: i64) -> Value {
        json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "var", "name": "x"},
                {"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": val}
            ]
        })
    }

    #[test]
    fn cross_file_same_name_inv_only_contracts_are_conjoined() {
        // Two same-named inv-only contracts (inv=1 and inv=2) must yield ONE
        // contract in the bundle with a conjoined `and` inv.
        let ir = vec![
            json!({
                "kind": "contract",
                "name": "make_value#euf#c:callresult_make_value_a1(v:x)::assertion",
                "outBinding": "out",
                "inv": inv_const(1)
            }),
            json!({
                "kind": "contract",
                "name": "make_value#euf#c:callresult_make_value_a1(v:x)::assertion",
                "outBinding": "out",
                "inv": inv_const(2)
            }),
        ];
        let tempdir = tempfile::tempdir().expect("tempdir");
        let (bytes, _, _) =
            mint_from_ir_document(&ir, None, None, None, Path::new("."), tempdir.path(), true)
                .expect("mint should succeed");
        // Decode and find the contract member.
        let graph = ProofGraph::read(&bytes).expect("decode catalog");
        let contract_cids: Vec<_> = graph
            .members_view()
            .filter(|v| v.kind().as_deref() == Some("contract"))
            .map(|v| v.cid().clone())
            .collect();
        // POSITIVE: exactly one contract (the two were coalesced, not doubled)
        assert_eq!(
            contract_cids.len(),
            1,
            "expected one conjoined contract, got {}",
            contract_cids.len()
        );
        // STRUCTURAL: the inv must be an `and` with two operands
        let inv = graph
            .contract_slot_json(&contract_cids[0], "inv")
            .expect("contract must have inv");
        assert_eq!(
            inv.get("kind").and_then(|k| k.as_str()),
            Some("and"),
            "conjoined inv must be kind=and; got: {inv}"
        );
        let operands = inv
            .get("operands")
            .and_then(|o| o.as_array())
            .expect("and must have operands array");
        assert_eq!(
            operands.len(),
            2,
            "conjoined inv must have 2 operands; got: {operands:#?}"
        );
    }

    #[test]
    fn cross_file_identical_inv_only_contracts_are_deduped_not_double_conjoined() {
        // Two same-named inv-only contracts with IDENTICAL invs must yield ONE
        // contract with the SAME inv (not `and(inv, inv)`).
        let ir = vec![
            json!({
                "kind": "contract",
                "name": "make_value#euf#c:callresult_make_value_a1(v:x)::assertion",
                "outBinding": "out",
                "inv": inv_const(1)
            }),
            json!({
                "kind": "contract",
                "name": "make_value#euf#c:callresult_make_value_a1(v:x)::assertion",
                "outBinding": "out",
                "inv": inv_const(1)
            }),
        ];
        let tempdir = tempfile::tempdir().expect("tempdir");
        let (bytes, _, _) =
            mint_from_ir_document(&ir, None, None, None, Path::new("."), tempdir.path(), true)
                .expect("mint should succeed");
        let graph = ProofGraph::read(&bytes).expect("decode catalog");
        let contract_cids: Vec<_> = graph
            .members_view()
            .filter(|v| v.kind().as_deref() == Some("contract"))
            .map(|v| v.cid().clone())
            .collect();
        // POSITIVE: exactly one contract (deduped, not doubled)
        assert_eq!(
            contract_cids.len(),
            1,
            "identical inv must yield one deduped contract, got {}",
            contract_cids.len()
        );
        // DISCRIMINATION: inv is NOT an `and` — it is just the original atomic
        let inv = graph
            .contract_slot_json(&contract_cids[0], "inv")
            .expect("contract must have inv");
        assert_ne!(
            inv.get("kind").and_then(|k| k.as_str()),
            Some("and"),
            "identical inv must NOT be wrapped in `and`; got: {inv}"
        );
    }

    #[test]
    fn cross_file_pre_bearing_same_name_contracts_are_not_merged() {
        // A pre/post-bearing contract with the same name must NOT be merged
        // with an inv-only one — they represent different obligations.
        let pre_bearing = json!({
            "kind": "contract",
            "name": "make_value::contract",
            "outBinding": "out",
            "pre": {"kind": "atomic", "name": "≠", "args": [
                {"kind": "var", "name": "x"},
                {"kind": "ctor", "name": "None", "args": []}
            ]},
            "inv": inv_const(1)
        });
        let inv_only = json!({
            "kind": "contract",
            "name": "make_value::contract",
            "outBinding": "out",
            "inv": inv_const(2)
        });
        let ir = vec![pre_bearing, inv_only];
        let tempdir = tempfile::tempdir().expect("tempdir");
        let (bytes, _, _) =
            mint_from_ir_document(&ir, None, None, None, Path::new("."), tempdir.path(), true)
                .expect("mint should succeed");
        let graph = ProofGraph::read(&bytes).expect("decode catalog");
        let contract_cids: Vec<_> = graph
            .members_view()
            .filter(|v| v.kind().as_deref() == Some("contract"))
            .map(|v| v.cid().clone())
            .collect();
        // DISCRIMINATION: pre-bearing contract must NOT be merged with inv-only.
        // Both must survive (different shapes).
        assert_eq!(
            contract_cids.len(),
            2,
            "pre-bearing + inv-only must both survive (no cross-shape merge), got {}",
            contract_cids.len()
        );
        // The pre-bearing one must still carry `pre`
        let has_pre_bearing = contract_cids
            .iter()
            .any(|cid| graph.contract_slot_json(cid, "pre").is_some());
        assert!(
            has_pre_bearing,
            "pre-bearing contract must not be merged away"
        );
    }
}
