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

use quote;
use syn::spanned::Spanned;

/// A Python suite has no AST node; a Rust block (`{ stmt; stmt; }`) does, but a bare
/// `&[Stmt]` (a function body, an `if`/`else` branch) does not. `Block` is the synthetic
/// fragment that puts a suite on the stack as ONE composite, so `BlockSugar` composes it
/// instead of an external loop -- exactly like the Python synthetic `Block`.
#[derive(Clone, Copy)]
#[cfg(test)]
pub(crate) struct BlockFrag<'a> {
    pub(crate) stmts: &'a [syn::Stmt],
    pub(crate) line: usize,
    pub(crate) col: usize,
}

/// The node a fragment wraps. Borrowed -- a fragment never owns AST.
#[derive(Clone, Copy)]
pub(crate) enum FragNode<'a> {
    #[cfg(test)]
    File(&'a syn::File),
    Item(&'a syn::Item),
    Stmt(&'a syn::Stmt),
    Expr(&'a syn::Expr),
    /// Synthetic suite (a `&[Stmt]` body/branch). See `BlockFrag`.
    #[cfg(test)]
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
        Self {
            node,
            file,
            line,
            col,
        }
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

    #[cfg(test)]
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
            #[cfg(test)]
            FragNode::File(_) => "File".into(),
            #[cfg(test)]
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
    #[cfg(test)]
    pub(crate) fn fragments(&self) -> Vec<SourceFragment<'a>> {
        match &self.node {
            // A synthetic Block decomposes into its statements.
            FragNode::Block(b) => b.stmts.iter().map(|s| Self::stmt(s, self.file)).collect(),

            // A File decomposes into Item fragments.
            FragNode::File(f) => f
                .items
                .iter()
                .map(|i| Self::from_node(FragNode::Item(i), self.file))
                .collect(),

            // Items: function body is the only child we expose at this granularity.
            FragNode::Item(syn::Item::Fn(f)) => {
                vec![Self::block(&f.block.stmts, self.file)]
            }
            FragNode::Item(syn::Item::Mod(m)) => m
                .content
                .as_ref()
                .map(|(_, items)| {
                    items
                        .iter()
                        .map(|i| Self::from_node(FragNode::Item(i), self.file))
                        .collect()
                })
                .unwrap_or_default(),

            // Statements: decompose into the inner expressions they carry.
            FragNode::Stmt(s) => stmt_child_fragments(s, self.file),

            // Expressions: decompose into their sub-expressions.
            FragNode::Expr(e) => expr_child_fragments(e, self.file),

            _ => Vec::new(),
        }
    }

    /// This fragment's statement children -- a body's lines. A `&[Stmt]` suite is one
    /// `Block` fragment (it composes its own statements at the STATEMENT role).
    #[cfg(test)]
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
    #[cfg(test)]
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
    #[cfg(test)]
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
            FragNode::Stmt(syn::Stmt::Expr(syn::Expr::If(i), _)) => i
                .else_branch
                .as_ref()
                .map(|(_, e)| Self::expr(e, self.file)),
            FragNode::Expr(syn::Expr::If(i)) => i
                .else_branch
                .as_ref()
                .map(|(_, e)| Self::expr(e, self.file)),
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

    /// The tail expression of a `Stmt::Expr(e, None)` where `e` is NOT
    /// `If`, `Block`, `Unsafe`, `Return`, or non-value control flow -- the "simple tail value"
    /// shapes that `ReturnSugar` claims at the statement role. Returns `None`
    /// for explicit return stmts, semicolon-terminated stmts, if/block/unsafe
    /// tail expressions, and all non-Stmt fragments. All raw syn field access
    /// lives HERE; recognizer bodies see only `Option<SourceFragment>`.
    pub(crate) fn stmt_tail_expr_noncf(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Stmt(syn::Stmt::Expr(e, None)) if !is_non_value_tail_control_expr(e) => {
                Some(Self::expr(e, self.file))
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

    /// Returns `true` iff this fragment (or any sub-expression reachable through
    /// binary operators, parens, casts, or groups) contains at least one bit-operation
    /// operator (`<<`, `>>`, `&`, `|`, `^`). Used by `str_table_select::recognize`
    /// to gate on bv32-routable index expressions. Returns `false` for any non-`Expr`
    /// fragment. All raw syn field access lives in `index_contains_bv_op_expr`.
    pub(crate) fn index_contains_bv_op_frag(&self) -> bool {
        match &self.node {
            FragNode::Expr(e) => index_contains_bv_op_expr(e),
            _ => false,
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
    pub(crate) fn binop_const_folded_term(&self) -> Option<std::rc::Rc<sugar_ir_symbolic::Term>> {
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

    /// For a `MethodCall` fragment, returns the simple single-ident name of the
    /// receiver, stripping `Paren` and `Group` wrappers (mirrors
    /// `crate::simple_path_name(&call.receiver)`). Returns `None` for
    /// non-`MethodCall` fragments or receivers that are not a bare identifier
    /// path (possibly wrapped in parentheses/groups).
    pub(crate) fn call_receiver_simple_ident(&self) -> Option<String> {
        match &self.node {
            FragNode::Expr(syn::Expr::MethodCall(m)) => crate::simple_path_name(&m.receiver),
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

    /// Returns `true` if this is a `MethodCall` fragment with a turbofish
    /// (e.g. `recv.parse::<i32>()`). Returns `false` for any non-`MethodCall`
    /// fragment or a method call without turbofish. All raw syn access lives HERE.
    pub(crate) fn call_has_turbofish(&self) -> bool {
        match &self.node {
            FragNode::Expr(syn::Expr::MethodCall(m)) => m.turbofish.is_some(),
            _ => false,
        }
    }

    // -- Char-method helpers -----------------------------------------------

    /// Returns `true` if this fragment is definitely NOT a valid `char` receiver.
    /// Strips `Reference`/`Paren`/`Group` wrappers first. A `Lit::Char(_)` returns
    /// `false` (it IS a char); any other `Lit` returns `true` (definitely not char);
    /// a `MethodCall` recurses on its own receiver; everything else returns `false`
    /// (uncertain -- could be a char variable or the result of a char-returning method).
    /// All raw syn access lives HERE.
    pub(crate) fn definitely_not_char_receiver(&self) -> bool {
        let stripped = self.strip_refs_groups();
        match &stripped.node {
            FragNode::Expr(syn::Expr::Lit(l)) => !matches!(l.lit, syn::Lit::Char(_)),
            FragNode::Expr(syn::Expr::MethodCall(call)) => {
                Self::expr(&call.receiver, stripped.file).definitely_not_char_receiver()
            }
            _ => false,
        }
    }

    /// Returns `true` if this fragment (the receiver of a `.to_string()` call)
    /// resolves to a `char` literal through paren/group/ref stripping and
    /// single-ident let-binding chains. All raw syn access lives HERE.
    pub(crate) fn char_to_string_receiver_resolves_literal(
        &self,
        fcx: &crate::sugar::factory::SugarBuildCtx<'_, '_>,
    ) -> bool {
        let Some(expr) = self.as_expr() else {
            return false;
        };
        char_to_string_receiver_resolves_literal_raw(expr, fcx)
    }

    // -- Literal accessor -------------------------------------------------

    /// The literal source text for a `PrimitiveLiteral` node. Returns the token's
    /// `.to_string()` representation. For typed accessors (parse as int/float/str)
    /// callers should match the inner `syn::Lit` themselves via `literal_value_str`.
    #[cfg(test)]
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
    #[cfg(test)]
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
    #[cfg(test)]
    pub(crate) fn assign_value(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Stmt(syn::Stmt::Local(l)) => l
                .init
                .as_ref()
                .map(|init| Self::expr(&init.expr, self.file)),
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
            FragNode::Expr(syn::Expr::Path(p)) => p
                .path
                .segments
                .iter()
                .rev()
                .nth(1)
                .map(|s| s.ident.to_string()),
            _ => None,
        }
    }

    /// Returns `true` if this fragment is an `Expr::Path` with a qualified self
    /// (`<T as Trait>::assoc` form). Returns `false` for plain paths and all
    /// non-path nodes.
    pub(crate) fn path_has_qself(&self) -> bool {
        match &self.node {
            FragNode::Expr(syn::Expr::Path(p)) => p.qself.is_some(),
            _ => false,
        }
    }

    /// Returns `true` if this fragment is a const-eval literal: an `Expr::Lit`
    /// of any kind, or a negated integer/float literal (`-7`, `-1.0`). Does NOT
    /// match paths to named consts, function calls, or any runtime expression.
    /// Mirrors the `is_const_eval_literal` private helper formerly in
    /// `maybe_uninit_new.rs`.
    pub(crate) fn is_const_eval_literal(&self) -> bool {
        match &self.node {
            FragNode::Expr(syn::Expr::Lit(_)) => true,
            FragNode::Expr(syn::Expr::Unary(u)) => {
                matches!(u.op, syn::UnOp::Neg(_)) && matches!(*u.expr, syn::Expr::Lit(_))
            }
            _ => false,
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
        let elems = crate::scalar_literal_array_elems(crate::strip_refs_groups(&call.receiver))?;
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
    pub(crate) fn const_folded_if_term(&self) -> Option<std::rc::Rc<sugar_ir_symbolic::Term>> {
        let e = match &self.node {
            FragNode::Expr(e @ syn::Expr::If(_)) => e,
            _ => return None,
        };
        use std::collections::BTreeMap;
        crate::const_eval(e, &BTreeMap::new()).and_then(|v| crate::const_val_term(&v))
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

    // -- RawAddr accessors ---------------------------------------------------

    /// The inner expression of an `Expr::RawAddr` fragment (`x` in
    /// `&raw const x` or `&raw mut x`). Returns `None` for any non-`RawAddr`
    /// fragment. All raw syn field access lives HERE.
    pub(crate) fn raw_addr_inner(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Expr(syn::Expr::RawAddr(raw)) => Some(Self::expr(&raw.expr, self.file)),
            _ => None,
        }
    }

    /// Whether an `Expr::RawAddr` fragment is a const raw-address (`&raw const x`).
    /// Returns `false` for `&raw mut x` and for any non-`RawAddr` fragment.
    pub(crate) fn raw_addr_is_const(&self) -> bool {
        match &self.node {
            FragNode::Expr(syn::Expr::RawAddr(raw)) => {
                matches!(raw.mutability, syn::PointerMutability::Const(_))
            }
            _ => false,
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

    // -- Node-kind guard (non-shim; no raw syn returned) ----------------------

    /// Returns `true` if this fragment wraps an expression node
    /// (`FragNode::Expr`). Use as a gate in recognizer bodies instead of
    /// `as_expr()?` when the body does not need the raw `&syn::Expr` (i.e.
    /// all subsequent field access goes through typed accessors). All raw
    /// syn is absent from the return type; the check is purely structural.
    #[cfg(test)]
    pub(crate) fn is_expr(&self) -> bool {
        matches!(self.node, FragNode::Expr(_))
    }

    // -- Closure parameter and free-variable accessors -------------------------

    /// For an `Expr::Closure` fragment, returns the set of parameter names
    /// declared in the closure's input list. Strips `Pat::Type` wrappers to
    /// expose the inner `Pat::Ident`. Multi-pattern / other non-ident patterns
    /// are silently skipped (conservative: they cannot be free-var captures
    /// since they bind by pattern). Returns an empty set for non-Closure
    /// fragments and zero-parameter closures. All raw syn access lives HERE.
    pub(crate) fn closure_param_names(&self) -> std::collections::BTreeSet<String> {
        let FragNode::Expr(syn::Expr::Closure(c)) = &self.node else {
            return std::collections::BTreeSet::new();
        };
        c.inputs
            .iter()
            .filter_map(|p| match p {
                syn::Pat::Ident(id) => Some(id.ident.to_string()),
                syn::Pat::Type(t) => match t.pat.as_ref() {
                    syn::Pat::Ident(id) => Some(id.ident.to_string()),
                    _ => None,
                },
                _ => None,
            })
            .collect()
    }

    /// For an `Expr::Closure` fragment, returns all names referenced in the
    /// closure body via `crate::names_referenced_in_expr`. Returns an empty
    /// `BTreeSet` for non-Closure fragments. All raw syn access lives HERE.
    pub(crate) fn closure_referenced_names(&self) -> std::collections::BTreeSet<String> {
        let FragNode::Expr(syn::Expr::Closure(c)) = &self.node else {
            return std::collections::BTreeSet::new();
        };
        crate::names_referenced_in_expr(&c.body)
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
            #[cfg(test)]
            FragNode::File(f) => quote::ToTokens::to_token_stream(f),
            #[cfg(test)]
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
    /// the macro path (e.g. `"concat"` for `concat!(...)`). Returns `None` for
    /// any non-macro fragment. Raw syn access lives here (ratchet-excluded);
    /// recognizer bodies compare the returned `String` against a string literal.
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

    // -- Macro args with callback ---------------------------------------------

    /// For an `Expr::Macro` fragment, parse the macro token stream as
    /// comma-separated expressions and invoke `f` once per argument with a
    /// `SourceFragment` wrapping that argument expression. Returns `true` on
    /// success (including an empty arg list); returns `false` if the fragment
    /// is not an `Expr::Macro` or if the token stream does not parse as a
    /// comma-separated expression list. All raw syn access (token parsing,
    /// `syn::Expr` construction) stays inside this accessor -- callers see
    /// only `SourceFragment`.
    pub(crate) fn macro_args_with<F>(&self, mut f: F) -> bool
    where
        F: for<'e> FnMut(SourceFragment<'e>),
    {
        let FragNode::Expr(syn::Expr::Macro(m)) = &self.node else {
            return false;
        };
        let parser = syn::punctuated::Punctuated::<syn::Expr, syn::Token![,]>::parse_terminated;
        let Ok(punctuated) = syn::parse::Parser::parse2(parser, m.mac.tokens.clone()) else {
            return false;
        };
        for expr in &punctuated {
            f(SourceFragment::expr(expr, self.file));
        }
        true
    }

    // -- Const/Static item accessors (typed; no raw-syn in callers) -----------

    /// For an `Item::Const` or `Item::Static` fragment, returns the item kind
    /// (`"const"` or `"static"`) and the identifier name as a `String`.
    /// Returns `None` for all other fragment kinds.
    pub(crate) fn item_const_static_kind_and_name(&self) -> Option<(&'static str, String)> {
        match &self.node {
            FragNode::Item(syn::Item::Const(item)) => Some(("const", item.ident.to_string())),
            FragNode::Item(syn::Item::Static(item)) => Some(("static", item.ident.to_string())),
            _ => None,
        }
    }

    /// For an `Item::Const` or `Item::Static` fragment, returns `true` when
    /// the initializer expression contains at least one assertion-surface macro.
    /// Returns `false` for all other fragment kinds or when the initializer is
    /// assertion-free.
    pub(crate) fn item_const_static_initializer_has_asserts(&self) -> bool {
        match &self.node {
            FragNode::Item(syn::Item::Const(item)) => crate::count_asserts_in_expr(&item.expr) != 0,
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
            FragNode::Item(syn::Item::Const(item)) => Some(crate::token_key(&*item.expr)),
            FragNode::Item(syn::Item::Static(item)) => Some(crate::token_key(&*item.expr)),
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
            FragNode::Item(syn::Item::Impl(imp)) => imp.items.iter().find_map(|it| {
                if let syn::ImplItem::Fn(m) = it {
                    if crate::count_asserts_in_stmts(&m.block.stmts) > 0 {
                        return Some(m.sig.ident.to_string());
                    }
                }
                None
            }),
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
            crate::sugar::int_literal::primitive_int_kind(&path.path.segments[0].ident.to_string())
        } else {
            None
        }
    }

    // -- For-loop mutation boundary ------------------------------------------

    /// Returns the `token_key` boundary string if this fragment is a `for` loop
    /// that carries a runtime mutation boundary in either the iterable expression
    /// or the loop body block (checked via `statement_position::has_runtime_boundary`).
    /// Mutation wins before forall decomposition: a side-effecting iterator domain is
    /// runtime work even when its loop shape is otherwise forall-like. Returns `None`
    /// for any non-`ForLoop` fragment or for a for loop that has no mutation boundary.
    /// All raw syn field access lives HERE; `for_loop_mutation::recognize` sees only
    /// the derived boundary string.
    pub(crate) fn for_loop_mutation_boundary(
        &self,
        fcx: &crate::sugar::factory::SugarBuildCtx<'_, '_>,
    ) -> Option<String> {
        let FragNode::Expr(syn::Expr::ForLoop(for_loop)) = &self.node else {
            return None;
        };
        // Check for runtime mutation boundary in the iterable expr or the body block.
        let body_block_as_expr = syn::Expr::Block(syn::ExprBlock {
            attrs: Vec::new(),
            label: None,
            block: for_loop.body.clone(),
        });
        let has_mutation = crate::sugar::statement_position::has_runtime_boundary(&for_loop.expr)
            || crate::sugar::statement_position::has_runtime_boundary(&body_block_as_expr);
        if has_mutation {
            let FragNode::Expr(e) = &self.node else {
                unreachable!()
            };
            Some(crate::token_key(e))
        } else if crate::sugar::forall::decompose_for_loop(
            for_loop,
            fcx.scope(),
            fcx.let_inits(),
            fcx,
        )
        .is_some()
        {
            None
        } else {
            None
        }
    }

    // -- Array / Tuple / Range accessors ------------------------------------

    /// Elements of an `Expr::Array` literal as child fragments, in source order.
    /// Returns `None` for any non-Array expression.
    /// All raw syn field access lives HERE; callers see `Option<Vec<SourceFragment>>`.
    pub(crate) fn array_elems(&self) -> Option<Vec<SourceFragment<'a>>> {
        let FragNode::Expr(syn::Expr::Array(arr)) = &self.node else {
            return None;
        };
        Some(arr.elems.iter().map(|e| Self::expr(e, self.file)).collect())
    }

    /// Elements of an `Expr::Tuple` literal as child fragments, in source order.
    /// Returns `None` for any non-Tuple expression.
    /// All raw syn field access lives HERE; callers see `Option<Vec<SourceFragment>>`.
    pub(crate) fn tuple_elems(&self) -> Option<Vec<SourceFragment<'a>>> {
        let FragNode::Expr(syn::Expr::Tuple(tup)) = &self.node else {
            return None;
        };
        Some(tup.elems.iter().map(|e| Self::expr(e, self.file)).collect())
    }

    /// The ctor name for an `Expr::Range` literal: `"range"` for `a..b`,
    /// `"range_incl"` for `a..=b`. Returns `None` for any non-Range fragment.
    /// All raw syn field access lives HERE; callers see `Option<&'static str>`.
    pub(crate) fn range_limits_name(&self) -> Option<&'static str> {
        let FragNode::Expr(syn::Expr::Range(r)) = &self.node else {
            return None;
        };
        Some(match r.limits {
            syn::RangeLimits::HalfOpen(_) => "range",
            syn::RangeLimits::Closed(_) => "range_incl",
        })
    }

    /// Start fragment of an `Expr::Range`, if present.
    /// Returns `None` for any non-Range fragment or an open-ended start (`..b`).
    pub(crate) fn range_start_frag(&self) -> Option<SourceFragment<'a>> {
        let FragNode::Expr(syn::Expr::Range(r)) = &self.node else {
            return None;
        };
        r.start.as_deref().map(|e| Self::expr(e, self.file))
    }

    /// End fragment of an `Expr::Range`, if present.
    /// Returns `None` for any non-Range fragment or an open-ended end (`a..`).
    pub(crate) fn range_end_frag(&self) -> Option<SourceFragment<'a>> {
        let FragNode::Expr(syn::Expr::Range(r)) = &self.node else {
            return None;
        };
        r.end.as_deref().map(|e| Self::expr(e, self.file))
    }

    /// Returns `true` if this fragment is an `Expr::Range` with `Closed` limits
    /// (i.e. `a..=b`). Returns `false` for half-open ranges (`a..b`) and all
    /// non-Range fragments. All raw syn access lives HERE.
    pub(crate) fn range_is_closed(&self) -> bool {
        let FragNode::Expr(syn::Expr::Range(r)) = &self.node else {
            return false;
        };
        matches!(r.limits, syn::RangeLimits::Closed(_))
    }

    // -- BvBinOp accessor (bv_binop.rs) ---------------------------------------

    /// For an `Expr::Binary` fragment whose operator is one of the five bv32
    /// bit-operation operators (`<<`, `>>`, `&`, `|`, `^`), returns the
    /// canonical bv32 ctor name. Returns `None` for non-Binary fragments or
    /// arithmetic operators. All raw syn access lives HERE.
    pub(crate) fn binop_bv32_op_name(&self) -> Option<&'static str> {
        let FragNode::Expr(syn::Expr::Binary(b)) = &self.node else {
            return None;
        };
        match b.op {
            syn::BinOp::Shl(_) => Some("bv32.shl"),
            // Rust `>>` on unsigned integers is a logical right-shift.
            syn::BinOp::Shr(_) => Some("bv32.lshr"),
            syn::BinOp::BitAnd(_) => Some("bv32.and"),
            syn::BinOp::BitOr(_) => Some("bv32.or"),
            syn::BinOp::BitXor(_) => Some("bv32.xor"),
            _ => None,
        }
    }

    // -- Repeat accessors -----------------------------------------------------

    /// The element expression of an `Expr::Repeat` (`[elem; N]`) as a child
    /// fragment. Returns `None` for any non-Repeat fragment.
    /// All raw syn field access lives HERE; recognizers see only
    /// `Option<SourceFragment>`.
    pub(crate) fn repeat_elem_frag(&self) -> Option<SourceFragment<'a>> {
        let FragNode::Expr(syn::Expr::Repeat(r)) = &self.node else {
            return None;
        };
        Some(Self::expr(&r.expr, self.file))
    }

    /// Resolve the repeat count (`N` in `[elem; N]`) through scope constants.
    /// Returns `None` for any non-Repeat fragment OR if the length expression
    /// does not reduce to a concrete `usize` via `repeat_count_in_scope`.
    /// All raw syn field access lives HERE; recognizers see only `Option<usize>`.
    pub(crate) fn repeat_len_in_scope(
        &self,
        fcx: &crate::sugar::factory::SugarBuildCtx<'_, '_>,
    ) -> Option<usize> {
        let FragNode::Expr(syn::Expr::Repeat(r)) = &self.node else {
            return None;
        };
        crate::repeat_count_in_scope(&r.len, fcx.scope())
    }

    // -- Loop accessors -------------------------------------------------------

    /// For a `loop { break <expr>; }` fragment: returns the break-payload
    /// expression as a child fragment. Returns `None` if the fragment is not a
    /// `Loop` with exactly one unlabeled `break <expr>;` statement.
    /// All raw syn field access lives HERE; callers see `Option<SourceFragment>`.
    pub(crate) fn loop_single_break_payload_frag(&self) -> Option<SourceFragment<'a>> {
        let FragNode::Expr(syn::Expr::Loop(loop_expr)) = &self.node else {
            return None;
        };
        let [syn::Stmt::Expr(syn::Expr::Break(expr_break), _)] = loop_expr.body.stmts.as_slice()
        else {
            return None;
        };
        if expr_break.label.is_some() {
            return None;
        }
        expr_break.expr.as_deref().map(|e| Self::expr(e, self.file))
    }

    // -- Struct-literal accessors ---------------------------------------------

    /// Returns `true` if this fragment is an `Expr::Struct` that has a `..rest`
    /// tail (a struct-update expression). Returns `false` for any non-Struct or
    /// a Struct without a rest clause.
    pub(crate) fn struct_has_rest(&self) -> bool {
        match &self.node {
            FragNode::Expr(syn::Expr::Struct(s)) => s.rest.is_some(),
            _ => false,
        }
    }

    /// The `struct:<path>` ctor name for an `Expr::Struct` fragment: path
    /// segments joined with `"::"`. Returns `None` for any non-Struct fragment.
    /// All raw syn field access lives HERE.
    pub(crate) fn struct_path_variant_string(&self) -> Option<String> {
        let FragNode::Expr(syn::Expr::Struct(s)) = &self.node else {
            return None;
        };
        Some(
            s.path
                .segments
                .iter()
                .map(|seg| seg.ident.to_string())
                .collect::<Vec<_>>()
                .join("::"),
        )
    }

    /// The named fields of an `Expr::Struct` literal as `(field_name, value_fragment)`
    /// pairs. Returns an empty `Vec` for any non-Struct, or a Struct with a `..rest`
    /// clause (where the rest makes the fields incomplete). All raw syn field access
    /// lives HERE; callers see `Vec<(String, SourceFragment)>`.
    pub(crate) fn struct_named_fields_frags(&self) -> Vec<(String, SourceFragment<'a>)> {
        let FragNode::Expr(syn::Expr::Struct(s)) = &self.node else {
            return Vec::new();
        };
        s.fields
            .iter()
            .map(|fv| {
                let fname = match &fv.member {
                    syn::Member::Named(id) => id.to_string(),
                    syn::Member::Unnamed(idx) => idx.index.to_string(),
                };
                (fname, Self::expr(&fv.expr, self.file))
            })
            .collect()
    }

    // -- If-expression accessors ----------------------------------------------

    /// Returns `true` if this fragment is an `Expr::If` whose condition is
    /// side-effecting (calls `crate::closure_body_is_side_effecting`).
    /// Returns `false` for any non-If fragment.
    /// All raw syn field access lives HERE.
    pub(crate) fn if_cond_is_side_effecting(&self) -> bool {
        let FragNode::Expr(syn::Expr::If(if_expr)) = &self.node else {
            return false;
        };
        crate::closure_body_is_side_effecting(&if_expr.cond)
    }

    /// For an `Expr::If`, the single tail expression of the then-branch block,
    /// if the block contains exactly one expression statement (no semicolon).
    /// Returns `None` for any non-If or a then-branch with more/fewer statements.
    /// All raw syn field access lives HERE.
    pub(crate) fn if_then_single_expr_frag(&self) -> Option<SourceFragment<'a>> {
        let FragNode::Expr(syn::Expr::If(if_expr)) = &self.node else {
            return None;
        };
        let [syn::Stmt::Expr(e, None)] = if_expr.then_branch.stmts.as_slice() else {
            return None;
        };
        Some(Self::expr(e, self.file))
    }

    // -- Cast accessors -------------------------------------------------------

    /// The inner expression of an `Expr::Cast` (`x` in `x as T`).
    /// Returns `None` for any non-Cast fragment.
    /// All raw syn field access lives HERE.
    pub(crate) fn cast_inner_frag(&self) -> Option<SourceFragment<'a>> {
        let FragNode::Expr(syn::Expr::Cast(cast)) = &self.node else {
            return None;
        };
        Some(Self::expr(&cast.expr, self.file))
    }

    /// Returns `true` if this is a Cast whose target type is `_` (infer).
    /// Transparent casts (`x as _`) delegate to the inner expression.
    pub(crate) fn cast_is_infer(&self) -> bool {
        let FragNode::Expr(syn::Expr::Cast(cast)) = &self.node else {
            return false;
        };
        matches!(cast.ty.as_ref(), syn::Type::Infer(_))
    }

    /// Returns `true` if this is a Cast to a slice reference (`&[T]` / `&[_]` /
    /// `&mut [T]`). An unsizing coercion (`&[T; N] as &[T]`) is value-preserving
    /// so `cast_term` treats it transparently.
    pub(crate) fn cast_is_slice_ref(&self) -> bool {
        let FragNode::Expr(syn::Expr::Cast(cast)) = &self.node else {
            return false;
        };
        matches!(
            cast.ty.as_ref(),
            syn::Type::Reference(r) if matches!(r.elem.as_ref(), syn::Type::Slice(_))
        )
    }

    /// Returns `true` if this is a Cast to a raw pointer (`*const T` / `*mut T`).
    pub(crate) fn cast_is_raw_ptr(&self) -> bool {
        let FragNode::Expr(syn::Expr::Cast(cast)) = &self.node else {
            return false;
        };
        matches!(cast.ty.as_ref(), syn::Type::Ptr(_))
    }

    /// Returns `true` if this is a Cast to a shared `dyn Any` reference
    /// (`&dyn Any` or `&dyn std::any::Any`). Delegates to `is_shared_dyn_any_type`.
    pub(crate) fn cast_is_shared_dyn_any(&self) -> bool {
        let FragNode::Expr(syn::Expr::Cast(cast)) = &self.node else {
            return false;
        };
        crate::is_shared_dyn_any_type(&cast.ty)
    }

    /// For a Cast to a primitive scalar target, returns the `cast:` ctor suffix
    /// (e.g. `"u8"`, `"i32"`, `"char"`, `"f64"`). Returns `None` for non-Cast
    /// fragments or non-scalar target types. Delegates to `scalar_cast_type_key`.
    pub(crate) fn cast_scalar_type_key(&self) -> Option<&'static str> {
        let FragNode::Expr(syn::Expr::Cast(cast)) = &self.node else {
            return None;
        };
        crate::scalar_cast_type_key(&cast.ty)
    }

    /// The canonical type-key string for the Cast target type (e.g. `"&dyn Any"`
    /// for a shared-dyn-any cast). Used for `cast:<T>` ctor names.
    /// Returns an empty string for non-Cast fragments.
    /// Delegates to `type_key` in `lib.rs`. All raw syn access lives HERE.
    pub(crate) fn cast_full_type_key_str(&self) -> String {
        let FragNode::Expr(syn::Expr::Cast(cast)) = &self.node else {
            return String::new();
        };
        crate::type_key(&cast.ty)
    }

    // -- Raw-pointer value check -----------------------------------------------

    /// Returns `true` if this fragment is a raw-pointer value in scope: a cast to
    /// `*const T`/`*mut T`, a path whose let-binding is typed or initialised as a
    /// raw pointer, or a `Paren`/`Group` wrapping thereof. Depth is bounded at 8
    /// to prevent unbounded recursion through chained let-bindings. All raw syn
    /// field access lives inside `raw_pointer_arithmetic::raw_pointer_value_in_scope`;
    /// recognizer bodies see only `bool`.
    pub(crate) fn is_raw_pointer_value_in_scope(
        &self,
        fcx: &crate::sugar::factory::SugarBuildCtx<'_, '_>,
        depth: usize,
    ) -> bool {
        let Some(expr) = self.as_expr() else {
            return false;
        };
        crate::sugar::raw_pointer_arithmetic::raw_pointer_value_in_scope(expr, fcx, depth)
    }

    // -- int-literal fold accessor (transitional; raw syn lives HERE) ----------

    /// Const-fold this fragment to an exact integer value through
    /// `int_literal::exact_int_value`. Handles int/byte literals, negated
    /// literals, and let-bound / const-path scalars when `fcx` is `Some`.
    /// Returns `None` for non-literal, non-path, or runtime expressions.
    /// All raw syn access lives HERE, not in the calling recognizer.
    pub(crate) fn exact_int_value_frag(
        &self,
        fcx: Option<&crate::sugar::factory::SugarBuildCtx<'_, '_>>,
    ) -> Option<crate::sugar::int_literal::ExactInt> {
        let expr = self.as_expr()?;
        crate::sugar::int_literal::exact_int_value(expr, fcx)
    }

    /// Const-fold this fragment through the exact closed evaluator and return a
    /// `u128` value. All raw syn access lives HERE, not in recognizer bodies.
    pub(crate) fn const_eval_u128_empty_env(&self) -> Option<u128> {
        let expr = self.as_expr()?;
        crate::const_eval(expr, &std::collections::BTreeMap::new())?.as_u128()
    }

    // -- macro token-stream accessor ------------------------------------------

    /// Returns the raw `proc_macro2::TokenStream` of the macro body for an
    /// `Expr::Macro` fragment. Returns `None` for non-Macro fragments.
    /// All raw syn access lives HERE.
    pub(crate) fn macro_token_stream(&self) -> Option<proc_macro2::TokenStream> {
        let FragNode::Expr(syn::Expr::Macro(m)) = &self.node else {
            return None;
        };
        Some(m.mac.tokens.clone())
    }

    // -- macro mut-local scan -------------------------------------------------

    /// Returns `true` if the macro's token stream (for an `Expr::Macro` fragment)
    /// contains an identifier that is a `mut` local in `scope`, or a string literal
    /// whose `{…}` format holes name a `mut` local. Returns `false` for non-Macro
    /// fragments. Mirrors the token scan in `macro_term::recognize`; all raw syn +
    /// proc_macro2 access lives HERE.
    pub(crate) fn macro_contains_mut_local(&self, scope: &crate::TemporalScope) -> bool {
        let FragNode::Expr(syn::Expr::Macro(m)) = &self.node else {
            return false;
        };
        m.mac.tokens.clone().into_iter().any(|tt| match &tt {
            proc_macro2::TokenTree::Ident(id) => scope.is_mut_local(&id.to_string()),
            proc_macro2::TokenTree::Literal(lit) => {
                let text = lit.to_string();
                crate::macro_literal_contains_mut_local(&text, scope)
            }
            _ => false,
        })
    }

    // -- macro cfg-predicate parse --------------------------------------------

    /// For an `Expr::Macro` fragment, parse the macro body as a `CfgPredicate`.
    /// Returns `None` for non-Macro fragments; `Some(Ok(predicate))` on success;
    /// `Some(Err(msg))` when the body does not parse. The `syn::Error` is
    /// converted to a `String` so the caller sees no raw syn error type.
    /// All raw syn access lives HERE.
    pub(crate) fn macro_parse_cfg_predicate(&self) -> Option<Result<crate::CfgPredicate, String>> {
        let FragNode::Expr(syn::Expr::Macro(m)) = &self.node else {
            return None;
        };
        Some(
            m.mac
                .parse_body::<crate::CfgPredicate>()
                .map_err(|e| e.to_string()),
        )
    }

    // -- closure accessors ----------------------------------------------------

    /// Returns `true` if this fragment is an `Expr::Closure` with zero input
    /// parameters (no arguments). Returns `false` for all non-Closure
    /// fragments and for closures that have one or more parameters.
    /// All raw syn access lives HERE.
    pub(crate) fn closure_is_zero_input(&self) -> bool {
        match &self.node {
            FragNode::Expr(syn::Expr::Closure(c)) => c.inputs.is_empty(),
            _ => false,
        }
    }

    /// Returns the body expression of an `Expr::Closure` as a `SourceFragment`.
    /// Returns `None` for non-Closure fragments.
    /// All raw syn access lives HERE.
    pub(crate) fn closure_body_frag(&self) -> Option<SourceFragment<'a>> {
        match &self.node {
            FragNode::Expr(syn::Expr::Closure(c)) => Some(Self::expr(c.body.as_ref(), self.file)),
            _ => None,
        }
    }

    /// For a closure with exactly one parameter, returns the parameter name as
    /// a `String`. Strips `Pat::Reference` and `Pat::Type` wrappers via
    /// `crate::closure_single_param_ident`. Returns `None` for non-Closure
    /// fragments, zero-parameter closures, multi-parameter closures, or
    /// parameters that are not simple idents. All raw syn access lives HERE.
    pub(crate) fn closure_single_param_name(&self) -> Option<String> {
        let FragNode::Expr(syn::Expr::Closure(c)) = &self.node else {
            return None;
        };
        if c.inputs.len() != 1 {
            return None;
        }
        crate::closure_single_param_ident(&c.inputs[0])
    }

    // -- char-range-collect-string accessors -----------------------------------

    /// Returns `true` if this fragment is a `.collect::<String>()` method call
    /// with exactly one turbofish generic argument that is a `Type::Path` whose
    /// last segment ident is `"String"` and has no qualified self.
    /// All raw syn access lives HERE; `char_range_collect_string::recognize`
    /// sees only `bool`.
    pub(crate) fn call_collects_string(&self) -> bool {
        let FragNode::Expr(syn::Expr::MethodCall(call)) = &self.node else {
            return false;
        };
        let Some(turbofish) = &call.turbofish else {
            return false;
        };
        if turbofish.args.len() != 1 {
            return false;
        }
        matches!(
            turbofish.args.first(),
            Some(syn::GenericArgument::Type(syn::Type::Path(path)))
                if path.qself.is_none()
                    && path.path.segments.last().is_some_and(|seg| seg.ident == "String")
        )
    }

    /// Returns `Some(())` if this fragment is a `|param| param as char` closure:
    /// exactly one single-ident input parameter, and a body (after stripping
    /// `Expr::Block`/refs/parens/groups) that is a `Cast` of that same ident
    /// to `char`. Handles both `|b| b as char` and `|b| { b as char }`.
    /// All raw syn access lives HERE; `char_range_collect_string::recognize`
    /// sees only `Option<()>`.
    pub(crate) fn closure_recognizes_char_cast(&self) -> Option<()> {
        let FragNode::Expr(syn::Expr::Closure(closure)) = &self.node else {
            return None;
        };
        if closure.inputs.len() != 1 {
            return None;
        }
        let param = crate::closure_single_param_ident(&closure.inputs[0])?;
        // Handle both `|b| b as char` and `|b| { b as char }`.
        let body_raw = crate::strip_refs_groups(&closure.body);
        let body: &syn::Expr = match body_raw {
            syn::Expr::Block(block) => match block.block.stmts.as_slice() {
                [syn::Stmt::Expr(expr, None)] => expr,
                _ => return None,
            },
            other => other,
        };
        let syn::Expr::Cast(cast) = crate::strip_refs_groups(body) else {
            return None;
        };
        if !matches!(
            crate::strip_refs_groups(&cast.expr),
            syn::Expr::Path(path)
                if path.path.get_ident().is_some_and(|ident| ident == param.as_str())
        ) {
            return None;
        }
        matches!(
            cast.ty.as_ref(),
            syn::Type::Path(path)
                if path.qself.is_none()
                    && path.path.segments.last().is_some_and(|seg| seg.ident == "char")
        )
        .then_some(())
    }

    /// Returns `true` if this fragment (as an expression) resolves to a literal
    /// sequence via `method_family::resolves_literal_sequence`. Peels fold
    /// adaptors and checks the base. All raw syn access lives in the delegate.
    /// Returns `false` for non-Expr fragments.
    pub(crate) fn resolves_literal_sequence_frag(
        &self,
        fcx: &crate::sugar::factory::SugarBuildCtx<'_, '_>,
    ) -> bool {
        let Some(expr) = self.as_expr() else {
            return false;
        };
        crate::sugar::method_family::resolves_literal_sequence(expr, fcx.let_inits())
    }

    /// Builds the composite literal sequence `Sugar` for this fragment's expression.
    /// Returns `None` if the fragment is not an expression, or does not resolve to
    /// a literal sequence. Delegates to `method_family::build_literal_sequence_composite`;
    /// all raw syn access lives in the delegate.
    pub(crate) fn build_literal_sequence_composite_frag(
        &self,
        fcx: &crate::sugar::factory::SugarBuildCtx<'_, '_>,
    ) -> Option<Box<dyn crate::Sugar>> {
        let expr = self.as_expr()?;
        crate::sugar::method_family::build_literal_sequence_composite(expr, fcx)
    }

    // -- size_of call accessor ------------------------------------------------

    /// Decode a `[std|core::]mem::size_of::<T>()` call site. Returns `None` if:
    ///   - the fragment is not an `Expr::Call`,
    ///   - the call has positional arguments,
    ///   - the callee is not an unqualified path whose final segment is `size_of`,
    ///   - the path matches a user-defined `size_of` fn visible in scope, or
    ///   - the last path segment has zero or >=2 generic type arguments.
    ///
    /// All raw syn field access lives HERE; recognizer bodies see only
    /// `Option<SizeOfTypeParts>`.
    pub(crate) fn call_size_of_type_parts(
        &self,
        fcx: &crate::sugar::factory::SugarBuildCtx<'_, '_>,
    ) -> Option<SizeOfTypeParts> {
        // Gate: must be an Expr::Call.
        let syn::Expr::Call(call) = self.as_expr()? else {
            return None;
        };
        // Zero positional arguments required.
        if !call.args.is_empty() {
            return None;
        }
        // Callee: unqualified path only.
        let syn::Expr::Path(syn::ExprPath {
            qself: None, path, ..
        }) = call.func.as_ref()
        else {
            return None;
        };
        // Path must be a compiler size_of path.
        if !size_of_is_compiler_path(path, fcx) {
            return None;
        }
        // Last segment must carry exactly one angle-bracketed type argument.
        let last = path.segments.last()?;
        let syn::PathArguments::AngleBracketed(args) = &last.arguments else {
            return None;
        };
        if args.args.len() != 1 {
            return None;
        }
        let Some(syn::GenericArgument::Type(ty)) = args.args.first() else {
            return None;
        };
        // Derive fragment-native data -- all raw syn access ends here.
        let ty_key = crate::type_key(ty);
        let ty_src = quote::ToTokens::to_token_stream(ty).to_string();
        let primitive_size = size_of_primitive_size(ty);
        let atomic_size = size_of_core_atomic_size(ty);
        Some(SizeOfTypeParts {
            ty_key,
            ty_src,
            primitive_size,
            atomic_size,
        })
    }

    // -- Slice accessor helpers -----------------------------------------------

    /// Build a `SugarBody<CompositeFloor>` for this fragment as a "slice sequence",
    /// preferring a pre-built literal-sequence composite node when one is available.
    /// Falls back to `SugarBody::composite_frag` for non-literal expressions. Mirrors
    /// the `sequence_body` helper formerly in `slice_accessor.rs`; all raw syn access
    /// lives inside the delegates (`build_literal_sequence_composite_frag` and
    /// `SugarBody::composite_frag`).
    pub(crate) fn sequence_body_frag(
        &self,
        fcx: &crate::sugar::factory::SugarBuildCtx<'_, '_>,
    ) -> crate::sugar::factory::SugarBody<crate::sugar::factory::CompositeFloor> {
        use crate::sugar::factory::SugarBody;
        match self.build_literal_sequence_composite_frag(fcx) {
            Some(node) => SugarBody::from_node(node),
            None => SugarBody::composite_frag(self, fcx),
        }
    }

    /// Returns `true` if this fragment's expression (after stripping
    /// `Reference`/`Paren`/`Group` wrappers) has the shape of a "slice-like"
    /// receiver for `.first()`, `.last()`, `.get()`, `.contains()`,
    /// `.starts_with()`, `.ends_with()` -- i.e. a literal array/repeat/index
    /// expression, or a bound name whose initialiser resolves to one. Returns
    /// `false` for string/range/tuple receivers (handled by other sugars) and
    /// for non-Expr fragments. Mirrors the `slice_receiver_shape` helper formerly
    /// in `slice_accessor.rs`; all raw syn access lives HERE.
    pub(crate) fn slice_receiver_shape_frag(
        &self,
        fcx: &crate::sugar::factory::SugarBuildCtx<'_, '_>,
    ) -> bool {
        let Some(expr) = self.as_expr() else {
            return false;
        };
        slice_receiver_shape_impl(expr, fcx, 0)
    }

    // -- block / unsafe block detector (used by block_term::recognize) -------

    /// Returns `true` if this fragment is an `Expr::Block` (value block) or
    /// `Expr::Unsafe` (unsafe block). Used by `block_term::recognize` to gate
    /// without touching raw syn. Raw syn field access lives in `match &self.node`.
    pub(crate) fn is_block_or_unsafe(&self) -> bool {
        matches!(
            &self.node,
            FragNode::Expr(syn::Expr::Block(_)) | FragNode::Expr(syn::Expr::Unsafe(_))
        )
    }
}

