// SPDX-License-Identifier: Apache-2.0
//
//! `SourceFragment` -- the ONE door the factory uses to talk to the syn AST.
//!
//! Mirrors the Python `factory/source_fragment.py`. A fragment wraps a node and where
//! it lives, knows how to DECOMPOSE itself into child fragments, and carries the
//! coverage triple (`observed`/`blame`/`suggested_sugar_module`) that drives totality
//! accounting. Sugars are meant to talk to `&SourceFragment` and its typed accessors --
//! never to raw `syn` fields (that migration is the Phase-4 ratchet).
//!
//! Rust differs from Python in two ways that shape this module:
//!   * `syn::Expr`/`Stmt`/`Item` are `#[non_exhaustive]`, so `observed()` ends in a `_`
//!     arm that routes unknown variants to the parametric bucket `"Other:<kind>"` -- the
//!     new-shape detector, the analogue of Python's `non-return:<Stmt>` bucket.
//!   * there is no `ast.iter_fields` reflection, so decomposition is hand-matched.

use syn::spanned::Spanned;

/// A Python suite has no AST node; a Rust block (`{ stmt; stmt; }`) does, but a bare
/// `&[Stmt]` (a function body, an `if`/`else` branch) does not. `Block` is the synthetic
/// fragment that puts a suite on the stack as ONE composite, so `BlockSugar` composes it
/// instead of an external loop -- exactly like the Python synthetic `Block`.
#[derive(Clone, Copy)]
pub(crate) struct BlockFrag<'a> {
    pub(crate) stmts: &'a [syn::Stmt],
    pub(crate) line: usize,
    pub(crate) col: usize,
}

