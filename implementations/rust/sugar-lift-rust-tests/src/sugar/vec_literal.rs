// SPDX-License-Identifier: Apache-2.0
//
// `VecLiteralSugar`: stdlib vector-builder patterns that are closed over primitive
// compiler axioms. This is deliberately not a general mutable-Vec interpreter; it
// owns the finite `vec![]` + typed bit-pattern loop used by core uint tests.

use std::collections::BTreeMap;

use syn::{BinOp, Expr, Lit, Pat, Stmt, Type, UnOp};
use tracing::debug;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::{
    const_eval, parse_macro_args, primitive_int_kind, simple_path_name, strip_refs_groups,
    token_key, ConstVal, Desugared, DesugaredElem, Outcome, PrimitiveIntKind, Sugar, SugarCtx,
    SUGAR_SEQ_CAP,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::composite("vec_literal", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let source = resolve_vec_literal_source(expr, fcx, 0)?;
    vec_builder_pattern(&source)?;
    Some(Box::new(VecLiteralSugar { source }))
}

struct VecLiteralSugar {
    source: Expr,
}

impl Sugar for VecLiteralSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let Some(seq) = eval_vec_builder_source(&self.source, ctx, 0) else {
            return Outcome::from_opt(None);
        };
        if seq.is_empty() || seq.len() > SUGAR_SEQ_CAP as usize {
            return Outcome::from_opt(None);
        }
        debug!(
            target: "sugar_lift_rust_tests::sugar::vec_literal",
            len = seq.len(),
            source = %token_key(&self.source),
            "resolved vec builder to literal sequence"
        );
        Outcome::Dug(Desugared::Seq(seq))
    }
}

fn resolve_vec_literal_source(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> Option<Expr> {
    if depth > 8 {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Block(_) => Some(expr.clone()),
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let init = fcx
                .let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))?;
            resolve_vec_literal_source(init, fcx, depth + 1)
        }
        _ => None,
    }
}

fn eval_vec_builder_source(
    expr: &Expr,
    ctx: &SugarCtx,
    depth: usize,
) -> Option<Vec<DesugaredElem>> {
    if depth > 8 {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Block(block) => eval_vec_builder_block(&block.block.stmts),
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let init = ctx.scope.stable_let_binding_for_term(&name)?;
            eval_vec_builder_source(init, ctx, depth + 1)
        }
        _ => None,
    }
}

fn eval_vec_builder_block(stmts: &[Stmt]) -> Option<Vec<DesugaredElem>> {
    let pattern = vec_builder_pattern_from_stmts(stmts)?;
    let mut x = pattern.initial_x;
    let mut w = pattern.initial_w;
    let mut values = Vec::new();
    let mask = primitive_mask(pattern.kind);
    while w > 0 {
        w >>= 1;
        values.push(x & mask);
        values.push((!x) & mask);
        let shifted = if w >= 128 { 0 } else { (x << w) & mask };
        x = (x ^ shifted) & mask;
        if values.len() > SUGAR_SEQ_CAP as usize {
            return None;
        }
    }
    values
        .into_iter()
        .map(|raw| {
            let expr: Expr = syn::parse_str(&format!("{raw}{}", pattern.kind.name)).ok()?;
            Some(DesugaredElem {
                value: const_eval(&expr, &BTreeMap::new()),
                expr,
            })
        })
        .collect()
}

fn vec_builder_pattern(expr: &Expr) -> Option<VecBuilderPattern> {
    let Expr::Block(block) = strip_refs_groups(expr) else {
        return None;
    };
    vec_builder_pattern_from_stmts(&block.block.stmts)
}

fn vec_builder_pattern_from_stmts(stmts: &[Stmt]) -> Option<VecBuilderPattern> {
    let [Stmt::Local(vec_local), Stmt::Local(x_local), Stmt::Local(w_local), Stmt::Expr(Expr::While(while_expr), _), tail] =
        stmts
    else {
        return None;
    };
    let vec_name = vec_empty_local_name(vec_local)?;
    let (x_name, kind, initial_x) = typed_int_local(x_local)?;
    let (w_name, initial_w) = bits_local(w_local, kind)?;
    if !while_condition_is_positive_path(&while_expr.cond, &w_name) {
        return None;
    }
    if !tail_returns_path(tail, &vec_name) {
        return None;
    }
    let [shrink_w, push_x, push_not_x, xor_shift_x] = while_expr.body.stmts.as_slice() else {
        return None;
    };
    if !is_shr_assign_by_one(shrink_w, &w_name) {
        return None;
    }
    if !is_push_path(push_x, &vec_name, &x_name, false) {
        return None;
    }
    if !is_push_path(push_not_x, &vec_name, &x_name, true) {
        return None;
    }
    if !is_xor_shift_assign(xor_shift_x, &x_name, &w_name) {
        return None;
    }
    Some(VecBuilderPattern {
        kind,
        initial_x,
        initial_w,
    })
}

struct VecBuilderPattern {
    kind: PrimitiveIntKind,
    initial_x: u128,
    initial_w: u32,
}

fn vec_empty_local_name(local: &syn::Local) -> Option<String> {
    let name = mut_pat_ident(&local.pat)?;
    let init = local.init.as_ref().filter(|init| init.diverge.is_none())?;
    let Expr::Macro(expr_macro) = strip_refs_groups(&init.expr) else {
        return None;
    };
    if !expr_macro
        .mac
        .path
        .segments
        .last()
        .is_some_and(|seg| seg.ident == "vec")
    {
        return None;
    }
    let args = parse_macro_args(expr_macro.mac.tokens.clone()).ok()?;
    args.exprs.is_empty().then_some(name)
}

