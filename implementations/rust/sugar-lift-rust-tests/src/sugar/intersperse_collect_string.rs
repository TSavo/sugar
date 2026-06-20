// SPDX-License-Identifier: Apache-2.0
//
// `IntersperseCollectStringSugar`: stdlib string collection sugar for
// `<literal seq>.map(|x| x.to_string()).intersperse(<literal sep>).collect::<String>()`.
// This owns only the terminal string materialization. The sequence receiver is still
// built through the factory so array/range/slice/iterator sugar compose normally.

use sugar_ir_symbolic::str_const;
use syn::{Expr, GenericArgument, Lit, Type};
use tracing::debug;

use crate::sugar::factory::{build_composite, SugarBuildCtx};
use crate::sugar::method_family;
use crate::{
    closure_single_param_ident, strip_refs_groups, ConstVal, Desugared, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("intersperse_collect_string", recognize);

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

    let Expr::MethodCall(intersperse_call) = strip_refs_groups(&collect_call.receiver) else {
        return None;
    };
    if intersperse_call.method != "intersperse" || intersperse_call.args.len() != 1 {
        return None;
    }
    let sep = literal_owned_string(&intersperse_call.args[0])?;

    let Expr::MethodCall(map_call) = strip_refs_groups(&intersperse_call.receiver) else {
        return None;
    };
    if map_call.method != "map" || map_call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(closure) = strip_refs_groups(&map_call.args[0]) else {
        return None;
    };
    recognizes_to_string_closure(closure)?;
    if !method_family::resolves_literal_sequence(&map_call.receiver, fcx.let_inits()) {
        return None;
    }

    debug!(
        target: "sugar_lift_rust_tests::sugar::intersperse_collect_string",
        sep = %sep,
        "recognized literal intersperse collect string"
    );
    Some(Box::new(IntersperseCollectStringSugar {
        seq: build_composite(&map_call.receiver, fcx),
        sep,
    }))
}

struct IntersperseCollectStringSugar {
    seq: Box<dyn Sugar>,
    sep: String,
}

impl Sugar for IntersperseCollectStringSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.seq.desugar(ctx).dug()?.into_seq()?;
            let parts = seq
                .iter()
                .map(|elem| elem.value.as_ref().and_then(const_value_to_string))
                .collect::<Option<Vec<_>>>()?;
            let joined = parts.join(&self.sep);
            debug!(
                target: "sugar_lift_rust_tests::sugar::intersperse_collect_string",
                len = parts.len(),
                "literal intersperse collect string reduced"
            );
            Some(Desugared::Term(str_const(joined)))
        })())
    }
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

fn recognizes_to_string_closure(closure: &syn::ExprClosure) -> Option<()> {
    if closure.inputs.len() != 1 {
        return None;
    }
    let param = closure_single_param_ident(&closure.inputs[0])?;
    let body = closure_body_expr(closure)?;
    let Expr::MethodCall(call) = strip_refs_groups(body) else {
        return None;
    };
    if call.method != "to_string" || !call.args.is_empty() {
        return None;
    }
    let receiver = strip_refs_groups(&call.receiver);
    matches!(
        receiver,
        Expr::Path(path) if path.path.get_ident().is_some_and(|ident| ident == param.as_str())
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

fn literal_owned_string(expr: &Expr) -> Option<String> {
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => match &lit.lit {
            Lit::Str(s) => Some(s.value()),
            _ => None,
        },
        Expr::MethodCall(call)
            if matches!(call.method.to_string().as_str(), "to_owned" | "to_string")
                && call.args.is_empty() =>
        {
            literal_owned_string(&call.receiver)
        }
        _ => None,
    }
}

fn const_value_to_string(value: &ConstVal) -> Option<String> {
    Some(match value {
        ConstVal::Int(n) => n.to_string(),
        ConstVal::PrimitiveInt { .. } => value.as_int()?.to_string(),
        ConstVal::UInt128(n) => n.to_string(),
        ConstVal::Bool(b) => b.to_string(),
        ConstVal::Char(c) => c.to_string(),
        ConstVal::UnitPath(path) => path.clone(),
        ConstVal::Tuple(_) => return None,
    })
}
