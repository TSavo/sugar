// SPDX-License-Identifier: Apache-2.0
//
// `MethodSugar` + the TERM recognizer for `Expr::MethodCall`. The constructive
// method-call term node completes the receiver child FIRST, applies the per-occurrence
// consuming-iterator `@adv{n}` re-tag (a runtime read of `ctx.scope`), then completes the
// arg children in source order, and emits `method:<m>` over `[receiver, args..]`.
//
// The recognizer runs the source-of-truth preamble in order: a CLOSED
// `try_fold`/`try_rfold` grounds to a literal and re-builds THAT; a closure-bearing
// adaptor in term position refuses with collection provenance; otherwise the EUF
// `method:` ctor node. This is the TERM-position node — DISTINCT from the COMPOSITE
// `fold`/`for_each`/closure-
// adaptor/match-scrutinee dispatch the COMPOSITE catalog routes `Expr::MethodCall` to.
// Byte-identical to the old fat factory's `Expr::MethodCall` term arm.

use std::rc::Rc;

use sugar_ir_symbolic::{make_var, Term};
use syn::Expr;

use crate::sugar::factory::{
    compat_reduction, FactoryGap, FactoryReduction, SugarBody, SugarBuildCtx, TermFloor,
};
use crate::sugar::term_leaf::reasoned_incomplete;
use crate::try_fold_eval;
use crate::{
    angle_args_key, closure_adaptor_refusal, is_consuming_iterator_method,
    receiver_is_versioned_iterator, simple_path_name, Desugared, Effect, Outcome, Sugar, SugarCtx,
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
                body: SugarBody::term(&grounded, fcx),
            }));
        }
    }
    // A closure-bearing adaptor in term position refuses with collection provenance.
    if let Some(reason) = closure_adaptor_refusal(expr, scope) {
        return Some(reasoned_incomplete(reason));
    }
    // The constructive `method:` ctor. The RECEIVER is completed first; a per-occurrence
    // consuming-iterator advance re-tags the receiver var (`@adv{n}`).
    Some(Box::new(MethodSugar::Constructive {
        method: method_key(call),
        receiver_expr: call.receiver.as_ref().clone(),
        receiver: SugarBody::term(&call.receiver, fcx),
        is_consuming: is_consuming_iterator_method(&call.method.to_string()),
        args: call
            .args
            .iter()
            .map(|arg| SugarBody::term(arg, fcx))
            .collect(),
    }))
}

/// The `method:<m>` ctor key: `method.turbofish` appends the angle-args key.
pub(crate) fn method_key(call: &syn::ExprMethodCall) -> String {
    match &call.turbofish {
        Some(args) => format!("{}{}", call.method, angle_args_key(args)),
        None => call.method.to_string(),
    }
}

/// Method-call term nodes are constructed with their receiver/arg bodies. Raw source
/// spelling is retained only for method identity and source-property checks.
enum MethodSugar {
    Grounded {
        body: SugarBody<TermFloor>,
    },
    Constructive {
        method: String,
        receiver_expr: Expr,
        receiver: SugarBody<TermFloor>,
        is_consuming: bool,
        args: Vec<SugarBody<TermFloor>>,
    },
}

impl Sugar for MethodSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        match self {
            MethodSugar::Grounded { body } => body.reduce(ctx),
            MethodSugar::Constructive {
                method,
                receiver_expr,
                receiver,
                is_consuming,
                args,
            } => {
                if matches!(method.as_str(), "starts_with" | "ends_with") {
                    if let Some(recv_name) = simple_path_name(receiver_expr) {
                        if ctx.scope.is_mut_local(&recv_name) {
                            return Ok(Outcome::Incomplete(Effect::Unsupported {
                                reason: format!(
                                    "{method} predicate over a MUTABLE-local receiver `{recv_name}` \
                                     (bin-2: a slice/string mutated by side-effecting iteration, not \
                                     constructed from source literals); refused"
                                ),
                            }));
                        }
                    }
                }
                let mut receiver = match receiver.reduce(ctx)? {
                    Outcome::Complete(d) => match d.into_term() {
                        Some(t) => t,
                        None => {
                            return Err(FactoryGap::new(format!(
                                "method `{method}` receiver completed a non-Term where a Term was required; write more Sugar for this AST"
                            )))
                        }
                    },
                    Outcome::Incomplete(e) => return Ok(Outcome::Incomplete(e)),
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
                    let term = match arg.reduce(ctx)? {
                        Outcome::Complete(d) => match d.into_term() {
                            Some(t) => t,
                            None => {
                                return Err(FactoryGap::new(format!(
                                    "method `{method}` argument completed a non-Term where a Term was required; write more Sugar for this AST"
                                )))
                            }
                        },
                        Outcome::Incomplete(e) => return Ok(Outcome::Incomplete(e)),
                    };
                    terms.push(term);
                }
                Ok(Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
                    name: format!("method:{method}"),
                    args: terms,
                }))))
            }
        }
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}
