// SPDX-License-Identifier: MIT OR Apache-2.0
//
// call_edges.rs: spec #114 §1: extract call-edge mementos from a syn AST.
//
// For each function `B` that has a contract in the current compilation unit,
// walk its body and collect every call site to a named callee `A`. Emit one
// `CallEdgeMemento` per call site.
//
// Resolution:
//   - If the callee name is present in `known_contracts` (the current lift's
//     name → contractCid map), set `target_contract_cid` to its CID.
//   - Otherwise (callee in another crate, extern "C" import, or unresolvable
//     path) set `target_contract_cid` to None and populate `target_symbol`.
//
// The `evidenceTerm` is a placeholder `{kind: "obligation", source: <cid_B>,
// target: <cid_A or symbol>}` per the dispatch spec. The linker derives the
// actual predicate-level check later; the lifter's job is to surface the call
// edge as a content-addressable memento.
//
// Locus shape (no prior definition in this codebase; defined here per spec):
//   { "file": <source_path>, "line": <u32 | null>, "col": <u32 | null> }
// syn's Span has no runtime line/col information in proc-macro2 without
// enabling `proc-macro2/span-locations`; we record file only, with null for
// line/col. This is honest under-coverage per the codebase convention.

use std::collections::{BTreeMap, HashSet};
use std::sync::Arc;

use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};

/// A call-edge memento as defined in spec #114 §1.
#[derive(Debug, Clone)]
pub struct CallEdgeMemento {
    /// CID of the calling function's contract (B).
    pub source_contract_cid: String,
    /// CID of the called function's contract (A), if resolved in this unit.
    pub target_contract_cid: Option<String>,
    /// Locus of the call site within the source file.
    pub call_site_locus: CallSiteLocus,
    /// Language-local symbol name for the callee. Always populated.
    pub target_symbol: String,
    /// JCS-canonical bytes of the full memento object.
    pub canonical_bytes: Vec<u8>,
    /// CID of the memento: blake3-512(canonical_bytes).
    pub cid: String,
}

/// Source location of a call site.
/// Line/col are null because proc-macro2 Span has no runtime location data
/// without the `span-locations` feature (which we do not enable).
#[derive(Debug, Clone)]
pub struct CallSiteLocus {
    pub file: String,
    /// Always None in this implementation; linker may enrich later.
    pub line: Option<u32>,
    pub col: Option<u32>,
}

impl CallSiteLocus {
    pub fn to_value(&self) -> Arc<Value> {
        Value::object([
            ("file", Value::string(self.file.clone())),
            (
                "line",
                match self.line {
                    Some(n) => Value::integer(n as i128),
                    None => Value::null(),
                },
            ),
            (
                "col",
                match self.col {
                    Some(n) => Value::integer(n as i128),
                    None => Value::null(),
                },
            ),
        ])
    }
}

/// Build the JCS-canonical bytes and CID for one call-edge memento.
pub fn mint_call_edge(
    source_contract_cid: &str,
    target_contract_cid: Option<&str>,
    locus: &CallSiteLocus,
    target_symbol: &str,
) -> CallEdgeMemento {
    // evidenceTerm placeholder per dispatch spec.
    let evidence_term = Value::object([
        ("kind", Value::string("obligation")),
        ("source", Value::string(source_contract_cid.to_string())),
        (
            "target",
            Value::string(
                target_contract_cid
                    .map(|s| s.to_string())
                    .unwrap_or_else(|| target_symbol.to_string()),
            ),
        ),
    ]);

    let target_cid_value: Arc<Value> = match target_contract_cid {
        Some(cid) => Value::string(cid.to_string()),
        None => Value::null(),
    };

    let memento = Value::object([
        ("schemaVersion", Value::string("1")),
        ("kind", Value::string("call-edge")),
        (
            "sourceContractCid",
            Value::string(source_contract_cid.to_string()),
        ),
        ("targetContractCid", target_cid_value),
        ("callSiteLocus", locus.to_value()),
        ("targetSymbol", Value::string(target_symbol.to_string())),
        ("evidenceTerm", evidence_term),
    ]);

    let canonical_bytes = encode_jcs(&memento).into_bytes();
    let cid = blake3_512_of(&canonical_bytes);

    CallEdgeMemento {
        source_contract_cid: source_contract_cid.to_string(),
        target_contract_cid: target_contract_cid.map(|s| s.to_string()),
        call_site_locus: locus.clone(),
        target_symbol: target_symbol.to_string(),
        canonical_bytes,
        cid,
    }
}

