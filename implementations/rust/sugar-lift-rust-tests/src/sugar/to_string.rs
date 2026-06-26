// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for closed stdlib `<literal>.to_string()`. Unknown receivers
// decline so generic MethodSugar can continue digging the method-call universe.

use syn::Expr;

use sugar_ir_symbolic::str_const;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::factory::{FormatValueFloor, SugarBody};
use crate::sugar::format::{display_format_value_floor, is_to_string_shape};
use crate::{strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "to_string",
        &["method", "transparent_term"],
        recognize,
    );

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if !is_to_string_shape(expr) {
        return None;
    }
    Some(Box::new(ToStringTermSugar {
        receiver: SugarBody::format_value(&call.receiver, fcx),
    }))
}

struct ToStringTermSugar {
    receiver: SugarBody<FormatValueFloor>,
}

impl Sugar for ToStringTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.reduce_format_value(ctx) {
            crate::sugar::factory::FloorRead::Complete(value) => value,
            crate::sugar::factory::FloorRead::Incomplete(effect) => {
                return Outcome::Incomplete(effect)
            }
        };
        match display_format_value_floor(&receiver) {
            Ok(Some(value)) => Outcome::Complete(Desugared::Term(str_const(value))),
            Ok(None) => {
                panic!("to_string receiver did not render through the format-value floor")
            }
            Err(reason) => panic!("to_string formatter could not render its floor: {reason}"),
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use sugar_ir_symbolic::{ConstValue, Term};
    use syn::{Expr, Item};

    use super::*;
    use crate::{
        sugar_ctx, FloatWidthScope, LiftOptions, ReductionCtx, TemporalPlan, TemporalScope,
    };

    fn run(src: &str) -> Outcome {
        let expr: Expr = syn::parse_str(src).expect("expr parses");
        let scope = TemporalScope::new("to-string-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = recognize(&expr, &fcx).expect("to_string sugar should recognize");
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        node.desugar(&ctx)
    }

    fn run_with_binding(src: &str, name: &str, init: &str) -> Outcome {
        let expr: Expr = syn::parse_str(src).expect("expr parses");
        let mut scope = TemporalScope::new("to-string-test", TemporalPlan::default());
        scope.record_let_binding(name, syn::parse_str(init).expect("binding parses"));
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = recognize(&expr, &fcx).expect("to_string sugar should recognize");
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        node.desugar(&ctx)
    }

    #[test]
    fn format_args_to_string_reduces_through_format_value_floor() {
        let Outcome::Complete(Desugared::Term(term)) =
            run(r#"format_args!("{}/{}", 10, 20).to_string()"#)
        else {
            panic!("format_args!.to_string() should complete to a string term");
        };
        let Term::Const {
            value: ConstValue::String(value),
            ..
        } = term.as_ref()
        else {
            panic!("expected string const, got {term:?}");
        };
        assert_eq!(value, "10/20");
    }

    #[test]
    fn bound_format_args_to_string_reduces_through_format_value_floor() {
        let Outcome::Complete(Desugared::Term(term)) =
            run_with_binding("a.to_string()", "a", r#"format_args!("hello {}", "there")"#)
        else {
            panic!("bound format_args!.to_string() should complete to a string term");
        };
        let Term::Const {
            value: ConstValue::String(value),
            ..
        } = term.as_ref()
        else {
            panic!("expected string const, got {term:?}");
        };
        assert_eq!(value, "hello there");
    }
}
