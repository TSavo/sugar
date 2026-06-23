// SPDX-License-Identifier: Apache-2.0
//
// `AssignOpSugar`: temporal rewrite sugar for literal-backed state transitions.
//
// This owns statement shapes such as `x += 1`, `v[0] += 10`, and `*a += 100`
// when the receiver is already pinned to a literal value by the current
// `TemporalScope`. The statement itself is inert support; its meaning is that
// later path reads resolve through the rewritten source value.

use std::collections::{BTreeMap, BTreeSet};
use std::rc::Rc;

use sugar_ir_symbolic::{eq, ConstValue, Sort, Term};
use syn::{BinOp, Expr, Lit, Pat, RangeLimits, Stmt, UnOp};
use tracing::{debug, trace};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::{
    const_int, parse_int_lit, parse_macro_args, simple_path_name, strip_refs_groups, token_key,
    AssertionFactKind, Desugared, Outcome, Sugar, SugarCtx, Warrant,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("temporal_assign_op", SugarRole::Constraint, recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    fcx.scope()
        .temporal_rewrite_can_apply(expr)
        .then(|| Box::new(AssignOpSugar { expr: expr.clone() }) as Box<dyn Sugar>)
}

struct AssignOpSugar {
    expr: Expr,
}

impl Sugar for AssignOpSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if !ctx.scope.apply_temporal_rewrite(&self.expr) {
            return Outcome::from_opt(None);
        }
        Outcome::Complete(Desugared::Constraints {
            atom: eq(bool_term(true), bool_term(true)),
            n: 0,
            kind: AssertionFactKind::Support,
            warrant: Warrant {
                name: Some(format!(
                    "{}::temporal-rewrite::{}",
                    ctx.scope.local_scope(),
                    token_key(&self.expr)
                )),
            },
        })
    }
}

#[derive(Clone, Debug, Default)]
pub(crate) struct TemporalRewriteState {
    values: BTreeMap<String, Expr>,
    aliases: BTreeMap<String, RewritePlace>,
    cell_values: BTreeMap<String, CellState>,
    unknown_consumed_iterators: BTreeMap<String, String>,
    unknown_mutations: BTreeMap<String, String>,
    exhausted_iterators: BTreeSet<String>,
    rewritten_bases: BTreeSet<String>,
    loop_replayed: BTreeSet<String>,
}

pub(crate) const CELL_RUNTIME_ALIASED_REASON: &str =
    "cell value runtime/aliased, not literal-pinned";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum CellKind {
    Cell,
    RefCell,
}

#[derive(Clone, Debug)]
struct CellState {
    kind: CellKind,
    value: Option<Expr>,
    reason: Option<String>,
}

#[derive(Clone, Debug)]
enum RewritePlace {
    Scalar(String),
    Element {
        base: String,
        index: usize,
    },
    Slice {
        base: String,
        start: usize,
        len: usize,
    },
}

#[derive(Clone, Debug)]
enum Target {
    Scalar(String),
    Element {
        base: String,
        index: usize,
        replayable_alias: bool,
    },
}

#[derive(Clone, Copy, Debug)]
enum AggregateKind {
    Array,
    VecMacro,
}

#[derive(Clone, Copy, Debug)]
enum IndexSpec {
    Element(usize),
    Slice { start: usize, len: usize },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum LoopStep {
    Fallthrough,
    Continue,
    Break,
}

const LOOP_REPLAY_CAP: usize = 256;

impl TemporalRewriteState {
    pub(crate) fn expr_for(&self, name: &str) -> Option<Expr> {
        if self.unknown_consumed_iterators.contains_key(name)
            || self.unknown_mutations.contains_key(name)
        {
            return None;
        }
        if let Some(expr) = self.values.get(name) {
            return Some(expr.clone());
        }
        if self.exhausted_iterators.contains(name) {
            return Some(syn::parse_quote!([].iter()));
        }
        match self.aliases.get(name)? {
            RewritePlace::Scalar(base)
                if !self.unknown_consumed_iterators.contains_key(base)
                    && !self.unknown_mutations.contains_key(base) =>
            {
                self.values.get(base).cloned()
            }
            RewritePlace::Element { base, index }
                if !self.unknown_consumed_iterators.contains_key(base)
                    && !self.unknown_mutations.contains_key(base) =>
            {
                self.aggregate_element(base, *index)
            }
            RewritePlace::Scalar(_) | RewritePlace::Element { .. } => None,
            RewritePlace::Slice { .. } => None,
        }
    }

    pub(crate) fn expr_for_index(&self, name: &str, index: usize) -> Option<Expr> {
        if self.unknown_consumed_iterators.contains_key(name)
            || self.unknown_mutations.contains_key(name)
        {
            return None;
        }
        if self.values.contains_key(name) && self.rewritten_bases.contains(name) {
            return self.aggregate_element(name, index);
        }
        match self.aliases.get(name)? {
            RewritePlace::Scalar(base)
                if self.rewritten_bases.contains(base)
                    && !self.unknown_consumed_iterators.contains_key(base)
                    && !self.unknown_mutations.contains_key(base) =>
            {
                self.aggregate_element(base, index)
            }
            RewritePlace::Slice { base, start, len }
                if index < *len
                    && self.rewritten_bases.contains(base)
                    && !self.unknown_consumed_iterators.contains_key(base)
                    && !self.unknown_mutations.contains_key(base) =>
            {
                self.aggregate_element(base, start.checked_add(index)?)
            }
            RewritePlace::Element { .. } | RewritePlace::Scalar(_) | RewritePlace::Slice { .. } => {
                None
            }
        }
    }

    pub(crate) fn unknown_iterator_consumption_reason(&self, name: &str) -> Option<String> {
        let method = self.unknown_consumed_iterators.get(name)?;
        Some(format!(
            "unknown iterator consumption for `{name}` via `{method}`: a prior iterator \
             operation advanced this mutable iterator by an unknown or by_ref-adaptor \
             count, so there is no single timeless source value to read at the assertion; \
             refused"
        ))
    }

    pub(crate) fn unknown_mutation_reason(&self, name: &str) -> Option<String> {
        self.unknown_mutations.get(name).cloned()
    }

    pub(crate) fn cell_kind(&self, name: &str) -> Option<CellKind> {
        self.cell_values.get(name).map(|state| state.kind)
    }

    pub(crate) fn cell_value_expr(
        &self,
        name: &str,
        kind: CellKind,
    ) -> Result<Option<Expr>, String> {
        let Some(state) = self.cell_values.get(name) else {
            return Ok(None);
        };
        if state.kind != kind {
            return Ok(None);
        }
        match &state.value {
            Some(value) => Ok(Some(value.clone())),
            None => Err(state
                .reason
                .clone()
                .unwrap_or_else(|| CELL_RUNTIME_ALIASED_REASON.to_string())),
        }
    }

    pub(crate) fn exact_loop_replayed(&self, name: &str) -> bool {
        self.loop_replayed.contains(name) && self.expr_for(name).is_some()
    }

    pub(crate) fn mark_loop_replayed(&mut self, name: &str) {
        if self.expr_for(name).is_some() {
            self.loop_replayed.insert(name.to_string());
        }
    }

    pub(crate) fn clear_loop_replayed(&mut self, name: &str) {
        self.loop_replayed.remove(name);
    }

    pub(crate) fn can_apply(&self, expr: &Expr) -> bool {
        let mut scratch = self.clone();
        scratch.apply_with_trace(expr, false)
    }

    pub(crate) fn apply(&mut self, expr: &Expr) -> bool {
        self.apply_with_trace(expr, true)
    }

    pub(crate) fn expr_bindings(&self) -> BTreeMap<String, Expr> {
        let mut out: BTreeMap<String, Expr> = self
            .values
            .iter()
            .filter(|(name, _)| {
                !self.unknown_consumed_iterators.contains_key(*name)
                    && !self.unknown_mutations.contains_key(*name)
            })
            .map(|(name, expr)| (name.clone(), expr.clone()))
            .collect();
        for name in self.aliases.keys() {
            if let Some(expr) = self.expr_for(name) {
                out.insert(name.clone(), expr);
            }
        }
        out
    }

    pub(crate) fn apply_statement(&mut self, stmt: &Stmt) -> bool {
        match stmt {
            Stmt::Local(local) => local
                .init
                .as_ref()
                .filter(|init| init.diverge.is_none())
                .is_some_and(|init| {
                    // Exact literal `get_disjoint_mut` aliases are the replay ledger,
                    // not an opaque mutable-view escape: the writes through those
                    // aliases are applied back to the tracked base below.
                    let captured_disjoint_aliases =
                        self.record_get_disjoint_mut_aliases(&local.pat, &init.expr);
                    let mut applied = captured_disjoint_aliases;
                    if !captured_disjoint_aliases {
                        applied |= self.apply_consumption_expr(&init.expr);
                    }
                    if let Some(base) = borrowed_iterator_source_name(&init.expr).filter(|base| {
                        simple_pat_binding(&local.pat).as_ref() != Some(base)
                            && self.values.contains_key(base)
                    }) {
                        applied |= self.invalidate_iterator_binding(&base, "by_ref");
                    }
                    applied
                }),
            Stmt::Expr(expr, _) => self.apply_consumption_expr(expr),
            Stmt::Macro(stmt_macro) => self.apply_consumption_macro(&stmt_macro.mac),
            _ => false,
        }
    }