fn is_non_value_tail_control_expr(expr: &syn::Expr) -> bool {
    match expr {
        syn::Expr::If(_)
        | syn::Expr::Block(_)
        | syn::Expr::Unsafe(_)
        | syn::Expr::Return(_)
        | syn::Expr::Break(_)
        | syn::Expr::Continue(_)
        | syn::Expr::ForLoop(_)
        | syn::Expr::While(_)
        | syn::Expr::Let(_) => true,
        syn::Expr::Loop(loop_expr) => !loop_tail_has_single_unlabeled_break_payload(loop_expr),
        syn::Expr::Paren(paren) => is_non_value_tail_control_expr(&paren.expr),
        syn::Expr::Group(group) => is_non_value_tail_control_expr(&group.expr),
        _ => false,
    }
}

fn loop_tail_has_single_unlabeled_break_payload(loop_expr: &syn::ExprLoop) -> bool {
    matches!(
        loop_expr.body.stmts.as_slice(),
        [syn::Stmt::Expr(syn::Expr::Break(break_expr), _)]
            if break_expr.label.is_none() && break_expr.expr.is_some()
    )
}

// ---------------------------------------------------------------------------
// size_of type-parts data + helpers (used by call_size_of_type_parts)
// ---------------------------------------------------------------------------

/// Data decoded from a `mem::size_of::<T>()` call site. All raw syn access
/// stays inside [`SourceFragment::call_size_of_type_parts`]; callers hold only
/// host-native types.
pub(crate) struct SizeOfTypeParts {
    /// Canonical type key (as produced by `crate::type_key`).
    pub ty_key: String,
    /// Token-stream string for the type argument (e.g. `"u32"` or
    /// `"std :: num :: NonZeroU32"`). Parseable back to `syn::Type`.
    pub ty_src: String,
    /// Precomputed size in bytes for a primitive type, or `None`.
    pub primitive_size: Option<i128>,
    /// Precomputed size in bytes for a `core::sync::atomic` type, or `None`.
    pub atomic_size: Option<i128>,
}

