// SPDX-License-Identifier: Apache-2.0
//
// sugar-lift: workspace lift toolchain.
//
// Walks a Rust workspace (or single crate), parses every `.rs` file
// with syn, dispatches each parsed file to all registered adapters,
// collects ContractDecls, mints them via sugar_claim_envelope, and
// bundles the result into a single signed `.proof` catalog.
//
// STRATEGIC POSITIONING (read this before extending):
//
//   Sugar does NOT compete with proptest, contracts, kani, prusti,
//   hypothesis-py, deal-py, bean-validation-java, zod-ts, etc. It sits
//   BENEATH them. Developers keep their existing annotation library;
//   `sugar-lift` reads what's already there and promotes it to a
//   content-addressed signed contract.
//
//   There is no bespoke contract-authoring macro. Greenfield code is
//   handled the same way: write the contract in a native annotation
//   library (or as native source the adapters understand), then lift it.
//   A contract only enters the substrate by being lifted.
//
// LIBRARY API:
//
//   `lift_path(workspace_root, options)` walks the directory tree,
//   runs every adapter, and returns a `LiftReport`.
//
//   `mint_proof(decls, options)` takes lifted decls and mints a signed
//   `.proof` byte blob plus its CID.
//
//   `lift_and_mint(workspace_root, options)` is the convenience that
//   does both and writes the file.
//
// CARGO SUBCOMMAND:
//
//   `cargo sugar-lift [--workspace <dir>] [--target-dir <out>]`
//   wires through the bin `cargo-sugar-lift`. We also ship a plain
//   `sugar-lift` bin for direct invocation.

use base64::Engine;
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use std::rc::Rc;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};
use sugar_claim_envelope::{
    compute_contract_set_cid, contract_cid as compute_contract_cid, mint_contract_with_body_cid,
    Authoring, MintContractArgs, KIT_DECLARATION_RPC_METHOD,
};
use sugar_ir_symbolic::{serialize::formula_to_value, ContractDecl, Formula};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, proof_filename, AtomMemento, ClaimContractMemento,
    ContractBody, Ed25519Seed, FlatAtom, ProofEnvelopeInput, ProofGraph,
};

pub mod call_edges;
pub use call_edges::{
    extract_call_edges_from_file, mint_call_edge, CallEdgeMemento, CallSiteLocus,
};

// THE SEVER: the rust `#[requires]`/`#[ensures]` contract lifter is no
// longer statically linked. `lift_path` dispatches it over RPC (the
// `contracts_rpc` kit) via the shared leaf client, then deserializes the
// returned ir-document back into `ContractDecl`s with the public
// `parse_document` (the inverse of `marshal_declarations`). Downstream
// (mint, call-edge extraction, linkerd's conversion) keeps consuming
// `ContractDecl` UNCHANGED — the RPC seam is localized to `lift_path`.

/// Per-adapter outcome. Counts what each adapter saw and what was
/// liftable. The `warnings` are the honest "I saw it but couldn't
/// translate" log surfaced to the caller.
#[derive(Debug, Default, Clone)]
pub struct AdapterReport {
    pub adapter: &'static str,
    pub seen: usize,
    pub lifted: usize,
    pub warnings: Vec<AdapterWarning>,
}

#[derive(Debug, Clone)]
pub struct AdapterWarning {
    pub adapter: &'static str,
    pub source_path: String,
    pub item_name: String,
    pub reason: String,
}

#[derive(Debug, Default)]
pub struct LiftReport {
    pub decls: Vec<ContractDecl>,
    /// Call-edge mementos extracted per spec #114 §1 R1.
    /// One memento per call site within a contracted function.
    pub call_edges: Vec<CallEdgeMemento>,
    pub adapter_reports: Vec<AdapterReport>,
    pub files_scanned: usize,
    pub parse_errors: Vec<(String, String)>,
}

#[derive(Debug, Clone)]
pub struct LiftOptions {
    /// Producer identity included in each minted memento.
    pub produced_by: String,
    /// ISO-8601 with millisecond precision and trailing 'Z'.
    pub produced_at: String,
    /// Ed25519 signing seed. Default is the shared dev seed
    /// `[0x42; 32]` so demos are reproducible across machines.
    pub signer_seed: Ed25519Seed,
    /// Lifter identity recorded in `Authoring::Lift`.
    pub lifter: String,
    /// Catalog name written into the `.proof` envelope.
    pub catalog_name: String,
    /// Catalog version string.
    pub catalog_version: String,
}

impl Default for LiftOptions {
    fn default() -> Self {
        Self {
            produced_by: "sugar-lift@0.1.0".into(),
            produced_at: "2026-04-30T00:00:00.000Z".into(),
            signer_seed: [0x42; 32],
            lifter: "sugar-lift".into(),
            catalog_name: "@sugar/lift".into(),
            catalog_version: "0.1.0".into(),
        }
    }
}

