// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Literal slice chunk/window adaptors. These are composite-only wrappers used by the
// sequence-method peel path: a literal slice split into `chunks`, `rchunks`, exact
// chunks, or `windows` is still a finite text-determined sequence. Each yielded
// sub-slice is represented as an array expression plus a tuple ConstVal payload so
// closure sugar can evaluate `chunk.iter().sum()` without inventing runtime state.

use quote::quote;
use syn::Expr;

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    strip_refs_groups, ConstVal, Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "slice_chunk_window",
        crate::sugar::claim::SugarWitnesses::temporal_campaign(
            "S5 adapter family: slice chunks/windows",
        ),
        recognize_composite,
    );

pub(crate) const TERM_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "slice_chunk_window_runtime",
        &["method"],
        crate::sugar::claim::SugarWitnesses::reasoned_bucket(
            "runtime slice chunks/windows have no literal sequence floor",
        ),
        recognize_term,
    );

#[derive(Clone, Copy)]
pub(crate) enum SliceChunkWindowKind {
    Chunks,
    ChunksExact,
    RChunks,
    RChunksExact,
    Windows,
}

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.args.len() != 1 {
        return None;
    }
    let n: usize = crate::const_int(&call.args[0])?.try_into().ok()?;
    if n == 0 {
        return None;
    }
    let kind = match call.method.to_string().as_str() {
        "chunks" | "chunks_mut" => SliceChunkWindowKind::Chunks,
        "chunks_exact" | "chunks_exact_mut" => SliceChunkWindowKind::ChunksExact,
        "rchunks" | "rchunks_mut" => SliceChunkWindowKind::RChunks,
        "rchunks_exact" | "rchunks_exact_mut" => SliceChunkWindowKind::RChunksExact,
        "windows" => SliceChunkWindowKind::Windows,
        _ => return None,
    };
    Some(Box::new(SliceChunkWindowSugar {
        inner: SugarBody::composite(&call.receiver, fcx),
        kind,
        n,
    }))
}

pub(crate) fn recognize_term(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    if !runtime_chunk_window_source_expr(expr, fcx, 0) {
        return None;
    }
    Some(Box::new(RuntimeChunkSourceSugar {
        boundary: frag.token_str(),
    }))
}

pub(crate) struct SliceChunkWindowSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) kind: SliceChunkWindowKind,
    pub(crate) n: usize,
}

struct RuntimeChunkSourceSugar {
    boundary: String,
}

impl Sugar for RuntimeChunkSourceSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::RuntimeChunkSource {
            boundary: self.boundary.clone(),
        })
    }
}

impl Sugar for SliceChunkWindowSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if self.n == 0 {
            slice_chunk_window_gap("zero chunk/window size should be rejected at construction");
        }
        let seq = match self.inner.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_seq()
                .unwrap_or_else(|| slice_chunk_window_gap("receiver reduced to non-sequence")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let out = chunk_window_sequence(&seq, self.kind, self.n)
            .unwrap_or_else(|| slice_chunk_window_gap("chunk/window output did not materialize"));
        Outcome::Complete(Desugared::Seq(out))
    }
}

fn chunk_window_sequence(
    seq: &[DesugaredElem],
    kind: SliceChunkWindowKind,
    n: usize,
) -> Option<Vec<DesugaredElem>> {
    let mut out = Vec::new();
    match kind {
        SliceChunkWindowKind::Chunks => {
            for start in (0..seq.len()).step_by(n) {
                let end = (start + n).min(seq.len());
                out.push(subslice_elem(&seq[start..end])?);
            }
        }
        SliceChunkWindowKind::ChunksExact => {
            for start in (0..seq.len()).step_by(n) {
                let end = start + n;
                if end > seq.len() {
                    break;
                }
                out.push(subslice_elem(&seq[start..end])?);
            }
        }
        SliceChunkWindowKind::RChunks => {
            let mut end = seq.len();
            while end > 0 {
                let start = end.saturating_sub(n);
                out.push(subslice_elem(&seq[start..end])?);
                end = start;
            }
        }
        SliceChunkWindowKind::RChunksExact => {
            let mut end = seq.len();
            while end >= n && n != 0 {
                let start = end - n;
                out.push(subslice_elem(&seq[start..end])?);
                end = start;
            }
        }
        SliceChunkWindowKind::Windows => {
            if n > seq.len() {
                return Some(out);
            }
            for start in 0..=seq.len() - n {
                out.push(subslice_elem(&seq[start..start + n])?);
            }
        }
    }
    Some(out)
}

fn parse_kind_and_size(call: &syn::ExprMethodCall) -> Option<(SliceChunkWindowKind, usize)> {
    if call.args.len() != 1 {
        return None;
    }
    let n: usize = crate::const_int(&call.args[0])?.try_into().ok()?;
    if n == 0 {
        return None;
    }
    let kind = match call.method.to_string().as_str() {
        "chunks" | "chunks_mut" => SliceChunkWindowKind::Chunks,
        "chunks_exact" | "chunks_exact_mut" => SliceChunkWindowKind::ChunksExact,
        "rchunks" | "rchunks_mut" => SliceChunkWindowKind::RChunks,
        "rchunks_exact" | "rchunks_exact_mut" => SliceChunkWindowKind::RChunksExact,
        "windows" => SliceChunkWindowKind::Windows,
        _ => return None,
    };
    Some((kind, n))
}

pub(crate) fn runtime_chunk_window_source_expr(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    depth: usize,
) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Reference(reference) => {
            runtime_chunk_window_source_expr(&reference.expr, fcx, depth + 1)
        }
        Expr::Paren(paren) => runtime_chunk_window_source_expr(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => runtime_chunk_window_source_expr(&group.expr, fcx, depth + 1),
        Expr::MethodCall(call) => {
            parse_kind_and_size(call).is_some()
                && !receiver_has_literal_sequence_floor(&call.receiver, fcx, depth + 1)
        }
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(ToString::to_string) else {
                return false;
            };
            fcx.let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
                .or_else(|| fcx.scope().let_binding_for_audit(&name))
                .is_some_and(|init| runtime_chunk_window_source_expr(init, fcx, depth + 1))
        }
        _ => false,
    }
}

fn receiver_has_literal_sequence_floor(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Array(_) | Expr::Repeat(_) | Expr::Index(_) => true,
        Expr::Reference(reference) => {
            receiver_has_literal_sequence_floor(&reference.expr, fcx, depth + 1)
        }
        Expr::Paren(paren) => receiver_has_literal_sequence_floor(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => receiver_has_literal_sequence_floor(&group.expr, fcx, depth + 1),
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(ToString::to_string) else {
                return false;
            };
            fcx.let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
                .is_some_and(|init| receiver_has_literal_sequence_floor(init, fcx, depth + 1))
        }
        other => crate::sugar::collection_literal::collection_literal_array(other).is_some(),
    }
}

fn slice_chunk_window_gap(reason: &str) -> ! {
    panic!("slice_chunk_window did not reach a lawful floor: {reason}")
}

fn subslice_elem(elems: &[DesugaredElem]) -> Option<DesugaredElem> {
    let exprs = elems
        .iter()
        .map(|elem| elem.expr.clone())
        .collect::<Vec<_>>();
    let expr: Expr = syn::parse2(quote!([#(#exprs),*])).ok()?;
    let value = elems
        .iter()
        .map(|elem| elem.value.clone())
        .collect::<Option<Vec<ConstVal>>>()
        .map(ConstVal::Tuple);
    Some(DesugaredElem { expr, value })
}
