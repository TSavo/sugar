// SPDX-License-Identifier: Apache-2.0
//
// Stage 1: load_all_proofs. Walk <project_root> for *.proof files,
// CBOR-decode the catalog, JSON-parse each member envelope, recompute
// every CID, reject mismatches, index by CID and by sourceSymbol.
//
// v1.1.0: the canonical on-disk filename is `blake3-512_<128 hex>.proof`
// (the CID's `:` replaced by `_` for Windows; the `blake3-512` prefix is
// retained for hash-algorithm agility). The legacy `blake3-512:<hex>` and
// bare `<hex>` stems are also accepted (parsed via
// `sugar_proof_envelope::cid_from_proof_stem`). Member CIDs MUST start
// with `"blake3-512:"`. Member signatures, when present, MUST verify
// cryptographically. Unsigned members remain accepted for now.
//
// v1.2 layered shape (per protocol/specs/2026-05-03-substrate-layers-
// envelope-header-body.md): mementos are `{envelope, header, metadata}`
// with `envelope = {signer, declaredAt, signature}`. The attestation
// CID is `blake3_512(JCS(envelope))`. The verifier branches on the
// presence of a top-level `envelope` key vs. `producerSignature` to
// pick the legacy strip-and-rehash path or the envelope-hash path.
// Both shapes coexist; the catalog cut elsewhere bumps the per-memento
// `schemaVersion` from "1" to "2".

use std::path::{Path, PathBuf};

use serde_json::Value as Json;
use sugar_canonicalizer::blake3_512_of;
use tracing::{debug, info, warn};

use sugar_proof_envelope::{
    AnchoredMember, AtomCid, ContractBodyCid, MemberKind, MementoCid, ProofGraph, StoredMember,
};

use crate::types::{EffectSiteAnnotation, LoadError, MementoPool};

const PANIC_FREEDOM_EFFECT: &str = "panic-freedom";
const EFFECT_SITE_ANNOTATION_LOAD_ERROR_TAG: &str = "[effect-site-annotation]";
const EFFECT_SITE_ANNOTATION_DUPLICATE_LOAD_ERROR_TAG: &str = "[effect-site-annotation-duplicate]";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProofBytes {
    pub label: String,
    pub expected_cid: MementoCid,
    pub bytes: Vec<u8>,
}

impl ProofBytes {
    pub fn try_from_parts(
        label: impl Into<String>,
        expected_cid: impl Into<String>,
        bytes: Vec<u8>,
    ) -> Result<Self, String> {
        let raw = expected_cid.into();
        let expected_cid = MementoCid::try_parse(raw.clone()).map_err(|_| {
            format!("invalid expected proof CID `{raw}`; expected blake3-512:<128 lowercase hex>")
        })?;
        Ok(Self {
            label: label.into(),
            expected_cid,
            bytes,
        })
    }
}

pub fn run(project_root: &Path) -> MementoPool {
    let _span = tracing::info_span!("load_all_proofs", root = %project_root.display()).entered();
    info!(root = %project_root.display(), "load_all_proofs: scanning for .proof files");
    let mut pool = MementoPool::default();
    for path in enumerate_proof_files(project_root) {
        debug!(path = %path.display(), "load_all_proofs: loading .proof file");
        load_path_into_pool(&path, &mut pool);
    }
    info!(
        mementos = pool.mementos.len(),
        load_errors = pool.load_errors.len(),
        "load_all_proofs: complete"
    );
    if !pool.load_errors.is_empty() {
        for err in &pool.load_errors {
            warn!(
                proof_path = %err.proof_path,
                reason = %err.reason,
                "load_all_proofs: load error"
            );
        }
    }
    pool
}

pub fn run_with_files(project_root: &Path, proof_files: &[PathBuf]) -> MementoPool {
    let mut pool = run(project_root);
    load_files_into_pool(proof_files, &mut pool);
    pool
}

pub fn load_files_into_pool(proof_files: &[PathBuf], pool: &mut MementoPool) {
    let mut proof_files = proof_files.to_vec();
    proof_files.sort();
    proof_files.dedup();
    for path in proof_files {
        load_path_into_pool(&path, pool);
    }
}