/// The node a fragment wraps. Borrowed -- a fragment never owns AST.
#[derive(Clone, Copy)]
pub(crate) enum FragNode<'a> {
    File(&'a syn::File),
    Item(&'a syn::Item),
    Stmt(&'a syn::Stmt),
    Expr(&'a syn::Expr),
    /// Synthetic suite (a `&[Stmt]` body/branch). See `BlockFrag`.
    Block(BlockFrag<'a>),
}

/// A fragment of source -- node + position. The single object both sugar construction
/// and gap accounting hold.
#[derive(Clone, Copy)]
pub(crate) struct SourceFragment<'a> {
    pub(crate) node: FragNode<'a>,
    pub(crate) file: &'a str,
    pub(crate) line: usize,
    pub(crate) col: usize,
}

impl<'a> SourceFragment<'a> {
    pub(crate) fn from_node(node: FragNode<'a>, file: &'a str) -> Self {
        let (line, col) = node_position(&node);
        Self { node, file, line, col }
    }

    pub(crate) fn expr(e: &'a syn::Expr, file: &'a str) -> Self {
        Self::from_node(FragNode::Expr(e), file)
    }
    pub(crate) fn stmt(s: &'a syn::Stmt, file: &'a str) -> Self {
        Self::from_node(FragNode::Stmt(s), file)
    }
    pub(crate) fn block(stmts: &'a [syn::Stmt], file: &'a str) -> Self {
        let (line, col) = stmts
            .first()
            .map(|s| (s.span().start().line, s.span().start().column))
            .unwrap_or((0, 0));
        Self::from_node(FragNode::Block(BlockFrag { stmts, line, col }), file)
    }

    // -----------------------------------------------------------------------
    // Coverage triple
    // -----------------------------------------------------------------------

    /// What this node IS -- the grammar shape. `Constant`-like literals normalize to
    /// `"PrimitiveLiteral"`; an unhandled `syn` variant falls to `"Other:<kind>"` (the
    /// non_exhaustive wildcard -- never a silent drop).
    pub(crate) fn observed(&self) -> String {
        match &self.node {
            FragNode::File(_) => "File".into(),
            FragNode::Block(_) => "Block".into(),
            FragNode::Item(i) => item_kind(i).into(),
            FragNode::Stmt(s) => stmt_kind(s).into(),
            FragNode::Expr(e) => expr_kind(e),
        }
    }

    /// `file:line:col` -- where a gap or fact lives.
    pub(crate) fn blame(&self) -> String {
        format!("{}:{}:{}", self.file, self.line, self.col)
    }

    /// The sugar module that SHOULD own this shape -- the `fix=` in a coverage gap.
    pub(crate) fn suggested_sugar_module(&self) -> String {
        let observed = self.observed();
        let snake = to_snake(observed.split(':').next().unwrap_or(&observed));
        format!("sugar::{snake}")
    }

    // -----------------------------------------------------------------------
    // Decomposition (hand-matched; the `_` arm is the new-shape detector)
    // -----------------------------------------------------------------------

    /// The immediate child fragments, in source order. A `&[Stmt]` suite (a function
    /// body / if-branch) becomes ONE Block fragment so it can be composed at the
    /// STATEMENT role by BlockSugar. Mirrors Python `SourceFragment.fragments()`.
    pub(crate) fn fragments(&self) -> Vec<SourceFragment<'a>> {
        match &self.node {
            // A synthetic Block decomposes into its statements.
            FragNode::Block(b) => b.stmts.iter().map(|s| Self::stmt(s, self.file)).collect(),

            // A File decomposes into Item fragments.
            FragNode::File(f) => {
                f.items.iter().map(|i| Self::from_node(FragNode::Item(i), self.file)).collect()
            }

            // Items: function body is the only child we expose at this granularity.
            FragNode::Item(syn::Item::Fn(f)) => {
                vec![Self::block(&f.block.stmts, self.file)]
            }

            // Statements: decompose into the inner expressions they carry.
            FragNode::Stmt(s) => stmt_child_fragments(s, self.file),

            // Expressions: decompose into their sub-expressions.
            FragNode::Expr(e) => expr_child_fragments(e, self.file),

            _ => Vec::new(),
        }
    }

    /// This fragment's statement children -- a body's lines. A `&[Stmt]` suite is one
    /// `Block` fragment (it composes its own statements at the STATEMENT role).
    pub(crate) fn statements(&self) -> Vec<SourceFragment<'a>> {
        match &self.node {
            FragNode::Block(b) => b.stmts.iter().map(|s| Self::stmt(s, self.file)).collect(),
            FragNode::Stmt(syn::Stmt::Expr(syn::Expr::If(i), _)) => {
                // an `if` decomposes into its then-Block and (optionally) its else-Block,
                // exactly like Python `IfSugar.build` -- "nesting is blocks within blocks".
                let mut out = vec![Self::block(&i.then_branch.stmts, self.file)];
                if let Some((_, else_expr)) = &i.else_branch {
                    out.push(Self::expr(else_expr, self.file));
                }
                out
            }
            FragNode::Expr(syn::Expr::If(i)) => {
                let mut out = vec![Self::block(&i.then_branch.stmts, self.file)];
                if let Some((_, else_expr)) = &i.else_branch {
                    out.push(Self::expr(else_expr, self.file));
                }
                out
            }
            _ => Vec::new(),
        }
    }

    /// This fragment as a series of expression children (the TERM role).
    /// Mirrors Python `SourceFragment.terms()`.
    pub(crate) fn terms(&self) -> Vec<SourceFragment<'a>> {
        self.fragments()
            .into_iter()
            .filter(|f| matches!(f.node, FragNode::Expr(_)))
            .collect()
    }

    // -----------------------------------------------------------------------
    // Body accessors
    // -----------------------------------------------------------------------

    /// The function body as a `Block` fragment (FunctionDef/ItemFn body).
    pub(crate) fn function_body(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Item(syn::Item::Fn(f)) => Some(Self::block(&f.block.stmts, self.file)),
            _ => None,
        }
    }

    // -----------------------------------------------------------------------
    // Typed accessors -- the ONLY sanctioned syn field access (Phase-4 ratchet)
    // -----------------------------------------------------------------------

    /// The condition expression of an `if` (Stmt or Expr).
    pub(crate) fn if_test(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Stmt(syn::Stmt::Expr(syn::Expr::If(i), _)) => {
                Some(Self::expr(&i.cond, self.file))
            }
            FragNode::Expr(syn::Expr::If(i)) => Some(Self::expr(&i.cond, self.file)),
            _ => None,
        }
    }

    /// The else branch of an `if`, if present.
    pub(crate) fn if_orelse(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Stmt(syn::Stmt::Expr(syn::Expr::If(i), _)) => {
                i.else_branch.as_ref().map(|(_, e)| Self::expr(e, self.file))
            }
            FragNode::Expr(syn::Expr::If(i)) => {
                i.else_branch.as_ref().map(|(_, e)| Self::expr(e, self.file))
            }
            _ => None,
        }
    }

    /// The value of a `return` statement.
    pub(crate) fn return_value(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Stmt(syn::Stmt::Expr(syn::Expr::Return(r), _)) => {
                r.expr.as_deref().map(|e| Self::expr(e, self.file))
            }
            FragNode::Expr(syn::Expr::Return(r)) => {
                r.expr.as_deref().map(|e| Self::expr(e, self.file))
            }
            _ => None,
        }
    }

    /// The identifier string for a `Path` (Name) node.
    pub(crate) fn name_id(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(syn::Expr::Path(p)) => p.path.get_ident().map(|i| i.to_string()),
            _ => None,
        }
    }

    // -- BinOp accessors ---------------------------------------------------

    /// Left operand of a `BinOp` expression.
    pub(crate) fn binop_left(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Expr(syn::Expr::Binary(b)) => Some(Self::expr(&b.left, self.file)),
            _ => None,
        }
    }

    /// Right operand of a `BinOp` expression.
    pub(crate) fn binop_right(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Expr(syn::Expr::Binary(b)) => Some(Self::expr(&b.right, self.file)),
            _ => None,
        }
    }

    /// Operator name of a `BinOp` expression (e.g. `"Add"`, `"Lt"`, `"BitAnd"`).
    pub(crate) fn binop_op_kind(&self) -> Option<&'static str> {
        match &self.node {
            FragNode::Expr(syn::Expr::Binary(b)) => Some(binop_kind(&b.op)),
            _ => None,
        }
    }

    // -- Compare accessors (syn merges binary + compare into Expr::Binary) -

    /// For `Expr::Binary` nodes that represent comparisons, same as `binop_left`.
    pub(crate) fn compare_left(&self) -> Option<SourceFragment<'a>> {
        self.binop_left()
    }

    /// For `Expr::Binary` comparison nodes, same as `binop_right` (single comparator).
    pub(crate) fn compare_right(&self) -> Option<SourceFragment<'a>> {
        self.binop_right()
    }

    // -- Call accessors ----------------------------------------------------

    /// The function being called (as a fragment). Works for both `Call` and `MethodCall`.
    pub(crate) fn call_func(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Expr(syn::Expr::Call(c)) => Some(Self::expr(&c.func, self.file)),
            _ => None,
        }
    }

    /// The function name for a plain `Call` where the callee is a path,
    /// or the method name for a `MethodCall`. Returns `None` for complex callees.
    pub(crate) fn call_target_name(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(syn::Expr::Call(c)) => {
                // plain call: last segment of the path
                match c.func.as_ref() {
                    syn::Expr::Path(p) => p.path.segments.last().map(|s| s.ident.to_string()),
                    _ => None,
                }
            }
            FragNode::Expr(syn::Expr::MethodCall(m)) => Some(m.method.to_string()),
            _ => None,
        }
    }

    /// Whether the call is a method call (`receiver.method(args)`).
    pub(crate) fn call_is_method_call(&self) -> bool {
        matches!(&self.node, FragNode::Expr(syn::Expr::MethodCall(_)))
    }

    /// The receiver expression for a `MethodCall`.
    pub(crate) fn call_receiver(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Expr(syn::Expr::MethodCall(m)) => Some(Self::expr(&m.receiver, self.file)),
            _ => None,
        }
    }

    /// Positional arguments for a `Call` or `MethodCall`.
    pub(crate) fn call_args(&self) -> Vec<SourceFragment<'a>> {
        match &self.node {
            FragNode::Expr(syn::Expr::Call(c)) => {
                c.args.iter().map(|a| Self::expr(a, self.file)).collect()
            }
            FragNode::Expr(syn::Expr::MethodCall(m)) => {
                m.args.iter().map(|a| Self::expr(a, self.file)).collect()
            }
            _ => Vec::new(),
        }
    }

    /// Number of positional arguments.
    pub(crate) fn call_arg_count(&self) -> usize {
        self.call_args().len()
    }

    // -- Literal accessor -------------------------------------------------

    /// The literal source text for a `PrimitiveLiteral` node. Returns the token's
    /// `.to_string()` representation. For typed accessors (parse as int/float/str)
    /// callers should match the inner `syn::Lit` themselves via `literal_value_str`.
    pub(crate) fn literal_value_str(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(syn::Expr::Lit(l)) => Some(lit_display(&l.lit)),
            _ => None,
        }
    }

    // -- Attribute (field) accessor ----------------------------------------

    /// The field name for a `Field` (attribute access) expression.
    pub(crate) fn attr_name(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(syn::Expr::Field(f)) => Some(match &f.member {
                syn::Member::Named(id) => id.to_string(),
                syn::Member::Unnamed(idx) => idx.index.to_string(),
            }),
            _ => None,
        }
    }

    // -- Assign accessor (let-binding) ------------------------------------

    /// The name bound in a `let` statement (single-ident patterns only).
    pub(crate) fn assign_target_name(&self) -> Option<String> {
        match &self.node {
            FragNode::Stmt(syn::Stmt::Local(l)) => match &l.pat {
                syn::Pat::Ident(p) => Some(p.ident.to_string()),
                syn::Pat::Type(pt) => {
                    if let syn::Pat::Ident(p) = pt.pat.as_ref() {
                        Some(p.ident.to_string())
                    } else {
                        None
                    }
                }
                _ => None,
            },
            _ => None,
        }
    }

    /// The initialiser expression of a `let` statement.
    pub(crate) fn assign_value(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Stmt(syn::Stmt::Local(l)) => {
                l.init.as_ref().map(|init| Self::expr(&init.expr, self.file))
            }
            _ => None,
        }
    }
}

