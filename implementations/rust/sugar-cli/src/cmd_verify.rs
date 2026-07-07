// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar verify <kit>`: the keystone GATE verb (PR-9, issue #1405).
//
// This is the real `verify` verb. It is distinct from the old `verify`
// alias (which routed to `cmd_prove`, the six-stage prover / `--kit`
// lift-plugin conformance gate). `verify` runs the *kit-level
// verification flow* end-to-end and emits a verification receipt:
//
//   1. Lift the kit's contract claims. The lifter writes each
//      @sugar/@boundary annotation as a contract memento (referencing
//      its concept) into the kit's `.proof` catalog under `.sugar/`.
//      We load that catalog with `load_all_proofs` and enumerate the
//      contract claims via `enumerate_callsites` (the bridge/callsite
//      enumeration is exactly "function Y claims to satisfy concept X").
//
//   2. For each claim, resolve the target contract (its pre/post),
//      build the weakest-precondition / refinement obligation
//      ("does Y satisfy the contract"), using the same obligation
//      construction the prover uses (`resolve_target` + implication
//      post -> pre, falling back to `instantiate`).
//
//   3. Solver dispatch (resolved question Q-5, #1421). We inspect the
//      obligation's *theory class* with `sugar_verifier::classify`
//      and route to the best-fit solver via a SOLVER-DISPATCH TABLE
//      (`SolverPlan::Dispatch(DispatchConfig)`): obligation class ->
//      ordered solver choice. The backends already exist as crates;
//      this verb wires them, it does not build new solvers. The table
//      is the structure (see [`verify_dispatch_table`]); v1 routes LIA
//      / BV / strings to SMT-LIB (Z3 / cvc5 / bitwuzla), first-order
//      with quantifiers to Vampire, equational theory to Maude,
//      dependent / categorical to Lean, everything else to Z3.
//
//   4. Mint a witness memento citing the discharging solver, and sign
//      it (Ed25519, the existing proof-envelope signing helper). The
//      witness's signature records which solver produced the proof so
//      consumers can trust-discriminate.
//
//   5. Emit a verification receipt: per-claim pass/fail, the obligation
//      class, which solver each used, and the witness CIDs. JSON +
//      human-readable.
//
// SCOPE: This verb is a conductor. catalog lookup, wp/obligation
// construction, the solver-dispatch table, and signing all already
// exist in `sugar-verifier` / `sugar-proof-envelope`. PR-9 wires
// them into one verb; it reimplements none of them.

use std::fmt::Write as _;
use std::path::{Path, PathBuf};

use crate::component_plan::{self, ComponentPlan, ComponentPlanOptions, PlanIntent};
use crate::project_config::read_project_config;
use crate::report_fmt;
use crate::witness_verify;
use clap::Parser;
use owo_colors::OwoColorize;
use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, cid_hex, encode_jcs};
use sugar_ir_compiler::registry::Registry as CompilerRegistry;
use sugar_ir_compiler::CompilerInput;
use sugar_proof_envelope::{ed25519_pubkey_string, ed25519_sign_string};
use sugar_verifier::body_discharge;
use sugar_verifier::solvers::registry;
use sugar_verifier::{
    classify, enumerate_callsites, instantiate, load_all_proofs, resolve_target,
    run_plan_with_compilers, DispatchConfig, FormulaTheory, LegacyZ3Fallback, MementoPool,
    ObligationVerdict, Runner, RunnerConfig, SolverHandle, SolverPlan, SolverSeat, SolversConfig,
    WitnessVerificationOutcome,
};
use tracing::{debug, info};

use crate::cmd_mint;
use crate::{EXIT_OK, EXIT_SOLVER_FAIL, EXIT_USER_ERROR, EXIT_VERIFY_FAIL};

// Default Ed25519 seed used to sign minted verification witnesses when
// no real signer is configured. This is a deterministic *developer*
// seed: a signature under it is an INTEGRITY TAG (it binds the witness
// bytes so tampering is detectable and the witness CID is reproducible),
// NOT an authority attestation (everyone knows this seed, so it asserts
// nothing about *who* produced the proof). Distinct byte from the
// runner's `RUN_SIGNER_SEED` so verify-witness signers are
// distinguishable from run signers.
//
// A real signer is honored when configured (see [`resolve_signer_seed`]):
//   - env `SUGAR_VERIFY_SIGNER_KEY` = hex-encoded 32-byte seed, or
//   - env `SUGAR_VERIFY_SIGNER_KEY_FILE` = path to a file whose first
//     non-whitespace token is the hex-encoded 32-byte seed.
// Only then does the signature carry authority.
const VERIFY_SIGNER_SEED_DEV: [u8; 32] = [0x76; 32];

/// The env var carrying a hex-encoded 32-byte Ed25519 signer seed.
const SIGNER_KEY_ENV: &str = "SUGAR_VERIFY_SIGNER_KEY";
/// The env var carrying a path to a file holding the hex-encoded seed.
const SIGNER_KEY_FILE_ENV: &str = "SUGAR_VERIFY_SIGNER_KEY_FILE";

/// Resolve the Ed25519 signer seed for minted witnesses.
///
/// Precedence:
///   1. `SUGAR_VERIFY_SIGNER_KEY`      — hex(32 bytes) inline,
///   2. `SUGAR_VERIFY_SIGNER_KEY_FILE` — path to a file whose first
///      whitespace-delimited token is hex(32 bytes),
///   3. the dev seed [`VERIFY_SIGNER_SEED_DEV`] (integrity tag only).
///
/// Returns `(seed, is_authoritative)`: `is_authoritative` is true only
/// when an override was supplied, so callers can be honest in output
/// about whether the signature attests authority. A malformed override
/// is an error (fail closed: do not silently fall back to the dev seed
/// when the operator clearly intended a real key).
fn resolve_signer_seed() -> Result<([u8; 32], bool), String> {
    if let Some(hex) = std::env::var_os(SIGNER_KEY_ENV) {
        let hex = hex.to_string_lossy().trim().to_string();
        return decode_seed_hex(&hex).map(|s| (s, true));
    }
    if let Some(path) = std::env::var_os(SIGNER_KEY_FILE_ENV) {
        let path = std::path::PathBuf::from(path);
        let contents = std::fs::read_to_string(&path)
            .map_err(|e| format!("read {SIGNER_KEY_FILE_ENV} `{}`: {e}", path.display()))?;
        let token = contents
            .split_whitespace()
            .next()
            .ok_or_else(|| format!("{SIGNER_KEY_FILE_ENV} `{}` is empty", path.display()))?;
        return decode_seed_hex(token).map(|s| (s, true));
    }
    Ok((VERIFY_SIGNER_SEED_DEV, false))
}

/// Decode a hex-encoded 32-byte Ed25519 seed.
fn decode_seed_hex(hex: &str) -> Result<[u8; 32], String> {
    let hex = hex.strip_prefix("0x").unwrap_or(hex);
    if hex.len() != 64 {
        return Err(format!(
            "signer seed must be 64 hex chars (32 bytes); got {} chars",
            hex.len()
        ));
    }
    let mut seed = [0u8; 32];
    for (i, byte) in seed.iter_mut().enumerate() {
        let s = &hex[i * 2..i * 2 + 2];
        *byte = u8::from_str_radix(s, 16)
            .map_err(|e| format!("signer seed has non-hex at byte {i}: {e}"))?;
    }
    Ok(seed)
}

#[derive(Parser, Debug, Clone)]
pub struct VerifyArgs {
    /// Configured kit alias to verify. Resolves through project/user
    /// `[[kits]]` config to the kit's project root; its `.sugar/`
    /// catalog carries the lifted contract claims. Conflicts with
    /// `--project`. May also be an explicit path when the value contains
    /// a path separator.
    #[arg(conflicts_with = "project")]
    pub kit: Option<String>,

    /// Verify an explicit project root instead of a named kit. Defaults
    /// to the current directory when neither `--kit` positional nor this
    /// is given.
    #[arg(long)]
    pub project: Option<PathBuf>,

    /// Path to z3 binary (default: "z3" on PATH). Used for the SMT-LIB
    /// dispatch-table seat fallback.
    #[arg(long, default_value = "z3")]
    pub z3: String,

    /// Directory to write signed witness mementos into. Defaults to
    /// `<project>/.sugar/witnesses`.
    #[arg(long = "emit-witnesses")]
    pub emit_witnesses: Option<PathBuf>,

    /// Continue after a discovered component crashes, times out, or returns malformed planning RPC.
    #[arg(long = "allow-failed-components")]
    pub allow_failed_components: bool,

    /// Require that a concept has reached the empirically-witnessed
    /// promotion tier. When set, the standard solver-dispatch flow is
    /// bypassed; instead the project's promotion catalog is queried.
    #[arg(long = "require-empirically-witnessed")]
    pub require_empirically_witnessed: Option<String>,

    /// Fixture-state CID for tier queries such as
    /// `--require-empirically-witnessed`.
    #[arg(long = "require-fixture")]
    pub require_fixture: Option<String>,

    /// Consensus policy JSON used to evaluate a required empirical
    /// witness vector (required with `--require-empirically-witnessed`).
    #[arg(long = "consensus-policy", requires = "require_empirically_witnessed")]
    pub consensus_policy: Option<PathBuf>,

    /// Artifact bytes to verify against a package release proof/receipt.
    /// Selects the supply-chain admission gate (binaryCid match).
    #[arg(long, requires = "proof")]
    pub artifact: Option<PathBuf>,

    /// Package release proof/receipt naming the expected binaryCid /
    /// policyCid. Required for the supply-chain admission gate.
    #[arg(long)]
    pub proof: Option<PathBuf>,

    /// Consumer policy proof/receipt used for policy admission checks
    /// (policyCid match).
    #[arg(long, requires = "proof")]
    pub policy: Option<PathBuf>,

    #[command(flatten)]
    pub out: crate::OutputFlags,
}

/// The SOLVER-DISPATCH TABLE: obligation theory class -> solver seat.
///
/// This is the *structure* PR-9 introduces (resolved question Q-5,
/// #1421). It is a `DispatchConfig`, the same type `SolverPlan::Dispatch`
/// consumes, so adding a class -> solver mapping is a one-line edit and
/// the plan executor (`run_plan`) already knows how to route a formula
/// through it via `dispatch_for_formula`.
///
/// v1 routing (each seat is an existing backend crate, never a new
/// solver):
///   - linear-arithmetic / bitvectors / strings -> SMT-LIB (Z3 / cvc5 /
///     bitwuzla): the arithmetic + bitvector + array workhorse.
///   - equational-theory -> Maude (rewriting-logic / desugar-equivalence).
///   - dependent-type / categorical-structure -> Lean (theorem-level).
///   - default (and first-order with quantifiers that the SMT seats
///     punt on) -> Z3, with Vampire as the configured first-order seat
///     when the kit config registers it.
///
/// When the kit's `.sugar/config.toml` already declares a
/// `[solvers.dispatch]` table we honor it (the kit author's table wins);
/// otherwise this default table is used. Either way the routing is a
/// table, not a hardcoded single backend.
pub fn verify_dispatch_table() -> DispatchConfig {
    DispatchConfig {
        equational_theory: Some(SolverSeat::Maude),
        first_order: Some(SolverSeat::Vampire),
        strings: Some(SolverSeat::Cvc5),
        bitvectors: Some(SolverSeat::Bitwuzla),
        linear_arithmetic: Some(SolverSeat::Z3),
        dependent_type: Some(SolverSeat::Lean),
        categorical_structure: Some(SolverSeat::Lean),
        default: Some(SolverSeat::Z3),
    }
}

/// Per-claim verification outcome, the row of the receipt.
struct ClaimResult {
    property_name: String,
    property_cid: String,
    /// The obligation's theory class, as classified for dispatch.
    obligation_class: String,
    /// The solver seat the dispatch table routed this obligation to.
    routed_solver: String,
    /// The solver that actually returned the authoritative verdict.
    discharging_solver: String,
    verdict: ObligationVerdict,
    reason: String,
    /// CID of the signed witness minted for a discharged claim.
    witness_cid: Option<String>,
    /// For a DISCHARGED claim, HOW it was proven: `reflexive` (sound but
    /// shallow: `T == T`, the function returns what it returns) vs
    /// `solver-substantive` (real arithmetic / implication). `None` for a
    /// claim that did not reach the solver (vacuous / hash-tier / not
    /// discharged). Reported separately so a reflexive discharge is never
    /// conflated with a meaningful proof.
    discharge_method: Option<String>,
    /// Body-discharge reducer route, when the claim was reduced through a
    /// callee body before solving. This stays separate from `discharge_method`:
    /// a route can be visible on a violation, while a method is only a proof
    /// classification for discharged obligations.
    body_discharge_tier: Option<String>,
}