/// Walk the workspace at `root`, running every adapter on every `.rs`
/// file. Skips `target/`, `.git/`, and the toolchain's own crates so
/// fixtures planted in this crate don't pollute caller workspaces.
pub fn lift_path(root: &Path) -> LiftReport {
    let mut report = LiftReport::default();

    // Per-adapter accumulators keyed by adapter name.
    let mut contracts_warnings: Vec<AdapterWarning> = Vec::new();

    // Enumerate the workspace's `.rs` files once. The same relative POSIX
    // paths are the cross-platform-deterministic source locators passed to
    // the lift kit AND used for call-edge extraction (absolute paths embed
    // the machine's directory prefix; relative POSIX paths are identical for
    // identical source trees on any host).
    let rs_files = enumerate_rs_files(root);
    report.files_scanned = rs_files.len();
    let source_paths: Vec<String> = rs_files.iter().map(|(rel, _)| rel.clone()).collect();

    // THE SEVER: dispatch the rust-contracts lift kit over RPC instead of
    // calling the contracts adapter's lift_file statically. One dispatch over
    // the whole workspace; the kit walks the supplied `source_paths` and
    // returns an ir-document. We deserialize its `ir` array back into
    // `ContractDecl`s via the public `parse_document` (the enforced inverse
    // of `marshal_declarations`), so every downstream consumer — mint,
    // call-edge extraction, linkerd's conversion — keeps seeing
    // `ContractDecl` exactly as before.
    match sugar_lift_rpc_client::invoke_lift(root, &source_paths) {
        Ok(doc) => {
            // Surface kit diagnostics (read/parse failures, lift gaps) on the
            // report's parse_errors / warnings, mirroring the old static path.
            if let Some(diags) = doc.get("diagnostics").and_then(|d| d.as_array()) {
                for d in diags {
                    let path = match d.get("path").and_then(|v| v.as_str()) {
                        Some(path) => path.to_string(),
                        None => {
                            report.parse_errors.push((
                                String::new(),
                                format!("contracts kit diagnostic missing string path: {d}"),
                            ));
                            continue;
                        }
                    };
                    let reason = match d.get("reason").and_then(|v| v.as_str()) {
                        Some(reason) => reason.to_string(),
                        None => {
                            report.parse_errors.push((
                                path,
                                format!("contracts kit diagnostic missing string reason: {d}"),
                            ));
                            continue;
                        }
                    };
                    if reason.starts_with("read:") || reason.starts_with("parse:") {
                        report.parse_errors.push((path, reason));
                    } else {
                        let item_name = match d.get("item").and_then(|v| v.as_str()) {
                            Some(item_name) => item_name.to_string(),
                            None => String::new(),
                        };
                        contracts_warnings.push(AdapterWarning {
                            adapter: "contracts",
                            source_path: path,
                            item_name,
                            reason,
                        });
                    }
                }
            }
            // Deserialize the ir-document's `ir` array into typed decls.
            // Render the `ir` array back to a JSON string for the public
            // `parse_document` entry point (its inverse, `marshal_declarations`,
            // also produces a string — this is the enforced round-trip pair).
            let ir_str = match doc.get("ir") {
                Some(ir) => ir.to_string(),
                None => "[]".to_string(),
            };
            match sugar_ir_symbolic::parse::parse_document(&ir_str) {
                Ok(decls) => report.decls.extend(decls),
                Err(e) => report
                    .parse_errors
                    .push((String::new(), format!("ir-document parse: {e}"))),
            }
        }
        Err(e) => {
            // A spawn/protocol failure is surfaced loudly, not silently
            // swallowed: record it so callers see the lifter is unreachable.
            report
                .parse_errors
                .push((String::new(), format!("contracts kit rpc: {e}")));
        }
    }

    let contracts_lifted = report.decls.len();
    report.adapter_reports.push(AdapterReport {
        adapter: "contracts",
        // `seen` and `lifted` collapse to the lifted count: the kit owns the
        // per-function seen/skip bookkeeping now and reports gaps as
        // diagnostics; the substrate counts what it received.
        seen: contracts_lifted,
        lifted: contracts_lifted,
        warnings: contracts_warnings,
    });

    // Re-parse files locally (syn) ONLY for call-edge extraction, which
    // needs the `syn::File` AST. Contract lifting itself is done (over RPC).
    let mut parsed_files: Vec<(String, syn::File)> = Vec::new();
    for (rel_posix, abs_path) in &rs_files {
        let Ok(bytes) = std::fs::read(abs_path) else {
            continue;
        };
        let Ok(src) = std::str::from_utf8(&bytes) else {
            continue;
        };
        if let Ok(file) = syn::parse_file(src) {
            parsed_files.push((rel_posix.clone(), file));
        }
    }

    // --- Second pass: call-edge extraction (spec #114 §1 R1) ----------------
    //
    // Build a signer-independent name → contractCid map from all lifted decls.
    // This covers the full compilation unit; cross-crate callees won't appear
    // here and will produce targetContractCid: null edges.
    let contract_cid_map: BTreeMap<String, String> = {
        let mut map = BTreeMap::new();
        for d in &report.decls {
            // Compute the signer-independent content CID using a minimal
            // MintContractArgs (only the content-bearing fields matter;
            // signer_seed, produced_at, etc. do not affect the CID per spec #94).
            let ccid = contract_cid_for_lift_path_prepass(d);
            // If the same name was lifted multiple times (e.g. semantic dedup),
            // use the first; they'll produce the same CID anyway.
            map.entry(d.name.clone()).or_insert(ccid);
        }
        map
    };

    for (path_str, parsed_file) in &parsed_files {
        let edges = extract_call_edges_from_file(parsed_file, path_str, &contract_cid_map);
        report.call_edges.extend(edges);
    }

    report
}

/// Directory names that are never part of a Rust workspace's source tree.
/// Any directory whose name matches one of these is skipped entirely,
/// at any depth, on any host platform.
const IGNORED_DIRS: &[&str] = &[
    "target",
    ".git",
    "node_modules",
    "__pycache__",
    ".DS_Store",
    ".idea",
    ".vscode",
];

/// Normalize `path` to a canonical, relative POSIX path rooted at `root`.
///
/// Rules (per spec #120 Locus, "File field semantics"):
/// - The result is relative to `root` (no leading `/`, no drive letters).
/// - Separators are forward slashes only.
/// - Any leading `./` is stripped.
/// - Paths that escape `root` (via `..`) are rejected; `None` is returned.
fn to_relative_posix(root: &Path, path: &Path) -> Option<String> {
    // Use `strip_prefix` to get a path relative to root.  Both `root` and
    // `path` come from walkdir which emits descendants of root, so
    // `strip_prefix` will succeed unless something unusual happened.
    let rel = match path.strip_prefix(root) {
        Ok(rel) => rel,
        Err(_) => return None,
    };
    // Convert separators to forward slashes (defensive on Windows too).
    let posix = rel
        .components()
        .map(|c| c.as_os_str().to_string_lossy().into_owned())
        .collect::<Vec<_>>()
        .join("/");
    // Reject empty (root itself) or any escaped path.
    if posix.is_empty() || posix.starts_with("..") {
        return None;
    }
    Some(posix)
}

/// Walk `root` for `.rs` source files, applying:
///  - Ignore-list filtering (build artifacts, VCS dirs, IDE noise).
///  - Deterministic lexicographic sort by relative POSIX path (byte order).
///
/// Returns a list of `(relative_posix_path, absolute_pathbuf)` pairs sorted
/// so that identical source trees produce identical output regardless of
/// host-filesystem readdir ordering (macOS APFS vs Linux ext4).
pub fn enumerate_rs_files(root: &Path) -> Vec<(String, PathBuf)> {
    let mut out: Vec<(String, PathBuf)> = Vec::new();
    if !root.exists() {
        return out;
    }
    for entry in walkdir::WalkDir::new(root)
        .follow_links(false)
        .into_iter()
        .filter_entry(|e| {
            // Skip ignored directories at any depth.
            let n = e.file_name().to_string_lossy();
            !IGNORED_DIRS.iter().any(|&ig| n == ig)
        })
    {
        let entry = match entry {
            Ok(entry) => entry,
            Err(err) => panic!(
                "failed to enumerate Rust source path under `{}`: {err}",
                root.display()
            ),
        };
        if entry.file_type().is_file() {
            if let Some(ext) = entry.path().extension() {
                if ext == "rs" {
                    if let Some(rel) = to_relative_posix(root, entry.path()) {
                        out.push((rel, entry.path().to_path_buf()));
                    }
                }
            }
        }
    }
    // Sort lexicographically by the relative POSIX path (raw byte order,
    // locale-independent) so walk order is deterministic across platforms.
    out.sort_by(|a, b| a.0.cmp(&b.0));
    out
}

#[derive(Debug)]
pub struct MintOutput {
    pub bytes: Vec<u8>,
    pub cid: String,
    /// Signer-independent trust anchor per spec #94.
    /// contractSetCid = blake3-512(JCS(<sorted contractCids>))
    /// where contractCids are content-only hashes:
    ///   contractCid = blake3-512(JCS({name, outBinding, pre?, post?, inv?}))
    pub contract_set_cid: String,
    pub member_count: usize,
    /// Map from contract name to its minted memento CID. Names that
    /// collide on identical canonical IR (semantic dedup) collapse to
    /// one entry; names that collide on different IR error out.
    pub contract_cids: BTreeMap<String, String>,
    pub deduplicated: usize,
}

#[derive(Debug, thiserror::Error)]
pub enum LiftMintError {
    #[error("mint_contract: {0}")]
    Mint(String),
    #[error("name collision on different IR: contract `{0}` lifted twice with different bodies")]
    NameCollisionDifferentIr(String),
    #[error("{0}")]
    InvalidPanicLoci(String),
}