fn typed_int_local(local: &syn::Local) -> Option<(String, PrimitiveIntKind, u128)> {
    let Pat::Type(pat_type) = &local.pat else {
        return None;
    };
    let name = mut_pat_ident(&pat_type.pat)?;
    let kind = primitive_kind_from_type(&pat_type.ty)?;
    let init = local.init.as_ref().filter(|init| init.diverge.is_none())?;
    let initial = if is_not_zero(&init.expr) {
        primitive_mask(kind)
    } else {
        let value = const_eval(&init.expr, &BTreeMap::new())?;
        mask_const_to_kind(value, kind)?
    };
    Some((name, kind, initial))
}

fn bits_local(local: &syn::Local, kind: PrimitiveIntKind) -> Option<(String, u32)> {
    let name = mut_pat_ident(&local.pat)?;
    let init = local.init.as_ref().filter(|init| init.diverge.is_none())?;
    type_bits_expr(&init.expr, kind).map(|bits| (name, bits))
}

fn mut_pat_ident(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(pat) if pat.mutability.is_some() && pat.subpat.is_none() => {
            Some(pat.ident.to_string())
        }
        Pat::Paren(paren) => mut_pat_ident(&paren.pat),
        _ => None,
    }
}

fn primitive_kind_from_type(ty: &Type) -> Option<PrimitiveIntKind> {
    let Type::Path(type_path) = ty else {
        return None;
    };
    if type_path.qself.is_some() || type_path.path.segments.len() != 1 {
        return None;
    }
    primitive_int_kind(&type_path.path.segments.first()?.ident.to_string())
}

fn type_bits_expr(expr: &Expr, expected: PrimitiveIntKind) -> Option<u32> {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return None;
    };
    if path.qself.is_some() || path.path.segments.len() != 2 {
        return None;
    }
    let mut segments = path.path.segments.iter();
    let kind = primitive_int_kind(&segments.next()?.ident.to_string())?;
    let bits = segments.next()?;
    (kind == expected && bits.ident == "BITS").then_some(kind.bits)
}

fn tail_returns_path(stmt: &Stmt, name: &str) -> bool {
    let Stmt::Expr(expr, None) = stmt else {
        return false;
    };
    simple_path_name(expr).is_some_and(|path| path == name)
}

fn while_condition_is_positive_path(expr: &Expr, name: &str) -> bool {
    let Expr::Binary(binary) = strip_refs_groups(expr) else {
        return false;
    };
    matches!(binary.op, BinOp::Gt(_))
        && simple_path_name(&binary.left).is_some_and(|path| path == name)
        && int_lit_is(&binary.right, 0)
}

fn is_shr_assign_by_one(stmt: &Stmt, name: &str) -> bool {
    let Stmt::Expr(Expr::Binary(binary), _) = stmt else {
        return false;
    };
    matches!(binary.op, BinOp::ShrAssign(_))
        && simple_path_name(&binary.left).is_some_and(|path| path == name)
        && int_lit_is(&binary.right, 1)
}

fn is_push_path(stmt: &Stmt, vec_name: &str, x_name: &str, inverted: bool) -> bool {
    let Stmt::Expr(Expr::MethodCall(call), _) = stmt else {
        return false;
    };
    call.method == "push"
        && call.args.len() == 1
        && simple_path_name(&call.receiver).is_some_and(|path| path == vec_name)
        && call
            .args
            .first()
            .is_some_and(|arg| expr_is_path_or_not_path(arg, x_name, inverted))
}

fn is_xor_shift_assign(stmt: &Stmt, x_name: &str, w_name: &str) -> bool {
    let Stmt::Expr(Expr::Binary(assign), _) = stmt else {
        return false;
    };
    if !matches!(assign.op, BinOp::BitXorAssign(_))
        || !simple_path_name(&assign.left).is_some_and(|path| path == x_name)
    {
        return false;
    }
    let Expr::Binary(shift) = strip_refs_groups(&assign.right) else {
        return false;
    };
    matches!(shift.op, BinOp::Shl(_))
        && simple_path_name(&shift.left).is_some_and(|path| path == x_name)
        && simple_path_name(&shift.right).is_some_and(|path| path == w_name)
}

fn expr_is_path_or_not_path(expr: &Expr, name: &str, inverted: bool) -> bool {
    if inverted {
        let Expr::Unary(unary) = strip_refs_groups(expr) else {
            return false;
        };
        matches!(unary.op, UnOp::Not(_))
            && simple_path_name(&unary.expr).is_some_and(|path| path == name)
    } else {
        simple_path_name(expr).is_some_and(|path| path == name)
    }
}

fn is_not_zero(expr: &Expr) -> bool {
    let Expr::Unary(unary) = strip_refs_groups(expr) else {
        return false;
    };
    matches!(unary.op, UnOp::Not(_)) && int_lit_is(&unary.expr, 0)
}

fn int_lit_is(expr: &Expr, expected: u128) -> bool {
    let Expr::Lit(expr_lit) = strip_refs_groups(expr) else {
        return false;
    };
    let Lit::Int(lit) = &expr_lit.lit else {
        return false;
    };
    lit.base10_parse::<u128>().ok() == Some(expected)
}

fn mask_const_to_kind(value: ConstVal, kind: PrimitiveIntKind) -> Option<u128> {
    match value {
        ConstVal::PrimitiveInt { raw, .. } => Some(raw & primitive_mask(kind)),
        ConstVal::UInt128(raw) => Some(raw & primitive_mask(kind)),
        ConstVal::Int(n) => Some((n as u128) & primitive_mask(kind)),
        _ => None,
    }
}

fn primitive_mask(kind: PrimitiveIntKind) -> u128 {
    if kind.bits == 128 {
        u128::MAX
    } else {
        (1u128 << kind.bits) - 1
    }
}