/// A direct formula claim from a contract memento.
///
/// Normal `inv` contracts are consistency facts: verify checks that asserted
/// facts can coexist. A contract may opt into validity checking with
/// `invVerification = "obligation"`, in which case `inv` is treated as the
/// obligation itself and dispatched through the solver table.
#[derive(Debug, Clone)]
struct DirectFormulaClaim {
    property_name: String,
    property_cid: String,
    formula: Json,
}

fn callsite_actual_terms(cs: &sugar_verifier::CallSite) -> Vec<Json> {
    if !cs.arg_terms.is_empty() {
        return cs.arg_terms.clone();
    }
    cs.arg_term.iter().cloned().collect()
}

pub fn run(args: VerifyArgs) -> u8 {
    // Early dispatch: the supply-chain admission gate. When any of
    // --artifact / --proof / --policy is given, verify a package release
    // receipt (binaryCid / policyCid match) rather than running the
    // solver-dispatch flow. The logic is owned by cmd_prove (it predates
    // this verb); we reuse it so both verbs expose one behavior.
    if args.artifact.is_some() || args.proof.is_some() || args.policy.is_some() {
        return crate::cmd_prove::run_admission_gate_with(
            &args.artifact,
            &args.proof,
            &args.policy,
            args.out.json,
            args.out.quiet,
        );
    }

    // Resolve the project root: a named kit, an explicit --project, or
    // the current directory.
    let project_root: PathBuf = if let Some(kit) = &args.kit {
        match cmd_mint::resolve_kit(kit) {
            Some((path, _surface, _lang)) => path,
            None => {
                // If the value looks like a path (contains a separator
                // or is `.`/`..`), treat it as an explicit project root
                // rather than a kit name.
                let p = PathBuf::from(kit);
                if kit.contains(std::path::MAIN_SEPARATOR)
                    || kit.starts_with('/')
                    || kit.starts_with('.')
                    || p.is_absolute()
                {
                    p
                } else {
                    let aliases = cmd_mint::configured_kit_alias_names();
                    eprintln!("{}", cmd_mint::format_unknown_kit_error(kit, &aliases));
                    return EXIT_USER_ERROR;
                }
            }
        }
    } else {
        args.project.clone().unwrap_or_else(|| PathBuf::from("."))
    };

    if !project_root.exists() {
        eprintln!(
            "{}: project root not found: {} (run from repo root)",
            "error".red().bold(),
            project_root.display()
        );
        return EXIT_USER_ERROR;
    }

    if use_artifact_project_verify(&args, &project_root) {
        return run_artifact_project_verify(&project_root, &args);
    }

    let quiet = args.out.quiet;
    let json_out = args.out.json;
    let component_plan_options = ComponentPlanOptions {
        allow_failed_components: args.allow_failed_components,
    };

    if !quiet && !json_out {
        println!(
            "{}: {} contract claims from `{}`",
            "verify".cyan().bold(),
            "lifting".dimmed(),
            project_root.display()
        );
    }

    // Stage 1: lift the kit's contract claims = load the kit's `.proof`
    // catalog and enumerate its callsites/claims.
    let pool = load_all_proofs::run(&project_root);
    let callsites = enumerate_callsites::run(&pool);
    let direct_formula_claims = enumerate_direct_formula_claims(&pool);

    if callsites.is_empty()
        && direct_formula_claims.is_empty()
        && !witness_verify::has_witnesses(&pool)
    {
        // No contract claims AND no witnesses. Reporting this as success is a
        // vacuous green: the run proved nothing. (A .proof carrying only
        // witness-mementos -- the pytest-witness seat -- has no callsites but
        // still has a witness dimension to verify, so it does NOT bail here.)
        let kit_label = args
            .kit
            .clone()
            .unwrap_or_else(|| project_root.display().to_string());
        if json_out {
            let out = json!({
                "kind": "verification-receipt",
                "schemaVersion": "1",
                "project": project_root.display().to_string(),
                "kit": args.kit,
                "claims": [],
                "totalClaims": 0,
                "discharged": 0,
                "failed": 0,
                "ok": false,
                "note": "no contract claims found in catalog; zero-claim verification is not a successful proof",
            });
            println!("{}", serde_json::to_string_pretty(&out).unwrap());
        } else if !quiet {
            println!(
                "{}: no contract claims found for `{}`; zero-claim verification is not a successful proof",
                "verify".red().bold(),
                kit_label
            );
            println!(
                "  (lift the kit first: `sugar mint --kit={}` or run the kit's lifter)",
                args.kit.as_deref().unwrap_or("<kit>")
            );
        }
        return EXIT_VERIFY_FAIL;
    }

    // Build the solver-dispatch plan + registry. Honor the kit's own
    // The kit author's declared `[solvers]` plan wins; otherwise the
    // default verify dispatch table over a single-Z3 registry.
    let (plan, solver_registry, plan_is_default) = build_plan_and_registry(&project_root, &args.z3);
    let component_plan = component_plan::plan_workspace_with_options(
        &project_root,
        PlanIntent::Verify,
        component_plan_options,
    );
    if let Err(error) = check_component_plan_errors(&component_plan) {
        eprintln!("{}: {error}", "error".red().bold());
        return EXIT_USER_ERROR;
    }
    if component_plan_options.allow_failed_components {
        emit_component_plan_warnings(&component_plan);
    }
    let compiler_registry =
        component_plan::compiler_registry_from_plan(&project_root, &component_plan);

    if !quiet && !json_out {
        let plan_label = match (&plan, plan_is_default) {
            (_, true) => "default solver-dispatch table".to_string(),
            (SolverPlan::Dispatch(_), false) => "kit-declared solver-dispatch table".to_string(),
            (SolverPlan::Chain(_), false) => "kit-declared solver chain".to_string(),
            (SolverPlan::Portfolio { .. }, false) => "kit-declared solver portfolio".to_string(),
            (SolverPlan::Single(n), false) => format!("kit-declared single solver `{n}`"),
        };
        println!(
            "  {} {} claims via {}",
            "discharging".dimmed(),
            callsites.len() + direct_formula_claims.len(),
            plan_label
        );
    }

    // Witness output directory.
    let witness_dir = args
        .emit_witnesses
        .clone()
        .unwrap_or_else(|| project_root.join(".sugar").join("witnesses"));

    // Resolve the signer seed once. A malformed override fails the whole
    // run (fail closed) rather than silently signing with the dev seed.
    let (signer_seed, signer_is_authoritative) = match resolve_signer_seed() {
        Ok(s) => s,
        Err(e) => {
            eprintln!("{}: signer key: {e}", "error".red().bold());
            return EXIT_USER_ERROR;
        }
    };
    if !quiet && !json_out && !signer_is_authoritative {
        println!(
            "  {} witnesses signed with the well-known dev seed (integrity tag only; set {} for an authoritative signer)",
            "note:".yellow(),
            SIGNER_KEY_ENV
        );
    }

    // Stage 2-4: per-claim discharge + witness mint.
    let mut results: Vec<ClaimResult> =
        Vec::with_capacity(callsites.len() + direct_formula_claims.len());
    for cs in &callsites {
        results.push(verify_one_claim(
            cs,
            &pool,
            &plan,
            &solver_registry,
            &compiler_registry,
            &witness_dir,
            &signer_seed,
            signer_is_authoritative,
        ));
    }
    for claim in &direct_formula_claims {
        results.push(verify_direct_formula_claim(
            claim,
            &plan,
            &solver_registry,
            &compiler_registry,
            &witness_dir,
            &signer_seed,
            signer_is_authoritative,
        ));
    }

    // Stage 5: emit receipt.
    let discharged = results
        .iter()
        .filter(|r| r.verdict == ObligationVerdict::Discharged)
        .count();
    let failed = results.len() - discharged;

    // Witness verify DIMENSION. Verification lives here, in rust: enumerate the
    // .proof's witness-mementos, RPC-resolve each body from the (untrusted) kit
    // oracle, blake3 it OURSELVES, and audit the signature. A body the oracle
    // approves that does not recompute to the pinned CID is a broken oracle,
    // caught because rust does the math anyway. Any non-verified witness fails.
    let witness_results =
        witness_verify::verify_witnesses_with_options(&project_root, &pool, component_plan_options);
    let witnesses_ok = witness_results.iter().all(|w| w.is_ok());
    let ok = failed == 0 && witnesses_ok;

    if json_out {
        emit_json_receipt(
            &project_root,
            &args.kit,
            &results,
            discharged,
            failed,
            ok,
            &witness_results,
        );
    } else {
        emit_human_receipt(&results, discharged, failed, ok, quiet, &witness_results);
    }

    // Exit code: any non-discharged claim OR non-verified witness is a
    // verification failure; an Undecidable verdict is a solver failure (exit 3)
    // only when there were no hard violations.
    if ok {
        EXIT_OK
    } else if !witnesses_ok
        || results
            .iter()
            .any(|r| r.verdict == ObligationVerdict::Unsatisfied)
    {
        EXIT_VERIFY_FAIL
    } else {
        // All failures were Undecidable / Disagreement: solver failure.
        EXIT_SOLVER_FAIL
    }
}

fn use_artifact_project_verify(args: &VerifyArgs, project_root: &Path) -> bool {
    args.emit_witnesses.is_none()
        && (args.project.is_some() || project_root.join(".sugar").join("config.toml").exists())
}

fn check_component_plan_errors(component_plan: &ComponentPlan) -> Result<(), String> {
    if let Some(diagnostic) = component_plan::first_error_diagnostic(component_plan) {
        return Err(diagnostic.message.clone());
    }
    Ok(())
}

fn emit_component_plan_warnings(component_plan: &ComponentPlan) {
    for diagnostic in component_plan::warning_diagnostics(component_plan) {
        eprintln!("{}: {}", "warning".yellow().bold(), diagnostic.message);
    }
}

fn run_artifact_project_verify(project_root: &Path, args: &VerifyArgs) -> u8 {
    let quiet = args.out.quiet;
    let json_out = args.out.json;
    let cfg_doc = read_project_config(project_root);
    let component_plan_options = ComponentPlanOptions {
        allow_failed_components: args.allow_failed_components,
    };
    let component_plan = component_plan::plan_workspace_with_options(
        project_root,
        PlanIntent::Verify,
        component_plan_options,
    );
    if let Err(error) = check_component_plan_errors(&component_plan) {
        eprintln!("{}: {error}", "error".red().bold());
        return EXIT_USER_ERROR;
    }
    if component_plan_options.allow_failed_components {
        emit_component_plan_warnings(&component_plan);
    }

    crate::cmd_prove::configure_witness_discharge_env_with_plan(
        project_root,
        &cfg_doc,
        Some(&component_plan),
    );

    let mut extra_projects: Vec<PathBuf> = Vec::new();
    for callee in &cfg_doc.callees {
        let p = project_root.join(callee);
        if p.exists() {
            extra_projects.push(p);
        }
    }

    let dependency_proofs = match crate::kit_dispatch::dependency_proofs_via_rpc(project_root) {
        Ok(proofs) => proofs,
        Err(error) => {
            eprintln!(
                "{}: dependency proof resolution failed: {error}",
                "error".red().bold()
            );
            return EXIT_USER_ERROR;
        }
    };

    let cfg = RunnerConfig {
        project_root: project_root.to_path_buf(),
        legacy_z3_fallback: Some(LegacyZ3Fallback::compat(args.z3.clone())),
        extra_projects,
        extra_proofs: dependency_proofs,
        trusted_implication_signers: cfg_doc.trusted_implication_signers.clone(),
        ..Default::default()
    };
    let compilers = component_plan::compiler_registry_from_plan(project_root, &component_plan);
    let runner = Runner::new_with_compilers(cfg, compilers);
    let run_artifact = match runner.run_with_proof_run() {
        Ok(artifact) => artifact,
        Err(error) => {
            eprintln!("{}: {error}", "error".red().bold());
            return EXIT_USER_ERROR;
        }
    };
    let report = run_artifact.report;
    let pool = load_all_proofs::run(project_root);
    let witness_results =
        witness_verify::verify_witnesses_with_options(project_root, &pool, component_plan_options);
    let witnesses_ok = witness_results.iter().all(|w| w.is_ok());
    let proof_gate = proof_report_gate(&report);
    let hard_failed_rows = proof_gate.hard_failed_rows;
    let undecided_rows = proof_gate.undecided_rows;
    let proof_ok = proof_gate.proof_ok;
    let proof_code = proof_gate.proof_code;
    let ok = proof_ok && witnesses_ok;

    if json_out {
        let mut out = report_fmt::report_to_json(&report);
        let rows = out
            .get("rows")
            .and_then(Json::as_array)
            .cloned()
            .unwrap_or_default();
        let claims: Vec<Json> = rows
            .iter()
            .map(|row| {
                let status = row.get("status").and_then(Json::as_str).unwrap_or("");
                json!({
                    "property": row.get("property").cloned().unwrap_or(Json::Null),
                    "propertyCid": row.get("propertyCid").cloned().unwrap_or(Json::Null),
                    "status": status,
                    "pass": status == "discharged",
                    "reason": row.get("reason").cloned().unwrap_or(Json::Null),
                    "dischargeMethod": row.get("dischargeMethod").cloned().unwrap_or(Json::Null),
                    "bodyDischargeTier": row.get("bodyDischargeTier").cloned().unwrap_or(Json::Null),
                    "bridge": row.get("bridge").cloned().unwrap_or(Json::Null),
                    "callee": row.get("callee").cloned().unwrap_or(Json::Null),
                    "file": row.get("file").cloned().unwrap_or(Json::Null),
                    "line": row.get("line").cloned().unwrap_or(Json::Null),
                })
            })
            .collect();
        let witness_dim: Vec<Json> = witness_results
            .iter()
            .map(|w| {
                json!({
                    "witnessCid": w.witness_cid,
                    "verdict": w.verdict(),
                    "checks": w.checks,
                    "reason": w.reason(),
                })
            })
            .collect();
        if let Some(obj) = out.as_object_mut() {
            obj.insert("kind".into(), Json::String("verification-receipt".into()));
            obj.insert("schemaVersion".into(), Json::String("1".into()));
            obj.insert(
                "project".into(),
                Json::String(project_root.display().to_string()),
            );
            obj.insert(
                "kit".into(),
                args.kit.clone().map(Json::String).unwrap_or(Json::Null),
            );
            obj.insert("claims".into(), Json::Array(claims));
            obj.insert("totalClaims".into(), json!(rows.len()));
            obj.insert("failed".into(), json!(hard_failed_rows));
            obj.insert("undecided".into(), json!(undecided_rows));
            obj.insert(
                "witnessDimension".into(),
                json!({
                    "witnesses": witness_dim,
                    "total": witness_results.len(),
                    "ok": witnesses_ok,
                }),
            );
            obj.insert("ok".into(), Json::Bool(ok));
        }
        match serde_json::to_string_pretty(&out) {
            Ok(s) => println!("{s}"),
            Err(e) => {
                eprintln!("{}: serialize receipt JSON: {e}", "error".red().bold());
                return EXIT_USER_ERROR;
            }
        }
    } else {
        report_fmt::print_report_pretty(&report, quiet);
        if !quiet && undecided_rows > 0 {
            print!("{}", format_undecided_rows(&report, undecided_rows));
        }
        if !quiet && !witness_results.is_empty() {
            print!("{}", format_witness_replay_report(&witness_results));
        }
    }

    if ok {
        EXIT_OK
    } else if !witnesses_ok {
        EXIT_VERIFY_FAIL
    } else {
        proof_code
    }
}

