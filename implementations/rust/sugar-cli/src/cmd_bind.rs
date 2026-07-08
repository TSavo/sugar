// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar bind`: substrate-only algebra pass.
//
// Input is ProofIR term JSON, normally the `ir-document` emitted by
// `sugar lift`. Output is the JCS-canonical named-term document for
// authoring and lower-plugin dispatch. The core BindKit still materializes the
// canonical bind-result Term::Op payload for path execution.
// Migration mode remains on the legacy rewrite path.

use std::io::{Read, Write};
use std::path::PathBuf;

use clap::Parser;
use libsugar::core::{
    address, ConformanceDeclaration, HashMapInputCatalog, Input, Path as CorePath, PathAlgebra,
    Term, Verb,
};
use owo_colors::OwoColorize;
use sugar_walk::{BindKit, BindOptions};
use serde_json::Value as Json;
use sugar_ir_types::{CompositionBoundaryMemento, Sort};

use crate::kit_path::{execute_path, KitRegistry, PathExecutionError};
use crate::{EXIT_OK, EXIT_USER_ERROR};

#[derive(Parser, Debug, Clone)]
pub struct BindArgs {
    /// ProofIR term JSON. Reads stdin when omitted or `-`.
    pub input: Option<PathBuf>,

    /// Output file. Writes stdout when omitted or `-`.
    #[arg(short = 'o', long = "output")]
    pub output: Option<PathBuf>,

    /// Source language hint for diagnostics and named-term metadata.
    #[arg(long, default_value = "auto")]
    pub lang: String,

    /// Legacy threshold hint. No effect in the four-verb model.
    #[arg(long, default_value = "1")]
    pub threshold: usize,

    /// Legacy rewrite flag. No effect in the four-verb model.
    #[arg(long, default_value = "invisible", value_parser = parse_rewrite)]
    pub rewrite: RewriteShape,

    /// Legacy observation mode flag. No effect in the four-verb model.
    #[arg(long, value_delimiter = ',', default_value = "monitor", value_parser = parse_mode)]
    pub mode: Vec<RuntimeMode>,

    /// Legacy target-language flag. Body lowering is retired; use `sugar emit`.
    #[arg(long)]
    pub target_language: Option<String>,

