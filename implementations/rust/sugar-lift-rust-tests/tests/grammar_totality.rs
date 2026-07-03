// SPDX-License-Identifier: Apache-2.0
//
//! Grammar-totality ledger (IDD Phase-5 syn-source census).
//!
//! Parses a corpus of real Rust source files, walks each file into syn AST
//! nodes using the same shape classification as `SourceFragment::observed()`,
//! histograms unique (kind, shape) pairs, and classifies each pair as one of:
//! lifted, debt, or membrane.
//!
//! A new syn variant hidden by `#[non_exhaustive]` must become either covered
//! by sugar, explicitly pinned debt, or an argued membrane row. Count-only
//! ceilings are forbidden: they let one new hole replace an old one.
//!
//! Each run prints the ledger vector plus every debt/unclassified row with an
//! example blame and the replacement shape.
//!
//! ## Extending the corpus
//!
//! Add file paths to `CORPUS_FILES` (relative to repo root) or add inline
//! source text to `INLINE_FIXTURES`. New shapes must enter a typed ledger
//! status in this file, never a numeric budget.

use std::collections::{BTreeMap, HashSet};
use std::fs;
use std::path::PathBuf;

use syn::spanned::Spanned;

// ─── Exact ledger dispositions ────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum GrammarLedgerStatus {
    Lifted,
    Debt,
    Membrane,
    Unclassified,
}

impl GrammarLedgerStatus {
    fn as_str(self) -> &'static str {
        match self {
            Self::Lifted => "lifted",
            Self::Debt => "debt",
            Self::Membrane => "membrane",
            Self::Unclassified => "unclassified",
        }
    }
}

#[derive(Clone, Copy)]
struct ExpectedGrammarDisposition {
    kind: &'static str,
    shape: &'static str,
    status: GrammarLedgerStatus,
    owner: &'static str,
    replacement: &'static str,
}

/// Explicit non-lifted rows for the syn-source grammar ledger.
///
/// The LLBC/Charon half of #3028 was excised by #3384, so this list is syn-only.
/// Any future row must choose debt or membrane by name; unclassified stays zero.
const EXPECTED_NON_LIFTED: &[ExpectedGrammarDisposition] = &[ExpectedGrammarDisposition {
    kind: "Item",
    shape: "Mod",
    status: GrammarLedgerStatus::Membrane,
    owner: "#3450 syn grammar ledger",
    replacement:
        "Item::Mod is a structural module membrane: the lifter descends into inline module items, but the Mod wrapper itself carries no assertion surface",
}];

// ─── Corpus definition ────────────────────────────────────────────────────────

/// Rust source files to include in the corpus (relative to repo root).
/// Extend this list to improve coverage measurement.
const CORPUS_FILES: &[&str] = &[
    "examples/base64-showcase/good/src/lib.rs",
    "examples/base64-showcase/bad/src/lib.rs",
];

/// Inline fixtures providing additional grammar shape coverage.
/// Each is a small self-contained Rust source string, parsed directly.
const INLINE_CLOSURES: &str = r#"
fn map_transform(v: &[i32]) -> Vec<i32> {
    v.iter().map(|x| *x * 2).collect()
}
fn for_loop_sum(v: &[i32]) -> i32 {
    let mut s = 0i32;
    for x in v {
        s += *x;
    }
    s
}
"#;

const INLINE_CONTROL: &str = r#"
fn match_option(x: Option<i32>) -> i32 {
    match x {
        Some(v) => v,
        None => 0,
    }
}
fn deref_ref(r: &i32) -> i32 {
    *r
}
fn range_sum(n: usize) -> usize {
    let mut acc = 0usize;
    for i in 0..n {
        acc += i;
    }
    acc
}
"#;

// ─── Shape classification (mirrors source_fragment.rs observed()) ─────────────

