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

use std::rc::Rc;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{
    has_tuple_producer_frag, SugarBody, SugarBuildCtx, TermFloor, TupleProducerFloor,
};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    callsite_assertion_name, parse_macro_args, AssertionFactKind, Desugared, Outcome, Sugar,
    SugarCtx, Warrant,
};
use sugar_ir_symbolic::{and_, atomic_, Term};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_tuple_decomp",
    SugarRole::Constraint,
    crate::sugar::claim::SugarWitnesses::Pending,
    recognize,
);

pub(crate) const ASSERTION_SURFACE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "assertion_surface_tuple_decomp",
    SugarRole::AssertionSurface,
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
                #[test]
                fn t_tuple_decomp_good() {
                    assert_eq!(3.14159265359f32.integer_decode(), (13176795, -22, 1));
                }
            "#,
        r#"
                #[test]
                fn t_tuple_decomp_bad() {
                    assert_eq!(3.14159265359f32.integer_decode(), (13176796, -22, 1));
                }
            "#,
    ),
    recognize,
);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if let Some(inner) = frag.transparent_inner() {
        return recognize(&inner, fcx);
    }
    if frag.binop_op_kind() == Some("Eq") {
        let lhs = frag.binop_left()?;
        let rhs = frag.binop_right()?;
        return recognize_eq_parts(&lhs, &rhs, fcx);
    }
    let name = frag.macro_name()?;
    if !matches!(name.as_str(), "assert_eq" | "debug_assert_eq") {
        return None;
    }
    let tokens = frag.macro_token_stream()?;
    let args = parse_macro_args(tokens).ok()?;
    if args.exprs.len() < 2 {
        return None;
    }
    let lhs_frag = SourceFragment::expr(&args.exprs[0], frag.file);
    let rhs_frag = SourceFragment::expr(&args.exprs[1], frag.file);
    recognize_eq_parts(&lhs_frag, &rhs_frag, fcx)
}

fn recognize_eq_parts<'a>(
    lhs: &SourceFragment<'a>,
    rhs: &SourceFragment<'a>,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let maybe_lhs_elems = literal_tuple_elements_frag(lhs);
    let maybe_rhs_elems = literal_tuple_elements_frag(rhs);
    if let (Some(lhs_elems), Some(rhs_elems)) = (&maybe_lhs_elems, &maybe_rhs_elems) {
        if !lhs_elems.is_empty() && lhs_elems.len() == rhs_elems.len() {
            return Some(TupleDecompSugar::new(TupleDecompKind::LiteralPair {
                lhs_terms: lhs_elems
                    .iter()
                    .map(|f| SugarBody::term_frag(f, fcx))
                    .collect(),
                rhs_terms: rhs_elems
                    .iter()
                    .map(|f| SugarBody::term_frag(f, fcx))
                    .collect(),
            }));
        }
    }
    let (producer, literal_frags) = match_producer_and_literal(lhs, rhs, fcx)?;
    if literal_frags.is_empty() {
        return None;
    }
    Some(TupleDecompSugar::new(TupleDecompKind::ProducerLiteral {
        producer,
        literal_terms: literal_frags
            .iter()
            .map(|f| SugarBody::term_frag(f, fcx))
            .collect(),
    }))
}

/// Strip `Paren`/`Group` wrappers then return the elements of a literal `Expr::Tuple`,
/// or `None` if the inner expression is not a non-empty tuple.
fn literal_tuple_elements_frag<'a>(frag: &SourceFragment<'a>) -> Option<Vec<SourceFragment<'a>>> {
    let mut f = *frag;
    while let Some(inner) = f.transparent_inner() {
        f = inner;
    }
    let elems = f.tuple_elems()?;
    if elems.is_empty() {
        return None;
    }
    Some(elems)
}

/// Resolve `(producer_sugar, literal_tuple_element_frags)` from the two sides, in either
/// order. A "producer" is a tuple-valued expr whose component decomposition is owned by
/// its Sugar and delayed until `desugar`; a plain literal tuple is NOT a producer here.
fn match_producer_and_literal<'a>(
    lhs: &SourceFragment<'a>,
    rhs: &SourceFragment<'a>,
    fcx: &SugarBuildCtx,
) -> Option<(SugarBody<TupleProducerFloor>, Vec<SourceFragment<'a>>)> {
    if has_tuple_producer_frag(lhs, fcx) {
        if let Some(l) = literal_tuple_elements_frag(rhs) {
            return Some((SugarBody::tuple_producer_frag(lhs, fcx), l));
        }
    }
    if has_tuple_producer_frag(rhs, fcx) {
        if let Some(l) = literal_tuple_elements_frag(lhs) {
            return Some((SugarBody::tuple_producer_frag(rhs, fcx), l));
        }
    }
    None
}

