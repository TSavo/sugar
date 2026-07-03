// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Reference`. Shared and mutable references are
// capability constructors: `&x` -> `ref(x)`, `&mut x` -> `ref_mut(x)`.
// Construction itself is inert; consumers own any temporal effect when the
// capability is written through or escapes.
//
// THE `ref`/`ref_mut` CTORS ARE STRUCTURAL: they keep a borrowed value distinct as a
// term so that an EUF call-result key (`r.contains(&i)` -> `..c:ref(i)`) and a pointer-
// identity predicate (`ptr::eq(&a, &b)`) stay sound. They are deliberately UNINTERPRETED.
// The value-equality READING of a shared borrow (`&a == &b` <=> `a == b`, Rust's
// `PartialEq for &T`) is recovered NOT here but at the relation surface: the single
// assertion-surface relation builder (`assertion_entry_from_relation` in `lib.rs`) strips
// a redundant outer shared-`ref` from each operand via `strip_shared_ref`. That keeps the
// EUF call-result arg keys and `ptr::eq` pointer-identity terms intact (a `ref` nested
// inside a call ctor is NOT a relational operand) while letting `&place == value` warrant
// the pointee instead of an uninterpreted `ref(..)` a bad twin could mis-satisfy.

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{SugarBody, SugarBuildCtx};
use crate::sugar::source_fragment::SourceFragment;
use crate::Sugar;

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::fallback_term(
    "reference_term",
    crate::sugar::claim::SugarWitnesses::Pending,
    recognize,
);

/// TERM recognizer for `Expr::Reference`.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let inner = frag.reference_inner()?;
    let ctor = if frag.reference_is_mutable() {
        "ref_mut"
    } else {
        "ref"
    };
    Some(Box::new(CtorSugar::new(
        ctor,
        vec![SugarBody::term_frag(&inner, fcx)],
    )))
}

#[cfg(test)]
mod tests {
    use std::rc::Rc;

    use super::*;
    use crate::{
        sugar_ctx, Desugared, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, TemporalPlan,
        TemporalScope,
    };
    use sugar_ir_symbolic::Term;
    use syn::{Expr, Item};

    /// from_src: source -> SourceFragment -> accessor gate -> build -> floor.
    /// Exercises `reference_inner` / `reference_is_mutable` directly; no
    /// parse_quote! / StubTerm / run().
    #[test]
    fn from_src_reference_accessors() {
        // shared ref
        let shared: Expr = syn::parse_str("&x").expect("parse");
        let frag_shared = SourceFragment::expr(&shared, "<src>");
        assert!(
            frag_shared.reference_inner().is_some(),
            "shared ref: inner is Some"
        );
        assert!(
            !frag_shared.reference_is_mutable(),
            "shared ref: not mutable"
        );

        // mutable ref
        let mutable: Expr = syn::parse_str("&mut y").expect("parse");
        let frag_mut = SourceFragment::expr(&mutable, "<src>");
        assert!(
            frag_mut.reference_inner().is_some(),
            "mut ref: inner is Some"
        );
        assert!(frag_mut.reference_is_mutable(), "mut ref: is mutable");

        // non-reference: accessor returns None / false
        let other: Expr = syn::parse_str("x + 1").expect("parse");
        let frag_other = SourceFragment::expr(&other, "<src>");
        assert!(
            frag_other.reference_inner().is_none(),
            "non-ref: inner is None"
        );
        assert!(!frag_other.reference_is_mutable(), "non-ref: not mutable");
    }

    fn reduce(src: &str) -> Rc<Term> {
        let expr: Expr = syn::parse_str(src).expect("parse reference expr");
        let scope = TemporalScope::new("reference-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = {
            let _frag = SourceFragment::expr(&expr, "<src>");
            recognize(&_frag, &fcx)
        }
        .expect("reference_term recognizes");
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        let Outcome::Complete(Desugared::Term(term)) = node.desugar(&ctx) else {
            panic!("reference sugar should complete as an inert reference term")
        };
        term
    }

    #[test]
    fn shared_reference_constructs_ref_floor() {
        let term = reduce("&x");
        let Term::Ctor { name, args } = term.as_ref() else {
            panic!("expected ref ctor, got {term:?}");
        };
        assert_eq!(name, "ref");
        assert_eq!(args.len(), 1);
        assert!(matches!(args[0].as_ref(), Term::Var { name } if name == "x"));
    }

    #[test]
    fn mutable_reference_constructs_ref_mut_floor() {
        let term = reduce("&mut x");
        let Term::Ctor { name, args } = term.as_ref() else {
            panic!("expected ref_mut ctor, got {term:?}");
        };
        assert_eq!(name, "ref_mut");
        assert_eq!(args.len(), 1);
        assert!(matches!(args[0].as_ref(), Term::Var { name } if name == "x"));
    }
}
