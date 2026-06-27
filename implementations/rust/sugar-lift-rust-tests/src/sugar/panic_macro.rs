// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for builtin `panic!`.
//
// A builtin panic macro is not a source-visible `macro_rules!` body this lifter can expand.
// It diverges by unwinding or aborting at runtime, so the term position owns a typed
// side-effect boundary instead of falling into the generic macro fallback.

use syn::Expr;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("panic_macro", &["macro_term"], recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(expr_macro) = expr else {
        return None;
    };
    let name = expr_macro.mac.path.segments.last()?.ident.to_string();
    if name != "panic" || fcx.scope().macro_registry().lookup(&name).is_some() {
        return None;
    }
    Some(Box::new(PanicMacroSugar {
        boundary: token_key(expr),
    }))
}

struct PanicMacroSugar {
    boundary: String,
}

impl Sugar for PanicMacroSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::PanicMacro {
            boundary: self.boundary.clone(),
        })
    }
}
