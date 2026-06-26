// SPDX-License-Identifier: Apache-2.0
//
// `InsertSugar`: replay `BTreeMap::insert(k, v)` presence semantics when the map
// was built from a finite literal integer-key iterator. The returned Option is
// scalarized for `is_none`/`is_some` assertions, and the replayed map is mutated.

use std::collections::{BTreeMap, BTreeSet};
use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, ConstValue, Formula, Sort, Term};
use syn::{BinOp, Expr, Pat, Stmt};

use crate::sugar::extract_if::ReplayAction;
use crate::{
    const_fold_int_term, parse_macro_args, strip_refs_groups, substitute_expr, term_as_int,
    translate_term_in_scope, ExprBindings, TemporalScope, SUGAR_SEQ_CAP,
};

#[derive(Clone, Default)]
pub(crate) struct InsertSugar {
    maps: BTreeMap<String, MapState>,
}

#[derive(Clone, Default)]
struct MapState {
    keys: BTreeSet<i128>,
    insert_step: usize,
}

pub(crate) fn body_has_replay_shape(stmts: &[Stmt]) -> bool {
    let mut has_map = false;
    let mut has_insert_assertion = false;
    for stmt in stmts {
        match stmt {
            Stmt::Local(local) if btree_map_from_iter_arg(local).is_some() => {
                has_map = true;
            }
            Stmt::Macro(stmt_macro) => {
                has_insert_assertion |= macro_mentions_insert_assertion(&stmt_macro.mac);
            }
            Stmt::Expr(Expr::Macro(expr_macro), _) => {
                has_insert_assertion |= macro_mentions_insert_assertion(&expr_macro.mac);
            }
            _ => {}
        }
    }
    has_map && has_insert_assertion
}

impl InsertSugar {
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
        let keys = keys_from_iter_source(source, scope, bindings)?;
        self.maps.insert(
            name,
            MapState {
                keys,
                insert_step: 0,
            },
        );
        Some(ReplayAction::Handled(()))
    }

    pub(crate) fn replay_expr(
        &mut self,
        expr: &Expr,
        scope: &TemporalScope,
        bindings: &ExprBindings,
    ) -> Option<ReplayAction<()>> {
        let Some((map_name, key_expr)) = insert_call(expr) else {
            return Some(ReplayAction::NotMine);
        };
        let key = expr_const_int(key_expr, scope, bindings)?;
        let map = self.maps.get_mut(&map_name)?;
        map.insert_step = map.insert_step.checked_add(1)?;
        map.keys.insert(key);
        Some(ReplayAction::Handled(()))
    }

    pub(crate) fn constraint_for_macro(
        &mut self,
        mac: &syn::Macro,
        scope: &TemporalScope,
        local_scope: &str,
        bindings: &ExprBindings,
    ) -> Option<ReplayAction<Rc<Formula>>> {
        let name = mac.path.segments.last()?.ident.to_string();
        if !matches!(name.as_str(), "assert" | "debug_assert") {
            return Some(ReplayAction::NotMine);
        }
        let args = parse_macro_args(mac.tokens.clone()).ok()?;
        let condition = args.exprs.first()?;
        let Some((map_name, key_expr, expected_none)) = insert_option_check(condition) else {
            return Some(ReplayAction::NotMine);
        };
        let key = expr_const_int(key_expr, scope, bindings)?;
        let Some(map) = self.maps.get_mut(&map_name) else {
            return Some(ReplayAction::NotMine);
        };
        let was_absent = !map.keys.contains(&key);
        map.insert_step = map.insert_step.checked_add(1)?;
        let term = temporal_insert_predicate_term(
            local_scope,
            &map_name,
            key,
            map.insert_step,
            expected_none,
        );
        map.keys.insert(key);
        let actual = if expected_none {
            was_absent
        } else {
            !was_absent
        };
        Some(ReplayAction::Handled(and_(vec![
            eq(term.clone(), bool_term(actual)),
            eq(term, bool_term(true)),
        ])))
    }
}

