// SPDX-License-Identifier: Apache-2.0
//
// `RangeBoundsContainsSugar`: a bound `RangeBounds` tuple receiver (`r.contains(&x)`,
// where `r = (Bound::Included(..), Bound::Excluded(..))`) is a trait-surface boundary.
// The receiver and needle children are still constructed as terms and reduced first;
// any child effect bubbles unchanged. If both children complete, the `RangeBounds`
// surface itself owns the named refusal instead of falling through `method` into a
// Composite factory gap for the tuple receiver.

use quote::ToTokens;
use syn::{Expr, ExprPath};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::{simple_path_name, strip_refs_groups, Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("range_bounds_contains", &["method"], recognize);

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.method != "contains" || call.args.len() != 1 {
        return None;
    }
    let receiver_name = simple_path_name(&call.receiver)?;
    let init = fcx
        .let_inits()
        .get(&receiver_name)
        .copied()
        .or_else(|| fcx.scope().stable_let_binding_for_term(&receiver_name))?;
    if !is_range_bounds_tuple(init) {
        return None;
    }

    Some(Box::new(RangeBoundsContainsSugar {
        receiver_name,
        receiver: SugarBody::term(&call.receiver, fcx),
        needle: SugarBody::term(&call.args[0], fcx),
    }))
}

struct RangeBoundsContainsSugar {
    receiver_name: String,
    receiver: SugarBody<TermFloor>,
    needle: SugarBody<TermFloor>,
}

impl Sugar for RangeBoundsContainsSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.receiver.reduce(ctx) {
            Outcome::Complete(desugared) => {
                desugared.into_term().unwrap_or_else(|| {
                    panic!("RangeBounds receiver completed as non-term; write more Sugar")
                });
            }
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        }
        match self.needle.reduce(ctx) {
            Outcome::Complete(desugared) => {
                desugared.into_term().unwrap_or_else(|| {
                    panic!("RangeBounds contains needle completed as non-term; write more Sugar")
                });
            }
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        }
        Outcome::Incomplete(Effect::RangeBoundsRuntimeValue {
            boundary: self.receiver_name.clone(),
        })
    }
}

fn is_range_bounds_tuple(expr: &Expr) -> bool {
    let Expr::Tuple(tuple) = strip_refs_groups(expr) else {
        return false;
    };
    tuple.elems.len() == 2 && tuple.elems.iter().all(is_bound_expr)
}

fn is_bound_expr(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Call(call) => is_bound_ctor_path(&call.func),
        Expr::Path(path) => is_bound_variant_path(path, "Unbounded"),
        _ => false,
    }
}

fn is_bound_ctor_path(expr: &Expr) -> bool {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return false;
    };
    is_bound_variant_path(path, "Included") || is_bound_variant_path(path, "Excluded")
}

fn is_bound_variant_path(path: &ExprPath, variant: &str) -> bool {
    if path.qself.is_some() || path.path.segments.last().is_none_or(|s| s.ident != variant) {
        return false;
    }
    path.path
        .segments
        .iter()
        .any(|segment| segment.ident == "Bound")
        || path.path.to_token_stream().to_string() == variant
}
