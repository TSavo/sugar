// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Struct`: a constructor `struct:<path>` with sorted
// `field:<name>` subctors over the field-value children. A `..rest` struct literal is
// not fully pinned by this sugar yet, so it takes the direct gap path at desugar time.

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::{path_to_variant_string, token_key, Outcome, Sugar, SugarCtx};
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("struct_term", recognize);

/// TERM recognizer for `Expr::Struct`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Struct(s) = expr else {
        return None;
    };
    if s.rest.is_some() {
        return Some(Box::new(StructUpdateGapSugar {
            site: token_key(expr),
        }));
    }
    let mut fields: Vec<(String, SugarBody<TermFloor>)> = Vec::new();
    for fv in &s.fields {
        let fname = match &fv.member {
            syn::Member::Named(id) => id.to_string(),
            syn::Member::Unnamed(idx) => idx.index.to_string(),
        };
        fields.push((fname, SugarBody::term(&fv.expr, fcx)));
    }
    fields.sort_by(|a, b| a.0.cmp(&b.0));
    let field_ctors: Vec<SugarBody<TermFloor>> = fields
        .into_iter()
        .map(|(fname, child)| {
            SugarBody::from_node(Box::new(CtorSugar::new(
                format!("field:{fname}"),
                vec![child],
            )))
        })
        .collect();
    Some(Box::new(CtorSugar::new(
        format!("struct:{}", path_to_variant_string(&s.path)),
        field_ctors,
    )))
}

struct StructUpdateGapSugar {
    site: String,
}

impl Sugar for StructUpdateGapSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        panic!(
            "struct literal with `..rest` is not fully pinned from the literal: `{}`",
            self.site
        );
    }
}
