// SPDX-License-Identifier: MIT OR Apache-2.0

#[path = "../../sugar-ir-compiler-test-support/vocabulary.rs"]
mod vocabulary;

use vocabulary::{
    audit_row, collect_corpus, formula_json_for, BackendReport, CorpusSymbol, Disposition,
    SymbolPosition,
};

use sugar_ir_compiler::{CompilerInput, IrCompiler};
use sugar_ir_compiler_lean::{LeanCompiler, DIALECT};

// #3468 reconciliation: the post-b240323de corpus additions below are
// legitimate red-pinned vocabulary, not leaks. `call:A` comes from the verifier
// ambient-testimony fixtures in 728d61877; the serde_json/panic/ref rows come
// from checked-in serde showcase re-mint artifacts in 98b8c34d5.
const EXPECTED_RED: &[(&str, &str, usize)] = &[
    ("atom", "<predicate>", 1),
    ("atom", "CategoryTheory.Functor.map_id", 0),
    ("atom", "bvadd", 0),
    ("atom", "bvadd", 2),
    ("atom", "call-site-obligation", 1),
    ("atom", "caller_post", 0),
    ("atom", "checked_add_u8.postcondition", 0),
    ("atom", "concept:eq", 2),
    ("atom", "consumer", 0),
    ("atom", "demo_true", 0),
    ("atom", "domain.opaque", 1),
    ("atom", "equational_theory", 0),
    ("atom", "is-null", 1),
    ("atom", "is_err", 1),
    ("atom", "is_ok", 1),
    ("atom", "is_some", 0),
    ("atom", "is_some", 1),
    ("atom", "length", 0),
    ("atom", "length", 1),
    ("atom", "lower_holds", 0),
    ("atom", "observed", 1),
    ("atom", "p", 0),
    ("atom", "p", 1),
    ("atom", "panic", 1),
    ("atom", "panic-free", 1),
    ("atom", "path_config_true", 0),
    ("atom", "producer", 0),
    ("atom", "producer_post", 0),
    ("atom", "producer_pre", 0),
    ("atom", "q", 0),
    ("atom", "qualified_post", 0),
    ("atom", "ready", 0),
    ("atom", "roundTrips", 1),
    ("atom", "same_leaf_post", 0),
    ("atom", "str.chars-in-set", 0),
    ("atom", "str.eq-bv-blocks", 2),
    ("atom", "str.eq-bv-blocks", 3),
    ("atom", "str.in-regex", 0),
    ("atom", "str.in-regex", 2),
    ("atom", "totally.unknown.op", 1),
    ("atom", "unknown", 0),
    ("atom", "upper_holds", 0),
    ("atom", "witnessed", 0),
    ("ctor", "%", 2),
    ("ctor", "Arc", 1),
    ("ctor", "Bool", 0),
    ("ctor", "Box", 1),
    ("ctor", "Int", 0),
    ("ctor", "MyError", 0),
    ("ctor", "MyType", 0),
    ("ctor", "None", 0),
    ("ctor", "Ok", 1),
    ("ctor", "Option", 1),
    ("ctor", "Option::unwrap_value", 1),
    ("ctor", "Point", 0),
    ("ctor", "Result", 2),
    ("ctor", "Some", 1),
    ("ctor", "String", 0),
    ("ctor", "Value", 0),
    ("ctor", "Vec", 1),
    ("ctor", "a", 0),
    ("ctor", "answer", 0),
    ("ctor", "atoi", 0),
    ("ctor", "await", 1),
    ("ctor", "b", 0),
    ("ctor", "bad token", 0),
    ("ctor", "bv32.add", 2),
    ("ctor", "bv32.and", 2),
    ("ctor", "bv32.ite", 3),
    ("ctor", "bv32.lshr", 2),
    ("ctor", "bv32.neg", 1),
    ("ctor", "bv32.shl", 2),
    ("ctor", "bv32.slt", 2),
    ("ctor", "bv32.xor", 2),
    ("ctor", "c", 0),
    ("ctor", "c:callresult_enc_a1", 1),
    ("ctor", "call:A", 0),
    ("ctor", "call:BooleanDtype", 0),
    ("ctor", "call:abs", 1),
    ("ctor", "call:answer", 0),
    ("ctor", "call:async_value", 0),
    ("ctor", "call:callee", 1),
    ("ctor", "call:enc", 1),
    ("ctor", "call:encode", 1),
    ("ctor", "call:encodeBase64String", 1),
    ("ctor", "call:encode_len", 1),
    ("ctor", "call:encoded_len", 2),
    ("ctor", "call:encoded_len#panic_callsite", 2),
    ("ctor", "call:f", 0),
    ("ctor", "call:f", 1),
    ("ctor", "call:g", 0),
    ("ctor", "call:make_value", 0),
    ("ctor", "call:new", 2),
    ("ctor", "call:serde_json::to_string", 1),
    ("ctor", "call:serde_json::to_string#panic_callsite", 1),
    ("ctor", "call:update", 0),
    ("ctor", "callval___repr___a1", 1),
    ("ctor", "cf_gt", 2),
    ("ctor", "cf_ite", 3),
    ("ctor", "channel:recv:rx", 1),
    ("ctor", "concept:add", 3),
    ("ctor", "concept:eq", 2),
    ("ctor", "concept:mul", 2),
    ("ctor", "concept:panic-freedom.result.ok", 1),
    ("ctor", "concept:sub", 2),
    ("ctor", "consumer", 1),
    ("ctor", "d", 0),
    ("ctor", "f", 0),
    ("ctor", "f", 1),
    ("ctor", "kit:floordiv", 2),
    ("ctor", "method:expect", 1),
    ("ctor", "method:to_digit", 2),
    ("ctor", "method:unwrap", 1),
    ("ctor", "method:unwrap#panic_callsite", 1),
    ("ctor", "method:y", 1),
    ("ctor", "mutex:guard:m", 1),
    ("ctor", "option_expect", 1),
    ("ctor", "option_unwrap", 1),
    ("ctor", "parseInt", 0),
    ("ctor", "parseInt", 1),
    ("ctor", "parse_int", 1),
    ("ctor", "plus", 2),
    ("ctor", "produce_zero", 0),
    ("ctor", "producer", 0),
    ("ctor", "python:attribute", 2),
    ("ctor", "python:floordiv", 2),
    ("ctor", "python:subscript", 2),
    ("ctor", "ref", 1),
    ("ctor", "requires_positive", 1),
    ("ctor", "result_unwrap", 1),
    ("ctor", "return", 1),
    ("ctor", "s", 1),
    ("ctor", "sumCredits", 1),
    ("ctor", "sumDebits", 1),
    ("ctor", "to_string", 1),
    ("ctor", "to_value", 1),
    ("ctor", "wrap", 1),
    ("ctor", "zero", 0),
    ("ctor", "≠", 2),
];