/// Coalesce decls that share a name into one. A producer callsite asserted
/// about in multiple places (e.g. a let-bound `.expect()` used in two
/// `assert!`s) is lifted as several decls with the same name but different
/// invariants. The honest single memento for that callsite carries the
/// CONJUNCTION of every fact asserted about it. This is computation over the
/// lifted data — the substrate's job, post-RPC — not the language kit's.
///
/// Exact-duplicate operands collapse (`a ∧ a ≡ a`). A contradiction
/// (`a ∧ ¬a`) is NOT masked here: it rides into the contract as an
/// unsatisfiable invariant and surfaces at prove/verify. That diagnostic is
/// the point of the system, caught at the proving layer — not papered over by
/// a naming-time error that also false-positived on compatible facts.
fn coalesce_decls_by_name(decls: &[ContractDecl]) -> (Vec<ContractDecl>, usize) {
    let mut order: Vec<String> = Vec::new();
    let mut grouped: BTreeMap<String, ContractDecl> = BTreeMap::new();
    // A same-name decl carrying IDENTICAL facts is a true duplicate (no new
    // information) and counts toward the dedup receipt. A same-name decl with
    // DISTINCT facts is conjoined, not deduplicated — it adds a fact (possibly
    // a contradictory one, which the solver will catch).
    let mut deduplicated = 0usize;
    for d in decls {
        if let Some(acc) = grouped.get_mut(&d.name) {
            let identical = format!("{:?}", acc.pre) == format!("{:?}", d.pre)
                && format!("{:?}", acc.post) == format!("{:?}", d.post)
                && format!("{:?}", acc.inv) == format!("{:?}", d.inv);
            merge_panic_loci(&mut acc.panic_loci, &d.panic_loci);
            if identical {
                deduplicated += 1;
            } else {
                acc.pre = conjoin_formula(acc.pre.take(), d.pre.clone());
                acc.post = conjoin_formula(acc.post.take(), d.post.clone());
                acc.inv = conjoin_formula(acc.inv.take(), d.inv.clone());
            }
        } else {
            order.push(d.name.clone());
            grouped.insert(d.name.clone(), d.clone());
        }
    }
    let out = order
        .into_iter()
        .filter_map(|name| grouped.remove(&name))
        .collect();
    (out, deduplicated)
}

fn merge_panic_loci(acc: &mut Vec<Arc<Value>>, incoming: &[Arc<Value>]) {
    for locus in incoming {
        // Full canonical-entry equality keeps this metadata lossless. Do not
        // collapse by projected file/line: col, callee, and argTerm matter.
        let key = encode_jcs(locus.as_ref());
        if !acc
            .iter()
            .any(|existing| encode_jcs(existing.as_ref()) == key)
        {
            acc.push(locus.clone());
        }
    }
}

fn validate_panic_loci(panic_loci: &[Arc<Value>]) -> Result<(), LiftMintError> {
    for (idx, locus) in panic_loci.iter().enumerate() {
        if !matches!(locus.as_ref(), Value::Object(_)) {
            return Err(LiftMintError::InvalidPanicLoci(format!(
                "panic_loci[{idx}] must be an object, got {}",
                value_type_name(locus.as_ref())
            )));
        }
    }
    Ok(())
}

fn normalized_panic_loci(panic_loci: &[Arc<Value>]) -> Vec<Arc<Value>> {
    let mut keyed: Vec<(String, Arc<Value>)> = panic_loci
        .iter()
        .map(|locus| (encode_jcs(locus.as_ref()), locus.clone()))
        .collect();
    keyed.sort_by(|a, b| a.0.cmp(&b.0));
    keyed.into_iter().map(|(_, locus)| locus).collect()
}

