// SPDX-License-Identifier: Apache-2.0
//
// Direct slice/array accessor methods over literal sequences. Iterator terminals
// (`.iter().sum()`, `.iter().min()`, ...), raw indexing (`a[i]`), `.len()`, and
// `.is_empty()` are owned by their existing sugars; this node only covers the
// direct accessor surfaces that otherwise fall through to opaque `method:*`.

use std::rc::Rc;

use quote::ToTokens;
use sugar_ir_symbolic::Term;
use syn::{Expr, ExprLit, ExprMethodCall, Lit};

use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
use crate::sugar::method_family;
use crate::sugar::monadic;
use crate::{
    bool_const, const_fold_int_term, num, strip_refs_groups, ConstVal, Desugared, DesugaredElem,
    Effect, Outcome, Sugar, SugarCtx, STRUCTURAL_BACKSTOP_REASON,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "slice_accessor",
        &["iter_terminal", "method"],
        recognize,
    );

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    let kind = recognize_kind(call)?;
    if !slice_receiver_shape(&call.receiver, fcx, 0)
        && !mutable_path_slice_predicate_receiver_shape(kind, &call.receiver, fcx)
    {
        return None;
    }
    Some(Box::new(SliceAccessorSugar {
        kind,
        receiver: call.receiver.as_ref().clone(),
        args: call.args.iter().cloned().collect(),
    }))
}

#[derive(Clone, Copy)]
enum AccessKind {
    First,
    Last,
    Get,
    Contains,
    StartsWith,
    EndsWith,
}

struct SliceAccessorSugar {
    kind: AccessKind,
    receiver: Expr,
    args: Vec<Expr>,
}

impl Sugar for SliceAccessorSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.eval(ctx) {
            Ok(term) => Outcome::Dug(Desugared::Term(term)),
            Err(effect) => Outcome::Hit(effect),
        }
    }
}

impl SliceAccessorSugar {
    fn eval(&self, ctx: &SugarCtx) -> Result<Rc<Term>, Effect> {
        if let Some(effect) = mutable_local_receiver_effect(self.kind, &self.receiver, ctx) {
            return Err(effect);
        }
        let stable = stable_let_bindings(ctx.scope);
        let let_inits = stable
            .iter()
            .map(|(name, init)| (name.clone(), init))
            .collect();
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let seq = literal_sequence(&self.receiver, &fcx, ctx, Some(self.kind))?;
        match self.kind {
            AccessKind::First => option_at(seq.first()),
            AccessKind::Last => option_at(seq.last()),
            AccessKind::Get => {
                let idx = self.index_arg(&fcx, ctx)?;
                Ok(match seq.get(idx) {
                    Some(elem) => monadic::some_term(num(elem_int(elem)?)),
                    None => monadic::none_term(),
                })
            }
            AccessKind::Contains => {
                let needle = self.int_arg(0, &fcx, ctx)?;
                let elems = int_values(&seq)?;
                Ok(bool_const(elems.contains(&needle)))
            }
            AccessKind::StartsWith => {
                let haystack = int_values(&seq)?;
                let prefix = literal_int_sequence_arg(&self.args[0], &fcx, ctx)?;
                Ok(bool_const(
                    haystack.as_slice().starts_with(prefix.as_slice()),
                ))
            }
            AccessKind::EndsWith => {
                let haystack = int_values(&seq)?;
                let suffix = literal_int_sequence_arg(&self.args[0], &fcx, ctx)?;
                Ok(bool_const(haystack.as_slice().ends_with(suffix.as_slice())))
            }
        }
    }

    fn index_arg(&self, fcx: &SugarBuildCtx, ctx: &SugarCtx) -> Result<usize, Effect> {
        let value = self.int_arg(0, fcx, ctx)?;
        usize::try_from(value).map_err(|_| structural_effect())
    }

    fn int_arg(&self, idx: usize, fcx: &SugarBuildCtx, ctx: &SugarCtx) -> Result<i128, Effect> {
        let arg = self.args.get(idx).ok_or_else(structural_effect)?;
        let term = term_for(strip_refs_groups(arg), fcx, ctx)?;
        const_fold_int_term(&term).ok_or_else(|| runtime_index_effect(strip_refs_groups(arg)))
    }
}

