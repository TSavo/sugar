// SPDX-License-Identifier: MIT OR Apache-2.0
//! Compatibility path for the Rust test assertion kit.
//!
//! The Rust SourceOracle lives in `sugar_walk::source_oracle`; this module keeps
//! older imports pointed at the single implementation.

pub use sugar_walk::source_oracle::*;
