// SPDX-License-Identifier: Apache-2.0
//
// Silent-drop frontier auditor (#2997).
//
// This is an IDD instrument, not a drain. It scans the Rust lift kit source for
// silent catch-all/default shapes that can hide unhandled syn/LLBC surface:
// wildcard match arms that do nothing or return None, and Option/Result
// conversion/default calls that erase failure. Each offender remains visible
// until a later drain either makes it loud/total or sanctions the specific site.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use syn::spanned::Spanned;
use syn::visit::Visit;

const EXPECTED_FRONTIER: &[(&str, &str, &str, &str)] = &[];

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
struct FrontierKey {
    file: String,
    enclosing_fn: String,
    observed: String,
}

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
struct Site {
    kind: &'static str,
    key: FrontierKey,
    line: usize,
    replacement: &'static str,
}

#[derive(Debug, Clone)]
struct Report {
    offenders: Vec<Site>,
}

impl Report {
    fn total(&self) -> usize {
        self.offenders.len()
    }

    fn is_zero(&self) -> bool {
        self.offenders.is_empty()
    }

    fn vector(&self) -> BTreeMap<&'static str, usize> {
        let mut vector = BTreeMap::from([
            ("ok", 0),
            ("unwrap_or", 0),
            ("unwrap_or_default", 0),
            ("wildcard_empty_block", 0),
            ("wildcard_none", 0),
        ]);
        for site in &self.offenders {
            *vector.entry(site.kind).or_insert(0) += 1;
        }
        vector
    }

    fn keys_with_kind(&self) -> Vec<(&str, &str, &str, &str)> {
        self.offenders
            .iter()
            .map(|site| {
                (
                    site.kind,
                    site.key.file.as_str(),
                    site.key.enclosing_fn.as_str(),
                    site.key.observed.as_str(),
                )
            })
            .collect()
    }

    fn to_json(&self) -> String {
        let offenders = self
            .offenders
            .iter()
            .map(|site| {
                serde_json::json!({
                    "kind": site.kind,
                    "file": site.key.file,
                    "enclosing_fn": site.key.enclosing_fn,
                    "observed": site.key.observed,
                    "line": site.line,
                    "replacement": site.replacement,
                })
            })
            .collect::<Vec<_>>();
        serde_json::to_string_pretty(&serde_json::json!({
            "total": self.total(),
            "is_zero": self.is_zero(),
            "vector": self.vector(),
            "offenders": offenders,
        }))
        .expect("serialize report")
    }

    fn to_expected_frontier_literal(&self) -> String {
        let mut out = String::new();
        out.push_str("const EXPECTED_FRONTIER: &[(&str, &str, &str, &str)] = &[\n");
        for site in &self.offenders {
            out.push_str(&format!(
                "    ({:?}, {:?}, {:?}, {:?}),\n",
                site.kind, site.key.file, site.key.enclosing_fn, site.key.observed
            ));
        }
        out.push_str("];\n");
        out
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

fn collect_silent_drop_frontier(root: &Path) -> Result<Report, String> {
    let source_roots = [
        root.join("implementations/rust/sugar-walk/src"),
        root.join("implementations/rust/sugar-lift/src"),
        root.join("implementations/rust/sugar-lift-contracts/src"),
    ];
    let mut offenders = Vec::new();
    for source_root in source_roots {
        let files = rust_files_under(&source_root)?;
        for path in files {
            let rel = path
                .strip_prefix(root)
                .map_err(|err| format!("strip {}: {err}", path.display()))?
                .to_string_lossy()
                .replace('\\', "/");
            let source = fs::read_to_string(&path)
                .map_err(|err| format!("read {}: {err}", path.display()))?;
            let parsed = syn::parse_file(&source).map_err(|err| format!("parse {rel}: {err}"))?;
            let lines = source.lines().map(str::to_string).collect::<Vec<_>>();
            let mut collector = Collector {
                file: rel,
                lines,
                fn_stack: Vec::new(),
                offenders: Vec::new(),
            };
            collector.visit_file(&parsed);
            offenders.extend(collector.offenders);
        }
    }
    offenders.sort();
    Ok(Report { offenders })
}

fn rust_files_under(root: &Path) -> Result<Vec<PathBuf>, String> {
    if !root.is_dir() {
        return Err(format!("source root missing: {}", root.display()));
    }
    let mut files = Vec::new();
    collect_rust_files(root, &mut files)?;
    files.sort();
    Ok(files)
}

fn collect_rust_files(dir: &Path, files: &mut Vec<PathBuf>) -> Result<(), String> {
    for entry in fs::read_dir(dir).map_err(|err| format!("read dir {}: {err}", dir.display()))? {
        let entry = entry.map_err(|err| format!("read dir entry {}: {err}", dir.display()))?;
        let path = entry.path();
        if path.is_dir() {
            collect_rust_files(&path, files)?;
        } else if path.extension().and_then(|ext| ext.to_str()) == Some("rs") {
            files.push(path);
        }
    }
    Ok(())
}

struct Collector {
    file: String,
    lines: Vec<String>,
    fn_stack: Vec<String>,
    offenders: Vec<Site>,
}

impl Collector {
    fn enclosing_fn(&self) -> String {
        self.fn_stack
            .last()
            .cloned()
            .unwrap_or_else(|| "<module>".to_string())
    }

    fn is_sanctioned(&self, line: usize) -> bool {
        line.checked_sub(2)
            .and_then(|idx| self.lines.get(idx))
            .is_some_and(|line| {
                line.contains("sugar-audit: not-mine(") || line.contains("sugar-audit: default-ok(")
            })
    }

    fn push_site(
        &mut self,
        kind: &'static str,
        line: usize,
        observed: &'static str,
        replacement: &'static str,
    ) {
        if self.is_sanctioned(line) {
            return;
        }
        self.offenders.push(Site {
            kind,
            key: FrontierKey {
                file: self.file.clone(),
                enclosing_fn: self.enclosing_fn(),
                observed: observed.to_string(),
            },
            line,
            replacement,
        });
    }
}

impl<'ast> Visit<'ast> for Collector {
    fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
        self.fn_stack.push(node.sig.ident.to_string());
        syn::visit::visit_item_fn(self, node);
        self.fn_stack.pop();
    }

    fn visit_impl_item_fn(&mut self, node: &'ast syn::ImplItemFn) {
        self.fn_stack.push(node.sig.ident.to_string());
        syn::visit::visit_impl_item_fn(self, node);
        self.fn_stack.pop();
    }

    fn visit_expr_match(&mut self, node: &'ast syn::ExprMatch) {
        for arm in &node.arms {
            if !matches!(arm.pat, syn::Pat::Wild(_)) {
                continue;
            }
            let line = arm.pat.span().start().line;
            if is_empty_block(&arm.body) {
                self.push_site(
                    "wildcard_empty_block",
                    line,
                    "_ => {}",
                    "replace silent catch-all with explicit variant handling or loud refusal",
                );
            } else if is_none_expr(&arm.body) {
                self.push_site(
                    "wildcard_none",
                    line,
                    "_ => None",
                    "replace silent classifier miss with explicit handling, refusal, or per-site sanction",
                );
            }
        }
        syn::visit::visit_expr_match(self, node);
    }

    fn visit_expr_method_call(&mut self, node: &'ast syn::ExprMethodCall) {
        let method = node.method.to_string();
        let line = node.method.span().start().line;
        match method.as_str() {
            "unwrap_or" => self.push_site(
                "unwrap_or",
                line,
                "unwrap_or",
                "replace silent default with typed error propagation or default-ok sanction",
            ),
            "unwrap_or_default" => self.push_site(
                "unwrap_or_default",
                line,
                "unwrap_or_default",
                "replace silent default with typed error propagation or default-ok sanction",
            ),
            "ok" => self.push_site(
                "ok",
                line,
                "ok",
                "preserve the error, make the refusal loud, or mark the specific miss not-mine/default-ok",
            ),
            _ => {}
        }
        syn::visit::visit_expr_method_call(self, node);
    }
}