fn expr_shape(e: &syn::Expr) -> String {
    use syn::Expr::*;
    match e {
        Lit(l) => match &l.lit {
            syn::Lit::Int(_) | syn::Lit::Str(_) | syn::Lit::Bool(_) | syn::Lit::Float(_) => {
                "PrimitiveLiteral".into()
            }
            _ => "Lit".into(),
        },
        Array(_) => "Array".into(),
        Binary(_) => "BinOp".into(),
        Unary(_) => "UnaryOp".into(),
        Call(_) => "Call".into(),
        MethodCall(_) => "MethodCall".into(),
        Path(_) => "Name".into(),
        If(_) => "If".into(),
        Match(_) => "Match".into(),
        Block(_) => "Block".into(),
        Return(_) => "Return".into(),
        Index(_) => "Index".into(),
        Field(_) => "Field".into(),
        Reference(_) => "Reference".into(),
        Paren(_) => "Paren".into(),
        Cast(_) => "Cast".into(),
        Tuple(_) => "Tuple".into(),
        Range(_) => "Range".into(),
        Macro(_) => "Macro".into(),
        Assign(_) => "Assign".into(),
        // #[non_exhaustive]: unhandled variants go to parametric bucket
        other => format!("Other:Expr:{}", expr_discriminant(other)),
    }
}

fn expr_discriminant(e: &syn::Expr) -> &'static str {
    use syn::Expr::*;
    match e {
        Async(_) => "Async",
        Await(_) => "Await",
        Break(_) => "Break",
        Closure(_) => "Closure",
        Const(_) => "Const",
        Continue(_) => "Continue",
        ForLoop(_) => "ForLoop",
        Group(_) => "Group",
        Infer(_) => "Infer",
        Let(_) => "Let",
        Loop(_) => "Loop",
        Repeat(_) => "Repeat",
        Struct(_) => "Struct",
        Try(_) => "Try",
        TryBlock(_) => "TryBlock",
        Unsafe(_) => "Unsafe",
        Verbatim(_) => "Verbatim",
        While(_) => "While",
        Yield(_) => "Yield",
        _ => "Unknown",
    }
}

fn stmt_shape(s: &syn::Stmt) -> &'static str {
    match s {
        syn::Stmt::Local(_) => "Assign",
        syn::Stmt::Item(_) => "Item",
        syn::Stmt::Macro(_) => "Macro",
        syn::Stmt::Expr(syn::Expr::Return(_), _) => "Return",
        syn::Stmt::Expr(syn::Expr::If(_), _) => "If",
        syn::Stmt::Expr(_, _) => "Expr",
    }
}

fn item_shape(i: &syn::Item) -> &'static str {
    match i {
        syn::Item::Fn(_) => "FunctionDef",
        syn::Item::Const(_) => "Const",
        syn::Item::Impl(_) => "Impl",
        syn::Item::Struct(_) => "Struct",
        syn::Item::Enum(_) => "Enum",
        syn::Item::Use(_) => "Use",
        syn::Item::Mod(_) => "Mod",
        _ => "Other:Item",
    }
}

// ─── Corpus walker ────────────────────────────────────────────────────────────

/// (kind, shape) -> example blame
type ShapeMap = BTreeMap<(String, String), String>;

fn record(map: &mut ShapeMap, kind: &str, shape: &str, blame: String) {
    map.entry((kind.into(), shape.into())).or_insert(blame);
}

fn blame_of(file: &str, span: proc_macro2::Span) -> String {
    format!("{}:{}:{}", file, span.start().line, span.start().column)
}

fn walk_source(src: &str, file: &str, map: &mut ShapeMap) {
    let parsed = match syn::parse_file(src) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("grammar_totality: parse error in {file}: {e}");
            return;
        }
    };
    for item in &parsed.items {
        walk_item(item, file, map);
    }
}

fn walk_item(item: &syn::Item, file: &str, map: &mut ShapeMap) {
    let shape = item_shape(item);
    record(map, "Item", shape, blame_of(file, item.span()));
    match item {
        syn::Item::Fn(f) => {
            for stmt in &f.block.stmts {
                walk_stmt(stmt, file, map);
            }
        }
        syn::Item::Const(c) => {
            walk_expr(&c.expr, file, map);
        }
        syn::Item::Impl(i) => {
            for ii in &i.items {
                if let syn::ImplItem::Fn(m) = ii {
                    for stmt in &m.block.stmts {
                        walk_stmt(stmt, file, map);
                    }
                }
            }
        }
        syn::Item::Mod(m) => {
            if let Some((_, items)) = &m.content {
                for item in items {
                    walk_item(item, file, map);
                }
            }
        }
        _ => {}
    }
}

