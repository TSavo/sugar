// SPDX-License-Identifier: Apache-2.0
//
// `OptionUnwrapSugar`: `.unwrap()` / `.expect(..)` over a grounded std
// `Option`/`Result` constructor is value sugar. The child is still built by the
// factory; this node only peels known monadic constructors.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::nonzero::is_nonzero_new_call;
use crate::sugar::term_dispatch::{MonadicFloorAccept, MonadicFloorVisitor};
use crate::{strip_refs_groups, Desugared, Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("option_unwrap", SugarRole::Term, recognize);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let method = frag.call_method_key()?;
    if !matches!(method.as_str(), "unwrap" | "expect") {
        return None;
    }
    let arg_count = frag.call_arg_count();
    if method == "unwrap" && arg_count != 0 {
        return None;
    }
    if method == "expect" && arg_count != 1 {
        return None;
    }
    let receiver_frag = frag.call_receiver()?;
    if !receiver_resolves_monadic_source_frag(&receiver_frag, fcx, 0) {
        return None;
    }
    Some(Box::new(OptionUnwrapSugar {
        method,
        receiver: SugarBody::term_frag(&receiver_frag, fcx),
        site_key: frag.token_str(),
    }))
}

/// Fragment-accepting wrapper for `receiver_resolves_monadic_source`.
/// Keeps `as_expr()` out of the `recognize` body (ratchet-clean).
fn receiver_resolves_monadic_source_frag(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
    depth: usize,
) -> bool {
    let Some(expr) = frag.as_expr() else {
        return false;
    };
    receiver_resolves_monadic_source(expr, fcx, depth)
}

struct OptionUnwrapSugar {
    method: String,
    receiver: SugarBody<TermFloor>,
    site_key: String,
}

impl Sugar for OptionUnwrapSugar {
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.reduce(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(term) => term,
                None => unreachable!(
                    "typed monadic `{}` receiver reduced to a non-term floor",
                    self.method
                ),
            },
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        receiver.accept_monadic_floor(UnwrapVisitor {
            method: &self.method,
            site_key: &self.site_key,
        })
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

struct UnwrapVisitor<'a> {
    method: &'a str,
    site_key: &'a str,
}

impl MonadicFloorVisitor for UnwrapVisitor<'_> {
    type Output = Outcome;

    fn visit_some(self, inner: &Rc<Term>) -> Self::Output {
        self.complete(inner)
    }

    fn visit_none(self) -> Self::Output {
        self.literal_panic("opt:none")
    }

    fn visit_ok(self, inner: &Rc<Term>) -> Self::Output {
        self.complete(inner)
    }

    fn visit_err(self, _inner: &Rc<Term>) -> Self::Output {
        self.literal_panic("res:err")
    }

    fn visit_non_monadic(self, _term: &Rc<Term>) -> Self::Output {
        panic!(
            "constructed monadic `{}` receiver did not reduce to Option/Result constructor",
            self.method
        )
    }
}

impl UnwrapVisitor<'_> {
    fn complete(self, inner: &Rc<Term>) -> Outcome {
        debug!(
            target: "sugar_lift_rust_tests::sugar::option_unwrap",
            method = self.method,
            "resolved monadic unwrap/expect stdlib axiom to inner term floor"
        );
        Outcome::Complete(Desugared::Term(Rc::clone(inner)))
    }

    fn literal_panic(self, kind: &str) -> Outcome {
        Outcome::Incomplete(Effect::LiteralPanic {
            boundary: self.site_key.to_string(),
            reason: format!(
                "monadic `{}` on literal `{kind}` panics; refused",
                self.method
            ),
        })
    }
}

pub(crate) fn receiver_resolves_monadic_source(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    depth: usize,
) -> bool {
    if depth > 8 {
        return false;
    }
    if is_known_monadic_source(expr)
        || try_from_receiver_folds_scoped(expr, fcx)
        || crate::sugar::array_try_from::folds_to_result(expr, fcx)
        || crate::sugar::iter_terminal::recognizes_monadic_terminal(expr, fcx)
    {
        return true;
    }
    match strip_refs_groups(expr) {
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(|ident| ident.to_string()) else {
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
            receiver_resolves_monadic_source(init, &child_fcx, depth + 1)
        }
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "map"
                    | "and_then"
                    | "filter"
                    | "ok_or"
                    | "map_err"
                    | "unwrap_or_else"
                    | "unwrap_or"
                    | "unwrap_or_default"
            ) =>
        {
            receiver_resolves_monadic_source(&call.receiver, fcx, depth + 1)
        }
        Expr::Paren(paren) => receiver_resolves_monadic_source(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => receiver_resolves_monadic_source(&group.expr, fcx, depth + 1),
        _ => false,
    }
}

