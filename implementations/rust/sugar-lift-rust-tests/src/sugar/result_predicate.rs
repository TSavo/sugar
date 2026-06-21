// SPDX-License-Identifier: Apache-2.0
//
// `ResultPredicateSugar`: `.is_ok()` / `.is_err()` over a grounded std `Result`
// constructor. The sibling of `option_predicate` (`is_some`/`is_none`): once the
// receiver bottoms out to `res:ok(_)` or `res:err(_)`, the predicate is a literal
// bool, replacing the opaque `method:is_ok` EUF var (no teeth).
//
// EXACT-OR-NONE AT RECOGNIZE. We claim ONLY when the receiver is an integer
// `try_from(literal)` that DEFINITELY folds to a `res:ok`/`res:err` (see
// `try_from`, whose `desugar` is unconditional). We do NOT accept bare
// `Ok(..)`/`Err(..)` here: a non-literal/effectful inner could make the build
// `Hit`/not-ground, turning a recognize-ACCEPT into a desugar-BAIL -- and a bailed
// Primary becomes a REFUSAL (not opaque-EUF), which would REGRESS coverage in
// corpus context. A runtime/opaque receiver -> `None`, existing handling stands.
//
// TEETH. `u8::try_from(256u16).is_err()` grounds to `res:err` -> `Bool(true)`;
// `.is_ok()` -> `Bool(false)` (z3-UNSAT if asserted).

use sugar_ir_symbolic::Term;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::monadic::{RES_ERR, RES_OK};
use crate::{bool_const, strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "result_predicate",
    SugarRole::Term,
    SugarPriority::Primary,
    recognize,
);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let method = call.method.to_string();
    if !matches!(method.as_str(), "is_ok" | "is_err") || !call.args.is_empty() {
        return None;
    }
    if !is_known_result_source(&call.receiver) {
        return None;
    }
    Some(Box::new(ResultPredicateSugar {
        method,
        receiver: build_term(&call.receiver, fcx),
    }))
}

struct ResultPredicateSugar {
    method: String,
    receiver: Box<dyn Sugar>,
}

impl Sugar for ResultPredicateSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        let Some(is_ok) = result_presence(&receiver) else {
            return Outcome::from_opt(None);
        };
        let value = if self.method == "is_ok" { is_ok } else { !is_ok };
        debug!(
            target: "sugar_lift_rust_tests::sugar::result_predicate",
            method = self.method.as_str(),
            value,
            "resolved Result presence predicate stdlib axiom"
        );
        Outcome::Dug(Desugared::Term(bool_const(value)))
    }
}

/// `Some(true)` for `res:ok`, `Some(false)` for `res:err`, `None` otherwise.
fn result_presence(term: &Term) -> Option<bool> {
    match term {
        Term::Ctor { name, .. } if name == RES_OK => Some(true),
        Term::Ctor { name, .. } if name == RES_ERR => Some(false),
        _ => None,
    }
}

/// A receiver that grounds to a `Result` ctor: an `Ok(..)`/`Err(..)` constructor,
/// an integer `try_from(literal)` that folds to a `Result`.
///
/// EXACT-OR-NONE AT RECOGNIZE: we accept ONLY a `try_from` that DEFINITELY grounds
/// to `res:ok`/`res:err` (its `desugar` is unconditional). We deliberately do NOT
/// accept bare `Ok(..)`/`Err(..)` here: a non-literal/effectful inner can make the
/// monadic build `Hit` or not-ground, which would turn this recognize-ACCEPT into a
/// desugar-BAIL -- and a bailed Primary is a REFUSAL, not an opaque-EUF fallback, so
/// it would REGRESS coverage in corpus context. A shape we might bail on must be
/// DECLINED here, not accepted-then-bailed.
fn is_known_result_source(expr: &Expr) -> bool {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return false;
    };
    crate::sugar::try_from::folds_to_result(call)
}