fn walk_stmt(stmt: &syn::Stmt, file: &str, map: &mut ShapeMap) {
    let shape = stmt_shape(stmt);
    record(map, "Stmt", shape, blame_of(file, stmt.span()));
    match stmt {
        syn::Stmt::Local(l) => {
            if let Some(init) = &l.init {
                walk_expr(&init.expr, file, map);
            }
        }
        syn::Stmt::Item(i) => walk_item(i, file, map),
        syn::Stmt::Expr(e, _) => walk_expr(e, file, map),
        syn::Stmt::Macro(_) => {}
    }
}

fn walk_expr(e: &syn::Expr, file: &str, map: &mut ShapeMap) {
    let shape = expr_shape(e);
    record(map, "Expr", &shape, blame_of(file, e.span()));
    match e {
        syn::Expr::Binary(b) => {
            walk_expr(&b.left, file, map);
            walk_expr(&b.right, file, map);
        }
        syn::Expr::Unary(u) => walk_expr(&u.expr, file, map),
        syn::Expr::Call(c) => {
            walk_expr(&c.func, file, map);
            for a in &c.args {
                walk_expr(a, file, map);
            }
        }
        syn::Expr::MethodCall(m) => {
            walk_expr(&m.receiver, file, map);
            for a in &m.args {
                walk_expr(a, file, map);
            }
        }
        syn::Expr::If(i) => {
            walk_expr(&i.cond, file, map);
            for s in &i.then_branch.stmts {
                walk_stmt(s, file, map);
            }
            if let Some((_, else_e)) = &i.else_branch {
                walk_expr(else_e, file, map);
            }
        }
        syn::Expr::Block(b) => {
            for s in &b.block.stmts {
                walk_stmt(s, file, map);
            }
        }
        syn::Expr::Return(r) => {
            if let Some(inner) = &r.expr {
                walk_expr(inner, file, map);
            }
        }
        syn::Expr::Cast(c) => walk_expr(&c.expr, file, map),
        syn::Expr::Index(i) => {
            walk_expr(&i.expr, file, map);
            walk_expr(&i.index, file, map);
        }
        syn::Expr::Field(f) => walk_expr(&f.base, file, map),
        syn::Expr::Reference(r) => walk_expr(&r.expr, file, map),
        syn::Expr::Paren(p) => walk_expr(&p.expr, file, map),
        syn::Expr::Array(a) => {
            for elem in &a.elems {
                walk_expr(elem, file, map);
            }
        }
        syn::Expr::Tuple(t) => {
            for elem in &t.elems {
                walk_expr(elem, file, map);
            }
        }
        syn::Expr::Range(r) => {
            if let Some(s) = &r.start {
                walk_expr(s, file, map);
            }
            if let Some(e) = &r.end {
                walk_expr(e, file, map);
            }
        }
        syn::Expr::Match(m) => {
            walk_expr(&m.expr, file, map);
            for arm in &m.arms {
                walk_expr(&arm.body, file, map);
            }
        }
        syn::Expr::Assign(a) => {
            walk_expr(&a.left, file, map);
            walk_expr(&a.right, file, map);
        }
        syn::Expr::ForLoop(f) => {
            walk_expr(&f.expr, file, map);
            for s in &f.body.stmts {
                walk_stmt(s, file, map);
            }
        }
        syn::Expr::While(w) => {
            walk_expr(&w.cond, file, map);
            for s in &w.body.stmts {
                walk_stmt(s, file, map);
            }
        }
        syn::Expr::Loop(l) => {
            for s in &l.body.stmts {
                walk_stmt(s, file, map);
            }
        }
        syn::Expr::Closure(c) => walk_expr(&c.body, file, map),
        syn::Expr::Await(a) => walk_expr(&a.base, file, map),
        _ => {}
    }
}

