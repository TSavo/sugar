// SPDX-License-Identifier: Apache-2.0
//
// Side-effecting `for` statement sugar.

use syn::{Expr, ExprForLoop};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::{forall, statement_position};
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::composite_before("for_loop_mutation", &["forall_loop"], recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::ForLoop(for_loop) = expr else {
        return None;
    };

    if forall::decompose_for_loop(for_loop, fcx.scope(), fcx.let_inits(), fcx).is_some() {
        return None;
    }
    loop_has_mutation_boundary(for_loop).then(|| {
        Box::new(ForLoopMutationSugar {
            boundary: token_key(expr),
        }) as Box<dyn Sugar>
    })
}

struct ForLoopMutationSugar {
    boundary: String,
}

impl Sugar for ForLoopMutationSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::Mutation {
            boundary: self.boundary.clone(),
        })
    }
}

fn loop_has_mutation_boundary(for_loop: &ExprForLoop) -> bool {
    statement_position::has_runtime_boundary(&for_loop.expr)
        || statement_position::has_runtime_boundary(&Expr::Block(syn::ExprBlock {
            attrs: Vec::new(),
            label: None,
            block: for_loop.body.clone(),
        }))
}
