// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Standalone JSON-RPC subprocess binary for the bundled Maude compiler.

use sugar_ir_compiler::server::serve_stdio;
use sugar_ir_compiler_maude::MaudeCompiler;

fn main() {
    serve_stdio(MaudeCompiler::new());
}
