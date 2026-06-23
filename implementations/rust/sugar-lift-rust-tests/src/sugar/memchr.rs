// SPDX-License-Identifier: Apache-2.0
//
// Literal `memchr` / `memrchr` terminal sugar. Byte-string and literal byte
// arrays are searched exactly. Runtime or mutable slice sources stop at a named
// Incomplete boundary instead of leaking through the structural backstop.

use std::collections::BTreeMap;

use syn::{Expr, Lit, RangeLimits};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
use crate::sugar::monadic::{none_term, some_term};
use crate::{
    const_eval, const_fold_int_term, repeat_count_in_scope, token_key, ConstVal, Desugared, Effect,
    Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("memchr", &["call"], recognize);

pub(crate) fn recognize(
    expr: &Expr,
    _fcx: &crate::sugar::factory::SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let Expr::Call(call) = peel_refs_groups(expr) else {
        return None;
    };
    if call.args.len() != 2 {
        return None;
    }
    let reverse = match path_last(call.func.as_ref())?.as_str() {
        "memchr" => false,
        "memrchr" => true,
        _ => return None,
    };
    Some(Box::new(MemchrSugar {
        needle: call.args[0].clone(),
        haystack: call.args[1].clone(),
        reverse,
    }))
}

struct MemchrSugar {
    needle: Expr,
    haystack: Expr,
    reverse: bool,
}

impl Sugar for MemchrSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let stable = stable_let_bindings(ctx.scope);
        let let_inits: BTreeMap<String, &Expr> =
            stable.iter().map(|(k, v)| (k.clone(), v)).collect();
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let needle = match const_byte_term(&self.needle, &fcx, ctx) {
            Some(byte) => byte,
            None => {
                return Outcome::Incomplete(Effect::Unsupported {
                    reason: format!(
                        "runtime memchr needle, not literal (bin-2: runtime data, not constructed \
                         from source literals); refused: `{}`",
                        token_key(&self.needle)
                    ),
                })
            }
        };
        let haystack = match byte_sequence(&self.haystack, ctx, &let_inits, 0) {
            Ok(bytes) => bytes,
            Err(effect) => return Outcome::Incomplete(effect),
        };
        let found = if self.reverse {
            haystack.iter().rposition(|byte| *byte == needle)
        } else {
            haystack.iter().position(|byte| *byte == needle)
        };
        let term = found
            .map(|idx| some_term(crate::num(idx as i128)))
            .unwrap_or_else(none_term);
        Outcome::Complete(Desugared::Term(term))
    }
}

fn byte_sequence<'a>(
    expr: &Expr,
    ctx: &SugarCtx,
    let_inits: &BTreeMap<String, &'a Expr>,
    depth: usize,
) -> Result<Vec<u8>, Effect> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return Err(runtime_slice_effect(expr));
    }
    match peel_refs_groups(expr) {
        Expr::Lit(lit) => match &lit.lit {
            Lit::ByteStr(bytes) => Ok(bytes.value()),
            _ => Err(runtime_slice_effect(expr)),
        },
        Expr::Array(array) => {
            if array.elems.len() > SUGAR_SEQ_CAP as usize {
                return Err(runtime_slice_effect(expr));
            }
            array
                .elems
                .iter()
                .map(const_byte_value)
                .collect::<Option<Vec<_>>>()
                .ok_or_else(|| runtime_slice_effect(expr))
        }
        Expr::Repeat(repeat) => {
            let count = repeat_count_in_scope(&repeat.len, ctx.scope)
                .filter(|count| *count <= SUGAR_SEQ_CAP as usize)
                .ok_or_else(|| runtime_slice_effect(expr))?;
            let byte = const_byte_value(&repeat.expr).ok_or_else(|| runtime_slice_effect(expr))?;
            Ok(vec![byte; count])
        }
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(ToString::to_string) else {
                return Err(runtime_slice_effect(expr));
            };
            if ctx.scope.is_mut_local(&name) {
                return Err(runtime_slice_effect(expr));
            }
            if let Some(current) = ctx.scope.temporal_rewrite_expr_for(&name) {
                return byte_sequence_owned(current, ctx, let_inits, depth + 1);
            }
            let init = let_inits
                .get(&name)
                .copied()
                .or_else(|| ctx.scope.stable_let_binding_for_term(&name))
                .ok_or_else(|| runtime_slice_effect(expr))?;
            byte_sequence(init, ctx, let_inits, depth + 1)
        }
        Expr::Index(index) => {
            let bytes = byte_sequence(&index.expr, ctx, let_inits, depth + 1)?;
            let (start, end) = slice_bounds(&index.index, bytes.len(), ctx, let_inits)
                .ok_or_else(|| runtime_slice_effect(expr))?;
            Ok(bytes[start..end].to_vec())
        }
        _ => Err(runtime_slice_effect(expr)),
    }
}

