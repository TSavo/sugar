// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Cast` (`x as T`): an inferred target (`as _`) is
// compiler type inference and therefore transparent; raw-pointer target casts are
// refused as provenance/address boundaries; a shared `dyn Any` cast or a scalar cast
// -> `cast:<T>` ctor over the child; any other cast -> reasoned Incomplete.

use std::rc::Rc;

use sugar_ir_symbolic::{ConstValue, Sort, Term};

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{build_term_frag, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    cast_const_fold_value, const_fold_int_term, str_const, u128_term, Desugared, Effect, Outcome,
    Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "cast_term",
        crate::sugar::claim::SugarWitnesses::Pending,
        recognize,
    );

/// TERM recognizer for `Expr::Cast`.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.observed() != "Cast" {
        return None;
    }
    // `as _`: inferred target is transparent -- delegate to inner expression.
    if frag.cast_is_infer() {
        let inner = frag.cast_inner_frag()?;
        return Some(build_term_frag(&inner, fcx));
    }
    // `&array as &[_]` / `&vec as &[T]`: an UNSIZING coercion to a slice reference is
    // VALUE-PRESERVING -- the slice views the SAME elements as its source, so the cast
    // carries no value of its own (exactly like the `as _` inferred-target arm). Desugar
    // transparently to the inner reference's term. This unblocks the dominant cast_term
    // dark shape (`Clamp(r).get(&slice as &[_]) == other.get(&slice as &[_])`): with the
    // cast transparent, both EUF call-arguments coalesce instead of backstopping. The
    // inner reference's own soundness still applies (a `&mut <place>` source propagates
    // its refusal); this arm only strips the unsizing coercion.
    if frag.cast_is_slice_ref() {
        let inner = frag.cast_inner_frag()?;
        return Some(build_term_frag(&inner, fcx));
    }
    if frag.cast_is_raw_ptr() {
        return Some(Box::new(RepresentationCastSugar {
            boundary: frag.token_str(),
            kind: "a raw pointer cast".to_string(),
        }));
    }
    if frag.cast_is_shared_dyn_any() {
        let inner = frag.cast_inner_frag()?;
        return Some(Box::new(CtorSugar::new(
            format!("cast:{}", frag.cast_full_type_key_str()),
            vec![SugarBody::term_frag(&inner, fcx)],
        )));
    }
    if let Some(cast_type) = frag.cast_scalar_type_key() {
        let inner = frag.cast_inner_frag()?;
        return Some(Box::new(CastSugar {
            cast_type: cast_type.to_string(),
            inner: SugarBody::term_frag(&inner, fcx),
        }));
    }
    Some(Box::new(RepresentationCastSugar {
        boundary: frag.token_str(),
        kind: "a non-scalar representation cast".to_string(),
    }))
}

struct CastSugar {
    cast_type: String,
    inner: SugarBody<TermFloor>,
}

impl Sugar for CastSugar {
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        let inner = match self.inner.reduce(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(term) => term,
                None => unreachable!("typed cast `{}` child reduced to non-term", self.cast_type),
            },
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        if let Some(term) = fold_grounded_scalar_cast(&inner, &self.cast_type) {
            return Outcome::Complete(Desugared::Term(term));
        }
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: format!("cast:{}", self.cast_type),
            args: vec![inner],
        })))
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

struct RepresentationCastSugar {
    boundary: String,
    kind: String,
}

impl Sugar for RepresentationCastSugar {
    fn reduce(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::RepresentationCast {
            boundary: self.boundary.clone(),
            kind: self.kind.clone(),
        })
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

fn fold_grounded_scalar_cast(term: &Rc<Term>, cast_type: &str) -> Option<Rc<Term>> {
    if cast_type == "char" {
        let codepoint = u32::try_from(const_fold_int_term(term)?).ok()?;
        let ch = char::from_u32(codepoint)?;
        return Some(str_const(ch.to_string()));
    }
    let value = const_fold_int_term(term).or_else(|| char_literal_codepoint(term))?;
    let folded = cast_const_fold_value(value, cast_type)?;
    Some(scalar_cast_const_term(folded, cast_type))
}

fn char_literal_codepoint(term: &Rc<Term>) -> Option<i128> {
    let Term::Const {
        value: ConstValue::String(value),
        sort,
    } = term.as_ref()
    else {
        return None;
    };
    if sort.name != "String" {
        return None;
    }
    let mut chars = value.chars();
    let ch = chars.next()?;
    chars.next().is_none().then_some(i128::from(u32::from(ch)))
}

fn scalar_cast_const_term(value: i128, cast_type: &str) -> Rc<Term> {
    if cast_type == "u128" {
        return u128_term(value as u128);
    }
    Rc::new(Term::Const {
        value: ConstValue::Int(value),
        sort: Sort {
            name: cast_type.to_string(),
        },
    })
}

#[cfg(test)]
mod tests {
    use crate::sugar::source_fragment::{FragNode, SourceFragment};
    use syn::Expr;

    fn e(src: &str) -> Expr {
        syn::parse_str(src).expect("parse expr")
    }

    // --- positive: cast to scalar type ---------------------------------------

    #[test]
    fn from_src_scalar_cast_observed_and_inner_frag() {
        // positive: `x as u32` -> observed "Cast", cast_scalar_type_key "u32",
        // cast_inner_frag observed "Name"
        let expr = e("x as u32");
        let frag = SourceFragment::from_node(FragNode::Expr(&expr), "<test>");
        assert_eq!(frag.observed(), "Cast");
        assert!(frag.cast_is_infer() == false, "u32 cast must not be infer");
        assert!(
            frag.cast_is_slice_ref() == false,
            "u32 cast is not a slice ref"
        );
        assert!(frag.cast_is_raw_ptr() == false, "u32 cast is not a raw ptr");
        assert!(
            frag.cast_is_shared_dyn_any() == false,
            "u32 cast is not dyn Any"
        );
        assert_eq!(
            frag.cast_scalar_type_key(),
            Some("u32"),
            "scalar_type_key must be u32"
        );
        let inner = frag.cast_inner_frag().expect("inner must be Some for Cast");
        assert_eq!(
            inner.observed(),
            "Name",
            "inner of `x as u32` is a path (Name)"
        );
    }

    // --- discrimination: non-Cast returns None from cast_inner_frag ----------

    #[test]
    fn from_src_non_cast_cast_inner_frag_returns_none() {
        // discrimination: a BinOp fragment must return None from cast_inner_frag
        let expr = e("1 + 2");
        let frag = SourceFragment::from_node(FragNode::Expr(&expr), "<test>");
        assert!(
            frag.cast_inner_frag().is_none(),
            "BinOp must not have cast_inner_frag"
        );
        assert!(
            frag.cast_scalar_type_key().is_none(),
            "BinOp must not have a scalar cast key"
        );
    }

    // --- structural: infer cast, slice-ref cast, raw-ptr cast flags ----------

    #[test]
    fn from_src_infer_cast_is_infer_true() {
        // structural: `x as _` -> cast_is_infer() == true, cast_is_slice_ref() == false
        let expr = e("x as _");
        let frag = SourceFragment::from_node(FragNode::Expr(&expr), "<test>");
        assert_eq!(frag.observed(), "Cast");
        assert!(frag.cast_is_infer(), "x as _ must be cast_is_infer");
        assert!(
            !frag.cast_is_slice_ref(),
            "x as _ must not be cast_is_slice_ref"
        );
        assert!(
            !frag.cast_is_raw_ptr(),
            "x as _ must not be cast_is_raw_ptr"
        );
        assert!(frag.cast_inner_frag().is_some(), "inner must be present");
    }
}
