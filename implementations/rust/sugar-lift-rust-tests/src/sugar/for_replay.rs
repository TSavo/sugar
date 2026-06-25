// SPDX-License-Identifier: Apache-2.0
//
// `ForReplaySugar`: finite literal-loop temporal replay. This is for loops whose
// body is not a symbolic forall because it contains source state transitions
// (tuple destructuring, enum match, simple local updates), but every iteration is
// pinned by a closed finite domain and every value helper is visible source.

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, ConstValue, Formula, Term};
use syn::{BinOp, Expr, Item, Lit, Pat, Stmt, Type, UnOp};
use tracing::debug;

use crate::sugar::callsite::{CallsiteOutcome, CallsiteSugar};
use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::configuration::{resolve as cfg_resolve, CfgDisposition};
use crate::sugar::extract_if::{ExtractIfSugar, ReplayAction};
use crate::sugar::factory::{
    build_composite, build_term, has_composite, CompositeFloor, SugarBody, SugarBuildCtx,
};
use crate::sugar::insert::InsertSugar;
use crate::{
    bool_const, bounded_domain_from_expr, const_fold_int_term, const_fold_u128_term,
    count_asserts_in_stmts, helper_param_names, macro_is_assertion_surface, path_to_variant_string,
    simple_call_name, simple_pat_name, strip_refs_groups, substitute_expr, substitute_macro_tokens,
    term_as_int, translate_term_in_scope, u128_expr, AssertionFactKind, BoundedDomain, ConstVal,
    Desugared, Effect, ExprBindings, FactoryAuditLog, FloatWidthScope, LiftOptions, Outcome,
    ReductionCtx, Sugar, SugarCtx, TemporalScope, Warrant, SUGAR_SEQ_CAP,
};

// Replay is the precise owner when a mutating loop is fully literal-determined;
// the mutation sugar remains the conservative boundary only after replay declines.
pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::composite_before(
    "for_replay",
    &["for_loop_mutation", "forall_loop"],
    recognize,
);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::ForLoop(for_loop) = expr else {
        return None;
    };
    let Some(vars) = loop_var_bindings(for_loop.pat.as_ref()) else {
        debug!(
            target: "sugar_lift_rust_tests::sugar::for_replay",
            domain = %crate::token_key(&for_loop.expr),
            "for_replay declined loop: pattern is not an ident or a tuple of idents"
        );
        return None;
    };
    let loop_vars = vars.join(", ");
    let assert_count = replay_assert_count(&for_loop.body.stmts, fcx.scope());
    let replay_only_assignments = assert_count == 0
        && vars.len() == 1
        && body_has_temporal_assignment_replay_shape(
            &for_loop.body.stmts,
            fcx.scope(),
            vars.first()?,
        );
    if assert_count == 0 && !replay_only_assignments {
        debug!(
            target: "sugar_lift_rust_tests::sugar::for_replay",
            loop_var = %loop_vars,
            domain = %crate::token_key(&for_loop.expr),
            "for_replay declined loop: no replayable assertions"
        );
        return None;
    }
    let adaptor_domain = sequence_adaptor_domain_shape(&for_loop.expr, fcx);
    let finite_replay_domain = domain_has_replay_shape(&for_loop.expr, adaptor_domain);
    if !finite_replay_domain {
        debug!(
            target: "sugar_lift_rust_tests::sugar::for_replay",
            loop_var = %loop_vars,
            domain = %crate::token_key(&for_loop.expr),
            assert_count,
            adaptor_domain,
            "for_replay declined loop: domain shape"
        );
        return None;
    }
    if range_domain_exceeds_replay_cap(&for_loop.expr, fcx.scope()) {
        debug!(
            target: "sugar_lift_rust_tests::sugar::for_replay",
            loop_var = %loop_vars,
            domain = %crate::token_key(&for_loop.expr),
            cap = SUGAR_SEQ_CAP,
            "for_replay declined loop: literal range exceeds replay cap"
        );
        return None;
    }
    let seed_names = accumulator_seed_names(&for_loop.body.stmts, fcx.scope());
    let tuple_loop = vars.len() > 1;
    let direct_pointwise_loop = tuple_loop
        || char_range_domain_shape(&for_loop.expr)
        || (range_domain_shape(&for_loop.expr)
            && body_has_relation_assertion_surface(&for_loop.body.stmts));
    if !body_has_replay_shape(
        &for_loop.body.stmts,
        fcx.scope(),
        finite_replay_domain,
        direct_pointwise_loop,
    ) && !replay_only_assignments
    {
        debug!(
            target: "sugar_lift_rust_tests::sugar::for_replay",
            loop_var = %loop_vars,
            domain = %crate::token_key(&for_loop.expr),
            assert_count,
            adaptor_domain,
            seed_count = seed_names.len(),
            "for_replay declined loop: body shape"
        );
        return None;
    }
    debug!(
        sugar = "for_replay",
        loop_var = %loop_vars,
        domain = %crate::token_key(&for_loop.expr),
        seed_count = seed_names.len(),
        "recognized finite literal loop replay"
    );
    Some(Box::new(ForReplaySugar {
        vars,
        domain: SugarBody::composite(&for_loop.expr, fcx),
        domain_expr: (*for_loop.expr).clone(),
        body_stmts: for_loop.body.stmts.clone(),
        seed_names,
    }))
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn desugar_synthesized_for_loop(
    expr: &Expr,
    scope: &TemporalScope,
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    float_widths: &mut FloatWidthScope,
    let_inits: &BTreeMap<String, &Expr>,
    macro_depth: usize,
    factory_audits: Option<&FactoryAuditLog>,
) -> Outcome {
    crate::sugar::statement_position::desugar_composite_expr(
        expr,
        scope,
        options,
        reducer,
        float_widths,
        let_inits,
        macro_depth,
        factory_audits,
    )
}

/// The binding ident for a `for <pat> in ..` loop var. Accepts `Pat::Ident` AND
/// reference patterns (`for &x` / `for &&x`) and parenthesized patterns, peeling to
/// the inner ident. `for &x` is idiomatic when the iterator yields `&T` (`[..].iter()`)
/// and was previously declined ("non-ident pattern"), refusing the whole loop. The
/// replay substitutes the loop var with the per-step element VALUE regardless of
/// pattern (the body's own `x` vs `*x` carries the deref), so peeling the `&` is sound
/// -- no new domain is admitted; the literal-domain gate downstream is unchanged.
fn loop_var_pat_ident(pat: &Pat) -> Option<&syn::PatIdent> {
    match pat {
        Pat::Ident(id) => Some(id),
        Pat::Reference(r) => loop_var_pat_ident(&r.pat),
        Pat::Paren(p) => loop_var_pat_ident(&p.pat),
        _ => None,
    }
}

/// The loop-var binding PLAN for a `for <pat> in ..` loop: the ordered ident names the
/// per-step element is bound to. A single ident (`for x` / `for &x`) yields `[name]`; a
/// tuple pattern (`for (i, &x)` over `.enumerate()`, etc.) yields one name per component,
/// peeling `&`/paren on each. Each component must be a plain ident with no subpattern --
/// any nested struct/tuple/wildcard declines (returns `None` -> the loop refuses). The
/// per-component element VALUE is bound at desugar by decomposing the tuple element; the
/// body's own `x` vs `*x` carries the deref, so peeling `&` is sound.
fn loop_var_bindings(pat: &Pat) -> Option<Vec<String>> {
    fn component_ident(pat: &Pat) -> Option<String> {
        let id = loop_var_pat_ident(pat)?;
        if id.subpat.is_some() {
            return None;
        }
        Some(id.ident.to_string())
    }
    match pat {
        // `for (i, &x)` tuple pattern (enumerate/zip pairs).
        Pat::Tuple(tuple) => {
            if tuple.elems.is_empty() {
                return None;
            }
            tuple.elems.iter().map(component_ident).collect()
        }
        // `for [a, b]` / `for [a, b, c]` slice/array pattern over a finite literal of
        // arrays (e.g. `[[1, 2], [3, 4]]`): each element pattern binds the corresponding
        // component of the per-step array. Require >= 2 elements -- a 1-element slice is
        // ambiguous against the single-ident bind-whole path, so refuse it
        // (finite-or-refuse on a rare edge).
        Pat::Slice(slice) => {
            if slice.elems.len() < 2 {
                return None;
            }
            slice.elems.iter().map(component_ident).collect()
        }
        Pat::Paren(p) => loop_var_bindings(&p.pat),
        // `for &(i, x)` / `for &[a, b]`: peel the reference and recurse to the inner
        // destructure (the body's own `*` carries the deref, so binding the component
        // value is sound regardless of the `&`).
        Pat::Reference(r) => loop_var_bindings(&r.pat),
        _ => component_ident(pat).map(|name| vec![name]),
    }
}

