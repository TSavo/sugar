// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for pure `bool` Option-producing methods over literal bool
// receivers. Recognition is lazy: it captures the raw receiver and argument site;
// `desugar` decides whether the receiver is a concrete bool in the live binding
// context. Non-literal receivers fall back to the ordinary opaque method term.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, ExprClosure};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
use crate::sugar::method;
use crate::sugar::monadic::{none_term, some_term};
use crate::{const_eval, strip_refs_groups, ConstVal, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("bool_literal_method", &["method"], recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    let method = call.method.to_string();
    match method.as_str() {
        "then_some" if call.args.len() == 1 => {}
        "then"
            if call.args.len() == 1
                && matches!(strip_refs_groups(&call.args[0]), Expr::Closure(_)) => {}
        _ => return None,
    }
    Some(Box::new(BoolMethodSugar {
        method: method::method_key(call),
        receiver: call.receiver.as_ref().clone(),
        args: call.args.iter().cloned().collect(),
        let_inits: capture_let_inits(fcx),
    }))
}

struct BoolMethodSugar {
    method: String,
    receiver: Expr,
    args: Vec<Expr>,
    let_inits: BTreeMap<String, Expr>,
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

fn const_env(bindings: &BTreeMap<String, &Expr>) -> BTreeMap<String, ConstVal> {
    let mut env = BTreeMap::new();
    for _ in 0..bindings.len() {
        let mut changed = false;
        for (name, init) in bindings {
            if env.contains_key(name) {
                continue;
            }
            if let Some(value) = const_eval(init, &env) {
                env.insert(name.clone(), value);
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    env
}

fn const_bool(expr: &Expr, bindings: &BTreeMap<String, &Expr>) -> Option<bool> {
    match const_eval(expr, &const_env(bindings))? {
        ConstVal::Bool(value) => Some(value),
        _ => None,
    }
}

fn build_child_term(expr: &Expr, fcx: &SugarBuildCtx, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match build_term(expr, fcx).desugar(ctx) {
        Outcome::Complete(d) => d.into_term().ok_or_else(|| Outcome::from_opt(None)),
        Outcome::Incomplete(e) => Err(Outcome::Incomplete(e)),
    }
}

fn zero_arg_closure(expr: &Expr) -> Option<&ExprClosure> {
    let Expr::Closure(closure) = strip_refs_groups(expr) else {
        return None;
    };
    closure.inputs.is_empty().then_some(closure)
}

impl BoolMethodSugar {
    fn opaque_method_term(
        &self,
        receiver: Rc<Term>,
        fcx: &SugarBuildCtx,
        ctx: &SugarCtx,
    ) -> Outcome {
        let mut terms = vec![receiver];
        for arg in &self.args {
            let term = match build_child_term(arg, fcx, ctx) {
                Ok(term) => term,
                Err(outcome) => return outcome,
            };
            terms.push(term);
        }
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: format!("method:{}", self.method),
            args: terms,
        })))
    }
}

impl Sugar for BoolMethodSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let stable = stable_let_bindings(ctx.scope);
        let let_inits = merge_let_inits(&stable, &self.let_inits);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);

        let receiver = match build_child_term(&self.receiver, &fcx, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let Some(value) = const_bool(&self.receiver, &let_inits) else {
            return self.opaque_method_term(receiver, &fcx, ctx);
        };

        match self.method.as_str() {
            "then_some" => {
                let Some(arg) = self.args.first() else {
                    return Outcome::from_opt(None);
                };
                let payload = match build_child_term(strip_refs_groups(arg), &fcx, ctx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                Outcome::Complete(Desugared::Term(if value {
                    some_term(payload)
                } else {
                    none_term()
                }))
            }
            "then" => {
                let Some(arg) = self.args.first() else {
                    return Outcome::from_opt(None);
                };
                if !value {
                    return Outcome::Complete(Desugared::Term(none_term()));
                }
                let Some(closure) = zero_arg_closure(arg) else {
                    return self.opaque_method_term(receiver, &fcx, ctx);
                };
                let payload = match build_child_term(strip_refs_groups(&closure.body), &fcx, ctx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                Outcome::Complete(Desugared::Term(some_term(payload)))
            }
            _ => Outcome::from_opt(None),
        }
    }
}