fn format_undecided_rows(report: &sugar_verifier::Report, undecided_rows: usize) -> String {
    let mut out = String::new();
    let _ = writeln!(out, "  undecided rows  : {}", undecided_rows);
    for row in report.rows.iter().filter(|row| {
        matches!(
            row.status,
            ObligationVerdict::Undecidable | ObligationVerdict::SolverTimeout
        )
    }) {
        let _ = writeln!(out, "      reason: {}", row.reason);
    }
    out
}

#[derive(Debug, Clone, Copy)]
struct ProofReportGate {
    hard_failed_rows: usize,
    undecided_rows: usize,
    proof_ok: bool,
    proof_code: u8,
}

fn proof_report_gate(report: &sugar_verifier::Report) -> ProofReportGate {
    let mut hard_failed_rows = 0usize;
    let mut undecided_rows = 0usize;
    for row in &report.rows {
        match row.status {
            ObligationVerdict::Discharged => {}
            ObligationVerdict::Unsatisfied
            | ObligationVerdict::Refused
            | ObligationVerdict::Disagreement => hard_failed_rows += 1,
            ObligationVerdict::Undecidable | ObligationVerdict::SolverTimeout => {
                undecided_rows += 1
            }
        }
    }
    let proof_ok = !report.rows.is_empty()
        && report.load_errors.is_empty()
        && hard_failed_rows == 0
        && undecided_rows == 0;
    let proof_code = if proof_ok {
        EXIT_OK
    } else if hard_failed_rows > 0 {
        EXIT_VERIFY_FAIL
    } else {
        EXIT_SOLVER_FAIL
    };
    ProofReportGate {
        hard_failed_rows,
        undecided_rows,
        proof_ok,
        proof_code,
    }
}

#[cfg(test)]
fn proof_report_exit_code(report: &sugar_verifier::Report) -> u8 {
    proof_report_gate(report).proof_code
}

/// Build the solver plan + registry for verification.
///
/// Precedence:
///   1. If the kit's `.sugar/config.toml` declares a `[solvers]`
///      config, the KIT AUTHOR'S PLAN WINS: build the registry from it
///      and derive the plan via `SolverPlan::from_config` (whatever the
///      kit declared — `Dispatch`, `Chain`, `Portfolio`, or `Single`).
///      `verify` does not override the kit's chosen routing.
///   2. Otherwise (no `[solvers]` config): synthesize the default
///      `verify` dispatch table over a single-Z3 registry. The default
///      table is the structure `verify` introduces so the verb still
///      routes by obligation class without a kit config; missing seats
///      simply miss the registry and `run_plan` reports Undecidable for
///      those rows (loudly), the correct posture on a host lacking those
///      backends.
///
/// Returns the plan, the registry, and whether the plan is the
/// synthesized default (vs. kit-declared) for honest receipt labelling.
fn build_plan_and_registry(
    project_root: &std::path::Path,
    z3_path: &str,
) -> (
    SolverPlan,
    std::collections::HashMap<SolverSeat, SolverHandle>,
    bool,
) {
    if let Ok(Some(sc)) = SolversConfig::load(project_root) {
        // Kit author's declared plan wins, verbatim.
        let reg = registry::build(&sc);
        let plan = SolverPlan::from_config(&sc);
        return (plan, reg, false);
    }
    // No kit config: the default verify dispatch table over single-Z3.
    let reg = registry::build_default_z3(z3_path);
    (SolverPlan::Dispatch(verify_dispatch_table()), reg, true)
}

fn enumerate_direct_formula_claims(pool: &MementoPool) -> Vec<DirectFormulaClaim> {
    let mut out = Vec::new();
    for (cid, member) in pool.contract_members() {
        if member.field("invVerification").and_then(|v| v.as_str()) != Some("obligation") {
            continue;
        }
        let formula = member
            .field("inv")
            .filter(|v| v.is_object())
            .cloned()
            .or_else(|| {
                let body = pool.contract_body_for_member(member)?;
                body.get("inv").filter(|v| v.is_object()).cloned()
            });
        let Some(formula) = formula else { continue };
        let property_name = member
            .field("name")
            .and_then(|v| v.as_str())
            .or_else(|| member.field("contractName").and_then(|v| v.as_str()))
            .unwrap_or("<unnamed>")
            .to_string();
        out.push(DirectFormulaClaim {
            property_name,
            property_cid: cid.to_string(),
            formula,
        });
    }
    out
}

fn verify_direct_formula_claim(
    claim: &DirectFormulaClaim,
    plan: &SolverPlan,
    solver_registry: &std::collections::HashMap<SolverSeat, SolverHandle>,
    compiler_registry: &CompilerRegistry,
    witness_dir: &std::path::Path,
    signer_seed: &[u8; 32],
    signer_is_authoritative: bool,
) -> ClaimResult {
    let mut result = ClaimResult {
        property_name: claim.property_name.clone(),
        property_cid: claim.property_cid.clone(),
        obligation_class: FormulaTheory::Default.as_str().to_string(),
        routed_solver: "<none>".to_string(),
        discharging_solver: "<none>".to_string(),
        verdict: ObligationVerdict::Undecidable,
        reason: String::new(),
        witness_cid: None,
        discharge_method: None,
        body_discharge_tier: None,
    };

    let theory = classify(&claim.formula);
    result.obligation_class = theory.as_str().to_string();
    result.routed_solver = routed_seat(plan, theory);

    let claim_input = match CompilerInput::decode_json(claim.formula.clone()) {
        Ok(input) => input,
        Err(error) => {
            result.verdict = ObligationVerdict::Undecidable;
            result.reason = format!("frontend decode: {}", error.payload);
            return result;
        }
    };
    let (verdict, reason, invs) =
        run_plan_with_compilers(plan, solver_registry, compiler_registry, &claim_input);
    result.verdict = verdict;
    result.reason = reason;
    result.discharging_solver = invs
        .iter()
        .find(|i| i.authoritative)
        .map(|i| format!("{}@{}", i.result.solver_name, i.result.solver_version))
        .unwrap_or_else(|| "<none>".to_string());

    if verdict == ObligationVerdict::Discharged {
        result.discharge_method = Some("solver-substantive".to_string());
        let property_cid = sugar_verifier::MementoCid::try_parse(claim.property_cid.clone()).ok();
        let pseudo_callsite = sugar_verifier::CallSite {
            bridge_ir_name: "direct-invariant".into(),
            bridge_target_cid: property_cid.clone(),
            bridge_source_layer: "contract".into(),
            bridge_target_layer: "solver".into(),
            property_name: claim.property_name.clone(),
            property_cid,
            ..Default::default()
        };
        match mint_verification_witness(
            &pseudo_callsite,
            &claim.formula,
            &result.discharging_solver,
            witness_dir,
            signer_seed,
            signer_is_authoritative,
        ) {
            Ok(cid) => result.witness_cid = Some(cid),
            Err(e) => {
                result.reason = format!("{} [witness-mint warning: {e}]", result.reason);
            }
        }
    }

    result
}

