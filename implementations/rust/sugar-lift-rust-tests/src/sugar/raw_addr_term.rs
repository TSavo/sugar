// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::RawAddr` (`&raw const x` / `&raw mut x`): a raw
// pointer capability constructor. Construction itself is inert; consumers own
// any temporal effect when the capability is used or escapes.

use std::collections::BTreeMap;
use std::rc::Rc;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::{
    assertion_entry_from_eq, bool_const, sugar_ctx_with_factory_audits, token_key, AssertionEntry,
    Desugared, Effect, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, Sugar, SugarCtx,
    TemporalScope,
};
use sugar_ir_symbolic::Term;
use syn::{Expr, Item};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("raw_addr_term", recognize);

pub(crate) const PTR_EQ_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("ptr_eq_term", &["call"], recognize_ptr_eq_term);

/// TERM recognizer for `Expr::RawAddr`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::RawAddr(raw) = expr else {
        return None;
    };
    let ctor = match &raw.mutability {
        syn::PointerMutability::Const(_) => "raw_addr_const",
        syn::PointerMutability::Mut(_) => "raw_addr_mut",
    };
    Some(Box::new(CtorSugar::new(
        ctor,
        vec![SugarBody::term(raw.expr.as_ref(), fcx)],
    )))
}

fn recognize_ptr_eq_term(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Call(call) = expr else {
        return None;
    };
    let callee = pointer_eq_callee(&call.func)?;
    if call.args.len() != 2 {
        panic!("ptr::eq expects two arguments; write more Sugar for this AST");
    }
    Some(Box::new(PointerEqTermSugar {
        callee,
        args: call
            .args
            .iter()
            .map(|arg| PointerEqArg {
                site: token_key(arg),
                body: SugarBody::term(arg, fcx),
            })
            .collect(),
    }))
}

struct PointerEqArg {
    site: String,
    body: SugarBody<TermFloor>,
}

struct PointerEqTermSugar {
    callee: String,
    args: Vec<PointerEqArg>,
}

impl Sugar for PointerEqTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let mut args = Vec::with_capacity(self.args.len());
        for arg in &self.args {
            let term = match arg.body.reduce(ctx) {
                Outcome::Complete(d) => match d.into_term() {
                    Some(term) => term,
                    None => {
                        panic!(
                            "ptr::eq argument `{}` completed a non-Term where pointer identity was required; write more Sugar for this AST",
                            arg.site
                        );
                    }
                },
                Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
            };
            if is_mutable_reference_identity(&term) {
                return Outcome::Incomplete(mutable_reference_identity_effect(&arg.site));
            }
            args.push(term);
        }
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: format!("call:{}", self.callee),
            args,
        })))
    }
}

pub(crate) fn pointer_eq_assertion_entry(
    expr: &Expr,
    scope: &TemporalScope,
) -> Result<Option<AssertionEntry>, String> {
    match expr {
        Expr::Paren(paren) => pointer_eq_assertion_entry(&paren.expr, scope),
        Expr::Group(group) => pointer_eq_assertion_entry(&group.expr, scope),
        Expr::Call(call) => {
            let Some(callee) = pointer_eq_callee(&call.func) else {
                return Ok(None);
            };
            if call.args.len() != 2 {
                return Err("ptr::eq expects two arguments".to_string());
            }
            let args = call
                .args
                .iter()
                .map(|arg| pointer_identity_term(arg, scope))
                .collect::<Result<Vec<_>, _>>()?;
            let term = Rc::new(Term::Ctor {
                name: format!("call:{callee}"),
                args,
            });
            Ok(Some(assertion_entry_from_eq(term, bool_const(true), scope)))
        }
        _ => Ok(None),
    }
}

pub(crate) fn pointer_identity_term(
    expr: &Expr,
    scope: &TemporalScope,
) -> Result<Rc<Term>, String> {
    match expr {
        Expr::Reference(reference) if reference.mutability.is_some() => {
            Err(mutable_reference_identity_effect(&token_key(expr)).reason())
        }
        Expr::Reference(reference) if reference.mutability.is_none() => Ok(Rc::new(Term::Ctor {
            name: "ref".to_string(),
            args: vec![pointer_identity_term(&reference.expr, scope)?],
        })),
        Expr::Index(index) => Ok(Rc::new(Term::Ctor {
            name: "index".to_string(),
            args: vec![
                pointer_identity_term(&index.expr, scope)?,
                pointer_identity_term(&index.index, scope)?,
            ],
        })),
        Expr::Paren(paren) => pointer_identity_term(&paren.expr, scope),
        Expr::Group(group) => pointer_identity_term(&group.expr, scope),
        other => reduce_term_in_scope(other, scope),
    }
}