    fn apply_with_trace(&mut self, expr: &Expr, emit_trace: bool) -> bool {
        match strip_refs_groups(expr) {
            Expr::Assign(assign) => {
                self.apply_refcell_borrow_mut_assign(&assign.left, &assign.right, emit_trace)
                    || self.apply_assign(&assign.left, &assign.right, emit_trace)
            }
            Expr::Binary(binary) if assignment_op(&binary.op).is_some() => {
                self.apply_compound_assign(binary, emit_trace)
            }
            _ => false,
        }
    }

    fn apply_consumption_macro(&mut self, mac: &syn::Macro) -> bool {
        let Ok(args) = parse_macro_args(mac.tokens.clone()) else {
            return false;
        };
        let mut applied = false;
        for expr in &args.exprs {
            applied |= self.apply_consumption_expr(expr);
        }
        applied
    }

    fn apply_consumption_expr(&mut self, expr: &Expr) -> bool {
        match strip_refs_groups(expr) {
            Expr::MethodCall(call) => {
                let mut applied = self.apply_consumption_expr(&call.receiver);
                for arg in &call.args {
                    applied |= self.apply_consumption_expr(arg);
                }
                let handled_cell_set = self.apply_cell_set(call);
                applied |= handled_cell_set;
                if !handled_cell_set && mutable_view_method(&call.method.to_string()) {
                    if let Some(name) = simple_path_name(&call.receiver) {
                        applied |= self.invalidate_mutable_view(&name, &call.method.to_string());
                    }
                }
                if !handled_cell_set && mutating_receiver_method(&call.method.to_string()) {
                    if let Some(name) = simple_path_name(&call.receiver) {
                        applied |=
                            self.invalidate_mutating_receiver(&name, &call.method.to_string());
                    }
                }
                if let Some((direction, count)) = iterator_consumption(call) {
                    if let Some(name) = simple_path_name(&call.receiver) {
                        applied |= self.advance_iterator_binding(&name, direction, count);
                    }
                } else if unknown_iterator_consumption(call) {
                    if let Some(name) = simple_path_name(&call.receiver) {
                        applied |=
                            self.invalidate_iterator_binding(&name, &call.method.to_string());
                    }
                }
                if borrowed_iterator_terminal(call) {
                    if let Some(name) = full_drain_borrowed_iterator_terminal_source(call) {
                        if !self.exhaust_iterator_binding(&name, &call.method.to_string()) {
                            applied |=
                                self.invalidate_iterator_binding(&name, &call.method.to_string());
                        } else {
                            applied = true;
                        }
                    } else if let Some(name) = borrowed_iterator_source_name(&call.receiver) {
                        applied |=
                            self.invalidate_iterator_binding(&name, &call.method.to_string());
                    }
                }
                applied
            }
            Expr::Call(call) => {
                let mut applied = false;
                for arg in &call.args {
                    applied |= self.apply_consumption_expr(arg);
                    let site = token_key(&call.func);
                    for name in mut_reference_targets(arg) {
                        applied |= self.invalidate_opaque_mut_borrow_call(&name, &site);
                    }
                }
                applied
            }
            Expr::Macro(expr_macro) => self.apply_consumption_macro(&expr_macro.mac),
            Expr::Reference(reference) => self.apply_consumption_expr(&reference.expr),
            Expr::Paren(paren) => self.apply_consumption_expr(&paren.expr),
            Expr::Group(group) => self.apply_consumption_expr(&group.expr),
            Expr::Try(try_expr) => self.apply_consumption_expr(&try_expr.expr),
            Expr::Array(array) => {
                let mut applied = false;
                for elem in &array.elems {
                    applied |= self.apply_consumption_expr(elem);
                }
                applied
            }
            Expr::Tuple(tuple) => {
                let mut applied = false;
                for elem in &tuple.elems {
                    applied |= self.apply_consumption_expr(elem);
                }
                applied
            }
            Expr::Binary(binary) => {
                self.apply_consumption_expr(&binary.left)
                    | self.apply_consumption_expr(&binary.right)
            }
            Expr::Assign(assign) => {
                self.apply_refcell_borrow_mut_assign(&assign.left, &assign.right, false)
                    || (self.apply_consumption_expr(&assign.left)
                        | self.apply_consumption_expr(&assign.right))
            }
            Expr::Block(block) => self.apply_consumption_stmts(&block.block.stmts),
            Expr::Unsafe(block) => self.apply_consumption_stmts(&block.block.stmts),
            Expr::ForLoop(for_loop) => {
                let mut applied = self.apply_consumption_expr(&for_loop.expr)
                    | self.apply_consumption_stmts(&for_loop.body.stmts);
                applied |= self.apply_for_loop_iterator_exhaustion(for_loop);
                applied
            }
            Expr::While(while_expr) => {
                self.apply_while_loop(while_expr)
                    | self.apply_while_loop_iterator_exhaustion(while_expr)
            }
            Expr::Loop(loop_expr) => self.apply_loop(loop_expr),
            Expr::If(if_expr) => {
                let mut applied = self.apply_consumption_expr(&if_expr.cond)
                    | self.apply_consumption_stmts(&if_expr.then_branch.stmts);
                if let Some((_, else_branch)) = &if_expr.else_branch {
                    applied |= self.apply_consumption_expr(else_branch);
                }
                applied
            }
            Expr::Match(match_expr) => {
                let mut applied = self.apply_consumption_expr(&match_expr.expr);
                for arm in &match_expr.arms {
                    applied |= self.apply_consumption_expr(&arm.body);
                }
                applied
            }
            _ => false,
        }
    }

    fn apply_consumption_stmts(&mut self, stmts: &[Stmt]) -> bool {
        let mut applied = false;
        for stmt in stmts {
            applied |= self.apply_statement(stmt);
        }
        applied
    }

    fn apply_while_loop(&mut self, while_expr: &syn::ExprWhile) -> bool {
        let mutated = loop_mutation_names_in_stmts(&while_expr.body.stmts);
        if mutated.is_empty() {
            return false;
        }
        let mut scratch = self.clone();
        for _ in 0..LOOP_REPLAY_CAP {
            let Some(cond) = scratch.bool_value(&while_expr.cond) else {
                return self.invalidate_unreplayed_loop_mutations(&mutated, "while condition");
            };
            if !cond {
                *self = scratch;
                self.loop_replayed.extend(mutated);
                return true;
            }
            match scratch.apply_loop_stmts_once(&while_expr.body.stmts) {
                Some(LoopStep::Break) => {
                    *self = scratch;
                    self.loop_replayed.extend(mutated);
                    return true;
                }
                Some(LoopStep::Continue | LoopStep::Fallthrough) => {}
                None => return self.invalidate_unreplayed_loop_mutations(&mutated, "while body"),
            }
        }
        self.invalidate_unreplayed_loop_mutations(&mutated, "while replay cap")
    }

    fn apply_while_loop_iterator_exhaustion(&mut self, while_expr: &syn::ExprWhile) -> bool {
        if block_may_escape_iteration(&while_expr.body.stmts) {
            return false;
        }
        let Some(name) = while_let_next_source_name(while_expr) else {
            return false;
        };
        self.exhaust_iterator_binding(&name, "while-next")
    }

    fn apply_for_loop_iterator_exhaustion(&mut self, for_loop: &syn::ExprForLoop) -> bool {
        if block_may_escape_iteration(&for_loop.body.stmts) {
            return false;
        }
        let Some(name) = for_loop_full_drain_source_name(&for_loop.expr) else {
            return false;
        };
        self.exhaust_iterator_binding(&name, "for-loop")
    }

    fn apply_loop(&mut self, loop_expr: &syn::ExprLoop) -> bool {
        let mutated = loop_mutation_names_in_stmts(&loop_expr.body.stmts);
        if mutated.is_empty() {
            return false;
        }
        let mut scratch = self.clone();
        for _ in 0..LOOP_REPLAY_CAP {
            match scratch.apply_loop_stmts_once(&loop_expr.body.stmts) {
                Some(LoopStep::Break) => {
                    *self = scratch;
                    self.loop_replayed.extend(mutated);
                    return true;
                }
                Some(LoopStep::Continue | LoopStep::Fallthrough) => {}
                None => return self.invalidate_unreplayed_loop_mutations(&mutated, "loop body"),
            }
        }
        self.invalidate_unreplayed_loop_mutations(&mutated, "loop replay cap")
    }

