use serde_json::json;
use sugar_ir_compiler::{CompilerInput, IrCompiler};
use sugar_ir_compiler_coq::CoqCompiler;

fn main() {
    let compiler = CoqCompiler::new();

    // Simple formula
    let ir = json!({
        "kind": "atomic",
        "name": "roundTrips",
        "args": [{"kind": "var", "name": "s"}]
    });

    let input = CompilerInput::decode_json(ir).unwrap();
    let result = compiler.compile_typed(&input, "coq").unwrap();

    println!("=== PREAMBLE ===");
    println!("{}", result.preamble);
    println!("=== BODY ===");
    println!("{}", result.body);
    println!("=== FREE VARS ===");
    println!("{:?}", result.free_vars);
}
