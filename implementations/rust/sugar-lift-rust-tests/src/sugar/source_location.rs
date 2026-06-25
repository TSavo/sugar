// SPDX-License-Identifier: Apache-2.0
//
// Source-location runtime methods over `Location::caller()`.
//
// `file!()` is a text literal owned by macro-term sugar. In contrast,
// `Location::caller().file()` / `.line()` / `.column()` observe the runtime
// callsite location and must not fall through to the generic method EUF bridge.

use syn::Expr;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::{source_location_runtime_reason, token_key, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("source_location", &["method"], recognize);

pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    source_location_runtime_reason(expr)?;
    Some(Box::new(SourceLocationSugar {
        boundary: token_key(expr),
    }))
}

struct SourceLocationSugar {
    boundary: String,
}

impl Sugar for SourceLocationSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::SourceLocation {
            boundary: self.boundary.clone(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        sugar_ctx, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, TemporalPlan, TemporalScope,
    };

    fn run(src: &str) -> Outcome {
        let expr: Expr = syn::parse_str(src).expect("parse expr");
        let scope = TemporalScope::new("source-location-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = recognize(&expr, &fcx).expect("recognized source-location method");
        let items = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        node.desugar(&ctx)
    }

    #[test]
    fn location_caller_methods_are_named_runtime_boundaries() {
        match run("Location::caller().file()") {
            Outcome::Incomplete(effect) => {
                let reason = effect.reason();
                assert!(
                    reason.contains("source location runtime-determined"),
                    "source-location method must own a named runtime refusal: {reason}"
                );
            }
            Outcome::Complete(_) => panic!("source-location method must not complete"),
        }
    }

    #[test]
    fn file_macro_is_not_source_location_method_sugar() {
        let expr: Expr = syn::parse_str("file!()").expect("parse expr");
        let scope = TemporalScope::new("source-location-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        assert!(
            recognize(&expr, &fcx).is_none(),
            "literal file! macro belongs to macro_term sugar, not source-location runtime sugar"
        );
    }
}
