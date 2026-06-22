// SPDX-License-Identifier: Apache-2.0
//
// `format_args!` is a rustc builtin that constructs `core::fmt::Arguments`, not an
// ordinary macro term. Own the closed stdlib methods whose result follows from the
// compiler-built template. Unknown/runtime shapes decline so generic callsite digging
// remains visible instead of becoming a forged fact.

use sugar_ir_symbolic::num;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::format::{
    is_format_args_macro_shape, stable_let_bindings, try_estimate_format_args_capacity,
};
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const ESTIMATED_CAPACITY_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "format_args_estimated_capacity",
    &["method"],
    recognize_estimated_capacity,
);

fn recognize_estimated_capacity(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "estimated_capacity" || !call.args.is_empty() {
        return None;
    }
    if !is_format_args_macro_shape(&call.receiver) {
        return None;
    }
    if fcx.scope().macro_registry().lookup("format_args").is_some() {
        debug!(
            target: "sugar_lift_rust_tests::sugar::format_args",
            "source macro named format_args is present; builtin FormatArgsSugar declines"
        );
        return None;
    }
    let stable = stable_let_bindings(fcx.scope());
    match try_estimate_format_args_capacity(&call.receiver, &stable) {
        Ok(Some(capacity)) => Some(Box::new(EstimatedCapacitySugar { capacity })),
        Ok(None) => None,
        Err(_) => None,
    }
}

struct EstimatedCapacitySugar {
    capacity: usize,
}

impl Sugar for EstimatedCapacitySugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        debug!(
            target: "sugar_lift_rust_tests::sugar::format_args",
            capacity = self.capacity,
            "resolved format_args estimated_capacity compiler axiom to literal"
        );
        Outcome::Dug(Desugared::Term(num(self.capacity as i128)))
    }
}
