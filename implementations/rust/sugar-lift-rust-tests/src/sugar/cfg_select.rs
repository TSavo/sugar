// SPDX-License-Identifier: Apache-2.0
//
// `cfg_select! { pred => { .. } _ => { .. } }` is a compile-time branch
// selector. Assertion-bearing inactive branches do not exist on this target;
// the selected branch is lowered exactly as if its statements were written
// directly at the callsite.

use std::rc::Rc;

use proc_macro2::{TokenStream, TokenTree};
use sugar_ir_symbolic::{and_, eq, Formula};
use syn::parse::{Parse, ParseStream};
use syn::visit::Visit;
use syn::{Expr, ExprMacro, Stmt, Token};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::configuration::{resolve_predicate as cfg_resolve_predicate, CfgDisposition};
use crate::sugar::factory::{AssertionSurfaceFloor, SugarBody, SugarBuildCtx};
use crate::sugar::macro_assertion_surface::collect_assertion_surfaces_from_stmts;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    bool_const, token_key, AssertionFactKind, CfgPredicate, Desugared, Effect, Outcome, Sugar,
    SugarCtx, Warrant,
};

pub(crate) const ASSERTION_SURFACE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "cfg_select_assertion_surface",
    SugarRole::AssertionSurface,
    recognize,
);

struct CfgSelectSugar {
    body: CfgSelectBody,
    site: String,
}

enum CfgSelectBody {
    Arms(Vec<CfgSelectBuiltArm>),
    Unconstructible(String),
}

struct CfgSelectBuiltArm {
    predicate: Option<CfgPredicate>,
    assertion_count: usize,
    surfaces: Vec<SugarBody<AssertionSurfaceFloor>>,
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use syn::Expr;

    use crate::sugar::factory::{has_assertion_surface, SugarBuildCtx};
    use crate::{LiftOptions, TemporalPlan, TemporalScope};

    #[test]
    fn assertion_bearing_cfg_select_is_an_assertion_surface() {
        let expr: Expr = syn::parse_quote! {
            cfg_select! {
                debug_assertions => {
                    assert!(cfg!(debug_assertions));
                    assert_eq!(4, 2 + 2);
                }
                _ => {}
            }
        };
        let scope = TemporalScope::new("cfg-select-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let Expr::Macro(expr_macro) = &expr else {
            panic!("cfg_select fixture did not parse as macro expression");
        };
        let arms = syn::parse2::<super::CfgSelectArms>(expr_macro.mac.tokens.clone())
            .expect("parse cfg_select arms");
        let assertion_count: usize = arms
            .arms
            .iter()
            .map(|arm| super::syntactic_assert_count_in_stmts(&arm.block.stmts))
            .sum();
        assert_eq!(assertion_count, 2);

        assert!(has_assertion_surface(&expr, &fcx));
    }
}

struct CfgSelectArms {
    arms: Vec<CfgSelectArm>,
}

struct CfgSelectArm {
    predicate: Option<CfgPredicate>,
    block: syn::Block,
}

impl Parse for CfgSelectArms {
    fn parse(input: ParseStream<'_>) -> syn::Result<Self> {
        let mut arms = Vec::new();
        while !input.is_empty() {
            let predicate = parse_arm_predicate(input)?;
            let _: Token![=>] = input.parse()?;
            let content;
            let brace_token = syn::braced!(content in input);
            let stmts = content.call(syn::Block::parse_within)?;
            arms.push(CfgSelectArm {
                predicate,
                block: syn::Block { brace_token, stmts },
            });
        }
        Ok(Self { arms })
    }
}

fn parse_arm_predicate(input: ParseStream<'_>) -> syn::Result<Option<CfgPredicate>> {
    if input.peek(Token![_]) {
        let _: Token![_] = input.parse()?;
        return Ok(None);
    }

    let mut tokens = TokenStream::new();
    while !input.is_empty() && !input.peek(Token![=>]) {
        let token: TokenTree = input.parse()?;
        tokens.extend(std::iter::once(token));
    }
    if tokens.is_empty() {
        return Err(input.error("expected cfg_select predicate"));
    }
    syn::parse2::<CfgPredicate>(tokens).map(Some)
}

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Macro(ExprMacro { mac, .. }) = expr else {
        return None;
    };
    if !mac
        .path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == "cfg_select")
    {
        return None;
    }
    let site = token_key(expr);
    let arms = match syn::parse2::<CfgSelectArms>(mac.tokens.clone()) {
        Ok(arms) => arms,
        Err(error) => {
            return Some(Box::new(CfgSelectSugar {
                body: CfgSelectBody::Unconstructible(format!(
                    "macro `cfg_select`: cannot parse cfg-select arms at construction time: {error}; write more Sugar for this AST"
                )),
                site,
            }));
        }
    };
    let body = build_cfg_select_body(arms, fcx)?;
    Some(Box::new(CfgSelectSugar { body, site }))
}

