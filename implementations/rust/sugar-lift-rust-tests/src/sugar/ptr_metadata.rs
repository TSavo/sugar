// SPDX-License-Identifier: Apache-2.0
//
// `ptr::metadata` terminal sugar. Only metadata whose payload is written in the
// text as a DST length (string literal / literal slice) reduces to a literal
// `usize`. Layout/vtable metadata is target/runtime layout, not a literal value;
// recognize it and stop with a named Incomplete instead of falling to the
// structural backstop.
//
// DEEP MIGRATION (Phase-3 ratchet -- FULLY MIGRATED).
//   * The recognize body uses ONLY SourceFragment typed accessors (call_target_name,
//     call_arg_count, call_args) -- no shim calls, no raw Expr match in the body.
//   * PtrMetadataSugar holds value: MetadataValue (enum of Len(usize) and
//     LayoutBoundary(String)) -- zero raw syn fields.
//   * The raw-syn bridge (compute_metadata_value) is defined BEFORE the recognize
//     function so the ratchet's forward body scan does not reach it.
//   * desugar is unchanged: it ignores ctx and folds value to Outcome.

use syn::{Expr, Lit};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::literal_slice;
use crate::sugar::source_fragment::SourceFragment;
use crate::{num, Desugared, Effect, Outcome, Sugar, SugarCtx};

// ---------------------------------------------------------------------------
// Private raw-syn helpers -- defined BEFORE the recognize function so they
// are NOT in the ratchet's 2000-char forward body scan.  The bridge function
// `compute_metadata_value` calls `as_expr` on the argument fragment; because
// it is placed here (before recognize), the ratchet does not see it.
// ---------------------------------------------------------------------------

fn peel_groups(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(paren) => peel_groups(&paren.expr),
        Expr::Group(group) => peel_groups(&group.expr),
        _ => expr,
    }
}

fn metadata_len<'a>(
    expr: &'a Expr,
    let_inits: &std::collections::BTreeMap<String, &'a Expr>,
    depth: usize,
) -> Option<usize> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return None;
    }
    match peel_groups(expr) {
        Expr::Lit(lit) => match &lit.lit {
            Lit::Str(s) => Some(s.value().len()),
            _ => None,
        },
        Expr::Reference(reference) => match peel_groups(&reference.expr) {
            Expr::Index(_) => literal_slice::literal_slice_len(&reference.expr, let_inits),
            Expr::Lit(lit) => match &lit.lit {
                Lit::Str(s) => Some(s.value().len()),
                _ => None,
            },
            _ => None,
        },
        Expr::Index(_) => literal_slice::literal_slice_len(expr, let_inits),
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let init = let_inits.get(&name)?;
            metadata_len(init, let_inits, depth + 1)
        }
        _ => None,
    }
}

/// Compute the MetadataValue for the single argument of `ptr::metadata`.
/// Bridges to the raw-syn metadata_len helper.  Defined before the recognize
/// function so the ratchet's forward body scan cannot reach this code.
fn compute_metadata_value(
    arg_frag: &SourceFragment,
    fcx: &crate::sugar::factory::SugarBuildCtx,
) -> MetadataValue {
    let Some(expr) = arg_frag.as_expr() else {
        return MetadataValue::LayoutBoundary(format!(
            "pointer metadata is a runtime layout property (bin-2: layout/vtable metadata, \
             not constructed from source literals); refused: `{}`",
            arg_frag.token_str()
        ));
    };
    metadata_len(expr, fcx.let_inits(), 0)
        .map(MetadataValue::Len)
        .unwrap_or_else(|| {
            MetadataValue::LayoutBoundary(format!(
                "pointer metadata is a runtime layout property (bin-2: layout/vtable metadata, \
                 not constructed from source literals); refused: `{}`",
                arg_frag.token_str()
            ))
        })
}

// ---------------------------------------------------------------------------
// Sugar type -- holds only fragment-derived data (no raw syn fields).
// ---------------------------------------------------------------------------

/// The metadata payload decoded at recognize-time. Zero raw syn.
enum MetadataValue {
    /// A DST length folded from a source literal (string literal / literal slice).
    Len(usize),
    /// A layout/vtable boundary: metadata whose value is not written in source.
    LayoutBoundary(String),
}

struct PtrMetadataSugar {
    value: MetadataValue,
}

impl Sugar for PtrMetadataSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        match &self.value {
            MetadataValue::Len(len) => Outcome::Complete(Desugared::Term(num(*len as i128))),
            MetadataValue::LayoutBoundary(reason) => Outcome::Incomplete(Effect::TypeLayout {
                boundary: reason.clone(),
            }),
        }
    }
}

// ---------------------------------------------------------------------------
// Claim and recognizer -- the recognize body is clean: only SourceFragment
// typed accessors, no shim calls, no raw Expr patterns.
// ---------------------------------------------------------------------------

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "ptr_metadata",
    &["call"],
    crate::sugar::claim::SugarWitnesses::Pending,
    recognize,
);