/// Discharge a single contract claim and mint a witness if it holds.
fn verify_one_claim(
    cs: &sugar_verifier::CallSite,
    pool: &MementoPool,
    plan: &SolverPlan,
    solver_registry: &std::collections::HashMap<SolverSeat, SolverHandle>,
    compiler_registry: &CompilerRegistry,
    witness_dir: &std::path::Path,
    signer_seed: &[u8; 32],
    signer_is_authoritative: bool,
) -> ClaimResult {
    let mut result = ClaimResult {
        property_name: cs.property_name.clone(),
        property_cid: cs
            .property_cid
            .as_ref()
            .map(ToString::to_string)
            .unwrap_or_default(),
        obligation_class: FormulaTheory::Default.as_str().to_string(),
        routed_solver: "<none>".to_string(),
        discharging_solver: "<none>".to_string(),
        verdict: ObligationVerdict::Undecidable,
        reason: String::new(),
        witness_cid: None,
        discharge_method: None,
        body_discharge_tier: None,
    };

    // Set when the panic-pre obligation was wrapped under a dominating guard
    // (`(and guard_facts) => pre`). A discharge of such an obligation is a
    // proof the call site CANNOT PANIC, tagged `panic-safe` -- a distinct,
    // substantive category, kept apart from `reflexive` (shallow self-post
    // tautology) and `solver-substantive` (arithmetic/refinement).
    let mut panic_guarded = false;

    if let Some(discharge) = sugar_verifier::attribute_safety::try_discharge(cs, pool) {
        result.verdict = discharge.verdict;
        result.reason = discharge.reason;
        result.discharge_method = discharge.discharge_method;
        result.obligation_class = "attribute-safety".to_string();
        result.routed_solver = "classShapes".to_string();
        result.discharging_solver = "classShapes".to_string();
        return result;
    }

    // ROUTING (the call-site-obligation precedence rule, generic + language-blind):
    // if the resolved TARGET CONTRACT carries a non-trivial `pre` (a real
    // precondition, not None/true), this call-site obligation is to DISCHARGE
    // THAT `pre` UNDER THE GUARD CONTEXT (`cs.guard_facts`), and that discharge
    // takes PRECEDENCE over the reflexive self-post path. We SKIP
    // `extract_body_obligation` (which would otherwise reduce the callee's
    // body-derived self-post to `unwrap(opt) == unwrap(opt)` and discharge it
    // REFLEXIVELY -- a vacuous pass that, on an UNGUARDED pre-bearing call,
    // would falsely report "cannot panic") by treating the lookup as
    // `Ok(None)`, which routes straight into the resolve-target + guard-discharge
    // arm below. The reflexive self-post path applies ONLY when the target has
    // no pre. The verifier recognizes no predicate name: the rule keys purely
    // on "target has a non-trivial pre."
    let target_has_pre = body_discharge::target_has_nontrivial_pre(cs, pool);
    if target_has_pre {
        info!(
            bridge = %cs.bridge_ir_name,
            target_cid = ?cs.bridge_target_cid,
            guard_facts = cs.guard_facts.len(),
            "verify_one_claim: target carries a non-trivial pre -> routing to guard-discharge \
             (discharge the precondition under the guard context); skipping the reflexive \
             self-post body-discharge path (precedence rule, language-blind)"
        );
    } else {
        debug!(
            bridge = %cs.bridge_ir_name,
            target_cid = ?cs.bridge_target_cid,
            "verify_one_claim: target has no non-trivial pre -> body-discharge path (unchanged)"
        );
    }
    let body_discharge_result = if target_has_pre {
        Ok(None)
    } else {
        body_discharge::extract_body_obligation(cs, pool)
    };

    // Body-discharge path (#1440): when the callsite names a callee with a
    // body-derived op-contract AND its harvested assertion has the
    // `=(<call>, <expected>)` shape, reduce the obligation THROUGH the
    // body. wp inlines the callee's value-semantics (`double(x) = x*2`),
    // so the solver sees a concrete formula (`*(3,2) == 6`) instead of an
    // uninterpreted `double` symbol. This is the spine that turns a
    // harvested body-obligation into a real, dischargeable / refutable
    // claim. Anything outside the recognized shape falls through to the
    // existing refinement path below.
    let obligation = match body_discharge_result {
        Ok(Some(body_discharge::BodyObligation::Reduced { formula, tier })) => {
            result.body_discharge_tier = Some(tier.as_str().to_string());
            formula
        }
        Ok(None) => {
            // Not a body-bearing claim: resolve the target contract's pre
            // and build the refinement obligation, exactly as before.
            let resolved = match resolve_target::run(cs, pool) {
                Ok(r) => r,
                Err(e) => {
                    result.reason = format!("resolve-target: {e}");
                    return result;
                }
            };

            // When the target has no precondition the claim is vacuously
            // discharged (nothing to prove). Otherwise build the wp /
            // refinement obligation: instantiate the resolved pre with the
            // call's arg term (the same obligation the prover builds).
            let Some(_pre) = resolved.ir_formula.as_ref() else {
                // HONESTY BOUNDARY (catches every body-bearing variant). The
                // vacuous-discharge shortcut is legitimate ONLY for a
                // genuinely non-body-bearing target. A target carrying
                // `formals` is body-bearing by definition: its `post`
                // describes a body whose obligation we reached here WITHOUT
                // reducing (e.g. `extract_body_obligation` could not build the
                // obligation because the body-derived `post` was not a
                // `result == <expr>` equation, so the resolver dropped it).
                // Vacuous-passing it would be a false green. Refuse instead:
                // leave the default Undecidable verdict (not discharged, not
                // pass, no witness).
                if resolved.target_is_body_bearing {
                    result.reason = format!(
                        "body-discharge: refuse: target `{}` is body-bearing \
                         (carries `formals`) but its obligation was not reduced \
                         and it has no precondition; refusing rather than \
                         reporting a vacuous pass",
                        cs.bridge_ir_name
                    );
                    return result;
                }
                if resolved.target_has_post {
                    result.reason = format!(
                        "vacuous-door: refuse: target `{}` carries a `post` but \
                         no `pre` and no `formals`; a lone opaque equality \
                         obligation has no constraining universe at this tier \
                         and must not vacuously discharge",
                        cs.bridge_ir_name
                    );
                    return result;
                }
                result.verdict = ObligationVerdict::Discharged;
                result.reason = "vacuous: target carries no precondition".to_string();
                result.obligation_class = "vacuous".to_string();
                result.discharging_solver = "none (vacuous)".to_string();
                return result;
            };

            debug!(
                bridge = %cs.bridge_ir_name,
                target_cid = ?cs.bridge_target_cid,
                resolved_pre = %resolved.ir_formula.as_ref()
                    .map(|f| f.to_string()).unwrap_or_else(|| "<none>".into()),
                arg_terms = %json!(callsite_actual_terms(cs)),
                "verify_one_claim: guard-discharge: resolved target pre, about to specialize \
                 with the callsite actual terms"
            );
            let instantiated = match instantiate::run_specialized(
                &resolved,
                &callsite_actual_terms(cs),
                cs.formal_actuals.as_ref(),
            ) {
                Ok(ob) => ob.ir_formula,
                Err(e) => {
                    result.reason = format!("instantiate: {e}");
                    return result;
                }
            };
            debug!(
                bridge = %cs.bridge_ir_name,
                instantiated_pre = %instantiated,
                guard_facts = cs.guard_facts.len(),
                guard_facts_json = %json!(cs.guard_facts),
                "verify_one_claim: guard-discharge: instantiated pre + guard facts \
                 (the obligation will be `(and guard_facts) => pre`; an empty guard set \
                 leaves the bare unprovable pre -> undecidable)"
            );
            // PANIC-FREEDOM guard discharge. A panic partial's instantiated pre
            // (`is_some(recv)`/`is_ok(recv)`/...) is unprovable on its own -- an
            // uninterpreted predicate over a free term -> the site is honestly
            // undecidable ("this unwrap is unproven"). When the call is
            // DOMINATED by the matching guard (a preceding `if recv.is_some()`
            // lifts it under `cf_ite(is_some(recv), ...)`, threaded into
            // `cs.guard_facts` by enumerate_callsites), the obligation becomes
            // `(and guard_facts) => pre`. With guard and pre identical after
            // substitution, the implication is valid -> PROVABLY panic-safe.
            // Fail-safe: empty guards keep the bare unprovable pre (undecidable);
            // an else-branch carries the NEGATED guard (`is_none(recv)`), which
            // never establishes `is_some(recv)` (also undecidable). No path
            // marks an unguarded site safe. `panic_guarded` flags the tag below.
            // The call-site obligation is the target pre SPECIALIZED to this
            // call's actual terms (`pre[formal_i := actual_i]`, free vars),
            // never a universal statement about all inputs and never a model of
            // panic effects. `run_specialized` returns that bare predicate
            // directly. Keep the strip as a defensive no-op for older hand-built
            // obligations that still arrive with one redundant outer forall.
            let specialized = instantiate::strip_outer_forall(&instantiated);
            if specialized != instantiated {
                debug!(
                    bridge = %cs.bridge_ir_name,
                    before = %instantiated,
                    after = %specialized,
                    "verify_one_claim: panic obligation: stripped redundant outer forall -> \
                     specialized pre over the free callsite arg (avoids guard-var capture and \
                     the opaque-sort `forall`->`true` emitter collapse)"
                );
            }

            // D-lib: CALLEE POSTCONDITION AS GUARD FACT (Phase 2 Tier D-lib,
            // cross-function-postcondition-as-assumable-fact). If the unwrap
            // receiver is itself a call (a `ctor` arg_term) whose bridge target
            // contract carries `post = is_ok(result)` (the strengthened totality
            // postcondition, NOT the generic is_ok||is_err), inject
            // `is_ok(arg_term)` as an additional guard fact.
            //
            // LANGUAGE-BLIND: body_discharge::callee_post_guard_fact reads only
            // JSON structure, recognizes no callee or library name, no type name.
            // The `is_ok` singleton post is the sole structural signal.
            //
            // ADDITIVE: the supplied fact is appended to any syntactic guard facts
            // already in cs.guard_facts. The same discharge path fires regardless
            // of fact source. No special case for the D-lib tier.
            //
            // REFUSE-FLOOR PRESERVED: when the callee's contract does NOT carry the
            // strengthened `is_ok(result)` singleton (e.g. generic T, or any
            // non-total Result-returner), `callee_post_guard_fact` returns None and
            // all_guard_facts == cs.guard_facts (unchanged). The unguarded site
            // stays undecidable; no false pass is introduced.
            let mut all_guard_facts: Vec<Json> = cs.guard_facts.clone();
            if let Some(callee_fact) = body_discharge::callee_post_guard_fact(cs, pool) {
                debug!(
                    bridge = %cs.bridge_ir_name,
                    callee_fact = %callee_fact,
                    "verify_one_claim: D-lib callee post supplies is_ok guard fact \
                     (totality contract on the unwrap receiver -> adding is_ok(arg) to guard context)"
                );
                all_guard_facts.push(callee_fact);
            }

            if all_guard_facts.is_empty() {
                info!(
                    bridge = %cs.bridge_ir_name,
                    target_cid = ?cs.bridge_target_cid,
                    obligation = %specialized,
                    "verify_one_claim: UNGUARDED panic site -> bare specialized pre obligation \
                     (no guard establishes it; the solver must leave it SAT-for-negation -> \
                     NOT-discharged: this is the refuse-floor negative control)"
                );
                specialized
            } else {
                panic_guarded = true;
                let antecedent = if all_guard_facts.len() == 1 {
                    all_guard_facts[0].clone()
                } else {
                    json!({ "kind": "and", "operands": all_guard_facts.clone() })
                };
                let guarded = json!({
                    "kind": "implies",
                    "operands": [antecedent, specialized],
                });
                info!(
                    bridge = %cs.bridge_ir_name,
                    target_cid = ?cs.bridge_target_cid,
                    guard_count = all_guard_facts.len(),
                    antecedent = %antecedent,
                    obligation = %guarded,
                    "verify_one_claim: GUARDED panic site -> `(and guard_facts) => pre` obligation \
                     (the guard must establish the pre; expected discharged + method=panic-safe)"
                );
                guarded
            }
        }
        Err(e) => {
            // The callee IS body-bearing (it has a body-derived op-contract)
            // but the obligation could not be reduced through the body: an
            // unrecognized assertion shape, an unconvertible operand, an
            // arity mismatch, or a wp refusal on a nested call. The spine
            // REFUSES rather than falling through to the refinement path,
            // because that path would mis-read the body-derived op-contract
            // (post/formals, no pre) as vacuous and report a FALSE pass.
            // Refusal leaves the default verdict (Undecidable): not
            // discharged, not pass, no witness, reason surfaced on the row.
            result.reason = format!("body-discharge: {e}");
            return result;
        }
    };

    // Classify the obligation for the dispatch table.
    let theory = classify(&obligation);
    result.obligation_class = theory.as_str().to_string();
    result.routed_solver = routed_seat(plan, theory);

    debug!(
        bridge = %cs.bridge_ir_name,
        panic_guarded,
        obligation_class = %result.obligation_class,
        routed_solver = %result.routed_solver,
        obligation = %obligation,
        "verify_one_claim: dispatching ProofIR obligation through the configured compiler registry"
    );

    // Dispatch through the solver-dispatch table.
    let obligation_input = match CompilerInput::decode_json(obligation.clone()) {
        Ok(input) => input,
        Err(error) => {
            result.verdict = ObligationVerdict::Undecidable;
            result.reason = format!("frontend decode: {}", error.payload);
            return result;
        }
    };
    let (verdict, reason, invs) =
        run_plan_with_compilers(plan, solver_registry, compiler_registry, &obligation_input);
    info!(
        bridge = %cs.bridge_ir_name,
        panic_guarded,
        verdict = %verdict.as_str(),
        reason = %reason,
        "verify_one_claim: solver verdict for the panic obligation"
    );
    result.verdict = verdict;
    result.reason = reason;
    // For a discharged obligation, record HOW it was proven. A
    // self-derived post reduces (after wp inlines the body) to `<term> ==
    // <term>`, discharged by reflexivity over uninterpreted terms: sound
    // but shallow. Tag it `reflexive` so the receipt never reports it as a
    // substantive proof. An obligation whose sides genuinely differ but
    // still discharges (real arithmetic / implication) is
    // `solver-substantive`.
    if verdict == ObligationVerdict::Discharged {
        result.discharge_method = Some(if panic_guarded {
            // A discharged guarded panic-pre is a proof the call site cannot
            // panic. Tag it distinctly so the scoreboard never conflates it
            // with a shallow reflexive self-post or a generic substantive
            // refinement discharge.
            "panic-safe".to_string()
        } else {
            body_discharge::classify_discharge_method(&obligation)
                .as_str()
                .to_string()
        });
    }
    result.discharging_solver = invs
        .iter()
        .find(|i| i.authoritative)
        .map(|i| format!("{}@{}", i.result.solver_name, i.result.solver_version))
        .unwrap_or_else(|| "<none>".to_string());

    // Mint + sign a witness for a discharged claim. A witness is minted
    // ONLY when the obligation is discharged (unsat for its negation); an
    // unsatisfied (violated) or undecidable claim mints nothing.
    if verdict == ObligationVerdict::Discharged {
        match mint_verification_witness(
            cs,
            &obligation,
            &result.discharging_solver,
            witness_dir,
            signer_seed,
            signer_is_authoritative,
        ) {
            Ok(cid) => result.witness_cid = Some(cid),
            Err(e) => {
                // Minting failure does not flip the verdict (the proof
                // held); surface it on the row.
                result.reason = format!("{} [witness-mint warning: {e}]", result.reason);
            }
        }
    }

    result
}

