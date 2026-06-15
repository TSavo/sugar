// SPDX-License-Identifier: Apache-2.0
//
// `ClosureAdaptorSugar`: the REFUSE-side node for a closure-bearing method statement
// (`<recv>.<adaptor>(|..| { asserts })`). It OWNS, in its own `desugar`, every order-loss
// verdict the old external `closure_method_terminal_effect` predicate made -- a `Tls` /
// `OpaqueRuntime`-accessor (a non-pure adaptor / opaque accessor), an `IterAdvance` /
// `Mutation` (a pure-adaptor side-effecting body), or an `OpaqueRuntime`-receiver (a pure
// body over a runtime receiver). Those verdicts hang off ONE walk + ONE receiver
// resolution, so they live in ONE node, not in a scattered predicate.
//
// THE TARGET SHAPE (`walk -> new -> compose -> desugar() collapses to one Outcome`):
// `decompose_closure_adaptor` (the `build` arm) recognizes the construct and `new`s the
// node, composing the receiver and body as CHILD LEAVES -- with NO degeneracy opinion and
// no early exit. `desugar` is where the verdict is made, and EACH LEAF owns its own
// degeneracy:
//   * the method is the ACCESSOR leaf: a non-pure adaptor `Hit`s `Tls`/`OpaqueRuntime`
//     (the accessor itself is an opaque/effectful boundary);
//   * the closure body is the BODY leaf: a side-effecting body `Hit`s `IterAdvance` (a
//     captured-iterator advance) or `Mutation` (a captured-state assignment);
//   * the receiver is the RECEIVER leaf: it Digs when it resolves to a finite LITERAL
//     domain (keep going -- the symbolic lifter handles it) and `Hit`s `OpaqueRuntime`
//     when it is runtime data (no finite construction to walk).
// The composite makes NO check of its own: it sequences the leaves in the wire-format
// precedence (accessor, then body, then receiver) and `?`-propagates the first `Hit`. The
// honest-unclassified case (pure adaptor, pure body, LITERAL receiver) is the STRUCTURAL
// backstop (`Effect::Unsupported` with `STRUCTURAL_BACKSTOP_REASON`) -- a `Hit` the
// fall-through consumer discards exactly as the old `None` was, never a fake-refuse.

use std::collections::BTreeMap;

use syn::{Expr, visit::Visit};

use crate::{
    bounded_domain_from_expr, closure_body_advances_iterator, closure_body_is_side_effecting,
    count_asserts_in_expr, peel_fold_adaptors, token_key, Effect, Outcome, Sugar, SugarCtx,
    PURE_CLOSURE_ADAPTORS, STRUCTURAL_BACKSTOP_REASON,
};

/// The closure-bearing method statement, composed as a node whose `desugar` makes every
/// order-loss verdict at the LEAVES (accessor / body / receiver). See the module header.
pub(crate) struct ClosureAdaptorSugar {
    /// The full statement expr -- the `boundary` token-key is `token_key(&expr)`.
    expr: Expr,
    /// The closure-bearing method name (`for_each` / `with` / `fold` / ...). The ACCESSOR
    /// leaf: a non-pure adaptor is itself the opaque/effectful boundary.
    method: String,
    /// The closure. The BODY leaf: its body is scanned for the side-effecting / iter-advance
    /// degeneracy.
    closure: syn::ExprClosure,
    /// The receiver of the closure-bearing call. The RECEIVER leaf: it Digs on a finite
    /// literal domain and `Hit`s `OpaqueRuntime` on runtime data.
    receiver: Expr,
    /// Owned snapshot of the in-scope `let` initializers (name -> init expr), captured at
    /// build time. Rebuilt into the borrowed `&Expr` map at desugar to drive
    /// `peel_fold_adaptors` -- the node owns its data (mirrors `FoldSugar::literal_arrays`).
    let_inits: BTreeMap<String, Expr>,
}

impl ClosureAdaptorSugar {
    /// ACCESSOR leaf: a non-pure adaptor (`.with`, `.with_unfilled_buf`, ...) ranges over
    /// runtime/opaque state, not a constructed literal domain -- bin-2. `.with` is the
    /// thread-local accessor (`Tls`); any other effectful accessor is the generic
    /// opaque-accessor boundary. A PURE adaptor is not an accessor boundary -> `None`
    /// (the leaf Digs -- keep going to the body / receiver leaves).
    fn accessor_effect(&self, boundary: &str) -> Option<Effect> {
        if PURE_CLOSURE_ADAPTORS.contains(&self.method.as_str()) {
            return None;
        }
        if self.method == "with" {
            return Some(Effect::Tls {
                boundary: boundary.to_string(),
            });
        }
        Some(Effect::OpaqueRuntime {
            boundary: boundary.to_string(),
            accessor: true,
        })
    }

