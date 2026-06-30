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
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const ESTIMATED_CAPACITY_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "format_args_estimated_capacity",
    &["method"],
    recognize_estimated_capacity,
);

fn recognize_estimated_capacity(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
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
        Outcome::Complete(Desugared::Term(num(self.capacity as i128)))
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use sugar_ir_symbolic::ConstValue;

    use super::*;
    use crate::{
        sugar_ctx, FloatWidthScope, LiftOptions, ReductionCtx, TemporalPlan, TemporalScope,
    };

    #[test]
    fn recognizes_builtin_format_args_estimated_capacity() {
        let expr: Expr = syn::parse_str(r#"format_args!("Hello").estimated_capacity()"#)
            .expect("format_args method parses");
        let scope = TemporalScope::new("format-args-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = { let _frag = SourceFragment::expr(&expr, "<src>"); recognize_estimated_capacity(&_frag, &fcx) }
            .expect("builtin format_args estimated_capacity should be owned");
        let items = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);

        let Outcome::Complete(Desugared::Term(term)) = node.desugar(&ctx) else {
            panic!("format_args estimated_capacity should complete to a term");
        };
        let sugar_ir_symbolic::Term::Const {
            value: ConstValue::Int(value),
            ..
        } = term.as_ref()
        else {
            panic!("expected integer capacity term, got {term:?}");
        };
        assert_eq!(*value, 5);
    }
}