fn mutable_reference_identity_effect(boundary: &str) -> Effect {
    Effect::RepresentationCast {
        boundary: boundary.to_string(),
        kind: "a `&mut` borrow".to_string(),
    }
}

fn is_mutable_reference_identity(term: &Rc<Term>) -> bool {
    matches!(term.as_ref(), Term::Ctor { name, .. } if name == "ref_mut")
}

fn reduce_term_in_scope(expr: &Expr, scope: &TemporalScope) -> Result<Rc<Term>, String> {
    let options = LiftOptions::default();
    let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
    let fcx = SugarBuildCtx::new(scope, &options, &let_inits);
    let body: SugarBody<TermFloor> = SugarBody::term(expr, &fcx);
    let items: Vec<Item> = Vec::new();
    let reducer = ReductionCtx::from_items_with_imports(&items, scope.macro_registry());
    let mut float_widths = FloatWidthScope::new();
    let ctx = sugar_ctx_with_factory_audits(scope, &options, &reducer, &mut float_widths, 0, None);
    match body.reduce(&ctx) {
        Outcome::Complete(desugared) => desugared
            .into_term()
            .ok_or_else(|| format!("unsupported term `{}`", token_key(expr))),
        Outcome::Incomplete(effect) => Err(effect.reason()),
    }
}

fn pointer_eq_callee(expr: &Expr) -> Option<String> {
    let name = match expr {
        Expr::Path(path) if path.qself.is_none() => plain_path_name(&path.path)?,
        Expr::Paren(paren) => return pointer_eq_callee(&paren.expr),
        Expr::Group(group) => return pointer_eq_callee(&group.expr),
        _ => return None,
    };
    matches!(name.as_str(), "core::ptr::eq" | "ptr::eq" | "std::ptr::eq").then_some(name)
}

fn plain_path_name(path: &syn::Path) -> Option<String> {
    path.segments
        .iter()
        .map(|segment| {
            matches!(segment.arguments, syn::PathArguments::None).then(|| segment.ident.to_string())
        })
        .collect::<Option<Vec<_>>>()
        .map(|segments| segments.join("::"))
}

#[cfg(test)]
mod tests {
    use std::rc::Rc;

    use super::*;
    use crate::{
        sugar_ctx, Desugared, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, TemporalPlan,
        TemporalScope,
    };
    use sugar_ir_symbolic::Term;
    use syn::Item;

    fn reduce(src: &str) -> Rc<Term> {
        let expr: Expr = syn::parse_str(src).expect("parse raw address expr");
        let scope = TemporalScope::new("raw-addr-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = recognize(&expr, &fcx).expect("raw_addr_term recognizes");
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        let Outcome::Complete(Desugared::Term(term)) = node.desugar(&ctx) else {
            panic!("raw address sugar should complete as an inert capability term")
        };
        term
    }

    #[test]
    fn raw_const_address_constructs_capability_floor() {
        let term = reduce("&raw const x");
        let Term::Ctor { name, args } = term.as_ref() else {
            panic!("expected raw_addr_const ctor, got {term:?}");
        };
        assert_eq!(name, "raw_addr_const");
        assert_eq!(args.len(), 1);
        assert!(matches!(args[0].as_ref(), Term::Var { name } if name == "x"));
    }

    #[test]
    fn raw_mut_address_constructs_capability_floor() {
        let term = reduce("&raw mut x");
        let Term::Ctor { name, args } = term.as_ref() else {
            panic!("expected raw_addr_mut ctor, got {term:?}");
        };
        assert_eq!(name, "raw_addr_mut");
        assert_eq!(args.len(), 1);
        assert!(matches!(args[0].as_ref(), Term::Var { name } if name == "x"));
    }
}
