// SPDX-License-Identifier: Apache-2.0
//
// `IntSqrtSugar`: Rust's primitive integer `isqrt` family over a grounded integer is
// a stdlib/compiler axiom. When the receiver has already bottomed out to a literal
// integer, compute the exact floor square root and emit that literal (or the
// structural `Option` value for `checked_isqrt`).

use std::rc::Rc;

use sugar_ir_symbolic::{num, Term};
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::monadic::{none_term, some_term};
use crate::{
    const_fold_int_term, const_fold_u128_term, u128_term, Desugared, Effect, Outcome, Sugar,
    SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "int_sqrt",
    SugarRole::Term,
    SugarPriority::Primary,
    recognize,
);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !call.args.is_empty() {
        return None;
    }
    let kind = match call.method.to_string().as_str() {
        "isqrt" => Kind::Sqrt,
        "checked_isqrt" => Kind::CheckedSqrt,
        _ => return None,
    };
    Some(Box::new(IntSqrtSugar {
        kind,
        receiver: build_term(&call.receiver, fcx),
    }))
}

#[derive(Clone, Copy)]
enum Kind {
    Sqrt,
    CheckedSqrt,
}

struct IntSqrtSugar {
    kind: Kind,
    receiver: Box<dyn Sugar>,
}

impl Sugar for IntSqrtSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        if let Some(value) = const_fold_u128_term(&receiver) {
            return self.desugar_u128(value);
        }
        let Some(value) = const_fold_int_term(&receiver) else {
            return Outcome::Dug(Desugared::Term(self.symbolic_term(receiver)));
        };
        self.desugar_i128(value)
    }
}

impl IntSqrtSugar {
    fn symbolic_term(&self, receiver: Rc<Term>) -> Rc<Term> {
        let method = match self.kind {
            Kind::Sqrt => "method:isqrt",
            Kind::CheckedSqrt => "method:checked_isqrt",
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::int_sqrt",
            method,
            "kept primitive integer sqrt call symbolic for point-wise contract"
        );
        Rc::new(Term::Ctor {
            name: method.to_string(),
            args: vec![receiver],
        })
    }

    fn desugar_i128(&self, value: i128) -> Outcome {
        match self.kind {
            Kind::Sqrt => {
                let Some(root) = int_sqrt(value) else {
                    return Outcome::Hit(Effect::Unsupported {
                        reason: format!(
                            "primitive integer `isqrt` on negative literal `{value}` panics; refused"
                        ),
                    });
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::int_sqrt",
                    value,
                    root,
                    "resolved primitive integer isqrt stdlib axiom to literal"
                );
                Outcome::Dug(Desugared::Term(num(root)))
            }
            Kind::CheckedSqrt => {
                let term = match int_sqrt(value) {
                    Some(root) => {
                        debug!(
                            target: "sugar_lift_rust_tests::sugar::int_sqrt",
                            value,
                            root,
                            "resolved primitive integer checked_isqrt stdlib axiom to Some literal"
                        );
                        some_term(num(root))
                    }
                    None => {
                        debug!(
                            target: "sugar_lift_rust_tests::sugar::int_sqrt",
                            value,
                            "resolved primitive integer checked_isqrt stdlib axiom to None"
                        );
                        none_term()
                    }
                };
                Outcome::Dug(Desugared::Term(term))
            }
        }
    }

    fn desugar_u128(&self, value: u128) -> Outcome {
        let root = int_sqrt_u128(value);
        match self.kind {
            Kind::Sqrt => {
                debug!(
                    target: "sugar_lift_rust_tests::sugar::int_sqrt",
                    value = %value,
                    root = %root,
                    "resolved primitive u128 isqrt stdlib axiom to literal"
                );
                Outcome::Dug(Desugared::Term(u128_term(root)))
            }
            Kind::CheckedSqrt => {
                debug!(
                    target: "sugar_lift_rust_tests::sugar::int_sqrt",
                    value = %value,
                    root = %root,
                    "resolved primitive u128 checked_isqrt stdlib axiom to Some literal"
                );
                Outcome::Dug(Desugared::Term(some_term(u128_term(root))))
            }
        }
    }
}

pub(crate) fn int_sqrt(value: i128) -> Option<i128> {
    if value < 0 {
        return None;
    }
    let n = value as u128;
    if n < 2 {
        return Some(value);
    }
    let mut lo = 1u128;
    let mut hi = 1u128 << 64;
    let mut best = 1u128;
    while lo <= hi {
        let mid = lo + ((hi - lo) / 2);
        if mid <= n / mid {
            best = mid;
            lo = mid + 1;
        } else {
            hi = mid - 1;
        }
    }
    i128::try_from(best).ok()
}

fn int_sqrt_u128(value: u128) -> u128 {
    if value < 2 {
        return value;
    }
    let mut lo = 1u128;
    let mut hi = 1u128 << 64;
    let mut best = 1u128;
    while lo <= hi {
        let mid = lo + ((hi - lo) / 2);
        if mid <= value / mid {
            best = mid;
            lo = mid + 1;
        } else {
            hi = mid - 1;
        }
    }
    best
}

pub(crate) fn term_as_int(term: &Rc<Term>) -> Option<i128> {
    const_fold_int_term(term)
}
