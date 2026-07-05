// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::BTreeSet;

use sugar_lsp_rust::forward_propagator::{BaselineEntry, ForwardPropagator, LspRange, Post, Stmt};

fn unwrap_entry() -> BaselineEntry {
    BaselineEntry::new(
        "std::option::Option::unwrap",
        Some(Post::known(["receiver is Some"])),
        Some(Post::known(["returns inner value"])),
    )
}

fn check_positive_entry() -> BaselineEntry {
    BaselineEntry::new(
        "checkPositive",
        Some(Post::known(["x > 0"])),
        Some(Post::known(["returns true"])),
    )
}

fn consume_return_entry() -> BaselineEntry {
    BaselineEntry::new(
        "consumeReturn",
        Some(Post::known(["returns true"])),
        Some(Post::known([])),
    )
}

fn call_unwrap() -> Stmt {
    Stmt::Call {
        callee_id: "std::option::Option::unwrap".into(),
        range: LspRange::single_line(4, 12, 18),
    }
}

fn call_check_positive() -> Stmt {
    Stmt::Call {
        callee_id: "checkPositive".into(),
        range: LspRange::single_line(4, 12, 25),
    }
}

fn call_consume_return() -> Stmt {
    Stmt::Call {
        callee_id: "consumeReturn".into(),
        range: LspRange::single_line(5, 12, 25),
    }
}

#[test]
fn callsite_satisfies_pre_no_diagnostic() {
    let propagator = ForwardPropagator::new([unwrap_entry()]);
    let body = vec![
        Stmt::Assign {
            post: Post::known(["receiver is Some", "caller kept an extra fact"]),
        },
        call_unwrap(),
    ];

    let diagnostics = propagator.emit_diagnostics(&body);

    assert!(
        diagnostics.is_empty(),
        "extra caller facts still imply the callee precondition: {diagnostics:#?}"
    );
}

#[test]
fn callsite_violates_pre_diagnostic_emitted() {
    let propagator = ForwardPropagator::new([unwrap_entry()]);
    let body = vec![
        Stmt::Assign {
            post: Post::known(["receiver is None"]),
        },
        call_unwrap(),
    ];

    let diagnostics = propagator.emit_diagnostics(&body);

    assert_eq!(diagnostics.len(), 1, "{diagnostics:#?}");
    let diagnostic = &diagnostics[0];
    assert_eq!(diagnostic.code, "sugar.lsp.implication_failed");
    assert_eq!(diagnostic.source, "sugar");
    assert_eq!(diagnostic.severity, 1);
    assert_eq!(diagnostic.range, LspRange::single_line(4, 12, 18));
    assert_eq!(diagnostic.data.callee, "std::option::Option::unwrap");
    assert_eq!(diagnostic.data.missing_conjuncts, vec!["receiver is Some"]);
    assert!(diagnostic.data.current_post_cid.starts_with("blake3-512:"));
    assert!(diagnostic
        .data
        .baseline_index_cid
        .starts_with("blake3-512:"));

    let as_json = diagnostic.to_lsp_json();
    assert_eq!(as_json["code"], "sugar.lsp.implication_failed");
    assert_eq!(as_json["source"], "sugar");
    assert_eq!(as_json["data"]["kind"], "sugar.lsp.implication_failed");
}

#[test]
fn branch_merge_partial_satisfaction_diagnostic_on_join_path() {
    let propagator = ForwardPropagator::new([unwrap_entry()]);
    let body = vec![
        Stmt::IfElse {
            then_branch: vec![Stmt::Assign {
                post: Post::known(["receiver is Some"]),
            }],
            else_branch: vec![Stmt::Assign {
                post: Post::known([]),
            }],
        },
        call_unwrap(),
    ];

    let diagnostics = propagator.emit_diagnostics(&body);

    assert_eq!(diagnostics.len(), 1, "{diagnostics:#?}");
    assert_eq!(diagnostics[0].code, "sugar.lsp.implication_failed");
    assert_eq!(
        diagnostics[0].data.missing_conjuncts,
        vec!["receiver is Some"]
    );
}

