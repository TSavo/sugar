// SPDX-License-Identifier: Apache-2.0

#[path = "../../sugar-ir-compiler-test-support/vocabulary.rs"]
mod vocabulary;

use vocabulary::{
    audit_row, collect_corpus, formula_json_for, BackendReport, CorpusSymbol, Disposition,
    SymbolPosition,
};

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
    ("ctor", "c", 0),
    ("ctor", "c:callresult_enc_a1", 1),
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

// No SMT-LIB uninterpreted pass-through is sanctioned here. Generic
// uninterpreted emissions stay red-pinned until a semantic review either
// implements a real encoding or adds a justified allowlist entry.
const SMT_UNINTERPRETED_ALLOWLIST: &[(&str, &str, &str)] = &[];

fn report() -> BackendReport {
    let corpus = collect_corpus(env!("CARGO_MANIFEST_DIR")).expect("collect IR vocabulary corpus");
    let rows = corpus
        .symbols
        .iter()
        .map(|symbol| {
            let ir = formula_json_for(symbol);
            match sugar_ir_compiler_smt_lib::compile_to_parts(&ir) {
                Ok(_) if smt_encoded(symbol) => audit_row(
                    symbol,
                    Disposition::Encoded,
                    "SMT-LIB theory/builtin encoding",
                ),
                Ok(_) if smt_allowlisted(symbol) => audit_row(
                    symbol,
                    Disposition::Allowlisted,
                    "SMT-LIB allowlisted opaque symbol",
                ),
                Ok(_) => audit_row(
                    symbol,
                    Disposition::RedPinned,
                    "compiled as uninterpreted SMT-LIB without an allowlist entry",
                ),
                Err(err) => audit_row(symbol, Disposition::Refused, err.to_string()),
            }
        })
        .collect();
    BackendReport::new("smt-lib", &corpus, rows)
}

fn smt_allowlisted(symbol: &CorpusSymbol) -> bool {
    SMT_UNINTERPRETED_ALLOWLIST
        .iter()
        .any(|(position, name, _)| {
            *position == symbol.key.position.as_str() && *name == symbol.key.name
        })
}

fn smt_encoded(symbol: &CorpusSymbol) -> bool {
    match symbol.key.position {
        SymbolPosition::Atom => {
            is_builtin_atom(&symbol.key.name) || is_smt_string_or_bv_atom(&symbol.key.name)
        }
        SymbolPosition::Ctor => {
            matches!(
                symbol.key.name.as_str(),
                "+" | "-"
                    | "*"
                    | "str.len"
                    | "str.++"
                    | "str.from_code"
                    | "str.table-select"
                    | "opt:some"
                    | "opt:none"
                    | "res:ok"
                    | "res:err"
            ) || symbol.key.name.starts_with("bv32.")
        }
    }
}

fn is_builtin_atom(name: &str) -> bool {
    matches!(
        name,
        "=" | "eq"
            | "ne"
            | "neq"
            | "distinct"
            | "<"
            | "lt"
            | "<="
            | "lte"
            | "\u{2264}"
            | ">"
            | "gt"
            | ">="
            | "gte"
            | "\u{2265}"
            | "!="
            | "\u{2260}"
            | "true"
            | "false"
            | "identity"
            | "Outlives"
    )
}

fn is_smt_string_or_bv_atom(name: &str) -> bool {
    name.starts_with("str.")
        || name.starts_with("bv32.")
        || name.starts_with("int32.")
        || name.starts_with("float.f32.")
        || name.starts_with("float.f64.")
}

#[test]
fn smt_lib_vocabulary_totality_matches_expected_frontier() {
    let report = report();
    let observed = report.red_keys();
    assert_eq!(
        observed,
        EXPECTED_RED,
        "SMT-LIB vocabulary frontier changed\n{}\n\nPasteable EXPECTED_RED:\n{}",
        report.to_json(),
        report.to_expected_red_literal("EXPECTED_RED")
    );
}

#[test]
fn smt_lib_vocabulary_totality_report() {
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
fn smt_lib_vocabulary_totality_stable_zero_target() {
    let report = report();
    assert!(report.is_zero(), "{}", report.to_json());
}