/// Walk a syn::File and extract call-edge mementos.
///
/// `contracted_fns` is the set of function names that have contracts in this
/// compilation unit (already lifted by the adapters). Only call sites within
/// these functions emit call-edge mementos; uncontracted functions are ignored.
///
/// `contract_cids` is the name → contractCid map built during `mint_proof`.
/// Because `lift_path` does not mint (it only lifts), we pass in a map built
/// from `compute_contract_cid` directly from the ContractDecls.
pub fn extract_call_edges_from_file(
    file: &syn::File,
    source_path: &str,
    contract_cids: &BTreeMap<String, String>,
) -> Vec<CallEdgeMemento> {
    let mut edges = Vec::new();
    let contracted_fn_names: HashSet<&str> = contract_cids.keys().map(|s| s.as_str()).collect();
    walk_items_for_edges(
        &file.items,
        source_path,
        contract_cids,
        &contracted_fn_names,
        &mut edges,
    );
    edges
}

// #3027 S7: was a single 15-arm match over `syn::Item` (the ladder-demolition
// census's `patterns-types-call-edges` row). Now a sequential `if let` chain
// per item, same relative order as the original arms. The closed no-op group
// and the trailing unknown-variant panic are unchanged verbatim.
fn walk_items_for_edges(
    items: &[syn::Item],
    source_path: &str,
    contract_cids: &BTreeMap<String, String>,
    contracted_fn_names: &HashSet<&str>,
    edges: &mut Vec<CallEdgeMemento>,
) {
    for item in items {
        if let syn::Item::Fn(f) = item {
            let fn_name = f.sig.ident.to_string();
            // Only look for edges within contracted functions.
            if let Some(source_cid) = contract_cids.get(&fn_name) {
                let locus = CallSiteLocus {
                    file: source_path.to_string(),
                    line: None,
                    col: None,
                };
                collect_call_sites_in_block(&f.block, source_cid, &locus, contract_cids, edges);
            }
            // Recurse into nested items in function body.
            for stmt in &f.block.stmts {
                if let syn::Stmt::Item(inner) = stmt {
                    walk_items_for_edges(
                        std::slice::from_ref(inner),
                        source_path,
                        contract_cids,
                        contracted_fn_names,
                        edges,
                    );
                }
            }
            continue;
        }
        if let syn::Item::Mod(m) = item {
            if let Some((_, items)) = &m.content {
                walk_items_for_edges(
                    items,
                    source_path,
                    contract_cids,
                    contracted_fn_names,
                    edges,
                );
            }
            continue;
        }
        if let syn::Item::ForeignMod(fm) = item {
            // extern "C" blocks: no call sites to extract here,
            // but we record the symbol names for resolution later.
            // The actual call-edge emission happens when contracted
            // functions CALL these extern symbols (handled below via
            // the call-site walker).
            let _ = fm;
            continue;
        }
        if matches!(
            item,
            syn::Item::Const(_)
                | syn::Item::Enum(_)
                | syn::Item::ExternCrate(_)
                | syn::Item::Macro(_)
                | syn::Item::Static(_)
                | syn::Item::Struct(_)
                | syn::Item::Trait(_)
                | syn::Item::TraitAlias(_)
                | syn::Item::Type(_)
                | syn::Item::Union(_)
                | syn::Item::Use(_)
                | syn::Item::Verbatim(_)
        ) {
            continue;
        }
        panic!("sugar-lift call_edges refused unknown syn::Item variant")
    }
}

/// Collect all call sites in a block, emitting one CallEdgeMemento per site.
fn collect_call_sites_in_block(
    block: &syn::Block,
    source_cid: &str,
    locus: &CallSiteLocus,
    contract_cids: &BTreeMap<String, String>,
    edges: &mut Vec<CallEdgeMemento>,
) {
    for stmt in &block.stmts {
        collect_call_sites_in_stmt(stmt, source_cid, locus, contract_cids, edges);
    }
}