fn report() -> BackendReport {
    let corpus = collect_corpus(env!("CARGO_MANIFEST_DIR")).expect("collect IR vocabulary corpus");
    let rows = corpus
        .symbols
        .iter()
        .map(|symbol| {
            let ir = formula_json_for(symbol);
            let input = CompilerInput::decode_json(ir).expect("vocabulary formula fixture decodes");
            match LeanCompiler::new().compile_typed(&input, DIALECT) {
                Ok(_) if lean_encoded(symbol) => audit_row(
                    symbol,
                    Disposition::Encoded,
                    "Lean builtin/operator encoding",
                ),
                Ok(_) => audit_row(
                    symbol,
                    Disposition::RedPinned,
                    "compiled as uninterpreted Lean without an allowlist entry",
                ),
                Err(err) => audit_row(symbol, Disposition::Refused, err.to_string()),
            }
        })
        .collect();
    BackendReport::new("lean", &corpus, rows)
}

fn lean_encoded(symbol: &CorpusSymbol) -> bool {
    match symbol.key.position {
        SymbolPosition::Atom => matches!(
            symbol.key.name.as_str(),
            "true"
                | "false"
                | "eq"
                | "="
                | "ne"
                | "neq"
                | "!="
                | "\u{2260}"
                | "lt"
                | "<"
                | "lte"
                | "<="
                | "\u{2264}"
                | "gt"
                | ">"
                | "gte"
                | ">="
                | "\u{2265}"
        ),
        SymbolPosition::Ctor => matches!(symbol.key.name.as_str(), "+" | "-" | "*"),
    }
}

#[test]
fn lean_vocabulary_totality_matches_expected_frontier() {
    let report = report();
    let observed = report.red_keys();
    assert_eq!(
        observed,
        EXPECTED_RED,
        "Lean vocabulary frontier changed\n{}\n\nPasteable EXPECTED_RED:\n{}",
        report.to_json(),
        report.to_expected_red_literal("EXPECTED_RED")
    );
}

#[test]
fn lean_vocabulary_totality_report() {
    let report = report();
    eprintln!("{}", report.to_json());
    assert_eq!(report.red_keys(), EXPECTED_RED, "{}", report.to_json());
    if !EXPECTED_RED.is_empty() {
        assert!(
            !report.is_zero(),
            "frontier unexpectedly reached stable zero"
        );
    }
}

#[test]
#[ignore = "red target: run with --ignored after encoding/allowlist drains to require stable zero"]
fn lean_vocabulary_totality_stable_zero_target() {
    let report = report();
    assert!(report.is_zero(), "{}", report.to_json());
}
