// SPDX-License-Identifier: Apache-2.0
//
// `LiteralSliceSugar`: sequence-floor sugar for const-bounded slices over literal
// arrays, e.g. `xs[..0]`. This is compiler/std sugar over a written array: when the
// receiver is a literal array in scope and the slice bounds are const and in-bounds,
// the slice is just the corresponding finite sequence. Empty slices are valid
// sequences; terminals like `.next()` need them to materialize `None`.

use std::collections::BTreeMap;

use syn::{Expr, ExprRange, Pat, Stmt};
use tracing::debug;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    const_acc_init_value, const_eval, const_int, repeat_count_in_scope, repeat_count_literal,
    strip_refs_groups, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx, TemporalScope,
    SUGAR_SEQ_CAP,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite_before(
        "literal_slice",
        &["reference_sequence"],
        crate::sugar::claim::SugarWitnesses::Pending,
        recognize_composite,
    );

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Index(index) = strip_refs_groups(expr) else {
        return None;
    };
    let elems = resolve_literal_elems(&index.expr, fcx.let_inits(), Some(fcx.scope()), 0)?;
    let (start, end) = slice_bounds_with_lets(&index.index, elems.len(), fcx.let_inits())?;
    debug!(
        target: "sugar_lift_rust_tests::sugar::literal_slice",
        start,
        end,
        len = elems.len(),
        "recognized literal slice"
    );
    Some(Box::new(LiteralSliceSugar {
        elems: elems
            .into_iter()
            .skip(start)
            .take(end - start)
            .map(|expr| DesugaredElem {
                value: const_eval(&expr, &BTreeMap::new()),
                expr,
            })
            .collect(),
    }))
}

pub(crate) fn is_literal_slice_base<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
) -> bool {
    is_literal_slice_base_inner(expr, let_inits, None)
}

pub(crate) fn is_literal_slice_base_in_scope<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    scope: &'a TemporalScope,
) -> bool {
    is_literal_slice_base_inner(expr, let_inits, Some(scope))
}

fn is_literal_slice_base_inner<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    scope: Option<&'a TemporalScope>,
) -> bool {
    let Expr::Index(index) = strip_refs_groups(expr) else {
        return false;
    };
    resolve_literal_elems(&index.expr, let_inits, scope, 0)
        .and_then(|elems| slice_bounds_with_lets(&index.index, elems.len(), let_inits))
        .is_some()
}

pub(crate) fn literal_slice_len<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
) -> Option<usize> {
    literal_slice_len_inner(expr, let_inits, None)
}

pub(crate) fn literal_slice_len_in_scope<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    scope: &'a TemporalScope,
) -> Option<usize> {
    literal_slice_len_inner(expr, let_inits, Some(scope))
}

fn literal_slice_len_inner<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    scope: Option<&'a TemporalScope>,
) -> Option<usize> {
    let Expr::Index(index) = strip_refs_groups(expr) else {
        return None;
    };
    let elems = resolve_literal_elems(&index.expr, let_inits, scope, 0)?;
    let (start, end) = slice_bounds_with_lets(&index.index, elems.len(), let_inits)?;
    Some(end - start)
}

struct LiteralSliceSugar {
    elems: Vec<DesugaredElem>,
}

impl Sugar for LiteralSliceSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Complete(Desugared::Seq(self.elems.clone()))
    }
}

fn resolve_literal_elems<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    scope: Option<&'a TemporalScope>,
    depth: usize,
) -> Option<Vec<Expr>> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Array(array) => Some(array.elems.iter().cloned().collect()),
        Expr::Repeat(repeat) => {
            let count = match scope {
                Some(scope) => repeat_count_in_scope(&repeat.len, scope),
                None => repeat_count_literal(&repeat.len),
            }?;
            if count > SUGAR_SEQ_CAP as usize {
                return None;
            }
            Some((0..count).map(|_| (*repeat.expr).clone()).collect())
        }
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let init = let_inits
                .get(&name)
                .copied()
                .or_else(|| scope.and_then(|scope| scope.stable_let_binding_for_term(&name)))?;
            resolve_literal_elems(init, let_inits, scope, depth + 1)
        }
        _ => None,
    }
}