pub fn load_proof_bytes_into_pool(proofs: &[ProofBytes], pool: &mut MementoPool) {
    let mut proofs = proofs.to_vec();
    proofs.sort_by(|a, b| {
        (a.expected_cid.as_str(), a.label.as_str())
            .cmp(&(b.expected_cid.as_str(), b.label.as_str()))
    });
    proofs.dedup_by(|a, b| a.expected_cid == b.expected_cid && a.bytes == b.bytes);
    for proof in proofs {
        load_bytes_into_pool(&proof.label, &proof.expected_cid, &proof.bytes, pool);
    }
}

fn load_path_into_pool(path: &Path, pool: &mut MementoPool) {
    match load_one(path, pool) {
        Ok(()) => {}
        Err(e) => pool.load_errors.push(LoadError {
            proof_path: path.display().to_string(),
            reason: format!("read/decode: {e}"),
        }),
    }
}

fn enumerate_proof_files(project_root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    if !project_root.exists() {
        return out;
    }
    for entry in walkdir::WalkDir::new(project_root)
        .follow_links(true)
        .into_iter()
        .filter_map(|e| e.ok())
    {
        if entry.file_type().is_file() {
            if let Some(ext) = entry.path().extension() {
                if ext == "proof" {
                    out.push(entry.path().to_path_buf());
                }
            }
        }
    }
    out
}

fn load_one(path: &Path, pool: &mut MementoPool) -> Result<(), Box<dyn std::error::Error>> {
    let bytes = std::fs::read(path)?;
    let source_label = path.display().to_string();

    // Rule 1: filename CID matches content (trust root).
    let filename = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or_default()
        .to_string();
    let stem = filename.trim_end_matches(".proof");
    // We accept three filename shapes, all parsed by the shared helper:
    //   * `blake3-512_<hex>` - the colon-free on-disk form (Windows-safe)
    //   * `blake3-512:<hex>` - the legacy colon form
    //   * `<hex>`            - a bare 128-hex stem
    // The trust root is recomputed from the bytes regardless; the
    // filename is advisory. A non-hex stem still errors loud.
    let derived_full = blake3_512_of(&bytes);
    match sugar_proof_envelope::cid_from_proof_stem(stem) {
        Some(filename_cid) => {
            let filename_cid = computed_memento_cid(filename_cid);
            let derived_full = computed_memento_cid(derived_full);
            if filename_cid != derived_full {
                pool.load_errors.push(LoadError {
                    proof_path: source_label,
                    reason: format!(
                        "rule 1 (trust root): filename CID {filename_cid} != content hash {derived_full}"
                    ),
                });
                return Ok(());
            }
            return load_catalog_bytes(path.display().to_string(), &derived_full, &bytes, pool);
        }
        None => {
            // Stem isn't a recognizable CID (e.g. the negative fixture
            // `invalid-filename-cid`). v1.1.0 requires a `blake3-512`
            // stem; reject loud. (C++ rejects unknown tags the same way.)
            pool.load_errors.push(LoadError {
                proof_path: source_label,
                reason: format!(
                    "rule 1: filename '{filename}' has non-hex stem; v1.1.0 requires `blake3-512`"
                ),
            });
            return Ok(());
        }
    }
}

fn load_bytes_into_pool(
    source_label: &str,
    expected_cid: &MementoCid,
    bytes: &[u8],
    pool: &mut MementoPool,
) {
    if let Err(e) = load_catalog_bytes(source_label.to_string(), expected_cid, bytes, pool) {
        pool.load_errors.push(LoadError {
            proof_path: source_label.to_string(),
            reason: format!("read/decode: {e}"),
        });
    }
}

