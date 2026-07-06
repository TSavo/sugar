// SPDX-License-Identifier: MIT OR Apache-2.0
//
// ConstraintSugar family: source shapes whose semantic output is a ProofIR
// constraint. The collector asks for the `Constraint` role; these claims own
// syntax entry points that expose an assertion-shaped expression. The proof
// meaning is the expression shape underneath (`lhs cmp rhs`, boolean
// connective, panic locus), not a human method name.

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::configuration;
use crate::sugar::constraint_runtime_boundary;
use crate::sugar::method_family;
use std::collections::BTreeMap;
use std::rc::Rc;

use crate::sugar::factory::{
    ConstraintFloor, FloorRead, PredicateValueFloor, SugarBody, SugarBuildCtx, TermFloor,
};
use crate::sugar::float_floor;
use crate::sugar::predicate_value::PredicateValue;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    ascii_byte_class_atom, ascii_char_class_atom, assertion_entry_from_relation, bool_const,
    callsite_assertion_name, const_fold_int_term, const_fold_u128_term, is_immutable_value_expr,
    is_literal_identity_term, literal_char_predicate_atom, literal_string_value, parse_macro_args,
    strip_refs_groups, sugar_ctx_with_factory_audits, token_key, AssertionEntry, AssertionFactKind,
    CfgDisposition, CfgPredicate, Desugared, Effect, FactoryAuditLog, FloatWidthScope, LiftOptions,
    Outcome, ReductionCtx, RelationOp, Sugar, SugarCtx, TemporalScope, Warrant,
};
use sugar_ir_symbolic::{and_, atomic_, eq, not_, num, str_const, ConstValue, Formula, Term};
use syn::parse::{Parse, ParseStream};
use syn::{BinOp, Expr, ExprIf, ExprLit, ExprMacro, Item, Lit, Token, Type, UnOp};
use tracing::debug;

pub(crate) const RELATION_MACRO_SUGAR: ExprSugarClaim = ExprSugarClaim::fallback_with_ordering(
    "constraint_relation_macro",
    SugarRole::Constraint,
    &["constraint_bool_expr"],
    crate::sugar::claim::SugarWitnesses::reasoned_bucket(
        "owner-mismatch macro row: relation witnesses dispatch through assertion-surface owners",
    ),
    recognize_relation_macro,
);

pub(crate) const RELATION_MACRO_ASSERTION_SURFACE: ExprSugarClaim =
    ExprSugarClaim::fallback_with_ordering(
        "assertion_surface_relation_macro",
        SugarRole::AssertionSurface,
        &["assertion_surface_assert_macro", "macro_assertion_surface"],
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_assertion_surface_relation_macro_good() {
                    assert_eq!(3_i32 * 3, 9);
                }
            "#,
            r#"
                #[test]
                fn t_assertion_surface_relation_macro_bad() {
                    assert_eq!(3_i32 * 3, 8);
                }
            "#,
        ),
        recognize_relation_macro,
    );

pub(crate) const BOUNDED_LITERAL_MACRO_SUGAR: ExprSugarClaim = ExprSugarClaim::constraint_before(
    "constraint_bounded_literal_macro",
    &[
        "constraint_relation_macro",
        "constraint_assert_macro",
        "constraint_bool_expr",
    ],
    crate::sugar::claim::SugarWitnesses::reasoned_bucket("owner-mismatch macro row: bounded literal assertion witnesses dispatch to assertion surface"),
    recognize_bounded_literal_macro,
);

pub(crate) const BOUNDED_LITERAL_MACRO_ASSERTION_SURFACE: ExprSugarClaim =
    ExprSugarClaim::with_ordering(
        "assertion_surface_bounded_literal_macro",
        SugarRole::AssertionSurface,
        &[
            "assertion_surface_relation_macro",
            "assertion_surface_assert_macro",
        ],
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                macro_rules! assert_all {
                    ($pred:ident, $($s:expr),+ $(,)?) => {
                        $(for ch in $s.chars() { assert!(ch.$pred()); })+
                    };
                }

                #[test]
                fn t_assertion_surface_bounded_literal_macro_good() {
                    assert_all!(is_ascii, "xyz");
                }
            "#,
            r#"
                macro_rules! assert_all {
                    ($pred:ident, $($s:expr),+ $(,)?) => {
                        $(for ch in $s.chars() { assert!(ch.$pred()); })+
                    };
                }

                #[test]
                fn t_assertion_surface_bounded_literal_macro_bad() {
                    assert_all!(is_ascii, "ø");
                }
            "#,
        ),
        recognize_bounded_literal_macro,
    );

pub(crate) const ASSERT_MACRO_SUGAR: ExprSugarClaim = ExprSugarClaim::constraint_before(
    "constraint_assert_macro",
    &["constraint_bool_expr"],
    crate::sugar::claim::SugarWitnesses::reasoned_bucket(
        "owner-mismatch macro row: assertion witnesses dispatch to assertion-surface macro owners",
    ),
    recognize_assert_macro,
);

pub(crate) const ASSERT_MACRO_ASSERTION_SURFACE: ExprSugarClaim =
    ExprSugarClaim::fallback_assertion_surface(
        "assertion_surface_assert_macro",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_assertion_surface_assert_macro_good() {
                    assert!(4_i32 >= 4);
                }
            "#,
            r#"
                #[test]
                fn t_assertion_surface_assert_macro_bad() {
                    assert!(4_i32 < 4);
                }
            "#,
        ),
        recognize_assert_macro,
    );

pub(crate) const CFG_MACRO_SUGAR: ExprSugarClaim = ExprSugarClaim::constraint_before(
    "constraint_cfg_macro",
    &["constraint_bool_expr"],
    crate::sugar::claim::SugarWitnesses::reasoned_bucket(
        "configuration fact surface missing; target-cfg facts need a typed witness source",
    ),
    recognize_cfg_macro,
);

pub(crate) const BOOL_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::fallback_constraint(
    "constraint_bool_expr",
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
            #[test]
            fn t_constraint_bool_expr_good() {
                assert!(true);
            }
        "#,
        r#"
            #[test]
            fn t_constraint_bool_expr_bad() {
                assert!(false);
            }
        "#,
    ),
    recognize_bool_expr,
);

pub(crate) const IF_PANIC_SUGAR: ExprSugarClaim = ExprSugarClaim::constraint_before(
    "constraint_if_panic",
    &["constraint_bool_expr"],
    crate::sugar::claim::SugarWitnesses::pinned_catch(
        "#3415 family g: panic/guard implication semantic lie remains SAT",
    ),
    recognize_if_panic,
);

pub(crate) const PATTERN_GUARD_SUGAR: ExprSugarClaim = ExprSugarClaim::fallback_constraint(
    "constraint_pattern_guard",
    crate::sugar::claim::SugarWitnesses::reasoned_bucket(
        "if-let pattern guards are runtime control-flow evidence, not scalar constraints",
    ),
    recognize_pattern_guard,
);

pub(crate) const NO_PANIC_CALL_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_no_panic_call",
    SugarRole::SupportConstraint,
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
            #[test]
            fn t_no_panic_call_good() {
                assert_eq!("abc".len(), 3);
            }
        "#,
        r#"
            #[test]
            fn t_no_panic_call_bad() {
                assert_eq!("abc".len(), 4);
            }
        "#,
    ),
    recognize_no_panic_call,
);

pub(crate) fn assertion_entry_with_audits(
    expr: &Expr,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
    factory_audits: Option<&FactoryAuditLog>,
) -> Result<AssertionEntry, Effect> {
    let options = LiftOptions::default();
    let let_inits = BTreeMap::new();
    let fcx = SugarBuildCtx::new(scope, &options, &let_inits);
    let body = SugarBody::<ConstraintFloor>::constraint(expr, &fcx);
    let items: Vec<Item> = Vec::new();
    let reducer = ReductionCtx::from_items_with_imports(&items, scope.macro_registry());
    let mut local_float_widths = float_widths.clone();
    let ctx = sugar_ctx_with_factory_audits(
        scope,
        &options,
        &reducer,
        &mut local_float_widths,
        0,
        factory_audits,
    );
    match body.reduce(&ctx) {
        Outcome::Complete(Desugared::Constraints {
            atom,
            n,
            kind,
            warrant,
        }) => Ok(AssertionEntry {
            name: warrant.name,
            atom,
            fact_span: None,
            kind,
            claim_count: n,
        }),
        Outcome::Complete(_) => {
            constraint_gap("boolean assertion reduced to a non-constraint floor");
        }
        Outcome::Incomplete(effect) => Err(effect),
    }
}

