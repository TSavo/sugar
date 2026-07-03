// SPDX-License-Identifier: Apache-2.0
//
// Literal-pinned interior-cell reads. The temporal rewrite ledger owns the write
// replay; this term sugar only turns a tracked read into the already-built currently
// pinned literal value body, or refuses by the ledger's named reason.

use crate::sugar::assign_op::CellKind;
use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "cell_refcell",
    &["unary", "method"],
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
            #[test]
            fn t_cell_refcell_good() {
                let cell = std::cell::Cell::new(5_i32);
                assert_eq!(cell.get(), 5);
            }
        "#,
        r#"
            #[test]
            fn t_cell_refcell_bad() {
                let cell = std::cell::Cell::new(5_i32);
                assert_eq!(cell.get(), 6);
            }
        "#,
    ),
    recognize,
);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if let Some(receiver_frag) = cell_get_receiver_frag(*frag) {
        if tracked_cell_kind_frag(receiver_frag, fcx) == Some(CellKind::Cell) {
            return Some(CellRefCellSugar::new(cell_value_frag(
                receiver_frag,
                CellKind::Cell,
                fcx,
            )));
        }
    }
    if let Some(receiver_frag) = refcell_borrow_deref_receiver_frag(*frag) {
        if tracked_cell_kind_frag(receiver_frag, fcx) == Some(CellKind::RefCell) {
            return Some(CellRefCellSugar::new(cell_value_frag(
                receiver_frag,
                CellKind::RefCell,
                fcx,
            )));
        }
    }
    None
}

struct CellRefCellSugar {
    value: CellValue,
}

enum CellValue {
    Body(SugarBody<TermFloor>),
    Missing,
    Refused(String),
}

impl Sugar for CellRefCellSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let value = match &self.value {
            CellValue::Body(value) => value,
            CellValue::Missing => {
                cell_refcell_gap("tracked Cell/RefCell read has no temporal value")
            }
            CellValue::Refused(reason) => {
                return Outcome::Incomplete(Effect::CellRuntimeAliased {
                    boundary: reason.clone(),
                })
            }
        };
        match value.reduce(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(term) => Outcome::Complete(Desugared::Term(term)),
                None => cell_refcell_gap("tracked Cell/RefCell value reduced to non-term"),
            },
            Outcome::Incomplete(effect) => Outcome::Incomplete(effect),
        }
    }
}

impl CellRefCellSugar {
    fn new(value: CellValue) -> Box<dyn Sugar> {
        Box::new(Self { value })
    }
}

fn cell_value_frag(
    receiver_frag: SourceFragment<'_>,
    kind: CellKind,
    fcx: &SugarBuildCtx,
) -> CellValue {
    let Some(name) = receiver_frag.strip_refs_groups().path_simple_ident() else {
        return CellValue::Missing;
    };
    match fcx.scope().temporal_cell_value_expr(&name, kind) {
        Ok(Some(value)) => CellValue::Body(SugarBody::term(&value, fcx)),
        Ok(None) => CellValue::Missing,
        Err(reason) => CellValue::Refused(reason),
    }
}

fn tracked_cell_kind_frag(
    receiver_frag: SourceFragment<'_>,
    fcx: &SugarBuildCtx,
) -> Option<CellKind> {
    let name = receiver_frag.strip_refs_groups().path_simple_ident()?;
    fcx.scope().temporal_cell_kind(&name)
}

fn cell_refcell_gap(reason: &str) -> ! {
    panic!("tracked Cell/RefCell read did not reach a lawful value floor: {reason}")
}

