// SPDX-License-Identifier: Apache-2.0
//
// MatchesMacroSugar: `matches!(subject, Pattern)` is a constraint-shaped
// assertion vocabulary entry. The subject is built through the normal term
// factory so bound variables keep their RHS/callsite identity; this node owns
// only the pattern-to-constraint semantics.

use std::rc::Rc;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    callsite_assertion_name, lit_membership_term, strict_variant_path, token_key, wrapped_variant,
    AssertionFactKind, Desugared, Outcome, Sugar, SugarCtx, Warrant,
};
use sugar_ir_symbolic::{and_, eq, str_const, Formula, Term};
use syn::parse::{ParseStream, Parser};
use syn::{Expr, ExprMacro, Pat, Token};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_matches_macro",
    SugarRole::Constraint,
    crate::sugar::claim::SugarWitnesses::Pending,
    recognize,
);

struct MatchesMacroSugar {
    subject: SugarBody<TermFloor>,
    pattern: Pat,
    site: String,
}

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Macro(ExprMacro { mac, .. }) = expr else {
        return None;
    };
    if !mac.path.is_ident("matches") {
        return None;
    }
    let (subject, pattern) = parse_subject_pattern(mac.tokens.clone())?;
    Some(Box::new(MatchesMacroSugar {
        subject: SugarBody::term(&subject, fcx),
        pattern,
        site: token_key(expr),
    }))
}

pub(crate) fn parse_subject_pattern(tokens: proc_macro2::TokenStream) -> Option<(Expr, Pat)> {
    let parser = |input: ParseStream| -> syn::Result<(Expr, Pat)> {
        let subject: Expr = input.parse()?;
        input.parse::<Token![,]>()?;
        let pat = Pat::parse_multi_with_leading_vert(input)?;
        let _ = input.parse::<proc_macro2::TokenStream>();
        Ok((subject, pat))
    };
    Parser::parse2(parser, tokens).ok()
}

impl Sugar for MatchesMacroSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let subject = match term_payload(&self.subject, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let Some(atom) = pattern_atom(&subject, &self.pattern) else {
            matches_macro_gap(&format!(
                "matches! pattern is not an unambiguous qualified variant \
                 (binding/wildcard/single-segment/or-pattern): `{}`",
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

fn term_payload(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(desugared) => Ok(desugared
            .into_term()
            .unwrap_or_else(|| matches_macro_gap("subject reduced to a non-term floor"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn matches_macro_gap(reason: &str) -> ! {
    panic!("matches_macro did not reach a lawful floor: {reason}")
}
