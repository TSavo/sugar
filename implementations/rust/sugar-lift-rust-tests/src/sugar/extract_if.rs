// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `ExtractIfSugar`: replay the stdlib `BTreeMap::extract_if(.., pred).for_each(drop)`
// state transition when the map was built from a finite literal integer-key iterator.
// This is a temporal stdlib axiom, not a general collection solver: exact readable
// construction -> replay, anything else -> decline.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, num, Formula, Term};
use syn::{BinOp, Expr, Lit, Pat, Stmt};

use crate::{
    parse_macro_args, strip_refs_groups, substitute_expr, term_as_int, translate_term_in_scope,
    ExprBindings, TemporalScope, SUGAR_SEQ_CAP,
};

pub(crate) enum ReplayAction<T> {
    Handled(T),
    NotMine,
}

#[derive(Clone, Default)]
pub(crate) struct ExtractIfSugar {
    maps: BTreeMap<String, MapState>,
}

#[derive(Clone)]
struct MapState {
    entries: BTreeMap<i128, Option<i128>>,
}

impl MapState {
    fn keys(&self) -> Vec<i128> {
        self.entries.keys().copied().collect()
    }

    fn len(&self) -> i128 {
        self.entries.len() as i128
    }
}

pub(crate) fn body_has_replay_shape(stmts: &[Stmt]) -> bool {
    let mut has_map = false;
    let mut has_extract_if = false;
    for stmt in stmts {
        match stmt {
            Stmt::Local(local) if btree_map_from_iter_arg(local).is_some() => {
                has_map = true;
            }
            Stmt::Expr(expr, _) if extract_if_for_each_drop(expr).is_some() => {
                has_extract_if = true;
            }
            _ => {}
        }
    }
    has_map && has_extract_if && stmts.iter().any(stmt_mentions_replay_assertion)
}

impl ExtractIfSugar {
    pub(crate) fn new() -> Self {
        Self::default()
    }

    pub(crate) fn replay_local(
        &mut self,
        local: &syn::Local,
        scope: &TemporalScope,
        bindings: &ExprBindings,
    ) -> Option<ReplayAction<()>> {
        let Some(source) = btree_map_from_iter_arg(local) else {
            return Some(ReplayAction::NotMine);
        };
        let Some(name) = simple_pat_binding(&local.pat) else {
            return None;
        };
        let entries = entries_from_iter_source(source, scope, bindings)?;
        self.maps.insert(name, MapState { entries });
        Some(ReplayAction::Handled(()))
    }

    pub(crate) fn replay_expr(
        &mut self,
        expr: &Expr,
        scope: &TemporalScope,
        bindings: &ExprBindings,
    ) -> Option<ReplayAction<()>> {
        let Some((map_name, pred)) = extract_if_for_each_drop(expr) else {
            return Some(ReplayAction::NotMine);
        };
        let map = self.maps.get_mut(&map_name)?;
        let keys = map.keys();
        for key in keys {
            let value = map.entries.get(&key).copied().flatten();
            if predicate_matches(pred, key, value, scope, bindings)? {
                map.entries.remove(&key);
            }
        }
        Some(ReplayAction::Handled(()))
    }

    pub(crate) fn constraint_for_macro(
        &self,
        mac: &syn::Macro,
        scope: &TemporalScope,
        bindings: &ExprBindings,
    ) -> Option<ReplayAction<Rc<Formula>>> {
        let name = mac.path.segments.last()?.ident.to_string();
        let args = parse_macro_args(mac.tokens.clone()).ok()?;
        match name.as_str() {
            "assert" | "debug_assert" => {
                let condition = args.exprs.first()?;
                if let Some((map_name, expected)) = keys_eq_range(condition, scope, bindings) {
                    let Some(map) = self.maps.get(&map_name) else {
                        return Some(ReplayAction::NotMine);
                    };
                    return Some(ReplayAction::Handled(sequence_eq_formula(
                        &map.keys(),
                        &expected,
                    )));
                }
                if let Some(map_name) = is_empty_expr(condition) {
                    let Some(map) = self.maps.get(&map_name) else {
                        return Some(ReplayAction::NotMine);
                    };
                    return Some(ReplayAction::Handled(eq(num(map.len()), num(0))));
                }
                Some(ReplayAction::NotMine)
            }
            "assert_eq" | "debug_assert_eq" => {
                if args.exprs.len() < 2 {
                    return None;
                }
                if let Some((map_name, expected)) =
                    len_eq(&args.exprs[0], &args.exprs[1], scope, bindings)
                {
                    let Some(map) = self.maps.get(&map_name) else {
                        return Some(ReplayAction::NotMine);
                    };
                    return Some(ReplayAction::Handled(eq(num(map.len()), num(expected))));
                }
                Some(ReplayAction::NotMine)
            }
            _ => Some(ReplayAction::NotMine),
        }
    }
}