fn value_type_name(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "bool",
        Value::Integer(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}

fn contract_cid_for_lift_path_prepass(d: &ContractDecl) -> String {
    let args = MintContractArgs {
        evidence_term: None,
        formals: Vec::new(),
        emit_empty_formals: false,
        formal_sorts: Vec::new(),
        library: None,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: normalized_panic_loci(&d.panic_loci),
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        contract_name: d.name.clone(),
        pre: d.pre.as_deref().map(formula_to_value),
        post: d.post.as_deref().map(formula_to_value),
        inv: d.inv.as_deref().map(formula_to_value),
        out_binding: d.out_binding.clone(),
        produced_by: "sugar-lift".into(),
        produced_at: "2026-01-01T00:00:00.000Z".into(),
        input_cids: vec![],
        authoring: Authoring::Lift {
            lifter: "sugar-lift".into(),
            evidence: String::new(),
            source_cid: None,
        },
        signer_seed: [0u8; 32],
    };
    compute_contract_cid(&args)
}

/// Conjoin two optional formulas into one `and` connective, flattening nested
/// `and`s and dropping exact-duplicate operands (compared by canonical Debug
/// form, since `Formula` has no `PartialEq`). Distinct operands — including a
/// fact and its negation — are all preserved for the prover.
fn conjoin_formula(a: Option<Rc<Formula>>, b: Option<Rc<Formula>>) -> Option<Rc<Formula>> {
    let (a, b) = match (a, b) {
        (None, None) => return None,
        (Some(x), None) | (None, Some(x)) => return Some(x),
        (Some(x), Some(y)) => (x, y),
    };
    let mut operands: Vec<Rc<Formula>> = Vec::new();
    for f in [a, b] {
        match &*f {
            Formula::Connective {
                kind,
                operands: inner,
            } if kind == "and" => {
                for op in inner {
                    push_unique_operand(&mut operands, op.clone());
                }
            }
            _ => push_unique_operand(&mut operands, f.clone()),
        }
    }
    match operands.len() {
        0 => None,
        1 => operands.into_iter().next(),
        _ => Some(Rc::new(Formula::Connective {
            kind: "and".to_string(),
            operands,
        })),
    }
}

fn push_unique_operand(operands: &mut Vec<Rc<Formula>>, candidate: Rc<Formula>) {
    let key = format!("{candidate:?}");
    if !operands
        .iter()
        .any(|existing| format!("{existing:?}") == key)
    {
        operands.push(candidate);
    }
}

fn register_contract_body_graph(
    proof_graph: &mut ProofGraph,
    pre: Option<&Arc<Value>>,
    post: Option<&Arc<Value>>,
    inv: Option<&Arc<Value>>,
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

/// Mint each lifted ContractDecl as a signed memento and bundle into a
/// single `.proof` catalog. CONTENT-ADDRESSED DEDUP: two decls whose
/// canonical IR encodes to the same byte string mint to the same CID and
/// collapse to one member. Decls that share a NAME are coalesced first
/// (`coalesce_decls_by_name`) so every fact about a producer callsite lives in
/// one memento; the residual same-name guard below is then a defensive
/// tripwire that should never fire.
pub fn mint_proof(decls: &[ContractDecl], opts: &LiftOptions) -> Result<MintOutput, LiftMintError> {
    let mut graph = ProofGraph::new();
    let mut emitted_member_cids: BTreeSet<String> = BTreeSet::new();
    let mut contract_cids: BTreeMap<String, String> = BTreeMap::new();
    // Signer-independent content CIDs for contractSetCid computation (spec #94).
    let mut content_cids: Vec<String> = Vec::new();
    // Coalesce same-named decls (computation over the lifted data) before
    // minting, so each producer callsite yields one memento carrying the
    // conjunction of every fact asserted about it. The coalesce reports the
    // true-duplicate count (identical facts under one name); the mint loop
    // below adds content-CID collapses (identical canonical bytes under
    // different names).
    let (coalesced, mut deduplicated) = coalesce_decls_by_name(decls);

    for d in &coalesced {
        validate_panic_loci(&d.panic_loci)?;
        let panic_loci = normalized_panic_loci(&d.panic_loci);
        let args = MintContractArgs {
            evidence_term: None,
            formals: Vec::new(),
            emit_empty_formals: false,
            formal_sorts: Vec::new(),
            library: None,
            body_discharge_eligible: true,
            body_discharge_refusal_reason: None,
            panic_loci,
            class_shapes: Vec::new(),
            source_warrants: Vec::new(),
            contract_name: d.name.clone(),
            pre: d.pre.as_deref().map(formula_to_value),
            post: d.post.as_deref().map(formula_to_value),
            inv: d.inv.as_deref().map(formula_to_value),
            out_binding: d.out_binding.clone(),
            produced_by: opts.produced_by.clone(),
            produced_at: opts.produced_at.clone(),
            input_cids: vec![],
            authoring: Authoring::Lift {
                lifter: opts.lifter.clone(),
                evidence: format!("lifted from `{}` annotations", d.name),
                source_cid: None,
            },
            signer_seed: opts.signer_seed,
        };
        // Compute signer-independent content CID BEFORE minting (spec #94).
        let ccid = compute_contract_cid(&args);
        let contract_body = register_contract_body_graph(
            &mut graph,
            args.pre.as_ref(),
            args.post.as_ref(),
            args.inv.as_ref(),
        )
        .map_err(|e| LiftMintError::Mint(format!("contract `{}`: {e}", args.contract_name)))?;
        let body_cid = contract_body.cid().as_str().to_string();
        let m = mint_contract_with_body_cid(&args, Some(&body_cid))
            .map_err(|e| LiftMintError::Mint(e.to_string()))?;

        if let Some(prev_cid) = contract_cids.get(&d.name) {
            if prev_cid == &m.cid {
                // Same name, identical IR: semantic dedup.
                deduplicated += 1;
                continue;
            } else {
                return Err(LiftMintError::NameCollisionDifferentIr(d.name.clone()));
            }
        }

        content_cids.push(ccid);
        contract_cids.insert(d.name.clone(), m.cid.clone());
        // If the CID itself already exists (different name, same IR),
        // members map collapses on insert; count as dedup.
        if emitted_member_cids.contains(&m.cid) {
            deduplicated += 1;
        } else {
            let memento = ClaimContractMemento::new(m.canonical_bytes);
            assert_eq!(
                memento.cid().as_str(),
                m.cid,
                "mint_contract returned a contract CID that disagrees with ClaimContractMemento"
            );
            emitted_member_cids.insert(memento.cid().as_str().to_string());
            graph.push_claim_contract(memento);
        }
    }

    // Compute contractSetCid per spec #94 §1.
    let contract_set_cid = compute_contract_set_cid(content_cids);

    let signer_pubkey = ed25519_pubkey_string(&opts.signer_seed);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let proof_input = ProofEnvelopeInput {
        name: opts.catalog_name.clone(),
        version: opts.catalog_version.clone(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid,
        signer_seed: opts.signer_seed,
        declared_at: opts.produced_at.clone(),
    };
    let built = build_proof_envelope(&proof_input);

    Ok(MintOutput {
        bytes: built.bytes,
        cid: built.cid,
        contract_set_cid,
        member_count: emitted_member_cids.len(),
        contract_cids,
        deduplicated,
    })
}

/// Convenience: walk -> lift -> mint -> write `<out_dir>/<cid>.proof`.
pub fn lift_and_mint(
    workspace_root: &Path,
    out_dir: &Path,
    opts: &LiftOptions,
) -> Result<(LiftReport, MintOutput, PathBuf), String> {
    let report = lift_path(workspace_root);
    if report.decls.is_empty() {
        return Err("no liftable contracts found in workspace".into());
    }
    let minted = mint_proof(&report.decls, opts).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(out_dir).map_err(|e| format!("create_dir_all: {e}"))?;
    let path = out_dir.join(proof_filename(&minted.cid));
    std::fs::write(&path, &minted.bytes).map_err(|e| format!("write: {e}"))?;
    Ok((report, minted, path))
}

// ---------------------------------------------------------------------------
// CLI shared between the two binaries.
// ---------------------------------------------------------------------------

#[derive(Debug, Default)]
pub struct CliFlags {
    pub workspace: Option<PathBuf>,
    pub target_dir: Option<PathBuf>,
    pub quiet: bool,
    pub rpc: bool,
}

pub fn parse_cli_flags(args: impl IntoIterator<Item = String>) -> CliFlags {
    let mut flags = CliFlags::default();
    let mut iter = args.into_iter();
    while let Some(a) = iter.next() {
        match a.as_str() {
            "--workspace" | "-w" => {
                flags.workspace = iter.next().map(PathBuf::from);
            }
            "--target-dir" | "-o" => {
                flags.target_dir = iter.next().map(PathBuf::from);
            }
            "--quiet" | "-q" => flags.quiet = true,
            "--rpc" => flags.rpc = true,
            "-h" | "--help" => {
                print_help();
                std::process::exit(0);
            }
            _ => {
                // Cargo passes the subcommand name as argv[1] when
                // invoked as `cargo sugar-lift ...`. Strip it.
                if a == "sugar-lift" {
                    continue;
                }
                eprintln!("sugar-lift: unrecognized argument: {a}");
                eprintln!("sugar-lift: try --help");
                std::process::exit(2);
            }
        }
    }
    flags
}

fn print_help() {
    println!(
        "sugar-lift: promote existing Rust annotations to signed contracts.\n\n\
         USAGE:\n  \
           cargo sugar-lift [--workspace <dir>] [--target-dir <dir>] [--quiet]\n  \
           sugar-lift     [--workspace <dir>] [--target-dir <dir>] [--quiet]\n\n\
         FLAGS:\n  \
           --workspace <dir>   Workspace root to walk. Default: current directory.\n  \
           --target-dir <dir>  Output directory. Default: <workspace>/target/release.\n  \
           --quiet             Suppress per-adapter summary lines.\n  \
           --rpc               Speak JSON-RPC over stdio (plugin mode).\n  \
           --help              Show this help.\n\n\
         POSITIONING:\n  \
           Sugar does NOT compete with proptest, contracts, kani, prusti,\n  \
           hypothesis-py, deal-py, bean-validation-java, zod-ts. It sits\n  \
           BENEATH them. We promote what you already have to content-addressed\n  \
           signed contracts. A contract only enters the substrate by being\n  \
           lifted from native source, never via a bespoke authoring macro."
    );
}

/// JSON-RPC plugin mode. Speaks NDJSON over stdio.
fn run_rpc_mode() -> i32 {
    use std::io::{BufRead, Write};
    let stdin = std::io::stdin();
    let mut stdout = std::io::stdout();
    'requests: for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => continue,
        };
        let req: serde_json::Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(e) => {
                let resp = serde_json::json!({"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":format!("parse error: {e}")}});
                let _ = writeln!(stdout, "{resp}");
                continue;
            }
        };
        let id = match req.get("id") {
            Some(id) => id.clone(),
            None => serde_json::Value::Null,
        };
        let method = match req.get("method").and_then(|v| v.as_str()) {
            Some(method) => method,
            None => {
                let resp = serde_json::json!({"jsonrpc":"2.0","id":id,"error":{"code":-32600,"message":"invalid request: missing method"}});
                let _ = writeln!(stdout, "{resp}");
                continue;
            }
        };
        match method {
            "initialize" => {
                // C1-C8 lift-plugin-protocol conformance: initialize MUST carry a
                // string `protocol_version` (C1) and `capabilities.authoring_surfaces`
                // as a non-empty array (C2/C4). The rust kit serves the `rust` surface.
                let resp = serde_json::json!({"jsonrpc":"2.0","id":id,"result":{"name":"sugar-lift","version":"1.0","protocol_version":"pep/1.7.0","capabilities":{"authoring_surfaces":["rust"],"ir_version":"v1.1.0"}}});
                let _ = writeln!(stdout, "{resp}");
            }
            KIT_DECLARATION_RPC_METHOD => {
                let resp = serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": kit_declaration_result(),
                });
                let _ = writeln!(stdout, "{resp}");
            }
            "lift" => {
                let params = req
                    .get("params")
                    .cloned()
                    .unwrap_or_else(|| serde_json::json!({}));
                // workspace_root: prefer RPC param so the cmd_mint
                // lift-plugin protocol routes correctly (params are
                // authoritative per pep/1.7.0); fall back to CWD for
                // direct CLI use.
                let workspace = params
                    .get("workspace_root")
                    .and_then(|v| v.as_str())
                    .map(PathBuf::from)
                    .unwrap_or_else(|| {
                        std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
                    });
                // options.emit selects the response shape. Default
                // "proof-envelope" preserves backward compat with the
                // self-minted path. "ir-document" emits raw contract
                // mementos so this plugin composes with sibling plugins
                // (walk_rpc for sugar/refuse) when cmd_mint runs N
                // plugins from a `[[plugins]]` config and merges their
                // ir-documents into one envelope.
                let emit = params
                    .get("options")
                    .and_then(|o| o.get("emit"))
                    .and_then(|v| v.as_str());
                let emit = match emit {
                    Some(emit) => emit.to_string(),
                    None => "proof-envelope".to_string(),
                };
                let opts = LiftOptions::default();
                if emit == "ir-document" {
                    let report = lift_path(&workspace);
                    // Content-addressed names (CID suffix) make
                    // duplicates safe — same name = same canonical IR =
                    // same minted memento. Dedup here so downstream
                    // consumers (cmd_mint's envelope minter) see a
                    // collision-free ir-document; the substrate's
                    // mint_proof primitive does the same thing one
                    // layer down, we surface it at the IR layer for
                    // multi-plugin merge correctness.
                    let mut seen: std::collections::HashSet<String> =
                        std::collections::HashSet::new();
                    let mut ir: Vec<serde_json::Value> = Vec::new();
                    for decl in &report.decls {
                        let entry = contract_decl_to_memento(decl);
                        let name = match entry.get("name").and_then(|v| v.as_str()) {
                            Some(name) => name.to_string(),
                            None => {
                                let resp = serde_json::json!({"jsonrpc":"2.0","id":id,"error":{"code":-32603,"message":"lift failed: contract memento missing name"}});
                                let _ = writeln!(stdout, "{resp}");
                                continue 'requests;
                            }
                        };
                        if seen.insert(name) {
                            ir.push(entry);
                        }
                    }
                    let diagnostics: Vec<serde_json::Value> = report
                        .parse_errors
                        .iter()
                        .map(|(path, err)| {
                            serde_json::json!({
                                "severity": "warning",
                                "message": format!("parse {path}: {err}"),
                            })
                        })
                        .collect();
                    let resp = serde_json::json!({
                        "jsonrpc": "2.0",
                        "id": id,
                        "result": {
                            "kind": "ir-document",
                            "ir": ir,
                            "diagnostics": diagnostics,
                        }
                    });
                    let _ = writeln!(stdout, "{resp}");
                } else {
                    let out_dir = workspace.join("target").join("release");
                    match lift_and_mint(&workspace, &out_dir, &opts) {
                        Ok((_report, minted, path)) => {
                            let bytes = match std::fs::read(&path) {
                                Ok(bytes) => bytes,
                                Err(e) => {
                                    let resp = serde_json::json!({"jsonrpc":"2.0","id":id,"error":{"code":-32603,"message":format!("lift failed: read minted proof `{}`: {e}", path.display())}});
                                    let _ = writeln!(stdout, "{resp}");
                                    continue;
                                }
                            };
                            let b64 = base64::engine::general_purpose::STANDARD.encode(&bytes);
                            let resp = serde_json::json!({"jsonrpc":"2.0","id":id,"result":{"kind":"proof-envelope","filename_cid":minted.cid,"contract_set_cid":minted.contract_set_cid,"bytes_base64":b64}});
                            let _ = writeln!(stdout, "{resp}");
                        }
                        Err(e) => {
                            let resp = serde_json::json!({"jsonrpc":"2.0","id":id,"error":{"code":-32603,"message":format!("lift failed: {e}")}});
                            let _ = writeln!(stdout, "{resp}");
                        }
                    }
                }
            }
            "shutdown" => {
                let resp = serde_json::json!({"jsonrpc":"2.0","id":id,"result":null});
                let _ = writeln!(stdout, "{resp}");
                return 0;
            }
            _ => {
                let resp = serde_json::json!({"jsonrpc":"2.0","id":id,"error":{"code":-32601,"message":format!("unknown method: {method}")}});
                let _ = writeln!(stdout, "{resp}");
            }
        }
    }
    0
}

