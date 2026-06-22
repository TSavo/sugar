// SPDX-License-Identifier: Apache-2.0
//
// `OptionPredicateSugar`: `.is_some()` / `.is_none()` over a grounded std Option
// constructor. This is value sugar, separate from generic method calls: once the
// receiver bottoms out to `opt:some(_)` or `opt:none`, the predicate is a literal bool.

use std::collections::BTreeMap;

use sugar_ir_symbolic::Term;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
use crate::sugar::monadic::{OPT_NONE, OPT_SOME};
use crate::sugar::nonzero::is_nonzero_new_call;
use crate::{bool_const, strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("option_predicate", SugarRole::Term, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let method = call.method.to_string();
    if !matches!(method.as_str(), "is_some" | "is_none") || !call.args.is_empty() {
        return None;
    }
    if !is_known_option_source(&call.receiver) {
        return None;
    }
    Some(Box::new(OptionPredicateSugar {
        method,
        receiver: (*call.receiver).clone(),
        let_inits: capture_let_inits(fcx),
    }))
}

struct OptionPredicateSugar {
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

impl Sugar for OptionPredicateSugar {
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
        let Some(is_some) = option_presence(&receiver) else {
            return Outcome::from_opt(None);
        };
        let value = if self.method == "is_some" {
            is_some
        } else {
            !is_some
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::option_predicate",
            method = self.method.as_str(),
            value,
            "resolved Option presence predicate stdlib axiom"
        );
        Outcome::Dug(Desugared::Term(bool_const(value)))
    }
}

fn option_presence(term: &Term) -> Option<bool> {
    match term {
        Term::Ctor { name, .. } if name == OPT_SOME => Some(true),
        Term::Ctor { name, .. } if name == OPT_NONE => Some(false),
        _ => None,
    }
}

fn is_known_option_source(expr: &Expr) -> bool {
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
            let Expr::Path(path) = strip_refs_groups(&call.func) else {
                return false;
            };
            path.path
                .segments
                .last()
                .is_some_and(|seg| seg.ident == "Some")
        }
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "checked_isqrt" | "checked_add" | "checked_sub" | "checked_mul" | "checked_div"
            ) =>
        {
            true
        }
        Expr::Paren(paren) => is_known_option_source(&paren.expr),
        Expr::Group(group) => is_known_option_source(&group.expr),
        _ => false,
    }
}
