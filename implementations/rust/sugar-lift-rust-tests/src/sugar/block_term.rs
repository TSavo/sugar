// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for the VALUE-TRANSPARENT blocks `Expr::Unsafe` (`unsafe { expr }`)
// and `Expr::Block` (`{ expr }`): a single-tail block is the value of its tail. The
// recognizer captures that raw tail expression; `desugar` recurses through
// `build_term` when the binding context is live. Any other block shape is refused by
// name. Byte-identical to the `Expr::Unsafe`/`Expr::Block` arms of the old fat factory.

use std::collections::BTreeMap;

use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::term_leaf::reasoned_incomplete;
use crate::sugar::unsafe_memory;
use crate::{substitute_expr, token_key, ExprBindings, Outcome, Sugar, SugarCtx};
use syn::{Expr, Item, Pat, Stmt};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("block_term", recognize);

/// TERM recognizer for `Expr::Unsafe` / `Expr::Block`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Unsafe(block) => Some(if let Some(tail) = inert_prefix_tail(&block.block.stmts) {
            BlockTermSugar::boxed(tail.clone(), fcx)
        } else if let Some(tail) = let_prefix_tail_expr(&block.block.stmts) {
            BlockTermSugar::boxed(tail, fcx)
        } else if unsafe_memory::unsafe_memory_boundary_stmts(&block.block.stmts) {
            reasoned_incomplete(unsafe_memory::runtime_memory_reason(&token_key(expr)))
        } else {
            reasoned_incomplete(format!("unsupported term `{}`", token_key(expr)))
        }),
        Expr::Block(block) => Some(
            inert_prefix_tail(&block.block.stmts)
                .map(|tail| BlockTermSugar::boxed(tail.clone(), fcx))
                .or_else(|| {
                    let_prefix_tail_expr(&block.block.stmts)
                        .map(|tail| BlockTermSugar::boxed(tail, fcx))
                })
                .unwrap_or_else(|| {
                    reasoned_incomplete(format!("unsupported term `{}`", token_key(expr)))
                }),
        ),
        _ => None,
    }
}

struct BlockTermSugar {
    tail: Expr,
    let_inits: BTreeMap<String, Expr>,
}

impl BlockTermSugar {
    fn boxed(tail: Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
        Box::new(Self {
            tail,
            let_inits: capture_let_inits(fcx),
        })
    }
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

fn merge_let_inits<'a>(
    stable: &'a BTreeMap<String, Expr>,
    captured: &'a BTreeMap<String, Expr>,
) -> BTreeMap<String, &'a Expr> {
    stable
        .iter()
        .map(|(name, init)| (name.clone(), init))
        .chain(captured.iter().map(|(name, init)| (name.clone(), init)))
        .collect()
}

impl Sugar for BlockTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
        let let_inits = merge_let_inits(&stable, &self.let_inits);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        build_term(&self.tail, &fcx).desugar(ctx)
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