/// Returns `true` when `path` is one of the compiler-owned `size_of` spellings:
/// bare `size_of` (when no user `size_of` fn shadows it in scope),
/// `mem::size_of`, `std::mem::size_of`, or `core::mem::size_of`.
/// Raw syn access lives HERE.
fn size_of_is_compiler_path(
    path: &syn::Path,
    fcx: &crate::sugar::factory::SugarBuildCtx<'_, '_>,
) -> bool {
    let segments: Vec<_> = path.segments.iter().collect();
    match segments.as_slice() {
        [size_of] if size_of.ident == "size_of" => !fcx.scope().has_visible_fn("size_of"),
        [mem, size_of] if mem.ident == "mem" && size_of.ident == "size_of" => true,
        [std_or_core, mem, size_of]
            if matches!(std_or_core.ident.to_string().as_str(), "std" | "core")
                && mem.ident == "mem"
                && size_of.ident == "size_of" =>
        {
            true
        }
        _ => false,
    }
}

/// Returns the host `mem::size_of` for a primitive Rust type (single-segment
/// path, no qself, no generic args). Raw syn access lives HERE.
fn size_of_primitive_size(ty: &syn::Type) -> Option<i128> {
    let syn::Type::Path(path) = ty else {
        return None;
    };
    if path.qself.is_some() || path.path.segments.len() != 1 {
        return None;
    }
    let segment = path.path.segments.first()?;
    if !matches!(segment.arguments, syn::PathArguments::None) {
        return None;
    }
    let size = match segment.ident.to_string().as_str() {
        "bool" => std::mem::size_of::<bool>(),
        "char" => std::mem::size_of::<char>(),
        "i8" => std::mem::size_of::<i8>(),
        "i16" => std::mem::size_of::<i16>(),
        "i32" => std::mem::size_of::<i32>(),
        "i64" => std::mem::size_of::<i64>(),
        "i128" => std::mem::size_of::<i128>(),
        "isize" => std::mem::size_of::<isize>(),
        "u8" => std::mem::size_of::<u8>(),
        "u16" => std::mem::size_of::<u16>(),
        "u32" => std::mem::size_of::<u32>(),
        "u64" => std::mem::size_of::<u64>(),
        "u128" => std::mem::size_of::<u128>(),
        "usize" => std::mem::size_of::<usize>(),
        "f32" => std::mem::size_of::<f32>(),
        "f64" => std::mem::size_of::<f64>(),
        _ => return None,
    };
    Some(size as i128)
}