fn macro_mentions_insert_assertion(mac: &syn::Macro) -> bool {
    let Some(name) = mac
        .path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
    else {
        return false;
    };
    if !matches!(name.as_str(), "assert" | "debug_assert") {
        return false;
    }
    let Ok(args) = parse_macro_args(mac.tokens.clone()) else {
        return false;
    };
    args.exprs
        .first()
        .is_some_and(|expr| insert_option_check(expr).is_some())
}

fn insert_option_check(expr: &Expr) -> Option<(String, &Expr, bool)> {
    let Expr::MethodCall(check) = strip_refs_groups(expr) else {
        return None;
    };
    if !check.args.is_empty() {
        return None;
    }
    let expected_none = match check.method.to_string().as_str() {
        "is_none" => true,
        "is_some" => false,
        _ => return None,
    };
    let (map_name, key) = insert_call(&check.receiver)?;
    Some((map_name, key, expected_none))
}

fn insert_call(expr: &Expr) -> Option<(String, &Expr)> {
    let Expr::MethodCall(insert) = strip_refs_groups(expr) else {
        return None;
    };
    if insert.method != "insert" || insert.args.len() != 2 {
        return None;
    }
    let map_name = simple_path_name(&insert.receiver)?;
    Some((map_name, &insert.args[0]))
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

fn keys_from_iter_source(
    source: &Expr,
    scope: &TemporalScope,
    bindings: &ExprBindings,
) -> Option<BTreeSet<i128>> {
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
    let mut keys = BTreeSet::new();
    for value in domain {
        let mut env = bindings.clone();
        env.insert(param.clone(), int_expr(value)?);
        let Expr::Tuple(tuple) = strip_refs_groups(&closure.body) else {
            return None;
        };
        if tuple.elems.len() != 2 {
            return None;
        }
        keys.insert(expr_const_int(&tuple.elems[0], scope, &env)?);
    }
    Some(keys)
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

fn bool_term(value: bool) -> Rc<Term> {
    Rc::new(Term::Const {
        value: ConstValue::Bool(value),
        sort: Sort::bool(),
    })
}

fn temporal_insert_predicate_term(
    local_scope: &str,
    map_name: &str,
    key: i128,
    step: usize,
    expected_none: bool,
) -> Rc<Term> {
    let predicate = if expected_none { "is_none" } else { "is_some" };
    Rc::new(Term::Ctor {
        name: format!(
            "temporal:{}_{}_insert_{}_{}_{}",
            safe_fragment(local_scope),
            safe_fragment(map_name),
            int_fragment(key),
            step,
            predicate
        ),
        args: Vec::new(),
    })
}

fn safe_fragment(value: &str) -> String {
    value
        .chars()
        .map(|ch| if ch.is_ascii_alphanumeric() { ch } else { '_' })
        .collect()
}

fn int_fragment(value: i128) -> String {
    if value < 0 {
        format!("neg{}", value.saturating_abs())
    } else {
        value.to_string()
    }
}

fn int_expr(value: i128) -> Option<Expr> {
    syn::parse_str::<Expr>(&value.to_string()).ok()
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
    fn untracked_insert_assertion_declines_so_replay_can_use_the_constraint_floor() {
        let expr: Expr =
            syn::parse_str("assert!(map.insert(1, 2).is_none())").expect("parse assert");
        let Expr::Macro(expr_macro) = expr else {
            panic!("test source must parse as a macro expression");
        };
        let scope = TemporalScope::new("insert-side-door-test", TemporalPlan::default());
        let bindings = ExprBindings::new();
        let mut sugar = InsertSugar::new();

        match sugar.constraint_for_macro(&expr_macro.mac, &scope, "insert-test", &bindings) {
            Some(ReplayAction::NotMine) => {}
            Some(ReplayAction::Handled(_)) => {
                panic!(
                    "insert must not claim assertions for maps it did not construct; \
                     for_replay should delegate ordinary assertions to the constraint floor"
                );
            }
            None => {
                panic!(
                    "insert must return NotMine, not None, when an insert-shaped assertion \
                     has no tracked map state; None blocks the normal assertion floor"
                );
            }
        }
    }
}
