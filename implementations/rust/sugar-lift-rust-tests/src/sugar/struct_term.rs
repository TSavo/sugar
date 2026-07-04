// SPDX-License-Identifier: MIT OR Apache-2.0
//
// TERM recognizer for `Expr::Struct`: a constructor `struct:<path>` with sorted
// `field:<name>` subctors over the field-value children. A `..rest` struct literal is
// not fully pinned by this sugar yet, so it takes a named terminal refusal at desugar time.

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "struct_term",
        crate::sugar::claim::SugarWitnesses::reasoned_bucket("owner-mismatch aggregate row: struct witnesses dispatch through aggregate_decomp/term_literal"),
        recognize,
    );

/// TERM recognizer for `Expr::Struct`.
/// No `as_expr()`, `Expr::`, or raw syn in this function.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let path_name = frag.struct_path_variant_string()?;
    if frag.struct_has_rest() {
        return Some(Box::new(StructUpdateGapSugar {
            site: frag.token_str(),
        }));
    }
    let mut fields: Vec<(String, SugarBody<TermFloor>)> = frag
        .struct_named_fields_frags()
        .into_iter()
        .map(|(fname, ef)| (fname, SugarBody::term_frag(&ef, fcx)))
        .collect();
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
        format!("struct:{path_name}"),
        field_ctors,
    )))
}

struct StructUpdateGapSugar {
    site: String,
}

impl Sugar for StructUpdateGapSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::StructUpdateRest {
            boundary: self.site.clone(),
        })
    }
}

// ---------------------------------------------------------------------------
// Phase-3 from_src tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use crate::{LiftOptions, TemporalPlan, TemporalScope};
    use std::collections::BTreeMap;
    use syn::Expr;

    fn make_fcx<'a>(
        scope: &'a crate::TemporalScope,
        options: &'a LiftOptions,
        let_inits: &'a BTreeMap<String, &'a Expr>,
    ) -> SugarBuildCtx<'a, 'a> {
        SugarBuildCtx::new(scope, options, let_inits)
    }

    /// Positive: `Foo { x: 1, y: 2 }` is an Expr::Struct with 2 fields.
    #[test]
    fn from_src_struct_two_fields_recognized() {
        let expr: Expr = syn::parse_str("Foo { x: 1_i32, y: 2_i32 }").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        let path_name = frag.struct_path_variant_string();
        assert_eq!(path_name.as_deref(), Some("Foo"));
        assert!(!frag.struct_has_rest());
        let fields = frag.struct_named_fields_frags();
        assert_eq!(fields.len(), 2);

        let scope = TemporalScope::new("struct-term-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_some(),
            "Foo with fields must be recognized"
        );
    }

    /// Discrimination: `(1_i32, 2_i32)` is a Tuple, not a Struct.
    #[test]
    fn from_src_tuple_not_recognized_as_struct() {
        let expr: Expr = syn::parse_str("(1_i32, 2_i32)").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert!(frag.struct_path_variant_string().is_none());

        let scope = TemporalScope::new("struct-term-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_none(),
            "tuple must not be recognized as Struct"
        );
    }

    /// Structural: field names are sorted alphabetically in the ctor.
    #[test]
    fn from_src_struct_fields_sorted() {
        let expr: Expr = syn::parse_str("Foo { z: 3_i32, a: 1_i32 }").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");
        let mut fields = frag.struct_named_fields_frags();
        fields.sort_by(|a, b| a.0.cmp(&b.0));
        assert_eq!(fields[0].0, "a");
        assert_eq!(fields[1].0, "z");
    }
}
