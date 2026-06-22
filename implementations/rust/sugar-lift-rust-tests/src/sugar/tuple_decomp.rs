// SPDX-License-Identifier: Apache-2.0
//
// `tuple_decomp` — the SHARED assertion-surface decomposition for tuple-valued warrants.
//
// `assert_eq!(L, (a, b, c))` / `L == (a, b, c)` where one side is a tuple-valued PRODUCER
// (e.g. `f.integer_decode()`) and the other a literal N-tuple decomposes into per-component
// SCALAR equalities: `(and (= L0 a) (= L1 b) (= L2 c))`. Tuple `PartialEq` IS componentwise,
// so this rewrite is semantically EXACT. Each component is a grounded scalar, which has REAL
// z3 teeth via the integer total order -- a wrong component (`a != a'`) is z3-UNSAT.
//
// WHY: a tuple VALUE otherwise lowers to a single uninterpreted `literal:Tuple(..)` constant
// (a `Term::Ctor`/`Var` with no injectivity axiom), so a whole-tuple comparison is
// CONGRUENCE-ONLY -- a wrong tuple is z3-SAT (two free constants can be equal) = NO TEETH,
// landing UNDECIDED rather than REFUTED. That is a fake light. Decomposing to scalar
// component equalities is the teethed answer.
//
// SHARED MECHANISM: any tuple-valued producer registers its component source-exprs in
// `producer_components`. integer_decode is the first consumer; size_hint, enumerate's
// idx/val split, and partition_point reuse the SAME arm (do NOT each build a local split).
//
// SOUNDNESS / EXACT-OR-NONE: for producer-vs-literal, we only fire when one side is a
// recognized producer (whose components we derive by RUNNING the real host op) AND the
// other is a literal tuple of the SAME arity. Plain literal-tuple-vs-literal-tuple is
// also exact stdlib sugar: tuple `PartialEq` is componentwise, so the same scalar
// decomposition is the literal floor. If a producer cannot derive its components
// (declined), or the arities differ, we decline -> the ordinary equality path applies
// (no regression, never a false discharge).

use std::collections::BTreeMap;
use std::rc::Rc;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_term, build_tuple_producer, has_tuple_producer, SugarBuildCtx};
use crate::{
    callsite_assertion_name, parse_macro_args, AssertionFactKind, Desugared, Effect, Outcome,
    Sugar, SugarCtx, Warrant, STRUCTURAL_BACKSTOP_REASON,
};
use sugar_ir_symbolic::{and_, atomic_, Term};
use syn::{BinOp, Expr, ExprBinary, ExprMacro};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("constraint_tuple_decomp", SugarRole::Constraint, recognize);

pub(crate) const ASSERTION_SURFACE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "assertion_surface_tuple_decomp",
    SugarRole::AssertionSurface,
    recognize,
);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Paren(paren) => recognize(&paren.expr, fcx),
        Expr::Group(group) => recognize(&group.expr, fcx),
        Expr::Binary(binary) => recognize_binary(binary, fcx),
        Expr::Macro(expr_macro) => recognize_macro(expr_macro, fcx),
        _ => None,
    }
}

fn recognize_binary(binary: &ExprBinary, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if !matches!(binary.op, BinOp::Eq(_)) {
        return None;
    }
    build(&binary.left, &binary.right, fcx)
}

fn recognize_macro(expr_macro: &ExprMacro, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let name = expr_macro.mac.path.segments.last()?.ident.to_string();
    if !matches!(name.as_str(), "assert_eq" | "debug_assert_eq") {
        return None;
    }
    let args = parse_macro_args(expr_macro.mac.tokens.clone()).ok()?;
    if args.exprs.len() < 2 {
        return None;
    }
    build(&args.exprs[0], &args.exprs[1], fcx)
}

fn build(lhs: &Expr, rhs: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if let (Some(lhs_exprs), Some(rhs_exprs)) =
        (literal_tuple_elements(lhs), literal_tuple_elements(rhs))
    {
        if !lhs_exprs.is_empty() && lhs_exprs.len() == rhs_exprs.len() {
            return Some(Box::new(TupleDecompSugar {
                kind: TupleDecompKind::LiteralPair {
                    lhs_exprs,
                    rhs_exprs,
                },
            }));
        }
    }

    let (producer, literal_exprs) = match_producer_and_literal(lhs, rhs, fcx)?;
    if literal_exprs.is_empty() {
        return None;
    }
    Some(Box::new(TupleDecompSugar {
        kind: TupleDecompKind::ProducerLiteral {
            producer,
            literal_exprs,
        },
    }))
}

