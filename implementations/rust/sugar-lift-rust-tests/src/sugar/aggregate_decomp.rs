// SPDX-License-Identifier: Apache-2.0
//
// `aggregate_decomp` -- assertion-surface decomposition for array/slice equality.
//
// This is the array/slice sibling of `tuple_decomp`: `assert_eq!(&[1, 2], &[1, 3])`
// is not a scalar assertion, but it is fully determined by source text. Lower it to
// scalar teeth: a length equality plus one equality per element. Child runtime/effect
// boundaries propagate; this sugar does not mint its own effects.

use std::collections::BTreeSet;
use std::rc::Rc;

use sugar_ir_symbolic::{and_, atomic_, num, str_const, Term};
use syn::{BinOp, Expr, ExprMacro};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::constraint::{
    relation_operand_capability_effect, relation_source_capability_effect,
};
use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    callsite_assertion_name, const_val_term, parse_macro_args, path_to_variant_string,
    repeat_count_in_scope, strip_refs_groups, AssertionFactKind, Desugared, Effect, Outcome,
    RelationOp, Sugar, SugarCtx, Warrant, SUGAR_SEQ_CAP,
};

pub(crate) const ASSERTION_SURFACE_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::fallback_with_ordering(
        "assertion_surface_aggregate_decomp",
        SugarRole::AssertionSurface,
        &[
            "assertion_surface_relation_macro",
            "assertion_surface_assert_macro",
        ],
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_collect_good() {
                    assert_eq!((0..5).collect::<Vec<_>>(), [0, 1, 2, 3, 4]);
                }
            "#,
            r#"
                #[test]
                fn t_collect_bad() {
                    assert_eq!((0..5).collect::<Vec<_>>(), [0, 1, 2, 3, 9]);
                }
            "#,
        ),
        recognize,
    );

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Macro(expr_macro) = expr else {
        return None;
    };
    let (lhs, rhs, op, bare_assert) = macro_eq_operands(expr_macro)?;
    let shape_matches = direct_vec_macro_operand(&lhs)
        || direct_vec_macro_operand(&rhs)
        || if bare_assert {
            explicit_aggregateish(&lhs) || explicit_aggregateish(&rhs)
        } else {
            aggregateish(&lhs) || aggregateish(&rhs)
        };
    if !shape_matches {
        return None;
    }
    Some(Box::new(AggregateDecompSugar {
        lhs: aggregate_body(&lhs, fcx, &mut BTreeSet::new()),
        rhs: aggregate_body(&rhs, fcx, &mut BTreeSet::new()),
        lhs_term: SugarBody::term(&lhs, fcx),
        rhs_term: SugarBody::term(&rhs, fcx),
        lhs_expr: lhs,
        rhs_expr: rhs,
        op,
    }))
}

fn macro_eq_operands(expr_macro: &ExprMacro) -> Option<(Expr, Expr, RelationOp, bool)> {
    let name = expr_macro.mac.path.segments.last()?.ident.to_string();
    let args = parse_macro_args(expr_macro.mac.tokens.clone()).ok()?;
    match name.as_str() {
        "assert_eq" => {
            if args.exprs.len() < 2 {
                return None;
            }
            Some((
                args.exprs[0].clone(),
                args.exprs[1].clone(),
                RelationOp::Eq,
                false,
            ))
        }
        "assert" => {
            let Expr::Binary(binary) = args.exprs.first()? else {
                return None;
            };
            if !matches!(binary.op, BinOp::Eq(_)) {
                return None;
            }
            Some((
                (*binary.left).clone(),
                (*binary.right).clone(),
                RelationOp::Eq,
                true,
            ))
        }
        _ => None,
    }
}

fn aggregateish(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Array(_) | Expr::Repeat(_) => true,
        Expr::Struct(_) | Expr::Path(_) => true,
        Expr::Index(index) => is_full_range(&index.index) || aggregateish(&index.expr),
        Expr::Cast(cast) => aggregateish(&cast.expr),
        Expr::Call(call) => call.args.iter().any(explicit_aggregateish),
        Expr::Paren(paren) => aggregateish(&paren.expr),
        Expr::Group(group) => aggregateish(&group.expr),
        Expr::Reference(reference) => aggregateish(&reference.expr),
        _ => false,
    }
}

