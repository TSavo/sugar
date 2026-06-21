// SPDX-License-Identifier: Apache-2.0
//
// `OptionUnwrapSugar`: `.unwrap()` / `.expect(..)` over a grounded std
// `Option`/`Result` constructor is value sugar. The child is still built by the
// factory; this node only peels known monadic constructors.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::monadic::{OPT_NONE, OPT_SOME, RES_ERR, RES_OK};
use crate::sugar::nonzero::is_nonzero_new_call;
use crate::{strip_refs_groups, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "option_unwrap",
    SugarRole::Term,
    SugarPriority::Primary,
    recognize,
);

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
    if !is_known_monadic_source(&call.receiver) {
        return None;
    }
    Some(Box::new(OptionUnwrapSugar {
        method,
        receiver: build_term(&call.receiver, fcx),
    }))
}

struct OptionUnwrapSugar {
    method: String,
    receiver: Box<dyn Sugar>,
}

impl Sugar for OptionUnwrapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.desugar(ctx) {
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
            if crate::sugar::try_from::folds_to_result(call) {
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