    fn apply_loop_stmts_once(&mut self, stmts: &[Stmt]) -> Option<LoopStep> {
        for stmt in stmts {
            match self.apply_loop_stmt_once(stmt)? {
                LoopStep::Fallthrough => {}
                flow => return Some(flow),
            }
        }
        Some(LoopStep::Fallthrough)
    }

    fn apply_loop_stmt_once(&mut self, stmt: &Stmt) -> Option<LoopStep> {
        match stmt {
            Stmt::Local(local) => {
                let init = local.init.as_ref().filter(|init| init.diverge.is_none())?;
                self.trackable_value(&init.expr)?;
                self.record_local(local);
                Some(LoopStep::Fallthrough)
            }
            Stmt::Expr(Expr::Break(expr_break), _) => {
                (expr_break.label.is_none() && expr_break.expr.is_none()).then_some(LoopStep::Break)
            }
            Stmt::Expr(Expr::Continue(expr_continue), _) => {
                expr_continue.label.is_none().then_some(LoopStep::Continue)
            }
            Stmt::Expr(Expr::If(if_expr), _) => self.apply_loop_if_once(if_expr),
            Stmt::Expr(expr, _) => self
                .apply_with_trace(expr, true)
                .then_some(LoopStep::Fallthrough),
            _ => None,
        }
    }

    fn apply_loop_if_once(&mut self, if_expr: &syn::ExprIf) -> Option<LoopStep> {
        if self.bool_value(&if_expr.cond)? {
            return self.apply_loop_stmts_once(&if_expr.then_branch.stmts);
        }
        let Some((_, else_branch)) = &if_expr.else_branch else {
            return Some(LoopStep::Fallthrough);
        };
        match strip_refs_groups(else_branch) {
            Expr::Block(block) => self.apply_loop_stmts_once(&block.block.stmts),
            Expr::If(nested) => self.apply_loop_if_once(nested),
            _ => None,
        }
    }

    fn invalidate_unreplayed_loop_mutations(
        &mut self,
        names: &BTreeSet<String>,
        reason: &str,
    ) -> bool {
        for name in names {
            let reason = format!(
                "temporally unstable post-loop read of `{name}` after {reason}: \
                 the loop was not exactly replayable from source literals, so there \
                 is no single timeless value to read at the assertion; refused"
            );
            self.values.remove(name);
            self.aliases.remove(name);
            self.unknown_consumed_iterators.remove(name);
            self.rewritten_bases.remove(name);
            self.exhausted_iterators.remove(name);
            self.loop_replayed.remove(name);
            self.poison_cell(name, reason.clone());
            self.unknown_mutations.insert(name.clone(), reason);
        }
        !names.is_empty()
    }

