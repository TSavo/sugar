// SPDX-License-Identifier: Apache-2.0
//
// Standalone JSON-RPC subprocess binary for the bundled Coq compiler.

use sugar_ir_compiler::server::serve_stdio;
use sugar_ir_compiler_coq::CoqCompiler;

fn main() {
    serve_stdio(CoqCompiler::new());
}
