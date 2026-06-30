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
use quote;

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

/// Data decoded from an `Expr::Lit` (`PrimitiveLiteral` / `Lit`) fragment,
/// holding ONLY host-native types -- no raw `syn`. `CStr` is absent because
/// it is not a scalar liftable by `TermLiteralSugar` (the recognizer returns
/// `None` for it). `Other` captures `Verbatim` and any future non-exhaustive
/// `syn::Lit` variants so the sugar can report a consistent gap panic.
///
/// All variants mirror the `syn::Lit` arms of `translate_lit` one-to-one;
/// `scalar_lit_to_term` in `term_literal.rs` produces a byte-identical `Term`
/// from this enum as `translate_lit` would from the original `&ExprLit`.
#[derive(Clone, Debug)]
pub(crate) enum ScalarLit {
    /// A `syn::Lit::Int` literal.
    ///
    /// `token_text` is the full source token (`syn::LitInt::to_string()`),
    /// e.g., `"42"`, `"0xFFu8"`, `"0b1010usize"`. `suffix` is the type
    /// suffix (`syn::LitInt::suffix()`), e.g., `""`, `"u8"`, `"u128"`.
    Int { token_text: String, suffix: String },
    /// A `syn::Lit::Float` literal.
    ///
    /// `base10_digits` is `syn::LitFloat::base10_digits()` (no suffix;
    /// may still contain `e`/`E` exponent markers and underscores).
    Float { base10_digits: String },
    /// A `syn::Lit::Str` literal. `value` is the unescaped string content.
    Str(String),
    /// A `syn::Lit::Char` literal.
    Char(char),
    /// A `syn::Lit::Bool` literal.
    Bool(bool),
    /// A `syn::Lit::ByteStr` literal (`b"…"`). `bytes` is the decoded byte vector.
    ByteStr(Vec<u8>),
    /// A `syn::Lit::Byte` literal (`b'x'`). `value` is the decoded byte.
    Byte(u8),
    /// Any other `syn::Lit` variant (e.g., `Verbatim`). `token` is the
    /// token-stream string for the gap panic message.
    Other(String),
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
    pub(crate) fn item(i: &'a syn::Item, file: &'a str) -> Self {
        Self::from_node(FragNode::Item(i), file)
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

    /// The base expression of an `Expr::Await` (`expr` in `expr.await`).
    /// Returns `None` for any non-`Await` fragment.
    pub(crate) fn await_base(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Expr(syn::Expr::Await(a)) => Some(Self::expr(&a.base, self.file)),
            _ => None,
        }
    }

    /// The inner expression of a `Paren` (`(expr)`) or `Group` node.
    /// Returns `None` for any other fragment kind.
    pub(crate) fn transparent_inner(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Expr(syn::Expr::Paren(p)) => Some(Self::expr(&p.expr, self.file)),
            FragNode::Expr(syn::Expr::Group(g)) => Some(Self::expr(&g.expr, self.file)),
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

    // -- UnaryOp accessors -------------------------------------------------

    /// The operand of a `UnaryOp` expression (`x` in `-x`, `!x`, `*x`).
    pub(crate) fn unary_operand(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Expr(syn::Expr::Unary(u)) => Some(Self::expr(&u.expr, self.file)),
            _ => None,
        }
    }

