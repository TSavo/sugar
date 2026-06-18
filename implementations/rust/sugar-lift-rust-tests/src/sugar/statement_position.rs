// SPDX-License-Identifier: Apache-2.0
//
// `StatementPositionSugar`: the REFUSE-side node for a bare expression-statement whose
// asserted value flows through a RUNTIME continuation that is NOT IN SCOPE. It OWNS, in its
// own `desugar`, every statement-position terminal verdict the old external pair of
// predicates -- `statement_position_terminal_effect` (a future continuation `ControlFlow`,
// an opaque `Reflection` scrutinee, a runtime `LoopAdvance`) and `runtime_expr_statement_effect`
// (a `&mut`-aliased / mutated `RuntimeExprStmt` read) -- made. Those verdicts all hang off
// ONE statement expr scanned for ONE of four mutually-distinct runtime signals, so they live
// in ONE node, not in a scattered predicate pair sequenced by `.or_else` at the call site.
//
// THE TARGET SHAPE (`walk -> new -> compose -> desugar() collapses to one Outcome`):
// `decompose_statement_position` (the `build` arm) recognizes the construct (a bare statement
// expr that carries an assertion) and `new`s the node, composing the statement expr as the
// single CHILD LEAF -- with NO degeneracy opinion and no early exit (its only `None` is
// non-recognition: an expr with no assert is not a statement-position bucket -- nothing to
// classify). `desugar` is where the verdict is made, and EACH LEAF owns its own degeneracy,
// scanned over the SAME statement expr:
//   * the CONTINUATION leaf: an `.await` anywhere, or a free-fn `block_on(async{..})`, is a
//     future driven by a runtime executor -- the awaited value is NOT in scope -> `ControlFlow`;
//   * the REFLECTION leaf: a `match <reflection> { .. }` whose scrutinee is `Type::of`/`.info()`
//     (after stripping a `const { .. }` wrapper) reads compiler-determined type identity, not a
//     constructed literal -> `Reflection`;
//   * the LOOP leaf: a `loop { .. }` whose body advances a runtime iterator (`iter.next()` /
//     `.size_hint()`) has no finite literal construction to enumerate -> `LoopAdvance`;
//   * the ALIASED-READ leaf: a statement whose asserted value flows through a `&mut` borrow or
//     a mutation (`+=`, `=`, ...) is mutably aliased -- no single timeless `t` -> `RuntimeExprStmt`.
// The composite makes NO check of its own: it sequences the leaves in the wire-format precedence
// (continuation, then reflection, then loop, then aliased-read -- the original predicate order,
// then its `.or_else`) and `?`-propagates the first `Hit`. The honest-unclassified case (a
// statement carrying a CONSTRUCTED literal value -- no await/reflection/loop-advance/`&mut`) is
// the STRUCTURAL backstop (`Effect::Unsupported` with `STRUCTURAL_BACKSTOP_REASON`) -- a `Hit`
// the fall-through consumer discards exactly as the old `None` was, never a fake-refuse.

use syn::{BinOp, Expr};

use crate::sugar::factory::SugarBuildCtx;
use crate::{
    closure_body_advances_iterator, count_asserts_in_expr, expr_contains_await,
    is_free_fn_block_on_async, reflection_scrutinee, strip_const_block, token_key, Effect, Outcome,
    Sugar, SugarCtx, STRUCTURAL_BACKSTOP_REASON,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::statement_effect("statement_position", recognize);

/// REFUSE-side statement-position recognizer ([`StatementPositionSugar`] via
/// [`decompose_statement_position`]): `Some` only for a bare statement expr that carries an
/// assertion, else `None`. The statement-effect claim owns the runtime-continuation verdict
/// in its own `desugar`. Ctx-independent (the build env is unused).
pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    decompose_statement_position(expr).map(|node| Box::new(node) as Box<dyn Sugar>)
}

/// The bare expression-statement whose asserted value flows through an out-of-scope runtime
/// continuation, composed as a node whose `desugar` makes every statement-position terminal
/// verdict at the LEAVES (continuation / reflection / loop / aliased-read). See the module header.
pub(crate) struct StatementPositionSugar {
    /// The full statement expr -- the `boundary` token-key is `token_key(&expr)`, and the leaf
    /// over which all four runtime signals are scanned.
    expr: Expr,
}

impl StatementPositionSugar {
    /// CONTINUATION leaf: an `.await` anywhere, or a free-fn `block_on(async{..})`, drives a
    /// future to completion via a runtime executor -- the awaited value is produced by the
    /// executor, not constructed from source literals (value NOT in scope) -> `ControlFlow`.
    /// No such continuation -> `None` (the leaf Digs -- keep going to the other leaves).
    fn control_flow_effect(&self, boundary: &str) -> Option<Effect> {
        if expr_contains_await(&self.expr) || is_free_fn_block_on_async(&self.expr) {
            return Some(Effect::ControlFlow {
                boundary: boundary.to_string(),
            });
        }
        None
    }

    /// REFLECTION leaf: a `match <reflection> { .. }` whose scrutinee is `Type::of`/`TypeId::of`/
    /// `.info()` (after stripping a `const { .. }`/paren/group/field wrapper) reads compiler-
    /// determined type identity, not a value constructed from source literals -> `Reflection`
    /// (the rendered scrutinee is the boundary). A `match` over a CONSTRUCTED literal scrutinee
    /// matches none of these -> `None` (the leaf Digs).
    fn reflection_effect(&self) -> Option<Effect> {
        if let Expr::Match(m) = &self.expr {
            let scrut = strip_const_block(&m.expr);
            if let Some(boundary) = reflection_scrutinee(scrut) {
                return Some(Effect::Reflection { boundary });
            }
        }
        None
    }

