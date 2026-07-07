// SPDX-License-Identifier: MIT OR Apache-2.0

pub mod canonical;
pub mod compose;
pub mod core;
pub mod ffi;
pub mod panic_freedom;
pub mod wp;

#[derive(Debug, thiserror::Error)]
pub enum SugarError {
    #[error("{0}")]
    Message(String),
}

pub type Result<T> = std::result::Result<T, SugarError>;
