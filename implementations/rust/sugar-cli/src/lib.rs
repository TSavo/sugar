// SPDX-License-Identifier: MIT OR Apache-2.0
//
// sugar-cli library root.
//
// Exposes selected internal modules for integration-test access.
// The binary (src/main.rs) is the full CLI; this lib target provides
// the pub surface for test crates that need to call internal functions
// (e.g. realize_for_bind in the slice2 byte-identical integration test).
//
// Only the modules needed by integration tests are declared here.
// Adding a module here does NOT automatically add it to the CLI binary;
// main.rs has its own module list.

use clap::Parser;

/// Exit codes used across subcommands.
pub const EXIT_OK: u8 = 0;
pub const EXIT_VERIFY_FAIL: u8 = 1;
pub const EXIT_USER_ERROR: u8 = 2;
pub const EXIT_SOLVER_FAIL: u8 = 3;

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

pub mod cmd_release_gate;
pub mod cmd_self_check;
#[allow(dead_code)]
pub mod component_plan;
#[allow(dead_code)]
pub mod doctor;
#[allow(dead_code)]
pub mod doctor_oracle;
pub mod floor_runtime_check;
pub mod kit_declaration;
pub mod kit_dispatch;
#[allow(dead_code)]
pub mod lift_plugin;
pub mod panic_annotations_runtime;
pub mod project_config;
