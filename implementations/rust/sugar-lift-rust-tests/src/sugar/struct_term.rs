// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Struct`: a constructor `struct:<path>` with sorted
// `field:<name>` subctors over the field-value children. A `..rest` struct literal is
// not fully pinned from the literal -> reasoned Incomplete. Byte-identical to the
// `Expr::Struct` arm of the old fat factory.

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::term_leaf::reasoned_incomplete;
use crate::{path_to_variant_string, token_key, Sugar};
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("struct_term", recognize);

/// TERM recognizer for `Expr::Struct`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Struct(s) = expr else {
        return None;
    };
    if s.rest.is_some() {
        return Some(reasoned_incomplete(format!(
            "struct literal with `..rest` is not fully pinned from the literal: `{}`",
            token_key(expr)
        )));
    }
    let mut fields: Vec<(String, Box<dyn Sugar>)> = Vec::new();
    for fv in &s.fields {
        let fname = match &fv.member {
            syn::Member::Named(id) => id.to_string(),
            syn::Member::Unnamed(idx) => idx.index.to_string(),
        };
        fields.push((fname, build_term(&fv.expr, fcx)));
    }
    fields.sort_by(|a, b| a.0.cmp(&b.0));
    let field_ctors: Vec<Box<dyn Sugar>> = fields
        .into_iter()
        .map(|(fname, child)| {
            Box::new(CtorSugar::new(format!("field:{fname}"), vec![child])) as Box<dyn Sugar>
        })
        .collect();
    Some(Box::new(CtorSugar::new(
        format!("struct:{}", path_to_variant_string(&s.path)),
        field_ctors,
    )))
}