    /// The operator kind for a `UnaryOp` expression: `"Neg"` for `-`, `"Not"` for
    /// `!`, `"Deref"` for `*`. Returns `None` for non-unary fragments. Unknown
    /// future operators (non-exhaustive `syn::UnOp`) return `Some("Other")`.
    pub(crate) fn unary_op_kind(&self) -> Option<&'static str> {
        match &self.node {
            FragNode::Expr(syn::Expr::Unary(u)) => Some(match u.op {
                syn::UnOp::Neg(_) => "Neg",
                syn::UnOp::Not(_) => "Not",
                syn::UnOp::Deref(_) => "Deref",
                _ => "Other",
            }),
            _ => None,
        }
    }

    // -- Index accessors ---------------------------------------------------

    /// The container (receiver) of an `Index` expression (`a` in `a[i]`).
    pub(crate) fn index_receiver(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Expr(syn::Expr::Index(i)) => Some(Self::expr(&i.expr, self.file)),
            _ => None,
        }
    }

    /// The index expression of an `Index` expression (`i` in `a[i]`).
    pub(crate) fn index_index(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Expr(syn::Expr::Index(i)) => Some(Self::expr(&i.index, self.file)),
            _ => None,
        }
    }

    // -- Field accessor ----------------------------------------------------

    /// The base/receiver of a `Field` expression (`base` in `base.member`).
    pub(crate) fn field_receiver(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Expr(syn::Expr::Field(f)) => Some(Self::expr(&f.base, self.file)),
            _ => None,
        }
    }

    /// Whether the member of a `Field` expression is unnamed (tuple-style, e.g. `.0`).
    /// Returns `false` for named fields and for non-`Field` nodes.
    pub(crate) fn field_is_unnamed(&self) -> bool {
        match &self.node {
            FragNode::Expr(syn::Expr::Field(f)) => {
                matches!(f.member, syn::Member::Unnamed(_))
            }
            _ => false,
        }
    }

    /// The tuple index of an unnamed `Field` member (e.g. `1` for `.1`).
    /// Returns `None` for named fields or non-`Field` nodes.
    pub(crate) fn field_tuple_index(&self) -> Option<usize> {
        match &self.node {
            FragNode::Expr(syn::Expr::Field(f)) => {
                if let syn::Member::Unnamed(idx) = &f.member {
                    Some(idx.index as usize)
                } else {
                    None
                }
            }
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

    /// Const-folds a `BinOp` (`Expr::Binary`) expression to a `Term` via the
    /// exact-or-bail `const_eval` + `const_val_term` path. Returns `None` for
    /// non-Binary fragments or expressions that contain non-const sub-expressions.
    /// Mirrors `const_folded_if_term` but for `Expr::Binary`.
    pub(crate) fn binop_const_folded_term(
        &self,
    ) -> Option<std::rc::Rc<sugar_ir_symbolic::Term>> {
        let e = match &self.node {
            FragNode::Expr(e @ syn::Expr::Binary(_)) => e,
            _ => return None,
        };
        crate::const_eval(e, &std::collections::BTreeMap::new())
            .and_then(|v| crate::const_val_term(&v))
    }

    /// The `RelationOp` for a `BinOp` comparison expression
    /// (`==`, `!=`, `<`, `<=`, `>`, `>=`). Returns `None` for non-Binary
    /// fragments or operators that are not comparisons.
    pub(crate) fn binop_relation(&self) -> Option<crate::RelationOp> {
        match &self.node {
            FragNode::Expr(syn::Expr::Binary(b)) => crate::relation_from_binop(&b.op),
            _ => None,
        }
    }

    /// The arithmetic term-binop name for a `BinOp` expression
    /// (e.g. `"+"` for `Add`, `"int-div"` for `Div`, `"*"` for `Mul`).
    /// Returns `None` for non-Binary fragments, comparison operators,
    /// logical-and/or, or any operator not in the arithmetic table.
    pub(crate) fn binop_term_name(&self) -> Option<&'static str> {
        match &self.node {
            FragNode::Expr(syn::Expr::Binary(b)) => crate::term_binop_name(&b.op),
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

    /// The full method key for a `MethodCall` fragment: bare method name, with the
    /// turbofish angle-args key appended when present (e.g. `"parse::<i32>"` for
    /// `recv.parse::<i32>()`). Returns `None` for any non-`MethodCall` fragment.
    /// Produces byte-identical output to `crate::sugar::method::method_key`.
    pub(crate) fn call_method_key(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(syn::Expr::MethodCall(m)) => Some(match &m.turbofish {
                Some(args) => format!("{}{}", m.method, crate::angle_args_key(args)),
                None => m.method.to_string(),
            }),
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

    /// The "head key" of a `Call` expression -- the canonical callee name used in
    /// `call:<head>` ctor names. Delegates to `crate::expr_head_key` on the internal
    /// func expression. Returns `None` for non-`Call` fragments.
    pub(crate) fn call_head_key(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(syn::Expr::Call(c)) => Some(crate::expr_head_key(&c.func)),
            _ => None,
        }
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

    // -- Path accessors ----------------------------------------------------

    /// The full path name for an `Expr::Path` node -- segments joined with `::`,
    /// argument keys included. For `x` this is `"x"`; for `Foo::BAR` it is
    /// `"Foo::BAR"`. Equivalent to `crate::path_to_name` applied to the inner
    /// `Path`. Returns `None` for non-path nodes.
    pub(crate) fn path_full_name(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(syn::Expr::Path(p)) => Some(crate::path_to_name(&p.path)),
            _ => None,
        }
    }

    /// The token-stream string for an `Expr::Path` node (e.g. `"Foo :: BAR"`).
    /// Used for diagnostic `boundary` strings in `AmbiguousTemporalIdentity`
    /// effects. Returns `None` for non-path nodes.
    pub(crate) fn path_token_str(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(syn::Expr::Path(p)) => {
                Some(quote::ToTokens::to_token_stream(p).to_string())
            }
            _ => None,
        }
    }

    /// For an `Expr::Path` with NO qualified self and a single bare ident,
    /// returns that ident string. Returns `None` for qualified paths
    /// (`<T as Trait>::Assoc`), multi-segment paths, or non-path nodes.
    /// Differs from `name_id()` in that `qself` must be absent.
    pub(crate) fn path_simple_ident(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(syn::Expr::Path(p)) if p.qself.is_none() => {
                p.path.get_ident().map(|i| i.to_string())
            }
            _ => None,
        }
    }

    /// The last path-segment ident for an `Expr::Path` node.
    /// E.g., for `u32::midpoint`, returns `Some("midpoint")`.
    /// Returns `None` for non-path nodes or empty paths.
    pub(crate) fn path_last_segment_ident(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(syn::Expr::Path(p)) => {
                p.path.segments.last().map(|s| s.ident.to_string())
            }
            _ => None,
        }
    }

    /// For an `Expr::Path` with a `qself` (`<T>::method`), returns the simple
    /// type name from the qself `Type::Path` last segment.
    /// E.g., for `<u32>::midpoint`, returns `Some("u32")`.
    /// Returns `None` for paths without qself, non-`Type::Path` qself types,
    /// or non-path nodes.
    pub(crate) fn path_qself_simple_type_name(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(syn::Expr::Path(p)) => {
                let qself = p.qself.as_ref()?;
                let syn::Type::Path(ty) = qself.ty.as_ref() else {
                    return None;
                };
                ty.path.segments.last().map(|s| s.ident.to_string())
            }
            _ => None,
        }
    }

    /// The second-to-last path-segment ident for an `Expr::Path` node.
    /// E.g., for `u32::midpoint` (two segments), returns `Some("u32")`.
    /// Returns `None` for single-segment paths or non-path nodes.
    pub(crate) fn path_penultimate_ident(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(syn::Expr::Path(p)) => {
                p.path.segments.iter().rev().nth(1).map(|s| s.ident.to_string())
            }
            _ => None,
        }
    }

    // -- partition_point fold accessor ----------------------------------------

    /// For a `.partition_point(|param| pred)` method call whose receiver is a
    /// literal scalar array, const-evaluates the predicate on each element in
    /// the host, verifies that the results form a valid partition (all satisfying
    /// elements precede all non-satisfying ones), and returns the count of leading
    /// satisfying elements as an `i128` index. Returns `None` if the fragment is
    /// not this shape, any element or closure body cannot be const-evaluated, or
    /// the slice is not properly partitioned (which signals a contract misuse;
    /// we decline rather than replicate the binary-search-defined value).
    pub(crate) fn partition_point_literal_index(&self) -> Option<i128> {
        let call = match &self.node {
            FragNode::Expr(syn::Expr::MethodCall(m)) => m,
            _ => return None,
        };
        if call.method != "partition_point" || call.args.len() != 1 {
            return None;
        }
        let syn::Expr::Closure(closure) = crate::strip_refs_groups(&call.args[0]) else {
            return None;
        };
        let elems =
            crate::scalar_literal_array_elems(crate::strip_refs_groups(&call.receiver))?;
        let empty: std::collections::BTreeMap<String, crate::ConstVal> =
            std::collections::BTreeMap::new();
        let mut preds = Vec::with_capacity(elems.len());
        for e in &elems {
            let value = crate::const_eval(e, &empty)?;
            let pred = crate::const_eval_unary_closure(closure, &value)?.as_bool()?;
            preds.push(pred);
        }
        // PARTITIONED check: no satisfying element after a non-satisfying one.
        // Otherwise the result is binary-search-defined (contract misuse) and
        // we decline rather than guess.
        let mut seen_false = false;
        for &p in &preds {
            if p && seen_false {
                return None;
            }
            seen_false |= !p;
        }
        Some(preds.iter().filter(|&&p| p).count() as i128)
    }

    // -- Const-fold If accessor -----------------------------------------------

    /// Const-folds an `Expr::If` fragment to its resolved `Term` via the exact-
    /// or-bail `const_eval` + `const_val_term` path. The condition is evaluated
    /// with an empty environment (closed expression only); the taken branch's tail
    /// value is folded to a `Term`. Returns `None` for any non-`If` fragment, for
    /// an `if`-without-else, or for any `If` whose condition or taken branch
    /// contains a non-const sub-expression. Callers see `Option<Rc<Term>>`; all
    /// raw `syn` evaluator logic stays in lib.rs.
    pub(crate) fn const_folded_if_term(
        &self,
    ) -> Option<std::rc::Rc<sugar_ir_symbolic::Term>> {
        let e = match &self.node {
            FragNode::Expr(e @ syn::Expr::If(_)) => e,
            _ => return None,
        };
        use std::collections::BTreeMap;
        crate::const_eval(e, &BTreeMap::new())
            .and_then(|v| crate::const_val_term(&v))
    }

    // -- Reference/paren/group stripping -------------------------------------

    /// Strip `Reference`, `Paren`, and `Group` wrappers from an expression
    /// fragment, returning the innermost non-wrapper fragment. Non-`Expr`
    /// fragments are returned unchanged (nothing to strip). Mirrors the
    /// crate-level `strip_refs_groups` helper used in recognizer bodies
    /// before this accessor was added, but operates entirely on fragments so
    /// recognizers need not escape to raw syn.
    pub(crate) fn strip_refs_groups(self) -> SourceFragment<'a> {
        match &self.node {
            FragNode::Expr(syn::Expr::Reference(r)) => {
                Self::expr(&r.expr, self.file).strip_refs_groups()
            }
            FragNode::Expr(syn::Expr::Paren(p)) => {
                Self::expr(&p.expr, self.file).strip_refs_groups()
            }
            FragNode::Expr(syn::Expr::Group(g)) => {
                Self::expr(&g.expr, self.file).strip_refs_groups()
            }
            _ => self,
        }
    }

    // -- Reference accessors -------------------------------------------------

    /// Whether an `Expr::Reference` fragment is a mutable borrow (`&mut expr`).
    /// Returns `false` for any non-`Reference` fragment or a shared reference.
    pub(crate) fn reference_is_mutable(&self) -> bool {
        match &self.node {
            FragNode::Expr(syn::Expr::Reference(r)) => r.mutability.is_some(),
            _ => false,
        }
    }

    /// The inner expression of an `Expr::Reference` fragment.
    /// Returns `None` for any non-`Reference` fragment.
    pub(crate) fn reference_inner(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Expr(syn::Expr::Reference(r)) => Some(Self::expr(&r.expr, self.file)),
            _ => None,
        }
    }

    // -- Escape-hatch accessors (transitional shim) -------------------------

    /// Returns the inner `&'a syn::Expr` with the fragment's own lifetime `'a`, not
    /// shortened to the borrow of `self`. This matters when callers take `self` by
    /// value (e.g. helper fns that return `SourceFragment<'a>` built from the fields
    /// of the same fragment): matching on `self.node` (Copy) gives `e: &'a syn::Expr`
    /// directly so the caller can use `self.file` in the same scope without a
    /// borrow-checker conflict. Without the explicit `'a`, Rust would tie the returned
    /// `&syn::Expr` to the lifetime of `&self`, blocking subsequent use of `self`.
    pub(crate) fn as_expr(&self) -> Option<&'a syn::Expr> {
        match self.node {
            FragNode::Expr(e) => Some(e),
            _ => None,
        }
    }

    pub(crate) fn as_stmt(&self) -> Option<&syn::Stmt> {
        match &self.node {
            FragNode::Stmt(s) => Some(s),
            _ => None,
        }
    }

    pub(crate) fn as_item(&self) -> Option<&syn::Item> {
        match &self.node {
            FragNode::Item(i) => Some(i),
            _ => None,
        }
    }

    // -- Token-stream string accessor -----------------------------------------

    /// Normalized token-stream string for this fragment (whitespace-collapsed).
    /// Mirrors `token_key` in `lib.rs`: joins whitespace-split tokens with a
    /// single space. Used to produce `boundary` strings without escaping to
    /// raw syn in recognizer bodies.
    pub(crate) fn token_str(&self) -> String {
        let ts = match &self.node {
            FragNode::Expr(e) => quote::ToTokens::to_token_stream(e),
            FragNode::Stmt(s) => quote::ToTokens::to_token_stream(s),
            FragNode::Item(i) => quote::ToTokens::to_token_stream(i),
            FragNode::File(f) => quote::ToTokens::to_token_stream(f),
            FragNode::Block(block) => {
                let mut ts = proc_macro2::TokenStream::new();
                for stmt in block.stmts {
                    quote::ToTokens::to_tokens(stmt, &mut ts);
                }
                ts
            }
        };
        ts.to_string()
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ")
    }

    // -- Source-location method check -----------------------------------------

    /// Returns `Some(())` if the fragment is a `Location::caller().file()`,
    /// `.line()`, or `.column()` call chain. Wraps the `source_location_runtime_reason`
    /// check from `lib.rs` without exposing raw `&Expr` to callers.
    pub(crate) fn source_location_method_check(&self) -> Option<()> {
        match &self.node {
            FragNode::Expr(e) => crate::source_location_runtime_reason(e).map(|_| ()),
            _ => None,
        }
    }

    // -- Macro name accessor --------------------------------------------------

    /// For an `Expr::Macro` fragment, returns the last path-segment ident of
    /// the macro path (e.g. `"panic"` for `panic!(...)`). Returns `None` for
    /// any non-macro fragment.
    pub(crate) fn macro_name(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(syn::Expr::Macro(m)) => {
                m.mac.path.segments.last().map(|seg| seg.ident.to_string())
            }
            _ => None,
        }
    }

    // -- Atomic-load method check ---------------------------------------------

    /// Returns `true` if the fragment is a `.load(ordering)` method call whose
    /// receiver is NOT a simple local-ident path -- the shape of an atomic
    /// field/deref load. The receiver check mirrors `simple_path_name` (recurses
    /// through `Paren`/`Group`) so a parenthesised simple path is excluded just
    /// as the original shim excluded it.
    pub(crate) fn is_atomic_load_method(&self) -> bool {
        match &self.node {
            FragNode::Expr(syn::Expr::MethodCall(call)) => {
                call.method == "load"
                    && call.args.len() == 1
                    && crate::simple_path_name(&call.receiver).is_none()
            }
            _ => false,
        }
    }

    // -- Async-block assertion check ------------------------------------------

    /// Returns `true` if the fragment is an `Expr::Async` block whose body
    /// contains at least one assertion surface (`count_asserts_in_stmts > 0`).
    /// Used by `statement_async_future::recognize` without escaping to raw syn.
    pub(crate) fn is_async_with_asserts(&self) -> bool {
        match &self.node {
            FragNode::Expr(syn::Expr::Async(a)) => {
                crate::count_asserts_in_stmts(&a.block.stmts) > 0
            }
            _ => false,
        }
    }

    // -- Control-flow check ---------------------------------------------------

    /// Returns `true` if this fragment is an expression that both carries at
    /// least one assertion macro and contains a `.await` expression -- the
    /// shape detected by `statement_control_flow`. Returns `false` for any
    /// non-`Expr` fragment. Delegates to `statement_position::has_control_flow`
    /// so the raw visitor logic stays out of recognizer bodies.
    pub(crate) fn has_control_flow(&self) -> bool {
        match &self.node {
            FragNode::Expr(e) => crate::sugar::statement_position::has_control_flow(e),
            _ => false,
        }
    }

    // -- Reflection-boundary check --------------------------------------------

    /// Returns the reflection boundary string if this fragment is an assertion-bearing
    /// `match` whose scrutinee is a `TypeId::of` / `Type::of` / `.info()` reflection
    /// call, optionally wrapped in a `const { .. }` block. Mirrors
    /// `statement_position::reflection_boundary` without escaping to raw syn. Returns
    /// `None` for any other fragment shape (non-match, no assert, non-reflection
    /// scrutinee).
    pub(crate) fn reflection_boundary_str(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(e) => crate::sugar::statement_position::reflection_boundary(e),
            _ => None,
        }
    }

    // -- Future-handoff boundary check ----------------------------------------

    /// Returns the future-handoff boundary string if this fragment matches the
    /// `statement_position::future_handoff_boundary` shape (a call or method call
    /// whose arguments contain an asserting async block). Delegates to
    /// `statement_position::future_handoff_boundary` without exposing `&Expr`.
    /// Returns `None` for any non-matching fragment.
    pub(crate) fn future_handoff_boundary(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(e) => crate::sugar::statement_position::future_handoff_boundary(e),
            _ => None,
        }
    }

    // -- Loop-advance check ---------------------------------------------------

    /// Returns `true` if this fragment is a loop-advance expression (contains
    /// an iterator-advance call like `.size_hint()` inside a `loop` body).
    /// Delegates to `statement_position::has_loop_advance` without exposing
    /// `&Expr` to recognizer bodies.
    pub(crate) fn is_loop_advance(&self) -> bool {
        match &self.node {
            FragNode::Expr(e) => crate::sugar::statement_position::has_loop_advance(e),
            _ => false,
        }
    }

    // -- Assertion-surface macro check ----------------------------------------

    /// Returns `true` if this fragment is an `Expr::Macro` that is an assertion
    /// surface (e.g. `assert!`, `assert_eq!`, etc. as determined by
    /// `macro_is_assertion_surface`). Returns `false` for any non-macro fragment.
    pub(crate) fn is_assertion_surface_macro(&self) -> bool {
        match &self.node {
            FragNode::Expr(syn::Expr::Macro(m)) => crate::macro_is_assertion_surface(&m.mac),
            _ => false,
        }
    }

    // -- Macro argument count -------------------------------------------------

    /// For an `Expr::Macro` fragment, parse the macro token stream as
    /// comma-separated expressions and return the count. Returns `None` for
    /// non-macro fragments or if the tokens do not parse as a comma list.
    pub(crate) fn macro_arg_count(&self) -> Option<usize> {
        match &self.node {
            FragNode::Expr(syn::Expr::Macro(m)) => {
                let parser =
                    syn::punctuated::Punctuated::<syn::Expr, syn::Token![,]>::parse_terminated;
                syn::parse::Parser::parse2(parser, m.mac.tokens.clone())
                    .ok()
                    .map(|p| p.len())
            }
            _ => None,
        }
    }

    // -- Const/Static item accessors (typed; no raw-syn in callers) -----------

    /// For an `Item::Const` or `Item::Static` fragment, returns the item kind
    /// (`"const"` or `"static"`) and the identifier name as a `String`.
    /// Returns `None` for all other fragment kinds.
    pub(crate) fn item_const_static_kind_and_name(&self) -> Option<(&'static str, String)> {
        match &self.node {
            FragNode::Item(syn::Item::Const(item)) => {
                Some(("const", item.ident.to_string()))
            }
            FragNode::Item(syn::Item::Static(item)) => {
                Some(("static", item.ident.to_string()))
            }
            _ => None,
        }
    }

    /// For an `Item::Const` or `Item::Static` fragment, returns `true` when
    /// the initializer expression contains at least one assertion-surface macro.
    /// Returns `false` for all other fragment kinds or when the initializer is
    /// assertion-free.
    pub(crate) fn item_const_static_initializer_has_asserts(&self) -> bool {
        match &self.node {
            FragNode::Item(syn::Item::Const(item)) => {
                crate::count_asserts_in_expr(&item.expr) != 0
            }
            FragNode::Item(syn::Item::Static(item)) => {
                crate::count_asserts_in_expr(&item.expr) != 0
            }
            _ => false,
        }
    }

    /// For an `Item::Const` or `Item::Static` fragment, returns the normalized
    /// token-key string of the initializer expression (whitespace-collapsed via
    /// `token_key`). Returns `None` for all other fragment kinds.
    pub(crate) fn item_const_static_initializer_token_str(&self) -> Option<String> {
        match &self.node {
            FragNode::Item(syn::Item::Const(item)) => {
                Some(crate::token_key(&*item.expr))
            }
            FragNode::Item(syn::Item::Static(item)) => {
                Some(crate::token_key(&*item.expr))
            }
            _ => None,
        }
    }

    // -- Impl-item accessor ---------------------------------------------------

    /// For an `Item::Impl` fragment, returns the name of the first impl method
    /// whose body carries at least one assertion surface. Returns `None` for
    /// non-impl-item fragments and for impl blocks with no asserting method
    /// (pure / assert-free impls stay on the generic unclassified path).
    /// All syn field access lives HERE -- recognizers see only the String.
    pub(crate) fn impl_item_asserting_method_name(&self) -> Option<String> {
        match &self.node {
            FragNode::Item(syn::Item::Impl(imp)) => {
                imp.items.iter().find_map(|it| {
                    if let syn::ImplItem::Fn(m) = it {
                        if crate::count_asserts_in_stmts(&m.block.stmts) > 0 {
                            return Some(m.sig.ident.to_string());
                        }
                    }
                    None
                })
            }
            _ => None,
        }
    }

    // -- Scalar literal accessor (typed; no raw-syn in callers) ---------------

    /// Decode the scalar literal held by an `Expr::Lit` fragment into a
    /// [`ScalarLit`], holding only host-native types. Returns `None` for
    /// `CStr` literals (not liftable as a scalar) and for any non-`Expr::Lit`
    /// fragment. All syn field access lives HERE -- callers see only the enum.
    pub(crate) fn scalar_lit(&self) -> Option<ScalarLit> {
        match &self.node {
            FragNode::Expr(syn::Expr::Lit(l)) => match &l.lit {
                // CStr is not a scalar liftable by TermLiteralSugar.
                syn::Lit::CStr(_) => None,
                syn::Lit::Int(i) => Some(ScalarLit::Int {
                    token_text: i.to_string(),
                    suffix: i.suffix().to_string(),
                }),
                syn::Lit::Float(f) => Some(ScalarLit::Float {
                    base10_digits: f.base10_digits().to_string(),
                }),
                syn::Lit::Str(s) => Some(ScalarLit::Str(s.value())),
                syn::Lit::Char(c) => Some(ScalarLit::Char(c.value())),
                syn::Lit::Bool(b) => Some(ScalarLit::Bool(b.value)),
                syn::Lit::ByteStr(bs) => Some(ScalarLit::ByteStr(bs.value())),
                syn::Lit::Byte(b) => Some(ScalarLit::Byte(b.value())),
                // Verbatim or any future non-exhaustive syn::Lit variant.
                other => {
                    let mut ts = proc_macro2::TokenStream::new();
                    quote::ToTokens::to_tokens(other, &mut ts);
                    Some(ScalarLit::Other(ts.to_string()))
                }
            },
            _ => None,
        }
    }

    /// For an `Expr::Lit(Lit::Int)` fragment, parse the integer value as
    /// `u128` using `syn::LitInt::base10_parse` (decimal digits only; hex,
    /// binary, and octal literals return `None`). Does NOT strip
    /// `Reference`/`Paren`/`Group` wrappers -- call `strip_refs_groups()`
    /// first if the fragment may be wrapped. All syn field access lives HERE.
    pub(crate) fn literal_int_u128(&self) -> Option<u128> {
        match &self.node {
            FragNode::Expr(syn::Expr::Lit(l)) => match &l.lit {
                syn::Lit::Int(i) => i.base10_parse::<u128>().ok(),
                _ => None,
            },
            _ => None,
        }
    }

    // -- Range-contains const-fold accessor -----------------------------------

    /// Const-fold a `(a..b).contains(&x)` / `(a..=b).contains(&x)` (and
    /// open-ended variants) over an inline range literal with all-integer-scalar
    /// endpoints and a single integer-scalar argument to the computed membership
    /// `bool`. Returns `None` when:
    ///   - the fragment is not a `.contains(single_arg)` method call,
    ///   - the receiver (after stripping refs/groups/parens) is not an inline
    ///     `Expr::Range` literal,
    ///   - any present endpoint or the argument does not const-fold to an
    ///     integer scalar (int/byte literal, possibly negated).
    /// CHAR ranges return `None` (left to the char lane).
    /// All raw syn field access lives HERE; callers see only `Option<bool>`.
    pub(crate) fn range_literal_contains_int(&self) -> Option<bool> {
        let FragNode::Expr(syn::Expr::MethodCall(call)) = &self.node else {
            return None;
        };
        if call.method != "contains" || call.args.len() != 1 {
            return None;
        }
        let syn::Expr::Range(range) = strip_refs_groups_expr(&call.receiver) else {
            return None;
        };
        let x = int_scalar_expr(&call.args[0])?;
        let start = match range.start.as_deref() {
            None => None,
            Some(e) => Some(int_scalar_expr(e)?),
        };
        let end = match range.end.as_deref() {
            None => None,
            Some(e) => Some(int_scalar_expr(e)?),
        };
        let lower_ok = start.map_or(true, |s| x >= s);
        let upper_ok = match (end, &range.limits) {
            (Some(e), syn::RangeLimits::HalfOpen(_)) => x < e,
            (Some(e), syn::RangeLimits::Closed(_)) => x <= e,
            (None, _) => true,
        };
        Some(lower_ok && upper_ok)
    }

    // -- Sorted-array const-fold accessors ------------------------------------

    /// Const-fold a literal scalar array (after stripping refs/parens/groups)
    /// to an ordered vector of i128 values, ready for consecutive-pair
    /// sortedness comparison (`windows(2)`). Each element must be a closed
    /// scalar: an int/byte literal, a `char` (codepoint), a `bool` (0/1), or a
    /// negated int/byte -- through paren/group/ref wrappers.
    ///
    /// Also handles `Box::new([..])` as the same finite construction
    /// (mirrors `scalar_literal_array_elems` in `lib.rs`).
    ///
    /// Returns `None` if the fragment is not a literal array, or if any element
    /// fails to fold. All raw syn field access lives HERE; callers see only
    /// `Option<Vec<i128>>`.
    pub(crate) fn scalar_array_ordered_values(&self) -> Option<Vec<i128>> {
        match &self.node {
            FragNode::Expr(syn::Expr::Array(arr)) => {
                arr.elems.iter().map(scalar_ordered_value_expr).collect()
            }
            // Strip references / parens / groups transparently.
            FragNode::Expr(syn::Expr::Reference(r)) => {
                Self::expr(&r.expr, self.file).scalar_array_ordered_values()
            }
            FragNode::Expr(syn::Expr::Paren(p)) => {
                Self::expr(&p.expr, self.file).scalar_array_ordered_values()
            }
            FragNode::Expr(syn::Expr::Group(g)) => {
                Self::expr(&g.expr, self.file).scalar_array_ordered_values()
            }
            // `Box::new([..])` -- the boxed array is the same finite construction.
            FragNode::Expr(syn::Expr::Call(c)) if c.args.len() == 1 => {
                if let syn::Expr::Path(p) = c.func.as_ref() {
                    let is_box_new = (p.path.segments.len() == 2
                        && p.path.segments[0].ident == "Box"
                        && p.path.segments[1].ident == "new")
                        || (p.path.segments.last().is_some_and(|s| s.ident == "new")
                            && p.path.segments.iter().any(|s| s.ident == "Box"));
                    if is_box_new {
                        return Self::expr(&c.args[0], self.file).scalar_array_ordered_values();
                    }
                }
                None
            }
            _ => None,
        }
    }

    /// Returns `true` if this fragment is a zero-argument `MethodCall` to one
    /// of the order-PRESERVING iterator/view adaptor names: `iter`,
    /// `into_iter`, `iter_mut`, `copied`, `cloned`, `as_slice`, `by_ref`.
    ///
    /// These can be peeled off the receiver of `.is_sorted()` while keeping
    /// the sortedness of the underlying literal array intact.
    /// Order-CHANGING adaptors (e.g. `.rev()`) are NOT listed here.
    /// All raw syn field access lives HERE; callers see only `bool`.
    pub(crate) fn is_order_preserving_view_adaptor(&self) -> bool {
        match &self.node {
            FragNode::Expr(syn::Expr::MethodCall(m)) => {
                m.args.is_empty()
                    && matches!(
                        m.method.to_string().as_str(),
                        "iter"
                            | "into_iter"
                            | "iter_mut"
                            | "copied"
                            | "cloned"
                            | "as_slice"
                            | "by_ref"
                    )
            }
            _ => false,
        }
    }

    // -- Char-range filter-map equality site ---------------------------------

    /// Returns the `token_key` boundary string if this fragment is an
    /// `assert!(...)` macro call whose single argument is a char-range
    /// `filter_map` equality expression of the form:
    ///   `(from..=to).eq((from as u32..=to as u32).filter_map(char::from_u32))`
    /// (optionally with `.rev()` on both sides). Returns `None` for any other
    /// shape. All raw syn field access lives HERE; `char_range_filter_map::recognize`
    /// sees only the derived site string.
    pub(crate) fn char_range_filter_map_eq_site(&self) -> Option<String> {
        let FragNode::Expr(syn::Expr::Macro(mac)) = &self.node else {
            return None;
        };
        if mac.mac.path.segments.last()?.ident != "assert" {
            return None;
        }
        let args = crate::parse_macro_args(mac.mac.tokens.clone()).ok()?;
        let payload = args.exprs.first()?;
        if !crate::sugar::char_range_filter_map::is_char_range_filter_map_eq(payload) {
            return None;
        }
        Some(crate::token_key(payload))
    }

    // -- Primitive-integer From callee accessor --------------------------------

    /// For an `Expr::Path` fragment that is the callee of a primitive-integer
    /// `from` call -- `<IntT>::from` (qualified self) or `IntT::from` (two-segment
    /// path) -- return the `IntKind` of the destination integer type. Returns `None`
    /// for any path that is not this shape, including non-integer types, floats,
    /// `char`, longer paths, or paths with generic arguments.
    ///
    /// Mirrors `primitive_int_from_kind` + `primitive_int_type_kind` from
    /// `from_bool.rs`; all raw syn field access lives HERE so recognizer bodies
    /// see only `Option<IntKind>`.
    pub(crate) fn path_primitive_int_from_kind(
        &self,
    ) -> Option<crate::sugar::int_literal::IntKind> {
        use syn::PathArguments;
        let syn::Expr::Path(path) = (match &self.node {
            FragNode::Expr(e) => e,
            _ => return None,
        }) else {
            return None;
        };
        let last = path.path.segments.last()?;
        if last.ident != "from" || !matches!(last.arguments, PathArguments::None) {
            return None;
        }
        if let Some(qself) = &path.qself {
            return primitive_int_type_kind_from_syn(&qself.ty);
        }
        if path.path.segments.len() == 2
            && matches!(path.path.segments[0].arguments, PathArguments::None)
        {
            crate::sugar::int_literal::primitive_int_kind(
                &path.path.segments[0].ident.to_string(),
            )
        } else {
            None
        }
    }

    // -- For-loop mutation boundary ------------------------------------------

    /// Returns the `token_key` boundary string if this fragment is a `for` loop
    /// that:
    ///   (a) is NOT decomposable as a forall loop (i.e. `forall::decompose_for_loop`
    ///       returns `None`), AND
    ///   (b) carries a runtime mutation boundary in either the iterable expression
    ///       or the loop body block (checked via `statement_position::has_runtime_boundary`).
    /// Returns `None` for any non-`ForLoop` fragment, for a loop that IS a forall,
    /// or for a for loop that has no mutation boundary. All raw syn field access
    /// lives HERE; `for_loop_mutation::recognize` sees only the derived boundary string.
    pub(crate) fn for_loop_mutation_boundary(
        &self,
        fcx: &crate::sugar::factory::SugarBuildCtx<'_, '_>,
    ) -> Option<String> {
        let FragNode::Expr(syn::Expr::ForLoop(for_loop)) = &self.node else {
            return None;
        };
        // If this for loop IS a forall, decline -- forall_loop owns it.
        if crate::sugar::forall::decompose_for_loop(
            for_loop,
            fcx.scope(),
            fcx.let_inits(),
            fcx,
        )
        .is_some()
        {
            return None;
        }
        // Check for runtime mutation boundary in the iterable expr or the body block.
        let body_block_as_expr = syn::Expr::Block(syn::ExprBlock {
            attrs: Vec::new(),
            label: None,
            block: for_loop.body.clone(),
        });
        let has_mutation =
            crate::sugar::statement_position::has_runtime_boundary(&for_loop.expr)
                || crate::sugar::statement_position::has_runtime_boundary(&body_block_as_expr);
        if has_mutation {
            let FragNode::Expr(e) = &self.node else {
                unreachable!()
            };
            Some(crate::token_key(e))
        } else {
            None
        }
    }
}

