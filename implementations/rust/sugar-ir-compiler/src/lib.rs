// SPDX-License-Identifier: Apache-2.0
//
// IR compiler protocol core. Defines the trait every compiler
// implements, the registry that dispatches by dialect name, the
// JSON-RPC subprocess client used for plugins, and the manifest
// loader that walks ~/.config/sugar/ir-compilers/.
//
// Spec: protocol/specs/2026-04-30-ir-compiler-protocol.md.

pub mod error;
pub mod frontend;
pub mod manifest;
pub mod registry;
pub mod server;
pub mod subprocess;

use serde::{Deserialize, Serialize};
use serde_json::Value as Json;

pub use error::CompileError;
pub use frontend::{
    BinaryProofIrFrontend, CompiledFormulaFieldPath, CompilerInput, EquationalEquation,
    EquationalOperator, EquationalSubsort, EquationalTheory, EquationalTheoryObligation,
    EquationalVariable, FrontendError, FrontendErrorKind, FrontendErrorPayload,
    FrontendProvenancePolicy,
};

/// Result of compiling one canonical IR-JSON formula to a target
/// dialect. Wire-equivalent to the JSON returned by
/// `sugar.ir.compile`.
///
/// Contract: `preamble + body` is the complete script the verifier
/// hands to the solver.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CompiledFormula {
    /// Logic declaration plus all `declare-const` (or dialect-equivalent)
    /// lines for free variables.
    pub preamble: String,
    /// The obligation assertion plus the dialect's driver terminator
    /// (e.g. `(check-sat)\n` for SMT-LIB).
    pub body: String,
    /// Free variables the compiler had to declare in `preamble`. Sort
    /// strings are dialect-native.
    pub free_vars: Vec<FreeVar>,
    /// Opacity manifest recording positions the compiler could not
    /// soundly translate. Empty when all positions were handled.
    #[serde(default)]
    pub opacity_manifest: OpacityManifest,
    /// Dialect-specific structured compiler metadata. Solver adapters
    /// that need more than the emitted source (for example Maude's CeTA
    /// TRS input) read it here instead of recompiling ProofIR.
    #[serde(default)]
    pub metadata: Json,
}

impl CompiledFormula {
    pub fn script(&self) -> String {
        format!("{}{}", self.preamble, self.body)
    }
}

/// Opacity manifest emitted alongside a compiled formula. Records
/// every IR position the compiler marked opaque (replaced with a
/// dialect-specific trust-me placeholder).
#[derive(Debug, Clone, PartialEq, Eq, Default, Serialize, Deserialize)]
pub struct OpacityManifest {
    #[serde(rename = "protocolVersion")]
    pub protocol_version: String,
    pub compiler: String,
    #[serde(rename = "compilerVersion")]
    pub compiler_version: String,
    pub opacities: Vec<OpacityEntry>,
}

/// One opaque position recorded in an OpacityManifest.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OpacityEntry {
    #[serde(rename = "positionCid")]
    pub position_cid: String,
    #[serde(rename = "reasonCode")]
    pub reason_code: String,
}

/// One declared free variable in the compiled output.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FreeVar {
    pub name: String,
    pub sort: String,
}

/// Capability descriptor returned by `sugar.ir.handshake`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Capabilities {
    pub name: String,
    pub version: String,
    pub protocol_version: String,
    pub dialects: Vec<String>,
    pub supported_sorts: Vec<String>,
    pub supported_predicates: Vec<String>,
}

/// Canonical protocol identifier, used in handshake and manifests.
pub const PROTOCOL_VERSION: &str = "sugar-ir-compiler/1";

impl From<FrontendError> for CompileError {
    fn from(error: FrontendError) -> Self {
        CompileError::Frontend(error.payload)
    }
}

/// The trait every IR compiler implements, whether it lives in-process
/// or speaks JSON-RPC over a subprocess pipe.
pub trait IrCompiler: Send + Sync {
    /// Translate one typed ProofIR compiler input to the target dialect.
    fn compile_typed(
        &self,
        ir: &CompilerInput,
        dialect: &str,
    ) -> Result<CompiledFormula, CompileError>;

    /// Capability descriptor: dialects served, sorts and predicates
    /// supported. Cached by the registry on insert.
    fn capabilities(&self) -> Capabilities;
}