// ---------------------------------------------------------------------------
// parse helper
// ---------------------------------------------------------------------------

/// Parse Rust source and return the root `File` fragment. Test/entry constructor; the
/// returned fragment borrows from `parsed`, so callers hold the `syn::File` alive.
pub(crate) fn parse_file(source: &str) -> syn::File {
    syn::parse_file(source).expect("source_fragment: parse_file failed")
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

fn node_position(node: &FragNode<'_>) -> (usize, usize) {
    let span = match node {
        FragNode::File(_) => return (0, 0),
        FragNode::Block(b) => return (b.line, b.col),
        FragNode::Item(i) => i.span(),
        FragNode::Stmt(s) => s.span(),
        FragNode::Expr(e) => e.span(),
    };
    (span.start().line, span.start().column)
}

fn expr_kind(e: &syn::Expr) -> String {
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
        // `#[non_exhaustive]`: every unhandled variant becomes a parametric bucket --
        // never a silent drop. This is the rust new-shape detector.
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

fn stmt_kind(s: &syn::Stmt) -> &'static str {
    match s {
        syn::Stmt::Local(_) => "Assign",
        syn::Stmt::Item(_) => "Item",
        syn::Stmt::Macro(_) => "Macro",
        syn::Stmt::Expr(syn::Expr::Return(_), _) => "Return",
        syn::Stmt::Expr(syn::Expr::If(_), _) => "If",
        syn::Stmt::Expr(_, _) => "Expr",
    }
}

fn item_kind(i: &syn::Item) -> &'static str {
    match i {
        syn::Item::Fn(_) => "FunctionDef",
        syn::Item::Const(_) => "Const",
        syn::Item::Impl(_) => "Impl",
        syn::Item::Struct(_) => "Struct",
        syn::Item::Enum(_) => "Enum",
        syn::Item::Use(_) => "Use",
        _ => "Other:Item",
    }
}

