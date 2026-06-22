// SPDX-License-Identifier: Apache-2.0
//
// `IntPowSugar`: primitive integer `.pow(<literal exponent>)` as a compiler
// axiom. For grounded bases this can fold to a literal; for point-wise contracts
// it rewrites small literal exponents to multiplication over the receiver term.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{num, Term};
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::{
    const_fold_int_term, const_fold_u128_term, simple_path_name, strip_refs_groups, u128_term,
    Desugared, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("int_pow", SugarRole::Term, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "pow" || call.args.len() != 1 {
        return None;
    }
    let exponent = call.args.first()?;
    if !receiver_looks_primitive_int(exponent, fcx, 0) {
        return None;
    }
    if !receiver_looks_primitive_int(&call.receiver, fcx, 0) {
        return None;
    }
    Some(Box::new(IntPowSugar {
        receiver: (*call.receiver).clone(),
        exponent: exponent.clone(),
        let_inits: capture_let_inits(fcx),
    }))
}

struct IntPowSugar {
    receiver: Expr,
    exponent: Expr,
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

fn desugar_term_expr(
    expr: &Expr,
    ctx: &SugarCtx,
    fcx: &SugarBuildCtx,
) -> Result<Rc<Term>, Outcome> {
    match build_term(expr, fcx).desugar(ctx) {
        Outcome::Dug(d) => d.into_term().ok_or_else(|| Outcome::from_opt(None)),
        Outcome::Hit(e) => Err(Outcome::Hit(e)),
    }
}

impl Sugar for IntPowSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
        let let_inits = merge_let_inits(&stable, &self.let_inits);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let receiver = match desugar_term_expr(&self.receiver, ctx, &fcx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let exponent = match desugar_term_expr(&self.exponent, ctx, &fcx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let Some(exponent) = const_fold_int_term(&exponent)
            .or_else(|| const_fold_u128_term(&exponent).and_then(|n| i128::try_from(n).ok()))
        else {
            return Outcome::from_opt(None);
        };
        let Some(term) = pow_term(receiver, exponent) else {
            return Outcome::from_opt(None);
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::int_pow",
            exponent,
            "resolved primitive integer pow compiler axiom"
        );
        Outcome::Dug(Desugared::Term(term))
    }
}

fn pow_term(receiver: Rc<Term>, exponent: i128) -> Option<Rc<Term>> {
    if exponent < 0 {
        return None;
    }
    if let Some(base) = const_fold_u128_term(&receiver) {
        let exponent = u32::try_from(exponent).ok()?;
        return Some(u128_term(base.checked_pow(exponent)?));
    }
    if let Some(base) = const_fold_int_term(&receiver) {
        let exponent = u32::try_from(exponent).ok()?;
        return Some(num(base.checked_pow(exponent)?));
    }
    match exponent {
        0 => Some(num(1)),
        1 => Some(receiver),
        2..=8 => {
            let mut acc = receiver.clone();
            for _ in 1..exponent {
                acc = Rc::new(Term::Ctor {
                    name: "*".to_string(),
                    args: vec![acc, receiver.clone()],
                });
            }
            Some(acc)
        }
        _ => None,
    }
}

fn receiver_looks_primitive_int(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => matches!(
            lit.lit,
            syn::Lit::Int(_) | syn::Lit::Byte(_) | syn::Lit::Char(_)
        ),
        Expr::Path(path) => {
            if fcx.scope().const_expr_for_path(&path.path).is_some() {
                return true;
            }
            let Some(name) = simple_path_name(expr) else {
                return false;
            };
            fcx.scope()
                .stable_let_binding_for_term(&name)
                .is_some_and(|init| receiver_looks_primitive_int(init, fcx, depth + 1))
        }
        Expr::Cast(cast) => receiver_looks_primitive_int(&cast.expr, fcx, depth + 1),
        Expr::Unary(unary) => receiver_looks_primitive_int(&unary.expr, fcx, depth + 1),
        Expr::Binary(binary) => {
            receiver_looks_primitive_int(&binary.left, fcx, depth + 1)
                && receiver_looks_primitive_int(&binary.right, fcx, depth + 1)
        }
        Expr::Reference(reference) => receiver_looks_primitive_int(&reference.expr, fcx, depth + 1),
        Expr::MethodCall(call) => matches!(
            call.method.to_string().as_str(),
            "isqrt"
                | "checked_isqrt"
                | "count_ones"
                | "count_zeros"
                | "leading_zeros"
                | "trailing_zeros"
                | "min"
                | "max"
                | "checked_add"
                | "checked_sub"
                | "checked_mul"
                | "checked_div"
                | "wrapping_add"
                | "wrapping_sub"
                | "wrapping_mul"
                | "abs"
                | "signum"
        ),
        _ => false,
    }
}
