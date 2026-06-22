// SPDX-License-Identifier: Apache-2.0
//
// Direct slice/array accessor methods over literal sequences. Iterator terminals
// (`.iter().sum()`, `.iter().min()`, ...), raw indexing (`a[i]`), `.len()`, and
// `.is_empty()` are owned by their existing sugars; this node only covers the
// direct accessor surfaces that otherwise fall through to opaque `method:*`.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, ExprMethodCall};

use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
use crate::sugar::method_family;
use crate::sugar::monadic;
use crate::{
    bool_const, const_fold_int_term, num, strip_refs_groups, ConstVal, Desugared, DesugaredElem,
    Effect, Outcome, Sugar, SugarCtx, STRUCTURAL_BACKSTOP_REASON,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before("slice_accessor", &["method"], recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    let kind = recognize_kind(call)?;
    if !literal_slice_receiver(&call.receiver, fcx, 0) {
        return None;
    }
    Some(Box::new(SliceAccessorSugar {
        kind,
        receiver: call.receiver.as_ref().clone(),
        args: call.args.iter().cloned().collect(),
        let_inits: capture_let_inits(fcx),
    }))
}

#[derive(Clone, Copy)]
enum AccessKind {
    First,
    Get,
    Contains,
    StartsWith,
    EndsWith,
}

struct SliceAccessorSugar {
    kind: AccessKind,
    receiver: Expr,
    args: Vec<Expr>,
    let_inits: BTreeMap<String, Expr>,
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
        let stable = stable_let_bindings(ctx.scope);
        let let_inits = merge_let_inits(&stable, &self.let_inits);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let seq = literal_sequence(&self.receiver, &fcx, ctx)?;
        match self.kind {
            AccessKind::First => option_at(seq.first()),
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
        const_fold_int_term(&term).ok_or_else(structural_effect)
    }
}

fn recognize_kind(call: &ExprMethodCall) -> Option<AccessKind> {
    Some(match call.method.to_string().as_str() {
        "first" if call.args.is_empty() => AccessKind::First,
        "get" if call.args.len() == 1 => AccessKind::Get,
        "contains" if call.args.len() == 1 => AccessKind::Contains,
        "starts_with" if call.args.len() == 1 => AccessKind::StartsWith,
        "ends_with" if call.args.len() == 1 => AccessKind::EndsWith,
        _ => return None,
    })
}

fn literal_slice_receiver(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Array(_) => true,
        Expr::Repeat(_) | Expr::Index(_) => {
            method_family::literal_sequence_static_len_in_scope(expr, fcx.let_inits(), fcx.scope())
                .is_some()
        }
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(ToString::to_string) else {
                return false;
            };
            fcx.let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
                .is_some_and(|init| literal_slice_receiver(init, fcx, depth + 1))
        }
        Expr::MethodCall(call) if call.args.is_empty() => {
            matches!(
                call.method.to_string().as_str(),
                "as_slice" | "to_vec" | "to_owned" | "into_vec"
            ) && literal_slice_receiver(&call.receiver, fcx, depth + 1)
        }
        other => crate::sugar::collection_literal::collection_literal_array(other).is_some(),
    }
}

fn literal_sequence(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
) -> Result<Vec<DesugaredElem>, Effect> {
    let node =
        method_family::build_literal_sequence_composite(expr, fcx).ok_or_else(structural_effect)?;
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
    int_values(&literal_sequence(strip_refs_groups(expr), fcx, ctx)?)
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

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

fn merge_let_inits<'a>(
    stable: &'a BTreeMap<String, Expr>,
    captured: &'a BTreeMap<String, Expr>,
) -> BTreeMap<String, &'a Expr> {
    stable
        .iter()
        .map(|(name, init)| (name.clone(), init))
        .chain(captured.iter().map(|(name, init)| (name.clone(), init)))
        .collect()
}
