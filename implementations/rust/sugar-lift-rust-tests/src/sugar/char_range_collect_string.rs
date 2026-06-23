// SPDX-License-Identifier: Apache-2.0
//
// `CharRangeCollectStringSugar`: stdlib string collection sugar for
// `<literal int range>.map(|b| b as char).collect::<String>()`. The Rust compiler
// has already accepted the cast; we only materialize the finite literal range into
// the exact string it denotes.

use std::collections::BTreeMap;

use sugar_ir_symbolic::str_const;
use syn::{Expr, GenericArgument, Type};
use tracing::debug;

use crate::sugar::factory::{build_composite, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
use crate::sugar::method_family;
use crate::{
    closure_single_param_ident, strip_refs_groups, ConstVal, Desugared, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("char_range_collect_string", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(collect_call) = strip_refs_groups(expr) else {
        return None;
    };
    if collect_call.method != "collect"
        || !collect_call.args.is_empty()
        || !collects_string(collect_call)
    {
        return None;
    }

    let Expr::MethodCall(map_call) = strip_refs_groups(&collect_call.receiver) else {
        return None;
    };
    if map_call.method != "map" || map_call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(closure) = strip_refs_groups(&map_call.args[0]) else {
        return None;
    };
    recognizes_char_cast_closure(closure)?;
    if !method_family::resolves_literal_sequence(&map_call.receiver, fcx.let_inits()) {
        return None;
    }

    debug!(
        target: "sugar_lift_rust_tests::sugar::char_range_collect_string",
        "recognized literal char range collect string"
    );
    Some(Box::new(CharRangeCollectStringSugar {
        seq_expr: (*map_call.receiver).clone(),
    }))
}

struct CharRangeCollectStringSugar {
    seq_expr: Expr,
}

impl Sugar for CharRangeCollectStringSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = build_composite_in_ctx(&self.seq_expr, ctx)
                .desugar(ctx)
                .complete()?
                .into_seq()?;
            let mut out = String::with_capacity(seq.len());
            for elem in seq {
                let n = elem.value.as_ref().and_then(ConstVal::as_int)?;
                let ch = u32::try_from(n).ok().and_then(char::from_u32)?;
                out.push(ch);
            }
            debug!(
                target: "sugar_lift_rust_tests::sugar::char_range_collect_string",
                len = out.chars().count(),
                "literal char range collect string reduced"
            );
            Some(Desugared::Term(str_const(out)))
        })())
    }
}

fn build_composite_in_ctx(expr: &Expr, ctx: &SugarCtx) -> Box<dyn Sugar> {
    let stable = stable_let_bindings(ctx.scope);
    let let_inits = stable_let_refs(&stable);
    let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
    build_composite(expr, &fcx)
}

fn stable_let_refs(stable: &BTreeMap<String, Expr>) -> BTreeMap<String, &Expr> {
    stable
        .iter()
        .map(|(name, init)| (name.clone(), init))
        .collect()
}

fn collects_string(call: &syn::ExprMethodCall) -> bool {
    let Some(turbofish) = &call.turbofish else {
        return false;
    };
    if turbofish.args.len() != 1 {
        return false;
    }
    matches!(
        turbofish.args.first(),
        Some(GenericArgument::Type(Type::Path(path)))
            if path.qself.is_none()
                && path.path.segments.last().is_some_and(|seg| seg.ident == "String")
    )
}

fn recognizes_char_cast_closure(closure: &syn::ExprClosure) -> Option<()> {
    if closure.inputs.len() != 1 {
        return None;
    }
    let param = closure_single_param_ident(&closure.inputs[0])?;
    let body = closure_body_expr(closure)?;
    let Expr::Cast(cast) = strip_refs_groups(body) else {
        return None;
    };
    if !matches!(strip_refs_groups(&cast.expr), Expr::Path(path) if path.path.get_ident().is_some_and(|ident| ident == param.as_str()))
    {
        return None;
    }
    matches!(
        cast.ty.as_ref(),
        Type::Path(path)
            if path.qself.is_none()
                && path.path.segments.last().is_some_and(|seg| seg.ident == "char")
    )
    .then_some(())
}

fn closure_body_expr(closure: &syn::ExprClosure) -> Option<&Expr> {
    match strip_refs_groups(&closure.body) {
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [syn::Stmt::Expr(expr, None)] => Some(expr),
            _ => None,
        },
        other => Some(other),
    }
}