    /// LOOP leaf: a `loop { .. }` whose body advances a RUNTIME iterator (`iter.next()` /
    /// `.size_hint()`) has no finite literal construction to enumerate, and the advanced
    /// iterator's per-iteration bounds are not a single timeless value -> `LoopAdvance`. A
    /// `loop` over a pure value (or any non-loop) -> `None` (the leaf Digs).
    fn loop_advance_effect(&self, boundary: &str) -> Option<Effect> {
        if let Expr::Loop(l) = &self.expr {
            let body = Expr::Block(syn::ExprBlock {
                attrs: Vec::new(),
                label: None,
                block: l.body.clone(),
            });
            if loop_body_advances_runtime_iterator(&body) {
                return Some(Effect::LoopAdvance {
                    boundary: boundary.to_string(),
                });
            }
        }
        None
    }

    /// ALIASED-READ leaf: a statement whose asserted value is read through a `&mut` borrow or a
    /// mutation -- e.g. the borrow/drop-scoping tuple `(assert_matches!(*MutRefWithDrop(&mut
    /// val).0, 0), mem::take(&mut val))`. A mutably aliased read has no single timeless `t` ->
    /// `RuntimeExprStmt`. A statement over a CONSTRUCTED literal value (no `&mut`, no mutation)
    /// -> `None` (the leaf Digs). Detection is by a positive `&mut`/assignment signal only.
    fn aliased_read_effect(&self, boundary: &str) -> Option<Effect> {
        #[derive(Default)]
        struct Scan {
            runtime: bool,
        }
        impl<'ast> syn::visit::Visit<'ast> for Scan {
            fn visit_expr_reference(&mut self, r: &'ast syn::ExprReference) {
                if r.mutability.is_some() {
                    self.runtime = true;
                }
                syn::visit::visit_expr_reference(self, r);
            }
            fn visit_expr_assign(&mut self, _: &'ast syn::ExprAssign) {
                self.runtime = true;
            }
            fn visit_expr_binary(&mut self, b: &'ast syn::ExprBinary) {
                if matches!(
                    b.op,
                    BinOp::AddAssign(_)
                        | BinOp::SubAssign(_)
                        | BinOp::MulAssign(_)
                        | BinOp::DivAssign(_)
                        | BinOp::RemAssign(_)
                        | BinOp::BitXorAssign(_)
                        | BinOp::BitAndAssign(_)
                        | BinOp::BitOrAssign(_)
                        | BinOp::ShlAssign(_)
                        | BinOp::ShrAssign(_)
                ) {
                    self.runtime = true;
                }
                syn::visit::visit_expr_binary(self, b);
            }
        }
        let mut scan = Scan::default();
        syn::visit::Visit::visit_expr(&mut scan, &self.expr);
        if scan.runtime {
            Some(Effect::RuntimeExprStmt {
                boundary: boundary.to_string(),
            })
        } else {
            None
        }
    }
}

impl Sugar for StatementPositionSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        let boundary = token_key(&self.expr);
        // The composite makes NO verdict of its own: it sequences the four leaves in the
        // wire-format precedence (continuation, then reflection, then loop -- the original
        // `statement_position_terminal_effect` order -- then the aliased-read, the original
        // `.or_else(runtime_expr_statement_effect)`) and propagates the first leaf that `Hit`s.
        // If all four Dig, this is the honest-unclassified case -- the STRUCTURAL backstop the
        // fall-through consumer discards as the old `None`.
        if let Some(effect) = self
            .control_flow_effect(&boundary)
            .or_else(|| self.reflection_effect())
            .or_else(|| self.loop_advance_effect(&boundary))
            .or_else(|| self.aliased_read_effect(&boundary))
        {
            return Outcome::Hit(effect);
        }
        Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })
    }
}

/// True if a loop body advances a RUNTIME iterator (`iter.next()` / `.size_hint()` reads
/// driving the loop). Reuses the iterator-advance scan (`closure_body_advances_iterator`,
/// imported from `crate::`) plus a `.size_hint()` probe (the size-hint loop reads
/// non-deterministic per-iteration bounds). Lives with the LOOP leaf it serves.
fn loop_body_advances_runtime_iterator(body: &Expr) -> bool {
    if closure_body_advances_iterator(body) {
        return true;
    }
    struct Scan {
        found: bool,
    }
    impl<'ast> syn::visit::Visit<'ast> for Scan {
        fn visit_expr_method_call(&mut self, m: &'ast syn::ExprMethodCall) {
            if m.method == "size_hint" && m.args.is_empty() {
                self.found = true;
            }
            syn::visit::visit_expr_method_call(self, m);
        }
    }
    let mut s = Scan { found: false };
    syn::visit::Visit::visit_expr(&mut s, body);
    s.found
}

/// Build (`new` + compose, NO degeneracy opinion) a `StatementPositionSugar` from a bare
/// statement expr. Recognizes the construct: a statement expr that actually carries an
/// assertion (else this is not a statement-position bucket -- nothing to classify). Returns
/// `None` (declines to RECOGNIZE) for an assert-free statement. It makes NO verdict -- the
/// statement-position decision is `StatementPositionSugar::desugar`'s (and its leaves') alone.
pub(crate) fn decompose_statement_position(expr: &Expr) -> Option<StatementPositionSugar> {
    if count_asserts_in_expr(expr) == 0 {
        return None;
    }
    Some(StatementPositionSugar { expr: expr.clone() })
}