fn load_catalog_bytes(
    source_label: String,
    expected_cid: &MementoCid,
    bytes: &[u8],
    pool: &mut MementoPool,
) -> Result<(), Box<dyn std::error::Error>> {
    // Rule 1: content hash matches the expected CID.
    let derived_full = computed_memento_cid(blake3_512_of(bytes));
    if expected_cid != &derived_full {
        pool.load_errors.push(LoadError {
            proof_path: source_label,
            reason: format!(
                "rule 1 (trust root): expected proof CID {expected_cid} != content hash {derived_full}"
            ),
        });
        return Ok(());
    }

    // Parse the CBOR catalog into a typed ProofGraph. This validates atom
    // and body CID integrity by recomputation; a mismatch rejects the whole
    // catalog (a partially-corrupted proof file is invalid in its entirety).
    let graph = match ProofGraph::read(bytes) {
        Ok(g) => g,
        Err(e) => {
            pool.load_errors.push(LoadError {
                proof_path: source_label,
                reason: format!("graph read: {e}"),
            });
            return Ok(());
        }
    };

    // Atoms -> pool: CIDs already verified by ProofGraph::read().
    for atom in graph.atoms() {
        let atom_cid = computed_atom_cid(atom.cid().as_str().to_string());
        pool.atoms
            .entry(atom_cid)
            .or_insert_with(|| atom.bytes().to_vec());
    }

    // Bodies -> pool: CIDs already verified by ProofGraph::read().
    for body in graph.bodies() {
        let body_cid = computed_body_cid(body.cid().as_str().to_string());
        pool.body
            .entry(body_cid)
            .or_insert_with(|| body.bytes().to_vec());
    }

    // Members -> pool: per-member validation (CID recomputation, signature
    // verification when present,
    // contract body-pointer resolution) then indexing. ProofGraph::read()
    // guarantees all member CIDs carry the `blake3-512:` prefix.
    for view in graph.members_view() {
        let cid = match MementoCid::try_parse(view.cid().as_str().to_string()) {
            Ok(cid) => cid,
            Err(raw) => {
                pool.load_errors.push(LoadError {
                    proof_path: source_label.clone(),
                    reason: format!("member {raw}: invalid member CID format"),
                });
                continue;
            }
        };
        let env: Json = match serde_json::from_slice(view.bytes()) {
            Ok(v) => v,
            Err(e) => {
                pool.load_errors.push(LoadError {
                    proof_path: source_label.clone(),
                    reason: format!("member {cid}: JSON parse: {e}"),
                });
                continue;
            }
        };
        let anchored = match AnchoredMember::new(cid.clone(), env) {
            Ok(member) => member,
            Err(error) => {
                pool.load_errors.push(LoadError {
                    proof_path: source_label.clone(),
                    reason: error,
                });
                continue;
            }
        };
        let bridge_index =
            match pool.try_insert_anchored_with(anchored, |stored_cid, member, pool| {
                let kind = member.kind();
                match kind {
                    MemberKind::Contract => {
                        let Some(body_cid) = member
                            .field("bodyCid")
                            .and_then(|v| v.as_str())
                            .filter(|s| !s.is_empty())
                            .and_then(|raw| ContractBodyCid::try_parse(raw.to_string()).ok())
                        else {
                            pool.load_errors.push(LoadError {
                                proof_path: source_label.clone(),
                                reason: format!(
                                    "contract {stored_cid}: missing bodyCid; legacy inline contract bodies are not a valid .proof graph"
                                ),
                            });
                            return None;
                        };
                        if !pool.body.contains_key(&body_cid) {
                            pool.load_errors.push(LoadError {
                                proof_path: source_label.clone(),
                                reason: format!(
                                    "contract {stored_cid}: bodyCid {body_cid} is not present in catalog `body` map"
                                ),
                            });
                            return None;
                        }
                    }
                    MemberKind::AliasingMemento
                    | MemberKind::AssertionSurfaceMemento
                    | MemberKind::Authority
                    | MemberKind::Bridge
                    | MemberKind::ClosureBinding
                    | MemberKind::EffectSiteAnnotation
                    | MemberKind::FactoryWalkMemento
                    | MemberKind::Implication
                    | MemberKind::LibrarySugarBindingEntry
                    | MemberKind::LoopInvariant
                    | MemberKind::PinInvariant
                    | MemberKind::PlanMemento
                    | MemberKind::ProofRun
                    | MemberKind::SourceMemento
                    | MemberKind::StageReceipt
                    | MemberKind::TryBranch
                    | MemberKind::Witness
                    | MemberKind::WitnessMemento => {}
                }
                // Bridge indexing metadata. StoredMember normalizes v1.1
                // (evidence.body.sourceSymbol), lean (body/header.sourceSymbol),
                // and v1.2 (header.sourceSymbol) before indexing. The indexes
                // themselves store only the bridge memento CID; the verified
                // member lives once in `pool.mementos`.
                let bridge_index = match kind {
                    MemberKind::Bridge => member
                        .field("sourceSymbol")
                        .and_then(|v| v.as_str())
                        .filter(|s| !s.is_empty())
                        .map(|sym| {
                            let callsite_key = member.body().and_then(|body| {
                                let cs = body.get("callsite");
                                let file = cs
                                    .and_then(|v| v.get("file"))
                                    .and_then(|v| v.as_str())
                                    .filter(|s| !s.is_empty());
                                let line = cs
                                    .and_then(|v| v.get("start_line").or_else(|| v.get("line")))
                                    .and_then(|v| v.as_u64())
                                    .map(|n| n as usize);
                                match (file, line) {
                                    (Some(file), Some(line)) => Some((
                                        derived_full.clone(),
                                        file.to_string(),
                                        line,
                                        sym.to_string(),
                                    )),
                                    _ => None,
                                }
                            });
                            (sym.to_string(), callsite_key)
                        }),
                    MemberKind::AliasingMemento
                    | MemberKind::AssertionSurfaceMemento
                    | MemberKind::Authority
                    | MemberKind::ClosureBinding
                    | MemberKind::Contract
                    | MemberKind::EffectSiteAnnotation
                    | MemberKind::FactoryWalkMemento
                    | MemberKind::Implication
                    | MemberKind::LibrarySugarBindingEntry
                    | MemberKind::LoopInvariant
                    | MemberKind::PinInvariant
                    | MemberKind::PlanMemento
                    | MemberKind::ProofRun
                    | MemberKind::SourceMemento
                    | MemberKind::StageReceipt
                    | MemberKind::TryBranch
                    | MemberKind::Witness
                    | MemberKind::WitnessMemento => None,
                };

                // Track bundle membership so resolve_target can enforce
                // BridgeDeclaration.ConsequentBundlePinned. The bundle's CID is
                // the .proof file's content hash (derived_full above). A given
                // member CID may legitimately appear in more than one bundle;
                // the per-bundle set is what matters at resolve time.
                pool.bundle_members
                    .entry(derived_full.clone())
                    .or_default()
                    .insert(stored_cid.clone());
                index_effect_site_annotation(
                    &source_label,
                    &derived_full,
                    stored_cid,
                    member,
                    pool,
                );

                Some(bridge_index)
            }) {
                Ok(Some(bridge_index)) => bridge_index,
                Ok(None) => continue,
                Err(error) => {
                    pool.load_errors.push(LoadError {
                        proof_path: source_label.clone(),
                        reason: format!("member {cid}: {error}"),
                    });
                    continue;
                }
            };

        if let Some((sym, callsite_key)) = bridge_index {
            pool.bridges_by_symbol.insert(sym.clone(), cid.clone());
            // Record the bundle this bridge was loaded from so the
            // self-pinned (no targetProofCid) case can be enforced as
            // same-bundle co-membership. `derived_full` is this
            // `.proof`'s content CID (the bundle CID).
            pool.bridge_self_bundle_by_symbol
                .insert(sym, derived_full.clone());
            // Callsite-scoped index. A bridge whose body carries a
            // `callsite` with file + line is the producer guarantee for
            // a SPECIFIC call (not just the symbol). Keying it by
            // `(bundle, file, line, symbol)` lets a panic obligation
            // whose arg is itself a call select the producer post that
            // governs THAT call, rather than whichever same-symbol
            // bridge won the per-symbol slot. Bundle scoping is required
            // for soundness: relative paths (`src/lib.rs`) collide
            // across crates. First-writer wins per full key.
            if let Some(key) = callsite_key {
                pool.bridges_by_callsite
                    .entry(key)
                    .or_insert_with(|| cid.clone());
            }
        }
    }
    Ok(())
}

