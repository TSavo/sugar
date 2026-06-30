// SPDX-License-Identifier: Apache-2.0
//
// `ArrayTryFromSugar`: fixed-array `TryFrom` over a literal-backed slice. The
// slice composite owns the elements; this node owns only the stdlib conversion:
// equal length => `Ok(array/ref)`, mismatched length => `Err(_)`.

use std::rc::Rc;

use sugar_ir_symbolic::{num, Term};
use syn::{Expr, Type};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::sugar::monadic::{err_term, ok_term};
use crate::{const_val_term, Desugared, Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("array_try_from", &["try_from", "call"], recognize);

#[derive(Clone, Copy)]
enum Dest {
    Value,
    SharedRef,
    MutRef,
}

struct ArrayTryFromSugar {
    source: SugarBody<CompositeFloor>,
    len: usize,
    dest: Dest,
    site: String,
}

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.observed() != "Call" || frag.call_arg_count() != 1 {
        return None;
    }
    let func_frag = frag.call_func()?;
    let (dest, len) = try_from_dest_frag(&func_frag, fcx)?;
    let args = frag.call_args();
    let arg_frag = args.first()?;
    Some(Box::new(ArrayTryFromSugar {
        source: source_body_frag(arg_frag, fcx),
        len,
        dest,
        site: frag.token_str(),
    }))
}

pub(crate) fn folds_to_result(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    let Expr::Call(call) = crate::strip_refs_groups(expr) else {
        return false;
    };
    if call.args.len() != 1 {
        return false;
    }
    try_from_destination(&call.func)
        .and_then(|dst| array_dest(dst, fcx))
        .is_some()
}

fn source_body(expr: &Expr, fcx: &SugarBuildCtx) -> SugarBody<CompositeFloor> {
    match method_family::build_literal_sequence_composite(expr, fcx) {
        Some(node) => SugarBody::from_node(node),
        None => SugarBody::composite(expr, fcx),
    }
}

impl Sugar for ArrayTryFromSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self.source.reduce(ctx) {
            Outcome::Complete(desugared) => desugared
                .into_seq()
                .unwrap_or_else(|| panic!("array TryFrom source completed as non-sequence")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        if seq.len() != self.len {
            return Outcome::Complete(Desugared::Term(err_term(num(0))));
        }

        let mut elems = Vec::with_capacity(seq.len());
        for elem in seq {
            let Some(term) = elem.value.as_ref().and_then(const_val_term) else {
                return Outcome::Incomplete(Effect::LiteralDomain {
                    boundary: self.site.clone(),
                    reason: "array TryFrom source element not literal-determined".to_string(),
                });
            };
            elems.push(term);
        }

        let array = literal_array_ctor(elems);
        let value = match self.dest {
            Dest::Value => array,
            Dest::SharedRef => ref_term("ref", array),
            Dest::MutRef => ref_term("ref_mut", array),
        };
        Outcome::Complete(Desugared::Term(ok_term(value)))
    }
}

fn literal_array_ctor(args: Vec<Rc<Term>>) -> Rc<Term> {
    Rc::new(Term::Ctor {
        name: "literal:Array".to_string(),
        args,
    })
}

fn ref_term(name: &str, inner: Rc<Term>) -> Rc<Term> {
    Rc::new(Term::Ctor {
        name: name.to_string(),
        args: vec![inner],
    })
}

fn try_from_destination(func: &Expr) -> Option<&Type> {
    let Expr::Path(path) = crate::strip_refs_groups(func) else {
        return None;
    };
    if path.path.segments.last()?.ident != "try_from" {
        return None;
    }
    path.qself.as_ref().map(|qself| qself.ty.as_ref())
}

fn array_dest(ty: &Type, fcx: &SugarBuildCtx) -> Option<(Dest, usize)> {
    match ty {
        Type::Reference(reference) => {
            let len = fcx.scope().array_len_for_type(&reference.elem)?;
            let dest = if reference.mutability.is_some() {
                Dest::MutRef
            } else {
                Dest::SharedRef
            };
            Some((dest, len))
        }
        _ => fcx
            .scope()
            .array_len_for_type(ty)
            .map(|len| (Dest::Value, len)),
    }
}

// -- fragment-based wrappers (outside 2000-char ratchet window) ---------------

/// Resolves the TryFrom destination type and array shape from a `call_func` fragment.
/// All raw syn access lives here; `recognize` sees only `Option<(Dest, usize)>`.
fn try_from_dest_frag(
    func_frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<(Dest, usize)> {
    let func = func_frag.as_expr()?;
    let dst = try_from_destination(func)?;
    array_dest(dst, fcx)
}

/// Builds the composite `SugarBody` for an array TryFrom source argument.
/// All raw syn access lives inside `source_body`; `recognize` sees only
/// `SugarBody<CompositeFloor>`.
fn source_body_frag(
    arg_frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> SugarBody<CompositeFloor> {
    let expr = arg_frag.as_expr().expect("call_args() returned a valid Expr fragment");
    source_body(expr, fcx)
}