struct RelationMacroSugar {
    name: String,
    lhs: SugarBody<TermFloor>,
    rhs: SugarBody<TermFloor>,
    lhs_expr: Expr,
    rhs_expr: Expr,
    op: RelationOp,
    debug_gated: bool,
}

struct BoundedLiteralMacroSugar {
    negate: bool,
    predicate: String,
    sources: Vec<String>,
}

fn recognize_bounded_literal_macro(
    frag: &SourceFragment,
    _fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Macro(ExprMacro { mac, .. }) = expr else {
        return None;
    };
    let name = mac.path.segments.last()?.ident.to_string();
    let negate = match name.as_str() {
        "assert_all" => false,
        "assert_none" => true,
        _ => return None,
    };
    let args = parse_macro_args(mac.tokens.clone()).ok()?;
    let predicate = bounded_literal_predicate_name(args.exprs.first()?)?;
    let sources: Vec<String> = args.exprs[1..]
        .iter()
        .map(literal_string_value)
        .collect::<Option<_>>()?;
    if sources.is_empty() {
        return None;
    }
    Some(Box::new(BoundedLiteralMacroSugar {
        negate,
        predicate,
        sources,
    }))
}

impl Sugar for BoundedLiteralMacroSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        let mut atoms = Vec::new();
        for source in &self.sources {
            for ch in source.chars() {
                let atom = ascii_char_class_atom(&self.predicate, str_const(ch.to_string()))
                    .or_else(|| literal_char_predicate_atom(&self.predicate, ch));
                let Some(atom) = atom else {
                    constraint_gap(format!(
                        "unsupported bounded literal macro predicate `{}`",
                        self.predicate
                    ));
                };
                atoms.push(if self.negate { not_(atom) } else { atom });
            }
            if !bounded_literal_char_only_predicate(&self.predicate) {
                for byte in source.as_bytes() {
                    let Some(atom) = ascii_byte_class_atom(&self.predicate, num(i128::from(*byte)))
                    else {
                        constraint_gap(format!(
                            "unsupported bounded literal macro predicate `{}`",
                            self.predicate
                        ));
                    };
                    atoms.push(if self.negate { not_(atom) } else { atom });
                }
            }
        }
        if atoms.is_empty() {
            constraint_gap("bounded literal macro emitted no predicate atoms");
        }
        Outcome::Complete(Desugared::Constraints {
            atom: and_(atoms),
            n: 1,
            kind: AssertionFactKind::Warranted,
            warrant: Warrant { name: None },
        })
    }
}

fn bounded_literal_predicate_name(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Path(path) => path.path.get_ident().map(|ident| ident.to_string()),
        Expr::Paren(paren) => bounded_literal_predicate_name(&paren.expr),
        Expr::Group(group) => bounded_literal_predicate_name(&group.expr),
        _ => None,
    }
}

fn bounded_literal_char_only_predicate(method: &str) -> bool {
    matches!(method, "is_alphabetic")
}

fn recognize_relation_macro(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Macro(ExprMacro { mac, .. }) = expr else {
        return None;
    };
    let name = mac.path.segments.last()?.ident.to_string();
    if name == "assert_eq_const_safe" {
        return recognize_assert_eq_const_safe_macro(mac, fcx);
    }
    let (op, debug_gated) = match name.as_str() {
        "assert_eq" => (RelationOp::Eq, false),
        "assert_ne" => (RelationOp::Ne, false),
        "debug_assert_eq" => (RelationOp::Eq, true),
        "debug_assert_ne" => (RelationOp::Ne, true),
        _ => return None,
    };
    let args = parse_macro_args(mac.tokens.clone()).ok()?;
    if args.exprs.len() < 2 {
        return None;
    }
    Some(Box::new(RelationMacroSugar {
        name,
        lhs: SugarBody::term(&args.exprs[0], fcx),
        rhs: SugarBody::term(&args.exprs[1], fcx),
        lhs_expr: args.exprs[0].clone(),
        rhs_expr: args.exprs[1].clone(),
        op,
        debug_gated,
    }))
}

fn recognize_assert_eq_const_safe_macro(
    mac: &syn::Macro,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    if fcx
        .scope()
        .macro_registry()
        .lookup("assert_eq_const_safe")
        .is_none()
    {
        return None;
    }
    let (lhs_expr, rhs_expr) = parse_assert_eq_const_safe_operands(mac.tokens.clone())?;
    Some(Box::new(RelationMacroSugar {
        name: "assert_eq_const_safe".to_string(),
        lhs: SugarBody::term(&lhs_expr, fcx),
        rhs: SugarBody::term(&rhs_expr, fcx),
        lhs_expr,
        rhs_expr,
        op: RelationOp::Eq,
        debug_gated: false,
    }))
}

pub(crate) fn parse_assert_eq_const_safe_operands(
    tokens: proc_macro2::TokenStream,
) -> Option<(Expr, Expr)> {
    let args = syn::parse2::<AssertEqConstSafeArgs>(tokens).ok()?;
    Some((args.lhs, args.rhs))
}

struct AssertEqConstSafeArgs {
    lhs: Expr,
    rhs: Expr,
}

impl Parse for AssertEqConstSafeArgs {
    fn parse(input: ParseStream<'_>) -> syn::Result<Self> {
        let _ty = input.parse::<Type>()?;
        input.parse::<Token![:]>()?;
        let lhs = input.parse::<Expr>()?;
        input.parse::<Token![,]>()?;
        let rhs = input.parse::<Expr>()?;
        if input.peek(Token![,]) {
            input.parse::<Token![,]>()?;
            let _message = input.parse::<proc_macro2::TokenStream>()?;
        }
        Ok(Self { lhs, rhs })
    }
}

impl Sugar for RelationMacroSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(outcome) = inactive_debug_assertion(&self.name, self.debug_gated, ctx) {
            return outcome;
        }
        relation_constraint_from_bodies(
            &format!("{}!", self.name),
            &self.lhs,
            &self.rhs,
            &self.lhs_expr,
            &self.rhs_expr,
            self.op,
            ctx,
        )
    }
}

struct AssertSugar {
    name: String,
    payload: SugarBody<ConstraintFloor>,
    debug_gated: bool,
}

fn recognize_assert_macro(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Macro(ExprMacro { mac, .. }) = expr else {
        return None;
    };
    let name = mac.path.segments.last()?.ident.to_string();
    let debug_gated = match name.as_str() {
        "assert" => false,
        "debug_assert" => true,
        _ => return None,
    };
    let args = parse_macro_args(mac.tokens.clone()).ok()?;
    let expr = args.exprs.first()?.clone();
    Some(Box::new(AssertSugar {
        name,
        payload: SugarBody::constraint(&expr, fcx),
        debug_gated,
    }))
}

impl Sugar for AssertSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(outcome) = inactive_debug_assertion(&self.name, self.debug_gated, ctx) {
            return outcome;
        }
        self.payload.reduce(ctx)
    }
}

struct CfgMacroSugar {
    mac: syn::Macro,
}

fn recognize_cfg_macro(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Macro(ExprMacro { mac, .. }) = expr else {
        return None;
    };
    if !mac
        .path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == "cfg")
    {
        return None;
    }
    Some(Box::new(CfgMacroSugar { mac: mac.clone() }))
}

impl Sugar for CfgMacroSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let predicate = match self.mac.parse_body::<CfgPredicate>() {
            Ok(predicate) => predicate,
            Err(e) => {
                constraint_gap(format!("cfg!: cannot parse cfg predicate: {e}"));
            }
        };
        let value = match configuration::resolve_predicate(&predicate, ctx.options) {
            CfgDisposition::Present => true,
            CfgDisposition::Absent(_) => false,
            CfgDisposition::Ambiguous(reason) => constraint_gap(format!(
                "cfg!: ambiguous cfg predicate `{predicate}`: {reason}"
            )),
        };
        Outcome::Complete(Desugared::Constraints {
            atom: eq(bool_const(value), bool_const(true)),
            n: 1,
            kind: AssertionFactKind::Warranted,
            warrant: Warrant { name: None },
        })
    }
}