/// Bind one per-step element `value` to the loop-var plan. A single-ident plan binds the
/// whole value. A multi-binding plan -- a tuple pattern (`for (i, &x)`) or a slice/array
/// pattern (`for [a, b]`) -- requires `value` to be a tuple expr (the `(i, e)` pairs
/// `EnumerateSugar` yields) OR an array expr (an element of a literal-of-arrays domain) of
/// matching arity, and binds each component to its name. Returns `None` (bail -> refuse)
/// if a multi-binding plan meets a non-tuple/non-array or wrong-arity value: a guessed
/// decomposition is never bound.
fn bind_loop_value(bindings: &mut ExprBindings, vars: &[String], value: Expr) -> Option<()> {
    if vars.len() == 1 {
        bindings.insert(vars[0].clone(), value);
        return Some(());
    }
    let components: Vec<&Expr> = match strip_refs_groups(&value) {
        Expr::Tuple(tuple) => tuple.elems.iter().collect(),
        Expr::Array(array) => array.elems.iter().collect(),
        _ => return None,
    };
    if components.len() != vars.len() {
        return None;
    }
    for (name, component) in vars.iter().zip(components.iter()) {
        bindings.insert(name.clone(), (*component).clone());
    }
    Some(())
}

fn body_has_replay_shape(
    stmts: &[Stmt],
    scope: &crate::TemporalScope,
    finite_replay_domain: bool,
    direct_pointwise_loop: bool,
) -> bool {
    let has_source_helper_destructure = stmts.iter().any(|stmt| {
        let Stmt::Local(local) = stmt else {
            return false;
        };
        if !matches!(strip_pat(&local.pat), Pat::Tuple(_)) {
            return false;
        }
        let Some(init) = local.init.as_ref().filter(|init| init.diverge.is_none()) else {
            return false;
        };
        let Expr::Call(call) = strip_refs_groups(&init.expr) else {
            return false;
        };
        simple_call_name(call)
            .and_then(|name| scope.fn_registry().lookup(&name))
            .is_some()
    });
    let has_match = stmts
        .iter()
        .any(|stmt| matches!(stmt, Stmt::Expr(Expr::Match(_), _)));
    (has_source_helper_destructure && has_match)
        || crate::sugar::extract_if::body_has_replay_shape(stmts)
        || crate::sugar::insert::body_has_replay_shape(stmts)
        || body_has_const_if_local_replay_shape(stmts)
        || body_has_helper_call_replay_shape(stmts, scope)
        || body_has_scalar_accumulator_replay_shape(stmts, scope)
        || (finite_replay_domain && body_has_pointwise_assert_replay_shape(stmts, true))
        // Tuple loop vars (`for (i, &x)`) carry their binding work in the pattern itself.
        // Literal CHAR ranges cannot be lowered as integer foralls, so replay concrete
        // characters. Relation-style assertion macros over integer ranges also replay
        // point-wise; bare predicate `assert!(x >= 0)` stays owned by `forall_loop`.
        || (finite_replay_domain
            && direct_pointwise_loop
            && body_has_pointwise_assert_replay_shape(stmts, false))
}

fn body_has_relation_assertion_surface(stmts: &[Stmt]) -> bool {
    stmts.iter().any(|stmt| match stmt {
        Stmt::Macro(stmt_macro) => relation_assert_macro(&stmt_macro.mac),
        Stmt::Expr(Expr::Macro(expr_macro), _) => relation_assert_macro(&expr_macro.mac),
        Stmt::Expr(Expr::If(expr_if), _) => if_stmt_has_relation_assertion(expr_if),
        Stmt::Expr(Expr::ForLoop(for_loop), _) => {
            body_has_relation_assertion_surface(&for_loop.body.stmts)
        }
        _ => false,
    })
}

fn if_stmt_has_relation_assertion(expr_if: &syn::ExprIf) -> bool {
    body_has_relation_assertion_surface(&expr_if.then_branch.stmts)
        || expr_if
            .else_branch
            .as_ref()
            .is_some_and(|(_, else_branch)| match strip_refs_groups(else_branch) {
                Expr::Block(block) => body_has_relation_assertion_surface(&block.block.stmts),
                Expr::If(nested) => if_stmt_has_relation_assertion(nested),
                _ => false,
            })
}

fn relation_assert_macro(mac: &syn::Macro) -> bool {
    mac.path.segments.last().is_some_and(|segment| {
        matches!(
            segment.ident.to_string().as_str(),
            "assert_eq"
                | "assert_ne"
                | "debug_assert_eq"
                | "debug_assert_ne"
                | "assert_eq_const_safe"
        )
    })
}

fn domain_has_replay_shape(expr: &Expr, composite_domain: bool) -> bool {
    range_domain_shape(expr) || composite_domain
}

fn sequence_adaptor_domain_shape(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    !range_domain_shape(expr) && has_composite(expr, fcx)
}

fn replay_assert_count(stmts: &[Stmt], scope: &crate::TemporalScope) -> usize {
    count_asserts_in_stmts(stmts) + helper_call_assert_count(stmts, scope)
}

fn helper_call_assert_count(stmts: &[Stmt], scope: &crate::TemporalScope) -> usize {
    stmts
        .iter()
        .filter_map(|stmt| match stmt {
            Stmt::Expr(expr, _) => helper_assert_count_expr(expr, scope),
            _ => None,
        })
        .sum()
}

fn helper_assert_count_expr(expr: &Expr, scope: &crate::TemporalScope) -> Option<usize> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    let name = simple_call_name(call)?;
    let helper = scope.fn_registry().lookup(&name)?;
    let count = count_asserts_in_stmts(&helper.block.stmts);
    (count > 0).then_some(count)
}

fn body_has_helper_call_replay_shape(stmts: &[Stmt], scope: &crate::TemporalScope) -> bool {
    helper_call_assert_count(stmts, scope) > 0
}

fn body_has_scalar_accumulator_replay_shape(stmts: &[Stmt], scope: &crate::TemporalScope) -> bool {
    if accumulator_seed_names(stmts, scope).is_empty() {
        return false;
    }
    let mut saw_assert = false;
    let mut saw_accumulator_update = false;
    for stmt in stmts {
        match stmt {
            Stmt::Local(local) => {
                let Pat::Ident(pat) = strip_pat(&local.pat) else {
                    return false;
                };
                if pat.subpat.is_some() || pat.by_ref.is_some() || pat.mutability.is_some() {
                    return false;
                }
                if local
                    .init
                    .as_ref()
                    .is_none_or(|init| init.diverge.is_some())
                {
                    return false;
                }
            }
            Stmt::Expr(Expr::Call(_), _) => {}
            Stmt::Macro(stmt_macro) if macro_is_assertion_surface(&stmt_macro.mac) => {
                saw_assert = true;
            }
            Stmt::Expr(Expr::Macro(expr_macro), _)
                if macro_is_assertion_surface(&expr_macro.mac) =>
            {
                saw_assert = true;
            }
            Stmt::Expr(Expr::Binary(binary), _)
                if matches!(
                    binary.op,
                    BinOp::AddAssign(_) | BinOp::SubAssign(_) | BinOp::MulAssign(_)
                ) =>
            {
                if simple_path_name(&binary.left).is_none() {
                    return false;
                }
                saw_accumulator_update = true;
            }
            Stmt::Expr(Expr::Assign(assign), _) => {
                if simple_path_name(&assign.left).is_none() {
                    return false;
                }
                saw_accumulator_update = true;
            }
            Stmt::Item(_) => {}
            _ => return false,
        }
    }
    saw_assert || (saw_accumulator_update && helper_call_assert_count(stmts, scope) > 0)
}

fn body_has_temporal_assignment_replay_shape(
    stmts: &[Stmt],
    scope: &crate::TemporalScope,
    loop_var: &str,
) -> bool {
    if stmts.is_empty() {
        return false;
    }
    let available: BTreeSet<String> = scope
        .let_bindings_iter()
        .map(|(name, _)| name.clone())
        .collect();
    stmts.iter().all(|stmt| {
        let Some((target, rhs)) = temporal_loop_assignment_parts(stmt) else {
            return false;
        };
        available.contains(&target) && temporal_loop_pure_value_expr(rhs, loop_var, &target)
    })
}

fn temporal_loop_assignment_parts(stmt: &Stmt) -> Option<(String, &Expr)> {
    match stmt {
        Stmt::Expr(Expr::Binary(binary), _)
            if matches!(
                binary.op,
                BinOp::AddAssign(_) | BinOp::SubAssign(_) | BinOp::MulAssign(_)
            ) =>
        {
            Some((
                assignment_target_base_name(&binary.left)?,
                binary.right.as_ref(),
            ))
        }
        Stmt::Expr(Expr::Assign(assign), _) => Some((
            assignment_target_base_name(&assign.left)?,
            assign.right.as_ref(),
        )),
        _ => None,
    }
}

