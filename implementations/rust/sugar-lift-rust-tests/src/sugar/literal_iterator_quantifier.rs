// SPDX-License-Identifier: Apache-2.0
//
// LiteralIteratorQuantifierSugar: constraint-position `.all(..)` / `.any(..)`
// over a finite literal iterator. This node is deliberately boring glue: the
// receiver body owns sequence construction, the predicate body owns its own term
// floor, and this sugar only curries that predicate over each element and joins
// the resulting boolean floors.

use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, or_, Formula, Term};
use syn::{Expr, ExprMethodCall};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::method_family;
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

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    recognize_method(call, fcx).map(|sugar| Box::new(sugar) as Box<dyn Sugar>)
}

fn recognize_method(
    call: &ExprMethodCall,
    fcx: &SugarBuildCtx,
) -> Option<LiteralIteratorQuantifierSugar> {
    let method = match call.method.to_string().as_str() {
        "all" if call.args.len() == 1 => Quantifier::All,
        "any" if call.args.len() == 1 => Quantifier::Any,
        _ => return None,
    };
    let Expr::Closure(closure) = call.args.first()? else {
        return None;
    };
    let param = closure_simple_param_name(closure)?;
    Some(LiteralIteratorQuantifierSugar {
        method,
        receiver: SugarBody::from_node(method_family::build_literal_sequence_composite(
            &call.receiver,
            fcx,
        )?),
        predicate: QuantifierPredicate {
            param,
            body: SugarBody::term(closure.body.as_ref(), fcx),
        },
    })
}

/// The bound parameter name of a single-parameter closure, accepting `|x|` and a
/// reference pattern `|&x|` (and `|&mut x|`), through a type ascription `|x: T|`.
/// `None` for a wildcard `|_|` or any destructuring pattern.
fn closure_simple_param_name(closure: &syn::ExprClosure) -> Option<String> {
    fn ident_of(pat: &syn::Pat) -> Option<String> {
        match pat {
            syn::Pat::Ident(id) if id.subpat.is_none() => Some(id.ident.to_string()),
            syn::Pat::Reference(r) => ident_of(&r.pat),
            syn::Pat::Paren(p) => ident_of(&p.pat),
            syn::Pat::Type(t) => ident_of(&t.pat),
            _ => None,
        }
    }
    ident_of(closure.inputs.first()?)
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
