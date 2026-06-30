// SPDX-License-Identifier: Apache-2.0
//
// Atomic `.load(..)` over a non-path receiver is a runtime state boundary.

use syn::Expr;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::{simple_path_name, token_key, Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("atomic_load", &["method"], recognize);

pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "load" || call.args.len() != 1 {
        return None;
    }
    if simple_path_name(&call.receiver).is_some() {
        return None;
    }
    Some(Box::new(AtomicLoadSugar {
        boundary: token_key(expr),
    }))
}

struct AtomicLoadSugar {
    boundary: String,
}

impl Sugar for AtomicLoadSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::AtomicLoad {
            boundary: self.boundary.clone(),
        })
    }
}
