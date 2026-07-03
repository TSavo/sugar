// SPDX-License-Identifier: Apache-2.0
//
// LiteralIteratorQuantifierSugar: constraint-position `.all(..)` / `.any(..)`
// over a finite literal iterator. This node is deliberately boring glue: the
// receiver body owns sequence construction, the predicate body owns its own term
// floor, and this sugar only curries that predicate over each element and joins
// the resulting boolean floors.
//
// MIGRATION NOTE (Phase-3 ratchet). Fully migrated:
//   * `recognize` uses ONLY `SourceFragment` typed accessors -- no `as_expr()`,
//     no `Expr::` / `ExprMethodCall` field access, no raw syn in this body.
//   * `LiteralIteratorQuantifierSugar` holds NO raw syn field: `method:
//     Quantifier` (clean enum), `receiver: SugarBody<CompositeFloor>` and
//     `predicate: QuantifierPredicate { param: String, body: SugarBody<TermFloor>
//     }` -- all fragment-derived, no raw syn.

use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, or_, Formula, Term};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_dispatch::{
    CurryOccurrence, CurryVisitor, DesugaredFloorAccept, LiteralPredicateBoolVisitor,
    TermFloorAccept,
};
use crate::{
    ascii_byte_class_atom, ascii_char_class_atom, assertion_entry_from_relation, bool_const,
    const_fold_int_term, const_val_term, make_var, token_key, AssertionFactKind, Desugared,
    DesugaredElem, Outcome, RelationOp, Sugar, SugarCtx, Warrant,
};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_literal_iterator_quantifier",
    SugarRole::Constraint,
    crate::sugar::claim::SugarWitnesses::Pending,
    recognize,
);

#[derive(Clone, Copy)]
enum Quantifier {
    All,
    Any,
}

struct LiteralIteratorQuantifierSugar {
    method: Quantifier,
    receiver: SugarBody<CompositeFloor>,
    predicate: QuantifierPredicate,
}

struct QuantifierPredicate {
    param: String,
    body: SugarBody<TermFloor>,
}

// FULLY MIGRATED (Phase-3 ratchet): no as_expr(), no raw Expr:: / ExprMethodCall
// field access in this body. Uses call_method_key(), call_arg_count(), call_args(),
// call_receiver(), closure_single_param_name(), closure_body_frag(),
// build_literal_sequence_composite_frag(), SugarBody::from_node(), and
// SugarBody::term_frag() exclusively. All raw syn stays inside those accessors.
fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Must be a MethodCall named "all" or "any" with exactly one argument.
    let method = match frag.call_method_key()?.as_str() {
        "all" if frag.call_arg_count() == 1 => Quantifier::All,
        "any" if frag.call_arg_count() == 1 => Quantifier::Any,
        _ => return None,
    };

    // The single argument must be a closure with one named parameter.
    let args = frag.call_args();
    let arg_frag = args.first()?;
    let param = arg_frag.closure_single_param_name()?;

    // Build receiver as a literal-sequence composite.
    let receiver_frag = frag.call_receiver()?;
    let receiver = SugarBody::from_node(receiver_frag.build_literal_sequence_composite_frag(fcx)?);

    // Build predicate body from the closure body fragment.
    let body_frag = arg_frag.closure_body_frag()?;
    let body = SugarBody::term_frag(&body_frag, fcx);

    Some(Box::new(LiteralIteratorQuantifierSugar {
        method,
        receiver,
        predicate: QuantifierPredicate { param, body },
    }))
}

impl Sugar for LiteralIteratorQuantifierSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self.receiver.reduce(ctx) {
            Outcome::Complete(desugared) => desugared
                .into_seq()
                .unwrap_or_else(|| quantifier_gap("receiver completed as non-sequence")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };

        let mut atoms = Vec::with_capacity(seq.len());
        let mut warranted = true;
        for (idx, elem) in seq.into_iter().enumerate() {
            let term = match self.predicate.curried_term(&elem, idx, ctx) {
                Ok(term) => term,
                Err(outcome) => return outcome,
            };
            let PredicateAtom { atom, literal } = predicate_atom(term, ctx);
            warranted &= literal;
            atoms.push(atom);
        }

        Outcome::Complete(Desugared::Constraints {
            atom: self.join(atoms),
            n: 1,
            kind: if warranted {
                AssertionFactKind::Warranted
            } else {
                AssertionFactKind::Support
            },
            warrant: Warrant { name: None },
        })
    }
}

impl LiteralIteratorQuantifierSugar {
    fn join(&self, atoms: Vec<Rc<Formula>>) -> Rc<Formula> {
        match self.method {
            Quantifier::All => {
                if atoms.is_empty() {
                    eq(bool_const(true), bool_const(true))
                } else {
                    and_(atoms)
                }
            }
            Quantifier::Any => {
                if atoms.is_empty() {
                    eq(bool_const(true), bool_const(false))
                } else {
                    or_(atoms)
                }
            }
        }
    }
}

impl QuantifierPredicate {
    fn curried_term(
        &self,
        elem: &DesugaredElem,
        ordinal: usize,
        ctx: &SugarCtx,
    ) -> Result<Rc<Term>, Outcome> {
        let elem_term = elem_term_floor(elem);
        let curried = match self.body.reduce(ctx) {
            Outcome::Complete(desugared) => desugared.accept_desugared_floor(CurryVisitor {
                param: &self.param,
                arg: &elem_term,
                occurrence: CurryOccurrence {
                    family: "quant",
                    ordinal,
                },
            }),
            Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
        };
        Ok(curried
            .into_term()
            .unwrap_or_else(|| quantifier_gap("predicate body completed as non-term")))
    }
}

struct PredicateAtom {
    atom: Rc<Formula>,
    literal: bool,
}

