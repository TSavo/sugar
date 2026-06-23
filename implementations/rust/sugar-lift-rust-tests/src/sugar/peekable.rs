// SPDX-License-Identifier: Apache-2.0
//
// `peekable`: the `.peekable()` adaptor. `Iterator::peekable` yields the SAME items in
// the SAME order -- it only ADDS `peek`/`next_if` capability; it never alters the value
// stream. So over a finite literal sequence it is the IDENTITY adaptor, reusing
// `IdentitySugar` over the receiver's composite. This is the outermost-call recognizer
// (so `build_composite([..].iter().peekable())` resolves); `peel_fold_adaptors` carries
// the same identity treatment when `.peekable()` sits inside a longer adaptor chain
// (e.g. the `while let next_if` rewrite's `<seq>.iter().peekable().take_while(..)`).

use syn::{Expr, ExprMacro};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::identity::IdentitySugar;
use crate::sugar::method_family;
use crate::{
    parse_macro_args, simple_path_name, strip_refs_groups, Effect, Outcome, Sugar, SugarCtx,
};

pub(crate) const ASSERTION_SURFACE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::with_ordering(
    "peekable_runtime_assertion_surface",
    SugarRole::AssertionSurface,
    &[
        "assertion_surface_relation_macro",
        "assertion_surface_assert_macro",
    ],
    recognize_assertion_surface,
);

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::composite("peekable", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method == "peekable" && call.args.is_empty() {
        return Some(Box::new(IdentitySugar {
            inner: method_family::build_literal_sequence_composite(&call.receiver, fcx)?,
        }));
    }
    None
}

fn recognize_assertion_surface(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(ExprMacro { mac, .. }) = expr else {
        return None;
    };
    if mac.path.segments.last()?.ident != "assert_eq" {
        return None;
    }
    let args = parse_macro_args(mac.tokens.clone()).ok()?;
    if args.exprs.len() < 2 {
        return None;
    }
    let receiver = peekable_none_boundary(&args.exprs[0], &args.exprs[1], fcx)
        .or_else(|| peekable_none_boundary(&args.exprs[1], &args.exprs[0], fcx))?;
    Some(Box::new(PeekableRuntimeRefusalSugar { receiver }))
}

fn peekable_none_boundary(lhs: &Expr, rhs: &Expr, fcx: &SugarBuildCtx) -> Option<String> {
    if !is_none_path(rhs) {
        return None;
    }
    let Expr::MethodCall(call) = strip_refs_groups(lhs) else {
        return None;
    };
    if !call.args.is_empty() || !matches!(call.method.to_string().as_str(), "peek" | "last") {
        return None;
    }
    let name = simple_path_name(&call.receiver)?;
    if fcx.scope().is_consumed_iterator_local(&name)
        || fcx
            .scope()
            .unknown_iterator_consumption_reason(&name)
            .is_some()
        || (fcx.scope().is_mut_local(&name) && runtime_peekable_binding(&name, fcx))
    {
        return Some(name);
    }
    None
}

fn runtime_peekable_binding(name: &str, fcx: &SugarBuildCtx) -> bool {
    let Some(init) = fcx
        .scope()
        .let_bindings_iter()
        .find_map(|(binding, init)| (binding == name).then_some(init))
    else {
        return false;
    };
    let Expr::MethodCall(call) = strip_refs_groups(init) else {
        return false;
    };
    call.method == "peekable"
        && call.args.is_empty()
        && !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits())
}

fn is_none_path(expr: &Expr) -> bool {
    matches!(
        strip_refs_groups(expr),
        Expr::Path(path)
            if path.qself.is_none()
                && path
                    .path
                    .segments
                    .last()
                    .is_some_and(|segment| segment.ident == "None")
    )
}

struct PeekableRuntimeRefusalSugar {
    receiver: String,
}

impl Sugar for PeekableRuntimeRefusalSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Hit(Effect::Unsupported {
            reason: format!("runtime slice source, not literal `{}`", self.receiver),
        })
    }
}