/// Strip refs/groups, then check for a zero-arg `.get()` method call.
/// Returns the receiver fragment if the shape matches, or `None`.
fn cell_get_receiver_frag(frag: SourceFragment<'_>) -> Option<SourceFragment<'_>> {
    let stripped = frag.strip_refs_groups();
    if stripped.call_method_key().as_deref() != Some("get") {
        return None;
    }
    if stripped.call_arg_count() != 0 {
        return None;
    }
    stripped.call_receiver()
}

/// Strip refs/groups, then check for `*(expr).borrow()` -- a `Deref` unary whose
/// operand (after further stripping) is a zero-arg `.borrow()` method call.
/// Returns the receiver fragment of the inner `.borrow()` call, or `None`.
fn refcell_borrow_deref_receiver_frag(frag: SourceFragment<'_>) -> Option<SourceFragment<'_>> {
    let stripped = frag.strip_refs_groups();
    if stripped.unary_op_kind() != Some("Deref") {
        return None;
    }
    let operand = stripped.unary_operand()?;
    let inner = operand.strip_refs_groups();
    if inner.call_method_key().as_deref() != Some("borrow") {
        return None;
    }
    if inner.call_arg_count() != 0 {
        return None;
    }
    inner.call_receiver()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Extract the single tail expression from a one-statement function body.
    fn tail_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    /// Positive: `c.get()` -- a zero-arg `.get()` method call.
    /// `cell_get_receiver_frag` returns the receiver, which has
    /// `path_simple_ident() == "c"`. Struct `CellRefCellSugar` holds `CellValue`
    /// -- no raw syn field.
    #[test]
    fn from_src_cell_get_observed_and_receiver_ident() {
        let file = parse_file("fn f(c: &Cell<i32>) -> Option<i32> { c.get() }");
        let frag = tail_expr_frag(&file, "f.rs");

        // shape check
        assert_eq!(frag.observed(), "MethodCall");
        assert_eq!(frag.call_method_key().as_deref(), Some("get"));
        assert_eq!(frag.call_arg_count(), 0);

        // frag helper returns the receiver
        let receiver = cell_get_receiver_frag(frag).expect("cell_get_receiver_frag matched");
        assert_eq!(receiver.observed(), "Name");
        assert_eq!(receiver.path_simple_ident().as_deref(), Some("c"));
    }

    /// Positive: `*rc.borrow()` -- a Deref unary wrapping a zero-arg `.borrow()`.
    /// `refcell_borrow_deref_receiver_frag` extracts the receiver `rc`.
    #[test]
    fn from_src_refcell_borrow_deref_observed_and_receiver_ident() {
        let file = parse_file("fn f(rc: &RefCell<i32>) -> i32 { *rc.borrow() }");
        let frag = tail_expr_frag(&file, "f.rs");

        // top-level shape: Deref unary
        assert_eq!(frag.observed(), "UnaryOp");
        assert_eq!(frag.unary_op_kind(), Some("Deref"));

        // operand is the .borrow() call
        let operand = frag.unary_operand().expect("operand present");
        assert_eq!(operand.observed(), "MethodCall");
        assert_eq!(operand.call_method_key().as_deref(), Some("borrow"));
        assert_eq!(operand.call_arg_count(), 0);

        // frag helper extracts the receiver
        let receiver = refcell_borrow_deref_receiver_frag(frag)
            .expect("refcell_borrow_deref_receiver matched");
        assert_eq!(receiver.observed(), "Name");
        assert_eq!(receiver.path_simple_ident().as_deref(), Some("rc"));
    }

    /// Discrimination: `.set(5)` has a non-zero arg count --
    /// `cell_get_receiver_frag` returns `None`, proving the zero-arg guard is active.
    #[test]
    fn discrimination_cell_set_not_matched_by_get_frag() {
        let file = parse_file("fn f(c: &Cell<i32>) { c.set(5); }");
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = frag.function_body().unwrap();
        let stmts = body.statements();
        // The statement is a semicolon-terminated expression; terms() yields the call.
        let terms = stmts[0].terms();
        let call_frag = terms[0];

        assert_eq!(call_frag.observed(), "MethodCall");
        assert_eq!(call_frag.call_method_key().as_deref(), Some("set"));
        assert_eq!(call_frag.call_arg_count(), 1);
        assert!(cell_get_receiver_frag(call_frag).is_none());
    }

    /// Structural: a `BinOp` fragment is not a MethodCall or Unary -- both frag
    /// helpers return `None`; shape-specific accessors do not bleed across kinds.
    #[test]
    fn structural_binop_returns_none_from_both_cell_frag_helpers() {
        let file = parse_file("fn f(a: i32, b: i32) -> i32 { a + b }");
        let frag = tail_expr_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "BinOp");
        assert_eq!(frag.unary_op_kind(), None);
        assert_eq!(frag.call_method_key(), None);
        assert!(cell_get_receiver_frag(frag).is_none());
        assert!(refcell_borrow_deref_receiver_frag(frag).is_none());
    }
}