fn mutable_local_receiver_effect(
    kind: AccessKind,
    receiver: &Expr,
    ctx: &SugarCtx,
) -> Option<Effect> {
    let method = match kind {
        AccessKind::Contains => "contains",
        AccessKind::StartsWith => "starts_with",
        AccessKind::EndsWith => "ends_with",
        _ => return None,
    };
    let recv_name = simple_path_name(receiver)?;
    if ctx
        .scope
        .let_binding_for_audit(&recv_name)
        .is_some_and(|init| matches!(strip_refs_groups(init), Expr::Range(_)))
    {
        return None;
    }
    ctx.scope
        .is_mut_local(&recv_name)
        .then(|| Effect::Unsupported {
            reason: format!(
                "{method} predicate over a MUTABLE-local receiver `{recv_name}` \
                 (bin-2: a slice/string mutated by side-effecting iteration, not \
                 constructed from source literals); refused"
            ),
        })
}

fn recognize_kind(call: &ExprMethodCall) -> Option<AccessKind> {
    Some(match call.method.to_string().as_str() {
        "first" if call.args.is_empty() => AccessKind::First,
        "last" if call.args.is_empty() => AccessKind::Last,
        "get" if call.args.len() == 1 => AccessKind::Get,
        "contains" if call.args.len() == 1 => AccessKind::Contains,
        "starts_with" if call.args.len() == 1 => AccessKind::StartsWith,
        "ends_with" if call.args.len() == 1 => AccessKind::EndsWith,
        _ => return None,
    })
}

impl AccessKind {
    fn method_name(self) -> &'static str {
        match self {
            AccessKind::First => "first",
            AccessKind::Last => "last",
            AccessKind::Get => "get",
            AccessKind::Contains => "contains",
            AccessKind::StartsWith => "starts_with",
            AccessKind::EndsWith => "ends_with",
        }
    }
}

fn slice_receiver_shape(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Range(_)
        | Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Str(_),
            ..
        }) => false,
        Expr::Array(_) | Expr::Repeat(_) | Expr::Index(_) => true,
        Expr::Reference(reference) => slice_receiver_shape(&reference.expr, fcx, depth + 1),
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(ToString::to_string) else {
                return false;
            };
            // Shared method names (`contains`, `starts_with`) dispatch by receiver domain:
            // a visible text binding belongs to `str_method`, not this slice lane.
            let bound = fcx
                .let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name));
            bound.is_some_and(|init| !text_receiver_shape(init, fcx, depth + 1))
        }
        Expr::MethodCall(call) if call.args.is_empty() => {
            matches!(
                call.method.to_string().as_str(),
                "as_slice" | "to_vec" | "to_owned" | "into_vec"
            ) && slice_receiver_shape(&call.receiver, fcx, depth + 1)
        }
        other => crate::sugar::collection_literal::collection_literal_array(other).is_some(),
    }
}

fn text_receiver_shape(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Str(_), ..
        }) => true,
        Expr::Macro(m) => m
            .mac
            .path
            .segments
            .last()
            .is_some_and(|s| s.ident == "format"),
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(ToString::to_string) else {
                return false;
            };
            fcx.let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
                .is_some_and(|init| text_receiver_shape(init, fcx, depth + 1))
        }
        Expr::MethodCall(call) if call.method == "to_string" && call.args.is_empty() => {
            text_receiver_shape(&call.receiver, fcx, depth + 1)
        }
        Expr::MethodCall(call) if string_result_method(&call.method.to_string()) => {
            text_receiver_shape(&call.receiver, fcx, depth + 1)
        }
        _ => false,
    }
}

fn string_result_method(method: &str) -> bool {
    matches!(
        method,
        "to_ascii_uppercase"
            | "to_ascii_lowercase"
            | "to_uppercase"
            | "to_lowercase"
            | "replace"
            | "trim"
            | "trim_start"
            | "trim_end"
            | "repeat"
    )
}

fn mutable_path_slice_predicate_receiver_shape(
    kind: AccessKind,
    expr: &Expr,
    fcx: &SugarBuildCtx,
) -> bool {
    if !matches!(kind, AccessKind::StartsWith | AccessKind::EndsWith) {
        return false;
    }
    simple_path_name(expr).is_some_and(|name| {
        fcx.scope().is_mut_local(&name) && !fcx.scope().ambiguous_contains(&name)
    })
}

fn literal_sequence(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
    method: Option<AccessKind>,
) -> Result<Vec<DesugaredElem>, Effect> {
    let node = method_family::build_literal_sequence_composite(expr, fcx)
        .ok_or_else(|| runtime_source_effect(expr, fcx, method))?;
    match node.desugar(ctx) {
        Outcome::Dug(d) => d.into_seq().ok_or_else(structural_effect),
        Outcome::Hit(effect) => Err(effect),
    }
}

fn literal_int_sequence_arg(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
) -> Result<Vec<i128>, Effect> {
    int_values(&literal_sequence(strip_refs_groups(expr), fcx, ctx, None)?)
}