// ─── Coverage oracle ──────────────────────────────────────────────────────────

/// Scans all `.rs` files in `src/sugar/` and collects the set of syn variant
/// references found there (e.g. `"Expr::Binary"`, `"Stmt::Local"`, `"Item::Fn"`).
///
/// A (kind, shape) pair is "covered" if the corresponding syn variant string
/// appears anywhere in the sugar source (recognizers, helpers, or comments).
fn build_sugar_coverage() -> HashSet<String> {
    let dir = manifest_dir().join("src/sugar");
    let mut covered = HashSet::new();

    let entries: Vec<_> = fs::read_dir(&dir)
        .expect("read src/sugar/")
        .filter_map(|e| e.ok())
        .filter(|e| {
            e.file_type().map(|ft| ft.is_file()).unwrap_or(false)
                && e.path().extension().map(|x| x == "rs").unwrap_or(false)
        })
        .map(|e| e.path())
        .collect();

    for path in entries {
        let src = fs::read_to_string(&path).unwrap_or_default();
        for prefix in &["Expr::", "Stmt::", "Item::"] {
            let mut i = 0_usize;
            while i < src.len() {
                let Some(rel) = src[i..].find(prefix) else {
                    break;
                };
                let vstart = i + rel + prefix.len();
                let vend = src[vstart..]
                    .find(|c: char| !c.is_alphanumeric() && c != '_')
                    .map(|n| vstart + n)
                    .unwrap_or(src.len());
                let variant = &src[vstart..vend];
                if !variant.is_empty()
                    && variant
                        .chars()
                        .next()
                        .map(|c| c.is_uppercase())
                        .unwrap_or(false)
                {
                    covered.insert(format!("{prefix}{variant}"));
                }
                i = vstart;
            }
        }
    }
    covered
}

/// Maps a (kind, shape) pair to the syn variant string the coverage oracle uses.
/// Returns `None` for shapes that have no named variant (e.g. `Other:Item`).
fn coverage_pattern(kind: &str, shape: &str) -> Option<String> {
    if let Some(var) = shape.strip_prefix("Other:Expr:") {
        return Some(format!("Expr::{var}"));
    }
    let pat: &str = match (kind, shape) {
        // Expr shapes (named in expr_shape)
        ("Expr", "BinOp") => "Expr::Binary",
        ("Expr", "UnaryOp") => "Expr::Unary",
        ("Expr", "PrimitiveLiteral") | ("Expr", "Lit") => "Expr::Lit",
        ("Expr", "Name") => "Expr::Path",
        ("Expr", "If") => "Expr::If",
        ("Expr", "Match") => "Expr::Match",
        ("Expr", "Block") => "Expr::Block",
        ("Expr", "Return") => "Expr::Return",
        ("Expr", "Call") => "Expr::Call",
        ("Expr", "MethodCall") => "Expr::MethodCall",
        ("Expr", "Index") => "Expr::Index",
        ("Expr", "Array") => "Expr::Array",
        ("Expr", "Field") => "Expr::Field",
        ("Expr", "Reference") => "Expr::Reference",
        ("Expr", "Paren") => "Expr::Paren",
        ("Expr", "Cast") => "Expr::Cast",
        ("Expr", "Tuple") => "Expr::Tuple",
        ("Expr", "Range") => "Expr::Range",
        ("Expr", "Macro") => "Expr::Macro",
        ("Expr", "Assign") => "Expr::Assign",
        // Stmt shapes
        ("Stmt", "Assign") => "Stmt::Local",
        ("Stmt", "Item") => "Stmt::Item",
        ("Stmt", "Macro") => "Stmt::Macro",
        ("Stmt", "Return") => "Expr::Return", // via expr recognizer
        ("Stmt", "If") => "Expr::If",         // via expr recognizer
        ("Stmt", "Expr") => "Stmt::Expr",
        // Item shapes
        ("Item", "FunctionDef") => "Item::Fn",
        ("Item", "Const") => "Item::Const",
        ("Item", "Impl") => "Item::Impl",
        ("Item", "Struct") => "Item::Struct",
        ("Item", "Enum") => "Item::Enum",
        ("Item", "Use") => "Item::Use",
        ("Item", "Other:Item") => return None,
        _ => return None,
    };
    Some(pat.to_string())
}