fn binop_kind(op: &syn::BinOp) -> &'static str {
    use syn::BinOp::*;
    match op {
        Add(_) => "Add",
        Sub(_) => "Sub",
        Mul(_) => "Mul",
        Div(_) => "Div",
        Rem(_) => "Rem",
        And(_) => "And",
        Or(_) => "Or",
        BitXor(_) => "BitXor",
        BitAnd(_) => "BitAnd",
        BitOr(_) => "BitOr",
        Shl(_) => "Shl",
        Shr(_) => "Shr",
        Eq(_) => "Eq",
        Lt(_) => "Lt",
        Le(_) => "Le",
        Ne(_) => "Ne",
        Ge(_) => "Ge",
        Gt(_) => "Gt",
        AddAssign(_) => "AddAssign",
        SubAssign(_) => "SubAssign",
        MulAssign(_) => "MulAssign",
        DivAssign(_) => "DivAssign",
        RemAssign(_) => "RemAssign",
        BitXorAssign(_) => "BitXorAssign",
        BitAndAssign(_) => "BitAndAssign",
        BitOrAssign(_) => "BitOrAssign",
        ShlAssign(_) => "ShlAssign",
        ShrAssign(_) => "ShrAssign",
        _ => "Other",
    }
}

fn lit_display(lit: &syn::Lit) -> String {
    match lit {
        syn::Lit::Str(s) => s.value(),
        syn::Lit::Int(i) => i.base10_digits().to_string(),
        syn::Lit::Float(f) => f.base10_digits().to_string(),
        syn::Lit::Bool(b) => b.value.to_string(),
        syn::Lit::Char(c) => c.value().to_string(),
        syn::Lit::Byte(b) => b.value().to_string(),
        _ => format!("{}", lit.span().start().line),
    }
}