#[test]
fn top_fallback_suppresses_false_positive() {
    let propagator = ForwardPropagator::new([unwrap_entry()]);
    let body = vec![Stmt::Unsupported, call_unwrap()];

    let diagnostics = propagator.emit_diagnostics(&body);

    assert!(
        diagnostics.is_empty(),
        "top fallback is loss of precision and must not become a diagnostic"
    );
}

#[test]
fn failed_precondition_does_not_propagate_callee_postcondition() {
    let propagator = ForwardPropagator::new([check_positive_entry(), consume_return_entry()]);
    let body = vec![
        Stmt::Assign {
            post: Post::known(["x <= 0"]),
        },
        call_check_positive(),
        call_consume_return(),
    ];

    let diagnostics = propagator.emit_diagnostics(&body);

    assert_eq!(diagnostics.len(), 2, "{diagnostics:#?}");
    let actual: BTreeSet<_> = diagnostics
        .iter()
        .map(|diagnostic| (diagnostic.data.callee.as_str(), diagnostic.code.as_str()))
        .collect();
    assert_eq!(
        actual,
        BTreeSet::from([
            ("checkPositive", "sugar.lsp.implication_failed"),
            ("consumeReturn", "sugar.lsp.implication_failed"),
        ])
    );
}

#[test]
fn floor_lowering_resets_on_qualified_function_headers() {
    let source = r#"
fn establishes_fact() {
    checkPositive(5);
}

pub fn public_violates() {
    checkPositive(-1);
}

pub(crate) fn crate_visible_violates() {
    checkPositive(-1);
}

async fn async_violates() {
    checkPositive(-1);
}
"#;
    let diagnostics = ForwardPropagator::floor_v1_seed_index()
        .emit_diagnostics(&ForwardPropagator::lower_floor_source(source));

    assert_eq!(diagnostics.len(), 3, "{diagnostics:#?}");
    assert!(diagnostics
        .iter()
        .all(|diagnostic| diagnostic.code == "sugar.lsp.implication_failed"));
    assert!(diagnostics
        .iter()
        .all(|diagnostic| diagnostic.data.callee == "checkPositive"));
}

#[test]
fn floor_lowering_resets_on_extern_function_headers() {
    let source = r#"
fn establishes_fact() {
    checkPositive(5);
}

pub unsafe extern "C" fn extern_violates() {
    checkPositive(-1);
}
"#;
    let diagnostics = ForwardPropagator::floor_v1_seed_index()
        .emit_diagnostics(&ForwardPropagator::lower_floor_source(source));

    assert_eq!(diagnostics.len(), 1, "{diagnostics:#?}");
    assert_eq!(diagnostics[0].code, "sugar.lsp.implication_failed");
    assert_eq!(diagnostics[0].data.callee, "checkPositive");
}

#[test]
fn floor_lowering_ignores_non_code_check_positive_text() {
    let source = r##"
fn no_false_calls() {
    // checkPositive(-1);
    let string = "checkPositive(-1)";
    let raw = r#"checkPositive(-1)"#;
    let _ = notcheckPositive(-1);
}
"##;
    let diagnostics = ForwardPropagator::floor_v1_seed_index()
        .emit_diagnostics(&ForwardPropagator::lower_floor_source(source));

    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
}

#[test]
fn floor_lowering_keeps_lifetime_lines_visible() {
    let source = r#"
fn violates<'a>(value: &'a str) {
    let _alias: &'a str = value; checkPositive(-1);
}
"#;
    let diagnostics = ForwardPropagator::floor_v1_seed_index()
        .emit_diagnostics(&ForwardPropagator::lower_floor_source(source));

    assert_eq!(diagnostics.len(), 1, "{diagnostics:#?}");
    assert_eq!(diagnostics[0].code, "sugar.lsp.implication_failed");
    assert_eq!(diagnostics[0].data.callee, "checkPositive");
}

#[test]
fn floor_lowering_treats_labeled_loops_as_top_fallback() {
    let source = r#"
fn labeled_loop() {
    'outer: loop {
        checkPositive(-1);
    }
}
"#;
    let diagnostics = ForwardPropagator::floor_v1_seed_index()
        .emit_diagnostics(&ForwardPropagator::lower_floor_source(source));

    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
}