// #3027 S7: was a 4-arm match over `syn::Stmt` (the ladder-demolition census's
// `patterns-types-call-edges` row). Now a sequential `if let` chain; the two
// no-op arms keep their exact same comments and behavior.
fn collect_call_sites_in_stmt(
    stmt: &syn::Stmt,
    source_cid: &str,
    locus: &CallSiteLocus,
    contract_cids: &BTreeMap<String, String>,
    edges: &mut Vec<CallEdgeMemento>,
) {
    if let syn::Stmt::Expr(expr, _) = stmt {
        collect_call_sites_in_expr(expr, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Stmt::Local(local) = stmt {
        if let Some(init) = &local.init {
            collect_call_sites_in_expr(&init.expr, source_cid, locus, contract_cids, edges);
            if let Some((_, diverge)) = &init.diverge {
                collect_call_sites_in_expr(diverge, source_cid, locus, contract_cids, edges);
            }
        }
        return;
    }
    if let syn::Stmt::Item(_) = stmt {
        // Nested items handled at the items-walking level.
        return;
    }
    // syn::Stmt::Macro(_): macro statements (e.g. assert!) may contain call
    // sites, but we cannot reliably parse their token streams here. Skipped.
}

// #3027 S7: was a single 39-arm match over `syn::Expr` (the ladder-demolition
// census's `patterns-types-call-edges` row). Now a sequential `if let` chain,
// same relative order as the original arms. The closed no-op group and the
// trailing unknown-variant panic are unchanged verbatim.
fn collect_call_sites_in_expr(
    expr: &syn::Expr,
    source_cid: &str,
    locus: &CallSiteLocus,
    contract_cids: &BTreeMap<String, String>,
    edges: &mut Vec<CallEdgeMemento>,
) {
    if let syn::Expr::Call(c) = expr {
        // Emit an edge for this call site.
        if let Some(callee_name) = callee_name_from_expr(&c.func) {
            let target_cid = contract_cids.get(&callee_name).map(|s| s.as_str());
            let edge = mint_call_edge(source_cid, target_cid, locus, &callee_name);
            edges.push(edge);
        }
        collect_call_sites_in_expr(&c.func, source_cid, locus, contract_cids, edges);
        // Recurse into arguments.
        for arg in &c.args {
            collect_call_sites_in_expr(arg, source_cid, locus, contract_cids, edges);
        }
        return;
    }
    if let syn::Expr::MethodCall(mc) = expr {
        // Emit an edge for the method call.
        let callee_name = mc.method.to_string();
        // Methods don't resolve to contract CIDs by name alone; treat as unresolved.
        let edge = mint_call_edge(source_cid, None, locus, &callee_name);
        edges.push(edge);
        // Recurse into receiver and arguments.
        collect_call_sites_in_expr(&mc.receiver, source_cid, locus, contract_cids, edges);
        for arg in &mc.args {
            collect_call_sites_in_expr(arg, source_cid, locus, contract_cids, edges);
        }
        return;
    }
    // Recurse into sub-expressions.
    if let syn::Expr::Block(b) = expr {
        collect_call_sites_in_block(&b.block, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Async(e) = expr {
        collect_call_sites_in_block(&e.block, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Const(e) = expr {
        collect_call_sites_in_block(&e.block, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::If(e) = expr {
        collect_call_sites_in_expr(&e.cond, source_cid, locus, contract_cids, edges);
        collect_call_sites_in_block(&e.then_branch, source_cid, locus, contract_cids, edges);
        if let Some((_, else_b)) = &e.else_branch {
            collect_call_sites_in_expr(else_b, source_cid, locus, contract_cids, edges);
        }
        return;
    }
    if let syn::Expr::While(e) = expr {
        collect_call_sites_in_expr(&e.cond, source_cid, locus, contract_cids, edges);
        collect_call_sites_in_block(&e.body, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::ForLoop(e) = expr {
        collect_call_sites_in_expr(&e.expr, source_cid, locus, contract_cids, edges);
        collect_call_sites_in_block(&e.body, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Loop(e) = expr {
        collect_call_sites_in_block(&e.body, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Match(e) = expr {
        collect_call_sites_in_expr(&e.expr, source_cid, locus, contract_cids, edges);
        for arm in &e.arms {
            if let Some((_, guard)) = &arm.guard {
                collect_call_sites_in_expr(guard, source_cid, locus, contract_cids, edges);
            }
            collect_call_sites_in_expr(&arm.body, source_cid, locus, contract_cids, edges);
        }
        return;
    }
    if let syn::Expr::Binary(e) = expr {
        collect_call_sites_in_expr(&e.left, source_cid, locus, contract_cids, edges);
        collect_call_sites_in_expr(&e.right, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Unary(e) = expr {
        collect_call_sites_in_expr(&e.expr, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Return(e) = expr {
        if let Some(v) = &e.expr {
            collect_call_sites_in_expr(v, source_cid, locus, contract_cids, edges);
        }
        return;
    }
    if let syn::Expr::Break(e) = expr {
        if let Some(v) = &e.expr {
            collect_call_sites_in_expr(v, source_cid, locus, contract_cids, edges);
        }
        return;
    }
    if let syn::Expr::Yield(e) = expr {
        if let Some(v) = &e.expr {
            collect_call_sites_in_expr(v, source_cid, locus, contract_cids, edges);
        }
        return;
    }
    if let syn::Expr::Assign(e) = expr {
        collect_call_sites_in_expr(&e.left, source_cid, locus, contract_cids, edges);
        collect_call_sites_in_expr(&e.right, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Field(e) = expr {
        collect_call_sites_in_expr(&e.base, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Index(e) = expr {
        collect_call_sites_in_expr(&e.expr, source_cid, locus, contract_cids, edges);
        collect_call_sites_in_expr(&e.index, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Paren(e) = expr {
        collect_call_sites_in_expr(&e.expr, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Group(e) = expr {
        collect_call_sites_in_expr(&e.expr, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Reference(e) = expr {
        collect_call_sites_in_expr(&e.expr, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::RawAddr(e) = expr {
        collect_call_sites_in_expr(&e.expr, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Cast(e) = expr {
        collect_call_sites_in_expr(&e.expr, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Closure(e) = expr {
        collect_call_sites_in_expr(&e.body, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Try(e) = expr {
        collect_call_sites_in_expr(&e.expr, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Await(e) = expr {
        collect_call_sites_in_expr(&e.base, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Unsafe(e) = expr {
        collect_call_sites_in_block(&e.block, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::TryBlock(e) = expr {
        collect_call_sites_in_block(&e.block, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Let(e) = expr {
        collect_call_sites_in_expr(&e.expr, source_cid, locus, contract_cids, edges);
        return;
    }
    if let syn::Expr::Tuple(e) = expr {
        for elem in &e.elems {
            collect_call_sites_in_expr(elem, source_cid, locus, contract_cids, edges);
        }
        return;
    }
    if let syn::Expr::Array(e) = expr {
        for elem in &e.elems {
            collect_call_sites_in_expr(elem, source_cid, locus, contract_cids, edges);
        }
        return;
    }
    if let syn::Expr::Struct(e) = expr {
        for field in &e.fields {
            collect_call_sites_in_expr(&field.expr, source_cid, locus, contract_cids, edges);
        }
        if let Some(rest) = &e.rest {
            collect_call_sites_in_expr(rest, source_cid, locus, contract_cids, edges);
        }
        return;
    }
    if let syn::Expr::Repeat(e) = expr {
        collect_call_sites_in_expr(&e.expr, source_cid, locus, contract_cids, edges);
        collect_call_sites_in_expr(&e.len, source_cid, locus, contract_cids, edges);
        return;
    }
    if matches!(
        expr,
        syn::Expr::Continue(_)
            | syn::Expr::Infer(_)
            | syn::Expr::Lit(_)
            | syn::Expr::Macro(_)
            | syn::Expr::Path(_)
            | syn::Expr::Verbatim(_)
    ) {
        return;
    }
    panic!("sugar-lift call_edges refused unknown syn::Expr variant")
}

/// Extract the callee name from a function-call expression's func field.
/// Returns None for closures, parenthesised exprs, and other non-path callees.
// #3027 S7: was a single 40-arm match over `syn::Expr` (the ladder-demolition
// census's `patterns-types-call-edges` row). Now a sequential `if let` chain;
// the closed no-op-returning-None group and the trailing unknown-variant
// panic are unchanged verbatim.
fn callee_name_from_expr(func: &syn::Expr) -> Option<String> {
    if let syn::Expr::Path(p) = func {
        return Some(path_to_string(&p.path));
    }
    if let syn::Expr::Paren(inner) = func {
        return callee_name_from_expr(&inner.expr);
    }
    if let syn::Expr::Group(inner) = func {
        return callee_name_from_expr(&inner.expr);
    }
    if matches!(
        func,
        syn::Expr::Array(_)
            | syn::Expr::Assign(_)
            | syn::Expr::Async(_)
            | syn::Expr::Await(_)
            | syn::Expr::Binary(_)
            | syn::Expr::Block(_)
            | syn::Expr::Break(_)
            | syn::Expr::Call(_)
            | syn::Expr::Cast(_)
            | syn::Expr::Closure(_)
            | syn::Expr::Const(_)
            | syn::Expr::Continue(_)
            | syn::Expr::Field(_)
            | syn::Expr::ForLoop(_)
            | syn::Expr::If(_)
            | syn::Expr::Index(_)
            | syn::Expr::Infer(_)
            | syn::Expr::Let(_)
            | syn::Expr::Lit(_)
            | syn::Expr::Loop(_)
            | syn::Expr::Macro(_)
            | syn::Expr::Match(_)
            | syn::Expr::MethodCall(_)
            | syn::Expr::Range(_)
            | syn::Expr::RawAddr(_)
            | syn::Expr::Reference(_)
            | syn::Expr::Repeat(_)
            | syn::Expr::Return(_)
            | syn::Expr::Struct(_)
            | syn::Expr::Try(_)
            | syn::Expr::TryBlock(_)
            | syn::Expr::Tuple(_)
            | syn::Expr::Unary(_)
            | syn::Expr::Unsafe(_)
            | syn::Expr::Verbatim(_)
            | syn::Expr::While(_)
            | syn::Expr::Yield(_)
    ) {
        return None;
    }
    panic!("sugar-lift call_edges refused unknown call callee syn::Expr variant")
}

fn path_to_string(p: &syn::Path) -> String {
    p.segments
        .iter()
        .map(|s| s.ident.to_string())
        .collect::<Vec<_>>()
        .join("::")
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    fn parse(src: &str) -> syn::File {
        syn::parse_file(src).expect("parse_file")
    }

    #[test]
    fn no_edges_from_uncontracted_function() {
        let file = parse(
            r#"
            fn a() {}
            fn b() { a(); }
        "#,
        );
        let cids: BTreeMap<String, String> = BTreeMap::new();
        let edges = extract_call_edges_from_file(&file, "test.rs", &cids);
        assert!(edges.is_empty());
    }

    #[test]
    fn edge_from_contracted_caller_to_contracted_callee() {
        let file = parse(
            r#"
            fn a() {}
            fn b() { a(); }
        "#,
        );
        let mut cids = BTreeMap::new();
        cids.insert("a".to_string(), "blake3-512:aaa".to_string());
        cids.insert("b".to_string(), "blake3-512:bbb".to_string());
        let edges = extract_call_edges_from_file(&file, "test.rs", &cids);
        assert_eq!(edges.len(), 1, "expected one edge b→a, got {edges:?}");
        let e = &edges[0];
        assert_eq!(e.source_contract_cid, "blake3-512:bbb");
        assert_eq!(e.target_contract_cid.as_deref(), Some("blake3-512:aaa"));
        assert_eq!(e.target_symbol, "a");
    }

    #[test]
    fn edge_to_unknown_callee_has_null_target_cid() {
        let file = parse(
            r#"
            fn b() { unknown_extern(); }
        "#,
        );
        let mut cids = BTreeMap::new();
        cids.insert("b".to_string(), "blake3-512:bbb".to_string());
        let edges = extract_call_edges_from_file(&file, "test.rs", &cids);
        assert_eq!(edges.len(), 1);
        let e = &edges[0];
        assert!(e.target_contract_cid.is_none(), "target_cid should be None");
        assert_eq!(e.target_symbol, "unknown_extern");
    }

    #[test]
    fn async_block_callsite_emits_edge() {
        let file = parse(
            r#"
            fn a() {}
            fn b() { let _fut = async { a(); }; }
        "#,
        );
        let mut cids = BTreeMap::new();
        cids.insert("a".to_string(), "blake3-512:aaa".to_string());
        cids.insert("b".to_string(), "blake3-512:bbb".to_string());

        let edges = extract_call_edges_from_file(&file, "test.rs", &cids);

        assert_eq!(edges.len(), 1, "async block callsite must emit one edge");
        assert_eq!(
            edges[0].target_contract_cid.as_deref(),
            Some("blake3-512:aaa")
        );
        assert_eq!(edges[0].target_symbol, "a");
    }

    #[test]
    fn jcs_bytes_are_deterministic_across_two_calls() {
        let file = parse(
            r#"
            fn a() {}
            fn b() { a(); }
        "#,
        );
        let mut cids = BTreeMap::new();
        cids.insert("a".to_string(), "blake3-512:aaa".to_string());
        cids.insert("b".to_string(), "blake3-512:bbb".to_string());
        let edges1 = extract_call_edges_from_file(&file, "test.rs", &cids);
        let edges2 = extract_call_edges_from_file(&file, "test.rs", &cids);
        assert_eq!(edges1.len(), edges2.len());
        for (e1, e2) in edges1.iter().zip(edges2.iter()) {
            assert_eq!(
                e1.canonical_bytes, e2.canonical_bytes,
                "JCS bytes must be deterministic"
            );
            assert_eq!(e1.cid, e2.cid, "CID must be deterministic");
        }
    }
}