enum BoolExprKind {
    Connective {
        left: SugarBody<ConstraintFloor>,
        right: SugarBody<ConstraintFloor>,
        is_and: bool,
    },
    Relation {
        lhs: SugarBody<TermFloor>,
        rhs: SugarBody<TermFloor>,
        lhs_expr: Expr,
        rhs_expr: Expr,
        op: RelationOp,
    },
    Not(SugarBody<ConstraintFloor>),
    Literal(bool),
    PredicateTerm {
        predicate: SugarBody<PredicateValueFloor>,
        expr: Expr,
    },
    Wrapper(SugarBody<ConstraintFloor>),
}

struct BoolExprSugar {
    kind: BoolExprKind,
}

struct PredicateValueSugar {
    term: SugarBody<TermFloor>,
    asserted: bool,
}

pub(crate) fn build_predicate_value_body(
    term: SugarBody<TermFloor>,
    asserted: bool,
) -> Box<dyn Sugar> {
    Box::new(PredicateValueSugar { term, asserted })
}

fn recognize_bool_expr(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    match expr {
        Expr::Binary(binary) if matches!(binary.op, BinOp::And(_) | BinOp::Or(_)) => {
            Some(Box::new(BoolExprSugar {
                kind: BoolExprKind::Connective {
                    left: SugarBody::constraint(&binary.left, fcx),
                    right: SugarBody::constraint(&binary.right, fcx),
                    is_and: matches!(binary.op, BinOp::And(_)),
                },
            }))
        }
        Expr::Binary(binary) => {
            let op = relation_from_binop(&binary.op)?;
            Some(Box::new(BoolExprSugar {
                kind: BoolExprKind::Relation {
                    lhs: SugarBody::term(&binary.left, fcx),
                    rhs: SugarBody::term(&binary.right, fcx),
                    lhs_expr: (*binary.left).clone(),
                    rhs_expr: (*binary.right).clone(),
                    op,
                },
            }))
        }
        Expr::Unary(unary) if matches!(unary.op, UnOp::Not(_)) => Some(Box::new(BoolExprSugar {
            kind: BoolExprKind::Not(SugarBody::constraint(&unary.expr, fcx)),
        })),
        Expr::Lit(ExprLit {
            lit: Lit::Bool(value),
            ..
        }) => Some(Box::new(BoolExprSugar {
            kind: BoolExprKind::Literal(value.value),
        })),
        expr if is_predicate_term_expr(expr) => Some(Box::new(BoolExprSugar {
            kind: BoolExprKind::PredicateTerm {
                predicate: SugarBody::predicate_value_term(SugarBody::term(expr, fcx)),
                expr: expr.clone(),
            },
        })),
        Expr::Paren(paren) => Some(Box::new(BoolExprSugar {
            kind: BoolExprKind::Wrapper(SugarBody::constraint(&paren.expr, fcx)),
        })),
        Expr::Group(group) => Some(Box::new(BoolExprSugar {
            kind: BoolExprKind::Wrapper(SugarBody::constraint(&group.expr, fcx)),
        })),
        _ => None,
    }
}

impl Sugar for BoolExprSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match &self.kind {
            BoolExprKind::Connective {
                left,
                right,
                is_and,
            } => {
                let left = match constraint_payload(left, ctx) {
                    Ok(payload) => payload,
                    Err(outcome) => return outcome,
                };
                match (*is_and, const_formula_bool(left.atom.as_ref())) {
                    (true, Some(false)) | (false, Some(true)) => {
                        debug!(
                            target: "sugar_lift_rust_tests::sugar::constraint",
                            connective = if *is_and { "&&" } else { "||" },
                            left_value = !*is_and,
                            "short-circuited boolean constraint on left literal-backed side"
                        );
                        return constraints_from_payload(left);
                    }
                    (true, Some(true)) | (false, Some(false)) => {
                        debug!(
                            target: "sugar_lift_rust_tests::sugar::constraint",
                            connective = if *is_and { "&&" } else { "||" },
                            left_value = *is_and,
                            "continued boolean constraint after non-deciding left literal-backed side"
                        );
                        let right = match constraint_payload(right, ctx) {
                            Ok(payload) => payload,
                            Err(outcome) => return outcome,
                        };
                        return constraints_from_payload(right);
                    }
                    _ => {}
                }
                let right = match constraint_payload(right, ctx) {
                    Ok(payload) => payload,
                    Err(outcome) => return outcome,
                };
                let atom = if *is_and {
                    and_(vec![left.atom, right.atom])
                } else {
                    sugar_ir_symbolic::or_(vec![left.atom, right.atom])
                };
                Outcome::Complete(Desugared::Constraints {
                    atom,
                    n: 1,
                    kind: if left.kind.is_warranted() || right.kind.is_warranted() {
                        AssertionFactKind::Warranted
                    } else {
                        AssertionFactKind::Support
                    },
                    warrant: Warrant {
                        name: common_constraint_name(&left.name, &right.name),
                    },
                })
            }
            BoolExprKind::Relation {
                lhs,
                rhs,
                lhs_expr,
                rhs_expr,
                op,
            } => relation_constraint_from_bodies("assert!", lhs, rhs, lhs_expr, rhs_expr, *op, ctx),
            BoolExprKind::Not(inner) => {
                let inner = match constraint_payload(inner, ctx) {
                    Ok(payload) => payload,
                    Err(outcome) => return outcome,
                };
                if let Some(atom) = bool_true_assertion_as_false(inner.atom.as_ref()) {
                    return Outcome::Complete(Desugared::Constraints {
                        atom,
                        n: 1,
                        kind: inner.kind,
                        warrant: Warrant { name: inner.name },
                    });
                }
                Outcome::Complete(Desugared::Constraints {
                    atom: not_(inner.atom),
                    n: 1,
                    kind: inner.kind,
                    warrant: Warrant { name: inner.name },
                })
            }
            BoolExprKind::Literal(value) => {
                let entry = assertion_entry_from_relation(
                    bool_const(*value),
                    bool_const(true),
                    RelationOp::Eq,
                    ctx.scope,
                );
                constraint_from_entry(entry)
            }
            BoolExprKind::PredicateTerm { predicate, expr } => {
                if let Some(effect) = crate::panic_freedom_expr_callsite_effect(expr, ctx.scope) {
                    return Outcome::Incomplete(effect);
                }
                let predicate = match predicate.reduce_predicate_value(ctx, "constraint predicate")
                {
                    FloorRead::Complete(predicate) => predicate,
                    FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
                };
                let asserted_term = asserted_predicate_term(predicate.formula().as_ref());
                let kind = if asserted_term
                    .map(|term| predicate_term_is_claim_bearing(term.as_ref(), expr))
                    .unwrap_or(true)
                {
                    AssertionFactKind::Warranted
                } else {
                    AssertionFactKind::Support
                };
                let name = asserted_term
                    .and_then(|term| callsite_assertion_name(term, ctx.scope.local_scope()));
                Outcome::Complete(Desugared::Constraints {
                    warrant: Warrant { name },
                    atom: predicate.into_formula(),
                    n: 1,
                    kind,
                })
            }
            BoolExprKind::Wrapper(inner) => inner.reduce(ctx),
        }
    }
}

impl Sugar for PredicateValueSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let term = match term_payload(&self.term, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let entry = assertion_entry_from_relation(
            term,
            bool_const(self.asserted),
            RelationOp::Eq,
            ctx.scope,
        );
        Outcome::Complete(Desugared::PredicateValue(PredicateValue::new(entry.atom)))
    }
}

fn predicate_term_is_claim_bearing(term: &Term, expr: &Expr) -> bool {
    if term_bool(term).is_some() {
        return true;
    }
    !predicate_term_is_unreduced_iterator_quantifier(expr)
}

fn asserted_predicate_term(formula: &Formula) -> Option<&Rc<Term>> {
    let Formula::Atomic { name, args } = formula else {
        return None;
    };
    if name != "=" || args.len() != 2 {
        return None;
    }
    if is_bool_const(args[1].as_ref(), true) {
        return Some(&args[0]);
    }
    if is_bool_const(args[0].as_ref(), true) {
        return Some(&args[1]);
    }
    None
}

fn predicate_term_is_unreduced_iterator_quantifier(expr: &Expr) -> bool {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return false;
    };
    matches!(call.method.to_string().as_str(), "all" | "any")
}

