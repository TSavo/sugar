// SPDX-License-Identifier: Apache-2.0
//
// MatchesMacroSugar: `matches!(subject, Pattern)` is a constraint-shaped
// assertion vocabulary entry. The subject is built through the normal term
// factory so bound variables keep their RHS/callsite identity; this node owns
// only the pattern-to-constraint semantics.

use std::{collections::BTreeMap, rc::Rc};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::{
    callsite_assertion_name, lit_membership_term, strict_variant_path, token_key, wrapped_variant,
    AssertionFactKind, Desugared, Effect, Outcome, Sugar, SugarCtx, Warrant,
    STRUCTURAL_BACKSTOP_REASON,
};
use sugar_ir_symbolic::{and_, eq, str_const, Formula, Term};
use syn::parse::{ParseStream, Parser};
use syn::{Expr, ExprMacro, Pat, Token};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("constraint_matches_macro", SugarRole::Constraint, recognize);

struct MatchesMacroSugar {
    subject: Expr,
    pattern: Pat,
    site: String,
    let_inits: BTreeMap<String, Expr>,
}

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(ExprMacro { mac, .. }) = expr else {
        return None;
    };
    if !mac.path.is_ident("matches") {
        return None;
    }
    let parser = |input: ParseStream| -> syn::Result<(Expr, Pat)> {
        let subject: Expr = input.parse()?;
        input.parse::<Token![,]>()?;
        let pat = Pat::parse_multi_with_leading_vert(input)?;
        let _ = input.parse::<proc_macro2::TokenStream>();
        Ok((subject, pat))
    };
    let (subject, pattern) = Parser::parse2(parser, mac.tokens.clone()).ok()?;
    Some(Box::new(MatchesMacroSugar {
        subject,
        pattern,
        site: token_key(expr),
        let_inits: capture_let_inits(fcx),
    }))
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

impl Sugar for MatchesMacroSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let subject = match term_payload(&self.subject, ctx, &self.let_inits) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let Some(atom) = pattern_atom(&subject, &self.pattern) else {
            return unsupported(format!(
                "matches! pattern is not an unambiguous qualified variant \
                 (binding/wildcard/single-segment/or-pattern); refused by name: `{}`",
                self.site
            ));
        };
        constraint(
            atom,
            callsite_assertion_name(subject.as_ref(), ctx.scope.local_scope()),
        )
    }
}

fn pattern_atom(subject: &Rc<Term>, pattern: &Pat) -> Option<Rc<Formula>> {
    if let Some(variant) = strict_variant_path(pattern) {
        return Some(variant_atom(subject.clone(), &variant));
    }
    if let Some((wrapper, inner)) = wrapped_variant(pattern) {
        return Some(wrapped_variant_atom(subject, &wrapper, inner.as_deref()));
    }
    tuple_pattern_atom(subject, pattern)
}

fn wrapped_variant_atom(subject: &Rc<Term>, wrapper: &str, inner: Option<&str>) -> Rc<Formula> {
    let outer = variant_atom(subject.clone(), wrapper);
    let Some(inner_variant) = inner else {
        return outer;
    };
    let payload = Rc::new(Term::Ctor {
        name: format!("payload:{wrapper}"),
        args: vec![subject.clone()],
    });
    and_(vec![outer, variant_atom(payload, inner_variant)])
}

fn tuple_pattern_atom(subject: &Rc<Term>, pattern: &Pat) -> Option<Rc<Formula>> {
    let tuple = match strip_pat_ref_paren(pattern) {
        Pat::Tuple(tuple) => tuple,
        _ => return None,
    };
    let mut atoms = Vec::new();
    for (i, elem) in tuple.elems.iter().enumerate() {
        let elem = strip_pat_ref_paren(elem);
        if matches!(elem, Pat::Wild(_)) {
            continue;
        }
        let field = Rc::new(Term::Ctor {
            name: format!("field:{i}"),
            args: vec![subject.clone()],
        });
        if let Some(variant) = strict_variant_path(elem) {
            atoms.push(variant_atom(field, &variant));
        } else if let Pat::Lit(lit) = elem {
            atoms.push(eq(field, lit_membership_term(&lit.lit)?));
        } else {
            return None;
        }
    }
    if atoms.is_empty() {
        return None;
    }
    Some(and_(atoms))
}

fn strip_pat_ref_paren(pattern: &Pat) -> &Pat {
    match pattern {
        Pat::Reference(reference) => strip_pat_ref_paren(&reference.pat),
        Pat::Paren(paren) => strip_pat_ref_paren(&paren.pat),
        other => other,
    }
}

fn variant_atom(subject: Rc<Term>, variant: &str) -> Rc<Formula> {
    let variant_of = Rc::new(Term::Ctor {
        name: "variant_of".to_string(),
        args: vec![subject],
    });
    eq(variant_of, str_const(format!("variant::{variant}")))
}

fn constraint(atom: Rc<Formula>, name: Option<String>) -> Outcome {
    Outcome::Complete(Desugared::Constraints {
        atom,
        n: 1,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name },
    })
}

fn term_payload(
    expr: &Expr,
    ctx: &SugarCtx,
    captured_let_inits: &BTreeMap<String, Expr>,
) -> Result<Rc<Term>, Outcome> {
    let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
    let let_inits: BTreeMap<String, &Expr> = stable
        .iter()
        .map(|(name, init)| (name.clone(), init))
        .chain(
            captured_let_inits
                .iter()
                .map(|(name, init)| (name.clone(), init)),
        )
        .collect();
    let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
    match build_term(expr, &fcx).desugar(ctx) {
        Outcome::Complete(desugared) => desugared.into_term().ok_or_else(|| {
            Outcome::Incomplete(Effect::Unsupported {
                reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
            })
        }),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn unsupported(reason: String) -> Outcome {
    Outcome::Incomplete(Effect::Unsupported { reason })
}
