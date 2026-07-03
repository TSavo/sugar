// SPDX-License-Identifier: Apache-2.0
//
// `CharRangeFilterMapSugar`: stdlib/compiler axiom for Rust scalar-value `char`
// ranges. `(from..=to).eq((from as u32..=to as u32).filter_map(char::from_u32))`
// states that the char range is exactly the integer range with invalid scalar
// values filtered out. The `.rev()` twin is the same axiom in reverse traversal.

use sugar_ir_symbolic::{atomic_, str_const};
use syn::{Expr, RangeLimits, Type};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{token_key, AssertionFactKind, Desugared, Outcome, Sugar, SugarCtx, Warrant};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::constraint_before(
    "char_range_filter_map_eq",
    &["constraint_assert_macro"],
    crate::sugar::claim::SugarWitnesses::temporal_campaign(
        "S5 adapter family: char range filter_map equality",
    ),
    recognize,
);

pub(crate) const ASSERTION_SURFACE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::with_ordering(
    "char_range_filter_map_eq_assertion_surface",
    SugarRole::AssertionSurface,
    &["assertion_surface_assert_macro"],
    crate::sugar::claim::SugarWitnesses::temporal_campaign(
        "S5 adapter family: assertion-surface char range filter_map equality",
    ),
    recognize,
);

struct CharRangeFilterMapSugar {
    site: String,
}

fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let site = frag.char_range_filter_map_eq_site()?;
    Some(Box::new(CharRangeFilterMapSugar { site }))
}

impl Sugar for CharRangeFilterMapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::Complete(Desugared::Constraints {
            atom: atomic_(
                "stdlib_char_range_filter_map_eq",
                vec![str_const(self.site.clone())],
            ),
            n: 1,
            kind: AssertionFactKind::Warranted,
            warrant: Warrant {
                name: Some(format!(
                    "{}::char-range-filter-map-eq::{}",
                    ctx.scope.local_scope(),
                    compact_warrant_fragment(&self.site)
                )),
            },
        })
    }
}

pub(crate) fn is_char_range_filter_map_eq(expr: &Expr) -> bool {
    let Expr::MethodCall(eq_call) = strip_expr(expr) else {
        return false;
    };
    if eq_call.method != "eq" || eq_call.args.len() != 1 {
        return false;
    }
    let (left, left_rev) = peel_rev(&eq_call.receiver);
    let (right, right_rev) = peel_rev(&eq_call.args[0]);
    if left_rev != right_rev {
        return false;
    }
    let Some((left_start, left_end)) = inclusive_range_parts(left) else {
        return false;
    };
    let Some((right_start, right_end)) = filter_map_from_u32_range_parts(right) else {
        return false;
    };
    cast_to_u32_source(right_start).is_some_and(|start| same_source_expr(start, left_start))
        && cast_to_u32_source(right_end).is_some_and(|end| same_source_expr(end, left_end))
}

fn peel_rev(expr: &Expr) -> (&Expr, bool) {
    let expr = strip_expr(expr);
    let Expr::MethodCall(call) = expr else {
        return (expr, false);
    };
    if call.method == "rev" && call.args.is_empty() {
        (strip_expr(&call.receiver), true)
    } else {
        (expr, false)
    }
}

fn inclusive_range_parts(expr: &Expr) -> Option<(&Expr, &Expr)> {
    let Expr::Range(range) = strip_expr(expr) else {
        return None;
    };
    if !matches!(range.limits, RangeLimits::Closed(_)) {
        return None;
    }
    Some((
        strip_expr(range.start.as_deref()?),
        strip_expr(range.end.as_deref()?),
    ))
}

fn filter_map_from_u32_range_parts(expr: &Expr) -> Option<(&Expr, &Expr)> {
    let Expr::MethodCall(call) = strip_expr(expr) else {
        return None;
    };
    if call.method != "filter_map" || call.args.len() != 1 {
        return None;
    }
    if !is_char_from_u32_path(&call.args[0]) {
        return None;
    }
    inclusive_range_parts(&call.receiver)
}

fn is_char_from_u32_path(expr: &Expr) -> bool {
    let Expr::Path(path) = strip_expr(expr) else {
        return false;
    };
    path.path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == "from_u32")
}

fn cast_to_u32_source(expr: &Expr) -> Option<&Expr> {
    let Expr::Cast(cast) = strip_expr(expr) else {
        return None;
    };
    if !type_is_u32(&cast.ty) {
        return None;
    }
    Some(strip_expr(&cast.expr))
}

fn type_is_u32(ty: &Type) -> bool {
    let Type::Path(path) = ty else {
        return false;
    };
    path.path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == "u32")
}

fn same_source_expr(left: &Expr, right: &Expr) -> bool {
    token_key(strip_expr(left)) == token_key(strip_expr(right))
}

fn strip_expr(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(paren) => strip_expr(&paren.expr),
        Expr::Group(group) => strip_expr(&group.expr),
        _ => expr,
    }
}

fn compact_warrant_fragment(site: &str) -> String {
    site.chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '_' | ':' | '.') {
                ch
            } else {
                '_'
            }
        })
        .collect()
}
