// SPDX-License-Identifier: Apache-2.0
//
// `WrappingNegSugar`: primitive integer `.wrapping_neg()` over a grounded literal is
// a stdlib/compiler axiom. The source receiver supplies the width when it is written
// with a primitive suffix/cast/associated const; otherwise ordinary exact negation is
// enough for unsuffixed literals in the lifted source.

use sugar_ir_symbolic::num;
use syn::{Expr, ExprPath, PathArguments, Type};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::int_sqrt::term_as_int;
use crate::{strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("wrapping_neg", SugarRole::Term, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "wrapping_neg" || !call.args.is_empty() {
        return None;
    }
    Some(Box::new(WrappingNegSugar {
        receiver_expr: (*call.receiver).clone(),
        receiver: build_term(&call.receiver, fcx),
    }))
}

struct WrappingNegSugar {
    receiver_expr: Expr,
    receiver: Box<dyn Sugar>,
}

impl Sugar for WrappingNegSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        let Some(value) = term_as_int(&receiver) else {
            return Outcome::from_opt(None);
        };
        let Some(result) = wrapping_neg_value(value, integer_kind_hint(&self.receiver_expr)) else {
            return Outcome::from_opt(None);
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::wrapping_neg",
            value,
            result,
            "resolved primitive wrapping_neg stdlib axiom to literal"
        );
        Outcome::Dug(Desugared::Term(num(result)))
    }
}

#[derive(Clone, Copy)]
struct IntegerKind {
    signed: bool,
    bits: u32,
}

fn wrapping_neg_value(value: i128, kind: Option<IntegerKind>) -> Option<i128> {
    let Some(kind) = kind else {
        return value.checked_neg();
    };
    if kind.signed {
        if kind.bits == 128 {
            return if value == i128::MIN {
                Some(i128::MIN)
            } else {
                value.checked_neg()
            };
        }
        let modulus = 1i128.checked_shl(kind.bits)?;
        let sign_bit = 1i128.checked_shl(kind.bits - 1)?;
        let raw = ((0i128.checked_sub(value)?) % modulus + modulus) % modulus;
        Some(if raw >= sign_bit { raw - modulus } else { raw })
    } else {
        if kind.bits == 128 {
            return if value == 0 { Some(0) } else { None };
        }
        let modulus = 1i128.checked_shl(kind.bits)?;
        Some(((0i128.checked_sub(value)?) % modulus + modulus) % modulus)
    }
}

fn integer_kind_hint(expr: &Expr) -> Option<IntegerKind> {
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => match &lit.lit {
            syn::Lit::Int(i) => primitive_integer_kind(i.suffix()),
            _ => None,
        },
        Expr::Cast(cast) => integer_kind_from_type(&cast.ty),
        Expr::Path(path) => integer_kind_from_expr_path(path),
        Expr::Unary(unary) => integer_kind_hint(&unary.expr),
        Expr::Paren(paren) => integer_kind_hint(&paren.expr),
        Expr::Group(group) => integer_kind_hint(&group.expr),
        _ => None,
    }
}

fn integer_kind_from_expr_path(path: &ExprPath) -> Option<IntegerKind> {
    if let Some(qself) = &path.qself {
        return integer_kind_from_type(&qself.ty);
    }
    let first = path.path.segments.first()?;
    primitive_integer_kind(&first.ident.to_string())
}

fn integer_kind_from_type(ty: &Type) -> Option<IntegerKind> {
    let Type::Path(path) = ty else {
        return None;
    };
    if path.qself.is_some() || path.path.segments.len() != 1 {
        return None;
    }
    let segment = path.path.segments.first()?;
    if !matches!(segment.arguments, PathArguments::None) {
        return None;
    }
    primitive_integer_kind(&segment.ident.to_string())
}

fn primitive_integer_kind(name: &str) -> Option<IntegerKind> {
    let (signed, bits) = match name {
        "i8" => (true, 8),
        "i16" => (true, 16),
        "i32" => (true, 32),
        "i64" => (true, 64),
        "i128" => (true, 128),
        "isize" => (true, usize::BITS),
        "u8" => (false, 8),
        "u16" => (false, 16),
        "u32" => (false, 32),
        "u64" => (false, 64),
        "u128" => (false, 128),
        "usize" => (false, usize::BITS),
        _ => return None,
    };
    Some(IntegerKind { signed, bits })
}