/// Returns the known size in bytes for a `core::sync::atomic` type via the
/// documented layout guarantee (same size as underlying primitive). Recognises
/// bare (`AtomicU32`) and fully-qualified spellings via the LAST path segment.
/// Raw syn access lives HERE.
fn size_of_core_atomic_size(ty: &syn::Type) -> Option<i128> {
    let syn::Type::Path(path) = ty else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    let segment = path.path.segments.last()?;
    let ident = segment.ident.to_string();
    let size = match ident.as_str() {
        "AtomicBool" => std::mem::size_of::<bool>(),
        "AtomicU8" | "AtomicI8" => std::mem::size_of::<u8>(),
        "AtomicU16" | "AtomicI16" => std::mem::size_of::<u16>(),
        "AtomicU32" | "AtomicI32" => std::mem::size_of::<u32>(),
        "AtomicU64" | "AtomicI64" => std::mem::size_of::<u64>(),
        "AtomicUsize" => std::mem::size_of::<usize>(),
        "AtomicIsize" => std::mem::size_of::<isize>(),
        "AtomicPtr" => std::mem::size_of::<*const ()>(),
        _ => return None,
    };
    // Only `AtomicPtr` may carry a type argument; any other atomic with type
    // arguments is a user type with the same name -> decline (finite-or-refuse).
    if ident != "AtomicPtr" && !matches!(segment.arguments, syn::PathArguments::None) {
        return None;
    }
    Some(size as i128)
}

