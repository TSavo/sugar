// SPDX-License-Identifier: Apache-2.0
//
// sugar-cli: user-facing CLI binary.
//
// Pure routing crate: parses argv via clap, dispatches into the
// existing workspace crates (canonicalizer, proof-envelope,
// claim-envelope, ir-symbolic, verifier). Nothing crypto-load-bearing
// is implemented here; this is the seam between humans and libs.
//
// Exit codes:
//   0 success
//   1 verification failure
//   2 user error (bad args, file not found)
//   3 solver failure (z3 unavailable / timeout)

use std::path::PathBuf;
use std::process::ExitCode;

use clap::{Parser, Subcommand};

mod cmd_bind;
mod cmd_compose;
mod cmd_diff;
mod cmd_doctor;
mod cmd_dump;
mod cmd_emit;
mod cmd_hash;
mod cmd_implicate;
mod cmd_init;
mod cmd_lift;
mod cmd_materialize;
mod cmd_mint;
mod cmd_model;
mod cmd_package;
mod cmd_plugin;
mod cmd_prove;
mod cmd_recognize;
mod cmd_release_gate;
mod cmd_self_check;
mod cmd_verify;
mod cmd_version;
mod doctor;
mod doctor_oracle;
pub mod floor_runtime_check;
mod kit_declaration;
mod kit_dispatch;
mod lift_plugin;
pub mod panic_annotations_runtime;
mod project_config;
mod report_fmt;
mod witness_verify;

/// Exit codes used across subcommands.
pub const EXIT_OK: u8 = 0;
pub const EXIT_VERIFY_FAIL: u8 = 1;
pub const EXIT_USER_ERROR: u8 = 2;
pub const EXIT_SOLVER_FAIL: u8 = 3;

#[derive(Parser, Debug)]
#[command(
    name = "sugar",
    version,
    about = "Sugar CLI: per-codebase invariant enforcement at git-commit speed.",
    long_about = "Sugar CLI. Walk .proof catalogs, verify property mementos, \
mint implications, hash content. Each subcommand wraps an existing \
Sugar Rust library; the CLI is routing only."
)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

/// Common output flags. Each subcommand embeds these so users can pass
/// `--json` / `--quiet` after the subcommand name.
#[derive(Parser, Debug, Clone, Default)]
pub struct OutputFlags {
    /// Emit structured JSON instead of human-readable text.
    #[arg(long, global = true)]
    pub json: bool,
    /// Suppress non-error output.
    #[arg(long, global = true)]
    pub quiet: bool,
}

/// PEP 1.7.0 plugin flags.  Embed in any subcommand that participates in the
/// plugin registry (§7 / §9).  The registry seals once per run; every output's
/// provenance MUST cite the registry CID (§9.4).
///
/// Flag catalogue (§7):
///   --plugin <kind>:<source>     canonical form
///   --sugar <source>             alias for --plugin sugar:<source>
///   --loss-fn <source>           alias for --plugin loss-function:<source>
///   --lifter <source>            alias for --plugin lift:<source>  (wire kind = "lift")
///   --no-default-plugins         legacy no-op; no implicit plugins exist
///   --no-default-plugin <kind>   legacy no-op; no implicit plugins exist
///   --strict-plugins             promote every plugin load failure to a refuse
///   --plugin-registry-out <path> write PluginRegistryMemento to <path> after sealing
pub use cmd_plugin::PluginFlags;

