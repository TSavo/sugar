// SPDX-License-Identifier: Apache-2.0
//
// `AssignOpSugar`: temporal rewrite sugar for literal-backed state transitions.
//
// This owns statement shapes such as `x += 1`, `v[0] += 10`, and `*a += 100`
// when the receiver is already pinned to a literal value by the current
// `TemporalScope`. The statement itself is inert support; its meaning is that
// later path reads resolve through the rewritten source value.

use std::collections::BTreeMap;
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
        Outcome::Dug(Desugared::Constraints {
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
    unknown_consumed_iterators: BTreeMap<String, String>,
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
    Element { base: String, index: usize },
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

impl TemporalRewriteState {
    pub(crate) fn expr_for(&self, name: &str) -> Option<Expr> {
        if self.unknown_consumed_iterators.contains_key(name) {
            return None;
        }
        if let Some(expr) = self.values.get(name) {
            return Some(expr.clone());
        }
        match self.aliases.get(name)? {
            RewritePlace::Scalar(base) if !self.unknown_consumed_iterators.contains_key(base) => {
                self.values.get(base).cloned()
            }
            RewritePlace::Element { base, index }
                if !self.unknown_consumed_iterators.contains_key(base) =>
            {
                self.aggregate_element(base, *index)
            }
            RewritePlace::Scalar(_) | RewritePlace::Element { .. } => None,
            RewritePlace::Slice { .. } => None,
        }
    }

    pub(crate) fn unknown_iterator_consumption_reason(&self, name: &str) -> Option<String> {
        let method = self.unknown_consumed_iterators.get(name)?;
        Some(format!(
            "unknown iterator consumption for `{name}` via `{method}`: a prior \
             short-circuit iterator terminal advanced this mutable iterator by a \
             data-dependent count, so there is no single timeless source value to read \
             at the assertion; refused"
        ))
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
            .filter(|(name, _)| !self.unknown_consumed_iterators.contains_key(*name))
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
                .is_some_and(|init| self.apply_consumption_expr(&init.expr)),
            Stmt::Expr(expr, _) => self.apply_consumption_expr(expr),
            Stmt::Macro(stmt_macro) => self.apply_consumption_macro(&stmt_macro.mac),
            _ => false,
        }
    }

    fn apply_with_trace(&mut self, expr: &Expr, emit_trace: bool) -> bool {
        match strip_refs_groups(expr) {
            Expr::Assign(assign) => self.apply_assign(&assign.left, &assign.right, emit_trace),
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
                applied
            }
            Expr::Call(call) => {
                let mut applied = false;
                for arg in &call.args {
                    applied |= self.apply_consumption_expr(arg);
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
                self.apply_consumption_expr(&assign.left)
                    | self.apply_consumption_expr(&assign.right)
            }
            _ => false,
        }
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

        self.aliases.remove(&name);
        if let Some(value) = self.trackable_value(&init.expr) {
            debug!(
                target: "sugar_lift_rust_tests::temporal_rewrite",
                binding = name.as_str(),
                value = %token_key(&value),
                "temporal rewrite captured literal-backed local"
            );
            self.values.insert(name, value);
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
            });
        }
        match self.aliases.get(&base_name)? {
            RewritePlace::Slice { base, start, len } if idx < *len => Some(Target::Element {
                base: base.clone(),
                index: start.checked_add(idx)?,
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
            Target::Element { base, index } => self.set_aggregate_element(&base, index, value),
        }
    }

    fn target_expr(&self, target: &Target) -> Option<Expr> {
        match target {
            Target::Scalar(name) => self.values.get(name).cloned(),
            Target::Element { base, index } => self.aggregate_element(base, *index),
        }
    }

    fn aggregate_element(&self, base: &str, index: usize) -> Option<Expr> {
        let expr = self.values.get(base)?;
        let (_, elems) = aggregate_elems(expr)?;
        elems.get(index).cloned()
    }

    fn set_aggregate_element(&mut self, base: &str, index: usize, value: Expr) -> bool {
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
}

fn unknown_iterator_consumption(call: &syn::ExprMethodCall) -> bool {
    matches!(
        call.method.to_string().as_str(),
        "try_fold"
            | "try_rfold"
            | "try_for_each"
            | "try_find"
            | "find"
            | "find_map"
            | "position"
            | "rposition"
            | "all"
            | "any"
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
        Target::Element { base, index } => format!("{base}[{index}]"),
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

fn bool_term(value: bool) -> Rc<Term> {
    Rc::new(Term::Const {
        value: ConstValue::Bool(value),
        sort: Sort::bool(),
    })
}