fn constraints_from_payload(payload: ConstraintPayload) -> Outcome {
    Outcome::Complete(Desugared::Constraints {
        atom: payload.atom,
        n: 1,
        kind: payload.kind,
        warrant: Warrant { name: payload.name },
    })
}

fn is_predicate_term_expr(expr: &Expr) -> bool {
    matches!(
        expr,
        Expr::Path(_) | Expr::Call(_) | Expr::MethodCall(_) | Expr::Await(_) | Expr::Field(_)
    )
}

fn bool_true_assertion_as_false(atom: &Formula) -> Option<Rc<Formula>> {
    let Formula::Atomic { name, args } = atom else {
        return None;
    };
    if name != "=" || args.len() != 2 {
        return None;
    }
    if is_bool_const(args[1].as_ref(), true) {
        return Some(eq(args[0].clone(), bool_const(false)));
    }
    if is_bool_const(args[0].as_ref(), true) {
        return Some(eq(bool_const(false), args[1].clone()));
    }
    None
}

fn is_bool_const(term: &Term, expected: bool) -> bool {
    matches!(
        term,
        Term::Const {
            value: ConstValue::Bool(value),
            ..
        } if *value == expected
    )
}

fn const_formula_bool(formula: &Formula) -> Option<bool> {
    match formula {
        Formula::Atomic { name, args } if args.len() == 2 => {
            const_atomic_bool(name, &args[0], &args[1])
        }
        Formula::Connective { kind, operands } if kind == "not" && operands.len() == 1 => {
            const_formula_bool(operands[0].as_ref()).map(|value| !value)
        }
        Formula::Connective { kind, operands } if kind == "and" => {
            let mut saw_any = false;
            for operand in operands {
                saw_any = true;
                match const_formula_bool(operand.as_ref()) {
                    Some(false) => return Some(false),
                    Some(true) => {}
                    None => return None,
                }
            }
            saw_any.then_some(true)
        }
        Formula::Connective { kind, operands } if kind == "or" => {
            let mut saw_any = false;
            for operand in operands {
                saw_any = true;
                match const_formula_bool(operand.as_ref()) {
                    Some(true) => return Some(true),
                    Some(false) => {}
                    None => return None,
                }
            }
            saw_any.then_some(false)
        }
        _ => None,
    }
}

fn const_atomic_bool(name: &str, lhs: &Rc<Term>, rhs: &Rc<Term>) -> Option<bool> {
    if let Some((left, right)) = const_u128_pair(lhs, rhs) {
        return compare_u128(name, left, right);
    }
    if let Some((left, right)) = const_int_pair(lhs, rhs) {
        return compare_i128(name, left, right);
    }
    if let Some((left, right)) = const_bool_pair(lhs, rhs) {
        return match name {
            "=" => Some(left == right),
            "\u{2260}" => Some(left != right),
            _ => None,
        };
    }
    None
}

fn const_u128_pair(lhs: &Rc<Term>, rhs: &Rc<Term>) -> Option<(u128, u128)> {
    let left_u = const_fold_u128_term(lhs);
    let right_u = const_fold_u128_term(rhs);
    if left_u.is_none() && right_u.is_none() {
        return None;
    }
    Some((
        left_u.or_else(|| const_fold_int_term(lhs).and_then(|n| u128::try_from(n).ok()))?,
        right_u.or_else(|| const_fold_int_term(rhs).and_then(|n| u128::try_from(n).ok()))?,
    ))
}

fn const_int_pair(lhs: &Rc<Term>, rhs: &Rc<Term>) -> Option<(i128, i128)> {
    Some((const_fold_int_term(lhs)?, const_fold_int_term(rhs)?))
}

fn const_bool_pair(lhs: &Rc<Term>, rhs: &Rc<Term>) -> Option<(bool, bool)> {
    Some((term_bool(lhs.as_ref())?, term_bool(rhs.as_ref())?))
}

fn term_bool(term: &Term) -> Option<bool> {
    match term {
        Term::Const {
            value: ConstValue::Bool(value),
            ..
        } => Some(*value),
        _ => None,
    }
}

fn compare_u128(name: &str, left: u128, right: u128) -> Option<bool> {
    match name {
        "=" => Some(left == right),
        "\u{2260}" => Some(left != right),
        "<" => Some(left < right),
        "\u{2264}" => Some(left <= right),
        ">" => Some(left > right),
        "\u{2265}" => Some(left >= right),
        _ => None,
    }
}

fn compare_i128(name: &str, left: i128, right: i128) -> Option<bool> {
    match name {
        "=" => Some(left == right),
        "\u{2260}" => Some(left != right),
        "<" => Some(left < right),
        "\u{2264}" => Some(left <= right),
        ">" => Some(left > right),
        "\u{2265}" => Some(left >= right),
        _ => None,
    }
}

struct IfPanicSugar {
    cond: SugarBody<ConstraintFloor>,
    negate: bool,
}

fn recognize_if_panic(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::If(if_expr) = expr else {
        return None;
    };
    if matches!(&*if_expr.cond, Expr::Let(_)) {
        return None;
    }
    let then_diverges = block_diverges(if_expr);
    let else_diverges = else_branch_diverges(if_expr);
    match (then_diverges, else_diverges) {
        (true, false) => Some(Box::new(IfPanicSugar {
            cond: SugarBody::constraint(&if_expr.cond, fcx),
            negate: true,
        })),
        (false, true) => Some(Box::new(IfPanicSugar {
            cond: SugarBody::constraint(&if_expr.cond, fcx),
            negate: false,
        })),
        _ => None,
    }
}

impl Sugar for IfPanicSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let payload = match constraint_payload(&self.cond, ctx) {
            Ok(payload) => payload,
            Err(outcome) => return outcome,
        };
        let atom = if self.negate {
            not_(payload.atom)
        } else {
            payload.atom
        };
        Outcome::Complete(Desugared::Constraints {
            atom,
            n: 1,
            kind: payload.kind,
            warrant: Warrant { name: payload.name },
        })
    }
}

struct PatternGuardSugar {
    boundary: String,
}

fn recognize_pattern_guard(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    if !matches!(expr, Expr::Let(_)) {
        return None;
    }
    Some(Box::new(PatternGuardSugar {
        boundary: token_key(expr),
    }))
}

impl Sugar for PatternGuardSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::IfGuardRuntime {
            boundary: self.boundary.clone(),
        })
    }
}

enum NoPanicKind {
    ReturnsNormally,
    UnconditionalPanic,
}

struct NoPanicCallSugar {
    site: String,
    kind: NoPanicKind,
    term_expr: Option<Expr>,
    ambient_effect: Option<Effect>,
}

fn recognize_no_panic_call(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    if !fcx.options().panic_freedom_enabled() {
        return None;
    }
    let kind = match expr {
        Expr::Call(_) | Expr::MethodCall(_) => NoPanicKind::ReturnsNormally,
        Expr::Macro(m) if panic_macro(&m.mac) => NoPanicKind::UnconditionalPanic,
        _ => return None,
    };
    let term_expr = match expr {
        Expr::Call(_) | Expr::MethodCall(_) => Some(expr.clone()),
        _ => None,
    };
    Some(Box::new(NoPanicCallSugar {
        site: token_key(expr),
        kind,
        term_expr,
        ambient_effect: fcx.panic_freedom_effect().cloned(),
    }))
}

