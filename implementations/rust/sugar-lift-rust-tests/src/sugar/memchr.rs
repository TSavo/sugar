// SPDX-License-Identifier: Apache-2.0
//
// Literal `memchr` / `memrchr` terminal sugar. Byte-string and literal byte
// arrays are searched exactly. Runtime or mutable slice sources stop at a named
// Incomplete boundary instead of leaking through the structural backstop.

use std::collections::BTreeMap;

use syn::{Expr, Lit, RangeLimits};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
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
    fcx: &crate::sugar::factory::SugarBuildCtx,
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
        needle: SugarBody::term(&call.args[0], fcx),
        needle_site: call.args[0].clone(),
        haystack: call.args[1].clone(),
        reverse,
    }))
}

struct MemchrSugar {
    needle: SugarBody<TermFloor>,
    needle_site: Expr,
    haystack: Expr,
    reverse: bool,
}

impl Sugar for MemchrSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let stable = stable_let_bindings(ctx.scope);
        let let_inits: BTreeMap<String, &Expr> =
            stable.iter().map(|(k, v)| (k.clone(), v)).collect();
        let needle = match const_byte_term(&self.needle, ctx) {
            Ok(Some(byte)) => byte,
            Ok(None) => {
                return Outcome::Incomplete(Effect::MemchrRuntime {
                    boundary: token_key(&self.needle_site),
                    reason: format!(
                        "runtime memchr needle, not literal (bin-2: runtime data, not constructed \
                         from source literals); refused: `{}`",
                        token_key(&self.needle_site)
                    ),
                });
            }
            Err(effect) => return Outcome::Incomplete(effect),
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
            let (start, end) = slice_bounds(&index.index, bytes.len(), ctx, let_inits)?
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
) -> Result<Option<(usize, usize)>, Effect> {
    let Expr::Range(range) = peel_refs_groups(expr) else {
        return Ok(None);
    };
    let start = match &range.start {
        Some(start) => {
            let Some(start) = const_int_term(start, ctx, let_inits)? else {
                return Ok(None);
            };
            let Ok(start) = usize::try_from(start) else {
                return Ok(None);
            };
            start
        }
        None => 0,
    };
    let mut end = match &range.end {
        Some(end) => {
            let Some(end) = const_int_term(end, ctx, let_inits)? else {
                return Ok(None);
            };
            let Ok(end) = usize::try_from(end) else {
                return Ok(None);
            };
            end
        }
        None => len,
    };
    if matches!(range.limits, RangeLimits::Closed(_)) {
        let Some(inclusive_end) = end.checked_add(1) else {
            return Ok(None);
        };
        end = inclusive_end;
    }
    Ok((start <= end && end <= len).then_some((start, end)))
}

fn const_byte_term(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Option<u8>, Effect> {
    let term = match body.reduce(ctx) {
        Outcome::Complete(d) => d.into_term(),
        Outcome::Incomplete(effect) => return Err(effect),
    };
    let Some(term) = term else {
        return Ok(None);
    };
    Ok(const_fold_int_term(&term).and_then(|value| u8::try_from(value).ok()))
}

fn const_int_term<'a>(
    expr: &Expr,
    _ctx: &SugarCtx,
    let_inits: &BTreeMap<String, &'a Expr>,
) -> Result<Option<i128>, Effect> {
    Ok(const_int_value(expr, let_inits))
}

fn const_byte_value(expr: &Expr) -> Option<u8> {
    match const_eval(expr, &BTreeMap::new())? {
        ConstVal::Int(n) => u8::try_from(n).ok(),
        ConstVal::PrimitiveInt { raw, .. } => u8::try_from(raw).ok(),
        _ => None,
    }
}

fn const_int_value<'a>(expr: &Expr, let_inits: &BTreeMap<String, &'a Expr>) -> Option<i128> {
    let value = match peel_refs_groups(expr) {
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let init = let_inits.get(&name).copied()?;
            const_eval(init, &BTreeMap::new())?
        }
        _ => const_eval(expr, &BTreeMap::new())?,
    };
    match value {
        ConstVal::Int(n) => Some(n),
        ConstVal::PrimitiveInt { raw, .. } => i128::try_from(raw).ok(),
        ConstVal::UInt128(n) => i128::try_from(n).ok(),
        _ => None,
    }
}

fn runtime_slice_effect(expr: &Expr) -> Effect {
    Effect::MemchrRuntime {
        boundary: token_key(expr),
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
