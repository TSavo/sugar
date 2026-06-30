// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for closed stdlib `<literal>.to_string()`. Unknown receivers
// decline so generic MethodSugar can continue digging the method-call universe.

use sugar_ir_symbolic::str_const;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::factory::{FormatValueFloor, SugarBody};
use crate::sugar::format::display_format_value_floor;
use crate::{Desugared, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "to_string",
        &["method", "transparent_term"],
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let srg = frag.strip_refs_groups();
    if srg.call_method_key()?.as_str() != "to_string" {
        return None;
    }
    if srg.call_arg_count() != 0 {
        return None;
    }
    let receiver = srg.call_receiver()?;
    Some(Box::new(ToStringTermSugar {
        receiver: SugarBody::format_value_frag(&receiver, fcx),
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

    #[test]
    fn from_src_recognizes_to_string_method() {
        let expr: Expr = syn::parse_str("x.to_string()").expect("parses");
        let frag = SourceFragment::expr(&expr, "<test>");
        assert_eq!(frag.observed(), "MethodCall");
        let scope = TemporalScope::new("from-src-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        // positive: bare to_string() with no args must recognize
        assert!(recognize(&frag, &fcx).is_some(), "to_string() with no args must recognize");
        // negative: different method must not recognize
        let clone_expr: Expr = syn::parse_str("x.clone()").expect("parses");
        assert!(recognize(&SourceFragment::expr(&clone_expr, "<test>"), &fcx).is_none(),
            "clone() must not recognize");
        // negative: to_string with extra args must not recognize
        let extra: Expr = syn::parse_str("x.to_string(extra)").expect("parses");
        assert!(recognize(&SourceFragment::expr(&extra, "<test>"), &fcx).is_none(),
            "to_string(arg) must not recognize");
    }

    fn run(src: &str) -> Outcome {
        let expr: Expr = syn::parse_str(src).expect("expr parses");
        let scope = TemporalScope::new("to-string-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = { let _frag = SourceFragment::expr(&expr, "<src>"); recognize(&_frag, &fcx) }.expect("to_string sugar should recognize");
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
        let node = { let _frag = SourceFragment::expr(&expr, "<src>"); recognize(&_frag, &fcx) }.expect("to_string sugar should recognize");
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