impl Sugar for CfgSelectSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let CfgSelectBody::Arms(arms) = &self.body else {
            let CfgSelectBody::Unconstructible(reason) = &self.body else {
                unreachable!("cfg_select body has only two variants")
            };
            panic!("{reason}");
        };

        let mut inactive_assertions = 0usize;
        for arm in arms {
            let selected = match &arm.predicate {
                Some(predicate) => match cfg_resolve_predicate(predicate, ctx.options) {
                    CfgDisposition::Present => true,
                    CfgDisposition::Absent(_) => {
                        inactive_assertions += arm.assertion_count;
                        false
                    }
                    CfgDisposition::Ambiguous(reason) => {
                        return Outcome::Incomplete(Effect::Configuration {
                            boundary: self.site.clone(),
                            reason: format!(
                                "macro `cfg_select`: ambiguous cfg branch `{predicate}`: {reason}; refused"
                            ),
                        })
                    }
                },
                None => true,
            };
            if selected {
                return self.desugar_selected_branch(arm, inactive_assertions, ctx);
            }
        }

        self.inactive_noop(ctx, inactive_assertions)
    }
}

impl CfgSelectSugar {
    fn desugar_selected_branch(
        &self,
        arm: &CfgSelectBuiltArm,
        inactive_before: usize,
        ctx: &SugarCtx,
    ) -> Outcome {
        if arm.surfaces.is_empty() {
            return self.inactive_noop(ctx, inactive_before);
        }
        reduce_surfaces(&arm.surfaces, ctx)
    }

    fn inactive_noop(&self, ctx: &SugarCtx, inactive_assertions: usize) -> Outcome {
        Outcome::Complete(Desugared::Constraints {
            atom: eq(bool_const(true), bool_const(true)),
            n: 0,
            kind: AssertionFactKind::Support,
            warrant: Warrant {
                name: Some(format!(
                    "{}::cfg-select-inactive::{}::{}",
                    ctx.scope.local_scope(),
                    inactive_assertions,
                    compact_warrant_fragment(&self.site)
                )),
            },
        })
    }
}

fn build_cfg_select_body(arms: CfgSelectArms, fcx: &SugarBuildCtx) -> Option<CfgSelectBody> {
    let mut built = Vec::new();
    let mut total_assertions = 0usize;
    for arm in arms.arms {
        let assertion_count = syntactic_assert_count_in_stmts(&arm.block.stmts);
        total_assertions += assertion_count;
        let mut surface_exprs = Vec::new();
        collect_assertion_surfaces_from_stmts(&arm.block.stmts, fcx, &mut surface_exprs);
        if assertion_count > 0 && surface_exprs.is_empty() {
            return Some(CfgSelectBody::Unconstructible(format!(
                "macro `cfg_select`: branch contains assertion surface syntax but no factory assertion-surface child was constructible; write more Sugar for this AST"
            )));
        }
        built.push(CfgSelectBuiltArm {
            predicate: arm.predicate,
            assertion_count,
            surfaces: surface_exprs
                .into_iter()
                .map(|expr| SugarBody::assertion_surface(&expr, fcx))
                .collect(),
        });
    }
    if total_assertions == 0 {
        None
    } else {
        Some(CfgSelectBody::Arms(built))
    }
}

fn reduce_surfaces(surfaces: &[SugarBody<AssertionSurfaceFloor>], ctx: &SugarCtx) -> Outcome {
    if surfaces.len() == 1 {
        return surfaces[0].reduce(ctx);
    }
    let mut atoms = Vec::<Rc<Formula>>::new();
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
            Outcome::Complete(other) => {
                let _ = other;
                panic!("cfg_select assertion-surface child did not reduce to constraints");
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

fn compact_warrant_fragment(site: &str) -> String {
    let mut out = String::new();
    for ch in site.chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch);
        } else if !out.ends_with('_') {
            out.push('_');
        }
        if out.len() >= 48 {
            break;
        }
    }
    out.trim_matches('_').to_string()
}

fn syntactic_assert_count_in_stmts(stmts: &[Stmt]) -> usize {
    #[derive(Default)]
    struct Counter {
        total: usize,
    }

    impl<'ast> Visit<'ast> for Counter {
        fn visit_macro(&mut self, mac: &'ast syn::Macro) {
            if macro_name_is_assertion_surface(mac) {
                self.total += 1;
                return;
            }
            syn::visit::visit_macro(self, mac);
        }
    }

    let mut counter = Counter::default();
    for stmt in stmts {
        counter.visit_stmt(stmt);
    }
    counter.total
}

fn macro_name_is_assertion_surface(mac: &syn::Macro) -> bool {
    mac.path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
        .is_some_and(|name| {
            matches!(
                name.as_str(),
                "assert"
                    | "assert_eq"
                    | "assert_ne"
                    | "assert_matches"
                    | "debug_assert"
                    | "debug_assert_eq"
                    | "debug_assert_ne"
                    | "debug_assert_matches"
            )
        })
}