fn term_for(expr: &Expr, fcx: &SugarBuildCtx, ctx: &SugarCtx) -> Result<Rc<Term>, Effect> {
    match build_term(expr, fcx).desugar(ctx) {
        Outcome::Dug(d) => d.into_term().ok_or_else(structural_effect),
        Outcome::Hit(effect) => Err(effect),
    }
}

fn option_at(elem: Option<&DesugaredElem>) -> Result<Rc<Term>, Effect> {
    Ok(match elem {
        Some(elem) => monadic::some_term(num(elem_int(elem)?)),
        None => monadic::none_term(),
    })
}

fn int_values(seq: &[DesugaredElem]) -> Result<Vec<i128>, Effect> {
    seq.iter().map(elem_int).collect()
}

fn elem_int(elem: &DesugaredElem) -> Result<i128, Effect> {
    elem.value
        .as_ref()
        .and_then(ConstVal::as_int)
        .ok_or_else(structural_effect)
}

fn structural_effect() -> Effect {
    Effect::Unsupported {
        reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
    }
}

fn runtime_source_effect(expr: &Expr, fcx: &SugarBuildCtx, method: Option<AccessKind>) -> Effect {
    if let Some(name) = range_bounds_receiver_name(expr, fcx) {
        return Effect::Unsupported {
            reason: format!("RangeBounds over runtime value {name}"),
        };
    }
    if let Some(name) = simple_path_name(expr) {
        if fcx.scope().is_mut_local(&name) {
            let method = method
                .map(AccessKind::method_name)
                .unwrap_or("slice accessor");
            return Effect::Unsupported {
                reason: format!(
                    "{method} predicate over a MUTABLE-local receiver `{name}` \
                     (bin-2: a slice/string mutated by side-effecting iteration, not \
                     constructed from source literals); refused"
                ),
            };
        }
    }
    let reason = if chunk_window_source_shape(expr, fcx, 0) {
        format!(
            "chunk source is runtime slice, not literal `{}`",
            strip_refs_groups(expr).to_token_stream()
        )
    } else {
        format!(
            "runtime slice source, not literal `{}`",
            strip_refs_groups(expr).to_token_stream()
        )
    };
    Effect::Unsupported { reason }
}

fn chunk_window_source_shape(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::MethodCall(call) if call.args.len() == 1 => matches!(
            call.method.to_string().as_str(),
            "chunks"
                | "chunks_mut"
                | "chunks_exact"
                | "chunks_exact_mut"
                | "rchunks"
                | "rchunks_mut"
                | "rchunks_exact"
                | "rchunks_exact_mut"
                | "windows"
        ),
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(ToString::to_string) else {
                return false;
            };
            fcx.let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
                .is_some_and(|init| chunk_window_source_shape(init, fcx, depth + 1))
        }
        Expr::Reference(reference) => chunk_window_source_shape(&reference.expr, fcx, depth + 1),
        Expr::Paren(paren) => chunk_window_source_shape(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => chunk_window_source_shape(&group.expr, fcx, depth + 1),
        _ => false,
    }
}

fn runtime_index_effect(expr: &Expr) -> Effect {
    Effect::Unsupported {
        reason: format!(
            "runtime slice index, not literal `{}`",
            strip_refs_groups(expr).to_token_stream()
        ),
    }
}

fn range_bounds_receiver_name(expr: &Expr, fcx: &SugarBuildCtx) -> Option<String> {
    match strip_refs_groups(expr) {
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let init = fcx
                .let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))?;
            is_range_bounds_tuple(init).then_some(name)
        }
        Expr::Tuple(_) if is_range_bounds_tuple(expr) => {
            Some(strip_refs_groups(expr).to_token_stream().to_string())
        }
        _ => None,
    }
}

fn is_range_bounds_tuple(expr: &Expr) -> bool {
    let Expr::Tuple(tuple) = strip_refs_groups(expr) else {
        return false;
    };
    tuple.elems.len() == 2 && tuple.elems.iter().all(is_bound_ctor_expr)
}

fn is_bound_ctor_expr(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Path(path) => path
            .path
            .segments
            .last()
            .is_some_and(|seg| seg.ident == "Unbounded"),
        Expr::Call(call) if call.args.len() == 1 => {
            let Expr::Path(path) = strip_refs_groups(&call.func) else {
                return false;
            };
            path.path.segments.last().is_some_and(|seg| {
                matches!(seg.ident.to_string().as_str(), "Included" | "Excluded")
            })
        }
        _ => false,
    }
}

fn simple_path_name(expr: &Expr) -> Option<String> {
    match strip_refs_groups(expr) {
        Expr::Path(path) if path.qself.is_none() => path.path.get_ident().map(ToString::to_string),
        _ => None,
    }
}