fn to_snake_fix(shape: &str) -> String {
    let base = shape.split(':').next().unwrap_or(shape);
    let mut out = String::new();
    for (i, ch) in base.chars().enumerate() {
        if ch.is_ascii_uppercase() && i != 0 {
            out.push('_');
        }
        out.push(ch.to_ascii_lowercase());
    }
    out
}

// ─── Ledger builder ──────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
struct GrammarLedgerRow {
    kind: String,
    shape: String,
    blame: String,
    status: GrammarLedgerStatus,
    owner: String,
    replacement: String,
}

impl GrammarLedgerRow {
    fn key(&self) -> String {
        format!("{}:{}", self.kind, self.shape)
    }

    fn render(&self) -> String {
        format!(
            "[{}] {} blame={} owner={} replacement={}",
            self.status.as_str(),
            self.key(),
            self.blame,
            self.owner,
            self.replacement
        )
    }
}

#[derive(Debug)]
struct GrammarLedger {
    rows: Vec<GrammarLedgerRow>,
    unclassified: Vec<GrammarLedgerRow>,
}

impl GrammarLedger {
    fn rows_with_status(&self, status: GrammarLedgerStatus) -> Vec<&GrammarLedgerRow> {
        self.rows
            .iter()
            .filter(|row| row.status == status)
            .collect()
    }

    fn debt_keys(&self) -> Vec<String> {
        self.rows_with_status(GrammarLedgerStatus::Debt)
            .into_iter()
            .map(GrammarLedgerRow::key)
            .collect()
    }

    fn membrane_keys(&self) -> Vec<String> {
        self.rows_with_status(GrammarLedgerStatus::Membrane)
            .into_iter()
            .map(GrammarLedgerRow::key)
            .collect()
    }

    fn status_count(&self, status: GrammarLedgerStatus) -> usize {
        self.rows_with_status(status).len()
    }

    fn render(&self) -> String {
        self.rows
            .iter()
            .map(GrammarLedgerRow::render)
            .collect::<Vec<_>>()
            .join("\n")
    }
}

fn expected_non_lifted(kind: &str, shape: &str) -> Option<&'static ExpectedGrammarDisposition> {
    EXPECTED_NON_LIFTED
        .iter()
        .find(|row| row.kind == kind && row.shape == shape)
}

fn collect_shape_map() -> ShapeMap {
    let mut shape_map: ShapeMap = BTreeMap::new();
    let root = repo_root();
    for rel in CORPUS_FILES {
        let path = root.join(rel);
        match fs::read_to_string(&path) {
            Ok(src) => walk_source(&src, rel, &mut shape_map),
            Err(e) => eprintln!("grammar_totality: skip {rel}: {e}"),
        }
    }
    walk_source(INLINE_CLOSURES, "<fixture:closures>", &mut shape_map);
    walk_source(INLINE_CONTROL, "<fixture:control>", &mut shape_map);
    shape_map
}

