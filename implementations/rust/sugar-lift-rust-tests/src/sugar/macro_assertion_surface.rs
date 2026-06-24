// SPDX-License-Identifier: Apache-2.0
//
// ASSERTION-SURFACE recognizer for held `macro_rules!` statement wrappers. Macro
// expansion is source-to-source: the expanded assertion body goes straight back
// through the factory as typed assertion-surface children. This sugar owns no
// runtime effect of its own; child effects propagate, and construction gaps panic.

use sugar_ir_symbolic::{and_, Formula};
use syn::{Expr, Stmt};

use crate::sugar::factory::{AssertionSurfaceFloor, SugarBody, SugarBuildCtx};
use crate::{
    AssertionFactKind, Desugared, Outcome, Sugar, SugarCtx, Warrant, MAX_MACRO_EXPANSION_DEPTH,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::fallback_assertion_surface(
        "macro_assertion_surface",
        recognize,
    );

/// Assertion-surface recognizer for a held source macro whose expansion contains
/// assertion-surface syntax.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(mac) = expr else {
        return None;
    };
    build_macro_assertion_surface(mac, fcx)
        .map(|surfaces| Box::new(MacroAssertionSurfaceSugar { surfaces }) as Box<dyn Sugar>)
}

pub(crate) struct MacroAssertionSurfaceSugar {
    surfaces: MacroAssertionSurfaceBody,
}

enum MacroAssertionSurfaceBody {
    Expanded(Vec<SugarBody<AssertionSurfaceFloor>>),
    Unconstructible(String),
}

fn build_macro_assertion_surface(
    mac: &syn::ExprMacro,
    fcx: &SugarBuildCtx,
) -> Option<MacroAssertionSurfaceBody> {
    let name = mac
        .mac
        .path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())?;
    if fcx.macro_depth() >= MAX_MACRO_EXPANSION_DEPTH {
        return Some(MacroAssertionSurfaceBody::Unconstructible(format!(
            "macro `{name}` assertion-surface expansion depth exceeded; write more Sugar for this AST"
        )));
    }
    let rules = fcx.scope().macro_registry().lookup(&name)?;
    let expanded = match crate::macro_expand::expand(&rules, mac.mac.tokens.clone()) {
        Ok(expanded) => expanded,
        Err(error) => {
            return Some(MacroAssertionSurfaceBody::Unconstructible(format!(
                "macro `{name}` assertion-surface expansion failed: {error}; write more Sugar for this AST"
            )));
        }
    };
    let expanded_for_block = expanded.clone();
    let block: syn::Block = match syn::parse2(quote::quote! { { #expanded_for_block } }) {
        Ok(block) => block,
        Err(error) => {
            return Some(MacroAssertionSurfaceBody::Unconstructible(format!(
                "macro `{name}` assertion-surface expansion did not parse as statements: {error}; write more Sugar for this AST"
            )));
        }
    };
    let block = if let Some(rewritten) =
        crate::sugar::utf8_chunks::rewrite_literal_utf8_chunks_block(&block)
    {
        rewritten
    } else {
        block
    };
    let child_fcx = fcx.with_macro_depth(fcx.macro_depth() + 1);
    let mut surface_exprs = Vec::new();
    collect_assertion_surfaces_from_stmts(&block.stmts, &child_fcx, &mut surface_exprs);
    if surface_exprs.is_empty() {
        if crate::count_asserts_in_stmts(&block.stmts) > 0 {
            return Some(MacroAssertionSurfaceBody::Unconstructible(format!(
                "macro `{name}` expansion contains assertion surface syntax but no factory assertion-surface child was constructible; write more Sugar for this AST"
            )));
        }
        return None;
    }
    Some(MacroAssertionSurfaceBody::Expanded(
        surface_exprs
            .into_iter()
            .map(|expr| SugarBody::assertion_surface(&expr, &child_fcx))
            .collect(),
    ))
}

pub(crate) fn collect_assertion_surfaces_from_stmts(
    stmts: &[Stmt],
    fcx: &SugarBuildCtx,
    out: &mut Vec<Expr>,
) {
    for stmt in stmts {
        match stmt {
            Stmt::Macro(stmt_macro) => {
                collect_assertion_surfaces_from_expr(
                    &Expr::Macro(syn::ExprMacro {
                        attrs: stmt_macro.attrs.clone(),
                        mac: stmt_macro.mac.clone(),
                    }),
                    fcx,
                    out,
                );
            }
            Stmt::Local(local) => {
                if let Some(init) = &local.init {
                    collect_assertion_surfaces_from_expr(&init.expr, fcx, out);
                }
            }
            Stmt::Item(syn::Item::Const(item)) => {
                collect_assertion_surfaces_from_expr(&item.expr, fcx, out);
            }
            Stmt::Item(syn::Item::Static(item)) => {
                collect_assertion_surfaces_from_expr(&item.expr, fcx, out);
            }
            Stmt::Item(_) => {}
            Stmt::Expr(expr, _) => collect_assertion_surfaces_from_expr(expr, fcx, out),
        }
    }
}

fn collect_assertion_surfaces_from_expr(expr: &Expr, fcx: &SugarBuildCtx, out: &mut Vec<Expr>) {
    if crate::sugar::factory::has_assertion_surface(expr, fcx) {
        out.push(expr.clone());
        return;
    }
    match expr {
        Expr::Block(block) => collect_assertion_surfaces_from_stmts(&block.block.stmts, fcx, out),
        Expr::Const(const_expr) => {
            collect_assertion_surfaces_from_stmts(&const_expr.block.stmts, fcx, out);
        }
        Expr::Unsafe(unsafe_expr) => {
            collect_assertion_surfaces_from_stmts(&unsafe_expr.block.stmts, fcx, out);
        }
        Expr::Paren(paren) => collect_assertion_surfaces_from_expr(&paren.expr, fcx, out),
        Expr::Group(group) => collect_assertion_surfaces_from_expr(&group.expr, fcx, out),
        _ => {}
    }
}

impl Sugar for MacroAssertionSurfaceSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match &self.surfaces {
            MacroAssertionSurfaceBody::Expanded(surfaces) => reduce_surfaces(surfaces, ctx),
            MacroAssertionSurfaceBody::Unconstructible(reason) => {
                panic!("{reason}");
            }
        }
    }
}

fn reduce_surfaces(surfaces: &[SugarBody<AssertionSurfaceFloor>], ctx: &SugarCtx) -> Outcome {
    if surfaces.len() == 1 {
        return surfaces[0].reduce(ctx);
    }
    let mut atoms = Vec::<std::rc::Rc<Formula>>::new();
    let mut claim_count = 0usize;
    let mut kind = AssertionFactKind::Support;
    let mut warrant_name = None::<String>;
    for surface in surfaces {
        match surface.reduce(ctx) {
            Outcome::Complete(Desugared::Constraints {
                atom,
                n,
                kind: child_kind,
                warrant,
            }) => {
                atoms.push(atom);
                claim_count += n;
                if child_kind.is_warranted() {
                    kind = AssertionFactKind::Warranted;
                }
                if warrant_name.is_none() {
                    warrant_name = warrant.name;
                }
            }
            Outcome::Complete(_) => {
                panic!(
                    "macro assertion-surface child did not reduce to constraints in `{}`",
                    ctx.scope.local_scope()
                );
            }
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        }
    }
    Outcome::Complete(Desugared::Constraints {
        atom: and_(atoms),
        n: claim_count,
        kind,
        warrant: Warrant { name: warrant_name },
    })
}