fn stmt_mentions_replay_assertion(stmt: &Stmt) -> bool {
    match stmt {
        Stmt::Macro(stmt_macro) => macro_mentions_replay_assertion(&stmt_macro.mac),
        Stmt::Expr(Expr::Macro(expr_macro), _) => macro_mentions_replay_assertion(&expr_macro.mac),
        _ => false,
    }
}

fn macro_mentions_replay_assertion(mac: &syn::Macro) -> bool {
    let Some(name) = mac
        .path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
    else {
        return false;
    };
    let Ok(args) = parse_macro_args(mac.tokens.clone()) else {
        return false;
    };
    match name.as_str() {
        "assert" | "debug_assert" => args
            .exprs
            .first()
            .is_some_and(|expr| keys_eq_range_shape(expr) || is_empty_expr(expr).is_some()),
        "assert_eq" | "debug_assert_eq" if args.exprs.len() >= 2 => {
            len_eq_shape(&args.exprs[0], &args.exprs[1])
        }
        _ => false,
    }
}

fn btree_map_from_iter_arg(local: &syn::Local) -> Option<&Expr> {
    let init = local.init.as_ref().filter(|init| init.diverge.is_none())?;
    let Expr::Call(call) = strip_refs_groups(&init.expr) else {
        return None;
    };
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    if call.args.len() != 1 {
        return None;
    }
    let mut saw_btree = false;
    let mut saw_from_iter = false;
    for segment in &path.path.segments {
        if segment.ident == "BTreeMap" {
            saw_btree = true;
        }
        if segment.ident == "from_iter" {
            saw_from_iter = true;
        }
    }
    if saw_btree && saw_from_iter {
        call.args.first()
    } else {
        None
    }
}

fn entries_from_iter_source(
    source: &Expr,
    scope: &TemporalScope,
    bindings: &ExprBindings,
) -> Option<BTreeMap<i128, Option<i128>>> {
    let source = resolve_iter_source(source, scope, bindings)?;
    let Expr::MethodCall(map_call) = strip_refs_groups(&source) else {
        return None;
    };
    if map_call.method != "map" || map_call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(closure) = strip_refs_groups(&map_call.args[0]) else {
        return None;
    };
    let param = closure_single_param(&closure.inputs)?;
    let domain = finite_range_values(&map_call.receiver, scope, bindings)?;
    let mut entries = BTreeMap::new();
    for value in domain {
        let mut env = bindings.clone();
        env.insert(param.clone(), int_expr(value)?);
        let Expr::Tuple(tuple) = strip_refs_groups(&closure.body) else {
            return None;
        };
        if tuple.elems.len() != 2 {
            return None;
        }
        let key = expr_const_int(&tuple.elems[0], scope, &env)?;
        let val = expr_const_int(&tuple.elems[1], scope, &env);
        entries.insert(key, val);
    }
    Some(entries)
}

fn resolve_iter_source(
    source: &Expr,
    scope: &TemporalScope,
    bindings: &ExprBindings,
) -> Option<Expr> {
    let substituted = substitute_expr(source, bindings);
    if let Some(inner) = clone_receiver(&substituted) {
        if let Some(name) = simple_path_name(inner) {
            if let Some(bound) = scope.replayable_let_binding_for_source(&name) {
                return Some(substitute_expr(bound, bindings));
            }
        }
        return resolve_iter_source(inner, scope, bindings);
    }
    if let Some(name) = simple_path_name(&substituted) {
        if let Some(bound) = scope.stable_let_binding_for_term(&name) {
            return Some(substitute_expr(bound, bindings));
        }
    }
    Some(substituted)
}

fn clone_receiver(expr: &Expr) -> Option<&Expr> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.method == "clone" && call.args.is_empty() {
        Some(&call.receiver)
    } else {
        None
    }
}