fn assignment_target_base_name(lhs: &Expr) -> Option<String> {
    match strip_refs_groups(lhs) {
        Expr::Path(_) => simple_path_name(lhs),
        Expr::Index(index) => simple_path_name(&index.expr),
        Expr::Unary(unary) if matches!(unary.op, UnOp::Deref(_)) => simple_path_name(&unary.expr),
        _ => None,
    }
}

fn temporal_loop_pure_value_expr(expr: &Expr, loop_var: &str, target: &str) -> bool {
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => matches!(lit.lit, Lit::Int(_) | Lit::Byte(_)),
        Expr::Unary(unary) if matches!(unary.op, UnOp::Neg(_)) => {
            temporal_loop_pure_value_expr(&unary.expr, loop_var, target)
        }
        Expr::Binary(binary)
            if matches!(
                binary.op,
                BinOp::Add(_) | BinOp::Sub(_) | BinOp::Mul(_) | BinOp::Div(_) | BinOp::Rem(_)
            ) =>
        {
            temporal_loop_pure_value_expr(&binary.left, loop_var, target)
                && temporal_loop_pure_value_expr(&binary.right, loop_var, target)
        }
        Expr::Path(_) => {
            simple_path_name(expr).is_some_and(|name| name == loop_var || name == target)
        }
        Expr::Cast(cast) => temporal_loop_pure_value_expr(&cast.expr, loop_var, target),
        _ => false,
    }
}

fn accumulator_seed_names(stmts: &[Stmt], scope: &crate::TemporalScope) -> Vec<String> {
    let available: BTreeSet<String> = scope
        .let_bindings_iter()
        .map(|(name, _)| name.clone())
        .collect();
    if available.is_empty() {
        return Vec::new();
    }
    let mut names = BTreeSet::new();
    for stmt in stmts {
        match stmt {
            Stmt::Expr(Expr::Binary(binary), _)
                if matches!(
                    binary.op,
                    BinOp::AddAssign(_) | BinOp::SubAssign(_) | BinOp::MulAssign(_)
                ) =>
            {
                if let Some(name) = simple_path_name(&binary.left) {
                    if available.contains(&name) {
                        names.insert(name);
                    }
                }
            }
            Stmt::Expr(Expr::Assign(assign), _) => {
                if let Some(name) = simple_path_name(&assign.left) {
                    if available.contains(&name) {
                        names.insert(name);
                    }
                }
            }
            _ => {}
        }
    }
    names.into_iter().collect()
}

fn body_has_pointwise_assert_replay_shape(stmts: &[Stmt], require_binding: bool) -> bool {
    let mut saw_assert = false;
    let mut saw_replay_binding = false;
    for stmt in stmts {
        match stmt {
            Stmt::Local(local) => {
                let Pat::Ident(pat) = strip_pat(&local.pat) else {
                    return false;
                };
                if pat.subpat.is_some() || pat.by_ref.is_some() || pat.mutability.is_some() {
                    return false;
                }
                if local
                    .init
                    .as_ref()
                    .is_none_or(|init| init.diverge.is_some())
                {
                    return false;
                }
                saw_replay_binding = true;
            }
            Stmt::Expr(Expr::Call(_), _) => {
                saw_replay_binding = true;
            }
            Stmt::Macro(stmt_macro) if macro_is_assertion_surface(&stmt_macro.mac) => {
                saw_assert = true;
            }
            Stmt::Expr(Expr::Macro(expr_macro), _)
                if macro_is_assertion_surface(&expr_macro.mac) =>
            {
                saw_assert = true;
            }
            Stmt::Expr(Expr::If(expr_if), _) if if_stmt_has_pointwise_assert(expr_if) => {
                saw_assert = true;
            }
            Stmt::Expr(Expr::ForLoop(for_loop), _)
                if nested_for_loop_has_pointwise_assert_replay_shape(for_loop) =>
            {
                saw_assert = true;
                saw_replay_binding = true;
            }
            Stmt::Item(_) => {}
            _ => return false,
        }
    }
    saw_assert && (!require_binding || saw_replay_binding)
}

fn nested_for_loop_has_pointwise_assert_replay_shape(for_loop: &syn::ExprForLoop) -> bool {
    loop_var_bindings(for_loop.pat.as_ref()).is_some()
        && range_domain_shape(&for_loop.expr)
        && body_has_pointwise_assert_replay_shape(&for_loop.body.stmts, false)
}

fn if_stmt_has_pointwise_assert(expr_if: &syn::ExprIf) -> bool {
    fn stmts_ok(stmts: &[Stmt]) -> Option<bool> {
        let mut saw_assert = false;
        for stmt in stmts {
            match stmt {
                Stmt::Macro(stmt_macro) if macro_is_assertion_surface(&stmt_macro.mac) => {
                    saw_assert = true;
                }
                Stmt::Expr(Expr::Macro(expr_macro), _)
                    if macro_is_assertion_surface(&expr_macro.mac) =>
                {
                    saw_assert = true;
                }
                Stmt::Expr(Expr::If(expr_if), _) if if_stmt_has_pointwise_assert(expr_if) => {
                    saw_assert = true;
                }
                Stmt::Item(_) => {}
                _ => return None,
            }
        }
        Some(saw_assert)
    }

    if stmts_ok(&expr_if.then_branch.stmts).unwrap_or(false) {
        return true;
    }
    let Some((_, else_branch)) = &expr_if.else_branch else {
        return false;
    };
    match strip_refs_groups(else_branch) {
        Expr::Block(block) => stmts_ok(&block.block.stmts).unwrap_or(false),
        Expr::If(nested) => if_stmt_has_pointwise_assert(nested),
        _ => false,
    }
}

fn body_has_const_if_local_replay_shape(stmts: &[Stmt]) -> bool {
    let mut saw_if_local = false;
    let mut saw_assert = false;
    for stmt in stmts {
        match stmt {
            Stmt::Local(local) => {
                let Pat::Ident(pat) = strip_pat(&local.pat) else {
                    return false;
                };
                if pat.subpat.is_some() || pat.by_ref.is_some() || pat.mutability.is_some() {
                    return false;
                }
                let Some(init) = local.init.as_ref().filter(|init| init.diverge.is_none()) else {
                    return false;
                };
                if !matches!(strip_refs_groups(&init.expr), Expr::If(_)) {
                    return false;
                }
                saw_if_local = true;
            }
            Stmt::Macro(stmt_macro) if macro_is_assertion_surface(&stmt_macro.mac) => {
                saw_assert = true;
            }
            Stmt::Expr(Expr::Macro(expr_macro), _)
                if macro_is_assertion_surface(&expr_macro.mac) =>
            {
                saw_assert = true;
            }
            Stmt::Item(_) => {}
            _ => return false,
        }
    }
    saw_if_local && saw_assert
}

fn strip_pat(pat: &Pat) -> &Pat {
    match pat {
        Pat::Type(t) => strip_pat(&t.pat),
        Pat::Paren(p) => strip_pat(&p.pat),
        _ => pat,
    }
}

fn range_domain_shape(expr: &Expr) -> bool {
    matches!(strip_refs_groups(expr), Expr::Range(range) if range.end.is_some())
}

fn char_range_domain_shape(expr: &Expr) -> bool {
    let Expr::Range(range) = strip_refs_groups(expr) else {
        return false;
    };
    range.start.as_deref().and_then(literal_char).is_some()
        && range.end.as_deref().and_then(literal_char).is_some()
}

fn literal_char(expr: &Expr) -> Option<char> {
    match strip_refs_groups(expr) {
        Expr::Lit(syn::ExprLit {
            lit: Lit::Char(ch), ..
        }) => Some(ch.value()),
        _ => None,
    }
}

fn range_domain_exceeds_replay_cap(expr: &Expr, scope: &crate::TemporalScope) -> bool {
    let Ok(domain) = bounded_domain_from_expr(expr, scope).ok_or(()) else {
        return false;
    };
    let BoundedDomain::Range {
        start,
        end,
        inclusive,
    } = domain
    else {
        return false;
    };
    if let (Some(start), Some(end)) = (const_fold_u128_term(&start), const_fold_u128_term(&end)) {
        let Some(span) = end.checked_sub(start) else {
            return false;
        };
        let Some(len) = span.checked_add(u128::from(inclusive)) else {
            return true;
        };
        return len > SUGAR_SEQ_CAP as u128;
    }
    let (Some(start), Some(end)) = (
        term_as_int(&start).or_else(|| const_fold_int_term(&start)),
        term_as_int(&end).or_else(|| const_fold_int_term(&end)),
    ) else {
        return false;
    };
    let Some(span) = end.checked_sub(start) else {
        return false;
    };
    let Some(len) = span.checked_add(i128::from(inclusive)) else {
        return true;
    };
    len > i128::from(SUGAR_SEQ_CAP)
}