fn kit_declaration_result() -> serde_json::Value {
    serde_json::json!({
        "kit": {
            "id": "sugar-lift",
            "language": "rust",
            "version": env!("CARGO_PKG_VERSION")
        },
        "rpc": {
            "methods": [
                {"name": "initialize", "required": true},
                {"name": "lift", "required": true},
                {"name": "shutdown", "required": true},
                {"name": KIT_DECLARATION_RPC_METHOD, "required": false}
            ]
        },
        "proofResolution": {
            "strategy": "cargo"
        },
        "residueCategories": []
    })
}

/// Serialize a `ContractDecl` as a `kind: "contract"` JSON memento in
/// the canonical-IR shape `cmd_mint`'s ir-document consumer expects.
/// The contract's `name` is content-addressed by appending the
/// formula-set CID — byte-identical formulas at the same name collapse
/// safely; different formulas survive as distinct entries. This is the
/// same dedup primitive `mint_proof` already applies internally; we
/// surface it at the IR layer so multi-plugin merges in `cmd_mint`
/// remain content-honest before envelope minting.
fn contract_decl_to_memento(decl: &ContractDecl) -> serde_json::Value {
    use sugar_canonicalizer::encode_jcs;
    fn formula_pair(f: Option<&sugar_ir_symbolic::Formula>) -> (Option<serde_json::Value>, String) {
        match f {
            Some(formula) => {
                let cv = formula_to_value(formula);
                let jcs = encode_jcs(&cv);
                let cid = blake3_512_of(jcs.as_bytes());
                let value = parse_canonical_json(&jcs, "formula");
                (Some(value), cid)
            }
            None => (None, String::new()),
        }
    }
    let (inv_value, inv_cid) = formula_pair(decl.inv.as_deref());
    let (pre_value, pre_cid) = formula_pair(decl.pre.as_deref());
    let (post_value, post_cid) = formula_pair(decl.post.as_deref());
    let content_cid = blake3_512_of(format!("{inv_cid}|{pre_cid}|{post_cid}").as_bytes());
    // The `#<content_cid>` suffix keeps two contracts that share a base name but
    // carry DIFFERENT formulas as distinct entries (content-honesty / dedup). That
    // is correct for location-keyed names (`callee@file:line:col`), where each
    // source site is its own claim. It is WRONG for `#euf#` names, which are
    // semantic call-identities (`callee#euf#...(argsig)`): two claims about the
    // SAME call (a vendor's `==5` and a consumer's `==6`) MUST share a name so the
    // verifier conjoins their invs and refuses the contradiction. So an `#euf#`
    // name carries the value in its `inv`, never in the name -- the substrate-wide
    // convention that makes behavioral inheritance work (mirrors the Python lifter).
    let name = if decl.name.contains("#euf#") {
        decl.name.clone()
    } else {
        format!("{}#{}", decl.name, content_cid)
    };
    let mut entry = serde_json::json!({
        "kind": "contract",
        "name": name,
        "outBinding": decl.out_binding,
    });
    if let Some(v) = inv_value {
        entry["inv"] = v;
    }
    if let Some(v) = pre_value {
        entry["pre"] = v;
    }
    if let Some(v) = post_value {
        entry["post"] = v;
    }
    if !decl.panic_loci.is_empty() {
        let panic_loci: Vec<serde_json::Value> = normalized_panic_loci(&decl.panic_loci)
            .into_iter()
            .map(|locus| {
                let jcs = encode_jcs(locus.as_ref());
                parse_canonical_json(&jcs, "panic_loci")
            })
            .collect();
        entry["panicLoci"] = serde_json::Value::Array(panic_loci);
    }
    entry
}

