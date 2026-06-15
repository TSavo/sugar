// SPDX-License-Identifier: Apache-2.0
//
// ForAllSugar -- the for-loop bounded universal.
//
// Moved verbatim from lib.rs in the file-split refactor (one file per Sugar
// class). Behaviour-preserving: the desugar logic is byte-identical to the
// monolith; only its physical location changed.

use syn::{Pat, Stmt};

use crate::*;

/// `ForEachSugar` / `ForAllSugar`: a bounded universal over a finite-construction
/// domain. `for v in <lit> { body }` and `<lit>.iter().for_each(|v| body)` assert
/// the SAME universal (a finite conjunction over a literal array; a guarded forall
/// over a closed range) -- `for_each` is `fold` with the unit accumulator, so the
/// construction is one piece of code (`lift_bounded_forall`, the shared verified
/// core). `desugar` reduces to that conjunction or bails (mutation / non-point-wise
/// body / count mismatch). `kind` only flavors the warrant name (`for_each`/`loop`).
pub(crate) struct ForAllSugar {
    pub(crate) var: String,
    pub(crate) domain: BoundedDomain,
    pub(crate) body_stmts: Vec<Stmt>,
    /// The warrant-name flavor: `"for_each"` (adaptor) or `"loop"` (for-loop).
    pub(crate) kind: &'static str,
}

impl Sugar for ForAllSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Option<Desugared> {
        // `lift_bounded_forall` is the shared verified core: it const-checks the
        // domain (range -> guarded forall; array -> finite conjunction), lifts the
        // body all-or-nothing through the normal collector, and gates purity. We
        // re-discriminate the domain here (it is consumed by value) by re-reading;
        // pass the already-resolved `BoundedDomain`.
        let (quantified, n_body) = lift_bounded_forall(
            &self.var,
            self.domain.clone(),
            &self.body_stmts,
            ctx.scope,
            ctx.options,
            ctx.reducer,
            *ctx.float_widths.borrow_mut(),
            ctx.macro_depth,
        )?;
        let warrant = Warrant {
            name: Some(format!(
                "{}::{}::{}",
                ctx.scope.local_scope(),
                self.kind,
                self.var
            )),
        };
        Some(Desugared::Constraints {
            atom: quantified,
            n: n_body,
            warrant,
        })
    }
}

/// Build a `ForAllSugar` from a `for <var> in <domain> { body }` loop: the domain
/// must be a finite construction (closed range / literal array). None (bail)
/// otherwise. This is the front half of `try_lift_for_loop_forall`.
pub(crate) fn decompose_for_loop(f: &syn::ExprForLoop, scope: &TemporalScope) -> Option<ForAllSugar> {
    let var = match &*f.pat {
        Pat::Ident(p) if p.subpat.is_none() => p.ident.to_string(),
        _ => return None,
    };
    let domain = bounded_domain_from_expr(&f.expr, scope)?;
    Some(ForAllSugar {
        var,
        domain,
        body_stmts: f.body.stmts.clone(),
        kind: "loop",
    })
}