    /// Suppress non-error diagnostics.
    #[arg(long)]
    pub quiet: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RewriteShape {
    Annotate,
    Canonical,
    Invisible,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RuntimeMode {
    Monitor,
    Emitter,
    Witness,
    Gate,
}

fn parse_rewrite(s: &str) -> Result<RewriteShape, String> {
    match s {
        "annotate" => Ok(RewriteShape::Annotate),
        "canonical" => Ok(RewriteShape::Canonical),
        "invisible" => Ok(RewriteShape::Invisible),
        other => Err(format!(
            "unknown rewrite shape '{other}'; expected annotate, canonical, or invisible"
        )),
    }
}

fn parse_mode(s: &str) -> Result<RuntimeMode, String> {
    match s {
        "monitor" => Ok(RuntimeMode::Monitor),
        "emitter" => Ok(RuntimeMode::Emitter),
        "witness" => Ok(RuntimeMode::Witness),
        "gate" => Ok(RuntimeMode::Gate),
        other => Err(format!(
            "unknown runtime mode '{other}'; expected monitor, emitter, witness, or gate"
        )),
    }
}

pub fn run(args: BindArgs) -> u8 {
    let raw = match read_input(args.input.as_ref()) {
        Ok(raw) => raw,
        Err(error) => {
            eprintln!("{}: {error}", "error".red().bold());
            return EXIT_USER_ERROR;
        }
    };
    let term_json: Json = match serde_json::from_slice(&raw) {
        Ok(value) => value,
        Err(error) => {
            eprintln!("{}: parse ProofIR term JSON: {error}", "error".red().bold());
            return EXIT_USER_ERROR;
        }
    };
    let payload = match run_bind_path(term_json, &args) {
        Ok(payload) => payload,
        Err(error) => {
            eprintln!("{}: {error}", "error".red().bold());
            return EXIT_USER_ERROR;
        }
    };
    let jcs = match libsugar::canonical::json_jcs(&payload) {
        Ok(jcs) => jcs,
        Err(error) => {
            eprintln!(
                "{}: canonicalize named-term document: {error}",
                "error".red().bold()
            );
            return EXIT_USER_ERROR;
        }
    };
    if let Err(error) = write_output(args.output.as_ref(), jcs.as_bytes()) {
        eprintln!("{}: {error}", "error".red().bold());
        return EXIT_USER_ERROR;
    }
    if !args.quiet
        && args
            .output
            .as_ref()
            .is_some_and(|path| path.as_os_str() != "-")
    {
        eprintln!("bind: wrote named-term document");
    }
    EXIT_OK
}

fn run_bind_path(term_json: Json, args: &BindArgs) -> Result<Json, BindCliError> {
    let term = Term::Const {
        value: term_json,
        sort: Sort::Primitive {
            name: "LiftPluginResponse".to_string(),
        },
    };
    let term_cid = address(&term);
    let mut inputs = HashMapInputCatalog::default();
    inputs.put(term_cid.clone(), Input::Term(term));
    let path_input = Input::Path(Box::new(CorePath {
        algebra: vec![PathAlgebra {
            name: "bind".to_string(),
            kit: "bind-default".to_string(),
            inputs: vec![term_cid],
            depends_on: vec![],
            verb: Verb::Transform,
        }],
    }));
    let mut registry = KitRegistry::default();
    registry.register(
        "bind-default",
        BindKit::new(BindOptions {
            lang: args.lang.clone(),
        }),
        ConformanceDeclaration::NonCarrier {
            reason: "transforms Input::Term to NamedTerm DomainClaim; emits no target source",
        },
    );
    let chain = execute_path(&path_input, &registry, &inputs).map_err(BindCliError::from_path)?;
    let claim = chain.terminal_claim();
    let payload = claim
        .payload
        .as_ref()
        .ok_or_else(|| BindCliError::Failed("bind claim missing term payload".to_string()))?;
    serde_json::to_value(payload)
        .map_err(|error| BindCliError::Failed(format!("serialize bind payload: {error}")))
}

#[derive(Debug)]
enum BindCliError {
    Refused(Box<CompositionBoundaryMemento>),
    Failed(String),
}

impl BindCliError {
    fn from_path(error: PathExecutionError) -> Self {
        match error {
            PathExecutionError::Refused(refusal) => Self::Refused(refusal),
            other => Self::Failed(other.to_string()),
        }
    }
}

impl std::fmt::Display for BindCliError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Refused(refusal) => {
                f.write_str(&serde_json::to_string(refusal).unwrap_or_else(|_| {
                    format!(
                        "{}: {}",
                        refusal.header.failure_kind, refusal.header.failure_detail
                    )
                }))
            }
            Self::Failed(message) => f.write_str(message),
        }
    }
}

fn read_input(path: Option<&PathBuf>) -> Result<Vec<u8>, String> {
    match path {
        Some(path) if path.as_os_str() != "-" => {
            std::fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))
        }
        _ => {
            let mut bytes = Vec::new();
            std::io::stdin()
                .read_to_end(&mut bytes)
                .map_err(|e| format!("read stdin: {e}"))?;
            Ok(bytes)
        }
    }
}

fn write_output(path: Option<&PathBuf>, bytes: &[u8]) -> Result<(), String> {
    match path {
        Some(path) if path.as_os_str() != "-" => {
            std::fs::write(path, bytes).map_err(|e| format!("write {}: {e}", path.display()))
        }
        _ => {
            let mut stdout = std::io::stdout().lock();
            stdout
                .write_all(bytes)
                .map_err(|e| format!("write stdout: {e}"))
        }
    }
}