    fn advance_iterator_binding(
        &mut self,
        name: &str,
        direction: IteratorConsumptionDirection,
        count: usize,
    ) -> bool {
        let Some(current) = self.values.get(name).cloned() else {
            return false;
        };
        let n = syn::LitInt::new(&count.to_string(), proc_macro2::Span::call_site());
        let updated: Expr = match direction {
            IteratorConsumptionDirection::Front => syn::parse_quote!((#current).skip(#n)),
            IteratorConsumptionDirection::Back => {
                syn::parse_quote!((#current).rev().skip(#n).rev())
            }
        };
        debug!(
            target: "sugar_lift_rust_tests::temporal_rewrite",
            binding = name,
            current = %token_key(&current),
            updated = %token_key(&updated),
            count,
            from_back = matches!(direction, IteratorConsumptionDirection::Back),
            "temporal rewrite advanced iterator receiver"
        );
        self.values.insert(name.to_string(), updated);
        self.unknown_consumed_iterators.remove(name);
        true
    }

    fn invalidate_iterator_binding(&mut self, name: &str, method: &str) -> bool {
        self.values.remove(name);
        self.aliases.remove(name);
        self.rewritten_bases.remove(name);
        self.loop_replayed.remove(name);
        self.exhausted_iterators.remove(name);
        self.unknown_consumed_iterators
            .insert(name.to_string(), method.to_string());
        debug!(
            target: "sugar_lift_rust_tests::temporal_rewrite",
            binding = name,
            method,
            "temporal rewrite invalidated iterator after unknown-count consumption"
        );
        true
    }

    fn exhaust_iterator_binding(&mut self, name: &str, method: &str) -> bool {
        let Some(current) = self.expr_for(name) else {
            return false;
        };
        if !iterator_state_expr(&current) {
            return false;
        }
        let exhausted: Expr = syn::parse_quote!([].iter());
        self.values.insert(name.to_string(), exhausted);
        self.exhausted_iterators.insert(name.to_string());
        self.aliases.remove(name);
        self.unknown_consumed_iterators.remove(name);
        self.unknown_mutations.remove(name);
        self.rewritten_bases.remove(name);
        self.loop_replayed.remove(name);
        debug!(
            target: "sugar_lift_rust_tests::temporal_rewrite",
            binding = name,
            method,
            "temporal rewrite exhausted iterator receiver"
        );
        true
    }

    fn invalidate_opaque_mut_borrow_call(&mut self, name: &str, site: &str) -> bool {
        let reason = format!(
            "ambiguous temporal identity for `{name}` after opaque mutable borrow call \
             `{site}`: the call may write through `&mut`, so there is no single \
             timeless value to read at the assertion; refused"
        );
        self.values.remove(name);
        self.aliases.remove(name);
        self.unknown_consumed_iterators.remove(name);
        self.rewritten_bases.remove(name);
        self.loop_replayed.remove(name);
        self.exhausted_iterators.remove(name);
        self.poison_cell(name, reason.clone());
        self.unknown_mutations.insert(name.to_string(), reason);
        debug!(
            target: "sugar_lift_rust_tests::temporal_rewrite",
            binding = name,
            site,
            "temporal rewrite invalidated local after opaque mutable borrow call"
        );
        true
    }

    fn invalidate_mutable_view(&mut self, name: &str, method: &str) -> bool {
        let reason = format!(
            "temporally unstable mutable view read of `{name}` after `.{method}()`: \
             the method exposes mutable state whose writes are not replayed by the \
             literal temporal rewrite, so there is no single timeless value to read \
             at the assertion; refused"
        );
        self.values.remove(name);
        self.aliases.remove(name);
        self.unknown_consumed_iterators.remove(name);
        self.rewritten_bases.remove(name);
        self.loop_replayed.remove(name);
        self.exhausted_iterators.remove(name);
        self.poison_cell(name, reason.clone());
        self.unknown_mutations.insert(name.to_string(), reason);
        debug!(
            target: "sugar_lift_rust_tests::temporal_rewrite",
            binding = name,
            method,
            "temporal rewrite invalidated local after mutable view method"
        );
        true
    }

    fn invalidate_mutating_receiver(&mut self, name: &str, method: &str) -> bool {
        let reason = format!(
            "temporally unstable mutating method read of `{name}` after `.{method}()`: \
             the method may write receiver state outside the literal temporal rewrite, \
             so there is no single timeless value to read at the assertion; refused"
        );
        self.values.remove(name);
        self.aliases.remove(name);
        self.unknown_consumed_iterators.remove(name);
        self.rewritten_bases.remove(name);
        self.loop_replayed.remove(name);
        self.exhausted_iterators.remove(name);
        self.poison_cell(name, reason.clone());
        self.unknown_mutations.insert(name.to_string(), reason);
        debug!(
            target: "sugar_lift_rust_tests::temporal_rewrite",
            binding = name,
            method,
            "temporal rewrite invalidated local after mutating receiver method"
        );
        true
    }

    pub(crate) fn record_local(&mut self, local: &syn::Local) {
        let Some(init) = local.init.as_ref().filter(|init| init.diverge.is_none()) else {
            return;
        };

        if self.record_get_disjoint_mut_aliases(&local.pat, &init.expr) {
            return;
        }

        let Some(name) = simple_pat_binding(&local.pat) else {
            return;
        };

        self.unknown_consumed_iterators.remove(&name);
        self.unknown_mutations.remove(&name);
        self.rewritten_bases.remove(&name);
        self.loop_replayed.remove(&name);
        self.exhausted_iterators.remove(&name);
        if let Some(base) = borrowed_iterator_source_name(&init.expr)
            .filter(|base| base != &name && self.values.contains_key(base))
        {
            self.invalidate_iterator_binding(&base, "by_ref");
        }
        if let Some(base) =
            mut_reference_target(&init.expr).filter(|base| self.values.contains_key(base))
        {
            self.values.remove(&name);
            debug!(
                target: "sugar_lift_rust_tests::temporal_rewrite",
                binding = name.as_str(),
                init = %token_key(&init.expr),
                "temporal rewrite captured mutable reference alias"
            );
            self.aliases.insert(name, RewritePlace::Scalar(base));
            return;
        }
        if let Some(base) =
            cell_reference_target(&init.expr).filter(|base| self.cell_values.contains_key(base))
        {
            self.invalidate_cell(&base);
            self.cell_values.remove(&name);
            return;
        }

        self.aliases.remove(&name);
        if let Some((kind, value)) = self.cell_constructor_value(&init.expr) {
            let value_label = value
                .as_ref()
                .map(token_key)
                .unwrap_or_else(|| "<runtime>".to_string());
            debug!(
                target: "sugar_lift_rust_tests::temporal_rewrite",
                binding = name.as_str(),
                kind = ?kind,
                value = value_label.as_str(),
                "temporal rewrite captured interior-mutable literal cell"
            );
            self.cell_values.insert(
                name,
                CellState {
                    kind,
                    value,
                    reason: None,
                },
            );
            return;
        }
        self.cell_values.remove(&name);
        if let Some(value) = self.trackable_value(&init.expr) {
            // Shadow guard: a shadowed `let x = x + expr` causes trackable_value to
            // return the raw expression still containing `x`. Storing it as-is makes
            // expr_for(x) self-referential and int_value recurse infinitely:
            //   int_value(x) → expr_for(x) → raw_expr → int_value(x) → ∞.
            // Detect this and force evaluation to a concrete integer while the old
            // binding is still live in `values`.
            let safe_value = if expr_references_name(&value, &name) {
                self.int_value(&value).and_then(int_expr)
            } else {
                Some(value)
            };
            if let Some(v) = safe_value {
                debug!(
                    target: "sugar_lift_rust_tests::temporal_rewrite",
                    binding = name.as_str(),
                    value = %token_key(&v),
                    "temporal rewrite captured literal-backed local"
                );
                self.values.insert(name, v);
            } else {
                trace!(
                    target: "sugar_lift_rust_tests::temporal_rewrite",
                    binding = name.as_str(),
                    init = %token_key(&init.expr),
                    "temporal rewrite declined self-referential local"
                );
                self.values.remove(&name);
            }
        } else {
            trace!(
                target: "sugar_lift_rust_tests::temporal_rewrite",
                binding = name.as_str(),
                init = %token_key(&init.expr),
                "temporal rewrite declined local"
            );
            self.values.remove(&name);
        }
    }

    pub(crate) fn record_literal_value(&mut self, name: &str, value: Expr) {
        self.unknown_consumed_iterators.remove(name);
        self.unknown_mutations.remove(name);
        self.aliases.remove(name);
        self.cell_values.remove(name);
        self.rewritten_bases.remove(name);
        self.loop_replayed.remove(name);
        self.exhausted_iterators.remove(name);
        self.values.insert(name.to_string(), value);
    }

    fn cell_constructor_value(&self, expr: &Expr) -> Option<(CellKind, Option<Expr>)> {
        let (kind, value) = cell_constructor_arg(expr)?;
        Some((kind, self.trackable_value(value)))
    }

    fn apply_cell_set(&mut self, call: &syn::ExprMethodCall) -> bool {
        if call.method != "set" || call.args.len() != 1 {
            return false;
        }
        let Some(name) = simple_path_name(&call.receiver) else {
            return false;
        };
        if self.cell_kind(&name) != Some(CellKind::Cell) {
            return false;
        }
        let Some(arg) = call.args.first() else {
            return false;
        };
        let value = self.trackable_value(arg);
        self.set_cell_value(&name, CellKind::Cell, value)
    }

    fn apply_refcell_borrow_mut_assign(
        &mut self,
        lhs: &Expr,
        rhs: &Expr,
        emit_trace: bool,
    ) -> bool {
        let Some(name) = refcell_borrow_mut_assignment_target(lhs) else {
            return false;
        };
        if self.cell_kind(&name) != Some(CellKind::RefCell) {
            return false;
        }
        let value = self.trackable_value(rhs);
        let applied = self.set_cell_value(&name, CellKind::RefCell, value);
        if applied && emit_trace {
            debug!(
                target: "sugar_lift_rust_tests::temporal_rewrite",
                binding = name.as_str(),
                rhs = %token_key(rhs),
                "temporal rewrite applied RefCell borrow_mut assignment"
            );
        }
        applied
    }

    fn set_cell_value(&mut self, name: &str, kind: CellKind, value: Option<Expr>) -> bool {
        let Some(state) = self.cell_values.get_mut(name) else {
            return false;
        };
        if state.kind != kind {
            return false;
        }
        match value {
            Some(value) => {
                state.value = Some(value);
                state.reason = None;
            }
            None => {
                state.value = None;
                state.reason = Some(CELL_RUNTIME_ALIASED_REASON.to_string());
            }
        }
        true
    }

    fn invalidate_cell(&mut self, name: &str) -> bool {
        self.poison_cell(name, CELL_RUNTIME_ALIASED_REASON.to_string())
    }

    fn poison_cell(&mut self, name: &str, reason: String) -> bool {
        let Some(state) = self.cell_values.get_mut(name) else {
            return false;
        };
        state.value = None;
        state.reason = Some(reason);
        true
    }

    fn record_get_disjoint_mut_aliases(&mut self, pat: &Pat, init: &Expr) -> bool {
        let Some(bindings) = slice_pat_bindings(pat) else {
            return false;
        };
        let Some((base, specs)) = get_disjoint_mut_specs(init) else {
            return false;
        };
        if !self.values.contains_key(&base) || bindings.len() != specs.len() {
            return false;
        }
        for (binding, spec) in bindings.into_iter().zip(specs.into_iter()) {
            let place = match spec {
                IndexSpec::Element(index) => RewritePlace::Element {
                    base: base.clone(),
                    index,
                },
                IndexSpec::Slice { start, len } => RewritePlace::Slice {
                    base: base.clone(),
                    start,
                    len,
                },
            };
            self.values.remove(&binding);
            debug!(
                target: "sugar_lift_rust_tests::temporal_rewrite",
                binding = binding.as_str(),
                base = base.as_str(),
                place = ?place,
                "temporal rewrite captured disjoint mutable alias"
            );
            self.aliases.insert(binding, place);
        }
        true
    }

    fn apply_assign(&mut self, lhs: &Expr, rhs: &Expr, emit_trace: bool) -> bool {
        let Some(target) = self.target_for_lhs(lhs) else {
            return false;
        };
        let Some(value) = self.trackable_value(rhs) else {
            return false;
        };
        let target_label = target_label(&target);
        let value_label = token_key(&value);
        let applied = self.set_target(target, value);
        if applied && emit_trace {
            debug!(
                target: "sugar_lift_rust_tests::temporal_rewrite",
                lhs = %token_key(lhs),
                rhs = %token_key(rhs),
                target = target_label.as_str(),
                value = value_label.as_str(),
                "temporal rewrite applied assignment"
            );
        }
        applied
    }

    fn apply_compound_assign(&mut self, binary: &syn::ExprBinary, emit_trace: bool) -> bool {
        let Some(op) = assignment_op(&binary.op) else {
            return false;
        };
        let Some(target) = self.target_for_lhs(&binary.left) else {
            return false;
        };
        let Some(old) = self.target_expr(&target) else {
            return false;
        };
        let Some(old_value) = self.int_value(&old) else {
            return false;
        };
        let Some(rhs_value) = self.int_value(&binary.right) else {
            return false;
        };
        let Some(updated) = apply_int_op(op, old_value, rhs_value).and_then(int_expr) else {
            return false;
        };
        let target_label = target_label(&target);
        let updated_label = token_key(&updated);
        let applied = self.set_target(target, updated);
        if applied && emit_trace {
            debug!(
                target: "sugar_lift_rust_tests::temporal_rewrite",
                lhs = %token_key(&binary.left),
                rhs = %token_key(&binary.right),
                op = ?op,
                target = target_label.as_str(),
                old = old_value,
                rhs_value,
                updated = updated_label.as_str(),
                "temporal rewrite applied compound assignment"
            );
        }
        applied
    }

    fn target_for_lhs(&self, lhs: &Expr) -> Option<Target> {
        match strip_refs_groups(lhs) {
            Expr::Path(_) => {
                let name = simple_path_name(lhs)?;
                if self.values.contains_key(&name) {
                    return Some(Target::Scalar(name));
                }
                match self.aliases.get(&name)? {
                    RewritePlace::Scalar(base) => Some(Target::Scalar(base.clone())),
                    RewritePlace::Element { base, index } => Some(Target::Element {
                        base: base.clone(),
                        index: *index,
                        replayable_alias: true,
                    }),
                    RewritePlace::Slice { .. } => None,
                }
            }
            Expr::Unary(unary) if matches!(unary.op, UnOp::Deref(_)) => {
                self.target_for_deref(&unary.expr)
            }
            Expr::Index(index) => self.target_for_index(index),
            _ => None,
        }
    }

    fn target_for_deref(&self, expr: &Expr) -> Option<Target> {
        let name = simple_path_name(expr)?;
        match self.aliases.get(&name)? {
            RewritePlace::Scalar(base) => Some(Target::Scalar(base.clone())),
            RewritePlace::Element { base, index } => Some(Target::Element {
                base: base.clone(),
                index: *index,
                replayable_alias: true,
            }),
            RewritePlace::Slice { .. } => None,
        }
    }

    fn target_for_index(&self, index: &syn::ExprIndex) -> Option<Target> {
        let idx = self.index_value(&index.index)?;
        let base_name = simple_path_name(&index.expr)?;
        if self.values.contains_key(&base_name) {
            return Some(Target::Element {
                base: base_name,
                index: idx,
                replayable_alias: false,
            });
        }
        match self.aliases.get(&base_name)? {
            RewritePlace::Slice { base, start, len } if idx < *len => Some(Target::Element {
                base: base.clone(),
                index: start.checked_add(idx)?,
                replayable_alias: true,
            }),
            RewritePlace::Element { .. } | RewritePlace::Scalar(_) | RewritePlace::Slice { .. } => {
                None
            }
        }
    }

    fn set_target(&mut self, target: Target, value: Expr) -> bool {
        match target {
            Target::Scalar(name) => {
                if self.trackable_value(&value).is_some() {
                    self.values.insert(name, value);
                    true
                } else {
                    false
                }
            }
            Target::Element {
                base,
                index,
                replayable_alias,
            } => self.set_aggregate_element(&base, index, value, replayable_alias),
        }
    }

    fn target_expr(&self, target: &Target) -> Option<Expr> {
        match target {
            Target::Scalar(name) => self.values.get(name).cloned(),
            Target::Element { base, index, .. } => self.aggregate_element(base, *index),
        }
    }

    fn aggregate_element(&self, base: &str, index: usize) -> Option<Expr> {
        let expr = self.values.get(base)?;
        let (_, elems) = aggregate_elems(expr)?;
        elems.get(index).cloned()
    }

    fn set_aggregate_element(
        &mut self,
        base: &str,
        index: usize,
        value: Expr,
        replayable_alias: bool,
    ) -> bool {
        if self.int_value(&value).is_none() {
            return false;
        }
        let Some(current) = self.values.get(base).cloned() else {
            return false;
        };
        let Some((kind, mut elems)) = aggregate_elems(&current) else {
            return false;
        };
        if index >= elems.len() {
            return false;
        }
        elems[index] = value;
        self.values
            .insert(base.to_string(), rebuild_aggregate(kind, elems));
        if replayable_alias {
            self.rewritten_bases.insert(base.to_string());
        }
        true
    }

    fn trackable_value(&self, expr: &Expr) -> Option<Expr> {
        if let Some(name) = simple_path_name(expr) {
            if let Some(value) = self.expr_for(&name) {
                return Some(value);
            }
        }
        if self.int_value(expr).is_some() {
            return Some(expr.clone());
        }
        if let Some(expr) = self.trackable_sequence_expr(expr) {
            return Some(expr);
        }
        let (kind, elems) = aggregate_elems(expr)?;
        if elems.iter().all(|elem| self.int_value(elem).is_some()) {
            Some(rebuild_aggregate(kind, elems))
        } else {
            None
        }
    }

    fn trackable_sequence_expr(&self, expr: &Expr) -> Option<Expr> {
        match strip_refs_groups(expr) {
            Expr::Path(_) => {
                let name = simple_path_name(expr)?;
                self.expr_for(&name)
            }
            Expr::Array(_) | Expr::Range(_) | Expr::Repeat(_) => Some(expr.clone()),
            Expr::Macro(expr_macro) if macro_name_is(&expr_macro.mac, "vec") => Some(expr.clone()),
            Expr::Call(call) if collection_constructor_sequence(call) => Some(expr.clone()),
            Expr::Call(call) => self.trackable_ufcs_into_iter(call),
            Expr::MethodCall(call) if trackable_sequence_method(&call.method.to_string()) => {
                if !trackable_sequence_args(call) {
                    return None;
                }
                let receiver = self.trackable_sequence_expr(&call.receiver)?;
                let mut out = call.clone();
                out.receiver = Box::new(receiver);
                Some(Expr::MethodCall(out))
            }
            Expr::Reference(reference) => self.trackable_sequence_expr(&reference.expr),
            Expr::Paren(paren) => self.trackable_sequence_expr(&paren.expr),
            Expr::Group(group) => self.trackable_sequence_expr(&group.expr),
            _ => None,
        }
    }

    fn trackable_ufcs_into_iter(&self, call: &syn::ExprCall) -> Option<Expr> {
        if !ufcs_into_iter_call(call) || call.args.len() != 1 {
            return None;
        }
        let receiver = self.trackable_sequence_expr(call.args.first()?)?;
        // Keep this local to temporal rewrites: the global UFCS callsite key stays stable,
        // while a tracked SSA-current iterator can reuse the existing method-adaptor path.
        Some(syn::parse_quote!((#receiver).into_iter()))
    }

    fn int_value(&self, expr: &Expr) -> Option<i128> {
        match strip_refs_groups(expr) {
            Expr::Lit(lit) => match &lit.lit {
                Lit::Int(i) => parse_int_lit(i).ok(),
                Lit::Byte(b) => Some(i128::from(b.value())),
                _ => None,
            },
            Expr::Unary(unary) => match unary.op {
                UnOp::Neg(_) => self.int_value(&unary.expr)?.checked_neg(),
                UnOp::Not(_) => Some(!self.int_value(&unary.expr)?),
                _ => None,
            },
            Expr::Path(_) => {
                let name = simple_path_name(expr)?;
                let value = self.expr_for(&name)?;
                self.int_value(&value)
            }
            Expr::Binary(binary) => {
                let left = self.int_value(&binary.left)?;
                let right = self.int_value(&binary.right)?;
                apply_value_binop(&binary.op, left, right)
            }
            Expr::Cast(cast) => self.int_value(&cast.expr),
            Expr::MethodCall(call) if call.method == "unwrap" && call.args.is_empty() => {
                self.int_value(&call.receiver)
            }
            Expr::Call(call) if is_nonzero_new_call(&call.func) && call.args.len() == 1 => {
                self.int_value(call.args.first()?)
            }
            _ => None,
        }
    }

    fn index_value(&self, expr: &Expr) -> Option<usize> {
        usize::try_from(self.int_value(expr)?).ok()
    }

    fn bool_value(&self, expr: &Expr) -> Option<bool> {
        match strip_refs_groups(expr) {
            Expr::Lit(lit) => match &lit.lit {
                Lit::Bool(b) => Some(b.value),
                _ => None,
            },
            Expr::Path(_) => {
                let name = simple_path_name(expr)?;
                self.expr_for(&name)
                    .and_then(|value| self.bool_value(&value))
            }
            Expr::Unary(unary) if matches!(unary.op, UnOp::Not(_)) => {
                Some(!self.bool_value(&unary.expr)?)
            }
            Expr::Binary(binary) => match binary.op {
                BinOp::And(_) => {
                    Some(self.bool_value(&binary.left)? && self.bool_value(&binary.right)?)
                }
                BinOp::Or(_) => {
                    Some(self.bool_value(&binary.left)? || self.bool_value(&binary.right)?)
                }
                BinOp::Eq(_) => self.eq_value(&binary.left, &binary.right),
                BinOp::Ne(_) => self.eq_value(&binary.left, &binary.right).map(|same| !same),
                BinOp::Lt(_) => {
                    Some(self.int_value(&binary.left)? < self.int_value(&binary.right)?)
                }
                BinOp::Le(_) => {
                    Some(self.int_value(&binary.left)? <= self.int_value(&binary.right)?)
                }
                BinOp::Gt(_) => {
                    Some(self.int_value(&binary.left)? > self.int_value(&binary.right)?)
                }
                BinOp::Ge(_) => {
                    Some(self.int_value(&binary.left)? >= self.int_value(&binary.right)?)
                }
                _ => None,
            },
            _ => None,
        }
    }

    fn eq_value(&self, left: &Expr, right: &Expr) -> Option<bool> {
        if let (Some(l), Some(r)) = (self.int_value(left), self.int_value(right)) {
            return Some(l == r);
        }
        if let (Some(l), Some(r)) = (self.bool_value(left), self.bool_value(right)) {
            return Some(l == r);
        }
        None
    }
}

fn unknown_iterator_consumption(call: &syn::ExprMethodCall) -> bool {
    matches!(
        call.method.to_string().as_str(),
        "try_fold"
            | "try_rfold"
            | "try_for_each"
            | "try_find"
            | "next_if_map"
            | "find"
            | "find_map"
            | "position"
            | "rposition"
            | "all"
            | "any"
    )
}

fn assigned_names_in_stmts(stmts: &[Stmt]) -> BTreeSet<String> {
    struct V {
        out: BTreeSet<String>,
    }
    impl V {
        fn record(&mut self, lhs: &Expr) {
            if let Some(name) = assigned_target_name(lhs) {
                self.out.insert(name);
            }
        }
    }
    impl<'ast> syn::visit::Visit<'ast> for V {
        fn visit_expr_assign(&mut self, assign: &'ast syn::ExprAssign) {
            self.record(&assign.left);
            syn::visit::visit_expr_assign(self, assign);
        }

        fn visit_expr_binary(&mut self, binary: &'ast syn::ExprBinary) {
            if assignment_op(&binary.op).is_some() {
                self.record(&binary.left);
            }
            syn::visit::visit_expr_binary(self, binary);
        }
    }

    let mut v = V {
        out: BTreeSet::new(),
    };
    for stmt in stmts {
        syn::visit::Visit::visit_stmt(&mut v, stmt);
    }
    v.out
}

fn loop_mutation_names_in_stmts(stmts: &[Stmt]) -> BTreeSet<String> {
    struct V {
        out: BTreeSet<String>,
    }

    impl V {
        fn record(&mut self, lhs: &Expr) {
            if let Some(name) = assigned_target_name(lhs) {
                self.out.insert(name);
            }
        }
    }

    impl<'ast> syn::visit::Visit<'ast> for V {
        fn visit_expr_assign(&mut self, assign: &'ast syn::ExprAssign) {
            self.record(&assign.left);
            syn::visit::visit_expr_assign(self, assign);
        }

        fn visit_expr_binary(&mut self, binary: &'ast syn::ExprBinary) {
            if assignment_op(&binary.op).is_some() {
                self.record(&binary.left);
            }
            syn::visit::visit_expr_binary(self, binary);
        }

        fn visit_expr_reference(&mut self, reference: &'ast syn::ExprReference) {
            if reference.mutability.is_some() {
                if let Some(name) = simple_path_name(&reference.expr) {
                    self.out.insert(name);
                }
            }
            syn::visit::visit_expr_reference(self, reference);
        }

        fn visit_expr_method_call(&mut self, call: &'ast syn::ExprMethodCall) {
            let method = call.method.to_string();
            if mutable_view_method(&method) || mutating_receiver_method(&method) {
                if let Some(name) = simple_path_name(&call.receiver) {
                    self.out.insert(name);
                }
            }
            syn::visit::visit_expr_method_call(self, call);
        }
    }

    let mut v = V {
        out: assigned_names_in_stmts(stmts),
    };
    for stmt in stmts {
        syn::visit::Visit::visit_stmt(&mut v, stmt);
    }
    v.out
}

fn assigned_target_name(lhs: &Expr) -> Option<String> {
    match strip_refs_groups(lhs) {
        Expr::Path(_) => simple_path_name(lhs),
        Expr::Index(index) => simple_path_name(&index.expr),
        Expr::Unary(unary) if matches!(unary.op, UnOp::Deref(_)) => simple_path_name(&unary.expr),
        _ => None,
    }
}

fn mutable_view_method(method: &str) -> bool {
    matches!(
        method,
        "iter_mut"
            | "values_mut"
            | "as_mut"
            | "as_mut_ptr"
            | "as_mut_slice"
            | "borrow_mut"
            | "get_mut"
            | "get_unchecked_mut"
            | "get_disjoint_mut"
            | "split_at_mut"
            | "chunks_mut"
            | "rchunks_mut"
            | "windows_mut"
            | "array_chunks_mut"
            | "array_windows_mut"
    )
}

fn mutating_receiver_method(method: &str) -> bool {
    matches!(
        method,
        "set"
            | "replace"
            | "swap"
            | "take"
            | "push"
            | "push_back"
            | "push_front"
            | "pop"
            | "pop_back"
            | "pop_front"
            | "insert"
            | "remove"
            | "clear"
            | "retain"
            | "resize"
            | "reserve"
            | "truncate"
            | "extend"
            | "append"
            | "drain"
            | "store"
            | "fetch_add"
            | "fetch_sub"
            | "fetch_and"
            | "fetch_or"
            | "fetch_xor"
            | "fetch_nand"
            | "fetch_max"
            | "fetch_min"
            | "fetch_update"
            | "compare_exchange"
            | "compare_exchange_weak"
            | "compare_and_swap"
            | "write"
            | "write_all"
            | "write_str"
            | "write_fmt"
            | "send"
    )
}

fn mut_reference_targets(expr: &Expr) -> BTreeSet<String> {
    fn collect(expr: &Expr, out: &mut BTreeSet<String>) {
        match expr {
            Expr::Reference(reference) if reference.mutability.is_some() => {
                if let Some(name) = simple_path_name(&reference.expr) {
                    out.insert(name);
                } else {
                    collect(&reference.expr, out);
                }
            }
            Expr::Reference(reference) => collect(&reference.expr, out),
            Expr::Cast(cast) => collect(&cast.expr, out),
            Expr::Paren(paren) => collect(&paren.expr, out),
            Expr::Group(group) => collect(&group.expr, out),
            Expr::Unary(unary) => collect(&unary.expr, out),
            Expr::Field(field) => collect(&field.base, out),
            Expr::Index(index) => {
                collect(&index.expr, out);
                collect(&index.index, out);
            }
            Expr::MethodCall(call) => {
                collect(&call.receiver, out);
                for arg in &call.args {
                    collect(arg, out);
                }
            }
            Expr::Call(call) => {
                collect(&call.func, out);
                for arg in &call.args {
                    collect(arg, out);
                }
            }
            Expr::Binary(binary) => {
                collect(&binary.left, out);
                collect(&binary.right, out);
            }
            Expr::Assign(assign) => {
                collect(&assign.left, out);
                collect(&assign.right, out);
            }
            Expr::Array(array) => {
                for elem in &array.elems {
                    collect(elem, out);
                }
            }
            Expr::Tuple(tuple) => {
                for elem in &tuple.elems {
                    collect(elem, out);
                }
            }
            Expr::Macro(expr_macro) if macro_name_is(&expr_macro.mac, "addr_of_mut") => {
                if let Ok(path) = syn::parse2::<syn::Path>(expr_macro.mac.tokens.clone()) {
                    if let Some(name) = path.get_ident() {
                        out.insert(name.to_string());
                    }
                }
            }
            _ => {}
        }
    }
    let mut out = BTreeSet::new();
    collect(expr, &mut out);
    out
}

fn borrowed_iterator_terminal(call: &syn::ExprMethodCall) -> bool {
    matches!(
        call.method.to_string().as_str(),
        "next"
            | "next_back"
            | "nth"
            | "nth_back"
            | "advance_by"
            | "advance_back_by"
            | "next_if"
            | "next_if_eq"
            | "next_if_map"
            | "try_fold"
            | "try_rfold"
            | "try_for_each"
            | "try_find"
            | "fold"
            | "rfold"
            | "for_each"
            | "find"
            | "find_map"
            | "position"
            | "rposition"
            | "all"
            | "any"
            | "count"
            | "last"
            | "sum"
            | "product"
            | "collect"
            | "reduce"
            | "try_reduce"
            | "max"
            | "min"
            | "max_by"
            | "min_by"
            | "max_by_key"
            | "min_by_key"
            | "cmp"
            | "partial_cmp"
            | "eq"
            | "ne"
            | "lt"
            | "le"
            | "gt"
            | "ge"
    )
}

fn borrowed_iterator_source_name(expr: &Expr) -> Option<String> {
    match strip_refs_groups(expr) {
        Expr::MethodCall(call) if call.method == "by_ref" && call.args.is_empty() => {
            simple_path_name(&call.receiver)
        }
        Expr::MethodCall(call) if borrowed_iterator_adapter(&call.method.to_string()) => {
            borrowed_iterator_source_name(&call.receiver)
        }
        Expr::Reference(reference) => borrowed_iterator_source_name(&reference.expr),
        Expr::Paren(paren) => borrowed_iterator_source_name(&paren.expr),
        Expr::Group(group) => borrowed_iterator_source_name(&group.expr),
        Expr::Try(try_expr) => borrowed_iterator_source_name(&try_expr.expr),
        _ => None,
    }
}

fn iterator_state_expr(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Range(_) => true,
        Expr::MethodCall(call) => {
            let method = call.method.to_string();
            match method.as_str() {
                "iter" | "iter_mut" | "into_iter" => call.args.is_empty(),
                "rev" | "fuse" | "enumerate" | "cloned" | "copied" | "peekable" => {
                    call.args.is_empty() && iterator_state_expr(&call.receiver)
                }
                "skip" | "take" | "step_by" => {
                    call.args.len() == 1
                        && const_int(&call.args[0]).is_some()
                        && iterator_state_expr(&call.receiver)
                }
                _ => false,
            }
        }
        _ => false,
    }
}

fn full_drain_borrowed_iterator_terminal_source(call: &syn::ExprMethodCall) -> Option<String> {
    if call.method != "count" || !call.args.is_empty() {
        return None;
    }
    full_drain_borrowed_iterator_source_name(&call.receiver)
}

fn full_drain_borrowed_iterator_source_name(expr: &Expr) -> Option<String> {
    match strip_refs_groups(expr) {
        Expr::MethodCall(call) if call.method == "by_ref" && call.args.is_empty() => {
            simple_path_name(&call.receiver)
        }
        Expr::MethodCall(call) if full_drain_borrowed_iterator_adapter(call) => {
            full_drain_borrowed_iterator_source_name(&call.receiver)
        }
        Expr::Reference(reference) => full_drain_borrowed_iterator_source_name(&reference.expr),
        Expr::Paren(paren) => full_drain_borrowed_iterator_source_name(&paren.expr),
        Expr::Group(group) => full_drain_borrowed_iterator_source_name(&group.expr),
        _ => None,
    }
}

fn full_drain_borrowed_iterator_adapter(call: &syn::ExprMethodCall) -> bool {
    match call.method.to_string().as_str() {
        "rev" | "fuse" | "enumerate" | "cloned" | "copied" | "peekable" => call.args.is_empty(),
        "skip" | "step_by" => call.args.len() == 1 && const_int(&call.args[0]).is_some(),
        _ => false,
    }
}

fn while_let_next_source_name(while_expr: &syn::ExprWhile) -> Option<String> {
    let Expr::Let(let_expr) = strip_refs_groups(&while_expr.cond) else {
        return None;
    };
    if !pat_is_some_variant(&let_expr.pat) {
        return None;
    }
    let Expr::MethodCall(call) = strip_refs_groups(&let_expr.expr) else {
        return None;
    };
    if !matches!(call.method.to_string().as_str(), "next" | "next_back") || !call.args.is_empty() {
        return None;
    }
    simple_path_name(&call.receiver)
        .or_else(|| full_drain_borrowed_iterator_source_name(&call.receiver))
}

fn for_loop_full_drain_source_name(expr: &Expr) -> Option<String> {
    match strip_refs_groups(expr) {
        Expr::Path(_) => simple_path_name(expr),
        Expr::Reference(reference) => simple_path_name(&reference.expr)
            .or_else(|| for_loop_full_drain_source_name(&reference.expr)),
        Expr::MethodCall(call) if call.method == "by_ref" && call.args.is_empty() => {
            simple_path_name(&call.receiver)
        }
        Expr::MethodCall(call) if full_drain_borrowed_iterator_adapter(call) => {
            for_loop_full_drain_source_name(&call.receiver)
        }
        Expr::Paren(paren) => for_loop_full_drain_source_name(&paren.expr),
        Expr::Group(group) => for_loop_full_drain_source_name(&group.expr),
        _ => None,
    }
}

fn pat_is_some_variant(pat: &Pat) -> bool {
    match pat {
        Pat::TupleStruct(tuple) => tuple
            .path
            .segments
            .last()
            .is_some_and(|segment| segment.ident == "Some"),
        Pat::Reference(reference) => pat_is_some_variant(&reference.pat),
        Pat::Paren(paren) => pat_is_some_variant(&paren.pat),
        Pat::Type(ty) => pat_is_some_variant(&ty.pat),
        Pat::Or(or_pat) => or_pat.cases.iter().all(pat_is_some_variant),
        _ => false,
    }
}

fn block_may_escape_iteration(stmts: &[Stmt]) -> bool {
    struct V {
        found: bool,
    }

    impl<'ast> syn::visit::Visit<'ast> for V {
        fn visit_expr_break(&mut self, _: &'ast syn::ExprBreak) {
            self.found = true;
        }

        fn visit_expr_return(&mut self, _: &'ast syn::ExprReturn) {
            self.found = true;
        }

        fn visit_expr_try(&mut self, _: &'ast syn::ExprTry) {
            self.found = true;
        }

        fn visit_expr_closure(&mut self, _: &'ast syn::ExprClosure) {}
    }

    let mut v = V { found: false };
    for stmt in stmts {
        syn::visit::Visit::visit_stmt(&mut v, stmt);
    }
    v.found
}

fn borrowed_iterator_adapter(method: &str) -> bool {
    matches!(
        method,
        "cloned"
            | "copied"
            | "fuse"
            | "peekable"
            | "enumerate"
            | "rev"
            | "skip"
            | "take"
            | "step_by"
            | "map"
            | "filter"
            | "filter_map"
            | "skip_while"
            | "take_while"
            | "inspect"
            | "chain"
            | "zip"
            | "flatten"
            | "flat_map"
            | "scan"
            | "cycle"
            | "map_while"
    )
}

#[derive(Clone, Copy, Debug)]
enum IteratorConsumptionDirection {
    Front,
    Back,
}

fn iterator_consumption(
    call: &syn::ExprMethodCall,
) -> Option<(IteratorConsumptionDirection, usize)> {
    match (call.method.to_string().as_str(), call.args.len()) {
        ("next", 0) => Some((IteratorConsumptionDirection::Front, 1)),
        ("next_back", 0) => Some((IteratorConsumptionDirection::Back, 1)),
        ("nth", 1) => {
            let n = usize::try_from(const_int(&call.args[0])?).ok()?;
            Some((IteratorConsumptionDirection::Front, n.checked_add(1)?))
        }
        ("nth_back", 1) => {
            let n = usize::try_from(const_int(&call.args[0])?).ok()?;
            Some((IteratorConsumptionDirection::Back, n.checked_add(1)?))
        }
        ("advance_by", 1) => {
            let n = usize::try_from(const_int(&call.args[0])?).ok()?;
            Some((IteratorConsumptionDirection::Front, n))
        }
        ("advance_back_by", 1) => {
            let n = usize::try_from(const_int(&call.args[0])?).ok()?;
            Some((IteratorConsumptionDirection::Back, n))
        }
        _ => None,
    }
}

fn trackable_sequence_method(method: &str) -> bool {
    matches!(
        method,
        "iter"
            | "into_iter"
            | "cloned"
            | "copied"
            | "fuse"
            | "peekable"
            | "enumerate"
            | "rev"
            | "skip"
            | "take"
            | "step_by"
            | "map"
            | "filter"
            | "filter_map"
            | "skip_while"
            | "take_while"
            | "inspect"
            | "chain"
            | "zip"
            | "flatten"
            | "flat_map"
    )
}

fn trackable_sequence_args(call: &syn::ExprMethodCall) -> bool {
    match call.method.to_string().as_str() {
        "iter" | "into_iter" | "cloned" | "copied" | "fuse" | "peekable" | "enumerate" | "rev"
        | "flatten" => call.args.is_empty(),
        "skip" | "take" | "step_by" => {
            call.args.len() == 1 && call.args.first().and_then(const_int).is_some()
        }
        "map" | "filter" | "filter_map" | "skip_while" | "take_while" | "inspect" | "flat_map" => {
            call.args.len() == 1 && matches!(call.args.first(), Some(Expr::Closure(_)))
        }
        "chain" | "zip" => call.args.len() == 1,
        _ => false,
    }
}

fn collection_constructor_sequence(call: &syn::ExprCall) -> bool {
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return false;
    };
    let segments = path
        .path
        .segments
        .iter()
        .map(|segment| segment.ident.to_string())
        .collect::<Vec<_>>();
    matches!(
        segments.as_slice(),
        [head, method] if (head == "Vec" && method == "from") || (head == "Box" && method == "new")
    )
}

fn ufcs_into_iter_call(call: &syn::ExprCall) -> bool {
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return false;
    };
    let segments = path
        .path
        .segments
        .iter()
        .map(|segment| segment.ident.to_string())
        .collect::<Vec<_>>();
    matches!(segments.as_slice(), [head, method] if head == "IntoIterator" && method == "into_iter")
}

fn assignment_op(op: &BinOp) -> Option<BinOpKind> {
    match op {
        BinOp::AddAssign(_) => Some(BinOpKind::Add),
        BinOp::SubAssign(_) => Some(BinOpKind::Sub),
        BinOp::MulAssign(_) => Some(BinOpKind::Mul),
        BinOp::DivAssign(_) => Some(BinOpKind::Div),
        BinOp::RemAssign(_) => Some(BinOpKind::Rem),
        BinOp::BitAndAssign(_) => Some(BinOpKind::BitAnd),
        BinOp::BitOrAssign(_) => Some(BinOpKind::BitOr),
        BinOp::BitXorAssign(_) => Some(BinOpKind::BitXor),
        BinOp::ShlAssign(_) => Some(BinOpKind::Shl),
        BinOp::ShrAssign(_) => Some(BinOpKind::Shr),
        _ => None,
    }
}

fn target_label(target: &Target) -> String {
    match target {
        Target::Scalar(name) => name.clone(),
        Target::Element { base, index, .. } => format!("{base}[{index}]"),
    }
}

#[derive(Clone, Copy, Debug)]
enum BinOpKind {
    Add,
    Sub,
    Mul,
    Div,
    Rem,
    BitAnd,
    BitOr,
    BitXor,
    Shl,
    Shr,
}

fn apply_value_binop(op: &BinOp, left: i128, right: i128) -> Option<i128> {
    let kind = match op {
        BinOp::Add(_) => BinOpKind::Add,
        BinOp::Sub(_) => BinOpKind::Sub,
        BinOp::Mul(_) => BinOpKind::Mul,
        BinOp::Div(_) => BinOpKind::Div,
        BinOp::Rem(_) => BinOpKind::Rem,
        BinOp::BitAnd(_) => BinOpKind::BitAnd,
        BinOp::BitOr(_) => BinOpKind::BitOr,
        BinOp::BitXor(_) => BinOpKind::BitXor,
        BinOp::Shl(_) => BinOpKind::Shl,
        BinOp::Shr(_) => BinOpKind::Shr,
        _ => return None,
    };
    apply_int_op(kind, left, right)
}

fn apply_int_op(kind: BinOpKind, left: i128, right: i128) -> Option<i128> {
    match kind {
        BinOpKind::Add => left.checked_add(right),
        BinOpKind::Sub => left.checked_sub(right),
        BinOpKind::Mul => left.checked_mul(right),
        BinOpKind::Div if right != 0 => left.checked_div(right),
        BinOpKind::Rem if right != 0 => left.checked_rem(right),
        BinOpKind::BitAnd => Some(left & right),
        BinOpKind::BitOr => Some(left | right),
        BinOpKind::BitXor => Some(left ^ right),
        BinOpKind::Shl => u32::try_from(right)
            .ok()
            .and_then(|rhs| left.checked_shl(rhs)),
        BinOpKind::Shr => u32::try_from(right)
            .ok()
            .and_then(|rhs| left.checked_shr(rhs)),
        BinOpKind::Div | BinOpKind::Rem => None,
    }
}

fn aggregate_elems(expr: &Expr) -> Option<(AggregateKind, Vec<Expr>)> {
    match strip_refs_groups(expr) {
        Expr::Array(array) => Some((AggregateKind::Array, array.elems.iter().cloned().collect())),
        Expr::Macro(expr_macro) if macro_name_is(&expr_macro.mac, "vec") => {
            let args = parse_macro_args(expr_macro.mac.tokens.clone()).ok()?;
            Some((AggregateKind::VecMacro, args.exprs))
        }
        _ => None,
    }
}

fn rebuild_aggregate(kind: AggregateKind, elems: Vec<Expr>) -> Expr {
    match kind {
        AggregateKind::Array => syn::parse_quote!([#(#elems),*]),
        AggregateKind::VecMacro => syn::parse_quote!(vec![#(#elems),*]),
    }
}

fn get_disjoint_mut_specs(expr: &Expr) -> Option<(String, Vec<IndexSpec>)> {
    let expr = unwrap_receiver(expr);
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.method != "get_disjoint_mut" || call.args.len() != 1 {
        return None;
    }
    let base = simple_path_name(&call.receiver)?;
    let Expr::Array(indices) = strip_refs_groups(call.args.first()?) else {
        return None;
    };
    let specs = indices
        .elems
        .iter()
        .map(index_spec)
        .collect::<Option<Vec<_>>>()?;
    Some((base, specs))
}

fn unwrap_receiver(expr: &Expr) -> &Expr {
    match strip_refs_groups(expr) {
        Expr::MethodCall(call) if call.method == "unwrap" && call.args.is_empty() => {
            unwrap_receiver(&call.receiver)
        }
        other => other,
    }
}

fn index_spec(expr: &Expr) -> Option<IndexSpec> {
    if let Some(index) = literal_index(expr) {
        return Some(IndexSpec::Element(index));
    }
    let Expr::Range(range) = strip_refs_groups(expr) else {
        return None;
    };
    let start = match &range.start {
        Some(start) => literal_index(start)?,
        None => 0,
    };
    let end = literal_index(range.end.as_ref()?)?;
    if end < start {
        return None;
    }
    let len = match range.limits {
        RangeLimits::HalfOpen(_) => end.checked_sub(start)?,
        RangeLimits::Closed(_) => end.checked_sub(start)?.checked_add(1)?,
    };
    Some(IndexSpec::Slice { start, len })
}

fn literal_index(expr: &Expr) -> Option<usize> {
    let Expr::Lit(lit) = strip_refs_groups(expr) else {
        return None;
    };
    let Lit::Int(i) = &lit.lit else {
        return None;
    };
    usize::try_from(parse_int_lit(i).ok()?).ok()
}

fn mut_reference_target(expr: &Expr) -> Option<String> {
    match strip_refs_groups(expr) {
        Expr::Reference(reference) if reference.mutability.is_some() => {
            simple_path_name(&reference.expr)
        }
        _ => None,
    }
}

fn cell_reference_target(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Reference(reference) => simple_path_name(&reference.expr),
        Expr::Paren(paren) => cell_reference_target(&paren.expr),
        Expr::Group(group) => cell_reference_target(&group.expr),
        _ => None,
    }
}

fn cell_constructor_arg(expr: &Expr) -> Option<(CellKind, &Expr)> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.args.len() != 1 {
        return None;
    }
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    let mut segments = path.path.segments.iter().rev();
    let method = segments.next()?.ident.to_string();
    if method != "new" {
        return None;
    }
    let ty = segments.next()?.ident.to_string();
    let kind = match ty.as_str() {
        "Cell" => CellKind::Cell,
        "RefCell" => CellKind::RefCell,
        _ => return None,
    };
    Some((kind, call.args.first()?))
}

fn refcell_borrow_mut_assignment_target(lhs: &Expr) -> Option<String> {
    let Expr::Unary(unary) = strip_refs_groups(lhs) else {
        return None;
    };
    if !matches!(unary.op, UnOp::Deref(_)) {
        return None;
    }
    let Expr::MethodCall(call) = strip_refs_groups(&unary.expr) else {
        return None;
    };
    (call.method == "borrow_mut" && call.args.is_empty()).then(|| ())?;
    simple_path_name(&call.receiver)
}

fn simple_pat_binding(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(ident) if ident.by_ref.is_none() && ident.subpat.is_none() => {
            Some(ident.ident.to_string())
        }
        Pat::Type(typed) => simple_pat_binding(&typed.pat),
        Pat::Paren(paren) => simple_pat_binding(&paren.pat),
        _ => None,
    }
}

fn slice_pat_bindings(pat: &Pat) -> Option<Vec<String>> {
    let Pat::Slice(slice) = strip_pat(pat) else {
        return None;
    };
    slice.elems.iter().map(simple_pat_binding).collect()
}

fn strip_pat(pat: &Pat) -> &Pat {
    match pat {
        Pat::Type(typed) => strip_pat(&typed.pat),
        Pat::Paren(paren) => strip_pat(&paren.pat),
        _ => pat,
    }
}

fn is_nonzero_new_call(func: &Expr) -> bool {
    let Expr::Path(path) = strip_refs_groups(func) else {
        return false;
    };
    if path.qself.is_some() || path.path.segments.len() < 2 {
        return false;
    }
    let mut segments = path.path.segments.iter().rev();
    let Some(method) = segments.next() else {
        return false;
    };
    let Some(ty) = segments.next() else {
        return false;
    };
    method.ident == "new" && ty.ident.to_string().starts_with("NonZero")
}

fn macro_name_is(mac: &syn::Macro, expected: &str) -> bool {
    mac.path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == expected)
}

fn int_expr(value: i128) -> Option<Expr> {
    syn::parse_str::<Expr>(&value.to_string()).ok()
}

/// Returns true if `expr` contains a path reference to `name`.
/// Used by `record_local` to detect self-referential shadowed bindings
/// like `let x = x + 1` before storing them in the temporal values map.
fn expr_references_name(expr: &Expr, name: &str) -> bool {
    match strip_refs_groups(expr) {
        Expr::Path(_) => simple_path_name(expr).as_deref() == Some(name),
        Expr::Binary(b) => {
            expr_references_name(&b.left, name) || expr_references_name(&b.right, name)
        }
        Expr::Unary(u) => expr_references_name(&u.expr, name),
        Expr::Cast(c) => expr_references_name(&c.expr, name),
        Expr::MethodCall(call) => {
            expr_references_name(&call.receiver, name)
                || call.args.iter().any(|a| expr_references_name(a, name))
        }
        Expr::Call(call) => call.args.iter().any(|a| expr_references_name(a, name)),
        Expr::Paren(p) => expr_references_name(&p.expr, name),
        Expr::Group(g) => expr_references_name(&g.expr, name),
        Expr::Reference(r) => expr_references_name(&r.expr, name),
        Expr::Range(r) => {
            r.start
                .as_ref()
                .is_some_and(|s| expr_references_name(s, name))
                || r.end
                    .as_ref()
                    .is_some_and(|e| expr_references_name(e, name))
        }
        _ => false,
    }
}

fn bool_term(value: bool) -> Rc<Term> {
    Rc::new(Term::Const {
        value: ConstValue::Bool(value),
        sort: Sort::bool(),
    })
}