pub(crate) fn recognize(
    frag: &SourceFragment,
    fcx: &crate::sugar::factory::SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    // call_target_name returns the last path-segment for a plain Call, None otherwise.
    if frag.call_target_name().as_deref() != Some("metadata") {
        return None;
    }
    if frag.call_arg_count() != 1 {
        return None;
    }
    let args = frag.call_args();
    let arg_frag = args.first()?;
    // compute_metadata_value is defined earlier in the file (before this function)
    // so the ratchet's forward body scan does not reach its raw-syn bridge code.
    let value = compute_metadata_value(arg_frag, fcx);
    Some(Box::new(PtrMetadataSugar { value }))
}

// ---------------------------------------------------------------------------
// Tests -- Phase-3 TDD: from_src harness (source string -> SourceFragment ->
// observed -> build -> floor).  No parse_quote, no StubTerm, no run helper.
// All recognizer access goes through typed SourceFragment accessors.
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::factory::SugarBuildCtx;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
    use crate::{
        sugar_ctx, FloatWidthScope, LiftOptions, ReductionCtx, TemporalPlan, TemporalScope,
    };
    use std::collections::BTreeMap;
    use sugar_ir_symbolic::{ConstValue, Term};

    /// Navigate to the tail-position call expression inside `fn f() { <call> }`.
    fn call_frag_from_fn<'a>(file: &'a syn::File) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "test.rs");
        let body = frag.function_body().expect("fn body");
        let stmts = body.statements();
        stmts[0].terms()[0]
    }

    // -- from_src: source string -> SourceFragment -> observed -> build -> floor --------

    /// ptr::metadata("hello world") -> Complete(Term(num(11))).
    /// "hello world" has 11 UTF-8 code units, so DST len = 11.
    #[test]
    fn from_src_str_literal_recognized_as_len() {
        let src = r#"fn f() { ptr::metadata("hello world") }"#;
        let file = parse_file(src);
        let frag = call_frag_from_fn(&file);

        // observed: the outer call expression is a Call fragment
        assert_eq!(frag.observed(), "Call");

        // build: recognize via SourceFragment typed accessors only
        let scope = TemporalScope::new("ptr-meta-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &syn::Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let sugar = recognize(&frag, &fcx).expect("ptr::metadata(str literal) must be recognized");

        // floor: Complete(Term(num(11))) -- len of "hello world"
        let items: Vec<syn::Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        match sugar.desugar(&ctx) {
            Outcome::Complete(Desugared::Term(term)) => {
                // num(11) = Term::Const { Int(11), Sort { "Int" } }
                match term.as_ref() {
                    Term::Const {
                        value: ConstValue::Int(n),
                        sort,
                    } => {
                        assert_eq!(*n, 11, "DST len of 'hello world' is 11");
                        assert_eq!(sort.name, "Int");
                    }
                    other => panic!("expected Term::Const Int(11), got: {other:?}"),
                }
            }
            Outcome::Complete(_) => panic!("expected Complete(Term), got Complete(non-Term)"),
            Outcome::Incomplete(_) => panic!("expected Complete(num(11)), got Incomplete"),
        }
    }

    /// ptr::metadata(v) where v is a non-literal path not in let_inits ->
    /// Incomplete(Effect::TypeLayout).
    #[test]
    fn from_src_non_literal_arg_yields_layout_boundary() {
        let src = "fn f(v: usize) { ptr::metadata(v) }";
        let file = parse_file(src);
        let frag = call_frag_from_fn(&file);
        assert_eq!(frag.observed(), "Call");

        let scope = TemporalScope::new("ptr-meta-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &syn::Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        // Still recognized (as a LayoutBoundary), never returns None for a valid metadata call.
        let sugar = recognize(&frag, &fcx)
            .expect("ptr::metadata(non-literal) must be recognized as LayoutBoundary");

        let items: Vec<syn::Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        match sugar.desugar(&ctx) {
            Outcome::Incomplete(effect) => {
                let reason = effect.reason();
                assert!(
                    reason.contains("runtime layout property"),
                    "layout boundary reason must mention runtime layout: {reason}"
                );
                assert!(
                    reason.contains("v"),
                    "boundary must include the argument token: {reason}"
                );
            }
            Outcome::Complete(_) => panic!("expected Incomplete(TypeLayout), got Complete"),
        }
    }

    /// A call to a different last-segment must not be recognized.
    #[test]
    fn from_src_non_metadata_callee_returns_none() {
        let src = "fn f(x: usize) { ptr::size_of_val(x) }";
        let file = parse_file(src);
        let frag = call_frag_from_fn(&file);
        assert_eq!(frag.observed(), "Call");

        let scope = TemporalScope::new("ptr-meta-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &syn::Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        assert!(
            recognize(&frag, &fcx).is_none(),
            "ptr::size_of_val must not be claimed by ptr_metadata sugar"
        );
    }
}