    /// BODY leaf: a side-effecting closure body is an order-loss boundary -- distinguish the
    /// iterator-advance cause (`iter.next()`) from a captured-state mutation (`+=`, `&mut`,
    /// `.push`). Both are the SAME terminal class; typing them apart records the cause in
    /// the catalog. A PURE body -> `None` (the leaf Digs).
    fn body_effect(&self, boundary: &str) -> Option<Effect> {
        if !closure_body_is_side_effecting(&self.closure.body) {
            return None;
        }
        if closure_body_advances_iterator(&self.closure.body) {
            return Some(Effect::IterAdvance {
                boundary: boundary.to_string(),
            });
        }
        Some(Effect::Mutation {
            boundary: boundary.to_string(),
        })
    }

    /// RECEIVER leaf: does the receiver resolve to a finite literal domain? If YES, the leaf
    /// DIGS (`None`) -- this is a defoldable / for_each-liftable case the symbolic lifter
    /// handles (or declined for a recoverable reason), honest UNCLASSIFIED work, never
    /// fake-refused. If NO, the iterated/threaded values are runtime data -- the leaf `Hit`s
    /// `OpaqueRuntime` (bin-2, no finite construction to walk).
    fn receiver_effect(&self, boundary: &str, ctx: &SugarCtx) -> Option<Effect> {
        let borrowed: BTreeMap<String, &Expr> =
            self.let_inits.iter().map(|(k, v)| (k.clone(), v)).collect();
        let resolves_literal = peel_fold_adaptors(&self.receiver, &borrowed, 0)
            .and_then(|(base, _)| bounded_domain_from_expr(base, ctx.scope))
            .is_some();
        if resolves_literal {
            return None;
        }
        Some(Effect::OpaqueRuntime {
            boundary: boundary.to_string(),
            accessor: false,
        })
    }
}

impl Sugar for ClosureAdaptorSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let boundary = token_key(&self.expr);
        // The composite makes NO verdict of its own: it sequences the three leaves in the
        // wire-format precedence (accessor, then body, then receiver) and propagates the
        // first leaf that `Hit`s. If all three Dig, this is the honest-unclassified case --
        // the STRUCTURAL backstop the fall-through consumer discards as the old `None`.
        if let Some(effect) = self
            .accessor_effect(&boundary)
            .or_else(|| self.body_effect(&boundary))
            .or_else(|| self.receiver_effect(&boundary, ctx))
        {
            return Outcome::Hit(effect);
        }
        Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })
    }
}

/// Build (`new` + compose, NO degeneracy opinion) a `ClosureAdaptorSugar` from a statement
/// expr that bears an asserting closure-method call. Recognizes the construct: the FIRST
/// closure-bearing method call along the chain (its method, closure, receiver), gated only
/// on the closure body carrying an assertion (else this is not a fold-closure-bucket
/// statement -- nothing to classify). Returns `None` (declines to RECOGNIZE) for a non-
/// closure-method statement or a closure with no assert. It makes NO verdict -- the
/// order-loss decision is `ClosureAdaptorSugar::desugar`'s (and its leaves') alone.
pub(crate) fn decompose_closure_adaptor(
    expr: &Expr,
    let_inits: &BTreeMap<String, &Expr>,
) -> Option<ClosureAdaptorSugar> {
    // Find the closure-bearing method call (anywhere along the chain), its closure, and
    // its receiver (for the literal-domain resolution).
    struct Find {
        method: Option<String>,
        closure: Option<syn::ExprClosure>,
        receiver: Option<Expr>,
    }
    impl<'ast> Visit<'ast> for Find {
        fn visit_expr_method_call(&mut self, m: &'ast syn::ExprMethodCall) {
            if self.closure.is_none() {
                if let Some(Expr::Closure(c)) = m.args.iter().find(|a| matches!(a, Expr::Closure(_)))
                {
                    self.method = Some(m.method.to_string());
                    self.closure = Some(c.clone());
                    self.receiver = Some((*m.receiver).clone());
                }
            }
            syn::visit::visit_expr_method_call(self, m);
        }
    }
    let mut f = Find {
        method: None,
        closure: None,
        receiver: None,
    };
    Visit::visit_expr(&mut f, expr);
    let (method, closure, receiver) = (f.method?, f.closure?, f.receiver?);
    // The closure body must actually carry an assertion (else this is not a
    // fold-closure-bucket statement -- nothing to classify; leave it alone).
    if count_asserts_in_expr(&closure.body) == 0 {
        return None;
    }
    Some(ClosureAdaptorSugar {
        expr: expr.clone(),
        method,
        closure,
        receiver,
        let_inits: let_inits
            .iter()
            .map(|(k, v)| (k.clone(), (*v).clone()))
            .collect(),
    })
}