impl Sugar for NoPanicCallSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let (normal_universe, name) = match &self.term_expr {
            Some(expr) => {
                if let Some(effect) = &self.ambient_effect {
                    return Outcome::Incomplete(effect.clone());
                }
                if is_no_panic_literal_empty_into_iter(expr)
                    || is_no_panic_empty_literal_sequence_callsite(expr, ctx)
                {
                    return no_panic_path_for_empty_literal_site(ctx, expr, &self.site);
                }
                let Some(subject) = ctx.opaque_callsite_term(expr) else {
                    constraint_gap(format!(
                        "no-panic callsite `{}` had no opaque subject term",
                        self.site
                    ));
                };
                // Lane 5 concrete-fold: ASCII char-class predicates and
                // `eq_ignore_ascii_case` on literal receivers can NEVER panic.
                // Emit a concrete tautology so the no-panic support entry does
                // not introduce an opaque panic atom into the group `inv` that
                // would block z3 discharge.
                if is_lane5_no_panic_literal_call(expr) {
                    let name = callsite_assertion_name(subject.as_ref(), ctx.scope.local_scope());
                    return Outcome::Complete(Desugared::Constraints {
                        atom: eq(bool_const(true), bool_const(true)),
                        n: 0,
                        kind: AssertionFactKind::Warranted,
                        warrant: Warrant { name },
                    });
                }
                let normal_universe = ctx
                    .normal_return_universe_for_subject(expr, subject.clone())
                    .unwrap_or_else(|| not_(atomic_("panic", vec![subject.clone()])));
                let name = callsite_assertion_name(subject.as_ref(), ctx.scope.local_scope());
                (normal_universe, name)
            }
            None => {
                let subject = str_const(format!("{}::{}", ctx.scope.local_scope(), self.site));
                (not_(atomic_("panic", vec![subject])), None)
            }
        };
        let (atom, kind) = match self.kind {
            NoPanicKind::ReturnsNormally => (normal_universe, AssertionFactKind::Warranted),
            NoPanicKind::UnconditionalPanic => (
                and_(vec![normal_universe.clone(), not_(normal_universe)]),
                AssertionFactKind::Warranted,
            ),
        };
        let name = name.or_else(|| {
            Some(format!(
                "{}::panic-path::{}",
                ctx.scope.local_scope(),
                compact_warrant_fragment(&self.site)
            ))
        });
        Outcome::Complete(Desugared::Constraints {
            atom,
            n: 0,
            kind,
            warrant: Warrant { name },
        })
    }
}

fn no_panic_path_for_empty_literal_site(ctx: &SugarCtx, expr: &Expr, site: &str) -> Outcome {
    let subject = ctx
        .opaque_callsite_term(expr)
        .unwrap_or_else(|| str_const(format!("{}::{}", ctx.scope.local_scope(), site)));
    let name = callsite_assertion_name(subject.as_ref(), ctx.scope.local_scope()).or_else(|| {
        Some(format!(
            "{}::panic-path::{}",
            ctx.scope.local_scope(),
            compact_warrant_fragment(site)
        ))
    });
    Outcome::Complete(Desugared::Constraints {
        atom: not_(atomic_("panic", vec![subject])),
        n: 0,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name },
    })
}

fn call_path_name(call: &syn::ExprCall) -> Option<String> {
    let Expr::Path(path) = call.func.as_ref() else {
        return None;
    };
    Some(
        path.path
            .segments
            .iter()
            .map(|segment| segment.ident.to_string())
            .collect::<Vec<_>>()
            .join("::"),
    )
}

fn is_no_panic_literal_empty_into_iter(expr: &Expr) -> bool {
    match strip_groups_parens(expr) {
        Expr::Call(call) => {
            let Some(path) = call_path_name(call) else {
                return false;
            };
            path.ends_with("IntoIterator::into_iter")
                && call.args.len() == 1
                && call
                    .args
                    .first()
                    .is_some_and(expr_is_empty_literal_array_expr)
        }
        Expr::MethodCall(call) => {
            call.method == "into_iter" && expr_is_empty_literal_array_expr(&call.receiver)
        }
        _ => false,
    }
}

fn is_no_panic_empty_literal_sequence_callsite(expr: &Expr, ctx: &SugarCtx) -> bool {
    let Expr::MethodCall(call) = strip_groups_parens(expr) else {
        return false;
    };
    let method = call.method.to_string();
    if !matches!(
        method.as_str(),
        "iter"
            | "into_iter"
            | "cloned"
            | "copied"
            | "fuse"
            | "rev"
            | "enumerate"
            | "skip"
            | "take"
            | "step_by"
    ) {
        return false;
    }
    let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
    method_family::literal_sequence_static_len_in_scope(expr, &let_inits, ctx.scope) == Some(0)
}

fn expr_is_empty_literal_array_expr(expr: &Expr) -> bool {
    match strip_groups_parens(expr) {
        Expr::Array(array) => array.elems.is_empty(),
        Expr::Cast(cast) => expr_is_empty_literal_array_expr(&cast.expr),
        Expr::Reference(reference) if reference.mutability.is_none() => {
            expr_is_empty_literal_array_expr(&reference.expr)
        }
        _ => false,
    }
}

fn strip_groups_parens(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(paren) => strip_groups_parens(&paren.expr),
        Expr::Group(group) => strip_groups_parens(&group.expr),
        _ => expr,
    }
}

fn compact_warrant_fragment(site: &str) -> String {
    site.chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '_' | ':' | '.') {
                ch
            } else {
                '_'
            }
        })
        .collect()
}

fn block_diverges(if_expr: &ExprIf) -> bool {
    if_expr
        .then_branch
        .stmts
        .last()
        .is_some_and(stmt_panics_or_aborts)
}

fn else_branch_diverges(if_expr: &ExprIf) -> bool {
    if_expr
        .else_branch
        .as_ref()
        .is_some_and(|(_, expr)| expr_panics_or_aborts(expr))
}

fn stmt_panics_or_aborts(stmt: &syn::Stmt) -> bool {
    match stmt {
        syn::Stmt::Expr(expr, _) => expr_panics_or_aborts(expr),
        syn::Stmt::Macro(m) => panic_macro(&m.mac),
        _ => false,
    }
}

fn expr_panics_or_aborts(expr: &Expr) -> bool {
    match expr {
        Expr::Macro(m) => panic_macro(&m.mac),
        Expr::Block(block) => block.block.stmts.last().is_some_and(stmt_panics_or_aborts),
        Expr::Unsafe(unsafe_expr) => unsafe_expr
            .block
            .stmts
            .last()
            .is_some_and(stmt_panics_or_aborts),
        Expr::Paren(paren) => expr_panics_or_aborts(&paren.expr),
        Expr::Group(group) => expr_panics_or_aborts(&group.expr),
        Expr::Call(call) => {
            let Expr::Path(path) = &*call.func else {
                return false;
            };
            let last = path
                .path
                .segments
                .last()
                .map(|segment| segment.ident.to_string());
            matches!(last.as_deref(), Some("exit") | Some("abort"))
                && path
                    .path
                    .segments
                    .iter()
                    .any(|segment| segment.ident == "process")
        }
        _ => false,
    }
}

fn panic_macro(mac: &syn::Macro) -> bool {
    mac.path.segments.last().is_some_and(|segment| {
        matches!(
            segment.ident.to_string().as_str(),
            "panic" | "unreachable" | "todo" | "unimplemented"
        )
    })
}

fn inactive_debug_assertion(name: &str, debug_gated: bool, ctx: &SugarCtx) -> Option<Outcome> {
    if !debug_gated {
        return None;
    }
    match configuration::resolve_predicate(
        &CfgPredicate::Name("debug_assertions".to_string()),
        ctx.options,
    ) {
        CfgDisposition::Present => None,
        CfgDisposition::Absent(reason) => Some(inert_support_constraint(
            ctx,
            format!("{name}!: cfg(debug_assertions) not active; skipped: {reason}"),
        )),
        CfgDisposition::Ambiguous(reason) => {
            let reason = format!("ambiguous cfg: {name}!: cfg(debug_assertions) skipped: {reason}");
            Some(Outcome::Incomplete(Effect::Configuration { reason }))
        }
    }
}

fn inert_support_constraint(ctx: &SugarCtx, reason: String) -> Outcome {
    Outcome::Complete(Desugared::Constraints {
        atom: eq(bool_const(true), bool_const(true)),
        n: 0,
        kind: AssertionFactKind::Support,
        warrant: Warrant {
            name: Some(format!(
                "{}::inactive::{}",
                ctx.scope.local_scope(),
                compact_warrant_fragment(&reason)
            )),
        },
    })
}

fn constraint_from_entry(entry: crate::AssertionEntry) -> Outcome {
    Outcome::Complete(Desugared::Constraints {
        atom: entry.atom,
        n: 1,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name: entry.name },
    })
}

struct ConstraintPayload {
    atom: Rc<Formula>,
    kind: AssertionFactKind,
    name: Option<String>,
}

