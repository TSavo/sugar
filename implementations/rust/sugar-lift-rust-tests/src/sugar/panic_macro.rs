// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for builtin `panic!`.
//
// A builtin panic macro is not a source-visible `macro_rules!` body this lifter can expand.
// It diverges by unwinding or aborting at runtime, so the term position owns a typed
// side-effect boundary instead of falling into the generic macro fallback.

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::route_raises_operation::RouteRaisesOperation;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("panic_macro", &["macro_term"], recognize);

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // `macro_name()` returns the last-segment ident without escaping to raw syn.
    let name = frag.macro_name()?;
    if name != "panic" || fcx.scope().macro_registry().lookup(&name).is_some() {
        return None;
    }
    Some(Box::new(PanicMacroSugar {
        boundary: frag.token_str(),
    }))
}

struct PanicMacroSugar {
    boundary: String,
}

impl Sugar for PanicMacroSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let outcome = Outcome::Incomplete(Effect::PanicMacro {
            boundary: self.boundary.clone(),
        });
        RouteRaisesOperation::new(Vec::new(), "PanicMacro")
            .route_incomplete_with_scope(outcome, ctx.scope)
    }
}
