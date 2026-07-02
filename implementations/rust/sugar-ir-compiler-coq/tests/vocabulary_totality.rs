// SPDX-License-Identifier: Apache-2.0

#[path = "../../sugar-ir-compiler-test-support/vocabulary.rs"]
mod vocabulary;

use std::collections::BTreeSet;

use sugar_ir_compiler::IrCompiler;
use vocabulary::{
    audit_row, collect_corpus, formula_json_for, BackendReport, CorpusSymbol, Disposition,
    SymbolPosition,
};

const EXPECTED_RED: &[(&str, &str, usize)] = &[];

fn report() -> BackendReport {
    let corpus = collect_corpus(env!("CARGO_MANIFEST_DIR")).expect("collect IR vocabulary corpus");
    let allowlist = sugar_ir_compiler_coq::uninterpreted_allowlist_entries()
        .into_iter()
        .collect::<BTreeSet<_>>();
    let compiler = sugar_ir_compiler_coq::CoqCompiler::new();
    let rows = corpus
        .symbols
        .iter()
        .map(|symbol| {
            let ir = formula_json_for(symbol);
            if let Some(reason) = coq_builtin_arity_refusal(symbol) {
                return audit_row(symbol, Disposition::Refused, reason);
            }
            match compiler.compile(&ir, sugar_ir_compiler_coq::DIALECT) {
                Ok(_) if coq_encoded(symbol) => audit_row(
                    symbol,
                    Disposition::Encoded,
                    "Coq builtin/operator encoding",
                ),
                Ok(_)
                    if allowlist
                        .contains(&(symbol.key.name.as_str(), symbol.key.position.as_str())) =>
                {
                    audit_row(
                        symbol,
                        Disposition::Allowlisted,
                        "COQ_UNINTERPRETED_ALLOWLIST",
                    )
                }
                Ok(_) => audit_row(
                    symbol,
                    Disposition::RedPinned,
                    "compiled as uninterpreted Coq without an allowlist entry",
                ),
                Err(err) => audit_row(symbol, Disposition::Refused, err.to_string()),
            }
        })
        .collect();
    BackendReport::new("coq", &corpus, rows)
}

fn coq_builtin_arity_refusal(symbol: &CorpusSymbol) -> Option<String> {
    let expected = match symbol.key.position {
        SymbolPosition::Atom => match symbol.key.name.as_str() {
            "=" | ">" | "<" | "\u{2265}" | "\u{2264}" | "\u{2260}" => Some(2),
            "true" | "false" => Some(0),
            _ => None,
        },
        SymbolPosition::Ctor => match symbol.key.name.as_str() {
            "<" | ">" | "<=" | "\u{2264}" | ">=" | "\u{2265}" | "=" | "+" | "-" | "*" => Some(2),
            _ => None,
        },
    }?;
    (symbol.key.arity != expected).then(|| {
        format!(
            "Coq builtin `{}` expects arity {expected}, corpus probe has {}",
            symbol.key.name, symbol.key.arity
        )
    })
}

fn coq_encoded(symbol: &CorpusSymbol) -> bool {
    match symbol.key.position {
        SymbolPosition::Atom => matches!(
            symbol.key.name.as_str(),
            "=" | ">" | "<" | "\u{2265}" | "\u{2264}" | "\u{2260}" | "true" | "false"
        ),
        SymbolPosition::Ctor => matches!(
            symbol.key.name.as_str(),
            "<" | ">" | "<=" | "\u{2264}" | ">=" | "\u{2265}" | "=" | "+" | "-" | "*"
        ),
    }
}

#[test]
fn coq_vocabulary_totality_matches_expected_frontier() {
    let report = report();
    let observed = report.red_keys();
    assert_eq!(
        observed,
        EXPECTED_RED,
        "Coq vocabulary frontier changed\n{}\n\nPasteable EXPECTED_RED:\n{}",
        report.to_json(),
        report.to_expected_red_literal("EXPECTED_RED")
    );
}

#[test]
fn coq_vocabulary_totality_report() {
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
fn coq_vocabulary_totality_stable_zero_target() {
    let report = report();
    assert!(report.is_zero(), "{}", report.to_json());
}