// ---------------------------------------------------------------------------
// Primitive-integer type kind helper (used by path_primitive_int_from_kind)
// ---------------------------------------------------------------------------

/// Decode a `&syn::Type` to an `IntKind` for the qualified-self form
/// `<IntT>::from`: the type must be a simple path (no qself, no args) whose
/// last segment is a known primitive integer type name.
fn primitive_int_type_kind_from_syn(ty: &syn::Type) -> Option<crate::sugar::int_literal::IntKind> {
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
#[cfg(test)]
pub(crate) fn parse_file(source: &str) -> syn::File {
    syn::parse_file(source).expect("source_fragment: parse_file failed")
}

// ---------------------------------------------------------------------------
// BV-op detection helper (used by `index_contains_bv_op_frag`)
// ---------------------------------------------------------------------------

/// Returns `true` iff `expr` contains at least one bit-operation binary operator
/// (`<<`, `>>`, `&`, `|`, `^`), indicating a bv32-routable index computation.
/// Recurses through binary ops, parens, casts, and groups. All raw syn field
/// access for the `index_contains_bv_op_frag` accessor lives HERE.
fn index_contains_bv_op_expr(expr: &syn::Expr) -> bool {
    match expr {
        syn::Expr::Binary(binary) => {
            matches!(
                binary.op,
                syn::BinOp::Shl(_)
                    | syn::BinOp::Shr(_)
                    | syn::BinOp::BitAnd(_)
                    | syn::BinOp::BitOr(_)
                    | syn::BinOp::BitXor(_)
            ) || index_contains_bv_op_expr(&binary.left)
                || index_contains_bv_op_expr(&binary.right)
        }
        syn::Expr::Paren(p) => index_contains_bv_op_expr(&p.expr),
        syn::Expr::Cast(c) => index_contains_bv_op_expr(&c.expr),
        syn::Expr::Group(g) => index_contains_bv_op_expr(&g.expr),
        _ => false,
    }
}

// ---------------------------------------------------------------------------
// Char-receiver literal-resolve helper (used by `char_to_string_receiver_resolves_literal`)
// ---------------------------------------------------------------------------

/// Recursively check whether `expr` (after stripping ref/paren/group wrappers)
/// resolves to a `char` literal, following single-ident let-binding chains through
/// `fcx`. All raw syn access lives HERE; the public SourceFragment method delegates
/// to this fn so recognizer bodies stay clean.
fn char_to_string_receiver_resolves_literal_raw(
    expr: &syn::Expr,
    fcx: &crate::sugar::factory::SugarBuildCtx<'_, '_>,
) -> bool {
    let expr = strip_refs_groups_expr(expr);
    match expr {
        syn::Expr::Lit(l) => matches!(l.lit, syn::Lit::Char(_)),
        syn::Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(|i| i.to_string()) else {
                return false;
            };
            if fcx.resolving_bound_path(&name) {
                return false;
            }
            let Some(init) = fcx
                .let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
            else {
                return false;
            };
            let child_fcx = fcx.with_bound_path(&name);
            char_to_string_receiver_resolves_literal_raw(init, &child_fcx)
        }
        _ => false,
    }
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
            syn::Lit::Int(i) => i.base10_parse::<i128>().ok(),
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
        #[cfg(test)]
        FragNode::File(_) => return (0, 0),
        #[cfg(test)]
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
        Struct(_) => "Struct".into(),
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
        syn::Item::Mod(_) => "Mod",
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

#[cfg(test)]
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
#[cfg(test)]
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
#[cfg(test)]
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
        Block(b) => b
            .block
            .stmts
            .iter()
            .map(|s| SourceFragment::stmt(s, file))
            .collect(),
        Return(r) => r
            .expr
            .as_deref()
            .map(|e| SourceFragment::expr(e, file))
            .into_iter()
            .collect(),
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
        Array(a) => a
            .elems
            .iter()
            .map(|e| SourceFragment::expr(e, file))
            .collect(),
        Tuple(t) => t
            .elems
            .iter()
            .map(|e| SourceFragment::expr(e, file))
            .collect(),
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
// Slice-shape helpers (used by SourceFragment::slice_receiver_shape_frag)
// ---------------------------------------------------------------------------

/// Returns `true` when `expr` (after stripping `Reference`/`Paren`/`Group`) has
/// the shape of a "slice-like" receiver -- a literal array/repeat/index, a bound
/// name whose initialiser resolves to one, or a mutable/unstable local. All raw
/// syn access lives HERE; the public API is `SourceFragment::slice_receiver_shape_frag`.
fn slice_receiver_shape_impl(
    expr: &syn::Expr,
    fcx: &crate::sugar::factory::SugarBuildCtx<'_, '_>,
    depth: usize,
) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups_expr(expr) {
        syn::Expr::Range(_)
        | syn::Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Str(_),
            ..
        }) => false,
        syn::Expr::Array(_) | syn::Expr::Repeat(_) | syn::Expr::Index(_) => true,
        syn::Expr::Reference(reference) => {
            slice_receiver_shape_impl(&reference.expr, fcx, depth + 1)
        }
        syn::Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(ToString::to_string) else {
                return false;
            };
            let bound = fcx
                .let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
                .or_else(|| fcx.scope().let_binding_for_audit(&name));
            bound.is_some_and(|init| {
                !matches!(
                    strip_refs_groups_expr(init),
                    syn::Expr::Range(_) | syn::Expr::Tuple(_)
                ) && !text_receiver_shape_impl(init, fcx, depth + 1)
                    && (slice_receiver_shape_impl(init, fcx, depth + 1)
                        || fcx.scope().is_mut_local(&name))
            }) || fcx.scope().is_temporally_unstable_read(&name)
                || fcx.scope().unknown_mutation_reason(&name).is_some()
        }
        syn::Expr::MethodCall(call) if call.args.is_empty() => {
            matches!(
                call.method.to_string().as_str(),
                "as_slice" | "to_vec" | "to_owned" | "into_vec"
            ) && slice_receiver_shape_impl(&call.receiver, fcx, depth + 1)
        }
        other => crate::sugar::collection_literal::collection_literal_array(other).is_some(),
    }
}