enum TupleDecompKind {
    ProducerLiteral {
        producer: SugarBody<TupleProducerFloor>,
        literal_terms: Vec<SugarBody<TermFloor>>,
    },
    LiteralPair {
        lhs_terms: Vec<SugarBody<TermFloor>>,
        rhs_terms: Vec<SugarBody<TermFloor>>,
    },
}

struct TupleDecompSugar {
    kind: TupleDecompKind,
}

impl Sugar for TupleDecompSugar {
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        match &self.kind {
            TupleDecompKind::ProducerLiteral {
                producer,
                literal_terms,
            } => {
                let producer_components = match producer.reduce(ctx) {
                    Outcome::Complete(desugared) => match desugared.into_tuple_components() {
                        Some(components) => components,
                        None => {
                            unreachable!("typed tuple producer reduced to non-tuple-components")
                        }
                    },
                    Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
                };
                if producer_components.len() != literal_terms.len() {
                    panic!("tuple decomp arity mismatch");
                }
                let mut atoms = Vec::with_capacity(literal_terms.len());
                let mut anchor: Option<Rc<Term>> = None;
                for (lhs_term, rhs) in producer_components.into_iter().zip(literal_terms) {
                    let rhs_term = match term_payload(rhs, ctx) {
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
                lhs_terms,
                rhs_terms,
            } => {
                if lhs_terms.len() != rhs_terms.len() {
                    panic!("tuple literal decomp arity mismatch");
                }
                let mut atoms = Vec::with_capacity(lhs_terms.len());
                let mut anchor: Option<Rc<Term>> = None;
                for (lhs, rhs) in lhs_terms.iter().zip(rhs_terms) {
                    let lhs_term = match term_payload(lhs, ctx) {
                        Ok(term) => term,
                        Err(outcome) => return outcome,
                    };
                    let rhs_term = match term_payload(rhs, ctx) {
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

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
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
    Outcome::Complete(Desugared::Constraints {
        atom,
        n: 1,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name },
    })
}

impl TupleDecompSugar {
    fn new(kind: TupleDecompKind) -> Box<dyn Sugar> {
        Box::new(Self { kind })
    }
}

fn term_payload(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(desugared) => Ok(desugared
            .into_term()
            .unwrap_or_else(|| panic!("typed tuple decomp literal reduced to non-term"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::factory::SugarBuildCtx;
    use crate::sugar::source_fragment::SourceFragment;
    use crate::{LiftOptions, TemporalPlan, TemporalScope};
    use std::collections::BTreeMap;
    use syn::Expr;

    fn make_fcx_and_scope() -> (TemporalScope, LiftOptions) {
        (
            TemporalScope::new("tuple-decomp-test", TemporalPlan::default()),
            LiftOptions::default(),
        )
    }

    /// Positive: binary `==` comparing two literal tuples of matching arity is recognized.
    /// Exercises `binop_op_kind()` == `"Eq"` and `tuple_elems()` via `literal_tuple_elements_frag`.
    #[test]
    fn from_src_literal_pair_binop_recognized() {
        let (scope, options) = make_fcx_and_scope();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let expr: Expr = syn::parse_str("(1u64, 2i32) == (3u64, 4i32)").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");
        assert_eq!(frag.binop_op_kind(), Some("Eq"), "accessor gate: op kind");
        assert!(
            recognize(&frag, &fcx).is_some(),
            "literal-pair binary == should be recognized"
        );
    }

    /// Positive: `assert_eq!` macro with two literal tuples is recognized.
    /// Exercises `macro_name()` accessor and the macro dispatch path.
    #[test]
    fn from_src_assert_eq_macro_literal_pair_recognized() {
        let (scope, options) = make_fcx_and_scope();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let expr: Expr = syn::parse_str("assert_eq!((1u64, 2i32), (3u64, 4i32))").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");
        assert_eq!(
            frag.macro_name(),
            Some("assert_eq".to_string()),
            "accessor gate: macro name"
        );
        assert!(
            recognize(&frag, &fcx).is_some(),
            "assert_eq! with literal tuple pair should be recognized"
        );
    }

    /// Discrimination: binary `!=` with literal tuples is NOT recognized (only `==` fires).
    /// Exercises `binop_op_kind()` == `"Ne"` discrimination gate.
    #[test]
    fn from_src_ne_binop_with_tuples_not_recognized() {
        let (scope, options) = make_fcx_and_scope();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let expr: Expr = syn::parse_str("(1u64, 2i32) != (3u64, 4i32)").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");
        assert_eq!(
            frag.binop_op_kind(),
            Some("Ne"),
            "accessor gate: op kind is Ne"
        );
        assert!(
            recognize(&frag, &fcx).is_none(),
            "!= with literal tuples should NOT be recognized"
        );
    }
}