fn is_empty_block(expr: &syn::Expr) -> bool {
    matches!(expr, syn::Expr::Block(block) if block.block.stmts.is_empty())
}

fn is_none_expr(expr: &syn::Expr) -> bool {
    matches!(expr, syn::Expr::Path(path) if path.path.is_ident("None"))
}

#[test]
fn silent_drop_frontier_matches_expected_multiset() {
    let report = collect_silent_drop_frontier(&repo_root()).expect("collect silent-drop frontier");
    let observed = report.keys_with_kind();

    assert_eq!(
        observed,
        EXPECTED_FRONTIER,
        "silent-drop frontier changed\n{}\n\nPasteable EXPECTED_FRONTIER:\n{}",
        report.to_json(),
        report.to_expected_frontier_literal()
    );
}

#[test]
fn silent_drop_frontier_is_red_report_only() {
    let report = collect_silent_drop_frontier(&repo_root()).expect("collect silent-drop frontier");
    eprintln!("{}", report.to_json());

    assert!(report.is_zero(), "{}", report.to_json());
    assert_eq!(
        report.total(),
        EXPECTED_FRONTIER.len(),
        "{}",
        report.to_json()
    );
}

#[test]
fn silent_drop_frontier_stable_zero_target() {
    let report = collect_silent_drop_frontier(&repo_root()).expect("collect silent-drop frontier");

    assert!(report.is_zero(), "{}", report.to_json());
}
