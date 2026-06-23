// SPDX-License-Identifier: Apache-2.0
//
// `OptionPredicateSugar`: `.is_some()` / `.is_none()` over a grounded std Option
// constructor. This is value sugar, separate from generic method calls: once the
// receiver body bottoms out to `opt:some(_)` or `opt:none`, the predicate is a literal bool.

use sugar_ir_symbolic::Term;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{
    compat_reduction, FactoryGap, FactoryReduction, SugarBody, SugarBuildCtx,
};
use crate::sugar::monadic::{is_grounded_literal_term, OPT_NONE, OPT_SOME};
use crate::sugar::nonzero::is_nonzero_new_call;
use crate::{bool_const, strip_refs_groups, Desugared, Effect, Outcome, Sugar, SugarCtx};

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
    if !receiver_resolves_option_source(&call.receiver, fcx, 0) {
        return None;
    }
    let receiver = SugarBody::term(&call.receiver, fcx);
    Some(OptionPredicateSugar::new(method, receiver))
}

struct OptionPredicateSugar {
    method: String,
    receiver: SugarBody,
}

impl OptionPredicateSugar {
    fn new(method: String, receiver: SugarBody) -> Box<dyn Sugar> {
        Box::new(Self { method, receiver })
    }
}

impl Sugar for OptionPredicateSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        let receiver = match self.receiver.reduce(ctx)? {
            Outcome::Complete(d) => match d.into_term() {
                Some(term) => term,
                None => {
                    return Err(FactoryGap::new(format!(
                        "Option predicate `{}` receiver reduced to non-term",
                        self.method
                    )))
                }
            },
            Outcome::Incomplete(e) => return Ok(Outcome::Incomplete(e)),
        };
        let Some(presence) = option_presence(&receiver) else {
            return Err(FactoryGap::new(format!(
                "Option predicate `{}` receiver did not reduce to Option constructor",
                self.method
            )));
        };
        let is_some = match presence {
            Ok(is_some) => is_some,
            Err(kind) => {
                return Ok(Outcome::Incomplete(Effect::Unsupported {
                    reason: format!(
                        "runtime Option/Result payload, not literal (`{}` over `{kind}`)",
                        self.method
                    ),
                }))
            }
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
        Ok(Outcome::Complete(Desugared::Term(bool_const(value))))
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

fn option_presence(term: &Term) -> Option<Result<bool, &'static str>> {
    match term {
        Term::Ctor { name, args } if name == OPT_SOME && args.len() == 1 => {
            if is_grounded_literal_term(args[0].as_ref()) {
                Some(Ok(true))
            } else {
                Some(Err(OPT_SOME))
            }
        }
        Term::Ctor { name, args } if name == OPT_NONE && args.is_empty() => Some(Ok(false)),
        _ => None,
    }
}

fn receiver_resolves_option_source(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    if is_known_option_source(expr) {
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
            receiver_resolves_option_source(init, &child_fcx, depth + 1)
        }
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "map" | "and_then" | "filter"
            ) =>
        {
            receiver_resolves_option_source(&call.receiver, fcx, depth + 1)
        }
        Expr::Paren(paren) => receiver_resolves_option_source(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => receiver_resolves_option_source(&group.expr, fcx, depth + 1),
        _ => false,
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
