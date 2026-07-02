// SPDX-License-Identifier: Apache-2.0

#[path = "../../sugar-ir-compiler-test-support/vocabulary.rs"]
mod vocabulary;

use sugar_ir_compiler::IrCompiler;
use vocabulary::{
    audit_row, collect_corpus, maude_json_for, BackendReport, Disposition, SymbolPosition,
};

const EXPECTED_RED: &[(&str, &str, usize)] = &[];

fn report() -> BackendReport {
    let corpus = collect_corpus(env!("CARGO_MANIFEST_DIR")).expect("collect IR vocabulary corpus");
    let compiler = sugar_ir_compiler_maude::MaudeCompiler::new();
    let rows = corpus
        .symbols
        .iter()
        .map(|symbol| {
            let ir = maude_json_for(symbol);
            match compiler.compile(&ir, sugar_ir_compiler_maude::DIALECT) {
                Ok(_) if symbol.key.position == SymbolPosition::Ctor => audit_row(
                    symbol,
                    Disposition::Encoded,
                    "Maude explicit equational-theory operator encoding",
                ),
                Ok(_) => audit_row(
                    symbol,
                    Disposition::RedPinned,
                    "non-equational atom unexpectedly compiled in Maude",
                ),
                Err(err) => audit_row(symbol, Disposition::Refused, err.to_string()),
            }
        })
        .collect();
    BackendReport::new("maude", &corpus, rows)
}

#[test]
fn maude_vocabulary_totality_matches_expected_frontier() {
    let report = report();
    let observed = report.red_keys();
    assert_eq!(
        observed,
        EXPECTED_RED,
        "Maude vocabulary frontier changed\n{}\n\nPasteable EXPECTED_RED:\n{}",
        report.to_json(),
        report.to_expected_red_literal("EXPECTED_RED")
    );
}

#[test]
fn maude_vocabulary_totality_report() {
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
fn maude_vocabulary_totality_stable_zero_target() {
    let report = report();
    assert!(report.is_zero(), "{}", report.to_json());
}