/// Child fragments of a statement node. A `Stmt::Expr(e, _)` wraps `e` as ONE child
/// (the expression itself), not its sub-expressions -- that matches Python where
/// `ast.Expr(value=BinOp(...))` has `BinOp` as its sole AST child via iter_fields.
fn stmt_child_fragments<'a>(s: &'a syn::Stmt, file: &'a str) -> Vec<SourceFragment<'a>> {
    match s {
        syn::Stmt::Local(l) => {
            if let Some(init) = &l.init {
                vec![SourceFragment::expr(&init.expr, file)]
            } else {
                Vec::new()
            }
        }
        syn::Stmt::Item(i) => vec![SourceFragment::from_node(FragNode::Item(i), file)],
        // Wrap the expression itself -- callers who want sub-expressions call
        // fragments()/terms() on the returned expression fragment.
        syn::Stmt::Expr(e, _) => vec![SourceFragment::expr(e, file)],
        syn::Stmt::Macro(_) => Vec::new(),
    }
}

/// Child expression fragments of an expression node (hand-matched decomposition).
fn expr_child_fragments<'a>(e: &'a syn::Expr, file: &'a str) -> Vec<SourceFragment<'a>> {
    use syn::Expr::*;
    match e {
        Binary(b) => vec![
            SourceFragment::expr(&b.left, file),
            SourceFragment::expr(&b.right, file),
        ],
        Unary(u) => vec![SourceFragment::expr(&u.expr, file)],
        Call(c) => {
            let mut out = vec![SourceFragment::expr(&c.func, file)];
            out.extend(c.args.iter().map(|a| SourceFragment::expr(a, file)));
            out
        }
        MethodCall(m) => {
            let mut out = vec![SourceFragment::expr(&m.receiver, file)];
            out.extend(m.args.iter().map(|a| SourceFragment::expr(a, file)));
            out
        }
        If(i) => {
            // condition + then-Block + optional else
            let mut out = vec![
                SourceFragment::expr(&i.cond, file),
                SourceFragment::block(&i.then_branch.stmts, file),
            ];
            if let Some((_, else_expr)) = &i.else_branch {
                out.push(SourceFragment::expr(else_expr, file));
            }
            out
        }
        Block(b) => b.block.stmts.iter().map(|s| SourceFragment::stmt(s, file)).collect(),
        Return(r) => r.expr.as_deref().map(|e| SourceFragment::expr(e, file)).into_iter().collect(),
        Field(f) => vec![SourceFragment::expr(&f.base, file)],
        Index(i) => vec![
            SourceFragment::expr(&i.expr, file),
            SourceFragment::expr(&i.index, file),
        ],
        Reference(r) => vec![SourceFragment::expr(&r.expr, file)],
        Paren(p) => vec![SourceFragment::expr(&p.expr, file)],
        Cast(c) => vec![SourceFragment::expr(&c.expr, file)],
        Assign(a) => vec![
            SourceFragment::expr(&a.left, file),
            SourceFragment::expr(&a.right, file),
        ],
        Array(a) => a.elems.iter().map(|e| SourceFragment::expr(e, file)).collect(),
        Tuple(t) => t.elems.iter().map(|e| SourceFragment::expr(e, file)).collect(),
        Range(r) => {
            let mut out = Vec::new();
            if let Some(from) = &r.start {
                out.push(SourceFragment::expr(from, file));
            }
            if let Some(to) = &r.end {
                out.push(SourceFragment::expr(to, file));
            }
            out
        }
        Match(m) => {
            let mut out = vec![SourceFragment::expr(&m.expr, file)];
            for arm in &m.arms {
                out.push(SourceFragment::expr(&arm.body, file));
            }
            out
        }
        _ => Vec::new(),
    }
}

