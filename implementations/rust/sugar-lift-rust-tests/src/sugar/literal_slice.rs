// SPDX-License-Identifier: Apache-2.0
//
// `LiteralSliceSugar`: sequence-floor sugar for const-bounded slices over literal
// arrays, e.g. `xs[..0]`. This is compiler/std sugar over a written array: when the
// receiver is a literal array in scope and the slice bounds are const and in-bounds,
// the slice is just the corresponding finite sequence. Empty slices are valid
// sequences; terminals like `.next()` need them to materialize `None`.

use std::collections::BTreeMap;

use syn::{Expr, ExprArray, ExprRange};
use tracing::debug;

use crate::sugar::factory::SugarBuildCtx;
use crate::{
    const_eval, const_int, strip_refs_groups, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx,
    SUGAR_SEQ_CAP,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite_before(
        "literal_slice",
        &["reference_sequence"],
        recognize_composite,
    );

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Index(index) = strip_refs_groups(expr) else {
        return None;
    };
    let array = resolve_literal_array(&index.expr, fcx.let_inits(), 0)?;
    let (start, end) = slice_bounds(&index.index, array.elems.len())?;
    debug!(
        target: "sugar_lift_rust_tests::sugar::literal_slice",
        start,
        end,
        len = array.elems.len(),
        "recognized literal slice"
    );
    Some(Box::new(LiteralSliceSugar {
        elems: array
            .elems
            .iter()
            .skip(start)
            .take(end - start)
            .cloned()
            .collect(),
    }))
}

pub(crate) fn is_literal_slice_base<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
) -> bool {
    let Expr::Index(index) = strip_refs_groups(expr) else {
        return false;
    };
    resolve_literal_array(&index.expr, let_inits, 0)
        .and_then(|array| slice_bounds(&index.index, array.elems.len()))
        .is_some()
}

pub(crate) fn literal_slice_len<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
) -> Option<usize> {
    let Expr::Index(index) = strip_refs_groups(expr) else {
        return None;
    };
    let array = resolve_literal_array(&index.expr, let_inits, 0)?;
    let (start, end) = slice_bounds(&index.index, array.elems.len())?;
    Some(end - start)
}

struct LiteralSliceSugar {
    elems: Vec<Expr>,
}

impl Sugar for LiteralSliceSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Dug(Desugared::Seq(
            self.elems
                .iter()
                .cloned()
                .map(|expr| DesugaredElem {
                    value: const_eval(&expr, &BTreeMap::new()),
                    expr,
                })
                .collect(),
        ))
    }
}

fn resolve_literal_array<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    depth: usize,
) -> Option<&'a ExprArray> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Array(array) => Some(array),
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let init = let_inits.get(&name)?;
            resolve_literal_array(init, let_inits, depth + 1)
        }
        _ => None,
    }
}

fn slice_bounds(expr: &Expr, len: usize) -> Option<(usize, usize)> {
    if len as i64 > SUGAR_SEQ_CAP {
        return None;
    }
    let Expr::Range(range) = strip_refs_groups(expr) else {
        return None;
    };
    slice_range_bounds(range, len)
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

fn const_usize(expr: &Expr) -> Option<usize> {
    usize::try_from(const_int(expr)?).ok()
}