pub(crate) struct ForReplaySugar {
    /// The loop-var binding plan: one ident per pattern component (a single ident for
    /// `for x`/`for &x`; one per tuple slot for `for (i, &x)`). Each per-step element is
    /// bound to these names -- a single element value for a 1-ident plan, or the tuple
    /// components for a multi-ident plan.
    vars: Vec<String>,
    domain: SugarBody<CompositeFloor>,
    domain_expr: Expr,
    body_stmts: Vec<Stmt>,
    seed_names: Vec<String>,
}

fn for_replay_construction_gap(reason: String) -> ! {
    panic!("for_replay recognized a replay shape it could not lawfully reduce: {reason}")
}

impl Sugar for ForReplaySugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let values = match finite_domain_body_exprs(&self.domain, ctx) {
            Ok(values) => values,
            Err(effect) => return Outcome::Incomplete(effect),
        };
        if values.is_empty() || values.len() > SUGAR_SEQ_CAP as usize {
            for_replay_construction_gap(format!(
                "recognized domain `{}` reduced to an empty or over-cap sequence",
                crate::token_key(&self.domain_expr)
            ));
        }
        let source_asserts = replay_assert_count(&self.body_stmts, ctx.scope);
        if source_asserts == 0 {
            if replay_temporal_assignment_loop(ctx, &self.vars, &self.body_stmts, values).is_none()
            {
                for_replay_construction_gap(format!(
                    "temporal assignment replay failed for `{}`",
                    crate::token_key(&self.domain_expr)
                ));
            }
            return Outcome::Complete(Desugared::Constraints {
                atom: eq(bool_const(true), bool_const(true)),
                n: 0,
                kind: AssertionFactKind::Support,
                warrant: Warrant {
                    name: Some(format!(
                        "{}::temporal-loop-replay::{}",
                        ctx.scope.local_scope(),
                        self.vars.join("_")
                    )),
                },
            });
        }

        let mut atoms = Vec::new();
        let mut terminal_effect = None;
        if self.seed_names.is_empty() {
            for value in values {
                let mut replay = Replay::new(ctx);
                if bind_loop_value(&mut replay.bindings, &self.vars, value).is_none()
                    || replay.replay_stmts(&self.body_stmts).is_none()
                {
                    if terminal_effect.is_none() {
                        terminal_effect = replay.terminal_effect.take();
                    }
                    return terminal_effect.map(Outcome::Incomplete).unwrap_or_else(|| {
                        for_replay_construction_gap(format!(
                            "body replay failed without a named child effect for `{}`",
                            crate::token_key(&self.domain_expr)
                        ))
                    });
                }
                atoms.extend(replay.atoms);
            }
        } else {
            let mut replay = Replay::new(ctx);
            if replay.seed_source_bindings(&self.seed_names).is_none() {
                for_replay_construction_gap(format!(
                    "seed binding replay failed for `{}`",
                    crate::token_key(&self.domain_expr)
                ));
            }
            for value in values {
                if bind_loop_value(&mut replay.bindings, &self.vars, value).is_none()
                    || replay.replay_stmts(&self.body_stmts).is_none()
                {
                    if terminal_effect.is_none() {
                        terminal_effect = replay.terminal_effect.take();
                    }
                    return terminal_effect.map(Outcome::Incomplete).unwrap_or_else(|| {
                        for_replay_construction_gap(format!(
                            "seeded body replay failed without a named child effect for `{}`",
                            crate::token_key(&self.domain_expr)
                        ))
                    });
                }
            }
            terminal_effect = replay.terminal_effect.take();
            atoms.extend(replay.atoms);
        }
        if atoms.is_empty() {
            return terminal_effect.map(Outcome::Incomplete).unwrap_or_else(|| {
                for_replay_construction_gap(format!(
                    "recognized replay produced no atoms for `{}`",
                    crate::token_key(&self.domain_expr)
                ))
            });
        }
        Outcome::Complete(Desugared::Constraints {
            atom: and_(atoms),
            n: source_asserts,
            kind: AssertionFactKind::Warranted,
            warrant: Warrant {
                name: Some(format!(
                    "{}::loop::{}",
                    ctx.scope.local_scope(),
                    self.vars.join("_")
                )),
            },
        })
    }
}

fn replay_temporal_assignment_loop(
    ctx: &SugarCtx,
    vars: &[String],
    body_stmts: &[Stmt],
    values: Vec<Expr>,
) -> Option<()> {
    let mut targets = BTreeSet::new();
    for value in values {
        let mut bindings = ExprBindings::new();
        bind_loop_value(&mut bindings, vars, value)?;
        for stmt in body_stmts {
            let (target, _) = temporal_loop_assignment_parts(stmt)?;
            let expr = temporal_assignment_stmt_expr(stmt)?;
            let substituted = substitute_expr(expr, &bindings);
            if !ctx.scope.apply_temporal_rewrite(&substituted) {
                return None;
            }
            targets.insert(target);
        }
    }
    for target in targets {
        ctx.scope.mark_temporal_loop_replayed(&target);
    }
    Some(())
}

fn temporal_assignment_stmt_expr(stmt: &Stmt) -> Option<&Expr> {
    match stmt {
        Stmt::Expr(expr @ Expr::Binary(binary), _)
            if matches!(
                binary.op,
                BinOp::AddAssign(_) | BinOp::SubAssign(_) | BinOp::MulAssign(_)
            ) =>
        {
            Some(expr)
        }
        Stmt::Expr(expr @ Expr::Assign(_), _) => Some(expr),
        _ => None,
    }
}

struct Replay<'a, 'c, 's> {
    ctx: &'s SugarCtx<'a, 'c>,
    bindings: ExprBindings,
    atoms: Vec<Rc<Formula>>,
    terminal_effect: Option<Effect>,
    extract_if: ExtractIfSugar,
    insert: InsertSugar,
}

impl<'a, 'c, 's> Replay<'a, 'c, 's> {
    fn new(ctx: &'s SugarCtx<'a, 'c>) -> Self {
        Self {
            ctx,
            bindings: ExprBindings::new(),
            atoms: Vec::new(),
            terminal_effect: None,
            extract_if: ExtractIfSugar::new(),
            insert: InsertSugar::new(),
        }
    }

    fn replay_stmts(&mut self, stmts: &[Stmt]) -> Option<()> {
        for stmt in stmts {
            self.replay_stmt(stmt)?;
        }
        Some(())
    }

    fn seed_source_bindings(&mut self, names: &[String]) -> Option<()> {
        for name in names {
            let init = self
                .ctx
                .scope
                .let_bindings_iter()
                .find_map(|(bound, init)| (bound == name).then_some(init.clone()))?;
            let value = self.eval_expr(&init)?;
            debug!(
                target: "sugar_lift_rust_tests::sugar::for_replay",
                binding = name.as_str(),
                init = %crate::token_key(&init),
                value = %crate::token_key(&value),
                "seeded scalar accumulator binding for finite loop replay"
            );
            self.bindings.insert(name.clone(), value);
        }
        Some(())
    }

    fn replay_stmt(&mut self, stmt: &Stmt) -> Option<()> {
        match stmt {
            Stmt::Local(local) => {
                let mut handled_temporal = false;
                match self
                    .extract_if
                    .replay_local(local, self.ctx.scope, &self.bindings)?
                {
                    ReplayAction::Handled(()) => handled_temporal = true,
                    ReplayAction::NotMine => {}
                }
                match self
                    .insert
                    .replay_local(local, self.ctx.scope, &self.bindings)?
                {
                    ReplayAction::Handled(()) => handled_temporal = true,
                    ReplayAction::NotMine => {}
                }
                if handled_temporal {
                    return Some(());
                }
                let init = local.init.as_ref().filter(|init| init.diverge.is_none())?;
                let value = self.eval_expr(&init.expr)?;
                self.bind_pat_value(&local.pat, &value)
            }
            Stmt::Macro(stmt_macro) => self.emit_macro(&stmt_macro.mac),
            Stmt::Expr(Expr::Macro(expr_macro), _) => self.emit_macro(&expr_macro.mac),
            Stmt::Expr(Expr::If(expr_if), _) => self.replay_if_stmt(expr_if),
            Stmt::Expr(Expr::ForLoop(for_loop), _) => self.replay_for_loop(for_loop),
            Stmt::Expr(Expr::Match(expr_match), _) => self.replay_match(expr_match),
            Stmt::Expr(Expr::Binary(binary), _)
                if matches!(
                    binary.op,
                    BinOp::AddAssign(_) | BinOp::SubAssign(_) | BinOp::MulAssign(_)
                ) =>
            {
                self.replay_compound_assign(binary)
            }
            Stmt::Expr(Expr::Assign(assign), _) => self.replay_assign(assign),
            Stmt::Expr(expr, _) => {
                match self
                    .extract_if
                    .replay_expr(expr, self.ctx.scope, &self.bindings)?
                {
                    ReplayAction::Handled(()) => return Some(()),
                    ReplayAction::NotMine => {}
                }
                match self
                    .insert
                    .replay_expr(expr, self.ctx.scope, &self.bindings)?
                {
                    ReplayAction::Handled(()) => return Some(()),
                    ReplayAction::NotMine => {}
                }
                if self.replay_helper_call_expr(expr)? {
                    return Some(());
                }
                if count_asserts_in_expr_local(expr) == 0 {
                    Some(())
                } else {
                    let substituted = substitute_expr(expr, &self.bindings);
                    self.emit_constraint_expr(&substituted)
                }
            }
            Stmt::Item(Item::Const(item)) => {
                let expr = replay_const_initializer_expr(item);
                let expr = substitute_expr(&expr, &self.bindings);
                debug!(
                    target: "sugar_lift_rust_tests::sugar::for_replay",
                    binding = item.ident.to_string(),
                    value = %crate::token_key(&expr),
                    "bound local const during finite loop replay"
                );
                self.bindings.insert(item.ident.to_string(), expr);
                Some(())
            }
            Stmt::Item(_) => Some(()),
        }
    }

