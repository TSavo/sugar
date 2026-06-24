// SPDX-License-Identifier: Apache-2.0
//
// `OptionPredicateSugar`: `.is_some()` / `.is_none()` over a grounded std Option
// constructor. This is value sugar, separate from generic method calls: once the
// receiver body bottoms out to `opt:some(_)` or `opt:none`, the predicate is a literal bool.
// The payload does not participate: `Some(runtime()).is_some()` is still the literal
// predicate `true`, with the runtime payload safely ignored by the monadic visitor.

use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::nonzero::is_nonzero_new_call;
use crate::sugar::term_dispatch::{MonadicFloorAccept, MonadicFloorVisitor};
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
    if !receiver_resolves_option_source(&call.receiver, fcx, 0) {
        return None;
    }
    let receiver = SugarBody::term(&call.receiver, fcx);
    Some(OptionPredicateSugar::new(method, receiver))
}

struct OptionPredicateSugar {
    method: String,
    receiver: SugarBody<TermFloor>,
}

impl OptionPredicateSugar {
    fn new(method: String, receiver: SugarBody<TermFloor>) -> Box<dyn Sugar> {
        Box::new(Self { method, receiver })
    }
}

impl Sugar for OptionPredicateSugar {
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.reduce(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(term) => term,
                None => panic!(
                    "Option predicate `{}` receiver reduced to non-term",
                    self.method
                ),
            },
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        receiver.accept_monadic_floor(OptionPresenceVisitor {
            method: &self.method,
        })
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

struct OptionPresenceVisitor<'a> {
    method: &'a str,
}

impl MonadicFloorVisitor for OptionPresenceVisitor<'_> {
    type Output = Outcome;

    fn visit_some(self, _inner: &std::rc::Rc<sugar_ir_symbolic::Term>) -> Self::Output {
        self.complete(true)
    }

    fn visit_none(self) -> Self::Output {
        self.complete(false)
    }

    fn visit_ok(self, _inner: &std::rc::Rc<sugar_ir_symbolic::Term>) -> Self::Output {
        panic!(
            "Option predicate `{}` received a Result::Ok floor",
            self.method
        )
    }

    fn visit_err(self, _inner: &std::rc::Rc<sugar_ir_symbolic::Term>) -> Self::Output {
        panic!(
            "Option predicate `{}` received a Result::Err floor",
            self.method
        )
    }

    fn visit_non_monadic(self, _term: &std::rc::Rc<sugar_ir_symbolic::Term>) -> Self::Output {
        panic!(
            "Option predicate `{}` receiver did not reduce to Option constructor",
            self.method
        )
    }
}

impl OptionPresenceVisitor<'_> {
    fn complete(self, is_some: bool) -> Outcome {
        let value = if self.method == "is_some" {
            is_some
        } else {
            !is_some
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::option_predicate",
            method = self.method,
            value,
            "resolved Option presence predicate stdlib axiom"
        );
        Outcome::Complete(Desugared::Term(bool_const(value)))
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
