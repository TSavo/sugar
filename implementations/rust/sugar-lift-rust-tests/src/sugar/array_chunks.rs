// SPDX-License-Identifier: Apache-2.0
//
// Composite recognizer for iterator `array_chunks::<N>()`.
//
// `array_chunks` is not a terminal; it is a sequence adaptor. A literal-backed receiver
// yields full N-element arrays and drops the remainder, matching Rust iterator semantics.
// Runtime/effectful receivers are owned by their receiver sugar and bubble unchanged.

use quote::quote;
use syn::{Expr, GenericArgument};

use crate::sugar::factory::{CompositeFloor, FloorRead, SugarBody, SugarBuildCtx};
use crate::{const_int, ConstVal, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("array_chunks", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "array_chunks" || !call.args.is_empty() {
        return None;
    }
    let n = method_const_usize(call)?;
    if n == 0 {
        return None;
    }
    Some(Box::new(ArrayChunksSugar {
        receiver: SugarBody::composite(&call.receiver, fcx),
        n,
    }))
}

struct ArrayChunksSugar {
    receiver: SugarBody<CompositeFloor>,
    n: usize,
}

impl Sugar for ArrayChunksSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self
            .receiver
            .reduce_sequence(ctx, "array_chunks receiver sequence")
        {
            FloorRead::Complete(seq) => seq,
            FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let chunks = array_chunks_sequence(&seq, self.n)
            .unwrap_or_else(|| panic!("array_chunks did not materialize array floors"));
        Outcome::Complete(Desugared::Seq(chunks))
    }
}

fn array_chunks_sequence(seq: &[DesugaredElem], n: usize) -> Option<Vec<DesugaredElem>> {
    if n == 0 {
        return None;
    }
    let mut out = Vec::new();
    for chunk in seq.chunks_exact(n) {
        out.push(array_elem(chunk)?);
    }
    Some(out)
}

fn array_elem(elems: &[DesugaredElem]) -> Option<DesugaredElem> {
    let exprs = elems
        .iter()
        .map(|elem| elem.expr.clone())
        .collect::<Vec<_>>();
    let expr = syn::parse2(quote!([#(#exprs),*])).ok()?;
    let value = elems
        .iter()
        .map(|elem| elem.value.clone())
        .collect::<Option<Vec<ConstVal>>>()
        .map(ConstVal::Array);
    Some(DesugaredElem { expr, value })
}

fn method_const_usize(call: &syn::ExprMethodCall) -> Option<usize> {
    let args = call.turbofish.as_ref()?;
    if args.args.len() != 1 {
        return None;
    }
    let GenericArgument::Const(expr) = args.args.first()? else {
        return None;
    };
    usize::try_from(const_int(expr)?).ok()
}