/// Scope-aware extension of the `try_from` monadic check: a `try_from` receiver
/// whose argument is a let-bound local / const path that RESOLVES to an integer
/// (`let m = 255u16; try_from(m).unwrap()`, `try_from(<u8>::MAX).unwrap()`). The
/// syntactic `is_known_monadic_source` only sees inline literals; this catches the
/// resolved-arg shapes via the scope (sound: see `try_from::scalar_int_value`).
fn try_from_receiver_folds_scoped(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return false;
    };
    crate::sugar::try_from::folds_to_result(call, Some(fcx))
}

pub(crate) fn is_known_monadic_source(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Path(path) => path
            .path
            .segments
            .last()
            .is_some_and(|seg| seg.ident == "None"),
        Expr::Call(call) => {
            if is_nonzero_new_call(expr) {
                return true;
            }
            // An integer `TryFrom::try_from(literal)` grounds to a `res:ok`/
            // `res:err` (see `try_from`), so `.unwrap()`/`.expect(..)` can peel it.
            // Inline-literal check here (this fn is the no-scope syntactic oracle);
            // the let-bound / const-path arg is caught by `try_from_receiver_folds_scoped`.
            if crate::sugar::try_from::folds_to_result(call, None) {
                return true;
            }
            let Expr::Path(path) = strip_refs_groups(&call.func) else {
                return false;
            };
            path.path
                .segments
                .last()
                .is_some_and(|seg| matches!(seg.ident.to_string().as_str(), "Some" | "Ok" | "Err"))
        }
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "checked_isqrt" | "checked_mul" | "checked_add" | "checked_sub" | "checked_div"
            ) =>
        {
            true
        }
        Expr::Paren(paren) => is_known_monadic_source(&paren.expr),
        Expr::Group(group) => is_known_monadic_source(&group.expr),
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{LiftOptions, TemporalPlan, TemporalScope};
    use std::collections::BTreeMap;
    use syn::Expr;

    /// from_src: source -> SourceFragment -> call_method_key / call_arg_count /
    /// call_receiver accessor gate -> recognize -> Sugar node returned.
    /// No parse_quote! / StubTerm / run().
    #[test]
    fn from_src_option_unwrap_recognize() {
        let expr: Expr = syn::parse_str("Some(42).unwrap()").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        // accessor gates -- these are what the migrated recognize reads
        assert_eq!(frag.call_method_key().as_deref(), Some("unwrap"), "method key");
        assert_eq!(frag.call_arg_count(), 0, "unwrap: 0 args");
        assert!(frag.call_receiver().is_some(), "receiver present");

        let scope = TemporalScope::new("option-unwrap-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        // grounded monadic source -> recognized
        assert!(recognize(&frag, &fcx).is_some(), "Some(42).unwrap() recognized");

        // unresolvable path receiver -> NOT recognized
        let expr_no: Expr = syn::parse_str("runtime_value.unwrap()").expect("parse");
        let frag_no = SourceFragment::expr(&expr_no, "<src>");
        assert!(recognize(&frag_no, &fcx).is_none(), "runtime receiver not recognized");

        // non-method-call -> NOT recognized
        let expr_other: Expr = syn::parse_str("x + 1").expect("parse");
        let frag_other = SourceFragment::expr(&expr_other, "<src>");
        assert!(recognize(&frag_other, &fcx).is_none(), "binop not recognized");
    }

    #[test]
    fn from_src_option_expect_recognize() {
        let expr: Expr = syn::parse_str(r#"Some(42).expect("must be Some")"#).expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert_eq!(frag.call_method_key().as_deref(), Some("expect"), "method key");
        assert_eq!(frag.call_arg_count(), 1, "expect: 1 arg");
        assert!(frag.call_receiver().is_some(), "receiver present");

        let scope = TemporalScope::new("option-unwrap-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(recognize(&frag, &fcx).is_some(), "Some(42).expect(..) recognized");

        // wrong arg count for expect -> NOT recognized
        let expr_bad: Expr = syn::parse_str("Some(42).expect()").expect("parse");
        let frag_bad = SourceFragment::expr(&expr_bad, "<src>");
        assert!(recognize(&frag_bad, &fcx).is_none(), "expect() with 0 args not recognized");
    }
}
