// SPDX-License-Identifier: Apache-2.0
//
// Shared decomposition and detectors for closure-adaptor verdict sugars. This module owns
// no catalog claim: each semantic leaf lives in its own `closure_*` Sugar file.

use std::collections::BTreeMap;

use syn::{visit::Visit, Expr};

use crate::{
    bounded_domain_from_expr, closure_body_advances_iterator, closure_body_is_side_effecting,
    count_asserts_in_expr, peel_fold_adaptors, TemporalScope, PURE_CLOSURE_ADAPTORS,
};

/// A closure-bearing method statement and the data every closure-adaptor verdict Sugar
/// needs to decide whether it owns the site.
#[derive(Clone)]
pub(crate) struct ClosureAdaptorSite {
    /// The full statement expr -- the `boundary` token-key is `token_key(&expr)`.
    expr: Expr,
    /// The closure-bearing method name (`for_each` / `with` / `fold` / ...). The ACCESSOR
    /// leaf: a non-pure adaptor is itself the opaque/effectful boundary.
    method: String,
    /// The closure. The BODY leaf: its body is scanned for the side-effecting / iter-advance
    /// degeneracy.
    closure: syn::ExprClosure,
    /// The receiver of the closure-bearing call. The RECEIVER leaf: it completes on a finite
    /// literal domain and `Incomplete`s `OpaqueRuntime` on runtime data.
    receiver: Expr,
    /// Owned snapshot of the in-scope `let` initializers (name -> init expr), captured at
    /// build time. Rebuilt into the borrowed `&Expr` map at desugar to drive
    /// `peel_fold_adaptors` -- the node owns its data (mirrors `FoldSugar::literal_arrays`).
    let_inits: BTreeMap<String, Expr>,
}

impl ClosureAdaptorSite {
    pub(crate) fn expr(&self) -> &Expr {
        &self.expr
    }

    /// ACCESSOR detector: `.with` is the thread-local accessor boundary.
    pub(crate) fn has_tls_accessor(&self) -> bool {
        !PURE_CLOSURE_ADAPTORS.contains(&self.method.as_str()) && self.method == "with"
    }

    /// ACCESSOR detector: any non-pure closure adaptor other than `.with` is opaque.
    pub(crate) fn has_opaque_accessor(&self) -> bool {
        !PURE_CLOSURE_ADAPTORS.contains(&self.method.as_str()) && self.method != "with"
    }

    /// BODY detector: a closure body that advances a captured iterator loses order.
    pub(crate) fn has_iter_advance_body(&self) -> bool {
        closure_body_is_side_effecting(&self.closure.body)
            && closure_body_advances_iterator(&self.closure.body)
    }

    /// BODY detector: any side-effecting closure body is mutating. Iterator advance is a
    /// better body owner and declares it comes before this verdict when both match.
    pub(crate) fn has_mutating_body(&self) -> bool {
        closure_body_is_side_effecting(&self.closure.body)
    }

    /// RECEIVER detector: a receiver that does not resolve to a finite literal domain is
    /// runtime data.
    pub(crate) fn has_runtime_receiver(&self, scope: &TemporalScope) -> bool {
        !self.receiver_resolves_literal(scope)
    }

    fn receiver_resolves_literal(&self, scope: &TemporalScope) -> bool {
        let borrowed: BTreeMap<String, &Expr> =
            self.let_inits.iter().map(|(k, v)| (k.clone(), v)).collect();
        peel_fold_adaptors(&self.receiver, &borrowed, 0)
            .and_then(|(base, _)| bounded_domain_from_expr(base, scope))
            .is_some()
    }
}

/// Build (`new` + compose, NO degeneracy opinion) a closure-adaptor site from a statement
/// expr that bears an asserting closure-method call. Recognizes the construct: the FIRST
/// closure-bearing method call along the chain (its method, closure, receiver), gated only
/// on the closure body carrying an assertion (else this is not a fold-closure-bucket
/// statement -- nothing to classify). Returns `None` for a non-closure-method statement or
/// a closure with no assert. It makes NO verdict; each closure verdict Sugar owns that.
pub(crate) fn decompose_closure_adaptor(
    expr: &Expr,
    let_inits: &BTreeMap<String, &Expr>,
) -> Option<ClosureAdaptorSite> {
    let Expr::MethodCall(_) = expr else {
        return None;
    };
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
                if let Some(Expr::Closure(c)) =
                    m.args.iter().find(|a| matches!(a, Expr::Closure(_)))
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
    Some(ClosureAdaptorSite {
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