fn build_grammar_ledger() -> GrammarLedger {
    let shape_map = collect_shape_map();
    let covered = build_sugar_coverage();
    let mut rows = Vec::new();

    for ((kind, shape), blame) in shape_map {
        let coverage = coverage_pattern(&kind, &shape);
        let is_covered = coverage.as_ref().is_some_and(|pat| covered.contains(pat));
        let row = if is_covered {
            GrammarLedgerRow {
                kind,
                shape,
                blame,
                status: GrammarLedgerStatus::Lifted,
                owner: "src/sugar coverage oracle".to_string(),
                replacement: coverage.unwrap_or_else(|| "<covered>".to_string()),
            }
        } else if let Some(expected) = expected_non_lifted(&kind, &shape) {
            GrammarLedgerRow {
                kind,
                shape,
                blame,
                status: expected.status,
                owner: expected.owner.to_string(),
                replacement: expected.replacement.to_string(),
            }
        } else {
            GrammarLedgerRow {
                kind,
                replacement: format!(
                    "classify this syn shape as lifted/debt/membrane; suggested sugar::{}",
                    to_snake_fix(&shape)
                ),
                shape,
                blame,
                status: GrammarLedgerStatus::Unclassified,
                owner: "#3028 syn grammar ledger".to_string(),
            }
        };
        rows.push(row);
    }

    rows.sort_by_key(GrammarLedgerRow::key);
    let unclassified = rows
        .iter()
        .filter(|row| row.status == GrammarLedgerStatus::Unclassified)
        .cloned()
        .collect();

    GrammarLedger { rows, unclassified }
}

// ─── Path helpers ─────────────────────────────────────────────────────────────

fn manifest_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn repo_root() -> PathBuf {
    manifest_dir()
        .parent()
        .unwrap() // rust/
        .parent()
        .unwrap() // implementations/
        .parent()
        .unwrap() // repo root
        .to_path_buf()
}

// ─── The ratchet test ─────────────────────────────────────────────────────────

#[test]
fn grammar_totality_ledger_has_no_unclassified_syn_shapes() {
    let ledger = build_grammar_ledger();
    eprintln!("--- grammar totality ledger ---");
    eprintln!(
        "corpus unique shapes: {}  lifted: {}  debt: {}  membrane: {}  unclassified: {}",
        ledger.rows.len(),
        ledger.status_count(GrammarLedgerStatus::Lifted),
        ledger.status_count(GrammarLedgerStatus::Debt),
        ledger.status_count(GrammarLedgerStatus::Membrane),
        ledger.status_count(GrammarLedgerStatus::Unclassified),
    );
    for row in ledger.rows_with_status(GrammarLedgerStatus::Debt) {
        eprintln!("debt row: {}", row.render());
    }
    for row in ledger.rows_with_status(GrammarLedgerStatus::Membrane) {
        eprintln!("membrane row: {}", row.render());
    }
    for row in &ledger.unclassified {
        eprintln!("unclassified row: {}", row.render());
    }

    assert!(
        ledger.unclassified.is_empty(),
        "R(grammar-ledger-unclassified) must stay 0; classify every syn shape as lifted/debt/membrane.\n{}",
        ledger.render()
    );
}

#[test]
fn grammar_totality_exact_ledger_replaces_ceiling() {
    let ledger = build_grammar_ledger();

    assert!(
        ledger.unclassified.is_empty(),
        "R(grammar-ledger-unclassified) must stay 0; every observed syn shape is lifted, debt, or membrane:\n{}",
        ledger.render()
    );
    assert_eq!(
        ledger.debt_keys(),
        Vec::<String>::new(),
        "the Item::Mod debt row must drain; count-only ceilings must not hide churn"
    );
    assert_eq!(
        ledger.membrane_keys(),
        vec!["Item:Mod"],
        "Item::Mod is the named syn-side structural membrane; its inner items are walked"
    );
}

#[test]
fn planted_item_mod_is_named_membrane_and_inner_items_are_walked() {
    let mut shape_map = ShapeMap::new();
    walk_source(
        "mod planted_mod { fn inner_test() { assert_eq!(1, 1); } }",
        "<fixture:item-mod>",
        &mut shape_map,
    );

    assert!(
        shape_map.contains_key(&("Item".to_string(), "Mod".to_string())),
        "planted Item::Mod must classify by name, not collapse into Other:Item: {shape_map:#?}"
    );
    assert!(
        !shape_map.contains_key(&("Item".to_string(), "Other:Item".to_string())),
        "named Item::Mod membrane must not leave an unnamed Other:Item bucket: {shape_map:#?}"
    );
    assert!(
        shape_map.contains_key(&("Item".to_string(), "FunctionDef".to_string())),
        "module membrane must descend into inline module items: {shape_map:#?}"
    );
}