fn computed_memento_cid(cid: String) -> MementoCid {
    MementoCid::try_parse(cid).expect("computed BLAKE3-512 CID must parse")
}

fn computed_atom_cid(cid: String) -> AtomCid {
    AtomCid::try_parse(cid).expect("computed atom CID must parse")
}

fn computed_body_cid(cid: String) -> ContractBodyCid {
    ContractBodyCid::try_parse(cid).expect("computed contract body CID must parse")
}

fn index_effect_site_annotation(
    source_label: &str,
    bundle_cid: &MementoCid,
    memento_cid: &MementoCid,
    member: &StoredMember,
    pool: &mut MementoPool,
) {
    if member.kind() != MemberKind::EffectSiteAnnotation {
        return;
    }
    let Some(body) = member.body() else {
        pool.load_errors.push(LoadError {
            proof_path: source_label.to_string(),
            reason: format!(
                "{EFFECT_SITE_ANNOTATION_LOAD_ERROR_TAG} {memento_cid}: missing header/body"
            ),
        });
        return;
    };

    let Some(effect_kind) =
        required_annotation_string(source_label, memento_cid, body, "effectKind", pool)
    else {
        return;
    };
    if effect_kind != PANIC_FREEDOM_EFFECT {
        return;
    }
    let Some(file) = required_annotation_string(source_label, memento_cid, body, "file", pool)
    else {
        return;
    };
    let Some(line) = required_annotation_line(source_label, memento_cid, body, pool) else {
        return;
    };
    let Some(callee) = required_annotation_string(source_label, memento_cid, body, "callee", pool)
    else {
        return;
    };
    let Some(status) = required_annotation_string(source_label, memento_cid, body, "status", pool)
    else {
        return;
    };
    if !matches!(status.as_str(), "residue" | "unproven") {
        pool.load_errors.push(LoadError {
            proof_path: source_label.to_string(),
            reason: format!(
                "{EFFECT_SITE_ANNOTATION_LOAD_ERROR_TAG} {memento_cid}: status must be residue or unproven"
            ),
        });
        return;
    }
    let Some(category) =
        required_annotation_string(source_label, memento_cid, body, "category", pool)
    else {
        return;
    };
    let Some(tier_to_close) =
        required_annotation_string(source_label, memento_cid, body, "tierToClose", pool)
    else {
        return;
    };
    let Some(reason) = required_annotation_string(source_label, memento_cid, body, "reason", pool)
    else {
        return;
    };

    let key = (bundle_cid.clone(), file.clone(), line, callee.clone());
    let annotation = EffectSiteAnnotation {
        effect_kind,
        file,
        line,
        callee,
        status,
        category,
        tier_to_close,
        reason,
        memento_cid: memento_cid.to_string(),
        bundle_cid: bundle_cid.to_string(),
    };
    if let Some(existing) = pool.panic_effect_site_annotations.get(&key) {
        pool.load_errors.push(LoadError {
            proof_path: source_label.to_string(),
            reason: format!(
                "{EFFECT_SITE_ANNOTATION_DUPLICATE_LOAD_ERROR_TAG} for ({}, {}, {}, {}): kept `{}`, dropped `{}`",
                            key.0, key.1, key.2, key.3, existing.memento_cid, memento_cid
                        ),
                    });
        return;
    }
    pool.panic_effect_site_annotations.insert(key, annotation);
}