pub(crate) fn slice_bounds(expr: &Expr, len: usize) -> Option<(usize, usize)> {
    if let Some(bounds) = exhausted_literal_iterator_block_bounds(expr, len) {
        return Some(bounds);
    }
    if len > SUGAR_SEQ_CAP as usize {
        return None;
    }
    let Expr::Range(range) = strip_refs_groups(expr) else {
        return None;
    };
    slice_range_bounds(range, len)
}

fn exhausted_literal_iterator_block_bounds(expr: &Expr, len: usize) -> Option<(usize, usize)> {
    let Expr::Block(block) = strip_refs_groups(expr) else {
        return None;
    };
    let [Stmt::Local(local), Stmt::Expr(drain, _), Stmt::Expr(tail, None)] =
        block.block.stmts.as_slice()
    else {
        return None;
    };
    let name = mutable_simple_binding(&local.pat)?;
    let init = local.init.as_ref().filter(|init| init.diverge.is_none())?;
    if !is_full_drain_by_ref_count(drain, &name) || !is_path_named(tail, &name) {
        return None;
    }
    exhausted_range_empty_bounds(&init.expr, len)
}

fn mutable_simple_binding(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(id) if id.subpat.is_none() && id.mutability.is_some() && id.by_ref.is_none() => {
            Some(id.ident.to_string())
        }
        Pat::Type(t) => mutable_simple_binding(&t.pat),
        Pat::Paren(p) => mutable_simple_binding(&p.pat),
        _ => None,
    }
}

fn is_full_drain_by_ref_count(expr: &Expr, name: &str) -> bool {
    let Expr::MethodCall(count) = strip_refs_groups(expr) else {
        return false;
    };
    if count.method != "count" || !count.args.is_empty() {
        return false;
    }
    let Expr::MethodCall(by_ref) = strip_refs_groups(&count.receiver) else {
        return false;
    };
    by_ref.method == "by_ref" && by_ref.args.is_empty() && is_path_named(&by_ref.receiver, name)
}

fn is_path_named(expr: &Expr, name: &str) -> bool {
    matches!(strip_refs_groups(expr), Expr::Path(path) if path.qself.is_none() && path.path.is_ident(name))
}

fn exhausted_range_empty_bounds(expr: &Expr, len: usize) -> Option<(usize, usize)> {
    let Expr::Range(range) = strip_refs_groups(expr) else {
        return None;
    };
    let start = match &range.start {
        Some(start) => const_usize(start)?,
        None => 0,
    };
    let end = const_usize(range.end.as_deref()?)?;
    let exhausted_at = match range.limits {
        syn::RangeLimits::HalfOpen(_) => end,
        syn::RangeLimits::Closed(_) => end.checked_add(1)?,
    };
    (start <= exhausted_at && exhausted_at <= len).then_some((exhausted_at, exhausted_at))
}

fn slice_range_bounds(range: &ExprRange, len: usize) -> Option<(usize, usize)> {
    let start = match &range.start {
        Some(start) => const_usize(start)?,
        None => 0,
    };
    let mut end = match &range.end {
        Some(end) => const_usize(end)?,
        None => len,
    };
    if matches!(range.limits, syn::RangeLimits::Closed(_)) {
        end = end.checked_add(1)?;
    }
    (start <= end && end <= len).then_some((start, end))
}

fn slice_bounds_with_lets<'a>(
    expr: &Expr,
    len: usize,
    let_inits: &BTreeMap<String, &'a Expr>,
) -> Option<(usize, usize)> {
    if let Some(bounds) = exhausted_literal_iterator_block_bounds(expr, len) {
        return Some(bounds);
    }
    if len > SUGAR_SEQ_CAP as usize {
        return None;
    }
    let Expr::Range(range) = strip_refs_groups(expr) else {
        return None;
    };
    let start = match &range.start {
        Some(start) => const_usize_with_lets(start, let_inits)?,
        None => 0,
    };
    let mut end = match &range.end {
        Some(end) => const_usize_with_lets(end, let_inits)?,
        None => len,
    };
    if matches!(range.limits, syn::RangeLimits::Closed(_)) {
        end = end.checked_add(1)?;
    }
    (start <= end && end <= len).then_some((start, end))
}

fn const_usize(expr: &Expr) -> Option<usize> {
    usize::try_from(const_int(expr)?).ok()
}

fn const_usize_with_lets<'a>(expr: &Expr, let_inits: &BTreeMap<String, &'a Expr>) -> Option<usize> {
    usize::try_from(const_acc_init_value(expr, let_inits)?.as_int()?).ok()
}
