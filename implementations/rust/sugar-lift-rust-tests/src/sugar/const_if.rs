// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for a CONSTANT `if cond { .. } else { .. }` expression
// (`Expr::If`) in term position. When the condition and the taken branch
// const-fold to a closed scalar value, the whole conditional collapses to that
// ground value -- the SAME `const_eval` + `const_val_term` path `binop` uses for a
// const arithmetic/comparison expression, so the emitted term is sort-identical to
// the literal the source would otherwise have written.
//
// SOUNDNESS: `const_eval` computes the EXACT compile-time bool of the condition and
// selects exactly the branch Rust evaluates; the untaken branch is dead. A non-const
// condition / taken branch, or an else-less `if`, folds to None here, so this Sugar
// DECLINES (returns `None`) and the conditional stays unresolved -- finite-or-refuse,
// never a fake-fold. No other Term-role recognizer claims `Expr::If`, so this is the
// sole `Expr::If` claimant (no catalog ambiguity).

use std::collections::BTreeMap;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::term_leaf::resolved_term;
use crate::{const_eval, const_val_term, Sugar};
use syn::Expr;
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before("const_if", &["value_if"], recognize);

/// TERM recognizer for a const `Expr::If`. Folds the whole conditional to its taken
/// branch's ground value via `const_eval`; declines (`None`) for any non-`If` expr or
/// any `If` that is not a closed constant.
pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    if !matches!(expr, Expr::If(_)) {
        return None;
    }
    let term = const_eval(expr, &BTreeMap::new()).and_then(|value| const_val_term(&value))?;
    Some(resolved_term(term))
}