#[derive(Subcommand, Debug)]
enum Cmd {
    /// Run the six-stage verifier: load proofs, enumerate callsites, solve obligations, report.
    Prove(ProveArgs),
    /// Run the deterministic self-application scoreboard.
    SelfCheck(cmd_self_check::SelfCheckArgs),
    /// Inspect package artifacts and supply-chain receipt inputs.
    Package(cmd_package::PackageArgs),
    /// Verify a kit end-to-end: lift its contract claims, discharge each
    /// via the solver-dispatch table, mint a signed witness citing the
    /// discharging solver, and emit a per-claim verification receipt.
    /// This is the real GATE verb (#1405); distinct from `prove` (the
    /// six-stage prover).
    Verify(cmd_verify::VerifyArgs),
    /// Behavior diff between two minted proof sets: report contracts that
    /// changed CID (behavior moved), were added, or removed. The CID is the
    /// name-stripped behavior identity, so a rename shows `unchanged`. Exits
    /// nonzero when behavior moved or surface dropped.
    Diff(cmd_diff::DiffArgs),
    /// Mint an implication memento (antecedent CID -> consequent CID) via Z3.
    Implicate(ImplicateArgs),
    /// Short alias for `implicate`.
    Imp(ImplicateArgs),
    /// Pretty-print a .proof envelope: members, bodies, signatures.
    Dump(DumpArgs),
    /// Compute the BLAKE3-512 self-identifying CID of a file (or stdin).
    Hash(HashArgs),
    /// Recognizer (per protocol §4.2.5): scan source for shapes that
    /// match published sugar binding templates; emit tags. The reverse
    /// direction of `materialize` — same kit, same AST machinery, two
    /// directions over one .proof envelope. Tron-named for the kit-side
    /// fingerprint scanner.
    Recognize(cmd_recognize::RecognizeArgs),
    /// Initialize a project: sugar.toml, .sugar/, sample invariant, GitHub Action.
    Init(InitArgs),
    /// Dispatch the configured lift surface and write its ProofIR term JSON (no `.proof` envelope; use `mint` for that).
    Lift(LiftArgs),
    /// Dispatch the lift-plugin protocol: spawn the configured plugin, write its `.proof`.
    Mint(cmd_mint::MintArgs),
    /// Emit target/framework test artifacts from neutral contract predicates.
    Emit(cmd_emit::EmitArgs),
    /// Print CLI version.
    Version(VersionArgs),
    /// JSON-RPC subprocess transport for the canonical compose primitive.
    /// Per spec protocol/specs/2026-05-09-contract-composition-protocol.md §6.3.
    /// Reads JSON-RPC requests on stdin, writes responses on stdout.
    Compose(ComposeArgs),
    /// Bind concept contracts to source code: lift, cluster, name, scope, identify, realize, witness.
    /// Implements the eight-verb pipeline (paper 20 §9) against arbitrary user code.
    /// --rewrite={annotate,canonical,invisible} --mode={witness,emitter,monitor,gate} --target-language=<lang>
    Bind(cmd_bind::BindArgs),
    /// Materialize source-oracle bodies by resolving real source by reference.
    Materialize(cmd_materialize::MaterializeArgs),
    /// Validate a kit's config/manifest wiring before a run. Catches missing
    /// binaries (the manifest-path footgun) before they silently produce an
    /// empty-set attestation. Exit 0 on pass (warnings allowed), exit 2 on any
    /// hard failure (invalid TOML or missing/non-executable binary).
    Doctor(cmd_doctor::DoctorArgs),
    /// Run the v1 release health gate and emit a release evidence receipt.
    ReleaseGate(cmd_release_gate::ReleaseGateArgs),
    /// Derive a concrete output from a lifted universe BV expression via z3 model extraction.
    ///
    /// Reads the walked universe body from a minted .proof (`--from-proof`, the
    /// int32.eq-bv-expr atom's bv_tree) or an extracted bv_tree JSON (`--bv-expr`),
    /// then asks z3 what the definition COMPUTES via `(get-value)`. Derived, not
    /// executed. No built-in formula: the lift is the only source of truth.
    ///
    /// Flagship: abs(Integer.MIN_VALUE) = -2147483648, derived from the lifted Math.abs body.
    Derive(cmd_model::ModelArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct ProveArgs {
    /// Project root to scan for .proof files. Defaults to the current directory.
    pub project: Option<PathBuf>,
    /// Path to z3 binary (default: "z3" on PATH).
    #[arg(long, default_value = "z3")]
    pub z3: String,
    /// Artifact bytes to verify against a package release proof/receipt.
    #[arg(long, requires = "proof")]
    pub artifact: Option<PathBuf>,
    /// Package release proof/receipt naming the expected binaryCid.
    #[arg(long)]
    pub proof: Option<PathBuf>,
    /// Consumer policy proof/receipt used for policy admission checks.
    #[arg(long, requires = "proof")]
    pub policy: Option<PathBuf>,
    /// Require that a concept has reached the empirically-witnessed promotion tier.
    #[arg(long = "require-empirically-witnessed")]
    pub require_empirically_witnessed: Option<String>,
    /// Fixture-state CID for tier queries such as --require-empirically-witnessed.
    #[arg(long = "require-fixture")]
    pub require_fixture: Option<String>,
    /// Consensus policy JSON used to evaluate a required empirical witness vector.
    #[arg(long = "consensus-policy", requires = "require_empirically_witnessed")]
    pub consensus_policy: Option<PathBuf>,
    #[command(flatten)]
    pub out: OutputFlags,
    /// Additional project directories whose .proof files should also be loaded
    /// (e.g., an OpenAPI spec project for cross-kit verification).
    #[arg(long = "with", num_args = 0..)]
    pub with: Vec<String>,
}

#[derive(Parser, Debug, Clone)]
pub struct ImplicateArgs {
    /// Antecedent memento CID (full self-identifying string).
    pub antecedent: String,
    /// Consequent memento CID (full self-identifying string).
    pub consequent: String,
    /// Path to z3 binary (default: "z3" on PATH).
    #[arg(long, default_value = "z3")]
    pub z3: String,
    #[command(flatten)]
    pub out: OutputFlags,
}

#[derive(Parser, Debug, Clone)]
pub struct DumpArgs {
    /// Path to a .proof file.
    pub proof_file: PathBuf,
    #[command(flatten)]
    pub out: OutputFlags,
}

#[derive(Parser, Debug, Clone)]
pub struct HashArgs {
    /// File to hash. Reads stdin when omitted.
    pub file: Option<PathBuf>,
    #[command(flatten)]
    pub out: OutputFlags,
}

#[derive(Parser, Debug, Clone)]
pub struct InitArgs {
    /// Project directory to initialize. Defaults to current directory.
    pub project: Option<PathBuf>,
    /// Overwrite any pre-existing files.
    #[arg(long)]
    pub force: bool,
    #[command(flatten)]
    pub out: OutputFlags,
}

#[derive(Parser, Debug, Clone)]
pub struct LiftArgs {
    /// Project root to lift. Defaults to the current directory.
    pub project: Option<PathBuf>,
    /// Output file. Writes stdout when omitted or `-`.
    #[arg(short = 'o', long = "output")]
    pub output: Option<PathBuf>,
    /// Ask the configured lifter to report native contract identities without full ProofIR lowering.
    #[arg(long, conflicts_with = "library_bindings")]
    pub identify_only: bool,
    /// Ask the configured lifter for proof-producing host-language library-sugar bindings.
    #[arg(long, conflicts_with = "identify_only")]
    pub library_bindings: bool,
    /// Print the lifter's source-audit countdown instead of the raw ProofIR term JSON.
    #[arg(long, conflicts_with_all = ["output", "identify_only", "library_bindings"])]
    pub report: bool,
    /// Restrict --report to source audits whose contract name contains this string.
    #[arg(long = "contract", requires = "report")]
    pub contract: Option<String>,
    #[command(flatten)]
    pub out: OutputFlags,
}

#[derive(Parser, Debug, Clone)]
pub struct VersionArgs {
    #[command(subcommand)]
    pub cmd: Option<cmd_version::VersionCmd>,
    #[command(flatten)]
    pub out: OutputFlags,
}

#[derive(Parser, Debug, Clone)]
pub struct ComposeArgs {
    /// Speak JSON-RPC over stdin / stdout. Required today; the only
    /// transport the CCP §6.3 binding mode defines.
    #[arg(long)]
    pub rpc: bool,
    #[command(flatten)]
    pub out: OutputFlags,
}

fn main() -> ExitCode {
    // Structured logging to stderr. Default level: warn, so a bare
    // `sugar mint`/`prove` run is silent. Override via RUST_LOG:
    //   RUST_LOG=info   -> pipeline narrative
    //   RUST_LOG=debug  -> per-item decisions
    //   RUST_LOG=trace  -> RPC payloads, RA queries
    init_tracing();
    let cli = Cli::parse();
    let code = match cli.cmd {
        Cmd::Prove(a) => cmd_prove::run(a),
        Cmd::SelfCheck(a) => cmd_self_check::run(a),
        Cmd::Verify(a) => cmd_verify::run(a),
        Cmd::Diff(a) => cmd_diff::run(a),
        Cmd::Package(a) => cmd_package::run(a),
        Cmd::Implicate(a) | Cmd::Imp(a) => cmd_implicate::run(a),
        Cmd::Dump(a) => cmd_dump::run(a),
        Cmd::Hash(a) => cmd_hash::run(a),
        Cmd::Recognize(a) => cmd_recognize::run(a),
        Cmd::Init(a) => cmd_init::run(a),
        Cmd::Lift(a) => cmd_lift::run(a),
        Cmd::Mint(a) => cmd_mint::run(a),
        Cmd::Emit(a) => cmd_emit::run(a),
        Cmd::Version(a) => cmd_version::run(a),
        Cmd::Compose(a) => cmd_compose::run(a),
        Cmd::Bind(a) => cmd_bind::run(a),
        Cmd::Materialize(a) => cmd_materialize::run(a),
        Cmd::Doctor(a) => cmd_doctor::run(a),
        Cmd::ReleaseGate(a) => cmd_release_gate::run(a),
        Cmd::Derive(a) => cmd_model::run(a),
    };
    ExitCode::from(code)
}

fn init_tracing() {
    // The pipeline is richly instrumented at info!/debug! (per-stage counts,
    // ambient-forall totals, "consistency pass complete: consistent/contradictory/
    // undecidable", etc.). Defaulting the whole world to WARN hid all of it and
    // made `sugar verify` a black box. Default OUR crates to info (the stage
    // narrative) while third-party deps stay at warn; RUST_LOG fully overrides.
    let filter = if std::env::var_os("RUST_LOG").is_some() {
        tracing_subscriber::EnvFilter::builder()
            .with_default_directive(tracing_subscriber::filter::LevelFilter::WARN.into())
            .from_env_lossy()
    } else {
        tracing_subscriber::EnvFilter::new(
            "warn,\
             sugar_cli=info,\
             sugar_verifier=info,\
             sugar_walk=info,\
             sugar_lift=info,\
             sugar_lift_rust_tests=info,\
             libsugar=info",
        )
    };
    if let Ok(path) = std::env::var("SUGAR_LOG_FILE") {
        match std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
        {
            Ok(file) => {
                tracing_subscriber::fmt()
                    .with_writer(file)
                    .with_ansi(false)
                    .with_env_filter(filter)
                    .init();
            }
            Err(error) => {
                eprintln!(
                    "warning: could not open SUGAR_LOG_FILE {path}: {error}; logging to stderr"
                );
                tracing_subscriber::fmt()
                    .with_writer(std::io::stderr)
                    .with_env_filter(filter)
                    .init();
            }
        }
    } else {
        tracing_subscriber::fmt()
            .with_writer(std::io::stderr)
            .with_env_filter(filter)
            .init();
    }
}