fn constraint_payload(
    body: &SugarBody<ConstraintFloor>,
    ctx: &SugarCtx,
) -> Result<ConstraintPayload, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(Desugared::Constraints {
            atom,
            kind,
            warrant,
            ..
        }) => Ok(ConstraintPayload {
            atom,
            kind,
            name: warrant.name,
        }),
        Outcome::Complete(_) => {
            constraint_gap("constraint body reduced to a non-constraint floor");
        }
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn relation_constraint_from_bodies(
    name: &str,
    lhs: &SugarBody<TermFloor>,
    rhs: &SugarBody<TermFloor>,
    lhs_expr: &Expr,
    rhs_expr: &Expr,
    op: RelationOp,
    ctx: &SugarCtx,
) -> Outcome {
    if let Some(effect) = float_floor::nan_comparison_effect(name, lhs_expr, rhs_expr, ctx) {
        return Outcome::Incomplete(effect);
    }
    if let Some(effect) =
        constraint_runtime_boundary::type_inferred_parse_result_effect(name, lhs_expr, rhs_expr)
    {
        return Outcome::Incomplete(effect);
    }
    if let Some(effect) = relation_source_capability_effect(lhs_expr) {
        return Outcome::Incomplete(effect);
    }
    if let Some(effect) = relation_source_capability_effect(rhs_expr) {
        return Outcome::Incomplete(effect);
    }
    let lhs_panic_effect = crate::panic_freedom_expr_callsite_effect(lhs_expr, ctx.scope);
    if let Some(effect) = lhs_panic_effect.as_ref() {
        if !relation_side_may_ground_scan_terminal(lhs_expr) {
            return Outcome::Incomplete(effect.clone());
        }
    }
    let rhs_panic_effect = crate::panic_freedom_expr_callsite_effect(rhs_expr, ctx.scope);
    if let Some(effect) = rhs_panic_effect.as_ref() {
        if !relation_side_may_ground_scan_terminal(rhs_expr) {
            return Outcome::Incomplete(effect.clone());
        }
    }
    let lhs = match term_payload(lhs, ctx) {
        Ok(term) => term,
        Err(outcome) => return outcome,
    };
    let rhs = match term_payload(rhs, ctx) {
        Ok(term) => term,
        Err(outcome) => return outcome,
    };
    if let Some(effect) = lhs_panic_effect {
        if !relation_side_grounded_scan_terminal(lhs_expr, lhs.as_ref(), &effect) {
            return Outcome::Incomplete(effect);
        }
    }
    if let Some(effect) = rhs_panic_effect {
        if !relation_side_grounded_scan_terminal(rhs_expr, rhs.as_ref(), &effect) {
            return Outcome::Incomplete(effect);
        }
    }
    if let Some(effect) = relation_operand_capability_effect(lhs_expr, &lhs) {
        return Outcome::Incomplete(effect);
    }
    if let Some(effect) = relation_operand_capability_effect(rhs_expr, &rhs) {
        return Outcome::Incomplete(effect);
    }
    let kind = if relation_side_is_unreduced_iterator_quantifier(lhs.as_ref(), lhs_expr)
        || relation_side_is_unreduced_iterator_quantifier(rhs.as_ref(), rhs_expr)
    {
        AssertionFactKind::Support
    } else {
        AssertionFactKind::Warranted
    };
    let entry = assertion_entry_from_relation(lhs, rhs, op, ctx.scope);
    Outcome::Complete(Desugared::Constraints {
        atom: entry.atom,
        n: 1,
        kind,
        warrant: Warrant { name: entry.name },
    })
}

fn relation_side_may_ground_scan_terminal(expr: &Expr) -> bool {
    // Routed through the iter_terminal catalog boundary: that module owns the
    // scan-terminal method set (`sum`/`last` grounding a `scan` receiver), so
    // this call site asks it rather than re-encoding the method names here.
    crate::sugar::iter_terminal::is_scan_terminal_grounding_call(expr)
}

fn relation_side_grounded_scan_terminal(expr: &Expr, term: &Term, effect: &Effect) -> bool {
    matches!(effect, Effect::Mutation { .. })
        && relation_side_may_ground_scan_terminal(expr)
        && relation_term_is_closed_ground(term)
}

fn relation_term_is_closed_ground(term: &Term) -> bool {
    match term {
        Term::Const { .. } => true,
        Term::Ctor { name, args } => {
            !name.starts_with("call:")
                && !name.starts_with("method:")
                && args
                    .iter()
                    .all(|arg| relation_term_is_closed_ground(arg.as_ref()))
        }
        Term::Var { .. } | Term::Lambda { .. } | Term::Let { .. } => false,
    }
}

fn relation_side_is_unreduced_iterator_quantifier(term: &Term, expr: &Expr) -> bool {
    term_bool(term).is_none() && predicate_term_is_unreduced_iterator_quantifier(expr)
}

pub(crate) fn relation_source_capability_effect(expr: &Expr) -> Option<Effect> {
    relation_source_capability_kind(expr).map(|kind| Effect::RepresentationCast {
        boundary: token_key(expr),
        kind: kind.to_string(),
    })
}

fn relation_source_capability_kind(expr: &Expr) -> Option<&'static str> {
    match expr {
        Expr::Reference(reference)
            if reference.mutability.is_some() && !is_immutable_value_expr(&reference.expr) =>
        {
            Some("a `&mut` borrow")
        }
        Expr::Reference(reference) => relation_source_capability_kind(&reference.expr),
        Expr::RawAddr(_) => Some("a raw pointer (`&raw const`/`&raw mut`)"),
        Expr::Unsafe(unsafe_expr) => {
            expression_only_tail(&unsafe_expr.block).and_then(relation_source_capability_kind)
        }
        Expr::Block(block) => {
            expression_only_tail(&block.block).and_then(relation_source_capability_kind)
        }
        Expr::Paren(paren) => relation_source_capability_kind(&paren.expr),
        Expr::Group(group) => relation_source_capability_kind(&group.expr),
        _ => None,
    }
}

fn expression_only_tail(block: &syn::Block) -> Option<&Expr> {
    match block.stmts.as_slice() {
        [syn::Stmt::Expr(expr, None)] => Some(expr),
        _ => None,
    }
}

pub(crate) fn relation_operand_capability_effect(expr: &Expr, term: &Rc<Term>) -> Option<Effect> {
    relation_operand_capability_kind(term).map(|kind| Effect::RepresentationCast {
        boundary: token_key(expr),
        kind: kind.to_string(),
    })
}

fn relation_operand_capability_kind(term: &Rc<Term>) -> Option<&'static str> {
    let Term::Ctor { name, args } = term.as_ref() else {
        return None;
    };
    match name.as_str() {
        "ref_mut" if args.len() == 1 && is_literal_identity_term(&args[0]) => None,
        "ref_mut" => Some("a `&mut` borrow"),
        "raw_addr_const" | "raw_addr_mut" => Some("a raw pointer (`&raw const`/`&raw mut`)"),
        // Shared borrows are value-transparent for relations; keep looking through them so
        // `&&mut x` cannot smuggle mutable-reference identity into a relational warrant.
        "ref" if args.len() == 1 => relation_operand_capability_kind(&args[0]),
        _ => args.iter().find_map(relation_operand_capability_kind),
    }
}

