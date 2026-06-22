// SPDX-License-Identifier: Apache-2.0
//
// `cfg_select! { pred => { .. } _ => { .. } }` is a compile-time branch
// selector. Assertion-bearing inactive branches do not exist on this target;
// the selected branch is lowered exactly as if its statements were written
// directly at the callsite.

use std::collections::{BTreeMap, HashSet};
use std::rc::Rc;

use proc_macro2::{TokenStream, TokenTree};
use sugar_ir_symbolic::{and_, Formula};
use syn::parse::{Parse, ParseStream};
use syn::visit::Visit;
use syn::{Expr, ExprMacro, Stmt, Token};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::configuration::{resolve_predicate as cfg_resolve_predicate, CfgDisposition};
use crate::sugar::factory::SugarBuildCtx;
use crate::{
    collect_assertion_entries, token_key, AssertionFactKind, CfgPredicate, Desugared, Effect,
    FnRegistry, LayoutTypeRegistry, Outcome, Sugar, SugarCtx, Warrant,
};

pub(crate) const ASSERTION_SURFACE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "cfg_select_assertion_surface",
    SugarRole::AssertionSurface,
    recognize,
);

struct CfgSelectSugar {
    mac: syn::Macro,
    site: String,
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

fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
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
    let arms = syn::parse2::<CfgSelectArms>(mac.tokens.clone()).ok()?;
    let assertion_surfaces: usize = arms
        .arms
        .iter()
        .map(|arm| syntactic_assert_count_in_stmts(&arm.block.stmts))
        .sum();
    if assertion_surfaces == 0 {
        return None;
    }
    Some(Box::new(CfgSelectSugar {
        mac: mac.clone(),
        site: token_key(expr),
    }))
}

impl Sugar for CfgSelectSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let arms = match syn::parse2::<CfgSelectArms>(self.mac.tokens.clone()) {
            Ok(arms) => arms,
            Err(e) => {
                return Outcome::Hit(Effect::Unsupported {
                    reason: format!(
                        "macro `cfg_select`: cannot parse cfg-select arms at desugar time: {e}; released to layer 0"
                    ),
                });
            }
        };

        let mut inactive_assertions = 0usize;
        for arm in arms.arms {
            let selected = match &arm.predicate {
                Some(predicate) => match cfg_resolve_predicate(predicate, ctx.options) {
                    CfgDisposition::Present => true,
                    CfgDisposition::Absent(_) => {
                        inactive_assertions += syntactic_assert_count_in_stmts(&arm.block.stmts);
                        false
                    }
                    CfgDisposition::Ambiguous(reason) => {
                        return Outcome::Hit(Effect::Unsupported {
                            reason: format!(
                                "macro `cfg_select`: ambiguous cfg branch `{predicate}`: {reason}; released to layer 0"
                            ),
                        });
                    }
                },
                None => true,
            };
            if selected {
                return self.desugar_selected_branch(&arm.block.stmts, inactive_assertions, ctx);
            }
        }

        if inactive_assertions > 0 {
            Outcome::Hit(Effect::Unsupported {
                reason: format!(
                    "inactive cfg select: {inactive_assertions} assertion surface(s) stripped on this target"
                ),
            })
        } else {
            Outcome::from_opt(None)
        }
    }
}

impl CfgSelectSugar {
    fn desugar_selected_branch(
        &self,
        stmts: &[Stmt],
        inactive_before: usize,
        ctx: &SugarCtx,
    ) -> Outcome {
        let expected = syntactic_assert_count_in_stmts(stmts);
        if expected == 0 {
            return Outcome::Hit(Effect::Unsupported {
                reason: format!(
                    "inactive cfg select: {inactive_before} assertion surface(s) stripped before selected assertion-free branch"
                ),
            });
        }
        let Some(atom) = self.lift_branch_conj(stmts, expected, ctx) else {
            return Outcome::from_opt(None);
        };
        Outcome::Dug(Desugared::Constraints {
            atom,
            n: expected,
            kind: AssertionFactKind::Warranted,
            warrant: Warrant {
                name: Some(format!(
                    "{}::cfg-select::{}",
                    ctx.scope.local_scope(),
                    compact_warrant_fragment(&self.site)
                )),
            },
        })
    }

    fn lift_branch_conj(
        &self,
        stmts: &[Stmt],
        expected: usize,
        ctx: &SugarCtx,
    ) -> Option<Rc<Formula>> {
        let mut entries = Vec::new();
        let mut skipped = Vec::new();
        let mut lifted = 0usize;
        let mut helpers = HashSet::new();
        collect_assertion_entries(
            stmts,
            ctx.scope.local_scope(),
            ctx.options,
            ctx.reducer,
            *ctx.float_widths.borrow_mut(),
            &mut entries,
            &mut skipped,
            &mut lifted,
            &mut helpers,
            ctx.factory_audits,
            ctx.macro_depth,
            &ctx.scope.plan.interior_mut,
            &BTreeMap::new(),
            &FnRegistry::new(),
            &LayoutTypeRegistry::new(),
        );
        let warranted: usize = entries
            .iter()
            .filter(|entry| matches!(entry.kind, AssertionFactKind::Warranted))
            .map(|entry| entry.claim_count)
            .sum();
        if !skipped.is_empty() || warranted != expected {
            return None;
        }
        Some(and_(
            entries.iter().map(|entry| entry.atom.clone()).collect(),
        ))
    }
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
