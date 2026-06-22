// SPDX-License-Identifier: Apache-2.0
//
// `OptionUnwrapSugar`: `.unwrap()` / `.expect(..)` over a grounded std
// `Option`/`Result` constructor is value sugar. The child is still built by the
// factory; this node only peels known monadic constructors.

use std::{collections::BTreeMap, rc::Rc};

use sugar_ir_symbolic::Term;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
use crate::sugar::monadic::{OPT_NONE, OPT_SOME, RES_ERR, RES_OK};
use crate::sugar::nonzero::is_nonzero_new_call;
use crate::{strip_refs_groups, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("option_unwrap", SugarRole::Term, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let method = call.method.to_string();
    if !matches!(method.as_str(), "unwrap" | "expect") {
        return None;
    }
    if method == "unwrap" && !call.args.is_empty() {
        return None;
    }
    if method == "expect" && call.args.len() != 1 {
        return None;
    }
    if !receiver_resolves_monadic_source(&call.receiver, fcx, 0) {
        return None;
    }
    Some(Box::new(OptionUnwrapSugar {
        method,
        receiver: (*call.receiver).clone(),
        let_inits: capture_let_inits(fcx),
    }))
}

struct OptionUnwrapSugar {
    method: String,
    receiver: Expr,
    let_inits: BTreeMap<String, Expr>,
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

impl Sugar for OptionUnwrapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let stable = stable_let_bindings(ctx.scope);
        let let_inits: BTreeMap<String, &Expr> = stable
            .iter()
            .map(|(name, init)| (name.clone(), init))
            .chain(
                self.let_inits
                    .iter()
                    .map(|(name, init)| (name.clone(), init)),
            )
            .collect();
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let receiver = match build_term(&self.receiver, &fcx).desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        match unwrap_monadic(&receiver) {
            Some(Ok(inner)) => {
                debug!(
                    target: "sugar_lift_rust_tests::sugar::option_unwrap",
                    method = self.method.as_str(),
                    "resolved monadic unwrap/expect stdlib axiom to inner literal"
                );
                Outcome::Dug(Desugared::Term(inner))
            }
            Some(Err(kind)) => Outcome::Hit(Effect::Unsupported {
                reason: format!(
                    "monadic `{}` on literal `{kind}` panics; refused",
                    self.method
                ),
            }),
            None => Outcome::from_opt(None),
        }
    }
}

fn unwrap_monadic(term: &Rc<Term>) -> Option<Result<Rc<Term>, &'static str>> {
    match term.as_ref() {
        Term::Ctor { name, args } if name == OPT_SOME && args.len() == 1 => {
            Some(Ok(Rc::clone(&args[0])))
        }
        Term::Ctor { name, args } if name == RES_OK && args.len() == 1 => {
            Some(Ok(Rc::clone(&args[0])))
        }
        Term::Ctor { name, .. } if name == OPT_NONE => Some(Err(OPT_NONE)),
        Term::Ctor { name, .. } if name == RES_ERR => Some(Err(RES_ERR)),
        _ => None,
    }
}

fn receiver_resolves_monadic_source(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    if is_known_monadic_source(expr)
        || try_from_receiver_folds_scoped(expr, fcx)
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
            let Some(init) = fcx.scope().stable_let_binding_for_term(&name) else {
                return false;
            };
            let child_fcx = fcx.with_bound_path(&name);
            receiver_resolves_monadic_source(init, &child_fcx, depth + 1)
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
