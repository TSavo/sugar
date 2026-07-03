// SPDX-License-Identifier: Apache-2.0
//
// IrTerm boundary-collapse campaign (#3191), Slice 1 Instrument C.
//
// This is an IDD gate. It rejects `sugar-walk` sites that reason structurally
// over `IrTerm` instead of crossing into the single floor-algebra
// representation. Slice 8 closed the pinned frontier; the planted bad twin
// below keeps the auditor armed.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use quote::ToTokens;
use syn::spanned::Spanned;
use syn::visit::Visit;

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
struct ExpectedStructuralSite {
    file: &'static str,
    symbol: &'static str,
    kind: &'static str,
    owner_slice: &'static str,
    replacement: &'static str,
}

const EXPECTED_STRUCTURAL_IRTERM_SITES: &[ExpectedStructuralSite] = &[];

const ALLOWED_STRUCTURAL_PATTERN_FNS: &[(&str, &str)] = &[
    (
        "is_pure_value_term",
        "let-hoist purity classifier, not a duplicate floor operation in #3191's drain list",
    ),
    (
        "is_trivial_result_term",
        "let-pruning helper, not a duplicate floor operation",
    ),
    (
        "lift_expr_to_term_inner",
        "native Rust AST to IrTerm construction, sanctioned boundary direction",
    ),
    (
        "ir_term_to_text",
        "serialization/rendering walk explicitly allowed by #3191",
    ),
];

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
struct ObservedSite {
    file: String,
    symbol: String,
    line: usize,
    kind: String,
    owner_slice: String,
    replacement: String,
}

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
struct UnexpectedStructuralPattern {
    file: String,
    enclosing_fn: String,
    line: usize,
    observed: String,
}

#[derive(Debug, Clone)]
struct Report {
    pinned: Vec<ObservedSite>,
    unexpected: Vec<UnexpectedStructuralPattern>,
}

impl Report {
    fn vector_by_owner(&self) -> BTreeMap<String, usize> {
        let mut vector = BTreeMap::new();
        for site in &self.pinned {
            *vector.entry(site.owner_slice.clone()).or_insert(0) += 1;
        }
        vector
    }

    fn to_json(&self) -> String {
        let pinned = self
            .pinned
            .iter()
            .map(|site| {
                serde_json::json!({
                    "file": site.file,
                    "symbol": site.symbol,
                    "line": site.line,
                    "kind": site.kind,
                    "ownerSlice": site.owner_slice,
                    "replacement": site.replacement,
                })
            })
            .collect::<Vec<_>>();
        let unexpected = self
            .unexpected
            .iter()
            .map(|site| {
                serde_json::json!({
                    "file": site.file,
                    "enclosingFn": site.enclosing_fn,
                    "line": site.line,
                    "observed": site.observed,
                    "replacement": "route structural IrTerm reasoning through the boundary/algebra or add a precise audit classification",
                })
            })
            .collect::<Vec<_>>();
        serde_json::to_string_pretty(&serde_json::json!({
            "R(structural-irterm-reasoning-sites)": self.pinned.len(),
            "vectorByOwner": self.vector_by_owner(),
            "pinned": pinned,
            "unexpected": unexpected,
        }))
        .expect("serialize report")
    }
}

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-walk has rust workspace parent")
        .parent()
        .expect("rust workspace has implementations parent")
        .parent()
        .expect("implementations has repo root parent")
        .to_path_buf()
}

fn read_source(root: &Path, rel: &str) -> String {
    fs::read_to_string(root.join(rel)).unwrap_or_else(|err| panic!("read {rel}: {err}"))
}

fn find_symbol_line(source: &str, symbol: &str) -> Option<usize> {
    let fn_needle = format!("fn {symbol}");
    let struct_needle = format!("struct {symbol}");
    source.lines().enumerate().find_map(|(idx, line)| {
        (line.contains(&fn_needle) || line.contains(&struct_needle)).then_some(idx + 1)
    })
}

fn collect_report(root: &Path) -> Report {
    let mut pinned = Vec::new();
    for expected in EXPECTED_STRUCTURAL_IRTERM_SITES {
        let source = read_source(root, expected.file);
        let line = find_symbol_line(&source, expected.symbol).unwrap_or_else(|| {
            panic!(
                "missing pinned IrTerm boundary site {} in {}",
                expected.symbol, expected.file
            )
        });
        pinned.push(ObservedSite {
            file: expected.file.to_string(),
            symbol: expected.symbol.to_string(),
            line,
            kind: expected.kind.to_string(),
            owner_slice: expected.owner_slice.to_string(),
            replacement: expected.replacement.to_string(),
        });
    }
    pinned.sort();

    let mut unexpected = Vec::new();
    for rel in [
        "implementations/rust/sugar-walk/src/lift.rs",
        "implementations/rust/sugar-walk/src/term_boundary.rs",
        "implementations/rust/sugar-walk/src/walk.rs",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
    ] {
        let source = read_source(root, rel);
        let parsed = syn::parse_file(&source).unwrap_or_else(|err| panic!("parse {rel}: {err}"));
        let mut collector = StructuralPatternCollector {
            file: rel.to_string(),
            fn_stack: Vec::new(),
            unexpected: Vec::new(),
        };
        collector.visit_file(&parsed);
        unexpected.extend(collector.unexpected);
    }
    unexpected.sort();

    Report { pinned, unexpected }
}