// ---------------------------------------------------------------------------
// Primitive-integer type kind helper (used by path_primitive_int_from_kind)
// ---------------------------------------------------------------------------

/// Decode a `&syn::Type` to an `IntKind` for the qualified-self form
/// `<IntT>::from`: the type must be a simple path (no qself, no args) whose
/// last segment is a known primitive integer type name.
fn primitive_int_type_kind_from_syn(
    ty: &syn::Type,
) -> Option<crate::sugar::int_literal::IntKind> {
    use syn::PathArguments;
    let syn::Type::Path(path) = ty else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    match path.path.segments.last() {
        Some(seg) if matches!(seg.arguments, PathArguments::None) => {
            crate::sugar::int_literal::primitive_int_kind(&seg.ident.to_string())
        }
        _ => None,
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
// Range-contains helpers (used by `range_literal_contains_int`)
// ---------------------------------------------------------------------------

/// Strip `Reference` / `Paren` / `Group` wrappers recursively to expose the inner
/// expression. Mirrors `strip_refs_groups` in `lib.rs` but scoped here so that
/// `range_literal_contains_int` does not escape to raw syn in recognizer bodies.
fn strip_refs_groups_expr(expr: &syn::Expr) -> &syn::Expr {
    match expr {
        syn::Expr::Reference(r) => strip_refs_groups_expr(&r.expr),
        syn::Expr::Paren(p) => strip_refs_groups_expr(&p.expr),
        syn::Expr::Group(g) => strip_refs_groups_expr(&g.expr),
        _ => expr,
    }
}

/// Const-fold an expression to an integer scalar through ref/paren/group wrappers.
/// Recognises int literals, byte literals (`b'x'`), and negated variants. CHAR is
/// intentionally excluded (char ranges are handled by the char-range lane).
fn int_scalar_expr(expr: &syn::Expr) -> Option<i128> {
    match strip_refs_groups_expr(expr) {
        syn::Expr::Lit(l) => match &l.lit {
            syn::Lit::Int(i) => i.base10_parse::<i128>().ok(),
            syn::Lit::Byte(b) => Some(i128::from(b.value())),
            _ => None,
        },
        syn::Expr::Unary(u) if matches!(u.op, syn::UnOp::Neg(_)) => {
            int_scalar_expr(&u.expr).and_then(i128::checked_neg)
        }
        _ => None,
    }
}

/// Const-fold a closed scalar expression to an ordering i128 value for
/// sortedness comparison. Extends `int_scalar_expr` to cover `char` (codepoint)
/// and `bool` (0/1), through ref/paren/group wrappers. Used by
/// `scalar_array_ordered_values`.
fn scalar_ordered_value_expr(expr: &syn::Expr) -> Option<i128> {
    match strip_refs_groups_expr(expr) {
        syn::Expr::Lit(l) => match &l.lit {
            syn::Lit::Int(i)  => i.base10_parse::<i128>().ok(),
            syn::Lit::Byte(b) => Some(i128::from(b.value())),
            syn::Lit::Char(c) => Some(i128::from(u32::from(c.value()))),
            syn::Lit::Bool(b) => Some(i128::from(b.value)),
            _ => None,
        },
        syn::Expr::Unary(u) if matches!(u.op, syn::UnOp::Neg(_)) => {
            scalar_ordered_value_expr(&u.expr).and_then(i128::checked_neg)
        }
        _ => None,
    }
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
        syn::Item::Static(_) => "Static",
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
