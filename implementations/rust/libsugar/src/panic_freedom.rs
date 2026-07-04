// SPDX-License-Identifier: MIT OR Apache-2.0

//! Substrate identifiers for panic freedom: the bare Rust v1 wire tokens the
//! lifter emits and the verifier reads to prove a function cannot panic
//! (every panic leaf is reachable only under a matching guard predicate).
//!
//! The `concept:*` alias spellings and the alias-read normalization layer were
//! removed with the concept hub: there is one spelling per token, the bare one.

/// Panic-freedom result-ok guard predicate.
pub const IS_OK: &str = "is_ok";

/// Panic-freedom result-err guard predicate.
pub const IS_ERR: &str = "is_err";

/// Panic-freedom option-some guard predicate.
pub const IS_SOME: &str = "is_some";

/// Panic-freedom option-none guard predicate.
pub const IS_NONE: &str = "is_none";

/// Panic-freedom guarded-branch control carrier.
pub const CF_GUARDED: &str = "cf_guarded";

/// Panic-freedom control-flow choice carrier.
pub const CF_ITE: &str = "cf_ite";

/// Panic-freedom unwrap leaf.
pub const METHOD_UNWRAP: &str = "method:unwrap";

/// Panic-freedom expect leaf.
pub const METHOD_EXPECT: &str = "method:expect";

/// Panic-freedom unwrap-err leaf.
pub const METHOD_UNWRAP_ERR: &str = "method:unwrap_err";

/// Panic-freedom runtime-failure-site leaf (a Python runtime failure that has
/// no static guard). This is the one cross-kit token still carrying the
/// `concept:` spelling: the Python kit emits it, so it stays until the deferred
/// Python pass bares it in lockstep on both sides.
pub const RUNTIME_FAILURE_SITE: &str = "concept:panic-freedom.leaf.runtime-failure-site";
