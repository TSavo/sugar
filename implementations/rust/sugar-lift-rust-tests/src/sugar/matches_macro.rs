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
    callsite_assertion_name, lit_membership_term, strict_variant_path, token_key,
    AssertionFactKind, Desugared, Effect, Outcome, Sugar, SugarCtx, Warrant,
};
use sugar_ir_symbolic::{and_, eq, str_const, Formula, Term};
use syn::parse::{ParseStream, Parser};
use syn::{Expr, ExprMacro, Pat, Token};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_matches_macro",
    SugarRole::Constraint,
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
            #[test]
            fn t_matches_macro_good() {
                assert!(matches!(Some(2_i32), Some(2_i32)));
            }
        "#,
        r#"
            #[test]
            fn t_matches_macro_bad() {
                assert!(matches!(Some(2_i32), Some(3_i32)));
            }
        "#,
    ),
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
            return Outcome::Incomplete(Effect::UnencodedMacroPattern {
                macro_name: "matches".to_string(),
                boundary: self.site.clone(),
            });
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
    if let Some(atom) = wrapped_variant_pattern_atom(subject, pattern) {
        return Some(atom);
    }
    tuple_pattern_atom(subject, pattern)
}

fn wrapped_variant_pattern_atom(subject: &Rc<Term>, pattern: &Pat) -> Option<Rc<Formula>> {
    let Pat::TupleStruct(tuple) = strip_pat_ref_paren(pattern) else {
        return None;
    };
    if tuple.path.segments.len() != 1 || tuple.elems.len() != 1 {
        return None;
    }
    let wrapper = tuple.path.segments[0].ident.to_string();
    if !matches!(wrapper.as_str(), "Some" | "Ok" | "Err") {
        return None;
    }
    let outer = variant_atom(subject.clone(), &wrapper);
    let inner = strip_pat_ref_paren(&tuple.elems[0]);
    if matches!(inner, Pat::Wild(_)) {
        return Some(outer);
    }
    if let Some(inner_variant) = strict_variant_path(inner) {
        let payload = payload_term(subject, &wrapper);
        return Some(and_(vec![outer, variant_atom(payload, &inner_variant)]));
    }
    if let Pat::Lit(lit) = inner {
        let payload = payload_term(subject, &wrapper);
        return Some(and_(vec![
            outer,
            eq(payload, lit_membership_term(&lit.lit)?),
        ]));
    }
    Some(outer)
}

fn payload_term(subject: &Rc<Term>, wrapper: &str) -> Rc<Term> {
    if let Some(payload) = known_single_payload(subject, wrapper) {
        return payload;
    }
    Rc::new(Term::Ctor {
        name: format!("payload:{wrapper}"),
        args: vec![subject.clone()],
    })
}

fn known_single_payload(subject: &Rc<Term>, wrapper: &str) -> Option<Rc<Term>> {
    let Term::Ctor { name, args } = subject.as_ref() else {
        return None;
    };
    if args.len() != 1 {
        return None;
    }
    let expected = match wrapper {
        "Some" => "opt:some",
        "Ok" => "res:ok",
        "Err" => "res:err",
        _ => return None,
    };
    (name == expected).then(|| Rc::clone(&args[0]))
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

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use syn::{parse_quote, Expr};

    use super::*;
    use crate::{
        refusal_disposition, sugar_ctx, Disposition, FloatWidthScope, LiftOptions, ReductionCtx,
        TemporalPlan, TemporalScope,
    };

    fn run(expr: &Expr) -> Outcome {
        let scope = TemporalScope::new("matches-macro-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let frag = SourceFragment::expr(expr, "<src>");
        let node = recognize(&frag, &fcx).expect("matches! is owned by matches_macro");
        let items = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        node.desugar(&ctx)
    }

    #[test]
    fn qualified_variant_pattern_still_completes() {
        let expr: Expr = parse_quote!(matches!(status, Status::Ready));
        match run(&expr) {
            Outcome::Complete(Desugared::Constraints { .. }) => {}
            _ => panic!("qualified variant pattern must complete"),
        }
    }

    #[test]
    fn literal_or_pattern_is_typed_macro_pattern_effect() {
        let expr: Expr = parse_quote!(matches!(name, ".git" | "target"));
        let Outcome::Incomplete(Effect::UnencodedMacroPattern {
            macro_name,
            boundary,
        }) = run(&expr)
        else {
            panic!("literal or-pattern must be a typed matches! pattern effect")
        };
        assert_eq!(macro_name, "matches");
        assert!(
            boundary.contains("\".git\""),
            "boundary names pattern: {boundary}"
        );
        let reason = (Effect::UnencodedMacroPattern {
            macro_name,
            boundary,
        })
        .reason();
        assert_eq!(refusal_disposition(&reason), Disposition::TerminalEffect);
    }

    #[test]
    fn binding_pattern_is_not_swallowed_as_qualified_variant() {
        let expr: Expr = parse_quote!(matches!(name, value));
        let Outcome::Incomplete(Effect::UnencodedMacroPattern {
            macro_name,
            boundary,
        }) = run(&expr)
        else {
            panic!("binding-style pattern must not be treated as a variant")
        };
        assert_eq!(macro_name, "matches");
        assert!(
            boundary.contains("value"),
            "boundary carries the unsupported binding pattern: {boundary}"
        );
    }
}