/// The solver seat the plan routes `theory` to (for the receipt's
/// per-claim "routed solver" field).
///
/// For a `Dispatch` plan this is the class-specific seat (falling back
/// to `default`). For a kit-declared non-dispatch plan the routing is
/// not theory-keyed, so we name the plan shape honestly rather than
/// pretending a per-class seat exists; the authoritative answer for
/// those is the `dischargingSolver` field, which records who actually
/// returned the verdict.
fn routed_seat(plan: &SolverPlan, theory: FormulaTheory) -> String {
    let d = match plan {
        SolverPlan::Dispatch(d) => d,
        SolverPlan::Single(n) => return format!("single:{n}"),
        SolverPlan::Chain(names) => return format!("chain:{}", seat_list(names)),
        SolverPlan::Portfolio { names, .. } => return format!("portfolio:{}", seat_list(names)),
    };
    let by_theory = match theory {
        FormulaTheory::EquationalTheory => d.equational_theory,
        FormulaTheory::FirstOrder => d.first_order,
        FormulaTheory::Strings => d.strings,
        FormulaTheory::Bitvectors => d.bitvectors,
        FormulaTheory::LinearArithmetic => d.linear_arithmetic,
        FormulaTheory::DependentType => d.dependent_type,
        FormulaTheory::CategoricalStructure => d.categorical_structure,
        FormulaTheory::Default => None,
    };
    by_theory
        .or(d.default)
        .map(|seat| seat.to_string())
        .unwrap_or_else(|| "<unrouted>".to_string())
}

fn seat_list(names: &[SolverSeat]) -> String {
    names
        .iter()
        .map(|seat| seat.as_str())
        .collect::<Vec<_>>()
        .join(",")
}

/// Mint a signed `WitnessMemento` citing the discharging solver and
/// write it to `witness_dir`. Returns the witness CID.
///
/// The signature is over JCS({header-content}) with the verify signer
/// seed; `signed_by` carries the signer's self-identifying public key,
/// and the discharging solver is recorded in `measurements.solver` so
/// consumers can trust-discriminate by prover.
fn mint_verification_witness(
    cs: &sugar_verifier::CallSite,
    obligation: &Json,
    discharging_solver: &str,
    witness_dir: &std::path::Path,
    signer_seed: &[u8; 32],
    signer_is_authoritative: bool,
) -> Result<String, String> {
    std::fs::create_dir_all(witness_dir)
        .map_err(|e| format!("create {}: {e}", witness_dir.display()))?;

    let pubkey = ed25519_pubkey_string(signer_seed);
    let observed_at = chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true);

    // The obligation CID is the fixture state this witness pins to.
    let obligation_jcs = jcs_of_json(obligation)?;
    let obligation_cid = blake3_512_of(obligation_jcs.as_bytes());

    // `signer_attests_authority` is honest about whether `signed_by`
    // names a real producer key or the well-known dev seed (integrity
    // tag only). Consumers trust-discriminate on it.
    let measurements = json!({
        "solver": discharging_solver,
        "obligation_cid": obligation_cid,
        "bridge_ir_name": cs.bridge_ir_name,
        "source_layer": cs.bridge_source_layer,
        "target_layer": cs.bridge_target_layer,
        "signer_attests_authority": signer_is_authoritative,
    });

    // Build the content over which the CID + signature are computed.
    // (Mirrors the WitnessMemento envelope/header convention: signed_by /
    // signature / observed_at are the HOW + WHEN (attestation + postmark),
    // EXCLUDED from the CID preimage per WitnessMemento::recompute_cid. Build
    // the memento with signer set + empty signature, derive the CID from the
    // canonical DISCHARGE bytes, then sign the {cid, observed_at} attestation
    // payload. The CID is the THEOREM-mode convergence handle: same discharge
    // => same CID regardless of WHO attests or WHEN. `observed_at` is a
    // TESTIMONY-mode IO event -- not in the convergence hash, but sworn
    // alongside the CID so the postmark cannot be peeled off or forged.
    let mut witness = sugar_ir_types::WitnessMemento {
        kind: "witness".to_string(),
        schema_version: "1".to_string(),
        witness_for: cs
            .property_cid
            .as_ref()
            .map(ToString::to_string)
            .unwrap_or_default(),
        subject: cs
            .bridge_target_cid
            .as_ref()
            .map(ToString::to_string)
            .unwrap_or_default(),
        fixture_state_cid: obligation_cid,
        observed_at,
        sample_count: 1,
        measurements,
        outcome: "pass".to_string(),
        signed_by: Some(pubkey),
        signature: None,
        cid: String::new(),
    };
    let cid = witness.recompute_cid().map_err(|e| e.to_string())?;
    witness.cid = cid.clone();
    // Seal the postmark under the signature: sign {cid, observed_at} (JCS),
    // the single source of truth defined in sugar-ir-types. The verify path
    // (witness_verify) reconstructs identical bytes.
    let attested = witness.attestation_payload();
    witness.signature = Some(ed25519_sign_string(signer_seed, &attested));

    let bytes =
        serde_json::to_string_pretty(&witness).map_err(|e| format!("serialize witness: {e}"))?;
    let hex = cid_hex(&cid).unwrap_or(&cid);
    let path = witness_dir.join(format!("witness-{hex}.json"));
    std::fs::write(&path, format!("{bytes}\n"))
        .map_err(|e| format!("write {}: {e}", path.display()))?;

    Ok(cid)
}

pub(crate) fn jcs_of_json(v: &Json) -> Result<String, String> {
    let canonical = json_to_canonical(v)?;
    Ok(encode_jcs(&canonical))
}

/// Convert serde_json into the canonicalizer's Value for JCS encoding.
/// (Mirrors the runner's `json_to_canonical`; integers only — witness
/// payloads carry no floats.)
fn json_to_canonical(value: &Json) -> Result<std::sync::Arc<sugar_canonicalizer::Value>, String> {
    use sugar_canonicalizer::Value as CV;
    match value {
        Json::Null => Ok(CV::null()),
        Json::Bool(b) => Ok(CV::boolean(*b)),
        Json::Number(n) => n
            .as_i64()
            .map(i128::from)
            .or_else(|| n.as_u64().map(i128::from))
            .map(CV::integer)
            .ok_or_else(|| format!("unsupported non-integer number in witness payload: {n}")),
        Json::String(s) => Ok(CV::string(s.clone())),
        Json::Array(items) => Ok(CV::array(
            items
                .iter()
                .map(json_to_canonical)
                .collect::<Result<Vec<_>, _>>()?,
        )),
        Json::Object(obj) => Ok(CV::object(
            obj.iter()
                .map(|(k, v)| Ok((k.clone(), json_to_canonical(v)?)))
                .collect::<Result<Vec<_>, String>>()?,
        )),
    }
}

/// The honest discharge split of a claim set. Every claim falls into
/// exactly one bucket. The two solver-reached discharge methods
/// (`reflexive`, `substantive`) are kept apart so a shallow `T == T`
/// proof is never reported as a meaningful one; `vacuous` is a
/// no-precondition discharge; `undecidable` is everything not discharged.
#[derive(Debug, Default, Clone, Copy)]
struct DischargeSplit {
    reflexive: usize,
    substantive: usize,
    /// Provably-panic-safe call sites: a panic partial's precondition
    /// (`is_some`/`is_ok`/bounds) discharged UNDER its dominating guard. This
    /// is the panic-freedom product metric (K). Kept apart from `reflexive`
    /// (shallow tautology) and `substantive` (arithmetic/refinement).
    panic_safe: usize,
    vacuous: usize,
    hash_tier: usize,
    undecidable: usize,
}

fn discharge_split(results: &[ClaimResult]) -> DischargeSplit {
    let mut s = DischargeSplit::default();
    for r in results {
        if r.verdict != ObligationVerdict::Discharged {
            s.undecidable += 1;
            continue;
        }
        match r.discharge_method.as_deref() {
            Some("reflexive") => s.reflexive += 1,
            Some("panic-safe") => s.panic_safe += 1,
            Some("solver-substantive") => s.substantive += 1,
            // A discharged claim with no recorded solver method came from
            // a non-solver path: vacuous (no precondition) or a hash-tier
            // memento-is-verification hit. Distinguish by obligation_class.
            _ => {
                if r.obligation_class == "vacuous" {
                    s.vacuous += 1;
                } else {
                    s.hash_tier += 1;
                }
            }
        }
    }
    s
}

fn emit_json_receipt(
    project_root: &std::path::Path,
    kit: &Option<String>,
    results: &[ClaimResult],
    discharged: usize,
    failed: usize,
    ok: bool,
    witnesses: &[witness_verify::WitnessVerifyResult],
) {
    let claims: Vec<Json> = results
        .iter()
        .map(|r| {
            json!({
                "property": r.property_name,
                "propertyCid": r.property_cid,
                "obligationClass": r.obligation_class,
                "routedSolver": r.routed_solver,
                "dischargingSolver": r.discharging_solver,
                "status": r.verdict.as_str(),
                "pass": r.verdict == ObligationVerdict::Discharged,
                "reason": r.reason,
                "witnessCid": r.witness_cid,
                "dischargeMethod": r.discharge_method,
                "bodyDischargeTier": r.body_discharge_tier,
            })
        })
        .collect();
    let split = discharge_split(results);
    let witness_dim: Vec<Json> = witnesses
        .iter()
        .map(|w| {
            json!({
                "witnessCid": w.witness_cid,
                "verdict": w.verdict(),
                "checks": w.checks,
                "reason": w.reason(),
            })
        })
        .collect();
    let witnesses_ok = witnesses.iter().all(|w| w.is_ok());
    let out = json!({
        "kind": "verification-receipt",
        "schemaVersion": "1",
        "project": project_root.display().to_string(),
        "kit": kit,
        "claims": claims,
        "totalClaims": results.len(),
        "discharged": discharged,
        "failed": failed,
        // The witness verify dimension: rust RPC-resolved each witness body from
        // the (untrusted) kit oracle, blake3'd it itself, and audited the
        // signature. "broken-oracle" = the oracle approved a body that did not
        // recompute to the pinned CID; rust caught it.
        "witnessDimension": {
            "witnesses": witness_dim,
            "total": witnesses.len(),
            "ok": witnesses_ok,
        },
        // Honest split of the discharged total. `reflexive` and
        // `solver-substantive` are the two solver-reached methods;
        // `vacuous` and `hash` are non-solver discharges; the methods are
        // never conflated. The reflexive bucket is sound but shallow.
        "dischargeSplit": {
            "reflexive": split.reflexive,
            "panicSafe": split.panic_safe,
            "solverSubstantive": split.substantive,
            "vacuous": split.vacuous,
            "hashTier": split.hash_tier,
            "undecidable": split.undecidable,
        },
        "ok": ok,
    });
    match serde_json::to_string_pretty(&out) {
        Ok(s) => println!("{s}"),
        Err(e) => eprintln!("{}: serialize receipt JSON: {e}", "error".red().bold()),
    }
}

fn emit_human_receipt(
    results: &[ClaimResult],
    discharged: usize,
    failed: usize,
    ok: bool,
    quiet: bool,
    witnesses: &[witness_verify::WitnessVerifyResult],
) {
    if quiet {
        return;
    }
    println!();
    println!("{}", "Sugar verification receipt".bold());
    for r in results {
        let status = match r.verdict {
            ObligationVerdict::Discharged => "pass".green().to_string(),
            ObligationVerdict::Unsatisfied => "FAIL".red().to_string(),
            ObligationVerdict::Undecidable => "undecidable".yellow().to_string(),
            ObligationVerdict::SolverTimeout => "solver-timeout".yellow().to_string(),
            ObligationVerdict::Disagreement => "disagreement".yellow().to_string(),
            ObligationVerdict::Refused => "refused".yellow().to_string(),
        };
        let method = r
            .discharge_method
            .as_deref()
            .map(|m| format!(", method={m}"))
            .unwrap_or_default();
        let body_tier = r
            .body_discharge_tier
            .as_deref()
            .map(|t| format!(", bodyTier={t}"))
            .unwrap_or_default();
        println!(
            "  [{}] {}  (class={}, solver={}{}{})",
            status, r.property_name, r.obligation_class, r.discharging_solver, method, body_tier
        );
        if let Some(cid) = &r.witness_cid {
            println!("        witness: {}", short_cid(cid).dimmed());
        }
        if !r.reason.is_empty() {
            println!("        {}", r.reason.dimmed());
        }
    }
    if !witnesses.is_empty() {
        println!();
        println!(
            "{}",
            "Witness dimension (rust recomputes; oracle untrusted)".bold()
        );
        for w in witnesses {
            let status = match &w.outcome {
                WitnessVerificationOutcome::Verified { .. } => "pass".green().to_string(),
                WitnessVerificationOutcome::BrokenOracle { .. } => {
                    "BROKEN-ORACLE".red().bold().to_string()
                }
                WitnessVerificationOutcome::Refused(_) => "REFUSED".red().to_string(),
            };
            println!(
                "  [{}] {}  ({})",
                status,
                short_cid(&w.witness_cid),
                w.checks.join("+")
            );
            let reason = w.reason();
            if !reason.is_empty() {
                println!("        {}", reason.dimmed());
            }
        }
    }
    println!();
    let split = discharge_split(results);
    let summary = format!(
        "{} claims: {} discharged ({} reflexive, {} panic-safe, {} solver-substantive, \
         {} vacuous, {} hash-tier), {} failed/undecidable",
        results.len(),
        discharged,
        split.reflexive,
        split.panic_safe,
        split.substantive,
        split.vacuous,
        split.hash_tier,
        failed
    );
    if ok {
        println!("{}: {}", "pass".green().bold(), summary);
    } else {
        println!("{}: {}", "FAIL".red().bold(), summary);
    }
}