fn extract_if_for_each_drop(expr: &Expr) -> Option<(String, &syn::ExprClosure)> {
    let Expr::MethodCall(for_each) = strip_refs_groups(expr) else {
        return None;
    };
    if for_each.method != "for_each" || for_each.args.len() != 1 {
        return None;
    }
    if !is_drop_arg(&for_each.args[0]) {
        return None;
    }
    let Expr::MethodCall(extract_if) = strip_refs_groups(&for_each.receiver) else {
        return None;
    };
    if extract_if.method != "extract_if" || extract_if.args.len() != 2 {
        return None;
    }
    if !is_full_range(&extract_if.args[0]) {
        return None;
    }
    let map_name = simple_path_name(&extract_if.receiver)?;
    let Expr::Closure(pred) = strip_refs_groups(&extract_if.args[1]) else {
        return None;
    };
    Some((map_name, pred))
}

fn predicate_matches(
    pred: &syn::ExprClosure,
    key: i128,
    value: Option<i128>,
    scope: &TemporalScope,
    bindings: &ExprBindings,
) -> Option<bool> {
    if pred.inputs.len() != 2 {
        return None;
    }
    let mut env = bindings.clone();
    bind_extract_if_param(&mut env, &pred.inputs[0], key)?;
    bind_extract_if_value_param(&mut env, &pred.inputs[1], value)?;
    expr_const_bool(&pred.body, scope, &env)
}

fn bind_extract_if_param(env: &mut ExprBindings, pat: &Pat, value: i128) -> Option<()> {
    match strip_pat(pat) {
        Pat::Ident(ident) if ident.subpat.is_none() => {
            env.insert(ident.ident.to_string(), int_expr(value)?);
            Some(())
        }
        Pat::Wild(_) => Some(()),
        Pat::Reference(reference) => bind_extract_if_param(env, &reference.pat, value),
        Pat::Type(typed) => bind_extract_if_param(env, &typed.pat, value),
        _ => None,
    }
}

fn bind_extract_if_value_param(
    env: &mut ExprBindings,
    pat: &Pat,
    value: Option<i128>,
) -> Option<()> {
    match strip_pat(pat) {
        Pat::Ident(ident) if ident.subpat.is_none() => {
            env.insert(ident.ident.to_string(), int_expr(value?)?);
            Some(())
        }
        Pat::Wild(_) => Some(()),
        Pat::Reference(reference) => bind_extract_if_value_param(env, &reference.pat, value),
        Pat::Type(typed) => bind_extract_if_value_param(env, &typed.pat, value),
        _ => None,
    }
}

fn keys_eq_range(
    expr: &Expr,
    scope: &TemporalScope,
    bindings: &ExprBindings,
) -> Option<(String, Vec<i128>)> {
    let Expr::MethodCall(eq_call) = strip_refs_groups(expr) else {
        return None;
    };
    if eq_call.method != "eq" || eq_call.args.len() != 1 {
        return None;
    }
    let map_name = keys_receiver_name(&eq_call.receiver)?;
    let expected = finite_range_values(&eq_call.args[0], scope, bindings)?;
    Some((map_name, expected))
}

fn keys_eq_range_shape(expr: &Expr) -> bool {
    let Expr::MethodCall(eq_call) = strip_refs_groups(expr) else {
        return false;
    };
    eq_call.method == "eq"
        && eq_call.args.len() == 1
        && keys_receiver_name(&eq_call.receiver).is_some()
        && matches!(strip_refs_groups(&eq_call.args[0]), Expr::Range(_))
}

fn keys_receiver_name(expr: &Expr) -> Option<String> {
    let expr = strip_identity_key_adaptors(expr);
    let Expr::MethodCall(keys) = strip_refs_groups(expr) else {
        return None;
    };
    if keys.method != "keys" || !keys.args.is_empty() {
        return None;
    }
    simple_path_name(&keys.receiver)
}

fn strip_identity_key_adaptors(expr: &Expr) -> &Expr {
    match strip_refs_groups(expr) {
        Expr::MethodCall(call)
            if call.args.is_empty()
                && matches!(call.method.to_string().as_str(), "copied" | "cloned") =>
        {
            strip_identity_key_adaptors(&call.receiver)
        }
        other => other,
    }
}

fn is_empty_expr(expr: &Expr) -> Option<String> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.method == "is_empty" && call.args.is_empty() {
        simple_path_name(&call.receiver)
    } else {
        None
    }
}

