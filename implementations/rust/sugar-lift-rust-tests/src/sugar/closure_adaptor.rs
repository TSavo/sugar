// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Shared decomposition and detectors for closure-adaptor verdict sugars. This module owns
// no catalog claim: each semantic leaf lives in its own `closure_*` Sugar file.

use std::collections::BTreeMap;

use syn::{visit::Visit, Expr};

use crate::{
    bounded_domain_from_expr, closure_body_advances_iterator, closure_body_is_side_effecting,
    count_asserts_in_expr, peel_fold_adaptors, TemporalScope, PURE_CLOSURE_ADAPTORS,
};

/// A closure-bearing method statement and the pre-computed data every closure-adaptor
/// verdict Sugar needs to decide whether it owns the site. All raw `syn` fields have been
/// replaced by derived (host-native) values computed at recognize time; the Sugar struct
/// holds NO raw syn after this rework.
#[derive(Clone)]
pub(crate) struct ClosureAdaptorSite {
    /// The closure-bearing method name (`for_each` / `with` / `fold` / ...). The ACCESSOR
    /// leaf: a non-pure adaptor is itself the opaque/effectful boundary.
    method: String,
    /// Pre-computed: is the closure body side-effecting?
    side_effecting: bool,
    /// Pre-computed: does the side-effecting closure body advance an iterator?
    /// Only meaningful (and set) when `side_effecting` is `true`.
    advances_iterator: bool,
    /// Pre-computed: does the receiver resolve to a finite literal domain?
    /// Computed at recognize time using the scope present at that point; the
    /// scope does not change between recognize and desugar for a single statement.
    resolves_literal: bool,
}

impl ClosureAdaptorSite {
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
        self.side_effecting && self.advances_iterator
    }

    /// BODY detector: any side-effecting closure body is mutating. Iterator advance is a
    /// better body owner and declares it comes before this verdict when both match.
    pub(crate) fn has_mutating_body(&self) -> bool {
        self.side_effecting
    }

    /// RECEIVER detector: a receiver that does not resolve to a finite literal domain is
    /// runtime data. The `_scope` parameter is retained for API compatibility with desugar
    /// call sites that pass `ctx.scope`; the actual computation is pre-done at recognize time.
    pub(crate) fn has_runtime_receiver(&self, _scope: &TemporalScope) -> bool {
        !self.resolves_literal
    }
}

/// Build (`new` + compose, NO degeneracy opinion) a closure-adaptor site from a statement
/// expr that bears an asserting closure-method call. Recognizes the construct: the FIRST
/// closure-bearing method call along the chain (its method, closure, receiver), gated only
/// on the closure body carrying an assertion (else this is not a fold-closure-bucket
/// statement -- nothing to classify). Returns `None` for a non-closure-method statement or
/// a closure with no assert. It makes NO verdict; each closure verdict Sugar owns that.
///
/// All raw `syn` values are distilled into host-native data here; the returned
/// `ClosureAdaptorSite` holds NO raw syn fields.
pub(crate) fn decompose_closure_adaptor(
    expr: &Expr,
    let_inits: &BTreeMap<String, &Expr>,
    scope: &TemporalScope,
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
    // Pre-compute all derived values so the Sugar struct holds no raw syn.
    let side_effecting = closure_body_is_side_effecting(&closure.body);
    let advances_iterator = side_effecting && closure_body_advances_iterator(&closure.body);
    let resolves_literal = peel_fold_adaptors(&receiver, let_inits, 0)
        .and_then(|(base, _)| bounded_domain_from_expr(base, scope))
        .is_some();
    Some(ClosureAdaptorSite {
        method,
        side_effecting,
        advances_iterator,
        resolves_literal,
    })
}

/// Fragment-level wrapper for `decompose_closure_adaptor`. Takes a `&SourceFragment`
/// instead of a raw `&Expr`; the `as_expr()` call lives HERE (ratchet-excluded
/// because this is a decomposer helper, not a recognizer body). Returns `None`
/// for non-`Expr` fragments.
pub(crate) fn decompose_closure_adaptor_frag(
    frag: &crate::sugar::source_fragment::SourceFragment,
    let_inits: &BTreeMap<String, &Expr>,
    scope: &TemporalScope,
) -> Option<ClosureAdaptorSite> {
    let expr = frag.as_expr()?;
    decompose_closure_adaptor(expr, let_inits, scope)
}
