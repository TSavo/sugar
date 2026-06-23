// SPDX-License-Identifier: Apache-2.0
//
// `IntMidpointSugar`: primitive integer `T::midpoint(a, b)` over text-determined
// operands is a stdlib/compiler axiom. The associated type supplies the width and
// signedness; desugar owns the lazy operand lowering and emits the exact literal
// result when both operands bottom out.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{num, Term};
use syn::{Expr, ExprCall};
use tracing::debug;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::int_literal::{primitive_int_kind, IntKind};
use crate::{
    const_fold_int_term, const_fold_u128_term, u128_term, Desugared, Effect, Outcome, Sugar,
    SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("int_midpoint", &["call"], recognize);

fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Call(call) = expr else {
        return None;
    };
    if call.args.len() != 2 {
        return None;
    }
    let kind = midpoint_kind(&call.func)?;
    Some(Box::new(IntMidpointSugar {
        call: call.clone(),
        kind,
    }))
}

fn midpoint_kind(func: &Expr) -> Option<IntKind> {
    let Expr::Path(path) = crate::strip_refs_groups(func) else {
        return None;
    };
    if path.path.segments.last()?.ident != "midpoint" {
        return None;
    }
    if let Some(qself) = &path.qself {
        let syn::Type::Path(ty) = qself.ty.as_ref() else {
            return None;
        };
        return primitive_int_kind(&ty.path.segments.last()?.ident.to_string());
    }
    let ty = path.path.segments.iter().rev().nth(1)?.ident.to_string();
    primitive_int_kind(&ty)
}

struct IntMidpointSugar {
    call: ExprCall,
    kind: IntKind,
}

impl Sugar for IntMidpointSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let lhs = match desugar_arg(&self.call.args[0], ctx, &fcx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let rhs = match desugar_arg(&self.call.args[1], ctx, &fcx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let Some(term) = midpoint_term(&lhs, &rhs, self.kind) else {
            return Outcome::Incomplete(Effect::Unsupported {
                reason: format!(
                    "runtime {} midpoint operand, not literal-determined",
                    self.kind.name
                ),
            });
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::int_midpoint",
            kind = self.kind.name,
            "resolved primitive integer midpoint stdlib axiom"
        );
        Outcome::Complete(Desugared::Term(term))
    }
}

fn desugar_arg(expr: &Expr, ctx: &SugarCtx, fcx: &SugarBuildCtx) -> Result<Rc<Term>, Outcome> {
    match build_term(expr, fcx).desugar(ctx) {
        Outcome::Complete(d) => d.into_term().ok_or_else(|| Outcome::from_opt(None)),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn midpoint_term(lhs: &Rc<Term>, rhs: &Rc<Term>, kind: IntKind) -> Option<Rc<Term>> {
    if kind.signed {
        let lhs = const_fold_int_term(lhs)?;
        let rhs = const_fold_int_term(rhs)?;
        let value = signed_midpoint(lhs, rhs, kind)?;
        return Some(num(value));
    }

    let lhs = const_fold_u128_term(lhs)
        .or_else(|| const_fold_int_term(lhs).and_then(|value| u128::try_from(value).ok()))?;
    let rhs = const_fold_u128_term(rhs)
        .or_else(|| const_fold_int_term(rhs).and_then(|value| u128::try_from(value).ok()))?;
    let value = unsigned_midpoint(lhs, rhs, kind)?;
    if kind.bits == 128 {
        Some(u128_term(value))
    } else {
        Some(num(i128::try_from(value).ok()?))
    }
}

fn signed_midpoint(lhs: i128, rhs: i128, kind: IntKind) -> Option<i128> {
    let (min, max) = signed_bounds(kind.bits);
    if lhs < min || lhs > max || rhs < min || rhs > max {
        return None;
    }
    if (lhs < 0) == (rhs < 0) {
        let halves = (lhs / 2).checked_add(rhs / 2)?;
        let remainders = (lhs % 2).checked_add(rhs % 2)?;
        halves.checked_add(remainders / 2)
    } else {
        lhs.checked_add(rhs)?.checked_div(2)
    }
}

fn unsigned_midpoint(lhs: u128, rhs: u128, kind: IntKind) -> Option<u128> {
    let max = unsigned_max(kind.bits);
    if lhs > max || rhs > max {
        return None;
    }
    Some((lhs & rhs) + ((lhs ^ rhs) >> 1))
}

fn signed_bounds(bits: u32) -> (i128, i128) {
    if bits >= 128 {
        (i128::MIN, i128::MAX)
    } else {
        let sign = 1i128 << (bits - 1);
        (-sign, sign - 1)
    }
}

fn unsigned_max(bits: u32) -> u128 {
    if bits >= 128 {
        u128::MAX
    } else {
        (1u128 << bits) - 1
    }
}
