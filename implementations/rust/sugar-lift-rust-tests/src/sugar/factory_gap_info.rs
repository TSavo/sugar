// SPDX-License-Identifier: Apache-2.0
//!
//! `CoverageGapInfo` -- structured coverage-gap data.
//!
//! Mirrors Python `factory/factory_gap_info.py`. A frozen struct that records
//! WHICH shape was encountered (observed), WHERE it lives (blame), WHAT role
//! was requested (requested), and WHAT module should be written (fix).
//!
//! `collect_gap(frag, role) -> CoverageGapInfo` is the totality-test harness:
//! call it on any `SourceFragment` that fails factory dispatch instead of
//! triggering a panic. The catalog miss arms also call it to embed the
//! structured data in the `unsupported` reason string, so a factory panic
//! always carries full gap detail.

use serde_json::{Map, Value};

use crate::sugar::source_fragment::SourceFragment;

/// A structured, queryable coverage gap.
///
/// Mirrors Python `factory.factory_gap_info` (frozen dataclass). All fields
/// are owned `String`s so the struct is `'static` and can cross thread/test
/// boundaries freely. `gap_kind` defaults to `"Sugar"` and `gap_locus`
/// defaults to `"AST"`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct CoverageGapInfo {
    pub(crate) owner:     String,
    pub(crate) blame:     String,
    pub(crate) observed:  String,
    pub(crate) requested: String,
    pub(crate) fix:       String,
    pub(crate) gap_kind:  String,
    pub(crate) gap_locus: String,
}

impl CoverageGapInfo {
    /// Primary constructor. `gap_kind` = `"Sugar"`, `gap_locus` = `"AST"`.
    pub(crate) fn new(
        owner:     impl Into<String>,
        blame:     impl Into<String>,
        observed:  impl Into<String>,
        requested: impl Into<String>,
        fix:       impl Into<String>,
    ) -> Self {
        Self {
            owner:     owner.into(),
            blame:     blame.into(),
            observed:  observed.into(),
            requested: requested.into(),
            fix:       fix.into(),
            gap_kind:  "Sugar".into(),
            gap_locus: "AST".into(),
        }
    }

    /// Human-readable gap message. Mirrors Python `factory_gap_info.message`.
    ///
    /// Format: `"write more Sugar for this AST: owner=… blame=… observed=… requested=… fix=…"`
    pub(crate) fn message(&self) -> String {
        format!(
            "write more {} for this {}: owner={} blame={} observed={} requested={} fix={}",
            self.gap_kind,
            self.gap_locus,
            self.owner,
            self.blame,
            self.observed,
            self.requested,
            self.fix,
        )
    }

    /// JSON map of the five identity fields. Mirrors Python `to_json()`.
    pub(crate) fn to_json(&self) -> Map<String, Value> {
        let mut m = Map::new();
        m.insert("owner".into(),     Value::String(self.owner.clone()));
        m.insert("blame".into(),     Value::String(self.blame.clone()));
        m.insert("observed".into(),  Value::String(self.observed.clone()));
        m.insert("requested".into(), Value::String(self.requested.clone()));
        m.insert("fix".into(),       Value::String(self.fix.clone()));
        m
    }
}

