// SPDX-License-Identifier: MIT OR Apache-2.0

pub mod canonical;
pub mod compose;
pub mod core;
pub mod desugar;
pub mod effect_propagation;
pub mod ffi;
pub mod panic_freedom;
pub mod policy_profile_registry;
pub mod transport;
pub mod witness_registry;
pub mod wp;

#[derive(Debug, thiserror::Error)]
pub enum SugarError {
    #[error("{0}")]
    Message(String),
}

pub type Result<T> = std::result::Result<T, SugarError>;
