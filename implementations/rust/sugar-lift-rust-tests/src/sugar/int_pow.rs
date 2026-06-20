// SPDX-License-Identifier: Apache-2.0
//
// `IntPowSugar`: primitive integer `.pow(<literal exponent>)` as a compiler
// axiom. For grounded bases this can fold to a literal; for point-wise contracts
// it rewrites small literal exponents to multiplication over the receiver term.

use std::rc::Rc;

use sugar_ir_symbolic::{num, Term};
use syn::{Expr, Lit};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::{
    const_fold_int_term, const_fold_u128_term, simple_path_name, strip_refs_groups, Desugared,
    Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "int_pow",
    SugarRole::Term,
    SugarPriority::Primary,
    recognize,
);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "pow" || call.args.len() != 1 {
        return None;
    }
    let exponent = call.args.first()?;
    if literal_exponent(exponent, fcx).is_none() {
        return None;
    }
    if !receiver_looks_primitive_int(&call.receiver, fcx, 0) {
        return None;
    }
    Some(Box::new(IntPowSugar {
        receiver: build_term(&call.receiver, fcx),
        exponent: build_term(exponent, fcx),
    }))
}

struct IntPowSugar {
    receiver: Box<dyn Sugar>,
    exponent: Box<dyn Sugar>,
}

impl Sugar for IntPowSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        let exponent = match self.exponent.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
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
    match exponent {
        n if n < 0 => None,
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

fn literal_exponent(expr: &Expr, fcx: &SugarBuildCtx) -> Option<i128> {
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => match &lit.lit {
            Lit::Int(value) => value.base10_parse::<i128>().ok(),
            _ => None,
        },
        _ => {
            let term = crate::translate_term_in_scope(expr, fcx.scope()).ok()?;
            const_fold_int_term(&term)
                .or_else(|| const_fold_u128_term(&term).and_then(|n| i128::try_from(n).ok()))
        }
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
                | "leading_zeros"
                | "trailing_zeros"
                | "min"
                | "checked_add"
                | "checked_sub"
                | "checked_mul"
                | "checked_div"
        ),
        _ => false,
    }
}
