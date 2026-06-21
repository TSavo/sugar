// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Cast` (`x as T`): an inferred target (`as _`) is
// compiler type inference and therefore transparent; raw-pointer target casts are
// refused as provenance/address boundaries; a shared `dyn Any` cast or a scalar cast
// -> `cast:<T>` ctor over the child; any other cast -> reasoned Hit.

use std::rc::Rc;

use sugar_ir_symbolic::{ConstValue, Sort, Term};

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::term_leaf::reasoned_hit;
use crate::{
    cast_const_fold_value, const_fold_int_term, is_shared_dyn_any_type, scalar_cast_type_key,
    str_const, token_key, type_key, u128_term, Desugared, Effect, Outcome, Sugar, SugarCtx,
    UnsupportedTermCause,
};
use syn::{Expr, Type};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("cast_term", recognize);

/// TERM recognizer for `Expr::Cast`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Cast(cast) = expr else {
        return None;
    };
    if matches!(cast.ty.as_ref(), Type::Infer(_)) {
        return Some(build_term(&cast.expr, fcx));
    }
    // `&array as &[_]` / `&vec as &[T]`: an UNSIZING coercion to a slice reference is
    // VALUE-PRESERVING -- the slice views the SAME elements as its source, so the cast
    // carries no value of its own (exactly like the `as _` inferred-target arm). Desugar
    // transparently to the inner reference's term. This unblocks the dominant cast_term
    // dark shape (`Clamp(r).get(&slice as &[_]) == other.get(&slice as &[_])`): with the
    // cast transparent, both EUF call-arguments coalesce instead of backstopping. The
    // inner reference's own soundness still applies (a `&mut <place>` source propagates
    // its refusal); this arm only strips the unsizing coercion.
    if is_slice_reference_cast(cast.ty.as_ref()) {
        return Some(build_term(&cast.expr, fcx));
    }
    if matches!(cast.ty.as_ref(), Type::Ptr(_)) {
        let effect =
            Effect::unsupported_term(&token_key(expr), UnsupportedTermCause::RawPointerCast);
        return Some(reasoned_hit(effect.reason()));
    }
    if is_shared_dyn_any_type(&cast.ty) {
        return Some(Box::new(CtorSugar::new(
            format!("cast:{}", type_key(&cast.ty)),
            vec![build_term(&cast.expr, fcx)],
        )));
    }
    if let Some(cast_type) = scalar_cast_type_key(&cast.ty) {
        return Some(Box::new(CastSugar {
            cast_type: cast_type.to_string(),
            inner: build_term(&cast.expr, fcx),
        }));
    }
    Some(reasoned_hit(format!(
        "unsupported term `{}`",
        token_key(expr)
    )))
}

/// `&[_]` / `&[T]` / `&mut [_]`: a reference to a SLICE. A cast to such a type is an
/// unsizing coercion (`&[T; N] as &[T]`, `&Vec<T> as &[T]`) that preserves the elements,
/// so `cast_term` treats it transparently. (The element type is irrelevant -- the value
/// is the source's elements either way.)
fn is_slice_reference_cast(ty: &Type) -> bool {
    matches!(ty, Type::Reference(reference) if matches!(reference.elem.as_ref(), Type::Slice(_)))
}

struct CastSugar {
    cast_type: String,
    inner: Box<dyn Sugar>,
}

impl Sugar for CastSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let inner = match self.inner.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        if let Some(term) = fold_grounded_scalar_cast(&inner, &self.cast_type) {
            return Outcome::Dug(Desugared::Term(term));
        }
        Outcome::Dug(Desugared::Term(Rc::new(Term::Ctor {
            name: format!("cast:{}", self.cast_type),
            args: vec![inner],
        })))
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