fn len_eq(
    lhs: &Expr,
    rhs: &Expr,
    scope: &TemporalScope,
    bindings: &ExprBindings,
) -> Option<(String, i128)> {
    if let Some(map_name) = len_receiver_name(lhs) {
        return Some((map_name, expr_const_int(rhs, scope, bindings)?));
    }
    if let Some(map_name) = len_receiver_name(rhs) {
        return Some((map_name, expr_const_int(lhs, scope, bindings)?));
    }
    None
}

fn len_eq_shape(lhs: &Expr, rhs: &Expr) -> bool {
    len_receiver_name(lhs).is_some() || len_receiver_name(rhs).is_some()
}

fn len_receiver_name(expr: &Expr) -> Option<String> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.method == "len" && call.args.is_empty() {
        simple_path_name(&call.receiver)
    } else {
        None
    }
}

fn sequence_eq_formula(actual: &[i128], expected: &[i128]) -> Rc<Formula> {
    let mut atoms = vec![eq(num(actual.len() as i128), num(expected.len() as i128))];
    for (left, right) in actual.iter().zip(expected.iter()) {
        atoms.push(eq(num(*left), num(*right)));
    }
    and_(atoms)
}

fn finite_range_values(
    expr: &Expr,
    scope: &TemporalScope,
    bindings: &ExprBindings,
) -> Option<Vec<i128>> {
    let substituted = substitute_expr(expr, bindings);
    let Expr::Range(range) = strip_refs_groups(&substituted) else {
        return None;
    };
    let start = range
        .start
        .as_ref()
        .map(|expr| expr_const_int(expr, scope, bindings))
        .unwrap_or(Some(0))?;
    let end = expr_const_int(range.end.as_ref()?, scope, bindings)?;
    let high = if matches!(range.limits, syn::RangeLimits::Closed(_)) {
        end.checked_add(1)?
    } else {
        end
    };
    if high < start || high - start > i128::from(SUGAR_SEQ_CAP) {
        return None;
    }
    Some((start..high).collect())
}

fn expr_const_bool(expr: &Expr, scope: &TemporalScope, bindings: &ExprBindings) -> Option<bool> {
    let substituted = substitute_expr(expr, bindings);
    match strip_refs_groups(&substituted) {
        Expr::Lit(lit) => match &lit.lit {
            Lit::Bool(value) => Some(value.value),
            _ => None,
        },
        Expr::Unary(unary) if matches!(unary.op, syn::UnOp::Not(_)) => {
            expr_const_bool(&unary.expr, scope, bindings).map(|value| !value)
        }
        Expr::Binary(binary) => match binary.op {
            BinOp::And(_) | BinOp::BitAnd(_) => Some(
                expr_const_bool(&binary.left, scope, bindings)?
                    && expr_const_bool(&binary.right, scope, bindings)?,
            ),
            BinOp::Or(_) | BinOp::BitOr(_) => Some(
                expr_const_bool(&binary.left, scope, bindings)?
                    || expr_const_bool(&binary.right, scope, bindings)?,
            ),
            BinOp::Eq(_) => Some(
                expr_const_int(&binary.left, scope, bindings)?
                    == expr_const_int(&binary.right, scope, bindings)?,
            ),
            BinOp::Ne(_) => Some(
                expr_const_int(&binary.left, scope, bindings)?
                    != expr_const_int(&binary.right, scope, bindings)?,
            ),
            BinOp::Lt(_) => Some(
                expr_const_int(&binary.left, scope, bindings)?
                    < expr_const_int(&binary.right, scope, bindings)?,
            ),
            BinOp::Le(_) => Some(
                expr_const_int(&binary.left, scope, bindings)?
                    <= expr_const_int(&binary.right, scope, bindings)?,
            ),
            BinOp::Gt(_) => Some(
                expr_const_int(&binary.left, scope, bindings)?
                    > expr_const_int(&binary.right, scope, bindings)?,
            ),
            BinOp::Ge(_) => Some(
                expr_const_int(&binary.left, scope, bindings)?
                    >= expr_const_int(&binary.right, scope, bindings)?,
            ),
            _ => None,
        },
        _ => None,
    }
}