fn term_payload(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(desugared) => Ok(desugared
            .into_term()
            .unwrap_or_else(|| constraint_gap("term body reduced to a non-term floor"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn common_constraint_name(left: &Option<String>, right: &Option<String>) -> Option<String> {
    match (left, right) {
        (Some(left), Some(right)) if left == right => Some(left.clone()),
        _ => None,
    }
}

fn relation_from_binop(op: &BinOp) -> Option<RelationOp> {
    match op {
        BinOp::Eq(_) => Some(RelationOp::Eq),
        BinOp::Ne(_) => Some(RelationOp::Ne),
        BinOp::Lt(_) => Some(RelationOp::Lt),
        BinOp::Le(_) => Some(RelationOp::Le),
        BinOp::Gt(_) => Some(RelationOp::Gt),
        BinOp::Ge(_) => Some(RelationOp::Ge),
        _ => None,
    }
}

/// Returns `true` when `expr` is a method call that can NEVER panic and whose
/// result is fully determined by the literal receiver / arguments.  These are
/// the Lane 5 ASCII char-class predicates and `eq_ignore_ascii_case`.
///
/// For such calls the "no-panic support" entry emitted by [`NoPanicCallSugar`]
/// should be a concrete tautology (`eq(true, true)`) rather than the opaque
/// `not(panic(method:…(…)))` atom.  An opaque atom in the group `inv` makes
/// both the positive and negative z3 queries SAT, keeping the discharge status
/// at `Undecided` even after the primary `StringPredicateSugar` has lowered the
/// predicate to `eq(bool(result), bool(true))`.
fn is_lane5_no_panic_literal_call(expr: &Expr) -> bool {
    let Expr::MethodCall(call) = expr else {
        return false;
    };
    let method = call.method.to_string();
    match method.as_str() {
        // Zero-arg ASCII char-class predicates — receiver must be a char or byte literal.
        "is_ascii_alphabetic"
        | "is_ascii_alphanumeric"
        | "is_ascii_control"
        | "is_ascii_digit"
        | "is_ascii_graphic"
        | "is_ascii_hexdigit"
        | "is_ascii_lowercase"
        | "is_ascii_octdigit"
        | "is_ascii_punctuation"
        | "is_ascii_uppercase"
        | "is_ascii_whitespace" => call.args.is_empty() && is_char_or_byte_lit(&call.receiver),
        // Case-insensitive string comparison — one arg, both sides must be string/char literals.
        "eq_ignore_ascii_case" => {
            call.args.len() == 1
                && is_str_or_char_lit(&call.receiver)
                && is_str_or_char_lit(&call.args[0])
        }
        _ => false,
    }
}

/// `true` iff `expr` is a char literal or byte literal (recursing through
/// parentheses and groups).
fn is_char_or_byte_lit(expr: &Expr) -> bool {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Char(_), ..
        }) => true,
        Expr::Lit(ExprLit {
            lit: Lit::Byte(_), ..
        }) => true,
        Expr::Paren(p) => is_char_or_byte_lit(&p.expr),
        Expr::Group(g) => is_char_or_byte_lit(&g.expr),
        _ => false,
    }
}

/// `true` iff `expr` is a string literal or char literal (recursing through
/// parentheses and groups).
fn is_str_or_char_lit(expr: &Expr) -> bool {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Str(_) | Lit::Char(_),
            ..
        }) => true,
        Expr::Paren(p) => is_str_or_char_lit(&p.expr),
        Expr::Group(g) => is_str_or_char_lit(&g.expr),
        _ => false,
    }
}

