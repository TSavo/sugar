// SPDX-License-Identifier: Apache-2.0
//
// Direct slice/array accessor methods over literal sequences. Iterator terminals
// (`.iter().sum()`, `.iter().min()`, ...), raw indexing (`a[i]`), `.len()`, and
// `.is_empty()` are owned by their existing sugars; this node only covers the
// direct accessor surfaces that otherwise fall through to opaque `method:*`.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, ExprLit, ExprMethodCall, Lit};

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::method_family;
use crate::sugar::monadic;
use crate::{
    bool_const, const_fold_int_term, const_val_term, num, simple_path_name, strip_refs_groups,
    ConstVal, Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx,
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
    if !slice_receiver_shape(&call.receiver, fcx, 0) {
        return None;
    }
    let receiver = sequence_body(&call.receiver, fcx);
    let arg = match kind {
        AccessKind::First | AccessKind::Last => SliceAccessorArg::None,
        AccessKind::Get | AccessKind::Contains => {
            let arg = call.args.first()?;
            SliceAccessorArg::Term(SugarBody::term(strip_refs_groups(arg), fcx))
        }
        AccessKind::StartsWith | AccessKind::EndsWith => {
            let arg = call.args.first()?;
            SliceAccessorArg::Sequence(sequence_body(strip_refs_groups(arg), fcx))
        }
    };
    Some(Box::new(SliceAccessorSugar {
        kind,
        receiver_name: simple_path_name(&call.receiver),
        receiver,
        arg,
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
    receiver_name: Option<String>,
    receiver: SugarBody<CompositeFloor>,
    arg: SliceAccessorArg,
}

enum SliceAccessorArg {
    None,
    Term(SugarBody<TermFloor>),
    Sequence(SugarBody<CompositeFloor>),
}

impl Sugar for SliceAccessorSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(effect) = self.mutable_local_predicate_effect(ctx) {
            return Outcome::Incomplete(effect);
        }
        let seq = match sequence_from_body(&self.receiver, ctx, "slice accessor receiver") {
            Ok(seq) => seq,
            Err(outcome) => return outcome,
        };
        let term = match self.eval(ctx, &seq) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        Outcome::Complete(Desugared::Term(term))
    }
}

impl SliceAccessorSugar {
    fn mutable_local_predicate_effect(&self, ctx: &SugarCtx) -> Option<Effect> {
        if !matches!(
            self.kind,
            AccessKind::Contains | AccessKind::StartsWith | AccessKind::EndsWith
        ) {
            return None;
        }
        let receiver = self.receiver_name.as_ref()?;
        if ctx
            .scope
            .let_binding_for_audit(receiver)
            .is_some_and(|init| matches!(strip_refs_groups(init), Expr::Range(_)))
        {
            return None;
        }
        if !ctx.scope.is_mut_local(receiver) {
            return None;
        }
        let method = self.kind.method_name().to_string();
        Some(Effect::MutableLocalSlicePredicate {
            boundary: format!("{receiver}.{method}(..)"),
            method,
            receiver: receiver.clone(),
        })
    }

    fn eval(&self, ctx: &SugarCtx, seq: &[DesugaredElem]) -> Result<Rc<Term>, Outcome> {
        match self.kind {
            AccessKind::First => option_at(seq.first()),
            AccessKind::Last => option_at(seq.last()),
            AccessKind::Get => {
                let idx = self.index_arg(ctx)?;
                Ok(match seq.get(idx) {
                    Some(elem) => monadic::some_term(num(elem_int(elem)?)),
                    None => monadic::none_term(),
                })
            }
            AccessKind::Contains => {
                let needle = self.int_arg(ctx)?;
                let elems = int_values(&seq)?;
                Ok(bool_const(elems.contains(&needle)))
            }
            AccessKind::StartsWith => {
                let haystack = int_values(&seq)?;
                let prefix = int_values(&self.sequence_arg(ctx, "starts_with argument")?)?;
                Ok(bool_const(
                    haystack.as_slice().starts_with(prefix.as_slice()),
                ))
            }
            AccessKind::EndsWith => {
                let haystack = int_values(&seq)?;
                let suffix = int_values(&self.sequence_arg(ctx, "ends_with argument")?)?;
                Ok(bool_const(haystack.as_slice().ends_with(suffix.as_slice())))
            }
        }
    }

    fn index_arg(&self, ctx: &SugarCtx) -> Result<usize, Outcome> {
        let value = self.int_arg(ctx)?;
        Ok(usize::try_from(value).unwrap_or_else(|_| {
            slice_accessor_gap("slice accessor index is negative or too large")
        }))
    }

    fn int_arg(&self, ctx: &SugarCtx) -> Result<i128, Outcome> {
        let term = match &self.arg {
            SliceAccessorArg::Term(body) => term_from_body(body, ctx, "slice accessor scalar arg")?,
            _ => slice_accessor_gap("slice accessor constructed without scalar arg"),
        };
        Ok(const_fold_int_term(&term).unwrap_or_else(|| {
            slice_accessor_gap("slice accessor scalar arg did not reduce to an integer literal")
        }))
    }

    fn sequence_arg(
        &self,
        ctx: &SugarCtx,
        label: &'static str,
    ) -> Result<Vec<DesugaredElem>, Outcome> {
        match &self.arg {
            SliceAccessorArg::Sequence(body) => sequence_from_body(body, ctx, label),
            _ => slice_accessor_gap("slice accessor constructed without sequence arg"),
        }
    }
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
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
                .or_else(|| fcx.scope().let_binding_for_audit(&name));
            bound.is_some_and(|init| {
                !matches!(strip_refs_groups(init), Expr::Range(_))
                    && !text_receiver_shape(init, fcx, depth + 1)
            }) || fcx.scope().is_temporally_unstable_read(&name)
                || fcx.scope().unknown_mutation_reason(&name).is_some()
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

fn sequence_body(expr: &Expr, fcx: &SugarBuildCtx) -> SugarBody<CompositeFloor> {
    match method_family::build_literal_sequence_composite(expr, fcx) {
        Some(node) => SugarBody::from_node(node),
        None => SugarBody::composite(expr, fcx),
    }
}

fn sequence_from_body(
    body: &SugarBody<CompositeFloor>,
    ctx: &SugarCtx,
    label: &'static str,
) -> Result<Vec<DesugaredElem>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_seq()
            .unwrap_or_else(|| slice_accessor_gap(&format!("{label} reduced to non-sequence")))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn term_from_body(
    body: &SugarBody<TermFloor>,
    ctx: &SugarCtx,
    label: &'static str,
) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_term()
            .unwrap_or_else(|| slice_accessor_gap(&format!("{label} reduced to non-term")))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn option_at(elem: Option<&DesugaredElem>) -> Result<Rc<Term>, Outcome> {
    Ok(match elem {
        Some(elem) => monadic::some_term(elem_term(elem)?),
        None => monadic::none_term(),
    })
}

fn int_values(seq: &[DesugaredElem]) -> Result<Vec<i128>, Outcome> {
    seq.iter().map(elem_int).collect()
}

fn elem_int(elem: &DesugaredElem) -> Result<i128, Outcome> {
    Ok(elem
        .value
        .as_ref()
        .and_then(ConstVal::as_int)
        .unwrap_or_else(|| {
            slice_accessor_gap("slice accessor sequence element was not an integer literal")
        }))
}

fn elem_term(elem: &DesugaredElem) -> Result<Rc<Term>, Outcome> {
    Ok(elem
        .value
        .as_ref()
        .and_then(const_val_term)
        .unwrap_or_else(|| {
            slice_accessor_gap("slice accessor sequence element did not dispatch to scalar literal")
        }))
}

fn slice_accessor_gap(reason: &str) -> ! {
    panic!("slice_accessor did not reach a lawful floor: {reason}")
}
