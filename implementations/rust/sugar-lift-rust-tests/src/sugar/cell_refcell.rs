// SPDX-License-Identifier: Apache-2.0
//
// Literal-pinned interior-cell reads. The temporal rewrite ledger owns the write
// replay; this term sugar only turns a tracked read into the already-built currently
// pinned literal value body, or refuses by the ledger's named reason.

use syn::{Expr, UnOp};

use crate::sugar::assign_op::CellKind;
use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::{simple_path_name, strip_refs_groups, Desugared, Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("cell_refcell", &["unary", "method"], recognize);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    if let Some(receiver) = cell_get_receiver(expr) {
        if tracked_cell_kind(receiver, fcx) == Some(CellKind::Cell) {
            return Some(CellRefCellSugar::new(cell_value(
                receiver,
                CellKind::Cell,
                fcx,
            )));
        }
    }
    if let Some(receiver) = refcell_borrow_deref_receiver(expr) {
        if tracked_cell_kind(receiver, fcx) == Some(CellKind::RefCell) {
            return Some(CellRefCellSugar::new(cell_value(
                receiver,
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

fn cell_value(receiver: &Expr, kind: CellKind, fcx: &SugarBuildCtx) -> CellValue {
    let Some(name) = simple_path_name(receiver) else {
        return CellValue::Missing;
    };
    match fcx.scope().temporal_cell_value_expr(&name, kind) {
        Ok(Some(value)) => CellValue::Body(SugarBody::term(&value, fcx)),
        Ok(None) => CellValue::Missing,
        Err(reason) => CellValue::Refused(reason),
    }
}

fn tracked_cell_kind(receiver: &Expr, fcx: &SugarBuildCtx) -> Option<CellKind> {
    let name = simple_path_name(receiver)?;
    fcx.scope().temporal_cell_kind(&name)
}

fn cell_refcell_gap(reason: &str) -> ! {
    panic!("tracked Cell/RefCell read did not reach a lawful value floor: {reason}")
}

fn cell_get_receiver(expr: &Expr) -> Option<&Expr> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    (call.method == "get" && call.args.is_empty()).then_some(call.receiver.as_ref())
}

fn refcell_borrow_deref_receiver(expr: &Expr) -> Option<&Expr> {
    let Expr::Unary(unary) = strip_refs_groups(expr) else {
        return None;
    };
    if !matches!(unary.op, UnOp::Deref(_)) {
        return None;
    }
    let Expr::MethodCall(call) = strip_refs_groups(&unary.expr) else {
        return None;
    };
    (call.method == "borrow" && call.args.is_empty()).then_some(call.receiver.as_ref())
}