fn explicit_aggregateish(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Array(_) | Expr::Repeat(_) | Expr::Struct(_) => true,
        Expr::Index(index) => is_full_range(&index.index) || explicit_aggregateish(&index.expr),
        Expr::Cast(cast) => explicit_aggregateish(&cast.expr),
        Expr::Call(call) => call.args.iter().any(explicit_aggregateish),
        Expr::Paren(paren) => explicit_aggregateish(&paren.expr),
        Expr::Group(group) => explicit_aggregateish(&group.expr),
        Expr::Reference(reference) => explicit_aggregateish(&reference.expr),
        Expr::Path(_) => false,
        _ => false,
    }
}

fn direct_vec_macro_operand(expr: &Expr) -> bool {
    matches!(strip_refs_groups(expr), Expr::Macro(expr_macro) if vec_macro_name(expr_macro))
}

enum AggregateBody {
    Array(Vec<AggregateBody>),
    Repeat {
        elem: Box<AggregateBody>,
        count: usize,
    },
    Struct {
        name: String,
        fields: Vec<(String, AggregateBody)>,
    },
    Ctor {
        name: &'static str,
        arg: Box<AggregateBody>,
    },
    CollectVec {
        receiver: SugarBody<CompositeFloor>,
    },
    Term {
        body: SugarBody<TermFloor>,
    },
}

struct AggregateDecompSugar {
    lhs: AggregateBody,
    rhs: AggregateBody,
    lhs_term: SugarBody<TermFloor>,
    rhs_term: SugarBody<TermFloor>,
    lhs_expr: Expr,
    rhs_expr: Expr,
    op: RelationOp,
}

impl Sugar for AggregateDecompSugar {
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(effect) = relation_source_capability_effect(&self.lhs_expr) {
            return Outcome::Incomplete(effect);
        }
        if let Some(effect) = relation_source_capability_effect(&self.rhs_expr) {
            return Outcome::Incomplete(effect);
        }
        if let Some(effect) = crate::panic_freedom_expr_callsite_effect(&self.lhs_expr, ctx.scope) {
            return Outcome::Incomplete(effect);
        }
        if let Some(effect) = crate::panic_freedom_expr_callsite_effect(&self.rhs_expr, ctx.scope) {
            return Outcome::Incomplete(effect);
        }
        let lhs = aggregate_components(&self.lhs, ctx);
        let rhs = aggregate_components(&self.rhs, ctx);
        match (lhs, rhs) {
            (Ok(Some(lhs)), Ok(Some(rhs))) => decompose_eq(lhs, rhs, ctx),
            (Err(outcome), _) | (_, Err(outcome)) => outcome,
            _ => fallback_relation(
                &self.lhs_term,
                &self.rhs_term,
                &self.lhs_expr,
                &self.rhs_expr,
                self.op,
                ctx,
            ),
        }
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

fn decompose_eq(lhs: Vec<Rc<Term>>, rhs: Vec<Rc<Term>>, ctx: &SugarCtx) -> Outcome {
    let mut atoms = Vec::with_capacity(lhs.len().min(rhs.len()) + 1);
    atoms.push(atomic_(
        "=".to_string(),
        vec![num(lhs.len() as i128), num(rhs.len() as i128)],
    ));
    let mut anchor = None;
    for (l, r) in lhs.into_iter().zip(rhs.into_iter()) {
        let l = strip_value_ref(l);
        let r = strip_value_ref(r);
        if anchor.is_none() {
            anchor = Some(Rc::clone(&l));
        }
        atoms.push(atomic_("=".to_string(), vec![l, r]));
    }
    let name =
        anchor.and_then(|term| callsite_assertion_name(term.as_ref(), ctx.scope.local_scope()));
    Outcome::Complete(Desugared::Constraints {
        atom: and_(atoms),
        n: 1,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name },
    })
}

