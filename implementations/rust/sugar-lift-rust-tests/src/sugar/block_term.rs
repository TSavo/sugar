// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for value blocks (`unsafe { .. }` / `{ .. }`). Construction only
// captures the raw statement list. The reduction walk decides at desugar time: child
// statement effects bubble, transparent tail expressions reduce recursively, and any
// unsupported block structure stays a loud gap.

use std::collections::BTreeMap;

use crate::sugar::claim::SugarRole;
use crate::sugar::factory::SugarBuildCtx;
use crate::{substitute_expr, token_key, ExprBindings, Outcome, Sugar, SugarCtx};
use syn::{Expr, Item, Pat, Stmt};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("block_term", recognize);

/// TERM recognizer for `Expr::Unsafe` / `Expr::Block`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Unsafe(block) => Some(BlockTermSugar::boxed(expr, block.block.stmts.clone(), fcx)),
        Expr::Block(block) => Some(BlockTermSugar::boxed(expr, block.block.stmts.clone(), fcx)),
        _ => None,
    }
}

struct BlockTermSugar {
    site: String,
    stmts: Vec<Stmt>,
    let_inits: BTreeMap<String, Expr>,
}

impl BlockTermSugar {
    fn boxed(site: &Expr, stmts: Vec<Stmt>, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
        Box::new(Self {
            site: token_key(site),
            stmts,
            let_inits: capture_let_inits(fcx),
        })
    }
}

impl Sugar for BlockTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let let_refs = captured_let_refs(&self.let_inits);
        if let Some(effect) = first_statement_effect(&self.stmts, ctx, &let_refs) {
            return Outcome::Incomplete(effect);
        }
        if let Some(tail) = inert_prefix_tail(&self.stmts) {
            return reduce_tail(tail, ctx, &let_refs);
        }
        if let Some(tail) = let_prefix_tail_expr(&self.stmts) {
            return reduce_tail(&tail, ctx, &let_refs);
        }
        panic!("unsupported term `{}`", self.site);
    }
}

fn inert_prefix_tail(stmts: &[Stmt]) -> Option<&Expr> {
    let (last, prefix) = stmts.split_last()?;
    if !prefix
        .iter()
        .all(|stmt| matches!(stmt, Stmt::Item(Item::Use(_))))
    {
        return None;
    }
    match last {
        Stmt::Expr(tail, None) => Some(tail),
        _ => None,
    }
}

fn let_prefix_tail_expr(stmts: &[Stmt]) -> Option<Expr> {
    let (last, prefix) = stmts.split_last()?;
    let Stmt::Expr(tail, None) = last else {
        return None;
    };
    let mut bindings = ExprBindings::new();
    let mut saw_let = false;
    for stmt in prefix {
        match stmt {
            Stmt::Item(Item::Use(_)) => {}
            Stmt::Local(local) => {
                let init = local.init.as_ref()?;
                if init.diverge.is_some() {
                    return None;
                }
                let name = immutable_simple_binding(&local.pat)?;
                if bindings.contains_key(&name) {
                    return None;
                }
                let value = substitute_expr(&init.expr, &bindings);
                bindings.insert(name, value);
                saw_let = true;
            }
            _ => return None,
        }
    }
    saw_let.then(|| substitute_expr(tail, &bindings))
}

fn immutable_simple_binding(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(id) if id.subpat.is_none() && id.mutability.is_none() && id.by_ref.is_none() => {
            Some(id.ident.to_string())
        }
        Pat::Type(t) => immutable_simple_binding(&t.pat),
        Pat::Paren(p) => immutable_simple_binding(&p.pat),
        _ => None,
    }
}

fn first_statement_effect(
    stmts: &[Stmt],
    ctx: &SugarCtx,
    let_inits: &BTreeMap<String, &Expr>,
) -> Option<crate::Effect> {
    stmts.iter().find_map(|stmt| match stmt {
        Stmt::Macro(stmt_macro) => {
            let expr = Expr::Macro(syn::ExprMacro {
                attrs: stmt_macro.attrs.clone(),
                mac: stmt_macro.mac.clone(),
            });
            statement_effect(&expr, ctx, let_inits)
        }
        Stmt::Expr(expr, Some(_)) => statement_effect(expr, ctx, let_inits),
        Stmt::Expr(expr @ Expr::Macro(_), None) => statement_effect(expr, ctx, let_inits),
        Stmt::Expr(_, None) | Stmt::Local(_) | Stmt::Item(_) => None,
    })
}

fn statement_effect(
    expr: &Expr,
    ctx: &SugarCtx,
    let_inits: &BTreeMap<String, &Expr>,
) -> Option<crate::Effect> {
    let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, let_inits);
    if !crate::sugar::factory::has_expr_role(expr, &fcx, SugarRole::StatementEffect) {
        return None;
    }
    let node = crate::sugar::factory::build_expr(expr, &fcx, SugarRole::StatementEffect);
    match node.desugar(ctx) {
        Outcome::Incomplete(effect) => Some(effect),
        Outcome::Complete(_) => None,
    }
}

fn reduce_tail(tail: &Expr, ctx: &SugarCtx, let_inits: &BTreeMap<String, &Expr>) -> Outcome {
    let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, let_inits);
    crate::sugar::factory::build_expr(tail, &fcx, SugarRole::Term).desugar(ctx)
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, expr)| (name.clone(), (*expr).clone()))
        .collect()
}

fn captured_let_refs(captured: &BTreeMap<String, Expr>) -> BTreeMap<String, &Expr> {
    captured
        .iter()
        .map(|(name, expr)| (name.clone(), expr))
        .collect()
}