fn parse_canonical_json(jcs: &str, label: &str) -> serde_json::Value {
    match serde_json::from_str(jcs) {
        Ok(value) => value,
        Err(e) => panic!("canonical {label} JSON failed to parse after JCS encoding: {e}"),
    }
}

/// Entry point shared by both bin targets. Returns a process exit code.
pub fn run_cli(flags: CliFlags) -> i32 {
    if flags.rpc {
        return run_rpc_mode();
    }
    let workspace = flags.workspace.unwrap_or_else(|| PathBuf::from("."));
    let out_dir = flags
        .target_dir
        .unwrap_or_else(|| workspace.join("target").join("release"));

    let opts = LiftOptions::default();
    match lift_and_mint(&workspace, &out_dir, &opts) {
        Ok((report, minted, path)) => {
            if !flags.quiet {
                println!("sugar-lift: scanned {} .rs files", report.files_scanned);
                for ar in &report.adapter_reports {
                    println!(
                        "  adapter `{}`: seen {}, lifted {}, skipped {}",
                        ar.adapter,
                        ar.seen,
                        ar.lifted,
                        ar.warnings.len()
                    );
                }
                if minted.deduplicated > 0 {
                    println!(
                        "  dedup: {} contracts collapsed by content address",
                        minted.deduplicated
                    );
                }
                println!(
                    "sugar-lift: wrote {} ({} members)",
                    path.display(),
                    minted.member_count
                );
                println!("sugar-lift: cid = {}", minted.cid);
            } else {
                println!("{}", minted.cid);
            }
            0
        }
        Err(e) => {
            eprintln!("sugar-lift: {e}");
            1
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::sync::Arc;

    use sugar_canonicalizer::Value;
    use sugar_proof_envelope::ProofGraph;

    fn tempdir() -> tempdir_compat::TempDir {
        tempdir_compat::TempDir::new("sugar-lift-test").unwrap()
    }

    /// Smallest possible "test workspace": one .rs file with two
    /// contracts-annotated functions, plus a duplicate of one of them in
    /// a second file (dedup case).
    fn write_fixture(dir: &Path) {
        let a = dir.join("a.rs");
        let mut f = std::fs::File::create(&a).unwrap();
        writeln!(
            f,
            r#"
#[requires(x > 0)]
#[ensures(ret >= 0)]
fn answer_is_42(x: i64) -> i64 {{ x }}

#[requires(x > 0)]
#[ensures(ret >= 0)]
fn sqrt(x: i64) -> i64 {{ x }}
"#
        )
        .unwrap();
        let b = dir.join("b.rs");
        let mut f = std::fs::File::create(&b).unwrap();
        // Same contract, expressed identically: should dedup.
        writeln!(
            f,
            r#"
#[requires(x > 0)]
#[ensures(ret >= 0)]
fn answer_is_42(x: i64) -> i64 {{ x }}
"#
        )
        .unwrap();
    }

    #[test]
    fn end_to_end_walk_lift_mint_dedup() {
        let td = tempdir();
        write_fixture(td.path());
        let opts = LiftOptions::default();
        let (report, minted, path) =
            lift_and_mint(td.path(), td.path(), &opts).expect("lift_and_mint");
        // 2 `answer_is_42` fns across the two files + 1 `sqrt` fn = 3 seen.
        let contracts = report
            .adapter_reports
            .iter()
            .find(|a| a.adapter == "contracts")
            .unwrap();
        assert_eq!(contracts.seen, 3);
        assert_eq!(contracts.lifted, 3);
        // Dedup: two `answer_is_42` collapse to one minted member; sqrt
        // adds one more = 2 members.
        assert_eq!(minted.member_count, 2, "expected dedup; got {minted:?}");
        assert!(path.exists());
        assert!(minted.cid.starts_with("blake3-512:"));
    }

    #[test]
    fn cli_flags_parse() {
        let flags = parse_cli_flags(
            [
                "--workspace".into(),
                "/a".into(),
                "--target-dir".into(),
                "/b".into(),
            ]
            .into_iter()
            .collect::<Vec<String>>(),
        );
        assert_eq!(flags.workspace.as_deref(), Some(Path::new("/a")));
        assert_eq!(flags.target_dir.as_deref(), Some(Path::new("/b")));
    }

    #[test]
    fn cargo_subcommand_arg_is_stripped() {
        // When invoked as `cargo sugar-lift --workspace /a`, Cargo
        // calls `cargo-sugar-lift` with argv = ["sugar-lift",
        // "--workspace", "/a"]. parse_cli_flags must skip "sugar-lift".
        let flags = parse_cli_flags(
            ["sugar-lift".into(), "--workspace".into(), "/a".into()]
                .into_iter()
                .collect::<Vec<String>>(),
        );
        assert_eq!(flags.workspace.as_deref(), Some(Path::new("/a")));
    }

    fn sample_contract_decl(name: &str) -> ContractDecl {
        // THE SEVER: this test helper used to call the static
        // the static contracts-adapter lift_file. The lifter is no longer statically
        // linked here (it is an RPC kit), so build the fixture decl from the
        // IR-JSON shape the lifter emits — the SAME `kind:"contract"` shape
        // marshalled across the wire — via the public `parse_document`
        // deserializer (the inverse of `marshal_declarations`). This
        // reproduces what `#[requires(x > 0)]` / `#[ensures(ret >= 0)]`
        // lifts to, with no compile-time dependency on the lifter.
        let doc = format!(
            r#"[{{"kind":"contract","name":{name:?},"outBinding":"out",
                "pre":{{"kind":"forall","name":"x","sort":{{"kind":"primitive","name":"Int"}},
                    "body":{{"kind":"atomic","name":">","args":[
                        {{"kind":"var","name":"x"}},
                        {{"kind":"const","value":0,"sort":{{"kind":"primitive","name":"Int"}}}}]}}}},
                "post":{{"kind":"forall","name":"x","sort":{{"kind":"primitive","name":"Int"}},
                    "body":{{"kind":"atomic","name":">=","args":[
                        {{"kind":"var","name":"ret"}},
                        {{"kind":"const","value":0,"sort":{{"kind":"primitive","name":"Int"}}}}]}}}}}}]"#
        );
        sugar_ir_symbolic::parse::parse_document(&doc)
            .expect("fixture document parses")
            .into_iter()
            .next()
            .expect("fixture yields one contract")
    }

    fn sample_panic_locus_at(line: i64, panic_line: i64) -> Arc<Value> {
        Value::object([
            (
                "argTerm",
                Value::object([
                    ("kind", Value::string("call")),
                    ("callee", Value::string("serde_json::to_string")),
                    (
                        "args",
                        Value::array(vec![Value::object([
                            ("kind", Value::string("var")),
                            ("name", Value::string("v")),
                        ])]),
                    ),
                ]),
            ),
            ("file", Value::string("src/lib.rs")),
            ("line", Value::integer(i128::from(line))),
            ("col", Value::integer(4)),
            ("panicLine", Value::integer(i128::from(panic_line))),
            ("panicCol", Value::integer(9)),
            ("callee", Value::string("method:unwrap")),
        ])
    }

    fn proof_member_headers(minted: &MintOutput) -> Vec<serde_json::Value> {
        let graph = ProofGraph::read(&minted.bytes).expect("decode proof envelope");
        let mut headers: Vec<_> = graph
            .members_view()
            .map(|mv| {
                serde_json::from_slice::<serde_json::Value>(mv.bytes())
                    .expect("member is JSON")
                    .get("header")
                    .expect("layered member header")
                    .clone()
            })
            .collect();
        headers.sort_by(|a, b| proof_member_header_name(a).cmp(proof_member_header_name(b)));
        headers
    }

    fn proof_member_header_name(header: &serde_json::Value) -> &str {
        match header.get("name").and_then(|value| value.as_str()) {
            Some(name) => name,
            None => panic!("proof member header missing string name: {header}"),
        }
    }

    fn only_proof_member_header(minted: &MintOutput) -> serde_json::Value {
        let mut headers = proof_member_headers(minted);
        assert_eq!(headers.len(), 1, "expected one proof member");
        headers.pop().unwrap()
    }

    #[test]
    fn mint_proof_preserves_panic_loci_in_contract_header() {
        let mut decl = sample_contract_decl("panic_loci_fixture");
        let locus = sample_panic_locus_at(12, 13);
        decl.panic_loci = vec![locus.clone()];

        let minted = mint_proof(&[decl], &LiftOptions::default()).expect("mint");
        let header = only_proof_member_header(&minted);

        let panic_loci = header
            .get("panicLoci")
            .and_then(|value| value.as_array())
            .expect("panicLoci header must be present");
        assert_eq!(panic_loci.len(), 1);
        assert_eq!(
            panic_loci[0],
            serde_json::from_str::<serde_json::Value>(&sugar_canonicalizer::encode_jcs(
                locus.as_ref()
            ))
            .expect("canonical locus parses as JSON")
        );
        assert_eq!(panic_loci[0]["callee"], "method:unwrap");
        assert_ne!(
            panic_loci[0]["callee"], "concept:panic-freedom.leaf.unwrap",
            "Rust v1 lift/mint writer must not emit the unwrap leaf concept alias"
        );
    }

    #[test]
    fn mint_proof_rejects_malformed_panic_loci_entries() {
        for (label, locus, expected_type) in [
            ("string", Value::string("not-a-locus-object"), "string"),
            ("number", Value::integer(42), "number"),
            ("array", Value::array(vec![]), "array"),
            ("null", Value::null(), "null"),
        ] {
            let mut decl = sample_contract_decl("malformed_panic_locus");
            decl.panic_loci = vec![locus];

            let err = mint_proof(&[decl], &LiftOptions::default())
                .expect_err("malformed panic_loci must fail closed");
            let err = err.to_string();
            assert!(
                err.contains(&format!(
                    "panic_loci[0] must be an object, got {expected_type}"
                )),
                "{label}: error should name panic_loci path and type, got: {err}"
            );
        }
    }

    #[test]
    fn mint_proof_keeps_absent_empty_and_nonempty_panic_loci_out_of_contract_set_cid() {
        let absent = sample_contract_decl("panic_loci_identity");
        let mut empty = absent.clone();
        empty.panic_loci = Vec::new();
        let mut nonempty = absent.clone();
        nonempty.panic_loci = vec![sample_panic_locus_at(20, 21)];

        let absent_mint = mint_proof(&[absent], &LiftOptions::default()).expect("absent mint");
        let empty_mint = mint_proof(&[empty], &LiftOptions::default()).expect("empty mint");
        let nonempty_mint =
            mint_proof(&[nonempty], &LiftOptions::default()).expect("nonempty mint");

        assert_eq!(
            absent_mint.contract_set_cid, empty_mint.contract_set_cid,
            "absent and explicit-empty panic_loci must be equivalent at the cid layer"
        );
        assert_eq!(
            empty_mint.contract_set_cid, nonempty_mint.contract_set_cid,
            "panic_loci is header provenance, not contract identity"
        );
        assert_eq!(
            absent_mint.cid, empty_mint.cid,
            "explicit empty panic_loci must preserve legacy proof envelope bytes"
        );
        assert_ne!(
            empty_mint.cid, nonempty_mint.cid,
            "nonempty panic_loci must change the proof envelope bytes/CID"
        );
    }

    #[test]
    fn lift_path_panic_loci_prepass_contract_cid_matches_real_minted_header_cid() {
        let mut decl = sample_contract_decl("panic_loci_prepass_equivalence");
        decl.panic_loci = vec![sample_panic_locus_at(22, 23)];

        let prepass_cid = contract_cid_for_lift_path_prepass(&decl);
        let minted = mint_proof(&[decl], &LiftOptions::default()).expect("mint");
        let header = only_proof_member_header(&minted);
        let real_header_cid = header
            .get("cid")
            .and_then(|value| value.as_str())
            .expect("contract header cid");

        assert_eq!(
            prepass_cid, real_header_cid,
            "lift_path CID prepass and real mint header cid must stay equivalent"
        );
    }

    #[test]
    fn mint_proof_normalizes_panic_loci_order_for_deterministic_headers() {
        let first = sample_panic_locus_at(30, 31);
        let second = sample_panic_locus_at(40, 41);
        let mut forward = sample_contract_decl("panic_loci_order");
        forward.panic_loci = vec![first.clone(), second.clone()];
        let mut reverse = sample_contract_decl("panic_loci_order");
        reverse.panic_loci = vec![second, first];

        let forward_mint = mint_proof(&[forward], &LiftOptions::default()).expect("forward mint");
        let reverse_mint = mint_proof(&[reverse], &LiftOptions::default()).expect("reverse mint");

        assert_eq!(
            forward_mint.bytes, reverse_mint.bytes,
            "panic_loci order must not perturb deterministic proof bytes"
        );
    }

    #[test]
    fn mint_proof_coalesces_same_name_panic_loci_without_dropping_provenance() {
        let mut first = sample_contract_decl("panic_loci_coalesce");
        first.panic_loci = vec![sample_panic_locus_at(50, 51)];
        let mut second = sample_contract_decl("panic_loci_coalesce");
        second.panic_loci = vec![sample_panic_locus_at(60, 61)];

        let minted = mint_proof(&[first, second], &LiftOptions::default()).expect("mint");
        let header = only_proof_member_header(&minted);
        let panic_loci = header
            .get("panicLoci")
            .and_then(|value| value.as_array())
            .expect("panicLoci header must be present");

        assert_eq!(
            panic_loci.len(),
            2,
            "coalescing same-name facts must union panic_loci provenance"
        );
    }

    // -----------------------------------------------------------------------
    // Determinism tests (spec #120 §"File field semantics" + §11 manifesto).
    //
    // Two instances of the SAME source tree at DIFFERENT absolute paths MUST
    // produce byte-identical contractSetCid.  This is the empirical gate for
    // cross-platform federated trust: different machines will always have
    // different absolute paths, but the relative POSIX path within the project
    // root is identical.
    // -----------------------------------------------------------------------

    /// Write a richer fixture: two .rs files in a nested sub-directory, a
    /// target/ directory with a dummy file that must NOT be lifted, and a
    /// .DS_Store file that must NOT be lifted.
    fn write_determinism_fixture(dir: &Path) {
        // Create nested source layout.
        let sub = dir.join("src").join("nested");
        std::fs::create_dir_all(&sub).unwrap();

        let mut f = std::fs::File::create(sub.join("alpha.rs")).unwrap();
        writeln!(
            f,
            r#"
#[requires(x > 0)]
#[ensures(ret > 0)]
fn positive(x: i64) -> i64 {{ x }}
"#
        )
        .unwrap();

        let mut f = std::fs::File::create(sub.join("beta.rs")).unwrap();
        writeln!(
            f,
            r#"
#[requires(n >= 0)]
#[ensures(ret >= 0)]
fn nonneg(n: i64) -> i64 {{ n }}
"#
        )
        .unwrap();

        // A top-level file too.
        let mut f = std::fs::File::create(dir.join("lib.rs")).unwrap();
        writeln!(
            f,
            r#"
#[requires(a != 0)]
#[ensures(ret != 0)]
fn nonzero(a: i64) -> i64 {{ a }}
"#
        )
        .unwrap();

        // Build artifact directory: must be filtered.
        let target = dir.join("target").join("release");
        std::fs::create_dir_all(&target).unwrap();
        std::fs::write(target.join("artifact.rs"), b"fn build_artifact() {}").unwrap();

        // macOS noise file: must be filtered.
        std::fs::write(dir.join(".DS_Store"), b"").unwrap();
    }

    /// Empirical cross-machine determinism test.
    ///
    /// Lifts the same fixture from TWO different absolute roots (simulating
    /// two machines with different directory prefixes) and asserts that
    /// `contract_set_cid` and bundle `cid` are byte-identical.
    #[test]
    fn contract_set_cid_is_identical_across_different_absolute_roots() {
        let td1 = tempdir_compat::TempDir::new("sugar-det-machine1").unwrap();
        let td2 = tempdir_compat::TempDir::new("sugar-det-machine2").unwrap();

        write_determinism_fixture(td1.path());
        write_determinism_fixture(td2.path());

        // Sanity: the two roots must NOT be the same directory.
        assert_ne!(
            td1.path(),
            td2.path(),
            "test requires two distinct temp dirs"
        );

        let opts = LiftOptions::default();

        let report1 = lift_path(td1.path());
        let report2 = lift_path(td2.path());

        // Both should have lifted the same number of contracts.
        assert_eq!(
            report1.decls.len(),
            report2.decls.len(),
            "declaration count must match across roots"
        );

        let mint1 = mint_proof(&report1.decls, &opts).expect("mint1");
        let mint2 = mint_proof(&report2.decls, &opts).expect("mint2");

        assert_eq!(
            mint1.contract_set_cid, mint2.contract_set_cid,
            "contractSetCid must be byte-identical across different absolute roots \
             (simulates cross-machine CID stability)"
        );
        assert_eq!(
            mint1.cid, mint2.cid,
            "bundle CID must be byte-identical across different absolute roots"
        );
    }

    /// Assert that target/ and .DS_Store artifacts are NOT in the lifted set.
    #[test]
    fn target_dir_and_ds_store_are_excluded() {
        let td = tempdir_compat::TempDir::new("sugar-det-ignore").unwrap();
        write_determinism_fixture(td.path());

        let report = lift_path(td.path());

        // Only 3 files (lib.rs, alpha.rs, beta.rs) should have been scanned;
        // target/release/artifact.rs and .DS_Store must be excluded.
        assert_eq!(
            report.files_scanned, 3,
            "expected 3 .rs files scanned; got {}. target/ or .DS_Store pollution?",
            report.files_scanned
        );
    }

    /// Assert that file paths embedded in call-edge loci are relative POSIX
    /// paths, not absolute paths.
    #[test]
    fn call_edge_loci_use_relative_posix_paths() {
        let td = tempdir_compat::TempDir::new("sugar-det-locus").unwrap();
        write_determinism_fixture(td.path());

        let report = lift_path(td.path());

        for edge in &report.call_edges {
            let file = &edge.call_site_locus.file;
            assert!(
                !file.starts_with('/'),
                "call-edge locus file must be relative, got absolute: {file}"
            );
            // No Windows drive letters.
            assert!(
                !file.chars().nth(1).map_or(false, |c| c == ':'),
                "call-edge locus file must not contain drive letter: {file}"
            );
            // No backslashes.
            assert!(
                !file.contains('\\'),
                "call-edge locus file must use forward slashes only: {file}"
            );
        }

        // enumerate_rs_files returns (rel_posix, abs): verify the posix strings too.
        let entries = enumerate_rs_files(td.path());
        for (rel, _) in &entries {
            assert!(
                !rel.starts_with('/'),
                "enumerate_rs_files returned absolute path: {rel}"
            );
            assert!(
                !rel.contains('\\'),
                "enumerate_rs_files returned backslash: {rel}"
            );
        }
    }

    /// Assert enumerate_rs_files output is sorted lexicographically.
    #[test]
    fn enumerate_rs_files_is_sorted() {
        let td = tempdir_compat::TempDir::new("sugar-det-sort").unwrap();
        write_determinism_fixture(td.path());

        let entries = enumerate_rs_files(td.path());
        let paths: Vec<&str> = entries.iter().map(|(r, _)| r.as_str()).collect();
        let mut sorted = paths.clone();
        sorted.sort();
        assert_eq!(
            paths, sorted,
            "enumerate_rs_files must return lexicographically sorted paths"
        );
    }
}

#[cfg(test)]
mod tempdir_compat {
    use std::path::{Path, PathBuf};

    pub struct TempDir {
        path: PathBuf,
    }

    impl TempDir {
        pub fn new(prefix: &str) -> std::io::Result<Self> {
            let base = std::env::temp_dir();
            // Use nanos + pid + counter for a non-colliding name.
            use std::sync::atomic::{AtomicU64, Ordering};
            static CTR: AtomicU64 = AtomicU64::new(0);
            let n = CTR.fetch_add(1, Ordering::Relaxed);
            let nanos = match std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH) {
                Ok(duration) => duration.as_nanos(),
                Err(_) => 0,
            };
            let path = base.join(format!("{prefix}-{}-{}-{}", std::process::id(), nanos, n));
            std::fs::create_dir_all(&path)?;
            Ok(Self { path })
        }
        pub fn path(&self) -> &Path {
            &self.path
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.path);
        }
    }
}
