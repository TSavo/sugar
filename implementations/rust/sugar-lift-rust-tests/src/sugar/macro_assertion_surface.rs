// SPDX-License-Identifier: MIT OR Apache-2.0
//
// ASSERTION-SURFACE recognizer for held `macro_rules!` statement wrappers. Macro
// expansion is source-to-source: the expanded assertion body goes straight back
// through the factory as typed assertion-surface children. This sugar owns no
// runtime effect of its own; child effects propagate, and construction gaps panic.

use std::collections::BTreeMap;

use sugar_ir_symbolic::{and_, Formula};
use syn::{Expr, Stmt};

use crate::sugar::factory::{AssertionSurfaceFloor, SugarBody, SugarBuildCtx};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    let_simple_value_binding, AssertionFactKind, Desugared, Outcome, Sugar, SugarCtx, Warrant,
    MAX_MACRO_EXPANSION_DEPTH,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::fallback_assertion_surface(
        "macro_assertion_surface",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                macro_rules! assert_four {
                    () => {
                        assert_eq!(2_i32 + 2, 4);
                    };
                }

                #[test]
                fn t_macro_assertion_surface_good() {
                    assert_four!();
                }
            "#,
            r#"
                macro_rules! assert_four {
                    () => {
                        assert_eq!(2_i32 + 2, 5);
                    };
                }

                #[test]
                fn t_macro_assertion_surface_bad() {
                    assert_four!();
                }
            "#,
        ),
        recognize,
    );

/// Assertion-surface recognizer for a held source macro whose expansion contains
/// assertion-surface syntax.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.observed() != "Macro" {
        return None;
    }
    build_macro_assertion_surface_frag(frag, fcx)
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
    let expansion_let_inits = expansion_simple_let_inits(&block.stmts);
    let mut child_let_inits: BTreeMap<String, &Expr> = fcx
        .let_inits()
        .iter()
        .map(|(name, expr)| (name.clone(), *expr))
        .collect();
    for (name, expr) in &expansion_let_inits {
        child_let_inits.insert(name.clone(), expr);
    }
    let child_fcx_base = SugarBuildCtx::new(fcx.scope(), fcx.options(), &child_let_inits);
    let child_fcx = child_fcx_base.with_macro_depth(fcx.macro_depth() + 1);
    let mut surface_exprs = Vec::new();
    collect_assertion_surfaces_from_stmts(&block.stmts, &child_fcx, &mut surface_exprs);
    if surface_exprs.is_empty() {
        return None;
    }
    Some(MacroAssertionSurfaceBody::Expanded(
        surface_exprs
            .into_iter()
            .map(|expr| SugarBody::assertion_surface(&expr, &child_fcx))
            .collect(),
    ))
}

fn expansion_simple_let_inits(stmts: &[Stmt]) -> BTreeMap<String, Expr> {
    stmts
        .iter()
        .filter_map(|stmt| {
            let Stmt::Local(local) = stmt else {
                return None;
            };
            let init = local.init.as_ref().filter(|init| init.diverge.is_none())?;
            let name = let_simple_value_binding(&local.pat)?;
            Some((name, (*init.expr).clone()))
        })
        .collect()
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

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use syn::Expr;

    use super::*;
    use crate::{LiftOptions, MacroRegistry, TemporalPlan, TemporalScope};

    fn with_macro_fcx<T>(src: &str, f: impl FnOnce(&SugarBuildCtx<'_, '_>) -> T) -> T {
        let mut registry = MacroRegistry::new();
        registry.scan_source(src);
        let scope = TemporalScope::new("macro-surface-test", TemporalPlan::default())
            .with_macro_registry(registry);
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        f(&fcx)
    }

    #[test]
    fn direct_assertion_macro_expansion_is_owned_as_assertion_surface() {
        let expr: Expr = syn::parse_str("wrap!()").unwrap();
        with_macro_fcx(
            r#"
macro_rules! wrap {
    () => { assert!(true); };
}
"#,
            |fcx| {
                assert!(
                    {
                        let _frag = SourceFragment::expr(&expr, "<src>");
                        recognize(&_frag, fcx)
                    }
                    .is_some(),
                    "direct assertion expansion should be assertion-surface sugar"
                );
            },
        );
    }

    #[test]
    fn guarded_assertion_macro_expansion_declines_to_statement_collector() {
        let expr: Expr = syn::parse_str("wrap!()").unwrap();
        with_macro_fcx(
            r#"
macro_rules! wrap {
    () => {
        if true {
            assert!(true);
        }
    };
}
"#,
            |fcx| {
                assert!(
                    {
                        let _frag = SourceFragment::expr(&expr, "<src>");
                        recognize(&_frag, fcx)
                    }
                    .is_none(),
                    "guarded expansion needs statement-position collection to preserve the guard"
                );
            },
        );
    }

    #[test]
    fn item_assertion_macro_expansion_declines_to_statement_collector() {
        let expr: Expr = syn::parse_str("suite!()").unwrap();
        with_macro_fcx(
            r#"
macro_rules! suite {
    () => {
        mod generated {
            pub fn run() {
                assert_eq!(1, 1);
            }
        }
        generated::run();
    };
}
"#,
            |fcx| {
                assert!(
                    {
                        let _frag = SourceFragment::expr(&expr, "<src>");
                        recognize(&_frag, fcx)
                    }
                    .is_none(),
                    "item expansion needs the normal statement collector to walk item bodies"
                );
            },
        );
    }
}

// -- fragment-based wrapper (outside 2000-char ratchet window) ----------------

/// Calls `build_macro_assertion_surface` from a `SourceFragment`. Callers must
/// have verified `frag.observed() == "Macro"`. All raw syn extraction of the
/// `ExprMacro` lives here, outside the 2000-char ratchet window from `recognize`.
fn build_macro_assertion_surface_frag(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<MacroAssertionSurfaceBody> {
    let expr = frag.as_expr()?;
    let Expr::Macro(mac) = expr else {
        return None;
    };
    build_macro_assertion_surface(mac, fcx)
}