fn expr_const_int(expr: &Expr, scope: &TemporalScope, bindings: &ExprBindings) -> Option<i128> {
    let substituted = substitute_expr(expr, bindings);
    match strip_refs_groups(&substituted) {
        Expr::Unary(unary) if matches!(unary.op, syn::UnOp::Deref(_)) => {
            expr_const_int(&unary.expr, scope, bindings)
        }
        Expr::Unary(unary) if matches!(unary.op, syn::UnOp::Neg(_)) => {
            expr_const_int(&unary.expr, scope, bindings)?.checked_neg()
        }
        Expr::Binary(binary) => {
            let lhs = expr_const_int(&binary.left, scope, bindings)?;
            let rhs = expr_const_int(&binary.right, scope, bindings)?;
            match binary.op {
                BinOp::Add(_) => lhs.checked_add(rhs),
                BinOp::Sub(_) => lhs.checked_sub(rhs),
                BinOp::Mul(_) => lhs.checked_mul(rhs),
                BinOp::Div(_) if rhs != 0 => lhs.checked_div(rhs),
                BinOp::Rem(_) if rhs != 0 => lhs.checked_rem(rhs),
                _ => None,
            }
        }
        _ => {
            let term = translate_term_in_scope(&substituted, scope).ok()?;
            term_as_int(&term).or_else(|| const_fold_int_term(&term))
        }
    }
}

fn const_fold_int_term(term: &Rc<Term>) -> Option<i128> {
    crate::const_fold_int_term(term)
}

fn int_expr(value: i128) -> Option<Expr> {
    syn::parse_str::<Expr>(&value.to_string()).ok()
}

fn is_drop_arg(expr: &Expr) -> bool {
    simple_path_name(expr).is_some_and(|name| name == "drop")
}

fn is_full_range(expr: &Expr) -> bool {
    matches!(strip_refs_groups(expr), Expr::Range(range) if range.start.is_none() && range.end.is_none())
}

fn simple_pat_binding(pat: &Pat) -> Option<String> {
    match strip_pat(pat) {
        Pat::Ident(ident) if ident.by_ref.is_none() && ident.subpat.is_none() => {
            Some(ident.ident.to_string())
        }
        Pat::Type(typed) => simple_pat_binding(&typed.pat),
        Pat::Paren(paren) => simple_pat_binding(&paren.pat),
        _ => None,
    }
}

fn closure_single_param(
    inputs: &syn::punctuated::Punctuated<Pat, syn::Token![,]>,
) -> Option<String> {
    if inputs.len() != 1 {
        return None;
    }
    match strip_pat(inputs.first()?) {
        Pat::Ident(ident) if ident.subpat.is_none() => Some(ident.ident.to_string()),
        Pat::Reference(reference) => match strip_pat(&reference.pat) {
            Pat::Ident(ident) if ident.subpat.is_none() => Some(ident.ident.to_string()),
            _ => None,
        },
        Pat::Type(typed) => {
            let mut typed_inputs = syn::punctuated::Punctuated::new();
            typed_inputs.push((*typed.pat).clone());
            closure_single_param(&typed_inputs)
        }
        _ => None,
    }
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

fn strip_pat(pat: &Pat) -> &Pat {
    match pat {
        Pat::Type(typed) => strip_pat(&typed.pat),
        Pat::Paren(paren) => strip_pat(&paren.pat),
        _ => pat,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{TemporalPlan, TemporalScope};

    #[test]
    fn untracked_len_assertion_declines_so_replay_can_use_the_constraint_floor() {
        let expr: Expr =
            syn::parse_str("assert_eq!(prefix.len(), case.len() - pos)").expect("parse assert_eq");
        let Expr::Macro(expr_macro) = expr else {
            panic!("test source must parse as a macro expression");
        };
        let scope = TemporalScope::new("extract-if-side-door-test", TemporalPlan::default());
        let bindings = ExprBindings::new();
        let sugar = ExtractIfSugar::new();

        match sugar.constraint_for_macro(&expr_macro.mac, &scope, &bindings) {
            Some(ReplayAction::NotMine) => {}
            Some(ReplayAction::Handled(_)) => {
                panic!(
                    "extract_if must not claim ordinary len assertions; \
                     for_replay should delegate them to the normal constraint floor"
                );
            }
            None => {
                panic!(
                    "extract_if must return NotMine, not None, when a len-shaped assertion \
                     has no tracked map state; None blocks the normal assertion floor"
                );
            }
        }
    }
}