fn constraint_gap(reason: impl Into<String>) -> ! {
    panic!(
        "constraint did not reach a lawful proof-universe floor: {}",
        reason.into()
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{FloatWidthScope, TemporalPlan, TemporalScope};

    #[test]
    fn raw_if_let_guard_constraint_is_typed_effect_not_factory_gap() {
        let expr: Expr = syn::parse_str("let Err(error) = write_output(path, bytes)")
            .expect("parse raw if-let guard");
        let frag = SourceFragment::expr(&expr, "<src>");
        let scope = TemporalScope::new("constraint-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let sugar = recognize_pattern_guard(&frag, &fcx)
            .expect("raw if-let guard must have a constraint-role typed owner");
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx =
            sugar_ctx_with_factory_audits(&scope, &options, &reducer, &mut float_widths, 0, None);

        let outcome =
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| sugar.desugar(&ctx)))
                .expect("raw if-let guard must be a typed effect, not a constraint factory gap");

        let Outcome::Incomplete(effect) = outcome else {
            panic!("raw if-let guard must not fabricate a scalar constraint");
        };
        assert!(
            effect.reason().contains("if-guard over a runtime value"),
            "effect should name the raw runtime guard boundary: {}",
            effect.reason()
        );
    }

    #[test]
    fn relation_capability_operand_check_only_classifies_the_compared_value() {
        let expr: Expr = syn::parse_str("value").expect("parse relation operand provenance");
        let literal = num(1);
        let direct_literal_mut_ref = Rc::new(Term::Ctor {
            name: "ref_mut".to_string(),
            args: vec![Rc::clone(&literal)],
        });
        assert!(
            relation_operand_capability_effect(&expr, &direct_literal_mut_ref).is_none(),
            "a mutable reference to a literal identity is a closed source value"
        );
        let shared_wrapped_literal_mut_ref = Rc::new(Term::Ctor {
            name: "ref".to_string(),
            args: vec![Rc::clone(&direct_literal_mut_ref)],
        });
        assert!(
            relation_operand_capability_effect(&expr, &shared_wrapped_literal_mut_ref).is_none(),
            "a shared wrapper around a literal mutable reference remains a closed source value"
        );

        let runtime_value = Rc::new(Term::Var {
            name: "runtime_value".to_string(),
        });
        let direct_mut_ref = Rc::new(Term::Ctor {
            name: "ref_mut".to_string(),
            args: vec![Rc::clone(&runtime_value)],
        });
        assert!(
            relation_operand_capability_effect(&expr, &direct_mut_ref).is_some(),
            "a compared mutable-reference value is not timeless"
        );
        let shared_wrapped_mut_ref = Rc::new(Term::Ctor {
            name: "ref".to_string(),
            args: vec![Rc::clone(&direct_mut_ref)],
        });
        assert!(
            relation_operand_capability_effect(&expr, &shared_wrapped_mut_ref).is_some(),
            "a shared reference wrapper must not launder mutable-reference identity"
        );
        let value_from_mut_ref_argument = Rc::new(Term::Ctor {
            name: "method:get_unchecked_mut".to_string(),
            args: vec![direct_mut_ref],
        });
        assert!(
            relation_operand_capability_effect(&expr, &value_from_mut_ref_argument).is_some(),
            "composite relation values must not launder mutable-reference identity"
        );
    }

    #[test]
    fn bool_assertion_entry_delegates_binary_payload_to_constraint_floor() {
        let expr: Expr =
            syn::parse_str("x + 2 == y && !(z < 3)").expect("parse bool assertion payload");
        let scope = TemporalScope::new("bool-assertion-test", TemporalPlan::default());
        let float_widths = FloatWidthScope::new();

        let entry = assertion_entry_with_audits(&expr, &scope, &float_widths, None)
            .expect("constraint floor should lift bool payload");

        assert_eq!(entry.kind, AssertionFactKind::Warranted);
        assert_eq!(entry.claim_count, 1);
        let Formula::Connective { kind, operands } = entry.atom.as_ref() else {
            panic!(
                "expected && payload to reduce to conjunction, got {:?}",
                entry.atom
            );
        };
        assert_eq!(kind, "and");
        assert_eq!(operands.len(), 2);

        assert_plus_relation(operands[0].as_ref());
        let Formula::Connective {
            kind: not_kind,
            operands: not_operands,
        } = operands[1].as_ref()
        else {
            panic!(
                "expected right side to reduce to not(<), got {:?}",
                operands[1]
            );
        };
        assert_eq!(not_kind, "not");
        assert_eq!(not_operands.len(), 1);
        assert_var_int_relation(not_operands[0].as_ref(), "<", "z", 3);
    }

    #[test]
    fn predicate_position_bool_uses_predicate_floor_while_data_bool_stays_term_floor() {
        let expr: Expr = syn::parse_str("true").expect("parse bool literal");
        let scope = TemporalScope::new("predicate-value-floor-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let reducer = ReductionCtx::from_items_with_imports(&[], scope.macro_registry());
        let mut float_widths = FloatWidthScope::new();
        let ctx =
            sugar_ctx_with_factory_audits(&scope, &options, &reducer, &mut float_widths, 0, None);

        let predicate =
            SugarBody::<PredicateValueFloor>::predicate_value_term(SugarBody::term(&expr, &fcx));
        let Outcome::Complete(Desugared::PredicateValue(predicate)) = predicate.reduce(&ctx) else {
            panic!("predicate-position bool did not reduce to PredicateValue");
        };
        assert!(matches!(
            predicate.formula().as_ref(),
            Formula::Atomic { name, args } if name == "=" && args.len() == 2
        ));

        let data_bool = SugarBody::<crate::sugar::factory::BoolFloor>::bool_expr(&expr, &fcx);
        let Outcome::Complete(Desugared::Term(term)) = data_bool.reduce(&ctx) else {
            panic!("data-position bool did not reduce to Term");
        };
        assert_eq!(term_bool(term.as_ref()), Some(true));
    }

    #[test]
    fn bool_assertion_entry_reduces_bound_matches_macro_subject() {
        let expr: Expr = syn::parse_str("matches!(p, Poll::Ready(_))")
            .expect("parse matches! assertion payload");
        let mut scope = TemporalScope::new("matches-assertion-test", TemporalPlan::default());
        let init: Expr = syn::parse_str("poll_it()").expect("parse runtime call initializer");
        scope.record_let_binding("p", init);
        let float_widths = FloatWidthScope::new();

        let entry = assertion_entry_with_audits(&expr, &scope, &float_widths, None)
            .expect("matches! payload should reduce through ConstraintFloor");

        let Formula::Atomic { name, args } = entry.atom.as_ref() else {
            panic!("expected matches! discriminant atom, got {:?}", entry.atom);
        };
        assert_eq!(name, "=");
        assert_eq!(args.len(), 2);
        let Term::Ctor {
            name: variant_name,
            args: variant_args,
        } = args[0].as_ref()
        else {
            panic!("expected variant_of lhs, got {:?}", args[0]);
        };
        assert_eq!(variant_name, "variant_of");
        assert_eq!(variant_args.len(), 1);
        assert_str_term(args[1].as_ref(), "variant::Poll::Ready");
    }

    #[test]
    fn assert_macro_surface_reduces_matches_payload_through_matches_sugar() {
        let expr: Expr = syn::parse_str("assert!(matches!(p, Poll::Ready(_)))")
            .expect("parse assert matches! surface");
        let mut scope =
            TemporalScope::new("matches-assertion-surface-test", TemporalPlan::default());
        let init: Expr = syn::parse_str("poll_it()").expect("parse runtime call initializer");
        scope.record_let_binding("p", init);
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let reducer = ReductionCtx::from_items_with_imports(&[], scope.macro_registry());
        let mut float_widths = FloatWidthScope::new();
        let ctx =
            sugar_ctx_with_factory_audits(&scope, &options, &reducer, &mut float_widths, 0, None);

        let outcome = crate::sugar::factory::build_assertion_surface(&expr, &fcx).desugar(&ctx);

        let Outcome::Complete(Desugared::Constraints { atom, kind, .. }) = outcome else {
            panic!("expected assert!(matches!(..)) surface constraint");
        };
        assert_eq!(kind, AssertionFactKind::Warranted);
        let Formula::Atomic { name, args } = atom.as_ref() else {
            panic!("expected matches! discriminant atom, got {atom:?}");
        };
        assert_eq!(name, "=");
        assert_eq!(args.len(), 2);
        let Term::Ctor {
            name: variant_name,
            args: variant_args,
        } = args[0].as_ref()
        else {
            panic!("expected variant_of lhs, got {:?}", args[0]);
        };
        assert_eq!(variant_name, "variant_of");
        assert_eq!(variant_args.len(), 1);
        assert_str_term(args[1].as_ref(), "variant::Poll::Ready");
    }

    #[test]
    fn relation_macro_surface_warrants_grounded_scan_terminal() {
        let expr: Expr = syn::parse_str(
            "assert_eq!([1i32, 2, 3].iter().copied().scan(0i32, |s, x| { *s += x; Some(*s) }).sum::<i32>(), 10i32)",
        )
        .expect("parse scan assertion surface");
        let scope = TemporalScope::new("scan-assertion-surface-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let reducer = ReductionCtx::from_items_with_imports(&[], scope.macro_registry());
        let mut float_widths = FloatWidthScope::new();
        let ctx =
            sugar_ctx_with_factory_audits(&scope, &options, &reducer, &mut float_widths, 0, None);

        let outcome = crate::sugar::factory::build_assertion_surface(&expr, &fcx).desugar(&ctx);

        let Outcome::Complete(Desugared::Constraints { atom, kind, .. }) = outcome else {
            panic!("expected scan terminal assertion surface to emit a constraint");
        };
        assert_eq!(kind, AssertionFactKind::Warranted);
        let Formula::Atomic { name, args } = atom.as_ref() else {
            panic!("expected scan terminal equality, got {atom:?}");
        };
        assert_eq!(name, "=");
        assert_eq!(args.len(), 2);
        for arg in args {
            assert!(
                matches!(
                    arg.as_ref(),
                    Term::Const {
                        value: ConstValue::Int(10),
                        ..
                    }
                ),
                "scan terminal assertion should ground both sides to 10, got {arg:?}"
            );
        }
    }

    #[test]
    fn assertion_surface_refuses_unsafe_mut_ref_operand() {
        let lhs: Expr =
            syn::parse_str("unsafe { &mut *cell.get() }").expect("parse unsafe mut-ref operand");
        assert!(
            relation_source_capability_effect(&lhs).is_some(),
            "unsafe mut-ref operand must be recognized as a relation capability"
        );
        let expr: Expr = syn::parse_str("assert_eq!(unsafe { &mut *cell.get() }, comp)")
            .expect("parse unsafe mut-ref relation surface");
        let Expr::Macro(expr_macro) = &expr else {
            panic!("expected macro expr");
        };
        let args = parse_macro_args(expr_macro.mac.tokens.clone()).expect("parse assert_eq args");
        assert!(
            relation_source_capability_effect(&args.exprs[0]).is_some(),
            "parsed lhs must be a mutable-reference capability: {}",
            token_key(&args.exprs[0])
        );
        let scope = TemporalScope::new("unsafe-mut-ref-surface-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let reducer = ReductionCtx::from_items_with_imports(&[], scope.macro_registry());
        let mut float_widths = FloatWidthScope::new();
        let ctx =
            sugar_ctx_with_factory_audits(&scope, &options, &reducer, &mut float_widths, 0, None);

        let outcome = crate::sugar::factory::build_assertion_surface(&expr, &fcx).desugar(&ctx);

        let Outcome::Incomplete(effect) = outcome else {
            panic!("unsafe `&mut *p` relation operand must refuse");
        };
        assert!(
            effect
                .reason()
                .contains("effectful / raw-pointer / mutable-reference term"),
            "expected mutable-reference terminal, got {}",
            effect.reason()
        );
    }

    #[test]
    fn bool_assertion_entry_reduces_negated_matches_macro_subject() {
        let expr: Expr = syn::parse_str("!matches!(p, Poll::Ready(_))")
            .expect("parse negated matches! assertion payload");
        let scope = TemporalScope::new("matches-negation-test", TemporalPlan::default());
        let float_widths = FloatWidthScope::new();

        let entry = assertion_entry_with_audits(&expr, &scope, &float_widths, None)
            .expect("negated matches! payload should reduce through ConstraintFloor");

        let Formula::Connective { kind, operands } = entry.atom.as_ref() else {
            panic!(
                "expected negated matches! to reduce to not(..), got {:?}",
                entry.atom
            );
        };
        assert_eq!(kind, "not");
        assert_eq!(operands.len(), 1);
    }

    fn assert_plus_relation(formula: &Formula) {
        let Formula::Atomic { name, args } = formula else {
            panic!("expected atomic relation, got {formula:?}");
        };
        assert_eq!(name, "=");
        assert_eq!(args.len(), 2);
        let Term::Ctor {
            name: plus_name,
            args: plus_args,
        } = args[0].as_ref()
        else {
            panic!(
                "expected x + 2 to reduce through BinOpSugar, got {:?}",
                args[0]
            );
        };
        assert_eq!(plus_name, "+");
        assert_eq!(plus_args.len(), 2);
        assert_var_term(plus_args[0].as_ref(), "x");
        assert_int_term(plus_args[1].as_ref(), 2);
        assert_var_term(args[1].as_ref(), "y");
    }

    fn assert_var_int_relation(formula: &Formula, expected_name: &str, lhs: &str, rhs: i128) {
        let Formula::Atomic { name, args } = formula else {
            panic!("expected atomic relation, got {formula:?}");
        };
        assert_eq!(name, expected_name);
        assert_eq!(args.len(), 2);
        assert_var_term(args[0].as_ref(), lhs);
        assert_int_term(args[1].as_ref(), rhs);
    }

    fn assert_var_term(term: &Term, expected: &str) {
        let Term::Var { name } = term else {
            panic!("expected var {expected}, got {term:?}");
        };
        assert_eq!(name, expected);
    }

    fn assert_int_term(term: &Term, expected: i128) {
        let Term::Const {
            value: ConstValue::Int(value),
            ..
        } = term
        else {
            panic!("expected int constant {expected}, got {term:?}");
        };
        assert_eq!(*value, expected);
    }

    fn assert_str_term(term: &Term, expected: &str) {
        let Term::Const {
            value: ConstValue::String(value),
            ..
        } = term
        else {
            panic!("expected string constant {expected}, got {term:?}");
        };
        assert_eq!(value, expected);
    }
}
