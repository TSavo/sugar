// SPDX-License-Identifier: Apache-2.0
//
// Standalone JSON-RPC subprocess binary for the bundled SMT-LIB v2.6 compiler.

use sugar_ir_compiler::server::serve_stdio;
use sugar_ir_compiler_smt_lib::SmtLibCompiler;

fn main() {
    serve_stdio(SmtLibCompiler::new());
}
