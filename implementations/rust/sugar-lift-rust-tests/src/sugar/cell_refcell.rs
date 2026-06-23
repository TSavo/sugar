// SPDX-License-Identifier: Apache-2.0
//
// Literal-pinned interior-cell reads. The temporal rewrite ledger owns the write
// replay; this term sugar only turns a tracked read into the currently pinned
// literal value, or refuses by the ledger's named reason.

use std::collections::BTreeMap;

use syn::{Expr, UnOp};

use crate::sugar::assign_op::CellKind;
use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
use crate::{simple_path_name, strip_refs_groups, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("cell_refcell", &["unary", "method"], recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if let Some(receiver) = cell_get_receiver(expr) {
        if tracked_cell_kind(receiver, fcx) == Some(CellKind::Cell) {
            return Some(Box::new(CellRefCellSugar {
                receiver: receiver.clone(),
                kind: CellKind::Cell,
                let_inits: capture_let_inits(fcx),
            }));
        }
    }
    if let Some(receiver) = refcell_borrow_deref_receiver(expr) {
        if tracked_cell_kind(receiver, fcx) == Some(CellKind::RefCell) {
            return Some(Box::new(CellRefCellSugar {
                receiver: receiver.clone(),
                kind: CellKind::RefCell,
                let_inits: capture_let_inits(fcx),
            }));
        }
    }
    None
}

struct CellRefCellSugar {
    receiver: Expr,
    kind: CellKind,
    let_inits: BTreeMap<String, Expr>,
}

impl Sugar for CellRefCellSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let Some(name) = simple_path_name(&self.receiver) else {
            return Outcome::from_opt(None);
        };
        let value = match ctx.scope.temporal_cell_value_expr(&name, self.kind) {
            Ok(Some(value)) => value,
            Ok(None) => return Outcome::from_opt(None),
            Err(reason) => return Outcome::Incomplete(Effect::Unsupported { reason }),
        };
        let stable = stable_let_bindings(ctx.scope);
        let let_inits: BTreeMap<String, &Expr> = stable
            .iter()
            .map(|(name, init)| (name.clone(), init))
            .chain(
                self.let_inits
                    .iter()
                    .map(|(name, init)| (name.clone(), init)),
            )
            .collect();
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        match build_term(&value, &fcx).desugar(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(term) => Outcome::Complete(Desugared::Term(term)),
                None => Outcome::from_opt(None),
            },
            Outcome::Incomplete(effect) => Outcome::Incomplete(effect),
        }
    }
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

fn tracked_cell_kind(receiver: &Expr, fcx: &SugarBuildCtx) -> Option<CellKind> {
    let name = simple_path_name(receiver)?;
    fcx.scope().temporal_cell_kind(&name)
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