fn predicate_atom(term: Rc<Term>, ctx: &SugarCtx) -> PredicateAtom {
    let literal = term
        .accept_term_floor(LiteralPredicateBoolVisitor)
        .is_some();
    if let Some(atom) = predicate_formula_from_term(&term, ctx) {
        PredicateAtom { atom, literal }
    } else if let Some(value) = term.accept_term_floor(LiteralPredicateBoolVisitor) {
        PredicateAtom {
            atom: eq(bool_const(value), bool_const(true)),
            literal: true,
        }
    } else {
        PredicateAtom {
            atom: eq(term, bool_const(true)),
            literal: false,
        }
    }
}

fn predicate_formula_from_term(term: &Rc<Term>, ctx: &SugarCtx) -> Option<Rc<Formula>> {
    match term.as_ref() {
        Term::Ctor { name, args } if args.len() == 2 => {
            let op = relation_from_cmp_ctor(name)?;
            Some(
                assertion_entry_from_relation(args[0].clone(), args[1].clone(), op, ctx.scope).atom,
            )
        }
        Term::Ctor { name, args } if name.starts_with("method:") && args.len() == 1 => {
            let method = name.strip_prefix("method:")?;
            let receiver = peel_deref_term(args[0].clone());
            if const_fold_int_term(&receiver).is_some() {
                ascii_byte_class_atom(method, receiver)
            } else {
                ascii_char_class_atom(method, receiver)
            }
        }
        _ => None,
    }
}

fn relation_from_cmp_ctor(name: &str) -> Option<RelationOp> {
    match name {
        "cmp:eq" => Some(RelationOp::Eq),
        "cmp:neq" => Some(RelationOp::Ne),
        "cmp:lt" => Some(RelationOp::Lt),
        "cmp:le" => Some(RelationOp::Le),
        "cmp:gt" => Some(RelationOp::Gt),
        "cmp:ge" => Some(RelationOp::Ge),
        _ => None,
    }
}

fn peel_deref_term(mut term: Rc<Term>) -> Rc<Term> {
    while let Term::Ctor { name, args } = term.as_ref() {
        if name == "deref" && args.len() == 1 {
            term = args[0].clone();
        } else {
            break;
        }
    }
    term
}

fn elem_term_floor(elem: &DesugaredElem) -> Rc<Term> {
    elem.value
        .as_ref()
        .and_then(const_val_term)
        .unwrap_or_else(|| make_var(format!("opaque:quantifier-elem:{}", token_key(&elem.expr))))
}

fn quantifier_gap(reason: &str) -> ! {
    panic!("literal iterator quantifier did not reach typed floors: {reason}")
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source string -> SourceFragment -> assert observed ->
    // assert frag accessors -> recognize() -> assert Some/None.
    // No parse_quote!, no StubTerm, no run().
    // Proves: recognize body has zero as_expr/raw-syn; struct holds only
    // SugarBody<CompositeFloor> + SugarBody<TermFloor> + String + Quantifier enum.
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
    use crate::{LiftOptions, TemporalPlan, TemporalScope};
    use std::collections::BTreeMap;
    use syn::Expr;

    fn tail_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let fn_frag = SourceFragment::from_node(FragNode::Item(&file.items[0]), file_str);
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        stmts[0].terms()[0]
    }

    fn make_fcx<'a, 'e>(
        scope: &'a TemporalScope,
        options: &'a LiftOptions,
        let_inits: &'a BTreeMap<String, &'e Expr>,
    ) -> SugarBuildCtx<'a, 'e> {
        SugarBuildCtx::new(scope, options, let_inits)
    }

    /// Positive: `[1u8, 2u8, 3u8].iter().all(|x| *x < 10)` is the recognized
    /// shape. Verifies the full accessor chain and that recognize returns Some.
    #[test]
    fn from_src_all_over_literal_array_recognized() {
        let src = "fn f() -> bool { [1u8, 2u8, 3u8].iter().all(|x| *x < 10) }";
        let file = parse_file(src);
        let frag = tail_expr_frag(&file, "t.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert_eq!(frag.call_method_key().as_deref(), Some("all"));
        assert_eq!(frag.call_arg_count(), 1);

        let args = frag.call_args();
        let arg_frag = &args[0];
        assert_eq!(
            arg_frag.closure_single_param_name().as_deref(),
            Some("x"),
            "closure_single_param_name must extract the parameter name"
        );
        assert!(arg_frag.closure_body_frag().is_some());
        assert!(frag.call_receiver().is_some());

        let scope = TemporalScope::new("quant-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_some(),
            "recognized shape must return Some"
        );
    }

    /// Discrimination: `.any()` with zero arguments is rejected by call_arg_count guard.
    #[test]
    fn from_src_any_zero_args_not_recognized() {
        let src = "fn f(v: &[u8]) -> bool { v.iter().any() }";
        let file = parse_file(src);
        let frag = tail_expr_frag(&file, "t.rs");

        assert_eq!(frag.call_method_key().as_deref(), Some("any"));
        assert_eq!(frag.call_arg_count(), 0);

        let scope = TemporalScope::new("quant-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_none(),
            "zero-arg .any() must not be recognized"
        );
    }

    /// Structural: `.len()` is not named "all"/"any" -- rejected immediately.
    #[test]
    fn from_src_unrelated_method_not_recognized() {
        let src = "fn f(v: &[u8]) -> usize { v.len() }";
        let file = parse_file(src);
        let frag = tail_expr_frag(&file, "t.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert_eq!(frag.call_method_key().as_deref(), Some("len"));

        let scope = TemporalScope::new("quant-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_none(),
            "v.len() must not be recognized"
        );
    }
}