/// Build a `CoverageGapInfo` from a `SourceFragment` and a role name string.
///
/// `owner` is always `"rust.factory"` and the remaining fields come from the
/// fragment's coverage triple plus the role that was requested.
///
/// Totality tests call this to get queryable data from a miss without
/// triggering a panic. The catalog miss arms call it to embed the structured
/// data in the `unsupported` reason string.
pub(crate) fn collect_gap(frag: &SourceFragment<'_>, role: &str) -> CoverageGapInfo {
    CoverageGapInfo::new(
        "rust.factory",
        frag.blame(),
        frag.observed(),
        role,
        frag.suggested_sugar_module(),
    )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Extract the tail-expr fragment from `fn f() -> _ { <expr> }`.
    fn tail_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let stmts = match &file.items[0] {
            syn::Item::Fn(f) => &f.block.stmts,
            _ => unreachable!("expected fn item"),
        };
        let expr = match &stmts[0] {
            syn::Stmt::Expr(e, _) => e,
            _ => unreachable!("expected expr stmt"),
        };
        SourceFragment::from_node(FragNode::Expr(expr), file_str)
    }

    // -----------------------------------------------------------------------
    // Core: missing-sugar fragment -> structured data, NOT a stack trace
    // -----------------------------------------------------------------------

    #[test]
    fn missing_sugar_fragment_yields_gap_info_not_stack_trace() {
        let src = "fn f() -> i32 { 42 }";
        let file = parse_file(src);
        let frag = tail_frag(&file, "gap_test.rs");

        // collect_gap NEVER panics -- it returns structured data.
        let gap = collect_gap(&frag, "Constraint");

        assert_eq!(gap.owner,     "rust.factory",           "owner");
        assert_eq!(gap.observed,  "PrimitiveLiteral",       "observed");
        assert_eq!(gap.requested, "Constraint",             "requested");
        assert_eq!(gap.gap_kind,  "Sugar",                  "gap_kind");
        assert_eq!(gap.gap_locus, "AST",                    "gap_locus");
        assert_eq!(gap.fix,       "sugar::primitive_literal","fix");
        assert!(gap.blame.starts_with("gap_test.rs:"),      "blame={}", gap.blame);
    }

    // -----------------------------------------------------------------------
    // message() mirrors the Python format exactly
    // -----------------------------------------------------------------------

    #[test]
    fn gap_info_message_mirrors_python_format() {
        let src = "fn f() -> i32 { 42 }";
        let file = parse_file(src);
        let frag = tail_frag(&file, "msg_test.rs");
        let gap  = collect_gap(&frag, "Term");
        let msg  = gap.message();

        assert!(msg.starts_with("write more Sugar for this AST:"),  "msg={msg}");
        assert!(msg.contains("owner=rust.factory"),                  "msg={msg}");
        assert!(msg.contains("observed=PrimitiveLiteral"),           "msg={msg}");
        assert!(msg.contains("requested=Term"),                      "msg={msg}");
        assert!(msg.contains("fix=sugar::primitive_literal"),        "msg={msg}");
    }

    // -----------------------------------------------------------------------
    // to_json() exposes all five identity fields
    // -----------------------------------------------------------------------

    #[test]
    fn gap_info_to_json_has_all_five_fields() {
        let src = "fn f(a: i32, b: i32) -> i32 { a + b }";
        let file = parse_file(src);
        let frag = tail_frag(&file, "json_test.rs");
        let gap  = collect_gap(&frag, "Composite");
        let json = gap.to_json();

        assert_eq!(json["owner"].as_str().unwrap(),     "rust.factory", "owner");
        assert_eq!(json["observed"].as_str().unwrap(),  "BinOp",        "observed");
        assert_eq!(json["requested"].as_str().unwrap(), "Composite",    "requested");
        assert_eq!(json["fix"].as_str().unwrap(),       "sugar::bin_op","fix");
        assert!(json.contains_key("blame"),             "blame missing from json");
    }

    // -----------------------------------------------------------------------
    // Structural equality (frozen-dataclass semantics)
    // -----------------------------------------------------------------------

    #[test]
    fn gap_info_equality_is_structural() {
        let g1 = CoverageGapInfo::new(
            "rust.factory", "f.rs:1:0", "BinOp", "Constraint", "sugar::bin_op",
        );
        let g2 = CoverageGapInfo::new(
            "rust.factory", "f.rs:1:0", "BinOp", "Constraint", "sugar::bin_op",
        );
        let g3 = CoverageGapInfo::new(
            "rust.factory", "f.rs:1:0", "BinOp", "Term", "sugar::bin_op",
        );
        assert_eq!(g1, g2, "identical fields should be equal");
        assert_ne!(g1, g3, "different requested role should differ");
    }

    // -----------------------------------------------------------------------
    // Default gap_kind / gap_locus
    // -----------------------------------------------------------------------

    #[test]
    fn gap_info_defaults_gap_kind_and_locus() {
        let gap = CoverageGapInfo::new(
            "rust.factory", "x.rs:1:0", "Name", "Term", "sugar::name",
        );
        assert_eq!(gap.gap_kind,  "Sugar");
        assert_eq!(gap.gap_locus, "AST");
    }

    // -----------------------------------------------------------------------
    // collect_gap on different AST shapes
    // -----------------------------------------------------------------------

    #[test]
    fn collect_gap_on_bin_op_names_correct_fix() {
        let src = "fn f(a: i32) -> i32 { a + 1 }";
        let file = parse_file(src);
        let frag = tail_frag(&file, "binop.rs");
        let gap  = collect_gap(&frag, "Term");
        assert_eq!(gap.observed, "BinOp");
        assert_eq!(gap.fix,      "sugar::bin_op");
        assert_eq!(gap.owner,    "rust.factory");
    }
}
