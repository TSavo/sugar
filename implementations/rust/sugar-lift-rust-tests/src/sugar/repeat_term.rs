// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Repeat` (`[elem; N]`) in TERM position: a literal count
// expands to the N-fold `literal_aggregate_term` "Array"; a non-literal count is the
// `ArrayRepeatSugar` refuse-shape (`Effect::ArrayRepeat`). This is the TERM-position
// node — DISTINCT from the COMPOSITE-registry `Expr::Repeat` (which boxes
// `decompose_array_repeat` directly as the refuse-shape). Byte-identical to the
// `Expr::Repeat` arm of the old fat factory.

use crate::sugar::array_repeat::decompose_array_repeat;
use crate::sugar::factory::FactoryCtx;
use crate::sugar::term_leaf::{reasoned_hit, resolved_term};
use crate::{
    literal_aggregate_term_in_scope, repeat_count_literal, token_key, Effect, Outcome, Sugar,
};
use syn::Expr;

/// TERM recognizer for `Expr::Repeat`.
pub(crate) fn recognize(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Repeat(repeat) = expr else {
        return None;
    };
    let scope = fcx.scope;
    let Some(count) = repeat_count_literal(&repeat.len) else {
        return Some(match decompose_array_repeat(expr) {
            Some(node) => match node.desugar_ctx_free() {
                Outcome::Hit(effect @ Effect::ArrayRepeat { .. }) => reasoned_hit(effect.reason()),
                _ => reasoned_hit(format!("unsupported term `{}`", token_key(expr))),
            },
            None => reasoned_hit(format!("unsupported term `{}`", token_key(expr))),
        });
    };
    const MAX_REPEAT: usize = 4096;
    if count > MAX_REPEAT {
        return Some(reasoned_hit(format!(
            "array-repeat length {count} exceeds the {MAX_REPEAT}-element \
             expansion bound; refused by name: `{}`",
            token_key(expr)
        )));
    }
    let elem_refs = std::iter::repeat(&*repeat.expr).take(count);
    Some(match literal_aggregate_term_in_scope("Array", elem_refs, expr, scope) {
        Ok(term) => resolved_term(term),
        Err(reason) => reasoned_hit(reason),
    })
}
