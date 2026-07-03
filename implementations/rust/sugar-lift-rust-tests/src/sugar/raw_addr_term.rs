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
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    assertion_entry_from_eq, bool_const, sugar_ctx_with_factory_audits, token_key, AssertionEntry,
    Desugared, Effect, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, Sugar, SugarCtx,
    TemporalScope,
};
use sugar_ir_symbolic::{make_var, Term};
use syn::{Expr, Item};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "raw_addr_term",
        crate::sugar::claim::SugarWitnesses::reasoned_bucket(
            "raw address term needs pointer-provenance facts before verdict pair",
        ),
        recognize,
    );

pub(crate) const PTR_EQ_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "ptr_eq_term",
    &["call"],
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
            #[test]
            fn t_ptr_eq_term_good() {
                let value = 1_i32;
                assert!(std::ptr::eq(&value, &value));
            }
        "#,
        r#"
            #[test]
            fn t_ptr_eq_term_bad() {
                let left = 1_i32;
                let right = 1_i32;
                assert!(std::ptr::eq(&left, &right));
            }
        "#,
    ),
    recognize_ptr_eq_term,
);

/// TERM recognizer for `Expr::RawAddr`.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let inner = frag.raw_addr_inner()?;
    let ctor = if frag.raw_addr_is_const() {
        "raw_addr_const"
    } else {
        "raw_addr_mut"
    };
    Some(Box::new(CtorSugar::new(
        ctor,
        vec![SugarBody::term_frag(&inner, fcx)],
    )))
}

fn recognize_ptr_eq_term(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let callee = pointer_eq_callee_frag(frag.call_func()?)?;
    if frag.call_arg_count() != 2 {
        panic!("ptr::eq expects two arguments; write more Sugar for this AST");
    }
    Some(Box::new(PointerEqTermSugar {
        callee,
        args: frag
            .call_args()
            .into_iter()
            .map(|arg| {
                let site = arg.token_str();
                let expr = arg
                    .as_expr()
                    .unwrap_or_else(|| {
                        panic!(
                            "ptr::eq argument `{site}` was not an expression fragment; write more Sugar for this AST"
                        )
                    })
                    .clone();
                PointerEqArg { site, expr }
            })
            .collect(),
    }))
}

/// Frag-based callee recognizer: peels Paren/Group wrappers via
/// transparent_inner, then checks path_full_name against the three
/// canonical ptr::eq spellings. Mirrors pointer_eq_callee (raw-syn
/// path) without escaping to raw syn in the recognize body.
fn pointer_eq_callee_frag(frag: SourceFragment<'_>) -> Option<String> {
    if let Some(inner) = frag.transparent_inner() {
        return pointer_eq_callee_frag(inner);
    }
    let name = frag.path_full_name()?;
    matches!(name.as_str(), "core::ptr::eq" | "ptr::eq" | "std::ptr::eq").then_some(name)
}

struct PointerEqArg {
    site: String,
    expr: Expr,
}

struct PointerEqTermSugar {
    callee: String,
    args: Vec<PointerEqArg>,
}

impl Sugar for PointerEqTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let mut args = Vec::with_capacity(self.args.len());
        for arg in &self.args {
            let term = match pointer_identity_term(&arg.expr, ctx.scope) {
                Ok(term) => term,
                Err(effect) => return Outcome::Incomplete(effect),
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
) -> Result<Option<AssertionEntry>, Effect> {
    match expr {
        Expr::Paren(paren) => pointer_eq_assertion_entry(&paren.expr, scope),
        Expr::Group(group) => pointer_eq_assertion_entry(&group.expr, scope),
        Expr::Call(call) => {
            let Some(callee) = pointer_eq_callee(&call.func) else {
                return Ok(None);
            };
            if call.args.len() != 2 {
                panic!("ptr::eq expects two arguments; write more Sugar for this AST");
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
) -> Result<Rc<Term>, Effect> {
    match expr {
        Expr::Reference(reference) if reference.mutability.is_some() => {
            Err(mutable_reference_identity_effect(&token_key(expr)))
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
        Expr::Path(path) if path.qself.is_none() => scope
            .path_name(&path.path)
            .map(make_var)
            .map_err(|reason| Effect::AmbiguousTemporalIdentity {
                boundary: token_key(expr),
                reason: format!(
                    "pointer identity path cannot be derived from scoped allocation/binding \
                     testimony: {reason}"
                ),
            }),
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

fn reduce_term_in_scope(expr: &Expr, scope: &TemporalScope) -> Result<Rc<Term>, Effect> {
    let options = LiftOptions::default();
    let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
    let fcx = SugarBuildCtx::new(scope, &options, &let_inits);
    let body: SugarBody<TermFloor> = SugarBody::term(expr, &fcx);
    let items: Vec<Item> = Vec::new();
    let reducer = ReductionCtx::from_items_with_imports(&items, scope.macro_registry());
    let mut float_widths = FloatWidthScope::new();
    let ctx = sugar_ctx_with_factory_audits(scope, &options, &reducer, &mut float_widths, 0, None);
    match body.reduce(&ctx) {
        Outcome::Complete(desugared) => match desugared.into_term() {
            Some(term) => Ok(term),
            None => {
                panic!(
                    "raw pointer identity term `{}` completed a non-Term floor",
                    token_key(expr)
                );
            }
        },
        Outcome::Incomplete(effect) => Err(effect),
    }
}

// Raw-syn callee recognizer used by the assertion pathway (pointer_eq_assertion_entry).
// The recognize body uses pointer_eq_callee_frag instead.
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
    use syn::{Expr, Item};

    /// from_src: source -> SourceFragment -> accessor gate -> build -> floor.
    /// Exercises raw_addr_inner / raw_addr_is_const directly; no
    /// parse_quote! / StubTerm / run().
    #[test]
    fn from_src_raw_addr_accessors() {
        // const raw addr
        let const_expr: Expr = syn::parse_str("&raw const x").expect("parse &raw const x");
        let frag_const = SourceFragment::expr(&const_expr, "<src>");
        assert!(
            frag_const.raw_addr_inner().is_some(),
            "const raw: inner is Some"
        );
        assert!(
            frag_const.raw_addr_is_const(),
            "const raw: is_const returns true"
        );

        // mut raw addr
        let mut_expr: Expr = syn::parse_str("&raw mut y").expect("parse &raw mut y");
        let frag_mut = SourceFragment::expr(&mut_expr, "<src>");
        assert!(
            frag_mut.raw_addr_inner().is_some(),
            "mut raw: inner is Some"
        );
        assert!(
            !frag_mut.raw_addr_is_const(),
            "mut raw: is_const returns false"
        );

        // non-raw-addr: accessors return None / false
        let other: Expr = syn::parse_str("x + 1").expect("parse x + 1");
        let frag_other = SourceFragment::expr(&other, "<src>");
        assert!(
            frag_other.raw_addr_inner().is_none(),
            "non-raw-addr: inner is None"
        );
        assert!(
            !frag_other.raw_addr_is_const(),
            "non-raw-addr: is_const returns false"
        );
    }

    fn reduce(src: &str) -> Rc<Term> {
        let expr: Expr = syn::parse_str(src).expect("parse raw address expr");
        let scope = TemporalScope::new("raw-addr-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = {
            let _frag = SourceFragment::expr(&expr, "<src>");
            recognize(&_frag, &fcx)
        }
        .expect("raw_addr_term recognizes");
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