/// Resolve `(producer_sugar, literal_tuple_element_exprs)` from the two sides, in either
/// order. A "producer" is a tuple-valued expr whose component decomposition is owned by
/// its Sugar and delayed until `desugar`; a plain literal tuple is NOT a producer here.
fn match_producer_and_literal(
    lhs: &Expr,
    rhs: &Expr,
    fcx: &SugarBuildCtx,
) -> Option<(Expr, Vec<Expr>)> {
    if has_tuple_producer(lhs, fcx) {
        if let Some(l) = literal_tuple_elements(rhs) {
            return Some((lhs.clone(), l));
        }
    }
    if has_tuple_producer(rhs, fcx) {
        if let Some(l) = literal_tuple_elements(lhs) {
            return Some((rhs.clone(), l));
        }
    }
    None
}

fn literal_tuple_elements(expr: &Expr) -> Option<Vec<Expr>> {
    match strip_paren_group(expr) {
        Expr::Tuple(tuple) if !tuple.elems.is_empty() => {
            Some(tuple.elems.iter().cloned().collect())
        }
        _ => None,
    }
}

fn strip_paren_group(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(paren) => strip_paren_group(&paren.expr),
        Expr::Group(group) => strip_paren_group(&group.expr),
        _ => expr,
    }
}

enum TupleDecompKind {
    ProducerLiteral {
        producer: Expr,
        literal_exprs: Vec<Expr>,
    },
    LiteralPair {
        lhs_exprs: Vec<Expr>,
        rhs_exprs: Vec<Expr>,
    },
}

struct TupleDecompSugar {
    kind: TupleDecompKind,
}

impl Sugar for TupleDecompSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let let_inits = scope_let_inits(ctx);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        match &self.kind {
            TupleDecompKind::ProducerLiteral {
                producer,
                literal_exprs,
            } => {
                let producer = build_tuple_producer(producer, &fcx);
                let literal_terms: Vec<Box<dyn Sugar>> = literal_exprs
                    .iter()
                    .map(|literal| build_term(literal, &fcx))
                    .collect();
                let producer_components = match producer.desugar(ctx) {
                    Outcome::Dug(desugared) => match desugared.into_tuple_components() {
                        Some(components) => components,
                        None => return Outcome::from_opt(None),
                    },
                    Outcome::Hit(effect) => return Outcome::Hit(effect),
                };
                if producer_components.len() != literal_terms.len() {
                    return Outcome::from_opt(None);
                }
                let mut atoms = Vec::with_capacity(literal_terms.len());
                let mut anchor: Option<Rc<Term>> = None;
                for (lhs_term, rhs) in producer_components.into_iter().zip(&literal_terms) {
                    let rhs_term = match term_payload(rhs.as_ref(), ctx) {
                        Ok(term) => term,
                        Err(outcome) => return outcome,
                    };
                    if anchor.is_none() {
                        anchor = Some(Rc::clone(&lhs_term));
                    }
                    atoms.push(atomic_("=".to_string(), vec![lhs_term, rhs_term]));
                }
                constraints(atoms, anchor, ctx)
            }
            TupleDecompKind::LiteralPair {
                lhs_exprs,
                rhs_exprs,
            } => {
                if lhs_exprs.len() != rhs_exprs.len() {
                    return Outcome::from_opt(None);
                }
                let mut atoms = Vec::with_capacity(lhs_exprs.len());
                let mut anchor: Option<Rc<Term>> = None;
                for (lhs, rhs) in lhs_exprs.iter().zip(rhs_exprs) {
                    let lhs_term = match term_from_expr(lhs, &fcx, ctx) {
                        Ok(term) => term,
                        Err(outcome) => return outcome,
                    };
                    let rhs_term = match term_from_expr(rhs, &fcx, ctx) {
                        Ok(term) => term,
                        Err(outcome) => return outcome,
                    };
                    if anchor.is_none() {
                        anchor = Some(Rc::clone(&lhs_term));
                    }
                    atoms.push(atomic_("=".to_string(), vec![lhs_term, rhs_term]));
                }
                constraints(atoms, anchor, ctx)
            }
        }
    }
}

fn constraints(
    atoms: Vec<Rc<sugar_ir_symbolic::Formula>>,
    anchor: Option<Rc<Term>>,
    ctx: &SugarCtx,
) -> Outcome {
    let atom = and_(atoms);
    let name =
        anchor.and_then(|term| callsite_assertion_name(term.as_ref(), ctx.scope.local_scope()));
    Outcome::Dug(Desugared::Constraints {
        atom,
        n: 1,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name },
    })
}

fn scope_let_inits<'a, 'c>(ctx: &SugarCtx<'a, 'c>) -> BTreeMap<String, &'a Expr> {
    ctx.scope
        .let_bindings_iter()
        .map(|(name, init)| (name.clone(), init))
        .collect()
}

fn term_payload(node: &dyn Sugar, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match node.desugar(ctx) {
        Outcome::Dug(desugared) => desugared.into_term().ok_or_else(|| {
            Outcome::Hit(Effect::Unsupported {
                reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
            })
        }),
        Outcome::Hit(effect) => Err(Outcome::Hit(effect)),
    }
}

fn term_from_expr(expr: &Expr, fcx: &SugarBuildCtx, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    let node = build_term(expr, fcx);
    term_payload(node.as_ref(), ctx)
}
