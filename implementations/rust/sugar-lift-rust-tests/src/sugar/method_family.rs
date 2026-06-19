// SPDX-License-Identifier: Apache-2.0
//
// Shared recognition gates for stdlib sequence-method Sugars.

use std::collections::BTreeMap;

use syn::Expr;

use crate::{peel_fold_adaptors, strip_refs_groups};

pub(crate) fn is_literal_sequence_base(expr: &Expr) -> bool {
    matches!(strip_refs_groups(expr), Expr::Array(_) | Expr::Range(_))
}

pub(crate) fn resolves_literal_sequence<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
) -> bool {
    let Some((base, _)) = peel_fold_adaptors(expr, let_inits, 0) else {
        return false;
    };
    is_literal_sequence_base(base)
}

pub(crate) fn resolves_literal_array_sequence<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
) -> bool {
    let Some((base, _)) = peel_fold_adaptors(expr, let_inits, 0) else {
        return false;
    };
    matches!(strip_refs_groups(base), Expr::Array(_))
}