fn aggregate_body(expr: &Expr, fcx: &SugarBuildCtx, seen: &mut BTreeSet<String>) -> AggregateBody {
    match strip_refs_groups(expr) {
        Expr::Array(array) => {
            let elems = array
                .elems
                .iter()
                .map(|elem| aggregate_body(elem, fcx, seen))
                .collect();
            AggregateBody::Array(elems)
        }
        Expr::Repeat(repeat) => match repeat_count_in_scope(&repeat.len, fcx.scope()) {
            Some(count) if count <= SUGAR_SEQ_CAP as usize => AggregateBody::Repeat {
                elem: Box::new(aggregate_body(&repeat.expr, fcx, seen)),
                count,
            },
            _ => AggregateBody::Term {
                body: SugarBody::term(expr, fcx),
            },
        },
        Expr::Struct(strukt) => {
            if strukt.rest.is_some() {
                return AggregateBody::Term {
                    body: SugarBody::term(expr, fcx),
                };
            }
            let mut fields: Vec<(String, AggregateBody)> = strukt
                .fields
                .iter()
                .map(|field| {
                    let name = match &field.member {
                        syn::Member::Named(ident) => ident.to_string(),
                        syn::Member::Unnamed(index) => index.index.to_string(),
                    };
                    (name, aggregate_body(&field.expr, fcx, seen))
                })
                .collect();
            fields.sort_by(|a, b| a.0.cmp(&b.0));
            AggregateBody::Struct {
                name: path_to_variant_string(&strukt.path),
                fields,
            }
        }
        Expr::Index(index) if is_full_range(&index.index) => aggregate_body(&index.expr, fcx, seen),
        Expr::Reference(reference) => aggregate_body(&reference.expr, fcx, seen),
        Expr::Cast(cast) => aggregate_body(&cast.expr, fcx, seen),
        Expr::MethodCall(call)
            if call.method == "collect"
                && call.args.is_empty()
                && crate::sugar::collect::collects_vec(call) =>
        {
            AggregateBody::CollectVec {
                receiver: SugarBody::composite(&call.receiver, fcx),
            }
        }
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(|ident| ident.to_string()) else {
                return AggregateBody::Term {
                    body: SugarBody::term(expr, fcx),
                };
            };
            if !seen.insert(name.clone()) {
                return AggregateBody::Term {
                    body: SugarBody::term(expr, fcx),
                };
            }
            let resolved = fcx
                .scope()
                .temporal_rewrite_expr_for(&name)
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name).cloned());
            let result = match resolved {
                Some(init) => aggregate_body(&init, &fcx.with_bound_path(&name), seen),
                None => AggregateBody::Term {
                    body: SugarBody::term(expr, fcx),
                },
            };
            seen.remove(&name);
            result
        }
        Expr::MethodCall(call)
            if matches!(call.method.to_string().as_str(), "unwrap" | "expect") =>
        {
            if call.method == "unwrap" && !call.args.is_empty() {
                return AggregateBody::Term {
                    body: SugarBody::term(expr, fcx),
                };
            }
            if call.method == "expect" && call.args.len() != 1 {
                return AggregateBody::Term {
                    body: SugarBody::term(expr, fcx),
                };
            }
            AggregateBody::Term {
                body: SugarBody::term(expr, fcx),
            }
        }
        Expr::Call(call) => match structural_ctor_term_name(&call.func) {
            Some(name) if call.args.len() == 1 => AggregateBody::Ctor {
                name,
                arg: Box::new(aggregate_body(&call.args[0], fcx, seen)),
            },
            _ => AggregateBody::Term {
                body: SugarBody::term(expr, fcx),
            },
        },
        Expr::Macro(expr_macro) if vec_macro_name(expr_macro) => {
            let Ok(args) = parse_macro_args(expr_macro.mac.tokens.clone()) else {
                return AggregateBody::Term {
                    body: SugarBody::term(expr, fcx),
                };
            };
            AggregateBody::Array(
                args.exprs
                    .iter()
                    .map(|expr| aggregate_body(expr, fcx, seen))
                    .collect(),
            )
        }
        Expr::Paren(paren) => aggregate_body(&paren.expr, fcx, seen),
        Expr::Group(group) => aggregate_body(&group.expr, fcx, seen),
        _ => AggregateBody::Term {
            body: SugarBody::term(expr, fcx),
        },
    }
}

