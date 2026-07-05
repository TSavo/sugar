// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Compile error model. One enum, one numeric code per variant, mapped
// to the JSON-RPC error codes in the spec.

use thiserror::Error;

use crate::frontend::FrontendErrorPayload;

/// Errors a compiler may raise. Numeric codes correspond to the table
/// in protocol/specs/2026-04-30-ir-compiler-protocol.md.
#[derive(Debug, Error)]
pub enum CompileError {
    /// The plugin does not serve the requested dialect.
    #[error("unsupported dialect: {0}")]
    UnsupportedDialect(String),

    /// The IR uses a sort the dialect cannot express.
    #[error("unsupported sort: {0}")]
    UnsupportedSort(String),

    /// The IR uses an atomic predicate the dialect cannot express.
    #[error("unsupported predicate: {0}")]
    UnsupportedPredicate(String),

    /// The IR-JSON does not parse against the formal grammar.
    #[error("malformed IR: {0}")]
    MalformedIr(String),

    /// The typed frontend adapter rejected a legacy transport input.
    #[error("frontend decode error: {0}")]
    Frontend(FrontendErrorPayload),

    /// Compiler bug; recoverable only by switching compilers.
    #[error("internal compiler error: {0}")]
    Internal(String),

    /// JSON-RPC transport failure (subprocess only).
    #[error("transport error: {0}")]
    Transport(String),
}

impl CompileError {
    /// JSON-RPC numeric error code for this variant.
    pub fn code(&self) -> i32 {
        match self {
            CompileError::UnsupportedDialect(_) => 2000,
            CompileError::UnsupportedSort(_) => 2001,
            CompileError::UnsupportedPredicate(_) => 2002,
            CompileError::MalformedIr(_) => 2003,
            CompileError::Frontend(_) => 2003,
            CompileError::Internal(_) => 2004,
            CompileError::Transport(_) => -32603,
        }
    }

    /// Symbolic name from the spec table.
    pub fn symbolic(&self) -> &'static str {
        match self {
            CompileError::UnsupportedDialect(_) => "compile_error.unsupported_dialect",
            CompileError::UnsupportedSort(_) => "compile_error.unsupported_sort",
            CompileError::UnsupportedPredicate(_) => "compile_error.unsupported_predicate",
            CompileError::MalformedIr(_) => "compile_error.malformed_ir",
            CompileError::Frontend(_) => "compile_error.frontend_decode",
            CompileError::Internal(_) => "compile_error.internal",
            CompileError::Transport(_) => "transport_error",
        }
    }
}
