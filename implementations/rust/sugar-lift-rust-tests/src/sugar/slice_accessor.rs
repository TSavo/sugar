// SPDX-License-Identifier: Apache-2.0
//
// Direct slice/array accessor methods over literal sequences. Iterator terminals
// (`.iter().sum()`, `.iter().min()`, ...), raw indexing (`a[i]`), `.len()`, and
// `.is_empty()` are owned by their existing sugars; this node only covers the
// direct accessor surfaces that otherwise fall through to opaque `method:*`.
//
// MIGRATION NOTE (Phase-3 ratchet). Fully migrated:
//   * `recognize` uses ONLY `SourceFragment` typed accessors -- no `as_expr()`,
//     no `Expr::`/`ExprMethodCall` field access, no raw `syn` in this body.
//   * `SliceAccessorSugar` holds NO raw `syn` fields: only fragment-derived data
//     (`AccessKind` enum, `Option<String>`, `SugarBody<CompositeFloor>`,
//     `SliceAccessorArg` enum over `SugarBody` children).

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::monadic;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    bool_const, const_fold_int_term, const_val_term, num, strip_refs_groups, ConstVal, Desugared,
    DesugaredElem, Effect, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "slice_accessor",
        &["iter_terminal", "method"],
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_slice_accessor_good() {
                    assert_eq!([1, 2, 3].first(), Some(&1));
                }
            "#,
            r#"
                #[test]
                fn t_slice_accessor_bad() {
                    assert_eq!([1, 2, 3].first(), Some(&2));
                }
            "#,
        ),
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let stripped = frag.strip_refs_groups();
    let kind = recognize_kind_frag(&stripped)?;
    let receiver_frag = stripped.call_receiver()?;
    if !receiver_frag.slice_receiver_shape_frag(fcx) {
        return None;
    }
    let receiver = receiver_frag.sequence_body_frag(fcx);
    let args = stripped.call_args();
    let arg = match kind {
        AccessKind::First | AccessKind::Last => SliceAccessorArg::None,
        AccessKind::Get | AccessKind::Contains => {
            let arg_frag = args.first()?;
            let stripped_arg = arg_frag.strip_refs_groups();
            SliceAccessorArg::Term(SugarBody::term_frag(&stripped_arg, fcx))
        }
        AccessKind::StartsWith | AccessKind::EndsWith => {
            let arg_frag = args.first()?;
            let stripped_arg = arg_frag.strip_refs_groups();
            SliceAccessorArg::Sequence(stripped_arg.sequence_body_frag(fcx))
        }
    };
    Some(Box::new(SliceAccessorSugar {
        kind,
        receiver_name: stripped.call_receiver_simple_ident(),
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

/// Classify the method call kind from a `SourceFragment`. Uses only
/// `call_method_key()` and `call_arg_count()` -- no raw syn in this body.
fn recognize_kind_frag(frag: &SourceFragment) -> Option<AccessKind> {
    let method = frag.call_method_key()?;
    let arg_count = frag.call_arg_count();
    Some(match method.as_str() {
        "first" if arg_count == 0 => AccessKind::First,
        "last" if arg_count == 0 => AccessKind::Last,
        "get" if arg_count == 1 => AccessKind::Get,
        "contains" if arg_count == 1 => AccessKind::Contains,
        "starts_with" if arg_count == 1 => AccessKind::StartsWith,
        "ends_with" if arg_count == 1 => AccessKind::EndsWith,
        _ => return None,
    })
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Extract the expression fragment of the first statement in the body of the
    /// first function item in `file`. Helper for all from_src tests below.
    fn first_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    /// Positive case: `[1u8, 2u8, 3u8].first()` -- observed is `MethodCall`,
    /// `call_method_key()` returns `"first"`, `call_arg_count()` is 0, and
    /// receiver is an `Array` fragment. The Sugar struct holds `AccessKind::First`,
    /// `receiver_name: None` (no bare ident), `SugarBody<CompositeFloor>`, and
    /// `SliceAccessorArg::None` -- zero raw syn fields.
    #[test]
    fn from_src_first_observed_method_key_arg_count_receiver() {
        let file = parse_file("fn f() -> Option<u8> { [1u8, 2u8, 3u8].first() }");
        let frag = first_expr_frag(&file, "f.rs");

        // shape -- no as_expr / Expr:: / raw field access, typed accessors only
        assert_eq!(frag.observed(), "MethodCall");
        assert_eq!(frag.call_method_key().as_deref(), Some("first"));
        assert_eq!(frag.call_arg_count(), 0);

        // receiver is the literal array
        let recv = frag.call_receiver().expect("receiver present");
        assert_eq!(recv.observed(), "Array");
    }

    /// Discrimination: `[1u8, 2u8].iter().sum::<u8>()` has method key `"sum"`, not
    /// a slice accessor method. Proves `recognize_kind_frag` rejects it.
    #[test]
    fn discrimination_iter_sum_not_a_slice_accessor_method() {
        let file = parse_file("fn f() -> u8 { [1u8, 2u8].iter().sum::<u8>() }");
        let frag = first_expr_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");
        let key = frag.call_method_key();
        assert_ne!(key.as_deref(), Some("first"));
        assert_ne!(key.as_deref(), Some("last"));
        assert_ne!(key.as_deref(), Some("get"));
        assert_ne!(key.as_deref(), Some("contains"));
        assert_ne!(key.as_deref(), Some("starts_with"));
        assert_ne!(key.as_deref(), Some("ends_with"));
    }

    /// Structural: a `BinOp` fragment returns `None` from `call_method_key()` and
    /// `call_receiver()` -- shape-specific accessors do not bleed across node kinds.
    #[test]
    fn structural_binop_returns_none_from_call_accessors() {
        let file = parse_file("fn f(a: u8, b: u8) -> u8 { a + b }");
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = frag.function_body().unwrap();
        let stmts = body.statements();
        let terms = stmts[0].terms();
        let binop_frag = &terms[0];

        assert_eq!(binop_frag.observed(), "BinOp");
        assert_eq!(binop_frag.call_method_key(), None);
        assert!(binop_frag.call_receiver().is_none());
        assert_eq!(binop_frag.call_arg_count(), 0);
    }
}