fn aggregate_components(
    body: &AggregateBody,
    ctx: &SugarCtx,
) -> Result<Option<Vec<Rc<Term>>>, Outcome> {
    match body {
        AggregateBody::Array(elems) => {
            let mut out = Vec::new();
            for elem in elems {
                append_body_components(&mut out, elem, ctx)?;
            }
            Ok(Some(out))
        }
        AggregateBody::Repeat { elem, count } => {
            let mut elem_parts = Vec::new();
            append_body_components(&mut elem_parts, elem, ctx)?;
            let total = elem_parts
                .len()
                .checked_mul(*count)
                .unwrap_or_else(|| panic!("aggregate repeat component count overflow"));
            if total > SUGAR_SEQ_CAP as usize {
                panic!("aggregate repeat component count {total} exceeds cap {SUGAR_SEQ_CAP}");
            }
            let mut out = Vec::with_capacity(total);
            for _ in 0..*count {
                out.extend(elem_parts.iter().cloned());
            }
            Ok(Some(out))
        }
        AggregateBody::Struct { name, fields } => {
            let mut out = Vec::with_capacity(fields.len() * 2 + 1);
            out.push(str_const(format!("struct:{name}")));
            for (name, value) in fields {
                out.push(str_const(format!("field:{name}")));
                append_body_components(&mut out, value, ctx)?;
            }
            Ok(Some(out))
        }
        AggregateBody::Ctor { name, arg } => {
            let Some(parts) = aggregate_components(arg, ctx)? else {
                return Ok(None);
            };
            let mut out = vec![str_const(format!("ctor:{name}:1"))];
            out.extend(parts);
            Ok(Some(out))
        }
        AggregateBody::CollectVec { receiver } => collect_vec_components(receiver, ctx),
        AggregateBody::Term { body } => {
            let term = text_determined_term(body, ctx)?;
            grounded_term_components(term)
        }
    }
}

fn append_body_components(
    out: &mut Vec<Rc<Term>>,
    body: &AggregateBody,
    ctx: &SugarCtx,
) -> Result<(), Outcome> {
    match aggregate_components(body, ctx)? {
        Some(parts) => {
            out.extend(parts);
            Ok(())
        }
        None => {
            let term = term_payload(body, ctx)?;
            match grounded_term_components(term)? {
                Some(parts) => {
                    out.extend(parts);
                    Ok(())
                }
                None => Err(Outcome::Incomplete(Effect::LiteralDomain {
                    reason: "aggregate element: literal array element is not text-determined"
                        .to_string(),
                })),
            }
        }
    }
}

fn vec_macro_name(expr_macro: &ExprMacro) -> bool {
    let Some(name) = expr_macro
        .mac
        .path
        .segments
        .last()
        .map(|seg| seg.ident.to_string())
    else {
        return false;
    };
    name == "vec"
}

fn collect_vec_components(
    receiver: &SugarBody<CompositeFloor>,
    ctx: &SugarCtx,
) -> Result<Option<Vec<Rc<Term>>>, Outcome> {
    let seq = match receiver.reduce(ctx) {
        Outcome::Complete(desugared) => {
            let Some(seq) = desugared.into_seq() else {
                return Ok(None);
            };
            seq
        }
        Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
    };
    let mut out = Vec::with_capacity(seq.len());
    for elem in seq {
        let Some(term) = elem.value.as_ref().and_then(const_val_term) else {
            return Ok(None);
        };
        out.push(term);
    }
    Ok(Some(out))
}

fn text_determined_term(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    let term = match body.reduce(ctx) {
        Outcome::Complete(desugared) => desugared
            .into_term()
            .unwrap_or_else(|| panic!("aggregate term child reduced to non-term")),
        Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
    };
    Ok(term)
}

fn term_payload(body: &AggregateBody, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body {
        AggregateBody::Term { body } => text_determined_term(body, ctx),
        _ => aggregate_decomp_construction_gap("aggregate body had no scalar term payload"),
    }
}

