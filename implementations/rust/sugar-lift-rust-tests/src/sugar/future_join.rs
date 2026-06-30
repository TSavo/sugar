// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for std `future::join!`.
//
// `join!` is a future-producing std macro, not a source-visible `macro_rules!`
// body this lifter owns. This sugar claims the macro before the generic macro
// fallback so the boundary is typed as future construction instead of becoming
// a macro-expansion construction gap.

use syn::Expr;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("future_join", &["macro_term"], recognize);

pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Macro(expr_macro) = expr else {
        return None;
    };
    expr_macro
        .mac
        .path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == "join")
        .then(|| {
            Box::new(FutureJoinSugar {
                boundary: token_key(expr),
            }) as Box<dyn Sugar>
        })
}

struct FutureJoinSugar {
    boundary: String,
}

impl Sugar for FutureJoinSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::FutureJoin {
            boundary: self.boundary.clone(),
        })
    }
}