    fn replay_if_stmt(&mut self, expr_if: &syn::ExprIf) -> Option<()> {
        let cond = self.expr_const_bool(&expr_if.cond)?;
        debug!(
            sugar = "for_replay",
            cond = %crate::token_key(&expr_if.cond),
            selected = if cond { "then" } else { "else" },
            "replayed const-if statement under pinned loop value"
        );
        if cond {
            self.replay_stmts(&expr_if.then_branch.stmts)
        } else {
            let Some((_, else_expr)) = expr_if.else_branch.as_ref() else {
                return Some(());
            };
            match else_expr.as_ref() {
                Expr::Block(block) => self.replay_stmts(&block.block.stmts),
                Expr::If(next) => self.replay_if_stmt(next),
                Expr::Unsafe(block) => self.replay_stmts(&block.block.stmts),
                other => self.replay_stmt(&Stmt::Expr(other.clone(), None)),
            }
        }
    }

    fn replay_for_loop(&mut self, for_loop: &syn::ExprForLoop) -> Option<()> {
        let vars = loop_var_bindings(for_loop.pat.as_ref())?;
        let domain = substitute_expr(&for_loop.expr, &self.bindings);
        if range_domain_exceeds_replay_cap(&domain, self.ctx.scope) {
            return None;
        }
        let values = match finite_domain_exprs(&domain, self.ctx) {
            Ok(values) => values,
            Err(effect) => {
                self.terminal_effect = Some(effect);
                return None;
            }
        };
        if values.is_empty() || values.len() > SUGAR_SEQ_CAP as usize {
            return None;
        }
        let saved: Vec<_> = vars
            .iter()
            .map(|name| (name.clone(), self.bindings.get(name).cloned()))
            .collect();
        let result = (|| {
            for value in values {
                bind_loop_value(&mut self.bindings, &vars, value)?;
                self.replay_stmts(&for_loop.body.stmts)?;
            }
            Some(())
        })();
        for (name, previous) in saved {
            if let Some(expr) = previous {
                self.bindings.insert(name, expr);
            } else {
                self.bindings.remove(&name);
            }
        }
        result
    }

    fn replay_helper_call_expr(&mut self, expr: &Expr) -> Option<bool> {
        let Expr::Call(call) = strip_refs_groups(expr) else {
            return Some(false);
        };
        let Some(name) = simple_call_name(call) else {
            return Some(false);
        };
        let Some(helper) = self.ctx.scope.fn_registry().lookup(&name) else {
            return Some(false);
        };
        if helper.sig.asyncness.is_some() {
            return None;
        }
        if !matches!(
            cfg_resolve(&helper.attrs, self.ctx.options),
            CfgDisposition::Present
        ) {
            return None;
        }
        let params = helper_param_names(&helper).ok()?;
        if params.len() != call.args.len() {
            return None;
        }
        let mut bindings = ExprBindings::new();
        for (param, arg) in params.into_iter().zip(call.args.iter()) {
            bindings.insert(param, self.eval_expr(arg)?);
        }
        debug!(
            sugar = "for_replay",
            helper = name.as_str(),
            args = call.args.len(),
            "replaying assertion helper call through CallsiteSugar under pinned loop value"
        );
        let cs = CallsiteSugar::from_bindings(helper.as_ref(), name.clone(), bindings);
        let reduced = HashSet::new();
        let mut fw = self.ctx.float_widths.borrow_mut();
        match cs.desugar(
            self.ctx.scope.local_scope(),
            self.atoms.len(),
            self.ctx.options,
            self.ctx.reducer,
            *fw,
            &reduced,
            self.ctx.macro_depth,
            self.ctx.factory_audits,
        ) {
            CallsiteOutcome::Complete(commit) if commit.skipped.is_empty() => {
                for helper in &commit.reduced_helpers {
                    self.ctx.scope.record_inlined_value_helper(helper);
                }
                self.ctx.scope.record_inlined_value_helper(&commit.name);
                self.atoms.extend(
                    commit
                        .entries
                        .into_iter()
                        .filter(|entry| matches!(entry.kind, AssertionFactKind::Warranted))
                        .map(|entry| entry.atom),
                );
                Some(true)
            }
            CallsiteOutcome::Complete(commit) => {
                debug!(
                    sugar = "for_replay",
                    helper = name.as_str(),
                    skipped = commit.skipped.len(),
                    "CallsiteSugar helper replay hit terminal refusals; replay declined"
                );
                None
            }
            CallsiteOutcome::Bail(cause) => {
                debug!(
                    sugar = "for_replay",
                    helper = name.as_str(),
                    cause = ?cause,
                    "CallsiteSugar helper replay bailed"
                );
                None
            }
        }
    }

    fn replay_assign(&mut self, assign: &syn::ExprAssign) -> Option<()> {
        let name = simple_path_name(&assign.left)?;
        let rhs = self.eval_expr(&assign.right)?;
        self.bindings.insert(name, rhs);
        Some(())
    }