/// Returns `true` when `expr` is a string-valued expression: a string literal,
/// a `format!` macro, a bound name pointing to one, or a String-returning method
/// chain. Used by `slice_receiver_shape_impl` to exclude string variables from the
/// slice lane. All raw syn access lives HERE.
fn text_receiver_shape_impl(
    expr: &syn::Expr,
    fcx: &crate::sugar::factory::SugarBuildCtx<'_, '_>,
    depth: usize,
) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups_expr(expr) {
        syn::Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Str(_),
            ..
        }) => true,
        syn::Expr::Macro(m) => m
            .mac
            .path
            .segments
            .last()
            .is_some_and(|s| s.ident == "format"),
        syn::Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(ToString::to_string) else {
                return false;
            };
            fcx.let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
                .is_some_and(|init| text_receiver_shape_impl(init, fcx, depth + 1))
        }
        syn::Expr::MethodCall(call) if call.method == "to_string" && call.args.is_empty() => {
            text_receiver_shape_impl(&call.receiver, fcx, depth + 1)
        }
        syn::Expr::MethodCall(call) if slice_string_result_method(&call.method.to_string()) => {
            text_receiver_shape_impl(&call.receiver, fcx, depth + 1)
        }
        _ => false,
    }
}

/// The set of `String`-returning methods that keep a text receiver shape through a
/// chain. Mirrors `string_result_method` formerly in `slice_accessor.rs`.
fn slice_string_result_method(method: &str) -> bool {
    matches!(
        method,
        "to_ascii_uppercase"
            | "to_ascii_lowercase"
            | "to_uppercase"
            | "to_lowercase"
            | "replace"
            | "trim"
            | "trim_start"
            | "trim_end"
            | "repeat"
    )
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
        let file =
            parse_file("fn classify(n: u32) -> u32 {\n    if n > 5 { return 50; }\n    0\n}\n");
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

    #[test]
    fn item_mod_observed_is_named_structural_membrane() {
        let file = parse_file("mod tests { fn inner() {} }\n");
        let frag = SourceFragment::from_node(FragNode::Item(&file.items[0]), "mod.rs");

        assert_eq!(
            frag.observed(),
            "Mod",
            "Item::Mod must be named explicitly; collapsing to Other:Item hides the membrane row"
        );
    }

    #[test]
    fn stmt_tail_noncf_excludes_non_value_loop_tail() {
        let file = parse_file("fn f() -> i32 { loop {} }\n");
        let item = root_fn_item(&file);
        let frag = fn_frag(item, "loop_tail.rs");
        let body = frag.function_body().expect("fn body");
        let stmts = body.statements();
        assert_eq!(stmts.len(), 1);
        assert!(
            stmts[0].observed().contains("Loop") || stmts[0].observed() == "Expr",
            "loop tail observed as expr bucket: {}",
            stmts[0].observed()
        );
        assert!(
            stmts[0].stmt_tail_expr_noncf().is_none(),
            "a loop without a break payload is control flow, not a return value"
        );
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