fn to_snake(camel: &str) -> String {
    let mut out = String::new();
    for (i, ch) in camel.chars().enumerate() {
        if ch.is_ascii_uppercase() && i != 0 {
            out.push('_');
        }
        out.push(ch.to_ascii_lowercase());
    }
    out
}

// ---------------------------------------------------------------------------
// Tests -- the from_src/parse_file harness: source string -> fragment ->
// observed/decompose/accessor asserts. No parse_quote!/stub plumbing.
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn root_fn_item(file: &syn::File) -> &syn::Item {
        &file.items[0]
    }

    fn fn_frag<'a>(item: &'a syn::Item, file_str: &'a str) -> SourceFragment<'a> {
        SourceFragment::from_node(FragNode::Item(item), file_str)
    }

    /// The door: a source string -> fragment -> observed/blame/decomposition, with no
    /// raw-syn plumbing in the test (this is the Phase-4 per-sugar TDD harness in miniature).
    #[test]
    fn classify_body_decomposes_through_the_door() {
        let file = parse_file(
            "fn classify(n: u32) -> u32 {\n    if n > 5 { return 50; }\n    0\n}\n",
        );
        let root = SourceFragment::from_node(FragNode::File(&file), "classify.rs");
        // first item is the fn
        let item = match &root.node {
            FragNode::File(f) => &f.items[0],
            _ => unreachable!(),
        };
        let frag = SourceFragment::from_node(FragNode::Item(item), "classify.rs");
        assert_eq!(frag.observed(), "FunctionDef");

        let body = frag.function_body().expect("fn has a body Block");
        assert_eq!(body.observed(), "Block");
        let stmts = body.statements();
        assert_eq!(stmts.len(), 2); // the `if` and the tail `0`
        assert_eq!(stmts[0].observed(), "If");

        // the `if` decomposes into its then-Block
        let then_block = &stmts[0].statements()[0];
        assert_eq!(then_block.observed(), "Block");
        assert_eq!(then_block.statements()[0].observed(), "Return");

        // the guard term
        let test = stmts[0].if_test().expect("if has a test");
        assert_eq!(test.observed(), "BinOp");
    }

    #[test]
    fn unknown_expr_shape_falls_to_a_parametric_bucket_not_a_drop() {
        let file = parse_file("fn f() { let _ = |x| x; }\n");
        let local = match &file.items[0] {
            syn::Item::Fn(f) => &f.block.stmts[0],
            _ => unreachable!(),
        };
        // a closure is an Expr variant observed() does not name -> parametric bucket
        if let syn::Stmt::Local(l) = local {
            let init = &l.init.as_ref().unwrap().expr;
            let frag = SourceFragment::from_node(FragNode::Expr(init), "f.rs");
            assert!(frag.observed().starts_with("Other:Expr:Closure"));
        } else {
            panic!("expected a let");
        }
    }

    // -----------------------------------------------------------------------
    // New tests: If / Block / Return / BinOp / Call / Name / PrimitiveLiteral
    // -----------------------------------------------------------------------

    #[test]
    fn if_fragment_observed_and_test_accessor() {
        let src = "fn f(x: i32) -> i32 { if x > 0 { return 1; } else { return -1; } 0 }";
        let file = parse_file(src);
        let item = root_fn_item(&file);
        let frag = fn_frag(item, "f.rs");
        let body = frag.function_body().unwrap();
        let stmts = body.statements();
        // first stmt is the `if`
        let if_frag = &stmts[0];
        assert_eq!(if_frag.observed(), "If");

        // if_test: x > 0 is a BinOp
        let test = if_frag.if_test().expect("if has test");
        assert_eq!(test.observed(), "BinOp");

        // branches via statements()
        let branches = if_frag.statements();
        assert_eq!(branches.len(), 2, "then + else");
        assert_eq!(branches[0].observed(), "Block"); // then-block
        assert_eq!(branches[1].observed(), "Block"); // else { ... } is Expr::Block in syn

        // if_orelse exists
        assert!(if_frag.if_orelse().is_some());
    }

    #[test]
    fn block_fragment_decomposes_into_statements() {
        let src = "fn f() { let x = 1; let y = 2; x + y }";
        let file = parse_file(src);
        let frag = fn_frag(root_fn_item(&file), "f.rs");
        let body = frag.function_body().unwrap();
        assert_eq!(body.observed(), "Block");
        let stmts = body.statements();
        assert_eq!(stmts.len(), 3);
        assert_eq!(stmts[0].observed(), "Assign");
        assert_eq!(stmts[1].observed(), "Assign");
        assert_eq!(stmts[2].observed(), "Expr");
    }

    #[test]
    fn return_fragment_and_return_value_accessor() {
        let src = "fn f() -> u32 { return 42; }";
        let file = parse_file(src);
        let frag = fn_frag(root_fn_item(&file), "f.rs");
        let body = frag.function_body().unwrap();
        let stmts = body.statements();
        assert_eq!(stmts[0].observed(), "Return");
        let val = stmts[0].return_value().expect("return has value");
        assert_eq!(val.observed(), "PrimitiveLiteral");
        assert_eq!(val.literal_value_str().unwrap(), "42");
    }

    #[test]
    fn binop_left_right_and_op_kind() {
        let src = "fn f(a: i32, b: i32) -> i32 { a + b }";
        let file = parse_file(src);
        let frag = fn_frag(root_fn_item(&file), "f.rs");
        let body = frag.function_body().unwrap();
        let expr_frag = &body.statements()[0]; // tail expr
        assert_eq!(expr_frag.observed(), "Expr");
        // get the inner expression fragment via terms()
        let terms = expr_frag.terms();
        let binop = &terms[0];
        assert_eq!(binop.observed(), "BinOp");
        assert_eq!(binop.binop_op_kind(), Some("Add"));
        let left = binop.binop_left().unwrap();
        let right = binop.binop_right().unwrap();
        assert_eq!(left.observed(), "Name");
        assert_eq!(right.observed(), "Name");
        assert_eq!(left.name_id().unwrap(), "a");
        assert_eq!(right.name_id().unwrap(), "b");
    }

    #[test]
    fn call_target_name_and_args() {
        let src = r#"fn f() -> usize { foo(1, 2) }"#;
        let file = parse_file(src);
        let frag = fn_frag(root_fn_item(&file), "f.rs");
        let body = frag.function_body().unwrap();
        let tail = &body.statements()[0];
        let terms = tail.terms();
        let call = &terms[0];
        assert_eq!(call.observed(), "Call");
        assert_eq!(call.call_target_name().as_deref(), Some("foo"));
        assert!(!call.call_is_method_call());
        let args = call.call_args();
        assert_eq!(args.len(), 2);
        assert_eq!(args[0].observed(), "PrimitiveLiteral");
        assert_eq!(args[0].literal_value_str().unwrap(), "1");
    }

    #[test]
    fn method_call_receiver_and_target_name() {
        let src = r#"fn f(s: &str) -> usize { s.len() }"#;
        let file = parse_file(src);
        let frag = fn_frag(root_fn_item(&file), "f.rs");
        let body = frag.function_body().unwrap();
        let tail = &body.statements()[0];
        let terms = tail.terms();
        let call = &terms[0];
        assert_eq!(call.observed(), "MethodCall");
        assert!(call.call_is_method_call());
        assert_eq!(call.call_target_name().as_deref(), Some("len"));
        let recv = call.call_receiver().unwrap();
        assert_eq!(recv.observed(), "Name");
    }

    #[test]
    fn name_fragment_name_id() {
        let src = "fn f(x: u32) -> u32 { x }";
        let file = parse_file(src);
        let frag = fn_frag(root_fn_item(&file), "f.rs");
        let body = frag.function_body().unwrap();
        let tail = &body.statements()[0];
        let terms = tail.terms();
        let name_frag = &terms[0];
        assert_eq!(name_frag.observed(), "Name");
        assert_eq!(name_frag.name_id().unwrap(), "x");
    }

    #[test]
    fn primitive_literal_int_str_bool() {
        for (src, expected_val) in &[
            ("fn f() -> i32 { 99 }", "99"),
            (r#"fn f() -> &str { "hello" }"#, "hello"),
            ("fn f() -> bool { true }", "true"),
        ] {
            let file = parse_file(src);
            let frag = fn_frag(root_fn_item(&file), "f.rs");
            let body = frag.function_body().unwrap();
            let tail = &body.statements()[0];
            let terms = tail.terms();
            let lit = &terms[0];
            assert_eq!(lit.observed(), "PrimitiveLiteral", "src={src}");
            assert_eq!(
                lit.literal_value_str().as_deref(),
                Some(*expected_val),
                "src={src}"
            );
        }
    }

    #[test]
    fn assign_target_name_and_value() {
        let src = "fn f() { let answer = 42; }";
        let file = parse_file(src);
        let frag = fn_frag(root_fn_item(&file), "f.rs");
        let body = frag.function_body().unwrap();
        let let_stmt = &body.statements()[0];
        assert_eq!(let_stmt.observed(), "Assign");
        assert_eq!(let_stmt.assign_target_name().as_deref(), Some("answer"));
        let val = let_stmt.assign_value().unwrap();
        assert_eq!(val.observed(), "PrimitiveLiteral");
        assert_eq!(val.literal_value_str().unwrap(), "42");
    }

    #[test]
    fn fragments_decomposes_binop_into_two_expr_children() {
        let src = "fn f(a: i32, b: i32) -> i32 { a - b }";
        let file = parse_file(src);
        let frag = fn_frag(root_fn_item(&file), "f.rs");
        let body = frag.function_body().unwrap();
        let tail_frag = &body.statements()[0]; // Expr stmt
        let terms = tail_frag.terms(); // picks expr children
        let binop = &terms[0];
        assert_eq!(binop.observed(), "BinOp");
        let children = binop.fragments();
        assert_eq!(children.len(), 2);
        assert_eq!(children[0].observed(), "Name"); // a
        assert_eq!(children[1].observed(), "Name"); // b
    }

    #[test]
    fn terms_filters_to_expression_children_only() {
        let src = "fn f(a: i32) -> i32 { a * 2 }";
        let file = parse_file(src);
        let frag = fn_frag(root_fn_item(&file), "f.rs");
        let body = frag.function_body().unwrap();
        let tail_frag = &body.statements()[0];
        let terms = tail_frag.terms();
        // tail is an Expr stmt containing a BinOp -- terms() should yield that BinOp
        assert_eq!(terms.len(), 1);
        assert_eq!(terms[0].observed(), "BinOp");
        assert_eq!(terms[0].binop_op_kind(), Some("Mul"));
    }

    #[test]
    fn other_wildcard_is_parametric_and_not_silent() {
        // ForLoop is an Expr variant in the Other: bucket
        let src = "fn f(v: &[i32]) { for _x in v.iter() {} }";
        let file = parse_file(src);
        let frag = fn_frag(root_fn_item(&file), "f.rs");
        let body = frag.function_body().unwrap();
        let stmt = &body.statements()[0];
        // The for loop is an Expr statement; its expr is ForLoop
        let terms = stmt.terms();
        assert!(!terms.is_empty(), "for loop expr should appear as a term");
        let for_frag = &terms[0];
        assert!(
            for_frag.observed().starts_with("Other:Expr:ForLoop"),
            "got: {}",
            for_frag.observed()
        );
    }

    #[test]
    fn blame_includes_file_and_position() {
        let src = "fn f() -> u32 { 1 }";
        let file = parse_file(src);
        let frag = fn_frag(root_fn_item(&file), "myfile.rs");
        let blame = frag.blame();
        assert!(blame.starts_with("myfile.rs:"), "blame={blame}");
    }

    #[test]
    fn suggested_sugar_module_maps_primitive_literal() {
        let src = "fn f() -> i32 { 7 }";
        let file = parse_file(src);
        let frag = fn_frag(root_fn_item(&file), "f.rs");
        let body = frag.function_body().unwrap();
        let tail = &body.statements()[0];
        let terms = tail.terms();
        let lit = &terms[0];
        assert_eq!(lit.observed(), "PrimitiveLiteral");
        assert_eq!(lit.suggested_sugar_module(), "sugar::primitive_literal");
    }

    #[test]
    fn suggested_sugar_module_maps_bin_op() {
        let src = "fn f(a: i32) -> i32 { a + 1 }";
        let file = parse_file(src);
        let frag = fn_frag(root_fn_item(&file), "f.rs");
        let body = frag.function_body().unwrap();
        let tail = &body.statements()[0];
        let terms = tail.terms();
        let binop = &terms[0];
        assert_eq!(binop.observed(), "BinOp");
        assert_eq!(binop.suggested_sugar_module(), "sugar::bin_op");
    }
}
