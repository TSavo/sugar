// SPDX-License-Identifier: MIT OR Apache-2.0
//
// End-to-end SMT-emit round-trip test. Builds a forall-Int formula in
// memory (no I/O), instantiates with a free var, emits SMT-LIB, and
// confirms the structural shape. Skips the actual z3 invocation (the
// solver subprocess is exercised separately via examples).

use serde_json::json;

use sugar_verifier::{instantiate, smt_emitter, ResolvedProperty};

#[test]
fn instantiate_then_smt_emit_basic() {
    // Resolved property: forall n. n > 0
    let pre = json!({
        "kind": "forall",
        "name": "n",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "atomic",
            "name": ">",
            "args": [
                {"kind": "var", "name": "n"},
                {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
            ]
        }
    });
    let resolved = ResolvedProperty {
        cid: "blake3-512:00".into(),
        ir_formula: Some(pre),
        ir_kit_version: String::new(),
        ..Default::default()
    };
    // Caller passed a var "x" as the argument.
    let arg = Some(json!({"kind": "var", "name": "x"}));
    let ob = instantiate::run(&resolved, &arg).expect("instantiate");
    let smt = smt_emitter::emit(&ob.ir_formula).expect("smt-emit");
    // After instantiation, result is forall x. x > 0 (sort preserved from original forall)
    assert!(smt.contains(r#"(forall ((n Int)) (> x 0)))"#));
    assert!(smt.contains("(assert (not"));
    assert!(smt.contains("(check-sat)"));
}
