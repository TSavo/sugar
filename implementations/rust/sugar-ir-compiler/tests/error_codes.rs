// SPDX-License-Identifier: MIT OR Apache-2.0

use sugar_ir_compiler::CompileError;

#[test]
fn error_codes_match_spec_table() {
    assert_eq!(CompileError::UnsupportedDialect("d".into()).code(), 2000);
    assert_eq!(CompileError::UnsupportedSort("Set".into()).code(), 2001);
    assert_eq!(
        CompileError::UnsupportedPredicate("foo".into()).code(),
        2002
    );
    assert_eq!(CompileError::MalformedIr("bad".into()).code(), 2003);
    assert_eq!(CompileError::Internal("bug".into()).code(), 2004);
}

#[test]
fn error_symbolic_names_match_spec() {
    assert_eq!(
        CompileError::UnsupportedSort("X".into()).symbolic(),
        "compile_error.unsupported_sort"
    );
    assert_eq!(
        CompileError::UnsupportedPredicate("X".into()).symbolic(),
        "compile_error.unsupported_predicate"
    );
    assert_eq!(
        CompileError::UnsupportedDialect("X".into()).symbolic(),
        "compile_error.unsupported_dialect"
    );
    assert_eq!(
        CompileError::MalformedIr("X".into()).symbolic(),
        "compile_error.malformed_ir"
    );
    assert_eq!(
        CompileError::Internal("X".into()).symbolic(),
        "compile_error.internal"
    );
}
