// SPDX-License-Identifier: Apache-2.0
//
// ClosureSugar -- invocation-time closure execution.
//
// Closure CONSTRUCTION is inert: `|| { assert!(..) }` by itself does not execute the
// body. Closure INVOCATION is different. If execution reaches a direct source closure
// call, the closure body runs to completion before the next statement. This sugar owns
// that compiler axiom and then gets out of the way: it turns the closure body back into
// statements and lets the normal collector/factory recurse through them.
//
// The callable-param bridge is the same story one level out. A source-backed driver
// such as `fn driver<F: Fn()>(f: F) { f(); f(); }` carries the precondition bridge
// `not(panic(call:f))`. When the callsite supplies a visible source closure
// (`driver(|| { assert_eq!(..); })`), this sugar beta-reduces `f := <closure>` in the
// driver body and runs the same exact-or-bail trial used by CallsiteSugar. The result is
// temporal: each `f();` statement re-enters as a distinct direct closure invocation.

use std::collections::{BTreeMap, HashSet};

use syn::{Expr, ItemFn, Stmt};

use crate::sugar::callsite::{desugar_substituted_stmts, CallsiteOutcome};
use crate::{
    cfg_resolve, helper_param_names, simple_call_name, simple_pat_name, substitute_stmts,
    CfgDisposition, ExprBindings, FactoryAuditLog, FloatWidthScope, LiftOptions, ReductionCtx,
    MAX_MACRO_EXPANSION_DEPTH,
};

pub(crate) struct ClosureSugar {
    stmts: Vec<Stmt>,
}

pub(crate) struct ClosureDriverSugar<'a> {
    helper: &'a ItemFn,
    name: String,
    closed_args: ExprBindings,
}

impl ClosureSugar {
    pub(crate) fn decompose_invocation(expr: &Expr) -> Option<Self> {
        let Expr::Call(call) = strip_wrappers(expr) else {
            return None;
        };
        let closure = closure_func(call.func.as_ref())?;
        if closure.inputs.len() != call.args.len() {
            return None;
        }
        let mut bindings = ExprBindings::new();
        for (pat, arg) in closure.inputs.iter().zip(call.args.iter()) {
            let name = simple_pat_name(pat)?;
            bindings.insert(name, arg.clone());
        }
        let body_stmts = closure_body_stmts(closure);
        let stmts = substitute_stmts(&body_stmts, &bindings);
        tracing::debug!(
            target: "sugar_lift_rust_tests::closure",
            params = closure.inputs.len(),
            stmts = stmts.len(),
            "ClosureSugar recognized direct closure invocation"
        );
        Some(Self { stmts })
    }

    pub(crate) fn stmts(&self) -> &[Stmt] {
        &self.stmts
    }
}

impl<'a> ClosureDriverSugar<'a> {
    pub(crate) fn decompose(
        expr: &Expr,
        local_fns: &BTreeMap<String, &'a ItemFn>,
        reducer: &ReductionCtx<'a>,
        options: &LiftOptions,
        macro_depth: usize,
    ) -> Option<Self> {
        if macro_depth >= MAX_MACRO_EXPANSION_DEPTH {
            return None;
        }
        let Expr::Call(call) = strip_wrappers(expr) else {
            return None;
        };
        if !call
            .args
            .iter()
            .any(|arg| matches!(strip_wrappers(arg), Expr::Closure(_)))
        {
            return None;
        }
        let name = simple_call_name(call)?;
        let helper: &'a ItemFn = match local_fns.get(name.as_str()) {
            Some(f) => f,
            None => reducer.function(&name).ok()??,
        };
        if !matches!(cfg_resolve(&helper.attrs, options), CfgDisposition::Present) {
            return None;
        }
        let params = helper_param_names(helper).ok()?;
        if params.len() != call.args.len() {
            return None;
        }
        let mut closed_args = ExprBindings::new();
        for (param, arg) in params.into_iter().zip(call.args.iter()) {
            closed_args.insert(param, arg.clone());
        }
        tracing::debug!(
            target: "sugar_lift_rust_tests::closure",
            helper = %name,
            closure_args = call
                .args
                .iter()
                .filter(|arg| matches!(strip_wrappers(arg), Expr::Closure(_)))
                .count(),
            "ClosureSugar recognized source-backed closure driver"
        );
        Some(Self {
            helper,
            name,
            closed_args,
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn desugar(
        &self,
        local_scope: &str,
        stmt_idx: usize,
        options: &LiftOptions,
        reducer: &ReductionCtx<'_>,
        float_widths: &mut FloatWidthScope,
        reduced_helpers: &HashSet<String>,
        macro_depth: usize,
        factory_audits: Option<&FactoryAuditLog>,
    ) -> CallsiteOutcome {
        desugar_substituted_stmts(
            &self.name,
            &self.helper.block.stmts,
            &self.closed_args,
            local_scope,
            stmt_idx,
            options,
            reducer,
            float_widths,
            reduced_helpers,
            macro_depth,
            factory_audits,
        )
    }
}

fn strip_wrappers(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(paren) => strip_wrappers(&paren.expr),
        Expr::Group(group) => strip_wrappers(&group.expr),
        _ => expr,
    }
}

fn closure_func(expr: &Expr) -> Option<&syn::ExprClosure> {
    match strip_wrappers(expr) {
        Expr::Closure(closure) => Some(closure),
        _ => None,
    }
}

fn closure_body_stmts(closure: &syn::ExprClosure) -> Vec<Stmt> {
    match closure.body.as_ref() {
        Expr::Block(block) => block.block.stmts.clone(),
        Expr::Unsafe(unsafe_expr) => unsafe_expr.block.stmts.clone(),
        Expr::Const(const_expr) => const_expr.block.stmts.clone(),
        Expr::Macro(expr_macro) => vec![Stmt::Expr(Expr::Macro(expr_macro.clone()), None)],
        other => vec![Stmt::Expr(other.clone(), None)],
    }
}
