// SPDX-License-Identifier: Apache-2.0
//
// Dialect-keyed registry. In-process Rust impls register here for the
// fast path; subprocess plugins discovered from manifests register the
// same way wrapped in JsonRpcCompiler.

use std::collections::HashMap;
use std::sync::Arc;

use crate::{CompileError, IrCompiler};

/// Registry of compilers, keyed by dialect identifier. A single
/// compiler that serves multiple dialects is registered once per
/// dialect (the `Arc` makes that cheap).
#[derive(Default, Clone)]
pub struct Registry {
    by_dialect: HashMap<String, Arc<dyn IrCompiler>>,
}

impl Registry {
    pub fn new() -> Self {
        Self::default()
    }

    /// Register `impl_` under every dialect listed in its capabilities.
    /// Returns the number of dialects registered.
    pub fn register(&mut self, impl_: Arc<dyn IrCompiler>) -> usize {
        let caps = impl_.capabilities();
        let n = caps.dialects.len();
        for d in caps.dialects {
            self.by_dialect.insert(d, impl_.clone());
        }
        n
    }

    /// Register `impl_` under one specific dialect. Useful in tests
    /// where the impl claims many dialects but you want exactly one.
    pub fn register_dialect(&mut self, dialect: &str, impl_: Arc<dyn IrCompiler>) {
        self.by_dialect.insert(dialect.to_string(), impl_);
    }

    /// Look up a compiler by dialect.
    pub fn get(&self, dialect: &str) -> Option<&Arc<dyn IrCompiler>> {
        self.by_dialect.get(dialect)
    }

    /// Dispatch a compile call. Returns `UnsupportedDialect` if no
    /// compiler is registered for this dialect.
    pub fn compile(
        &self,
        ir: &serde_json::Value,
        dialect: &str,
    ) -> Result<crate::CompiledFormula, CompileError> {
        match self.by_dialect.get(dialect) {
            Some(c) => c.compile(ir, dialect),
            None => Err(CompileError::UnsupportedDialect(dialect.to_string())),
        }
    }

    /// All registered dialect names. Order is unspecified.
    pub fn dialects(&self) -> Vec<String> {
        self.by_dialect.keys().cloned().collect()
    }
}
