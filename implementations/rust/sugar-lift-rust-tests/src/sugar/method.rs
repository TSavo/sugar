// SPDX-License-Identifier: Apache-2.0
//
// `MethodSugar` + the TERM recognizer for `Expr::MethodCall`. The constructive
// method-call term node digs the receiver child FIRST, applies the per-occurrence
// consuming-iterator `@adv{n}` re-tag (a runtime read of `ctx.scope`), then digs the
// arg children in source order, and emits `method:<m>` over `[receiver, args..]`.
//
// The recognizer runs the source-of-truth preamble in order: a CLOSED
// `try_fold`/`try_rfold` grounds to a literal and re-builds THAT; a closure-bearing
// adaptor in term position refuses with collection provenance; otherwise the EUF
// `method:` ctor node. This is the TERM-position node — DISTINCT from the COMPOSITE
// `fold`/`for_each`/closure-
// adaptor/match-scrutinee dispatch the COMPOSITE catalog routes `Expr::MethodCall` to.
// Byte-identical to the old fat factory's `Expr::MethodCall` term arm.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{make_var, Term};
use syn::Expr;

use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::term_leaf::reasoned_hit;
use crate::try_fold_eval;
use crate::{
    angle_args_key, closure_adaptor_refusal, is_consuming_iterator_method,
    receiver_is_versioned_iterator, Desugared, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::fallback_term("method", recognize);

/// TERM recognizer for `Expr::MethodCall`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let scope = fcx.scope();
    // CLOSED try_fold / try_rfold: ground to a literal and re-build THAT.
    if matches!(call.method.to_string().as_str(), "try_fold" | "try_rfold") {
        if let Some(grounded) = try_fold_eval::eval_try_fold_operand(expr, scope) {
            return Some(Box::new(MethodSugar::Grounded {
                expr: grounded,
                let_inits: capture_let_inits(fcx),
            }));
        }
    }
    // A closure-bearing adaptor in term position refuses with collection provenance.
    if let Some(reason) = closure_adaptor_refusal(expr, scope) {
        return Some(reasoned_hit(reason));
    }
    // The constructive `method:` ctor. The RECEIVER is dug first; a per-occurrence
    // consuming-iterator advance re-tags the receiver var (`@adv{n}`).
    Some(Box::new(MethodSugar::Constructive {
        method: method_key(call),
        receiver: call.receiver.as_ref().clone(),
        is_consuming: is_consuming_iterator_method(&call.method.to_string()),
        args: call.args.iter().cloned().collect(),
        let_inits: capture_let_inits(fcx),
    }))
}

/// The `method:<m>` ctor key: `method.turbofish` appends the angle-args key.
pub(crate) fn method_key(call: &syn::ExprMethodCall) -> String {
    match &call.turbofish {
        Some(args) => format!("{}{}", call.method, angle_args_key(args)),
        None => call.method.to_string(),
    }
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

fn merge_let_inits<'a>(
    stable: &'a BTreeMap<String, Expr>,
    captured: &'a BTreeMap<String, Expr>,
) -> BTreeMap<String, &'a Expr> {
    stable
        .iter()
        .map(|(name, init)| (name.clone(), init))
        .chain(captured.iter().map(|(name, init)| (name.clone(), init)))
        .collect()
}

/// Method-call term nodes capture only raw child expressions in recognition. Child
/// decomposition happens here, at desugar time, when the binding/sort context is live.
enum MethodSugar {
    Grounded {
        expr: Expr,
        let_inits: BTreeMap<String, Expr>,
    },
    Constructive {
        method: String,
        receiver: Expr,
        is_consuming: bool,
        args: Vec<Expr>,
        let_inits: BTreeMap<String, Expr>,
    },
}

impl Sugar for MethodSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self {
            MethodSugar::Grounded { expr, let_inits } => {
                let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
                let let_inits = merge_let_inits(&stable, let_inits);
                let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
                build_term(expr, &fcx).desugar(ctx)
            }
            MethodSugar::Constructive {
                method,
                receiver,
                is_consuming,
                args,
                let_inits,
            } => {
                let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
                let let_inits = merge_let_inits(&stable, let_inits);
                let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
                let mut receiver = match build_term(receiver, &fcx).desugar(ctx) {
                    Outcome::Dug(d) => match d.into_term() {
                        Some(t) => t,
                        None => return Outcome::from_opt(None),
                    },
                    Outcome::Hit(e) => return Outcome::Hit(e),
                };
                if *is_consuming {
                    if let Term::Var { name } = receiver.as_ref() {
                        if receiver_is_versioned_iterator(name, ctx.scope) {
                            let occ = ctx.scope.bump_consuming_occurrence(name);
                            if occ > 0 {
                                receiver = make_var(format!("{name}@adv{occ}"));
                            }
                        }
                    }
                }
                let mut terms = vec![receiver];
                for arg in args {
                    let term = match build_term(arg, &fcx).desugar(ctx) {
                        Outcome::Dug(d) => match d.into_term() {
                            Some(t) => t,
                            None => return Outcome::from_opt(None),
                        },
                        Outcome::Hit(e) => return Outcome::Hit(e),
                    };
                    terms.push(term);
                }
                Outcome::Dug(Desugared::Term(Rc::new(Term::Ctor {
                    name: format!("method:{method}"),
                    args: terms,
                })))
            }
        }
    }
}
