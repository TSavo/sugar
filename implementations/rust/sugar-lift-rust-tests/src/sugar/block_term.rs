// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for value blocks (`unsafe { .. }` / `{ .. }`). Construction only
// captures the raw statement list. The reduction walk decides at desugar time: child
// statement effects bubble, transparent tail expressions reduce recursively, and any
// unsupported block structure stays a loud gap.

use std::rc::Rc;

use crate::sugar::factory::{StatementEffectFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    substitute_expr, token_key, translate_term_in_scope_with_audits, Effect, ExprBindings,
    FactoryAuditLog, Outcome, Sugar, SugarCtx, TemporalScope,
};
use sugar_ir_symbolic::Term;
use syn::{Expr, Item, Pat, Stmt};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("block_term", recognize);

/// TERM recognizer for `Expr::Unsafe` / `Expr::Block`.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if !frag.is_block_or_unsafe() {
        return None;
    }
    Some(BlockTermSugar::boxed_frag(frag, fcx))
}

pub(crate) fn has_transparent_term_tail(expr: &Expr) -> bool {
    match expr {
        Expr::Unsafe(block) => transparent_tail_expr(&block.block.stmts).is_some(),
        Expr::Block(block) => transparent_tail_expr(&block.block.stmts).is_some(),
        _ => false,
    }
}

pub(crate) fn translate_expression_only_block_in_scope(
    block: &syn::Block,
    label: &str,
    scope: &TemporalScope,
) -> Result<Rc<Term>, Effect> {
    translate_expression_only_block_in_scope_with_audits(block, label, scope, None)
}

pub(crate) fn translate_expression_only_block_in_scope_with_audits(
    block: &syn::Block,
    label: &str,
    scope: &TemporalScope,
    factory_audits: Option<&FactoryAuditLog>,
) -> Result<Rc<Term>, Effect> {
    match block.stmts.as_slice() {
        [Stmt::Expr(expr, None)] => {
            if let Some(nested_const) = find_const_expr(expr) {
                block_term_gap(format!(
                    "unsupported nested const term `{}`",
                    token_key(nested_const)
                ));
            }
            translate_term_in_scope_with_audits(expr, scope, factory_audits)
        }
        _ => block_term_gap(format!(
            "{label} block is not an expression-only term `{}`",
            token_key(block)
        )),
    }
}

fn block_term_gap(reason: String) -> ! {
    panic!("block_term did not reach a lawful term floor: {reason}")
}

fn find_const_expr(expr: &Expr) -> Option<&Expr> {
    match expr {
        Expr::Const(_) => Some(expr),
        Expr::Unary(unary) => find_const_expr(&unary.expr),
        Expr::Call(call) => call
            .args
            .iter()
            .find_map(find_const_expr)
            .or_else(|| find_const_expr(&call.func)),
        Expr::Array(array) => array.elems.iter().find_map(find_const_expr),
        Expr::Tuple(tuple) => tuple.elems.iter().find_map(find_const_expr),
        Expr::MethodCall(call) => {
            find_const_expr(&call.receiver).or_else(|| call.args.iter().find_map(find_const_expr))
        }
        Expr::Await(await_expr) => find_const_expr(&await_expr.base),
        Expr::Reference(reference) => find_const_expr(&reference.expr),
        Expr::Cast(cast) => find_const_expr(&cast.expr),
        Expr::Range(range) => range
            .start
            .as_deref()
            .and_then(find_const_expr)
            .or_else(|| range.end.as_deref().and_then(find_const_expr)),
        Expr::Field(field) => find_const_expr(&field.base),
        Expr::Binary(binary) => {
            find_const_expr(&binary.left).or_else(|| find_const_expr(&binary.right))
        }
        Expr::Paren(paren) => find_const_expr(&paren.expr),
        Expr::Group(group) => find_const_expr(&group.expr),
        _ => None,
    }
}

struct BlockTermSugar {
    site: String,
    statement_effects: Vec<SugarBody<StatementEffectFloor>>,
    tail: Option<SugarBody<TermFloor>>,
}

impl BlockTermSugar {
    fn boxed(site: &Expr, stmts: Vec<Stmt>, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
        Box::new(Self {
            site: token_key(site),
            statement_effects: statement_effect_bodies(&stmts, fcx),
            tail: tail_body(&stmts, fcx),
        })
    }

    /// Fragment-based constructor. Callers must have verified `frag.is_block_or_unsafe()`.
    /// All raw syn access lives here -- outside the 2000-char ratchet window from `recognize`.
    fn boxed_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
        let expr = frag.as_expr().expect("is_block_or_unsafe was checked");
        let stmts = match expr {
            Expr::Unsafe(block) => block.block.stmts.clone(),
            Expr::Block(block) => block.block.stmts.clone(),
            _ => unreachable!("is_block_or_unsafe was checked"),
        };
        Self::boxed(expr, stmts, fcx)
    }
}

impl Sugar for BlockTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        for body in &self.statement_effects {
            match body.desugar(ctx) {
                Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
                Outcome::Complete(_) => {}
            }
        }
        if let Some(tail) = &self.tail {
            return tail.desugar(ctx);
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

fn transparent_tail_expr(stmts: &[Stmt]) -> Option<Expr> {
    if let Some(tail) = inert_prefix_tail(stmts) {
        return Some(tail.clone());
    }
    let_prefix_tail_expr(stmts)
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

fn statement_effect_bodies(
    stmts: &[Stmt],
    fcx: &SugarBuildCtx,
) -> Vec<SugarBody<StatementEffectFloor>> {
    stmts
        .iter()
        .filter_map(statement_effect_expr)
        .filter_map(|expr| SugarBody::statement_effect(&expr, fcx))
        .collect()
}

fn statement_effect_expr(stmt: &Stmt) -> Option<Expr> {
    match stmt {
        Stmt::Macro(stmt_macro) => Some(Expr::Macro(syn::ExprMacro {
            attrs: stmt_macro.attrs.clone(),
            mac: stmt_macro.mac.clone(),
        })),
        Stmt::Expr(expr, Some(_)) => Some(expr.clone()),
        Stmt::Expr(expr @ Expr::Macro(_), None) => Some(expr.clone()),
        Stmt::Expr(_, None) | Stmt::Local(_) | Stmt::Item(_) => None,
    }
}

fn tail_body(stmts: &[Stmt], fcx: &SugarBuildCtx) -> Option<SugarBody<TermFloor>> {
    let tail = transparent_tail_expr(stmts)?;
    Some(SugarBody::term(&tail, fcx))
}