fn byte_sequence_owned<'a>(
    expr: Expr,
    ctx: &SugarCtx,
    let_inits: &BTreeMap<String, &'a Expr>,
    depth: usize,
) -> Result<Vec<u8>, Effect> {
    byte_sequence(&expr, ctx, let_inits, depth)
}

fn slice_bounds<'a>(
    expr: &Expr,
    len: usize,
    ctx: &SugarCtx,
    let_inits: &BTreeMap<String, &'a Expr>,
) -> Option<(usize, usize)> {
    let Expr::Range(range) = peel_refs_groups(expr) else {
        return None;
    };
    let start = match &range.start {
        Some(start) => usize::try_from(const_int_term(start, ctx, let_inits)?).ok()?,
        None => 0,
    };
    let mut end = match &range.end {
        Some(end) => usize::try_from(const_int_term(end, ctx, let_inits)?).ok()?,
        None => len,
    };
    if matches!(range.limits, RangeLimits::Closed(_)) {
        end = end.checked_add(1)?;
    }
    (start <= end && end <= len).then_some((start, end))
}

fn const_byte_term(expr: &Expr, fcx: &SugarBuildCtx, ctx: &SugarCtx) -> Option<u8> {
    let term = match build_term(expr, fcx).desugar(ctx) {
        Outcome::Complete(d) => d.into_term()?,
        Outcome::Incomplete(_) => return None,
    };
    u8::try_from(const_fold_int_term(&term)?).ok()
}

fn const_int_term<'a>(
    expr: &Expr,
    ctx: &SugarCtx,
    let_inits: &BTreeMap<String, &'a Expr>,
) -> Option<i128> {
    let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, let_inits);
    let term = match build_term(expr, &fcx).desugar(ctx) {
        Outcome::Complete(d) => d.into_term()?,
        Outcome::Incomplete(_) => return None,
    };
    const_fold_int_term(&term)
}

fn const_byte_value(expr: &Expr) -> Option<u8> {
    match const_eval(expr, &BTreeMap::new())? {
        ConstVal::Int(n) => u8::try_from(n).ok(),
        ConstVal::PrimitiveInt { raw, .. } => u8::try_from(raw).ok(),
        _ => None,
    }
}

fn runtime_slice_effect(expr: &Expr) -> Effect {
    Effect::Unsupported {
        reason: format!(
            "runtime slice source, not literal `{}` (memchr haystack is not a pinned literal byte slice); refused",
            token_key(expr)
        ),
    }
}

fn path_last(expr: &Expr) -> Option<String> {
    let Expr::Path(path) = peel_refs_groups(expr) else {
        return None;
    };
    path.path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
}

fn peel_refs_groups(expr: &Expr) -> &Expr {
    match expr {
        Expr::Reference(reference) => peel_refs_groups(&reference.expr),
        Expr::Paren(paren) => peel_refs_groups(&paren.expr),
        Expr::Group(group) => peel_refs_groups(&group.expr),
        _ => expr,
    }
}
