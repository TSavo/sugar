// SPDX-License-Identifier: Apache-2.0
//
// `from_bool`: `<IntT>::from(<bool literal>)` / `IntT::from(<bool literal>)` for a
// primitive INTEGER target type folds to the std `From<bool>` value -- `true -> 1`,
// `false -> 0`.
//
// The same sugar also owns literal numeric `From` into primitive integer targets.
// `From` is infallible but not universal: we require a spelled primitive source
// integer kind (`u64::MAX`, `255u8`, `<i64>::MIN`) and only fold conversions the
// standard library actually implements. The desugar arm resolves the argument lazily
// so the complete sort-correct value can be emitted as a concrete int/u128 floor.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{num, Term};
use syn::{Expr, ExprCall, Lit, PathArguments, Type};

use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::int_literal::{exact_int_source, from_impl_exists, primitive_int_kind, IntKind};
use crate::{expr_head_key, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("from_bool", recognize);

pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Call(call) = expr else {
        return None;
    };
    if call.args.len() != 1 {
        return None;
    }
    let dst = primitive_int_from_kind(&call.func)?;
    Some(Box::new(FromPrimitiveSugar {
        call: call.clone(),
        dst,
    }))
}

struct FromPrimitiveSugar {
    call: ExprCall,
    dst: IntKind,
}

impl Sugar for FromPrimitiveSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(term) = from_bool_term(&self.call) {
            return Outcome::Dug(Desugared::Term(term));
        }

        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        if let Some(source) = exact_int_source(&self.call.args[0], Some(&fcx)) {
            if let Some(src_kind) = source.kind {
                if from_impl_exists(src_kind, self.dst) {
                    if let Some(term) = source.value.term_for_kind(self.dst) {
                        return Outcome::Dug(Desugared::Term(term));
                    }
                }
            }
            return self.fallback_call(ctx, &fcx);
        }

        if self.dst.bits == 128 {
            return Outcome::Hit(Effect::Unsupported {
                reason: format!("runtime {} operand, not literal-determined", self.dst.name),
            });
        }
        self.fallback_call(ctx, &fcx)
    }
}

impl FromPrimitiveSugar {
    fn fallback_call(&self, ctx: &SugarCtx, fcx: &SugarBuildCtx) -> Outcome {
        let mut args: Vec<Rc<Term>> = Vec::new();
        for arg in &self.call.args {
            let term = match build_term(arg, fcx).desugar(ctx) {
                Outcome::Dug(d) => match d.into_term() {
                    Some(term) => term,
                    None => return Outcome::from_opt(None),
                },
                Outcome::Hit(effect) => return Outcome::Hit(effect),
            };
            args.push(term);
        }
        Outcome::Dug(Desugared::Term(Rc::new(Term::Ctor {
            name: format!("call:{}", expr_head_key(&self.call.func)),
            args,
        })))
    }
}

fn from_bool_term(call: &ExprCall) -> Option<Rc<Term>> {
    let Expr::Lit(lit) = &call.args[0] else {
        return None;
    };
    let Lit::Bool(b) = &lit.lit else {
        return None;
    };
    Some(num(if b.value { 1 } else { 0 }))
}

/// `<IntT>::from` (qself) or `IntT::from` (two-segment path) where `IntT` is a known
/// primitive integer type. Anything else (a user type, a float, `char`, a longer
/// path) is NOT a std primitive-integer `From` and is declined.
fn primitive_int_from_kind(func: &Expr) -> Option<IntKind> {
    let Expr::Path(path) = func else {
        return None;
    };
    let Some(last) = path.path.segments.last() else {
        return None;
    };
    if last.ident != "from" || !matches!(last.arguments, PathArguments::None) {
        return None;
    }
    if let Some(qself) = &path.qself {
        return primitive_int_type_kind(&qself.ty);
    }
    if path.path.segments.len() == 2
        && matches!(path.path.segments[0].arguments, PathArguments::None)
    {
        primitive_int_kind(&path.path.segments[0].ident.to_string())
    } else {
        None
    }
}

fn primitive_int_type_kind(ty: &Type) -> Option<IntKind> {
    let Type::Path(path) = ty else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    match path.path.segments.last() {
        Some(seg) if matches!(seg.arguments, PathArguments::None) => {
            primitive_int_kind(&seg.ident.to_string())
        }
        _ => None,
    }
}