fn format_witness_replay_report(witnesses: &[witness_verify::WitnessVerifyResult]) -> String {
    let mut out = String::new();
    if witnesses.is_empty() {
        return out;
    }
    let _ = writeln!(out);
    let _ = writeln!(
        out,
        "{}",
        "Witness body replay (rust recomputes; oracle untrusted)".bold()
    );
    for witness in witnesses {
        let status = match &witness.outcome {
            WitnessVerificationOutcome::Verified { .. } => "verified".green().to_string(),
            WitnessVerificationOutcome::BrokenOracle { .. } => {
                "broken-oracle".red().bold().to_string()
            }
            WitnessVerificationOutcome::Refused(_) => "refused".red().to_string(),
        };
        let _ = writeln!(out, "  [{status}] {}", witness.witness_cid);
        if !witness.checks.is_empty() {
            let _ = writeln!(out, "      checks: {}", witness.checks.join(", "));
        }
        let reason = witness.reason();
        if !reason.is_empty() {
            let _ = writeln!(out, "      reason: {}", reason);
        }
    }
    out
}

fn short_cid(cid: &str) -> String {
    let hex = cid_hex(cid).unwrap_or(cid);
    let take: String = hex.chars().take(16).collect();
    format!("blake3-512:{take}...")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_cid(label: &str) -> sugar_verifier::MementoCid {
        sugar_verifier::MementoCid::try_parse(label.to_string()).unwrap_or_else(|_| {
            sugar_verifier::MementoCid::try_parse(sugar_canonicalizer::blake3_512_of(
                label.as_bytes(),
            ))
            .expect("test CID must parse")
        })
    }

    fn test_cid_string(label: &str) -> String {
        test_cid(label).to_string()
    }

    fn insert_unanchored_test_member(
        pool: &mut MementoPool,
        cid: sugar_verifier::MementoCid,
        envelope: Json,
    ) {
        let member = sugar_verifier::StoredMember::from_envelope(cid.clone(), &envelope)
            .expect("test member must parse");
        pool.mementos.insert(cid, member);
    }

    fn test_compilers() -> CompilerRegistry {
        let mut compilers = CompilerRegistry::new();
        compilers.register(std::sync::Arc::new(
            sugar_ir_compiler_smt_lib::SmtLibCompiler::new(),
        ));
        compilers
    }

    fn verify_args(project: Option<PathBuf>, emit_witnesses: Option<PathBuf>) -> VerifyArgs {
        VerifyArgs {
            kit: None,
            project,
            z3: "z3".to_string(),
            emit_witnesses,
            allow_failed_components: false,
            require_empirically_witnessed: None,
            require_fixture: None,
            consensus_policy: None,
            artifact: None,
            proof: None,
            policy: None,
            out: crate::OutputFlags::default(),
        }
    }

    fn temp_project(name: &str) -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("system clock")
            .as_nanos();
        let root = std::env::temp_dir().join(format!("{name}_{nanos}"));
        std::fs::create_dir_all(&root).expect("create temp project");
        root
    }

    #[test]
    fn explicit_project_verify_uses_artifact_report_without_config() {
        let root = temp_project("verify_project_no_config");
        let args = verify_args(Some(root.clone()), None);
        assert!(use_artifact_project_verify(&args, &root));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn emit_witnesses_keeps_project_verify_on_live_claim_path() {
        let root = temp_project("verify_project_emit_witnesses");
        let args = verify_args(Some(root.clone()), Some(root.join(".sugar/witnesses")));
        assert!(!use_artifact_project_verify(&args, &root));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn config_still_selects_artifact_report_for_implicit_project() {
        let root = temp_project("verify_project_config");
        std::fs::create_dir_all(root.join(".sugar")).expect("create .sugar");
        std::fs::write(root.join(".sugar/config.toml"), "").expect("write config");
        let args = verify_args(None, None);
        assert!(use_artifact_project_verify(&args, &root));
        let _ = std::fs::remove_dir_all(root);
    }

    fn report_with_status(status: ObligationVerdict) -> sugar_verifier::Report {
        let mut report = sugar_verifier::Report::default();
        report.rows.push(sugar_verifier::ReportRow {
            callsite: sugar_verifier::CallSite {
                bridge_ir_name: "bridge".to_string(),
                property_name: "property".to_string(),
                ..sugar_verifier::CallSite::default()
            },
            status,
            reason: status.as_str().to_string(),
            discharge_method: None,
            body_discharge_tier: None,
            verification: None,
        });
        report
    }

    #[test]
    fn proof_report_exit_code_is_exhaustive_over_obligation_verdicts() {
        let cases = [
            (ObligationVerdict::Discharged, EXIT_OK),
            (ObligationVerdict::Unsatisfied, EXIT_VERIFY_FAIL),
            (ObligationVerdict::Undecidable, EXIT_SOLVER_FAIL),
            (ObligationVerdict::SolverTimeout, EXIT_SOLVER_FAIL),
            (ObligationVerdict::Disagreement, EXIT_VERIFY_FAIL),
            (ObligationVerdict::Refused, EXIT_VERIFY_FAIL),
        ];

        for (verdict, expected) in cases {
            let report = report_with_status(verdict);
            assert_eq!(
                proof_report_exit_code(&report),
                expected,
                "unexpected exit code for {verdict:?}"
            );
        }
    }

    #[test]
    fn dispatch_table_routes_each_theory_class() {
        // The solver-dispatch table is the structure: every theory class
        // maps to a seat, with a default fallback. This is the test that
        // PR-9's "the table is exercised, and supports adding more"
        // requirement leans on.
        let plan = SolverPlan::Dispatch(verify_dispatch_table());
        assert_eq!(routed_seat(&plan, FormulaTheory::LinearArithmetic), "z3");
        assert_eq!(routed_seat(&plan, FormulaTheory::FirstOrder), "vampire");
        assert_eq!(routed_seat(&plan, FormulaTheory::Bitvectors), "bitwuzla");
        assert_eq!(routed_seat(&plan, FormulaTheory::Strings), "cvc5");
        assert_eq!(routed_seat(&plan, FormulaTheory::EquationalTheory), "maude");
        assert_eq!(routed_seat(&plan, FormulaTheory::DependentType), "lean");
        assert_eq!(
            routed_seat(&plan, FormulaTheory::CategoricalStructure),
            "lean"
        );
        // Default class with no class-specific seat falls back to default.
        assert_eq!(routed_seat(&plan, FormulaTheory::Default), "z3");
    }

    #[test]
    fn dispatch_routes_lia_obligation_to_smt_seat() {
        // At least one obligation routed to SMT-LIB/Z3 (PR-9 verification
        // requirement). A linear-arithmetic obligation classifies as LIA,
        // which the table routes to the z3 SMT seat.
        let lia = json!({
            "kind": "atomic",
            "name": ">",
            "args": [{"kind":"var","name":"n"}, {"kind":"const","value":0}]
        });
        assert_eq!(classify(&lia), FormulaTheory::LinearArithmetic);
        let plan = SolverPlan::Dispatch(verify_dispatch_table());
        assert_eq!(routed_seat(&plan, classify(&lia)), "z3");
    }

    #[test]
    fn verify_dispatch_table_does_not_reintroduce_stringly_seats() {
        let source = include_str!("cmd_verify.rs");
        let table_source = source
            .split("pub fn verify_dispatch_table() -> DispatchConfig")
            .nth(1)
            .and_then(|tail| tail.split("/// Per-claim verification outcome").next())
            .expect("verify dispatch table source is present");

        for literal in [
            "\"z3\"",
            "\"vampire\"",
            "\"bitwuzla\"",
            "\"cvc5\"",
            "\"maude\"",
            "\"lean\"",
        ] {
            assert!(
                !table_source.contains(literal),
                "dispatch table must use SolverSeat variants, not seat literal {literal}"
            );
        }
    }

    #[test]
    fn witness_replay_report_names_checks_and_recompute_reason() {
        let out = format_witness_replay_report(&[witness_verify::WitnessVerifyResult {
            witness_cid: "blake3-512:witness-body".into(),
            outcome: WitnessVerificationOutcome::Verified {
                resolved_by: "rust-kit".into(),
            },
            checks: vec!["signature".into(), "content-address:rust-kit".into()],
        }]);

        assert!(out.contains("Witness body replay"), "{out}");
        assert!(out.contains("verified"), "{out}");
        assert!(out.contains("blake3-512:witness-body"), "{out}");
        assert!(
            out.contains("checks: signature, content-address:rust-kit"),
            "{out}"
        );
        assert!(
            out.contains(
                "reason: oracle resolved via rust-kit; rust recomputed the CID and it matched"
            ),
            "{out}"
        );
    }

    #[test]
    fn witness_payload_canonicalizes_and_signs() {
        // A minted witness must canonicalize (JCS) and produce a verifiable
        // CID + signature. This exercises the signing path without needing
        // a real solver or catalog.
        let tmp = std::env::temp_dir().join(format!("sugar-verify-test-{}", std::process::id()));
        let cs = sugar_verifier::CallSite {
            bridge_ir_name: "demo_bridge".into(),
            bridge_target_cid: Some(test_cid("target")),
            bridge_source_layer: "rust".into(),
            bridge_target_layer: "concept".into(),
            bridge_pin: sugar_verifier::BridgePin::SelfPinned,
            bridge_self_bundle_cid: None,
            callsite_bundle_cid: None,
            property_name: "demo_property".into(),
            property_cid: Some(test_cid("prop")),
            arg_term: None,
            arg_terms: Vec::new(),
            formal_actuals: None,
            producer_file: None,
            producer_line: None,
            producer_symbol: None,
            containing_atomic: None,
            guard_facts: Vec::new(),
            file: None,
            line: None,
            source_column: None,
            callee: None,
            panic_site: false,
            attribute_safety: None,
        };
        let obligation = json!({"kind":"atomic","name":"true","args":[]});
        let cid = mint_verification_witness(
            &cs,
            &obligation,
            "z3@4.x",
            &tmp,
            &VERIFY_SIGNER_SEED_DEV,
            false,
        )
        .expect("witness mint must succeed");
        assert!(cid.starts_with("blake3-512:"));
        // The witness file exists and re-parses as a WitnessMemento.
        let hex = cid_hex(&cid).unwrap_or(&cid);
        let path = tmp.join(format!("witness-{hex}.json"));
        let bytes = std::fs::read_to_string(&path).expect("witness file written");
        let parsed: sugar_ir_types::WitnessMemento =
            serde_json::from_str(&bytes).expect("witness re-parses");
        assert_eq!(parsed.outcome, "pass");
        assert_eq!(parsed.measurements["solver"], "z3@4.x");
        // The dev seed is an integrity tag, not authority.
        assert_eq!(parsed.measurements["signer_attests_authority"], false);
        assert!(parsed.signature.is_some());
        let _ = std::fs::remove_dir_all(&tmp);
    }

    // -----------------------------------------------------------------------
    // PANIC-FREEDOM routing (the call-site-obligation precedence rule).
    //
    // The trap shape: ONE contract carrying a real `pre` (`is_some(opt)`) AND
    // `formals` + a body-derived `post` -- i.e. it is BOTH pre-bearing AND
    // body-bearing. Before the routing fix, `extract_body_obligation` fired
    // first on this shape and discharged the callee self-post REFLEXIVELY
    // (`unwrap(opt) == unwrap(opt)`), preempting the precondition. On an
    // UNGUARDED call that is a false "cannot panic." The fix routes any
    // pre-bearing target to the guard-discharge path:
    //   - guarded   (guard_facts = [is_some(opt)]) -> `(is_some(opt) => is_some(opt))`
    //                valid -> discharged, method = `panic-safe` (NOT reflexive).
    //   - unguarded (guard_facts = [])             -> bare `is_some(opt)` over a
    //                free `opt` -> unprovable -> NOT discharged (the negative
    //                control; never a false pass).
    // This is the snake-eats-tail proof the mechanism is real and sound.
    // -----------------------------------------------------------------------

    const PRE_BEARING_BODY_BEARING_CID: &str = "panic-trap-contract";
    const TRAP_BUNDLE: &str = "panic-trap-bundle";

    /// The trap contract: pre = `is_some(opt)`, plus `formals` + a
    /// body-derived `post` (so it is body-bearing too). This is the dual-shape
    /// the routing rule must resolve in favor of the pre.
    fn panic_trap_pool() -> MementoPool {
        let pre = json!({"kind": "atomic", "name": "is_some",
            "args": [{"kind": "var", "name": "opt"}]});
        let post = json!({"kind": "atomic", "name": "=",
            "args": [{"kind": "var", "name": "result"},
                     {"kind": "ctor", "name": "option_unwrap",
                      "args": [{"kind": "var", "name": "opt"}]}]});
        let env = json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "pre": pre,
                    "post": post,
                    "formals": ["opt"],
                    // OPAQUE Rust source sort (NOT an SMT primitive). This is
                    // load-bearing for the negative control: it reproduces the
                    // emitter's opaque-`forall`->`true` collapse, so a
                    // pre-strip unguarded site FALSELY discharges. With `Int`
                    // here the bug would be masked (a primitive-sorted forall
                    // emits faithfully), and the test would pass for the wrong
                    // reason. The strip fix is what makes the unguarded site
                    // honestly undecidable; this sort makes the test able to
                    // catch a regression of it.
                    "formalSorts": [{"kind": "primitive", "name": "Option<T>"}]
                }
            }
        });
        let mut pool = MementoPool::default();
        insert_unanchored_test_member(&mut pool, test_cid(PRE_BEARING_BODY_BEARING_CID), env);
        pool.bundle_members
            .entry(test_cid(TRAP_BUNDLE))
            .or_default()
            .insert(test_cid(PRE_BEARING_BODY_BEARING_CID));
        pool
    }

    /// A callsite into the trap contract. `guard_facts` is the only axis that
    /// differs between the guarded and unguarded sites.
    fn panic_callsite(guard_facts: Vec<Json>) -> sugar_verifier::CallSite {
        sugar_verifier::CallSite {
            bridge_ir_name: "method:unwrap".into(),
            bridge_target_cid: Some(test_cid(PRE_BEARING_BODY_BEARING_CID)),
            bridge_source_layer: "rust".into(),
            bridge_target_layer: "concept".into(),
            bridge_pin: sugar_verifier::BridgePin::SelfPinned,
            bridge_self_bundle_cid: Some(test_cid(TRAP_BUNDLE)),
            callsite_bundle_cid: Some(test_cid(TRAP_BUNDLE)),
            property_name: "panic_site".into(),
            property_cid: Some(test_cid("panic-prop")),
            arg_term: Some(json!({"kind": "var", "name": "opt"})),
            arg_terms: Vec::new(),
            formal_actuals: None,
            producer_file: None,
            producer_line: None,
            producer_symbol: None,
            containing_atomic: None,
            guard_facts,
            file: None,
            line: None,
            source_column: None,
            callee: None,
            // This fixture is a panic trap (`opt.unwrap()`); the guarded vs
            // unguarded split keys off `panic_site` to demand the `panic-safe`
            // discharge method, so it MUST be a panic site.
            panic_site: true,
            attribute_safety: None,
        }
    }

    fn is_some_guard() -> Json {
        json!({"kind": "atomic", "name": "is_some",
            "args": [{"kind": "var", "name": "opt"}]})
    }

    #[test]
    fn routing_predicate_fires_on_pre_bearing_target_not_on_post_only_or_true() {
        let pool = panic_trap_pool();
        // The trap contract carries a real `pre` -> route to guard-discharge.
        assert!(
            body_discharge::target_has_nontrivial_pre(&panic_callsite(vec![]), &pool),
            "a contract with pre=is_some(opt) must route to guard-discharge"
        );

        // A post-only contract (no `pre`) must NOT reroute: stays on the
        // body-discharge path (the `double()` family is unaffected).
        let mut post_only = MementoPool::default();
        insert_unanchored_test_member(
            &mut post_only,
            test_cid("post-only"),
            json!({"evidence": {"kind": "contract", "body": {
                "post": {"kind": "atomic", "name": "=", "args": []},
                "formals": ["x"]}}}),
        );
        let mut cs = panic_callsite(vec![]);
        cs.bridge_target_cid = Some(test_cid("post-only"));
        assert!(
            !body_discharge::target_has_nontrivial_pre(&cs, &post_only),
            "a post-only (no-pre) contract must stay on the body-discharge path"
        );

        // A `pre = true` total contract (e.g. unwrap_or) is trivial -> no
        // reroute (a vacuous pre is nothing to discharge under guards).
        let mut total = MementoPool::default();
        insert_unanchored_test_member(
            &mut total,
            test_cid("total"),
            json!({"evidence": {"kind": "contract", "body": {
                "pre": {"kind": "atomic", "name": "true", "args": []},
                "post": {"kind": "atomic", "name": "=", "args": []},
                "formals": ["x"]}}}),
        );
        cs.bridge_target_cid = Some(test_cid("total"));
        assert!(
            !body_discharge::target_has_nontrivial_pre(&cs, &total),
            "a pre=true contract must NOT reroute (trivial precondition)"
        );
    }

    #[test]
    fn guarded_panic_safe_unguarded_undecidable() {
        // The whole point (K=1 with the negative control). Needs a real z3.
        let pool = panic_trap_pool();
        // No kit config at this path -> the default verify dispatch table over
        // single-z3 (the real solver discriminates guarded from unguarded).
        let no_kit = std::path::Path::new("/nonexistent-panic-test-kit");
        let (plan, registry, _) = build_plan_and_registry(no_kit, "z3");
        let witness_dir =
            std::env::temp_dir().join(format!("sugar-panic-test-{}", std::process::id()));
        std::fs::create_dir_all(&witness_dir).ok();

        // GUARDED: `if opt.is_some() { opt.unwrap() }`. The guard establishes
        // the partial's pre -> PROVABLY panic-safe.
        let guarded = verify_one_claim(
            &panic_callsite(vec![is_some_guard()]),
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            &witness_dir,
            &VERIFY_SIGNER_SEED_DEV,
            false,
        );
        assert_eq!(
            guarded.verdict,
            ObligationVerdict::Discharged,
            "guarded unwrap must be discharged (the is_some guard discharges the is_some pre); \
             reason: {}",
            guarded.reason
        );
        assert_eq!(
            guarded.discharge_method.as_deref(),
            Some("panic-safe"),
            "a guarded panic-pre discharge must be tagged `panic-safe`, NOT reflexive/substantive; \
             reason: {}",
            guarded.reason
        );

        // UNGUARDED: bare `opt.unwrap()`. No guard -> bare `is_some(opt)` over a
        // free `opt` is unprovable -> NEVER discharged. The negative control:
        // a vacuous/reflexive pass here would be a false "cannot panic".
        let unguarded = verify_one_claim(
            &panic_callsite(vec![]),
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            &witness_dir,
            &VERIFY_SIGNER_SEED_DEV,
            false,
        );
        assert_ne!(
            unguarded.verdict,
            ObligationVerdict::Discharged,
            "REFUSE-FLOOR: an unguarded unwrap into a pre-bearing contract must NEVER be \
             discharged (no guard establishes the pre); got discharged with reason: {}",
            unguarded.reason
        );
        assert_ne!(
            unguarded.discharge_method.as_deref(),
            Some("panic-safe"),
            "an unguarded site must never be tagged panic-safe; reason: {}",
            unguarded.reason
        );

        let _ = std::fs::remove_dir_all(&witness_dir);
    }

    // -----------------------------------------------------------------------
    // PHASE 2 TIER D-LIB: callee-post as guard fact (serde_json::Value totality)
    //
    // This tests the cross-function-postcondition-as-assumable-fact mechanism:
    // when the `.unwrap()` receiver is a call (`ctor` arg_term) whose bridge
    // target contract carries `post = is_ok(result)`, `callee_post_guard_fact`
    // injects `is_ok(arg_term)` into the guard context, and the existing
    // `(and guard_facts) => pre` discharge path fires.
    //
    // Two sub-tests, one pool:
    //   VALUE-TOTAL site: ctor arg_term with is_ok post -> PANIC-SAFE.
    //   GENERIC-RESULT control: ctor arg_term with is_ok||is_err post -> UNDECIDABLE.
    //
    // The control directly proves the Value-specialization is real: if the
    // totality post leaked to the generic contract, the control would flip to
    // PANIC-SAFE, which would be a false claim.
    // -----------------------------------------------------------------------

    // CID constants for the D-lib test pool.
    const DLIB_TOTALITY_CONTRACT_CID: &str = "dlib-totality-contract";
    const DLIB_OPTION_TOTALITY_CONTRACT_CID: &str = "dlib-option-totality-contract";
    const DLIB_RESULT_UNWRAP_CID: &str = "dlib-result-unwrap";
    const DLIB_OPTION_EXPECT_CID: &str = "dlib-option-expect";
    const DLIB_OPTION_EXPECT_MISMATCH_CID: &str = "dlib-option-expect-mismatch";
    const DLIB_GENERIC_CONTRACT_CID: &str = "dlib-generic-result";
    const DLIB_BUNDLE: &str = "dlib-bundle";

    /// Build the D-lib test pool. Contains:
    ///   (a) the Value-totality contract: post = is_ok(result), no pre
    ///   (b) the result_unwrap contract: pre = is_ok(result), body-bearing
    ///   (c) the generic Result contract: post = is_ok||is_err (NOT total), no pre
    ///   (d) bridges: serde_json_to_string_value -> (a), to_string_generic -> (c)
    fn dlib_pool() -> MementoPool {
        // (a) Value-totality contract: post = is_ok(result), no pre.
        // This is the D-lib catalog entry. The bridge for to_string_value
        // points here.
        let totality_contract = json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "post": {
                        "kind": "atomic",
                        "name": "is_ok",
                        "args": [{"kind": "var", "name": "result"}]
                    }
                }
            }
        });

        // Option-totality contract: post = is_some(result), no pre.
        // This is the D-fn catalog primitive shape (`.cid(...)` known Some).
        let option_totality_contract = json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "post": {
                        "kind": "atomic",
                        "name": "is_some",
                        "args": [{"kind": "var", "name": "result"}]
                    }
                }
            }
        });

        // (b) result_unwrap contract: pre = is_ok(result). This is the
        // result_unwrap partial (same shape as the rust-std shim's
        // result_unwrap, with an explicit pre for the discharge path).
        // formalSorts uses a primitive sort so the opaque-forall emitter
        // path does not collapse it to `true`.
        let result_unwrap_contract = json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "pre": {
                        "kind": "atomic",
                        "name": "is_ok",
                        "args": [{"kind": "var", "name": "result"}]
                    },
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "out"},
                            {"kind": "ctor", "name": "result_unwrap",
                             "args": [{"kind": "var", "name": "result"}]}
                        ]
                    },
                    "formals": ["result"],
                    "formalSorts": [{"kind": "primitive", "name": "Result"}]
                }
            }
        });

        // Option::expect partial: pre = is_some(result).
        let option_expect_contract = json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "pre": {
                        "kind": "atomic",
                        "name": "is_some",
                        "args": [{"kind": "var", "name": "result"}]
                    },
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "out"},
                            {"kind": "ctor", "name": "option_expect",
                             "args": [{"kind": "var", "name": "result"}]}
                        ]
                    },
                    "formals": ["result"],
                    "formalSorts": [{"kind": "primitive", "name": "Option"}]
                }
            }
        });

        // Same partial shape, but the pre mentions a different receiver.
        // A supplied is_some(actual_receiver) fact must not discharge it.
        let option_expect_mismatch_contract = json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "pre": {
                        "kind": "atomic",
                        "name": "is_some",
                        "args": [{"kind": "var", "name": "other"}]
                    },
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "out"},
                            {"kind": "ctor", "name": "option_expect",
                             "args": [{"kind": "var", "name": "result"}]}
                        ]
                    },
                    "formals": ["result"],
                    "formalSorts": [{"kind": "primitive", "name": "Option"}]
                }
            }
        });

        // (c) generic Result contract: post = is_ok(result) || is_err(result).
        // This is NOT a totality contract -- it says the result is some kind
        // of Result, not specifically Ok. No pre, no formals.
        let generic_contract = json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "post": {
                        "kind": "or",
                        "operands": [
                            {"kind": "atomic", "name": "is_ok",
                             "args": [{"kind": "var", "name": "result"}]},
                            {"kind": "atomic", "name": "is_err",
                             "args": [{"kind": "var", "name": "result"}]}
                        ]
                    }
                }
            }
        });

        // (d1) Bridge: serde_json_to_string_value -> totality contract.
        let totality_bridge = json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": "serde_json_to_string_value",
                    "targetContractCid": test_cid_string(DLIB_TOTALITY_CONTRACT_CID)
                }
            }
        });

        // Bridge: grammar_op_registry_cid_known -> option-totality contract.
        let option_totality_bridge = json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": "grammar_op_registry_cid_known",
                    "targetContractCid": test_cid_string(DLIB_OPTION_TOTALITY_CONTRACT_CID)
                }
            }
        });

        // (d2) Bridge: to_string_generic -> generic contract.
        let generic_bridge = json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": "to_string_generic",
                    "targetContractCid": test_cid_string(DLIB_GENERIC_CONTRACT_CID)
                }
            }
        });

        let mut pool = MementoPool::default();
        insert_unanchored_test_member(
            &mut pool,
            test_cid(DLIB_TOTALITY_CONTRACT_CID),
            totality_contract,
        );
        insert_unanchored_test_member(
            &mut pool,
            test_cid(DLIB_OPTION_TOTALITY_CONTRACT_CID),
            option_totality_contract,
        );
        insert_unanchored_test_member(
            &mut pool,
            test_cid(DLIB_RESULT_UNWRAP_CID),
            result_unwrap_contract,
        );
        insert_unanchored_test_member(
            &mut pool,
            test_cid(DLIB_OPTION_EXPECT_CID),
            option_expect_contract,
        );
        insert_unanchored_test_member(
            &mut pool,
            test_cid(DLIB_OPTION_EXPECT_MISMATCH_CID),
            option_expect_mismatch_contract,
        );
        insert_unanchored_test_member(
            &mut pool,
            test_cid(DLIB_GENERIC_CONTRACT_CID),
            generic_contract,
        );
        let totality_bridge_cid = test_cid("dlib-totality-bridge");
        insert_unanchored_test_member(
            &mut pool,
            totality_bridge_cid.clone(),
            totality_bridge.clone(),
        );
        pool.insert_bridge_by_symbol(
            "serde_json_to_string_value",
            totality_bridge_cid,
            totality_bridge,
        );
        let option_totality_bridge_cid = test_cid("dlib-option-totality-bridge");
        insert_unanchored_test_member(
            &mut pool,
            option_totality_bridge_cid.clone(),
            option_totality_bridge.clone(),
        );
        pool.insert_bridge_by_symbol(
            "grammar_op_registry_cid_known",
            option_totality_bridge_cid,
            option_totality_bridge,
        );
        let generic_bridge_cid = test_cid("dlib-generic-bridge");
        insert_unanchored_test_member(
            &mut pool,
            generic_bridge_cid.clone(),
            generic_bridge.clone(),
        );
        pool.insert_bridge_by_symbol("to_string_generic", generic_bridge_cid, generic_bridge);
        pool.bundle_members
            .entry(test_cid(DLIB_BUNDLE))
            .or_default()
            .extend([
                test_cid(DLIB_TOTALITY_CONTRACT_CID),
                test_cid(DLIB_OPTION_TOTALITY_CONTRACT_CID),
                test_cid(DLIB_RESULT_UNWRAP_CID),
                test_cid(DLIB_OPTION_EXPECT_CID),
                test_cid(DLIB_OPTION_EXPECT_MISMATCH_CID),
                test_cid(DLIB_GENERIC_CONTRACT_CID),
            ]);
        pool
    }

    /// Build a callsite for `.unwrap()` on the result of a `ctor` call.
    /// `callee_ctor_name`: the ctor name in the arg_term (which function
    /// produced the Result being unwrapped).
    /// `guard_facts`: any syntactic guard facts (empty for our D-lib test).
    fn dlib_unwrap_callsite(
        callee_ctor_name: &str,
        guard_facts: Vec<Json>,
    ) -> sugar_verifier::CallSite {
        sugar_verifier::CallSite {
            bridge_ir_name: "result_unwrap".into(),
            bridge_target_cid: Some(test_cid(DLIB_RESULT_UNWRAP_CID)),
            bridge_source_layer: "rust".into(),
            bridge_target_layer: "concept".into(),
            bridge_pin: sugar_verifier::BridgePin::SelfPinned,
            bridge_self_bundle_cid: Some(test_cid(DLIB_BUNDLE)),
            property_name: "dlib_panic_site".into(),
            property_cid: Some(test_cid("dlib-prop")),
            // The arg_term is the ctor call expression -- the result of calling
            // `callee_ctor_name(v)` that gets passed to `.unwrap()`.
            arg_term: Some(json!({
                "kind": "ctor",
                "name": callee_ctor_name,
                "args": [{"kind": "var", "name": "v"}]
            })),
            containing_atomic: None,
            guard_facts,
            ..Default::default()
        }
    }

    fn dlib_option_expect_callsite(
        callee_ctor_name: &str,
        target_cid: &str,
    ) -> sugar_verifier::CallSite {
        sugar_verifier::CallSite {
            bridge_ir_name: "option_expect".into(),
            bridge_target_cid: Some(test_cid(target_cid)),
            bridge_source_layer: "rust".into(),
            bridge_target_layer: "concept".into(),
            bridge_pin: sugar_verifier::BridgePin::SelfPinned,
            bridge_self_bundle_cid: Some(test_cid(DLIB_BUNDLE)),
            property_name: "dlib_option_panic_site".into(),
            property_cid: Some(test_cid("dlib-option-prop")),
            arg_term: Some(json!({
                "kind": "ctor",
                "name": callee_ctor_name,
                "args": [{"kind": "var", "name": "v"}]
            })),
            containing_atomic: None,
            guard_facts: vec![],
            ..Default::default()
        }
    }

    #[test]
    fn dlib_value_totality_discharges_panic_safe_control_stays_undecidable() {
        // Phase 2 Tier D-lib full-pipeline test. Needs a real z3.
        //
        // POSITIVE: `serde_json_to_string_value(v).unwrap()` -- the callee's
        // contract carries `post = is_ok(result)`. `callee_post_guard_fact`
        // supplies `is_ok(ctor(...))` as an established fact. The discharge
        // path fires: `is_ok(ctor(v)) => is_ok(ctor(v))` is a tautology.
        // Expected: PANIC-SAFE (Discharged, method = panic-safe).
        //
        // CONTROL: `to_string_generic(v).unwrap()` -- the callee's contract
        // carries the generic `is_ok || is_err` post, NOT the singleton `is_ok`.
        // `callee_post_guard_fact` returns None. No guard -> undecidable.
        // Expected: NOT Discharged (refuse-floor).
        let pool = dlib_pool();
        let no_kit = std::path::Path::new("/nonexistent-dlib-test-kit");
        let (plan, registry, _) = build_plan_and_registry(no_kit, "z3");
        let witness_dir =
            std::env::temp_dir().join(format!("sugar-dlib-test-{}", std::process::id()));
        std::fs::create_dir_all(&witness_dir).ok();

        // POSITIVE: Value-totality ctor arg. The callee_post_guard_fact wiring
        // injects is_ok(serde_json_to_string_value(v)) into guard_facts.
        let positive = verify_one_claim(
            &dlib_unwrap_callsite("serde_json_to_string_value", vec![]),
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            &witness_dir,
            &VERIFY_SIGNER_SEED_DEV,
            false,
        );
        assert_eq!(
            positive.verdict,
            ObligationVerdict::Discharged,
            "D-lib VALUE-TOTAL site: callee post supplies is_ok fact -> must discharge PANIC-SAFE; \
             reason: {}",
            positive.reason
        );
        assert_eq!(
            positive.discharge_method.as_deref(),
            Some("panic-safe"),
            "D-lib discharge must be tagged `panic-safe` (not reflexive/substantive); \
             reason: {}",
            positive.reason
        );

        // CONTROL: generic is_ok||is_err post -- NOT a totality contract.
        // callee_post_guard_fact returns None -> no supplemental fact ->
        // bare is_ok(ctor(v)) over a free v -> unprovable -> UNDECIDABLE.
        // This is the D-lib refuse-floor: if the is_ok post leaked to the
        // generic contract, this site would falsely discharge as panic-safe.
        let control = verify_one_claim(
            &dlib_unwrap_callsite("to_string_generic", vec![]),
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            &witness_dir,
            &VERIFY_SIGNER_SEED_DEV,
            false,
        );
        assert_ne!(
            control.verdict,
            ObligationVerdict::Discharged,
            "D-lib CONTROL: generic is_ok||is_err post must NOT supply the totality fact; \
             site must stay UNDECIDABLE (refuse-floor); got discharged with reason: {}",
            control.reason
        );
        assert_ne!(
            control.discharge_method.as_deref(),
            Some("panic-safe"),
            "D-lib control must never be tagged panic-safe; reason: {}",
            control.reason
        );

        let _ = std::fs::remove_dir_all(&witness_dir);
    }

    #[test]
    fn dlib_singleton_is_some_post_discharges_option_expect_panic_safe() {
        // D-fn / language-blind callee-post fact supply:
        // post = is_some(result) should supply is_some(receiver), exactly like
        // post = is_ok(result) supplies is_ok(receiver). The verifier must not
        // hardcode Rust's Result predicate vocabulary.
        let pool = dlib_pool();
        let no_kit = std::path::Path::new("/nonexistent-dlib-option-test-kit");
        let (plan, registry, _) = build_plan_and_registry(no_kit, "z3");
        let witness_dir =
            std::env::temp_dir().join(format!("sugar-dlib-option-test-{}", std::process::id()));
        std::fs::create_dir_all(&witness_dir).ok();

        let positive = verify_one_claim(
            &dlib_option_expect_callsite("grammar_op_registry_cid_known", DLIB_OPTION_EXPECT_CID),
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            &witness_dir,
            &VERIFY_SIGNER_SEED_DEV,
            false,
        );
        assert_eq!(
            positive.verdict,
            ObligationVerdict::Discharged,
            "D-fn singleton is_some post must discharge option_expect pre as PANIC-SAFE; reason: {}",
            positive.reason
        );
        assert_eq!(
            positive.discharge_method.as_deref(),
            Some("panic-safe"),
            "D-fn singleton post discharge must be tagged panic-safe; reason: {}",
            positive.reason
        );

        let _ = std::fs::remove_dir_all(&witness_dir);
    }

    #[test]
    fn dlib_wrong_predicate_and_wrong_receiver_stay_undecidable() {
        let pool = dlib_pool();
        let no_kit = std::path::Path::new("/nonexistent-dlib-option-negative-test-kit");
        let (plan, registry, _) = build_plan_and_registry(no_kit, "z3");
        let witness_dir =
            std::env::temp_dir().join(format!("sugar-dlib-option-neg-test-{}", std::process::id()));
        std::fs::create_dir_all(&witness_dir).ok();

        let wrong_predicate = verify_one_claim(
            &dlib_option_expect_callsite("serde_json_to_string_value", DLIB_OPTION_EXPECT_CID),
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            &witness_dir,
            &VERIFY_SIGNER_SEED_DEV,
            false,
        );
        assert_ne!(
            wrong_predicate.verdict,
            ObligationVerdict::Discharged,
            "post=is_ok(result) must not discharge pre=is_some(receiver); reason: {}",
            wrong_predicate.reason
        );
        assert_ne!(
            wrong_predicate.discharge_method.as_deref(),
            Some("panic-safe"),
            "wrong-predicate control must never be tagged panic-safe; reason: {}",
            wrong_predicate.reason
        );

        let wrong_receiver = verify_one_claim(
            &dlib_option_expect_callsite(
                "grammar_op_registry_cid_known",
                DLIB_OPTION_EXPECT_MISMATCH_CID,
            ),
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            &witness_dir,
            &VERIFY_SIGNER_SEED_DEV,
            false,
        );
        assert_ne!(
            wrong_receiver.verdict,
            ObligationVerdict::Discharged,
            "post=is_some(actual_receiver) must not discharge pre=is_some(other_receiver); reason: {}",
            wrong_receiver.reason
        );
        assert_ne!(
            wrong_receiver.discharge_method.as_deref(),
            Some("panic-safe"),
            "wrong-receiver control must never be tagged panic-safe; reason: {}",
            wrong_receiver.reason
        );

        let _ = std::fs::remove_dir_all(&witness_dir);
    }

    #[test]
    fn signer_seed_hex_override_decodes_and_is_authoritative() {
        // An override seed decodes to 32 bytes and is marked authoritative.
        let hex = "ab".repeat(32);
        let seed = decode_seed_hex(&hex).expect("valid 64-hex seed decodes");
        assert_eq!(seed, [0xabu8; 32]);
        // 0x-prefixed accepted; wrong length rejected.
        assert_eq!(decode_seed_hex(&format!("0x{hex}")).unwrap(), [0xabu8; 32]);
        assert!(decode_seed_hex("dead").is_err());
        assert!(decode_seed_hex(&"zz".repeat(32)).is_err());
    }
}