fn grounded_term_components(term: Rc<Term>) -> Result<Option<Vec<Rc<Term>>>, Outcome> {
    let term = strip_value_ref(term);
    match term.as_ref() {
        Term::Ctor { name, .. } if name == "agg:Array" => Ok(None),
        Term::Var { name } if name.starts_with("agg:Array(") => Ok(None),
        Term::Const { .. } => Ok(Some(vec![Rc::clone(&term)])),
        Term::Var { name } if name.starts_with("literal:Array(") => {
            Ok(literal_array_var_int_components(name))
        }
        Term::Var { name } if name.starts_with("literal:") => Ok(Some(vec![Rc::clone(&term)])),
        Term::Var { .. } => Ok(None),
        Term::Ctor { name, args } if name == "literal:Array" => {
            let mut out = Vec::new();
            for arg in args {
                let Some(parts) = grounded_term_components(Rc::clone(arg))? else {
                    return Ok(None);
                };
                out.extend(parts);
            }
            Ok(Some(out))
        }
        Term::Ctor { name, args } if text_structural_ctor(name) => {
            let mut out = Vec::with_capacity(args.len() + 1);
            out.push(str_const(format!("ctor:{name}:{}", args.len())));
            for arg in args {
                let Some(parts) = grounded_term_components(Rc::clone(arg))? else {
                    return Ok(None);
                };
                out.extend(parts);
            }
            Ok(Some(out))
        }
        _ => Ok(None),
    }
}

fn literal_array_var_int_components(name: &str) -> Option<Vec<Rc<Term>>> {
    let inner = name.strip_prefix("literal:Array(")?.strip_suffix(')')?;
    if inner.is_empty() {
        return Some(Vec::new());
    }
    inner
        .split(',')
        .map(|part| part.strip_prefix("i:")?.parse::<i128>().ok().map(num))
        .collect()
}

fn text_structural_ctor(name: &str) -> bool {
    !name.starts_with("call:")
        && !name.starts_with("method:")
        && (name == "literal:Array"
            || name.starts_with("struct:")
            || name.starts_with("field:")
            || matches!(
                name,
                "opt:some" | "opt:none" | "res:ok" | "res:err" | "ref" | "ref_mut"
            ))
}

fn structural_ctor_term_name(func: &Expr) -> Option<&'static str> {
    let Expr::Path(path) = strip_refs_groups(func) else {
        return None;
    };
    path.path
        .segments
        .last()
        .and_then(|segment| match segment.ident.to_string().as_str() {
            "Some" => Some("opt:some"),
            "Ok" => Some("res:ok"),
            "Err" => Some("res:err"),
            "None" => Some("opt:none"),
            _ => None,
        })
}

fn fallback_relation(
    lhs: &SugarBody<TermFloor>,
    rhs: &SugarBody<TermFloor>,
    lhs_expr: &Expr,
    rhs_expr: &Expr,
    op: RelationOp,
    ctx: &SugarCtx,
) -> Outcome {
    let lhs = match term_or_construction_gap(lhs, "aggregate fallback lhs", ctx) {
        Ok(term) => term,
        Err(outcome) => return outcome,
    };
    let rhs = match term_or_construction_gap(rhs, "aggregate fallback rhs", ctx) {
        Ok(term) => term,
        Err(outcome) => return outcome,
    };
    if let Some(effect) = relation_operand_capability_effect(lhs_expr, &lhs) {
        return Outcome::Incomplete(effect);
    }
    if let Some(effect) = relation_operand_capability_effect(rhs_expr, &rhs) {
        return Outcome::Incomplete(effect);
    }
    let entry = crate::assertion_entry_from_relation(lhs, rhs, op, ctx.scope);
    Outcome::Complete(Desugared::Constraints {
        atom: entry.atom,
        n: 1,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name: entry.name },
    })
}

fn term_or_construction_gap(
    body: &SugarBody<TermFloor>,
    label: &'static str,
    ctx: &SugarCtx,
) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(desugared) => Ok(desugared
            .into_term()
            .unwrap_or_else(|| panic!("{label} reduced to non-term"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn is_full_range(expr: &Expr) -> bool {
    matches!(strip_refs_groups(expr), Expr::Range(range) if range.start.is_none() && range.end.is_none())
}

fn strip_value_ref(mut term: Rc<Term>) -> Rc<Term> {
    loop {
        match term.as_ref() {
            Term::Ctor { name, args }
                if matches!(name.as_str(), "ref" | "ref_mut") && args.len() == 1 =>
            {
                term = Rc::clone(&args[0]);
            }
            _ => return term,
        }
    }
}

fn aggregate_decomp_construction_gap(reason: &'static str) -> ! {
    panic!("aggregate_decomp recognized a shape it could not lawfully reduce: {reason}")
}