struct StructuralPatternCollector {
    file: String,
    fn_stack: Vec<String>,
    unexpected: Vec<UnexpectedStructuralPattern>,
}

impl StructuralPatternCollector {
    fn enclosing_fn(&self) -> String {
        self.fn_stack
            .last()
            .cloned()
            .unwrap_or_else(|| "<module>".to_string())
    }

    fn is_expected_or_allowed(&self, enclosing_fn: &str) -> bool {
        EXPECTED_STRUCTURAL_IRTERM_SITES
            .iter()
            .any(|site| site.symbol == enclosing_fn)
            || ALLOWED_STRUCTURAL_PATTERN_FNS
                .iter()
                .any(|(symbol, _reason)| *symbol == enclosing_fn)
            || self.file.ends_with("llbc_lift.rs")
    }

    fn push_unexpected(&mut self, line: usize, observed: String) {
        let enclosing_fn = self.enclosing_fn();
        if self.is_expected_or_allowed(&enclosing_fn) {
            return;
        }
        self.unexpected.push(UnexpectedStructuralPattern {
            file: self.file.clone(),
            enclosing_fn,
            line,
            observed,
        });
    }
}

fn has_cfg_test(attrs: &[syn::Attribute]) -> bool {
    attrs.iter().any(|attr| {
        attr.path().is_ident("cfg") && attr.meta.to_token_stream().to_string().contains("test")
    })
}

fn irterm_variant_path(path: &syn::Path) -> Option<String> {
    let mut segments = path.segments.iter();
    let first = segments.next()?;
    if first.ident != "IrTerm" {
        return None;
    }
    let variant = segments.next()?;
    Some(format!("IrTerm::{}", variant.ident))
}

impl<'ast> Visit<'ast> for StructuralPatternCollector {
    fn visit_item_mod(&mut self, node: &'ast syn::ItemMod) {
        if has_cfg_test(&node.attrs) {
            return;
        }
        syn::visit::visit_item_mod(self, node);
    }

    fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
        self.fn_stack.push(node.sig.ident.to_string());
        syn::visit::visit_item_fn(self, node);
        self.fn_stack.pop();
    }

    fn visit_pat_struct(&mut self, node: &'ast syn::PatStruct) {
        if let Some(path) = irterm_variant_path(&node.path) {
            self.push_unexpected(node.path.span().start().line, path);
        }
        syn::visit::visit_pat_struct(self, node);
    }

    fn visit_pat_tuple_struct(&mut self, node: &'ast syn::PatTupleStruct) {
        if let Some(path) = irterm_variant_path(&node.path) {
            self.push_unexpected(node.path.span().start().line, path);
        }
        syn::visit::visit_pat_tuple_struct(self, node);
    }
}

#[test]
fn structural_irterm_reasoning_frontier_matches_expected() {
    let report = collect_report(&repo_root());

    assert!(
        report.unexpected.is_empty(),
        "new structural IrTerm reasoning sites found\n{}",
        report.to_json()
    );
    assert_eq!(
        report.pinned.len(),
        EXPECTED_STRUCTURAL_IRTERM_SITES.len(),
        "{}",
        report.to_json()
    );
    assert!(
        report.pinned.is_empty(),
        "Instrument C gate requires stable zero\n{}",
        report.to_json()
    );
    eprintln!("{}", report.to_json());
}

#[test]
fn structural_irterm_reasoning_gate_is_stable_zero() {
    let report = collect_report(&repo_root());

    assert!(
        report.pinned.is_empty(),
        "Instrument C is a gate at campaign close; structural IrTerm reasoning must be zero\n{}",
        report.to_json()
    );
}

#[test]
fn structural_irterm_reasoning_bad_twin_fixture_is_detected() {
    let source = r#"
        use sugar_ir_types::IrTerm;

        fn planted_second_representation(term: &IrTerm) -> bool {
            match term {
                IrTerm::Ctor { .. } => true,
                _ => false,
            }
        }
    "#;
    let parsed = syn::parse_file(source).expect("parse planted bad twin");
    let mut collector = StructuralPatternCollector {
        file: "implementations/rust/sugar-walk/src/lift.rs".into(),
        fn_stack: Vec::new(),
        unexpected: Vec::new(),
    };
    collector.visit_file(&parsed);

    assert_eq!(collector.unexpected.len(), 1);
    let site = &collector.unexpected[0];
    assert_eq!(site.enclosing_fn, "planted_second_representation");
    assert_eq!(site.observed, "IrTerm::Ctor");
}
