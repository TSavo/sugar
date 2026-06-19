// SPDX-License-Identifier: Apache-2.0
//
// `ForReplaySugar`: finite literal-loop temporal replay. This is for loops whose
// body is not a symbolic forall because it contains source state transitions
// (tuple destructuring, enum match, simple local updates), but every iteration is
// pinned by a closed finite domain and every value helper is visible source.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{and_, Formula, Term};
use syn::{BinOp, Expr, Lit, Pat, Stmt};

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::extract_if::{ExtractIfSugar, ReplayAction};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::insert::InsertSugar;
use crate::{
    const_fold_int_term, count_asserts_in_stmts, path_to_variant_string, simple_call_name,
    simple_pat_name, strip_refs_groups, substitute_expr, substitute_macro_tokens, term_as_int,
    translate_term_in_scope, AssertionFactKind, Desugared, Effect, ExprBindings, Outcome, Sugar,
    SugarCtx, Warrant, STRUCTURAL_BACKSTOP_REASON, SUGAR_SEQ_CAP,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "for_replay",
    SugarRole::Composite,
    SugarPriority::Primary,
    recognize,
);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::ForLoop(for_loop) = expr else {
        return None;
    };
    let Pat::Ident(var) = for_loop.pat.as_ref() else {
        return None;
    };
    if var.subpat.is_some() {
        return None;
    }
    if count_asserts_in_stmts(&for_loop.body.stmts) == 0 {
        return None;
    }
    if !range_domain_shape(&for_loop.expr) {
        return None;
    }
    if !body_has_replay_shape(&for_loop.body.stmts, fcx.scope()) {
        return None;
    }
    Some(Box::new(ForReplaySugar {
        var: var.ident.to_string(),
        domain: (*for_loop.expr).clone(),
        body_stmts: for_loop.body.stmts.clone(),
    }))
}

fn body_has_replay_shape(stmts: &[Stmt], scope: &crate::TemporalScope) -> bool {
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

pub(crate) struct ForReplaySugar {
    var: String,
    domain: Expr,
    body_stmts: Vec<Stmt>,
}

impl Sugar for ForReplaySugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let values = finite_range_values(&self.domain, ctx.scope)?;
            if values.is_empty() || values.len() as i64 > SUGAR_SEQ_CAP {
                return None;
            }
            let source_asserts = count_asserts_in_stmts(&self.body_stmts);
            if source_asserts == 0 {
                return None;
            }

            let mut atoms = Vec::new();
            for value in values {
                let mut replay = Replay::new(ctx);
                replay.bindings.insert(self.var.clone(), int_expr(value)?);
                replay.replay_stmts(&self.body_stmts)?;
                atoms.extend(replay.atoms);
            }
            if atoms.is_empty() {
                return None;
            }
            Some(Desugared::Constraints {
                atom: and_(atoms),
                n: source_asserts,
                kind: AssertionFactKind::Warranted,
                warrant: Warrant {
                    name: Some(format!("{}::loop::{}", ctx.scope.local_scope(), self.var)),
                },
            })
        })())
    }
}

struct Replay<'a, 'c, 's> {
    ctx: &'s SugarCtx<'a, 'c>,
    bindings: ExprBindings,
    atoms: Vec<Rc<Formula>>,
    extract_if: ExtractIfSugar,
    insert: InsertSugar,
}

impl<'a, 'c, 's> Replay<'a, 'c, 's> {
    fn new(ctx: &'s SugarCtx<'a, 'c>) -> Self {
        Self {
            ctx,
            bindings: ExprBindings::new(),
            atoms: Vec::new(),
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
                if count_asserts_in_expr_local(expr) == 0 {
                    Some(())
                } else {
                    let substituted = substitute_expr(expr, &self.bindings);
                    self.emit_constraint_expr(&substituted)
                }
            }
            Stmt::Item(_) => Some(()),
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
            Outcome::Dug(Desugared::Constraints {
                atom,
                kind: AssertionFactKind::Warranted,
                ..
            }) => {
                self.atoms.push(atom);
                Some(())
            }
            Outcome::Hit(Effect::Unsupported { reason })
                if reason == STRUCTURAL_BACKSTOP_REASON =>
            {
                None
            }
            _ => None,
        }
    }

    fn eval_expr(&self, expr: &Expr) -> Option<Expr> {
        let substituted = substitute_expr(expr, &self.bindings);
        match strip_refs_groups(&substituted) {
            Expr::Call(call) => self.eval_call(call).or(Some(substituted)),
            Expr::Match(expr_match) => self.eval_match_value(expr_match),
            _ => Some(substituted),
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
                BinOp::And(_) | BinOp::BitAnd(_) => Some(
                    self.expr_const_bool(&binary.left)? && self.expr_const_bool(&binary.right)?,
                ),
                BinOp::Or(_) | BinOp::BitOr(_) => Some(
                    self.expr_const_bool(&binary.left)? || self.expr_const_bool(&binary.right)?,
                ),
                BinOp::Eq(_) => {
                    Some(self.expr_const_int(&binary.left)? == self.expr_const_int(&binary.right)?)
                }
                BinOp::Ne(_) => {
                    Some(self.expr_const_int(&binary.left)? != self.expr_const_int(&binary.right)?)
                }
                BinOp::Lt(_) => {
                    Some(self.expr_const_int(&binary.left)? < self.expr_const_int(&binary.right)?)
                }
                BinOp::Le(_) => {
                    Some(self.expr_const_int(&binary.left)? <= self.expr_const_int(&binary.right)?)
                }
                BinOp::Gt(_) => {
                    Some(self.expr_const_int(&binary.left)? > self.expr_const_int(&binary.right)?)
                }
                BinOp::Ge(_) => {
                    Some(self.expr_const_int(&binary.left)? >= self.expr_const_int(&binary.right)?)
                }
                _ => None,
            },
            _ => {
                let term = translate_term_in_scope(&substituted, self.ctx.scope).ok()?;
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
        expr_const_int(&substitute_expr(expr, &self.bindings), self.ctx.scope)
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

fn finite_range_values(expr: &Expr, scope: &crate::TemporalScope) -> Option<Vec<i128>> {
    let Expr::Range(range) = strip_refs_groups(expr) else {
        return None;
    };
    let start = range
        .start
        .as_ref()
        .map(|expr| expr_const_int(expr, scope))
        .unwrap_or(Some(0))?;
    let end = expr_const_int(range.end.as_ref()?, scope)?;
    let high = if matches!(range.limits, syn::RangeLimits::Closed(_)) {
        end.checked_add(1)?
    } else {
        end
    };
    if high <= start || high - start > i128::from(SUGAR_SEQ_CAP) {
        return None;
    }
    Some((start..high).collect())
}

fn expr_const_int(expr: &Expr, scope: &crate::TemporalScope) -> Option<i128> {
    let term = translate_term_in_scope(expr, scope).ok()?;
    term_as_int(&term).or_else(|| const_fold_int_term(&term))
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