fn required_annotation_string(
    source_label: &str,
    memento_cid: &MementoCid,
    body: &Json,
    field: &str,
    pool: &mut MementoPool,
) -> Option<String> {
    let value = body
        .get(field)
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty());
    match value {
        Some(value) => Some(value.to_string()),
        None => {
            pool.load_errors.push(LoadError {
                proof_path: source_label.to_string(),
                reason: format!(
                    "{EFFECT_SITE_ANNOTATION_LOAD_ERROR_TAG} {memento_cid}: missing or invalid `{field}`"
                ),
            });
            None
        }
    }
}

fn required_annotation_line(
    source_label: &str,
    memento_cid: &MementoCid,
    body: &Json,
    pool: &mut MementoPool,
) -> Option<usize> {
    match body.get("line").and_then(|v| v.as_u64()) {
        Some(line) if usize::try_from(line).is_ok() => Some(line as usize),
        _ => {
            pool.load_errors.push(LoadError {
                proof_path: source_label.to_string(),
                reason: format!(
                    "{EFFECT_SITE_ANNOTATION_LOAD_ERROR_TAG} {memento_cid}: missing or invalid `line`"
                ),
            });
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sugar_claim_envelope::{mint_effect_site_annotation, MintEffectSiteAnnotationArgs};
    use sugar_proof_envelope::{
        build_proof_envelope, EffectSiteAnnotationMemento, ProofEnvelopeInput, ProofGraph,
    };

    const PANIC_EFFECT: &str = "panic-freedom";

    fn annotation_args(
        effect_kind: &str,
        file: &str,
        line: usize,
        callee: &str,
        status: &str,
        category: &str,
        reason: &str,
    ) -> MintEffectSiteAnnotationArgs {
        MintEffectSiteAnnotationArgs {
            effect_kind: effect_kind.to_string(),
            file: file.to_string(),
            line,
            callee: callee.to_string(),
            status: status.to_string(),
            category: category.to_string(),
            tier_to_close: "irreducible".to_string(),
            reason: reason.to_string(),
            input_cids: Vec::new(),
            produced_by: "test".to_string(),
            produced_at: "2026-06-01T00:00:00Z".to_string(),
            signer_seed: [0x42; 32],
        }
    }

    fn proof_bytes(members: Vec<sugar_claim_envelope::MintedEnvelope>) -> ProofBytes {
        let mut graph = ProofGraph::new();
        for member in members {
            let cid = member.cid.clone();
            let memento = EffectSiteAnnotationMemento::new(member.canonical_bytes);
            assert_eq!(memento.cid().as_str(), cid);
            graph.push_effect_site_annotation(memento);
        }
        let proof = build_proof_envelope(&ProofEnvelopeInput {
            name: "annotation-test".to_string(),
            version: "1.0.0".to_string(),
            binary_cid: None,
            metadata: None,
            graph,
            signer_cid: "test-signer".to_string(),
            signer_seed: [0x24; 32],
            declared_at: "2026-06-01T00:00:00Z".to_string(),
        });
        ProofBytes::try_from_parts("annotation-test.proof".to_string(), proof.cid, proof.bytes)
            .expect("built proof CID must parse")
    }

    #[test]
    fn proof_bytes_expected_cid_rejects_bad_prefix_before_loading() {
        let err = ProofBytes::try_from_parts(
            "bad-rpc-proof.proof",
            "sha256:not-a-blake3-proof-cid",
            b"not a proof catalog".to_vec(),
        )
        .expect_err("bad expected proof CID must fail before loader lookup");

        assert!(
            err.contains("invalid expected proof CID")
                && err.contains("sha256:not-a-blake3-proof-cid"),
            "unexpected parse error: {err}"
        );
    }

    #[test]
    fn proof_bytes_expected_cid_rejects_bad_hex_before_loading() {
        let err = ProofBytes::try_from_parts(
            "bad-rpc-proof.proof",
            "blake3-512:not-hex",
            b"not a proof catalog".to_vec(),
        )
        .expect_err("bad expected proof CID hex must fail before loader lookup");

        assert!(
            err.contains("invalid expected proof CID") && err.contains("blake3-512:not-hex"),
            "unexpected parse error: {err}"
        );
    }

    #[test]
    fn load_all_proofs_indexes_panic_effect_site_annotation_by_bundle_and_site() {
        let annotation = mint_effect_site_annotation(&annotation_args(
            PANIC_EFFECT,
            "src/lib.rs",
            42,
            "method:unwrap",
            "residue",
            "lock_poisoning_residue",
            "lock poisoning is runtime residue",
        ))
        .expect("mint annotation");
        let proof = proof_bytes(vec![annotation]);
        let expected_bundle = proof.expected_cid.clone();
        let mut pool = MementoPool::default();

        load_proof_bytes_into_pool(&[proof], &mut pool);

        let key = (
            expected_bundle,
            "src/lib.rs".to_string(),
            42,
            "method:unwrap".to_string(),
        );
        let indexed = pool
            .panic_effect_site_annotations
            .get(&key)
            .expect("annotation indexed by bundle/site");
        assert_eq!(indexed.status, "residue");
        assert_eq!(indexed.category, "lock_poisoning_residue");
        assert_eq!(indexed.tier_to_close, "irreducible");
        assert!(pool.load_errors.is_empty(), "{:#?}", pool.load_errors);
    }

    #[test]
    fn load_all_proofs_ignores_non_panic_effect_site_annotation() {
        let annotation = mint_effect_site_annotation(&annotation_args(
            "non-panic-effect",
            "src/lib.rs",
            42,
            "read",
            "unproven",
            "io_residue",
            "not a panic-freedom annotation",
        ))
        .expect("mint annotation");
        let proof = proof_bytes(vec![annotation]);
        let mut pool = MementoPool::default();

        load_proof_bytes_into_pool(&[proof], &mut pool);

        assert!(pool.panic_effect_site_annotations.is_empty());
        assert!(pool.load_errors.is_empty(), "{:#?}", pool.load_errors);
    }

    #[test]
    fn load_all_proofs_reports_malformed_panic_effect_site_annotation() {
        let mut annotation = mint_effect_site_annotation(&annotation_args(
            PANIC_EFFECT,
            "src/lib.rs",
            42,
            "method:unwrap",
            "residue",
            "lock_poisoning_residue",
            "lock poisoning is runtime residue",
        ))
        .expect("mint annotation");
        let mut env: serde_json::Value =
            serde_json::from_slice(&annotation.canonical_bytes).expect("parse annotation");
        env.pointer_mut("/header")
            .and_then(|v| v.as_object_mut())
            .expect("header object")
            .remove("callee");
        // This fixture mutates the signed payload to exercise annotation
        // validation; signature enforcement itself is covered by integration
        // tests.
        env.pointer_mut("/envelope")
            .and_then(|v| v.as_object_mut())
            .expect("envelope object")
            .remove("signature");
        annotation.cid = sugar_proof_envelope::recompute_member_cid(&env);
        annotation.canonical_bytes =
            serde_json::to_vec(&env).expect("serialize malformed annotation");
        let proof = proof_bytes(vec![annotation]);
        let mut pool = MementoPool::default();

        load_proof_bytes_into_pool(&[proof], &mut pool);

        assert!(pool.panic_effect_site_annotations.is_empty());
        assert!(
            pool.load_errors
                .iter()
                .any(|err| err.reason.contains("effect-site-annotation")
                    && err.reason.contains("callee")),
            "missing callee should be a typed load error: {:#?}",
            pool.load_errors
        );
    }

    #[test]
    fn load_all_proofs_reports_duplicate_effect_site_annotation_key() {
        let first = mint_effect_site_annotation(&annotation_args(
            PANIC_EFFECT,
            "src/lib.rs",
            42,
            "method:unwrap",
            "residue",
            "lock_poisoning_residue",
            "first annotation",
        ))
        .expect("mint first annotation");
        let second = mint_effect_site_annotation(&annotation_args(
            PANIC_EFFECT,
            "src/lib.rs",
            42,
            "method:unwrap",
            "unproven",
            "D-lib",
            "second annotation",
        ))
        .expect("mint second annotation");
        let proof = proof_bytes(vec![first, second]);
        let mut pool = MementoPool::default();

        load_proof_bytes_into_pool(&[proof], &mut pool);

        assert!(
            pool.load_errors
                .iter()
                .any(|err| err.reason.contains("effect-site-annotation-duplicate")),
            "duplicate effect-site annotation should fail loud: {:#?}",
            pool.load_errors
        );
    }
}