    fn replay_compound_assign(&mut self, binary: &syn::ExprBinary) -> Option<()> {
        let name = simple_path_name(&binary.left)?;
        let old = self.bindings.get(&name)?.clone();
        let rhs = self.eval_expr(&binary.right)?;
        let updated: Expr = match binary.op {
            BinOp::AddAssign(_) => syn::parse_quote!((#old) + (#rhs)),
            BinOp::SubAssign(_) => syn::parse_quote!((#old) - (#rhs)),
            BinOp::MulAssign(_) => syn::parse_quote!((#old) * (#rhs)),
            _ => return None,
        };
        let updated = self.eval_expr(&updated)?;
        debug!(
            target: "sugar_lift_rust_tests::sugar::for_replay",
            binding = name.as_str(),
            value = %crate::token_key(&updated),
            "folded scalar accumulator update during finite loop replay"
        );
        self.bindings.insert(name, updated);
        Some(())
    }

    fn replay_match(&mut self, expr_match: &syn::ExprMatch) -> Option<()> {
        let scrutinee = self.eval_expr(&expr_match.expr)?;
        for arm in &expr_match.arms {
            if arm.guard.is_some() {
                return None;
            }
            match pattern_bindings(&scrutinee, &arm.pat, self.ctx.scope) {
                PatternOutcome::NoMatch => continue,
                PatternOutcome::Unsupported => return None,
                PatternOutcome::Match(bindings) => {
                    let mut saved_pattern_bindings = Vec::new();
                    for (name, expr) in bindings {
                        saved_pattern_bindings
                            .push((name.clone(), self.bindings.get(&name).cloned()));
                        self.bindings.insert(name, expr);
                    }
                    let result = match arm.body.as_ref() {
                        Expr::Block(block) => self.replay_stmts(&block.block.stmts),
                        Expr::Unsafe(block) => self.replay_stmts(&block.block.stmts),
                        other => self.replay_stmt(&Stmt::Expr(other.clone(), None)),
                    };
                    for (name, previous) in saved_pattern_bindings {
                        if let Some(expr) = previous {
                            self.bindings.insert(name, expr);
                        } else {
                            self.bindings.remove(&name);
                        }
                    }
                    return result;
                }
            }
        }
        None
    }

    fn bind_pat_value(&mut self, pat: &Pat, value: &Expr) -> Option<()> {
        match strip_pat(pat) {
            Pat::Ident(ident) if ident.subpat.is_none() && ident.by_ref.is_none() => {
                self.bindings.insert(ident.ident.to_string(), value.clone());
                Some(())
            }
            Pat::Tuple(tuple_pat) => {
                let Expr::Tuple(tuple) = strip_refs_groups(value) else {
                    return None;
                };
                if tuple_pat.elems.len() != tuple.elems.len() {
                    return None;
                }
                for (pat, expr) in tuple_pat.elems.iter().zip(tuple.elems.iter()) {
                    match strip_pat(pat) {
                        Pat::Wild(_) => {}
                        _ => self.bind_pat_value(pat, expr)?,
                    }
                }
                Some(())
            }
            Pat::Wild(_) => Some(()),
            _ => None,
        }
    }

    fn emit_macro(&mut self, mac: &syn::Macro) -> Option<()> {
        match self
            .extract_if
            .constraint_for_macro(mac, self.ctx.scope, &self.bindings)?
        {
            ReplayAction::Handled(atom) => {
                self.atoms.push(atom);
                return Some(());
            }
            ReplayAction::NotMine => {}
        }
        match self.insert.constraint_for_macro(
            mac,
            self.ctx.scope,
            self.ctx.scope.local_scope(),
            &self.bindings,
        )? {
            ReplayAction::Handled(atom) => {
                self.atoms.push(atom);
                return Some(());
            }
            ReplayAction::NotMine => {}
        }
        let mut expr = Expr::Macro(syn::ExprMacro {
            attrs: Vec::new(),
            mac: mac.clone(),
        });
        if let Expr::Macro(expr_macro) = &mut expr {
            expr_macro.mac.tokens = substitute_macro_tokens(mac, &self.bindings)?;
        }
        self.emit_constraint_expr(&expr)
    }

    fn emit_constraint_expr(&mut self, expr: &Expr) -> Option<()> {
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(self.ctx.scope, self.ctx.options, &let_inits);
        let node = crate::sugar::factory::build_constraint(expr, &fcx);
        match node.desugar(self.ctx) {
            Outcome::Complete(Desugared::Constraints {
                atom,
                kind: AssertionFactKind::Warranted,
                ..
            }) => {
                self.atoms.push(atom);
                Some(())
            }
            Outcome::Incomplete(effect) => {
                let reason = effect.reason();
                if reason.contains("structural backstop") {
                    for_replay_construction_gap(format!(
                        "nested assertion `{}` hit the structural backstop",
                        crate::token_key(expr)
                    ));
                }
                self.terminal_effect = Some(effect);
                None
            }
            Outcome::Complete(_) => None,
        }
    }

    fn eval_expr(&self, expr: &Expr) -> Option<Expr> {
        let substituted = substitute_expr(expr, &self.bindings);
        if let Some(value) = self.ground_expr_from_factory(&substituted) {
            return Some(value);
        }
        match strip_refs_groups(&substituted) {
            Expr::Call(call) => self.eval_call(call).or(Some(substituted)),
            Expr::Block(block) => self.eval_single_expr_block(&block.block),
            Expr::If(expr_if) => self.eval_if_value(expr_if),
            Expr::Match(expr_match) => self.eval_match_value(expr_match),
            _ => Some(substituted),
        }
    }

    fn ground_expr_from_factory(&self, expr: &Expr) -> Option<Expr> {
        let term = self.term_from_factory(expr)?;
        let value = term_ground_expr(&term)?;
        debug!(
            target: "sugar_lift_rust_tests::sugar::for_replay",
            source = %crate::token_key(expr),
            value = %crate::token_key(&value),
            "replayed local value through term factory"
        );
        Some(value)
    }

    fn term_from_factory(&self, expr: &Expr) -> Option<Rc<Term>> {
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(self.ctx.scope, self.ctx.options, &let_inits);
        build_term(expr, &fcx)
            .desugar(self.ctx)
            .complete()?
            .into_term()
    }

    fn eval_if_value(&self, expr_if: &syn::ExprIf) -> Option<Expr> {
        let cond = self.expr_const_bool(&expr_if.cond)?;
        debug!(
            sugar = "for_replay",
            cond = %crate::token_key(&expr_if.cond),
            selected = if cond { "then" } else { "else" },
            "evaluated const-if local during loop replay"
        );
        if cond {
            self.eval_single_expr_block(&expr_if.then_branch)
        } else {
            let (_, else_expr) = expr_if.else_branch.as_ref()?;
            self.eval_expr(else_expr)
        }
    }

    fn eval_single_expr_block(&self, block: &syn::Block) -> Option<Expr> {
        match block.stmts.as_slice() {
            [Stmt::Expr(expr, None)] => self.eval_expr(expr),
            _ => None,
        }
    }

    fn eval_call(&self, call: &syn::ExprCall) -> Option<Expr> {
        let name = simple_call_name(call)?;
        let helper = self.ctx.scope.fn_registry().lookup(&name)?;
        if helper.sig.asyncness.is_some() {
            return None;
        }
        let mut params = Vec::new();
        for input in &helper.sig.inputs {
            let syn::FnArg::Typed(pat_type) = input else {
                return None;
            };
            params.push(simple_pat_name(&pat_type.pat)?);
        }
        if params.len() != call.args.len() {
            return None;
        }
        let mut child = Replay::new(self.ctx);
        for (param, arg) in params.into_iter().zip(call.args.iter()) {
            child.bindings.insert(param, self.eval_expr(arg)?);
        }
        child.eval_value_body(&helper.block)
    }

    fn eval_value_body(&mut self, block: &syn::Block) -> Option<Expr> {
        let (tail, leading) = block.stmts.split_last()?;
        for stmt in leading {
            match stmt {
                Stmt::Local(local) => {
                    let init = local.init.as_ref().filter(|init| init.diverge.is_none())?;
                    let value = self.eval_expr(&init.expr)?;
                    self.bind_pat_value(&local.pat, &value)?;
                }
                Stmt::Macro(stmt_macro) if self.assert_macro_const_true(&stmt_macro.mac)? => {}
                Stmt::Expr(Expr::Macro(expr_macro), _)
                    if self.assert_macro_const_true(&expr_macro.mac)? => {}
                _ => return None,
            }
        }
        match tail {
            Stmt::Expr(expr, None) => self.eval_expr(expr),
            Stmt::Macro(stmt_macro) if self.assert_macro_const_true(&stmt_macro.mac)? => {
                Some(syn::parse_quote!(()))
            }
            Stmt::Expr(Expr::Macro(expr_macro), _)
                if self.assert_macro_const_true(&expr_macro.mac)? =>
            {
                Some(syn::parse_quote!(()))
            }
            _ => None,
        }
    }

    fn eval_match_value(&self, expr_match: &syn::ExprMatch) -> Option<Expr> {
        let scrutinee = self.eval_expr(&expr_match.expr)?;
        for arm in &expr_match.arms {
            if arm.guard.is_some() {
                return None;
            }
            match pattern_bindings(&scrutinee, &arm.pat, self.ctx.scope) {
                PatternOutcome::NoMatch => continue,
                PatternOutcome::Unsupported => return None,
                PatternOutcome::Match(bindings) => {
                    let mut child_bindings = self.bindings.clone();
                    for (name, expr) in bindings {
                        child_bindings.insert(name, expr);
                    }
                    let mut child = Replay {
                        ctx: self.ctx,
                        bindings: child_bindings,
                        atoms: Vec::new(),
                        terminal_effect: None,
                        extract_if: self.extract_if.clone(),
                        insert: self.insert.clone(),
                    };
                    return match arm.body.as_ref() {
                        Expr::Block(block) => child.eval_value_body(&block.block),
                        Expr::Unsafe(block) => child.eval_value_body(&block.block),
                        other => child.eval_expr(other),
                    };
                }
            }
        }
        None
    }

    fn assert_macro_const_true(&self, mac: &syn::Macro) -> Option<bool> {
        let name = mac.path.segments.last()?.ident.to_string();
        if !matches!(name.as_str(), "assert" | "debug_assert") {
            return None;
        }
        let args = crate::parse_macro_args(mac.tokens.clone()).ok()?;
        let condition = args.exprs.first()?;
        self.expr_const_bool(condition).filter(|value| *value)
    }

    fn expr_const_bool(&self, expr: &Expr) -> Option<bool> {
        let substituted = substitute_expr(expr, &self.bindings);
        match strip_refs_groups(&substituted) {
            Expr::Lit(lit) => match &lit.lit {
                Lit::Bool(value) => Some(value.value),
                _ => None,
            },
            Expr::Unary(unary) if matches!(unary.op, syn::UnOp::Not(_)) => {
                self.expr_const_bool(&unary.expr).map(|v| !v)
            }
            Expr::Binary(binary) => match binary.op {
                BinOp::And(_) => {
                    let left = self.expr_const_bool(&binary.left)?;
                    if !left {
                        return Some(false);
                    }
                    Some(self.expr_const_bool(&binary.right)?)
                }
                BinOp::Or(_) => {
                    let left = self.expr_const_bool(&binary.left)?;
                    if left {
                        return Some(true);
                    }
                    Some(self.expr_const_bool(&binary.right)?)
                }
                BinOp::BitAnd(_) => Some(
                    self.expr_const_bool(&binary.left)? & self.expr_const_bool(&binary.right)?,
                ),
                BinOp::BitOr(_) => Some(
                    self.expr_const_bool(&binary.left)? | self.expr_const_bool(&binary.right)?,
                ),
                BinOp::Eq(_) => {
                    if let Some((lhs, rhs)) = self.expr_const_u128_pair(&binary.left, &binary.right)
                    {
                        return Some(lhs == rhs);
                    }
                    Some(self.expr_const_int(&binary.left)? == self.expr_const_int(&binary.right)?)
                }
                BinOp::Ne(_) => {
                    if let Some((lhs, rhs)) = self.expr_const_u128_pair(&binary.left, &binary.right)
                    {
                        return Some(lhs != rhs);
                    }
                    Some(self.expr_const_int(&binary.left)? != self.expr_const_int(&binary.right)?)
                }
                BinOp::Lt(_) => {
                    if let Some((lhs, rhs)) = self.expr_const_u128_pair(&binary.left, &binary.right)
                    {
                        return Some(lhs < rhs);
                    }
                    Some(self.expr_const_int(&binary.left)? < self.expr_const_int(&binary.right)?)
                }
                BinOp::Le(_) => {
                    if let Some((lhs, rhs)) = self.expr_const_u128_pair(&binary.left, &binary.right)
                    {
                        return Some(lhs <= rhs);
                    }
                    Some(self.expr_const_int(&binary.left)? <= self.expr_const_int(&binary.right)?)
                }
                BinOp::Gt(_) => {
                    if let Some((lhs, rhs)) = self.expr_const_u128_pair(&binary.left, &binary.right)
                    {
                        return Some(lhs > rhs);
                    }
                    Some(self.expr_const_int(&binary.left)? > self.expr_const_int(&binary.right)?)
                }
                BinOp::Ge(_) => {
                    if let Some((lhs, rhs)) = self.expr_const_u128_pair(&binary.left, &binary.right)
                    {
                        return Some(lhs >= rhs);
                    }
                    Some(self.expr_const_int(&binary.left)? >= self.expr_const_int(&binary.right)?)
                }
                _ => None,
            },
            _ => {
                let term = self.term_from_factory(&substituted)?;
                match term.as_ref() {
                    Term::Const {
                        value: sugar_ir_symbolic::ConstValue::Bool(value),
                        ..
                    } => Some(*value),
                    _ => None,
                }
            }
        }
    }

    fn expr_const_int(&self, expr: &Expr) -> Option<i128> {
        let substituted = substitute_expr(expr, &self.bindings);
        let term = self.term_from_factory(&substituted)?;
        term_as_int(&term).or_else(|| const_fold_int_term(&term))
    }

    fn expr_const_u128(&self, expr: &Expr) -> Option<u128> {
        let substituted = substitute_expr(expr, &self.bindings);
        let term = self.term_from_factory(&substituted)?;
        const_fold_u128_term(&term)
    }

    fn expr_const_u128_pair(&self, lhs: &Expr, rhs: &Expr) -> Option<(u128, u128)> {
        let left = self.expr_const_u128(lhs);
        let right = self.expr_const_u128(rhs);
        if left.is_none() && right.is_none() {
            return None;
        }
        Some((
            left.or_else(|| {
                self.expr_const_int(lhs)
                    .and_then(|n| u128::try_from(n).ok())
            })?,
            right.or_else(|| {
                self.expr_const_int(rhs)
                    .and_then(|n| u128::try_from(n).ok())
            })?,
        ))
    }
}

enum PatternOutcome {
    Match(ExprBindings),
    NoMatch,
    Unsupported,
}

fn pattern_bindings(scrutinee: &Expr, pat: &Pat, scope: &crate::TemporalScope) -> PatternOutcome {
    match strip_pat(pat) {
        Pat::Wild(_) => PatternOutcome::Match(ExprBindings::new()),
        Pat::Ident(ident)
            if ident.subpat.is_none()
                && ident.mutability.is_none()
                && ident.by_ref.is_none()
                && is_const_pattern_ident(&ident.ident.to_string()) =>
        {
            let Some(lhs) = expr_const_int(scrutinee, scope) else {
                return PatternOutcome::Unsupported;
            };
            let Ok(rhs_expr) = syn::parse_str::<Expr>(&ident.ident.to_string()) else {
                return PatternOutcome::Unsupported;
            };
            let Some(rhs) = expr_const_int(&rhs_expr, scope) else {
                return PatternOutcome::Unsupported;
            };
            if lhs == rhs {
                PatternOutcome::Match(ExprBindings::new())
            } else {
                PatternOutcome::NoMatch
            }
        }
        Pat::Ident(ident)
            if ident.subpat.is_none() && ident.mutability.is_none() && ident.by_ref.is_none() =>
        {
            let mut bindings = ExprBindings::new();
            bindings.insert(ident.ident.to_string(), scrutinee.clone());
            PatternOutcome::Match(bindings)
        }
        Pat::Lit(lit) => {
            let Some(lhs) = expr_const_int(scrutinee, scope) else {
                return PatternOutcome::Unsupported;
            };
            let Some(rhs) = literal_int(&lit.lit) else {
                return PatternOutcome::Unsupported;
            };
            if lhs == rhs {
                PatternOutcome::Match(ExprBindings::new())
            } else {
                PatternOutcome::NoMatch
            }
        }
        Pat::Range(range) => {
            let Some(value) = expr_const_int(scrutinee, scope) else {
                return PatternOutcome::Unsupported;
            };
            let lower_ok = range
                .start
                .as_ref()
                .and_then(|start| expr_const_int(start, scope))
                .map(|lo| value >= lo)
                .unwrap_or(true);
            let upper_ok = range
                .end
                .as_ref()
                .and_then(|end| expr_const_int(end, scope))
                .map(|hi| {
                    if matches!(range.limits, syn::RangeLimits::Closed(_)) {
                        value <= hi
                    } else {
                        value < hi
                    }
                })
                .unwrap_or(true);
            if lower_ok && upper_ok {
                PatternOutcome::Match(ExprBindings::new())
            } else {
                PatternOutcome::NoMatch
            }
        }
        Pat::TupleStruct(tuple_struct) => {
            let Some((tag, payloads)) = variant_call(scrutinee) else {
                return PatternOutcome::Unsupported;
            };
            if tag != path_to_variant_string(&tuple_struct.path) {
                return PatternOutcome::NoMatch;
            }
            if tuple_struct.elems.len() != payloads.len() {
                return PatternOutcome::Unsupported;
            }
            let mut bindings = ExprBindings::new();
            for (pat, payload) in tuple_struct.elems.iter().zip(payloads.into_iter()) {
                match strip_pat(pat) {
                    Pat::Wild(_) => {}
                    Pat::Ident(ident)
                        if ident.subpat.is_none()
                            && ident.mutability.is_none()
                            && ident.by_ref.is_none() =>
                    {
                        bindings.insert(ident.ident.to_string(), payload);
                    }
                    _ => return PatternOutcome::Unsupported,
                }
            }
            PatternOutcome::Match(bindings)
        }
        Pat::Path(path) => {
            if let (Some(lhs), Some(rhs)) = (
                expr_const_int(scrutinee, scope),
                expr_const_int(
                    &Expr::Path(syn::ExprPath {
                        attrs: Vec::new(),
                        qself: None,
                        path: path.path.clone(),
                    }),
                    scope,
                ),
            ) {
                return if lhs == rhs {
                    PatternOutcome::Match(ExprBindings::new())
                } else {
                    PatternOutcome::NoMatch
                };
            }
            let Some((tag, payloads)) = variant_call(scrutinee) else {
                return PatternOutcome::Unsupported;
            };
            if !payloads.is_empty() {
                return PatternOutcome::Unsupported;
            }
            if tag == path_to_variant_string(&path.path) {
                PatternOutcome::Match(ExprBindings::new())
            } else {
                PatternOutcome::NoMatch
            }
        }
        Pat::Reference(reference) => pattern_bindings(scrutinee, &reference.pat, scope),
        Pat::Or(or_pat) => {
            for case in &or_pat.cases {
                match pattern_bindings(scrutinee, case, scope) {
                    PatternOutcome::NoMatch => {}
                    other => return other,
                }
            }
            PatternOutcome::NoMatch
        }
        _ => PatternOutcome::Unsupported,
    }
}

fn is_const_pattern_ident(name: &str) -> bool {
    name.chars().any(|ch| ch.is_ascii_uppercase())
        && name
            .chars()
            .all(|ch| ch.is_ascii_uppercase() || ch.is_ascii_digit() || ch == '_')
}

fn finite_domain_body_exprs(
    domain: &SugarBody<CompositeFloor>,
    ctx: &SugarCtx,
) -> Result<Vec<Expr>, Effect> {
    let seq = match domain.reduce(ctx) {
        Outcome::Complete(Desugared::Seq(seq)) => seq,
        Outcome::Complete(_) => {
            for_replay_construction_gap(
                "domain body completed as a non-sequence floor".to_string(),
            );
        }
        Outcome::Incomplete(effect) => return Err(effect),
    };
    let mut values = Vec::with_capacity(seq.len());
    for elem in seq {
        let value = match elem.value.as_ref() {
            Some(ConstVal::Int(value)) => int_expr(*value).unwrap_or_else(|| {
                for_replay_construction_gap(format!(
                    "integer domain element `{value}` did not reify to an expression"
                ))
            }),
            Some(ConstVal::PrimitiveInt { .. }) => elem
                .value
                .as_ref()
                .and_then(ConstVal::to_expr)
                .unwrap_or_else(|| {
                    for_replay_construction_gap(
                        "primitive integer domain element did not reify to an expression"
                            .to_string(),
                    )
                }),
            Some(ConstVal::UInt128(value)) => u128_expr(*value).unwrap_or_else(|| {
                for_replay_construction_gap(format!(
                    "u128 domain element `{value}` did not reify to an expression"
                ))
            }),
            _ => elem.expr,
        };
        values.push(value);
    }
    Ok(values)
}

fn finite_domain_exprs(expr: &Expr, ctx: &SugarCtx) -> Result<Vec<Expr>, Effect> {
    let let_inits = BTreeMap::new();
    let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
    let seq = match build_composite(expr, &fcx).desugar(ctx) {
        Outcome::Complete(Desugared::Seq(seq)) => seq,
        Outcome::Complete(_) => {
            for_replay_construction_gap(
                "nested finite domain completed as a non-sequence floor".to_string(),
            );
        }
        Outcome::Incomplete(effect) => return Err(effect),
    };
    if seq.is_empty() || seq.len() > SUGAR_SEQ_CAP as usize {
        return Ok(Vec::new());
    }
    let mut values = Vec::with_capacity(seq.len());
    for elem in seq {
        let value = match elem.value.as_ref() {
            Some(ConstVal::Int(value)) => int_expr(*value).unwrap_or_else(|| {
                for_replay_construction_gap(format!(
                    "integer nested-domain element `{value}` did not reify to an expression"
                ))
            }),
            Some(ConstVal::PrimitiveInt { .. }) => elem
                .value
                .as_ref()
                .and_then(ConstVal::to_expr)
                .unwrap_or_else(|| {
                    for_replay_construction_gap(
                        "primitive integer nested-domain element did not reify to an expression"
                            .to_string(),
                    )
                }),
            Some(ConstVal::UInt128(value)) => u128_expr(*value).unwrap_or_else(|| {
                for_replay_construction_gap(format!(
                    "u128 nested-domain element `{value}` did not reify to an expression"
                ))
            }),
            _ => elem.expr,
        };
        values.push(value);
    }
    Ok(values)
}

fn replay_const_initializer_expr(item: &syn::ItemConst) -> Expr {
    let init = item.expr.as_ref();
    if replay_const_type_is_primitive_int(&item.ty) {
        let ty = item.ty.as_ref();
        syn::parse_quote!((#init) as #ty)
    } else {
        init.clone()
    }
}

fn replay_const_type_is_primitive_int(ty: &Type) -> bool {
    let Type::Path(path) = ty else {
        return false;
    };
    path.path.segments.last().is_some_and(|segment| {
        matches!(
            segment.ident.to_string().as_str(),
            "i8" | "i16"
                | "i32"
                | "i64"
                | "i128"
                | "isize"
                | "u8"
                | "u16"
                | "u32"
                | "u64"
                | "u128"
                | "usize"
        )
    })
}

fn expr_const_int(expr: &Expr, scope: &crate::TemporalScope) -> Option<i128> {
    if let Some(value) = exact_int_expr(expr) {
        return Some(value);
    }
    let term = translate_term_in_scope(expr, scope).ok()?;
    term_as_int(&term).or_else(|| const_fold_int_term(&term))
}

fn term_ground_expr(term: &Rc<Term>) -> Option<Expr> {
    if let Some(value) = const_fold_u128_term(term) {
        return u128_expr(value);
    }
    match term.as_ref() {
        Term::Const { value, sort } => match value {
            ConstValue::Int(n) if sort.name == "Int" => int_expr(*n),
            ConstValue::Int(n) if is_primitive_int_sort(&sort.name) => {
                syn::parse_str::<Expr>(&format!("{n}{}", sort.name)).ok()
            }
            ConstValue::Bool(value) => syn::parse_str::<Expr>(&value.to_string()).ok(),
            ConstValue::String(value) => syn::parse_str::<Expr>(&format!("{value:?}")).ok(),
            _ => None,
        },
        _ => None,
    }
}

fn is_primitive_int_sort(name: &str) -> bool {
    matches!(
        name,
        "i8" | "i16"
            | "i32"
            | "i64"
            | "i128"
            | "isize"
            | "u8"
            | "u16"
            | "u32"
            | "u64"
            | "u128"
            | "usize"
    )
}

fn exact_int_expr(expr: &Expr) -> Option<i128> {
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => literal_int(&lit.lit),
        Expr::Cast(cast) => exact_int_cast(&cast.expr, &cast.ty),
        Expr::Unary(unary) if matches!(unary.op, UnOp::Neg(_)) => {
            exact_int_expr(&unary.expr)?.checked_neg()
        }
        Expr::Binary(binary) => {
            let lhs = exact_int_expr(&binary.left)?;
            let rhs = exact_int_expr(&binary.right)?;
            match binary.op {
                BinOp::Add(_) => lhs.checked_add(rhs),
                BinOp::Sub(_) => lhs.checked_sub(rhs),
                BinOp::Mul(_) => lhs.checked_mul(rhs),
                BinOp::Div(_) => {
                    if rhs == 0 {
                        None
                    } else {
                        lhs.checked_div(rhs)
                    }
                }
                BinOp::Rem(_) => {
                    if rhs == 0 {
                        None
                    } else {
                        lhs.checked_rem(rhs)
                    }
                }
                BinOp::Shl(_) => u32::try_from(rhs)
                    .ok()
                    .and_then(|shift| lhs.checked_shl(shift)),
                BinOp::Shr(_) => u32::try_from(rhs)
                    .ok()
                    .and_then(|shift| lhs.checked_shr(shift)),
                BinOp::BitAnd(_) => Some(lhs & rhs),
                BinOp::BitOr(_) => Some(lhs | rhs),
                BinOp::BitXor(_) => Some(lhs ^ rhs),
                _ => None,
            }
        }
        _ => None,
    }
}

fn exact_int_cast(expr: &Expr, ty: &syn::Type) -> Option<i128> {
    let value = exact_int_expr(expr)?;
    let syn::Type::Path(path) = ty else {
        return None;
    };
    let name = path.path.segments.last()?.ident.to_string();
    match name.as_str() {
        "i8" => fits_signed(value, i8::MIN as i128, i8::MAX as i128),
        "i16" => fits_signed(value, i16::MIN as i128, i16::MAX as i128),
        "i32" => fits_signed(value, i32::MIN as i128, i32::MAX as i128),
        "i64" => fits_signed(value, i64::MIN as i128, i64::MAX as i128),
        "i128" => Some(value),
        "isize" => fits_signed(value, isize::MIN as i128, isize::MAX as i128),
        "u8" => fits_unsigned(value, u8::MAX as i128),
        "u16" => fits_unsigned(value, u16::MAX as i128),
        "u32" => fits_unsigned(value, u32::MAX as i128),
        "u64" => fits_unsigned(value, u64::MAX as i128),
        "u128" => (value >= 0).then_some(value),
        "usize" => fits_unsigned(value, usize::MAX as i128),
        _ => None,
    }
}

fn fits_signed(value: i128, min: i128, max: i128) -> Option<i128> {
    (min..=max).contains(&value).then_some(value)
}

fn fits_unsigned(value: i128, max: i128) -> Option<i128> {
    (0..=max).contains(&value).then_some(value)
}

fn int_expr(value: i128) -> Option<Expr> {
    syn::parse_str::<Expr>(&value.to_string()).ok()
}

fn literal_int(lit: &Lit) -> Option<i128> {
    match lit {
        Lit::Int(value) => crate::parse_int_lit(value).ok(),
        Lit::Byte(value) => Some(i128::from(value.value())),
        Lit::Char(value) => Some(i128::from(u32::from(value.value()))),
        _ => None,
    }
}

fn variant_call(expr: &Expr) -> Option<(String, Vec<Expr>)> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    Some((
        path_to_variant_string(&path.path),
        call.args.iter().cloned().collect(),
    ))
}

fn simple_path_name(expr: &Expr) -> Option<String> {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    path.path.get_ident().map(ToString::to_string)
}

fn count_asserts_in_expr_local(expr: &Expr) -> usize {
    let stmt = Stmt::Expr(expr.clone(), None);
    count_asserts_in_stmts(&[stmt])
}
