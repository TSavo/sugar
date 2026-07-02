// SPDX-License-Identifier: Apache-2.0
//
// Backward WP propagation over a Rust function body via `syn` AST.
//
// Algorithm sketch (matches issue #368):
//   1. Locate every callsite to the named callee within `caller`.
//   2. For each callsite, the initial WP is the callee's precondition with
//      formal parameters substituted by the actual argument expressions
//      lifted to IR terms.
//   3. Walk backward through the surrounding statements. For each statement
//      `let x = e`, transform the WP via Dijkstra's substitution rule:
//        wp(let x = e, P) = P[e/x]
//   4. The walk terminates at the start of the function body. The WP at
//      that point is the proof obligation the caller's caller must discharge.
//   5. Each (statement, accumulated_WP) pair is one Arrival in the DAG.
//
// MVP limits (deferred to subsequent commits on #368):
//   - Only top-level `let` statements are recognized as allocations in the
//     outer-body backward walk; nested-block bindings are also walked now.
//   - if-statements strengthen the WP via condition-context capture.
//   - Only one callee per walk; multiple callees per body are walked
//     independently.

use sugar_ir_types::{IrFormula, IrTerm};
use syn::{Expr, ExprCall, ExprIf, ExprPath, ItemFn, Local, Pat, Stmt};

use crate::lift::lift_predicate;
use crate::term_boundary::{
    pattern_field_projection, pattern_index_projection, pattern_tuple_projection,
    pattern_tuple_struct_projection,
};
use crate::wp::{substitute_in_formula, Wp};

/// One step in the walk. Records the WP that holds at this AST location
/// after applying Dijkstra's transformation rule for the statement at
/// `kind`.
///
/// `stmt_index` is the position of the statement within the caller's
/// body (0-indexed); for `FunctionEntry` it is the body length, denoting
/// "before any statement." This is how the MVP attaches arrivals to
/// AST locations without depending on `proc_macro::Span::start()`,
/// which is unstable on stable rustc.
#[derive(Debug, Clone)]
pub struct Arrival {
    pub kind: ArrivalKind,
    pub stmt_index: usize,
    pub wp: Wp,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ArrivalKind {
    /// The WP demanded at the callsite (initial state of the walk, after
    /// substituting actual arguments for the callee's formals).
    Callsite { callee: String },
    /// A `let` binding statement encountered during the walk. The `name`
    /// is the bound variable; the WP recorded here is the WP AFTER
    /// applying `P[rhs/name]`.
    LetBinding { name: String },
    /// The function entry point. The WP at this arrival is the proof
    /// obligation for the function as a whole.
    FunctionEntry { fn_name: String },
}

/// One end-to-end walk: from a single callsite, backward through the
/// caller's body, terminating at the function entry. The arrivals list
/// is ordered from callsite (index 0) to entry (last index).
#[derive(Debug, Clone)]
pub struct CallsiteWalk {
    pub caller_name: String,
    pub callee_name: String,
    pub arrivals: Vec<Arrival>,
}

impl CallsiteWalk {
    /// The proof obligation the caller's caller must discharge.
    pub fn entry_wp(&self) -> &Wp {
        &self
            .arrivals
            .last()
            .expect("walk has at least one arrival")
            .wp
    }
}

/// Walk every callsite to `callee_name` inside `caller`, propagating the
/// callee's `precondition` backward through the caller's body to the
/// function entry. Returns one walk per callsite.
///
/// The callee's precondition is expressed as a WP over the callee's
/// formal parameter names (e.g. `x ≥ 10` for a callee `f(x: u32)`).
/// At each callsite, `formal_params[i]` is substituted by the lifted
/// IR term of the i-th actual argument expression.
pub fn walk_callsites_to_entry(
    caller: &ItemFn,
    callee_name: &str,
    formal_params: &[String],
    precondition: Wp,
) -> Vec<CallsiteWalk> {
    let caller_name = caller.sig.ident.to_string();
    let stmts: &[Stmt] = &caller.block.stmts;
    let mut walks = Vec::new();
    for (idx, stmt) in stmts.iter().enumerate() {
        for hit in find_callsites_with_context(stmt, callee_name) {
            // 1. Arity check: if formals and actuals disagree, the substitution
            //    would be misaligned and silently wrong. Skip with a warning so
            //    liveness is preserved (other callsites still walk).
            if formal_params.len() != hit.args.len() {
                eprintln!(
                    "sugar-walk: arity mismatch at {}→{} callsite \
                     (formals={}, actuals={}); skipping this callsite",
                    caller_name,
                    callee_name,
                    formal_params.len(),
                    hit.args.len()
                );
                continue;
            }
            // 1. Build the WP at the callsite by substituting formals -> actuals.
            let mut wp = precondition.clone().into_formula();
            for (formal, actual_expr) in formal_params.iter().zip(hit.args.iter()) {
                let actual_term = lift_expr_to_term(actual_expr);
                wp = substitute_in_formula(wp, formal, &actual_term);
            }
            // Premise the WP on every in-scope if-condition: if any of the
            // surrounding conditions failed, the callsite would not have
            // been reached, so the WP would not need to hold. Encode this
            // as `(c1 ∧ c2 ∧ ...) → wp` — the conditions are free posts
            // at the callsite, available as premises for substrate
            // discharge.
            if !hit.conditions.is_empty() {
                let premise = match hit.conditions.len() {
                    1 => hit.conditions[0].clone(),
                    _ => IrFormula::And {
                        operands: hit.conditions.clone(),
                    },
                };
                wp = IrFormula::Implies {
                    operands: vec![premise, wp],
                };
            }

            let mut arrivals = vec![Arrival {
                kind: ArrivalKind::Callsite {
                    callee: callee_name.to_string(),
                },
                stmt_index: idx,
                wp: Wp(wp.clone()),
            }];

            // 2a. Walk backward through inner-block let-bindings that
            //     precede this callsite inside nested blocks (if-branches,
            //     explicit blocks, etc.). These were collected during the
            //     forward traversal and stored innermost-first, so iterating
            //     them in order gives the correct backward substitution chain.
            for inner_prev in &hit.preceding_inner_stmts {
                if let Some(bindings) = let_binding(inner_prev) {
                    for (bound_name, bound_term) in bindings {
                        wp = substitute_in_formula(wp, &bound_name, &bound_term);
                        arrivals.push(Arrival {
                            kind: ArrivalKind::LetBinding { name: bound_name },
                            stmt_index: idx,
                            wp: Wp(wp.clone()),
                        });
                    }
                }
            }

            // 2b. Walk backward through the statements preceding this one
            //     in the outer (caller) body.
            for (prev_idx, prev) in stmts[..idx].iter().enumerate().rev() {
                if let Some(bindings) = let_binding(prev) {
                    // Destructuring lets emit multiple bindings per
                    // statement; substitute them in declaration order
                    // (left-to-right), and emit one arrival per binding.
                    for (bound_name, bound_term) in bindings {
                        wp = substitute_in_formula(wp, &bound_name, &bound_term);
                        arrivals.push(Arrival {
                            kind: ArrivalKind::LetBinding { name: bound_name },
                            stmt_index: prev_idx,
                            wp: Wp(wp.clone()),
                        });
                    }
                }
                // Non-let statements pass through without transformation in
                // the MVP (e.g. `println!()`). Side-effecting statements are
                // tracked in #368 stretch goals.
            }

            // 3. Function entry. `stmt_index = stmts.len()` denotes
            // "before any statement in the body."
            arrivals.push(Arrival {
                kind: ArrivalKind::FunctionEntry {
                    fn_name: caller_name.clone(),
                },
                stmt_index: stmts.len(),
                wp: Wp(wp),
            });

            walks.push(CallsiteWalk {
                caller_name: caller_name.clone(),
                callee_name: callee_name.to_string(),
                arrivals,
            });
        }
    }
    walks
}

// ----- internals -----

/// One callsite found during context-aware traversal: the actual
/// arguments at the callsite, plus the conjunction of in-scope
/// if-conditions (each tagged for the branch the callsite was found in,
/// already-negated where the callsite is in an else-branch).
///
/// `preceding_inner_stmts`: statements that precede this callsite inside
/// inner blocks (if-branches, explicit blocks, etc.), ordered innermost-
/// first. Each inner-block layer is prepended so that substitution applies
/// the innermost shadowing first — matching Dijkstra's substitution order
/// when walked in reverse.
///
/// Sir's framing: every if is a free post. When a callsite sits inside
/// `if cond { ... }`, `cond` is a premise the substrate has for free at
/// that callsite. The walk records these conditions so the substrate's
/// downstream discharge can use them.
#[derive(Debug, Clone)]
pub struct CallsiteHit {
    pub args: Vec<Expr>,
    pub conditions: Vec<IrFormula>,
    /// Let-binding statements from inner blocks that precede this callsite,
    /// innermost-first. These must be substituted before the outer-body
    /// statements during the backward walk.
    pub preceding_inner_stmts: Vec<Stmt>,
}

/// Find every callsite to `callee_name` reachable from `stmt`, descending
/// into if-statement branches and tracking the surrounding condition
/// context. The condition context flips sign when descending into the
/// else-branch: `if cond { then-region } else { else-region }` adds
/// `cond` to the then-region's context and `¬cond` to the else-region's.
fn find_callsites_with_context(stmt: &Stmt, callee_name: &str) -> Vec<CallsiteHit> {
    let mut hits = Vec::new();
    walk_stmt_for_callsites(
        stmt,
        callee_name,
        &mut Vec::new(),
        &mut Vec::new(),
        &mut hits,
    );
    hits
}

fn walk_stmt_for_callsites(
    stmt: &Stmt,
    callee_name: &str,
    conditions: &mut Vec<IrFormula>,
    inner_stmts: &mut Vec<Stmt>,
    hits: &mut Vec<CallsiteHit>,
) {
    let exprs: Vec<&Expr> = match stmt {
        Stmt::Local(local) => match &local.init {
            Some(init) => vec![init.expr.as_ref()],
            None => vec![],
        },
        Stmt::Expr(e, _) => vec![e],
        Stmt::Macro(_) | Stmt::Item(_) => vec![],
    };
    for expr in exprs {
        walk_expr_for_callsites(expr, callee_name, conditions, inner_stmts, hits);
    }
}

fn walk_expr_for_callsites(
    expr: &Expr,
    callee_name: &str,
    conditions: &mut Vec<IrFormula>,
    inner_stmts: &mut Vec<Stmt>,
    hits: &mut Vec<CallsiteHit>,
) {
    match expr {
        Expr::Call(ExprCall { func, args, .. }) => {
            // Direct call check at this expression.
            if let Expr::Path(ExprPath { path, .. }) = func.as_ref() {
                if path.segments.last().is_some_and(|s| s.ident == callee_name) {
                    hits.push(CallsiteHit {
                        args: args.iter().cloned().collect(),
                        conditions: conditions.clone(),
                        preceding_inner_stmts: inner_stmts.clone(),
                    });
                }
            }
            walk_expr_for_callsites(func, callee_name, conditions, inner_stmts, hits);
            // Recurse into argument expressions.
            for a in args {
                walk_expr_for_callsites(a, callee_name, conditions, inner_stmts, hits);
            }
        }
        Expr::MethodCall(m) => {
            // Method call `recv.foo(args)` is a callsite to `foo` if
            // foo matches callee_name. The receiver becomes the
            // implicit first argument (paper 07 normalizes
            // `Type::method(recv, args)`).
            if m.method == callee_name {
                let mut all_args: Vec<Expr> = vec![(*m.receiver).clone()];
                for a in &m.args {
                    all_args.push(a.clone());
                }
                hits.push(CallsiteHit {
                    args: all_args,
                    conditions: conditions.clone(),
                    preceding_inner_stmts: inner_stmts.clone(),
                });
            }
            // Recurse into receiver and args for nested callsites.
            walk_expr_for_callsites(&m.receiver, callee_name, conditions, inner_stmts, hits);
            for a in &m.args {
                walk_expr_for_callsites(a, callee_name, conditions, inner_stmts, hits);
            }
        }
        Expr::If(ExprIf {
            cond,
            then_branch,
            else_branch,
            ..
        }) => {
            // Lift the condition; if it doesn't lift to an IrFormula we
            // proceed without adding a context entry (the walker is
            // best-effort: missing conditions are equivalent to `true`).
            let lifted = lift_predicate(cond);
            // Then-branch: condition holds.
            if let Some(c) = &lifted {
                conditions.push(c.clone());
            }
            // For each statement in the then-branch, the preceding statements
            // in that branch are in-scope inner let-bindings. We push them
            // into inner_stmts as we advance through the block.
            for (branch_idx, s) in then_branch.stmts.iter().enumerate() {
                // Push preceding stmts from this branch (innermost-first,
                // reversed so the backward walk applies them in the right order).
                let mut branch_preceding: Vec<Stmt> = then_branch.stmts[..branch_idx]
                    .iter()
                    .rev()
                    .cloned()
                    .collect();
                branch_preceding.extend(inner_stmts.iter().cloned());
                // Save and restore the caller's inner_stmts across the
                // recursive descent — identical to the Block-arm pattern.
                let saved = inner_stmts.clone();
                *inner_stmts = branch_preceding;
                walk_stmt_for_callsites(s, callee_name, conditions, inner_stmts, hits);
                *inner_stmts = saved;
            }
            if lifted.is_some() {
                conditions.pop();
            }
            // Else-branch: ¬condition holds.
            if let Some((_, else_expr)) = else_branch {
                if let Some(c) = &lifted {
                    let negated = IrFormula::Not {
                        operands: vec![c.clone()],
                    };
                    conditions.push(negated);
                }
                walk_expr_for_callsites(else_expr, callee_name, conditions, inner_stmts, hits);
                if lifted.is_some() {
                    conditions.pop();
                }
            }
        }
        Expr::Block(b) => {
            for (block_idx, s) in b.block.stmts.iter().enumerate() {
                let mut block_preceding: Vec<Stmt> =
                    b.block.stmts[..block_idx].iter().rev().cloned().collect();
                block_preceding.extend(inner_stmts.iter().cloned());
                let saved = inner_stmts.clone();
                *inner_stmts = block_preceding;
                walk_stmt_for_callsites(s, callee_name, conditions, inner_stmts, hits);
                *inner_stmts = saved;
            }
        }
        Expr::Async(a) => {
            for (block_idx, s) in a.block.stmts.iter().enumerate() {
                let mut block_preceding: Vec<Stmt> =
                    a.block.stmts[..block_idx].iter().rev().cloned().collect();
                block_preceding.extend(inner_stmts.iter().cloned());
                let saved = inner_stmts.clone();
                *inner_stmts = block_preceding;
                walk_stmt_for_callsites(s, callee_name, conditions, inner_stmts, hits);
                *inner_stmts = saved;
            }
        }
        Expr::Const(c) => {
            for (block_idx, s) in c.block.stmts.iter().enumerate() {
                let mut block_preceding: Vec<Stmt> =
                    c.block.stmts[..block_idx].iter().rev().cloned().collect();
                block_preceding.extend(inner_stmts.iter().cloned());
                let saved = inner_stmts.clone();
                *inner_stmts = block_preceding;
                walk_stmt_for_callsites(s, callee_name, conditions, inner_stmts, hits);
                *inner_stmts = saved;
            }
        }
        // Loops: recurse into the body. The body's callsites are reachable
        // from the loop's pre-state; their conditions are unchanged from
        // outside the loop (we don't yet add loop-iteration invariants
        // here — that would require lift-side invariant inference; for
        // the MVP we walk the body once with the surrounding context).
        Expr::While(w) => {
            for s in &w.body.stmts {
                walk_stmt_for_callsites(s, callee_name, conditions, inner_stmts, hits);
            }
        }
        Expr::ForLoop(fl) => {
            for s in &fl.body.stmts {
                walk_stmt_for_callsites(s, callee_name, conditions, inner_stmts, hits);
            }
        }
        Expr::Loop(l) => {
            for s in &l.body.stmts {
                walk_stmt_for_callsites(s, callee_name, conditions, inner_stmts, hits);
            }
        }
        // Match arms: each arm's body sees its pattern's binding context.
        // For the MVP we descend into every arm's body without
        // narrowing the pattern as a predicate; the postcondition split
        // is captured separately in the lifter (lift_match_postcondition).
        Expr::Match(m) => {
            for arm in &m.arms {
                walk_expr_for_callsites(&arm.body, callee_name, conditions, inner_stmts, hits);
            }
        }
        // `?` operator: the success-path continues with the unwrapped
        // value. The MVP recurses into the wrapped expression to find
        // any callsites it contains.
        Expr::Try(t) => {
            walk_expr_for_callsites(&t.expr, callee_name, conditions, inner_stmts, hits);
        }
        Expr::Await(a) => {
            walk_expr_for_callsites(&a.base, callee_name, conditions, inner_stmts, hits);
        }
        // Return statements: recurse into the returned expression for
        // callsite discovery.
        Expr::Return(r) => {
            if let Some(inner) = &r.expr {
                walk_expr_for_callsites(inner, callee_name, conditions, inner_stmts, hits);
            }
        }
        Expr::Break(b) => {
            if let Some(inner) = &b.expr {
                walk_expr_for_callsites(inner, callee_name, conditions, inner_stmts, hits);
            }
        }
        Expr::Yield(y) => {
            if let Some(inner) = &y.expr {
                walk_expr_for_callsites(inner, callee_name, conditions, inner_stmts, hits);
            }
        }
        // Common compound expression forms that can contain callsites. We
        // recurse into their sub-expressions so a callsite inside
        // `foo() && callee(x) > 0` or `(callee(x), y)` is not silently
        // dropped (Bug #2).
        Expr::Binary(b) => {
            walk_expr_for_callsites(&b.left, callee_name, conditions, inner_stmts, hits);
            walk_expr_for_callsites(&b.right, callee_name, conditions, inner_stmts, hits);
        }
        Expr::Unary(u) => {
            walk_expr_for_callsites(&u.expr, callee_name, conditions, inner_stmts, hits);
        }
        Expr::Cast(c) => {
            walk_expr_for_callsites(&c.expr, callee_name, conditions, inner_stmts, hits);
        }
        Expr::Paren(p) => {
            walk_expr_for_callsites(&p.expr, callee_name, conditions, inner_stmts, hits);
        }
        Expr::Group(g) => {
            walk_expr_for_callsites(&g.expr, callee_name, conditions, inner_stmts, hits);
        }
        Expr::Reference(r) => {
            walk_expr_for_callsites(&r.expr, callee_name, conditions, inner_stmts, hits);
        }
        Expr::RawAddr(r) => {
            walk_expr_for_callsites(&r.expr, callee_name, conditions, inner_stmts, hits);
        }
        Expr::Field(f) => {
            walk_expr_for_callsites(&f.base, callee_name, conditions, inner_stmts, hits);
        }
        Expr::Index(i) => {
            walk_expr_for_callsites(&i.expr, callee_name, conditions, inner_stmts, hits);
            walk_expr_for_callsites(&i.index, callee_name, conditions, inner_stmts, hits);
        }
        Expr::Range(r) => {
            if let Some(start) = &r.start {
                walk_expr_for_callsites(start, callee_name, conditions, inner_stmts, hits);
            }
            if let Some(end) = &r.end {
                walk_expr_for_callsites(end, callee_name, conditions, inner_stmts, hits);
            }
        }
        Expr::Tuple(t) => {
            for elem in &t.elems {
                walk_expr_for_callsites(elem, callee_name, conditions, inner_stmts, hits);
            }
        }
        Expr::Array(a) => {
            for elem in &a.elems {
                walk_expr_for_callsites(elem, callee_name, conditions, inner_stmts, hits);
            }
        }
        Expr::Assign(a) => {
            walk_expr_for_callsites(&a.left, callee_name, conditions, inner_stmts, hits);
            walk_expr_for_callsites(&a.right, callee_name, conditions, inner_stmts, hits);
        }
        Expr::TryBlock(t) => {
            for (block_idx, s) in t.block.stmts.iter().enumerate() {
                let mut block_preceding: Vec<Stmt> =
                    t.block.stmts[..block_idx].iter().rev().cloned().collect();
                block_preceding.extend(inner_stmts.iter().cloned());
                let saved = inner_stmts.clone();
                *inner_stmts = block_preceding;
                walk_stmt_for_callsites(s, callee_name, conditions, inner_stmts, hits);
                *inner_stmts = saved;
            }
        }
        Expr::Let(l) => {
            walk_expr_for_callsites(&l.expr, callee_name, conditions, inner_stmts, hits);
        }
        Expr::Repeat(r) => {
            walk_expr_for_callsites(&r.expr, callee_name, conditions, inner_stmts, hits);
            walk_expr_for_callsites(&r.len, callee_name, conditions, inner_stmts, hits);
        }
        Expr::Struct(s) => {
            for field in &s.fields {
                walk_expr_for_callsites(&field.expr, callee_name, conditions, inner_stmts, hits);
            }
            if let Some(rest) = &s.rest {
                walk_expr_for_callsites(rest, callee_name, conditions, inner_stmts, hits);
            }
        }
        Expr::Unsafe(u) => {
            for (block_idx, s) in u.block.stmts.iter().enumerate() {
                let mut block_preceding: Vec<Stmt> =
                    u.block.stmts[..block_idx].iter().rev().cloned().collect();
                block_preceding.extend(inner_stmts.iter().cloned());
                let saved = inner_stmts.clone();
                *inner_stmts = block_preceding;
                walk_stmt_for_callsites(s, callee_name, conditions, inner_stmts, hits);
                *inner_stmts = saved;
            }
        }
        Expr::Closure(_) => {}
        Expr::Continue(_)
        | Expr::Infer(_)
        | Expr::Lit(_)
        | Expr::Macro(_)
        | Expr::Path(_)
        | Expr::Verbatim(_) => {}
        _ => panic!("sugar-walk WP walker refused unknown syn::Expr variant"),
    }
}

/// If `stmt` is a `let pat = expr;` binding, return one or more
/// (bound-name, bound-term) pairs. Single bindings (`let x = e`) yield
/// one pair; destructuring bindings (`let (a, b) = pair`,
/// `let Point { x, y } = p`, `let [a, b] = arr`) yield one pair per
/// bound name, with each name's term being a catalog projection of the
/// RHS routed through the IrTerm boundary.
fn let_binding(stmt: &Stmt) -> Option<Vec<(String, IrTerm)>> {
    match stmt {
        Stmt::Local(Local {
            pat,
            init: Some(init),
            ..
        }) => {
            let rhs = lift_expr_to_term(init.expr.as_ref());
            collect_pat_bindings(pat, rhs)
        }
        Stmt::Local(Local { init: None, .. })
        | Stmt::Expr(_, _)
        | Stmt::Item(_)
        | Stmt::Macro(_) => None,
    }
}

/// Walk a Pat tree, emitting one (name, projected-term) per bound name.
fn collect_pat_bindings(pat: &Pat, rhs: IrTerm) -> Option<Vec<(String, IrTerm)>> {
    let mut out = Vec::new();
    collect_into(pat, rhs, &mut out)?;
    if out.is_empty() {
        None
    } else {
        Some(out)
    }
}

fn collect_into(pat: &Pat, term: IrTerm, out: &mut Vec<(String, IrTerm)>) -> Option<()> {
    match pat {
        Pat::Ident(p) => {
            out.push((p.ident.to_string(), term));
            Some(())
        }
        Pat::Type(pt) => collect_into(&pt.pat, term, out),
        Pat::Wild(_) => Some(()), // `_` binds nothing
        Pat::Reference(r) => collect_into(&r.pat, term, out),
        Pat::Paren(p) => collect_into(&p.pat, term, out),
        Pat::Tuple(t) => {
            for (i, sub) in t.elems.iter().enumerate() {
                let projected = pattern_tuple_projection(&term, i);
                collect_into(sub, projected, out)?;
            }
            Some(())
        }
        Pat::TupleStruct(ts) => {
            for (i, sub) in ts.elems.iter().enumerate() {
                let projected = pattern_tuple_struct_projection(&term, i);
                collect_into(sub, projected, out)?;
            }
            Some(())
        }
        Pat::Struct(s) => {
            for field in &s.fields {
                let field_name = match &field.member {
                    syn::Member::Named(id) => id.to_string(),
                    syn::Member::Unnamed(idx) => idx.index.to_string(),
                };
                let projected = pattern_field_projection(&term, &field_name);
                collect_into(&field.pat, projected, out)?;
            }
            Some(())
        }
        Pat::Slice(s) => {
            for (i, sub) in s.elems.iter().enumerate() {
                let projected = pattern_index_projection(&term, i);
                collect_into(sub, projected, out)?;
            }
            Some(())
        }
        Pat::Const(_)
        | Pat::Lit(_)
        | Pat::Macro(_)
        | Pat::Or(_)
        | Pat::Path(_)
        | Pat::Range(_)
        | Pat::Rest(_)
        | Pat::Verbatim(_) => refuse_unsupported_pattern(pat),
        _ => panic!("sugar-walk WP pattern collector refused unknown syn::Pat variant"),
    }
}

fn refuse_unsupported_pattern(pat: &Pat) -> ! {
    panic!(
        "sugar-walk WP pattern collector refused unsupported syn::Pat shape {}; \
         route it through a catalog projection before accepting this binding",
        pat_kind(pat)
    )
}

fn pat_kind(pat: &Pat) -> &'static str {
    match pat {
        Pat::Const(_) => "Const",
        Pat::Ident(_) => "Ident",
        Pat::Lit(_) => "Lit",
        Pat::Macro(_) => "Macro",
        Pat::Or(_) => "Or",
        Pat::Paren(_) => "Paren",
        Pat::Path(_) => "Path",
        Pat::Range(_) => "Range",
        Pat::Reference(_) => "Reference",
        Pat::Rest(_) => "Rest",
        Pat::Slice(_) => "Slice",
        Pat::Struct(_) => "Struct",
        Pat::Tuple(_) => "Tuple",
        Pat::TupleStruct(_) => "TupleStruct",
        Pat::Type(_) => "Type",
        Pat::Verbatim(_) => "Verbatim",
        Pat::Wild(_) => "Wild",
        _ => "Unknown",
    }
}

/// Lift a Rust `syn::Expr` to a canonical `IrTerm`.
///
/// Delegates to `crate::lift::lift_expr_to_term` which handles binary ops,
/// field access, index, method calls, closures, casts, references, and more.
/// Falls back to a structurally-stable placeholder for shapes that cannot be
/// lifted semantically. The placeholder uses a fixed descriptor rather than
/// the pretty-printed token stream, so two syntactically-different but
/// semantically-equivalent expressions do not accidentally receive the same
/// placeholder key (and two different unsupported expressions still get
/// distinct placeholders via their structural position in the call chain —
/// the caller's formal name makes them distinct at the substitution level).
fn lift_expr_to_term(expr: &Expr) -> IrTerm {
    crate::lift::lift_expr_to_term(expr).unwrap_or_else(|| placeholder_term(expr))
}

fn placeholder_term(expr: &Expr) -> IrTerm {
    use quote::ToTokens;
    // Use a stable structural fingerprint. The token stream is still used
    // here as a last-resort human-readable trace, but callers go through
    // `lift_expr_to_term` first so common shapes never reach this path.
    crate::wp::var(format!("<expr:{}>", expr.to_token_stream()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lift::lift_function_precondition;
    use crate::wp::{atomic_ge, const_int, var};

    fn parse_fn(src: &str) -> ItemFn {
        let file: syn::File = syn::parse_str(src).expect("parses");
        file.items
            .into_iter()
            .find_map(|item| match item {
                syn::Item::Fn(f) => Some(f),
                // sugar-audit: not-mine(test-helper-search-ignores-non-function-items)
                _ => None,
            })
            .expect("function present")
    }

    fn term_json(term: &IrTerm) -> String {
        serde_json::to_string(term).expect("term serializes")
    }

    fn panic_text(result: std::thread::Result<Option<Vec<(String, IrTerm)>>>) -> String {
        match result {
            Ok(value) => panic!("expected pattern collector to refuse, got {value:?}"),
            Err(payload) => {
                if let Some(text) = payload.downcast_ref::<&str>() {
                    (*text).to_string()
                } else if let Some(text) = payload.downcast_ref::<String>() {
                    text.clone()
                } else {
                    "<non-string panic>".to_string()
                }
            }
        }
    }

    #[test]
    fn pattern_projection_boundary_helper_preserves_wire_shape() {
        let rhs = IrTerm::Var {
            name: "root".into(),
        };

        assert_eq!(
            crate::term_boundary::pattern_tuple_projection(&rhs, 1),
            IrTerm::Ctor {
                name: "tuple_proj".into(),
                args: vec![rhs.clone(), IrTerm::Var { name: ".1".into() }],
            }
        );
        assert_eq!(
            crate::term_boundary::pattern_tuple_struct_projection(&rhs, 2),
            IrTerm::Ctor {
                name: "tuple_struct_proj".into(),
                args: vec![rhs.clone(), IrTerm::Var { name: ".2".into() }],
            }
        );
        assert_eq!(
            crate::term_boundary::pattern_field_projection(&rhs, "x"),
            IrTerm::Ctor {
                name: "field".into(),
                args: vec![rhs.clone(), IrTerm::Var { name: ".x".into() }],
            }
        );
        assert_eq!(
            crate::term_boundary::pattern_index_projection(&rhs, 3),
            IrTerm::Ctor {
                name: "index".into(),
                args: vec![rhs, const_int(3)],
            }
        );
    }

    #[test]
    fn nested_destructure_projects_byte_identically() {
        let pat: Pat = syn::parse_quote!((Point { x, y }, [first, _, third]));
        let rhs = IrTerm::Var {
            name: "payload".into(),
        };
        let bindings = collect_pat_bindings(&pat, rhs).expect("nested pattern binds names");

        let keys: Vec<_> = bindings.iter().map(|(name, _)| name.as_str()).collect();
        assert_eq!(keys, ["x", "y", "first", "third"]);

        let x_term = term_json(&bindings[0].1);
        assert!(
            x_term.contains("\"tuple_proj\"") && x_term.contains("\"field\""),
            "struct inside tuple must be field(tuple_proj(payload, .0), .x): {x_term}"
        );
        let third_term = term_json(&bindings[3].1);
        assert!(
            third_term.contains("\"tuple_proj\"") && third_term.contains("\"index\""),
            "slice inside tuple must be index(tuple_proj(payload, .1), 2): {third_term}"
        );
    }

    #[test]
    fn unsupported_pattern_shape_refuses_loudly() {
        let pat: Pat = syn::parse_quote!([head, ..]);
        let rhs = IrTerm::Var { name: "arr".into() };

        let reason = panic_text(std::panic::catch_unwind(|| collect_pat_bindings(&pat, rhs)));

        assert!(
            reason.contains("refused unsupported syn::Pat shape Rest"),
            "unsupported pattern must be a loud refusal, got: {reason}"
        );
    }

    #[test]
    fn nested_block_let_binding_substituted_at_callsite() {
        // Bug #1: when the callsite is inside an `if` block, the inner
        // let-bindings preceding the callsite must be substituted.
        // `fn caller(x: u32) { if x > 5 { let y = 42u32; callee(y); } }`
        // At the `callee(y)` callsite, the walk must see `let y = 42` from
        // the inner block and substitute y → 42 in the precondition.
        let callee_src = r#"
            fn callee(x: u32) -> u32 {
                if x < 10 { panic!(); }
                x * 2
            }
        "#;
        let caller_src = r#"
            fn caller(x: u32) {
                if x > 5 {
                    let y: u32 = 42;
                    callee(y);
                }
            }
        "#;
        let callee_fn: ItemFn = parse_fn(callee_src);
        let caller_fn: ItemFn = parse_fn(caller_src);
        let pre = lift_function_precondition(&callee_fn);

        let walks = walk_callsites_to_entry(&caller_fn, "callee", &["x".to_string()], pre);

        assert_eq!(walks.len(), 1, "exactly one callsite found");
        let entry_wp = walks[0].entry_wp();
        let json = serde_json::to_string(entry_wp.as_formula()).unwrap();
        // After substituting y → 42 in the precondition `x ≥ 10`,
        // we get `42 ≥ 10` — the entry WP should be ground (no free vars).
        assert!(
            !json.contains("\"y\""),
            "y should be substituted away at entry: {}",
            json
        );
    }

    #[test]
    fn arity_mismatch_skips_callsite() {
        // Bug #4: when formals.len() != actuals.len(), the walk must
        // skip the mismatched callsite rather than silently truncating.
        let caller_src = r#"
            fn caller() {
                callee(1u32, 2u32);
            }
        "#;
        let caller_fn: ItemFn = parse_fn(caller_src);
        let pre = atomic_ge(var("x"), const_int(10));

        // One formal but two actuals — mismatch.
        let walks = walk_callsites_to_entry(&caller_fn, "callee", &["x".to_string()], pre);

        // The mismatched callsite must be skipped: zero walks returned.
        assert_eq!(
            walks.len(),
            0,
            "arity mismatch must skip the callsite (got {} walks)",
            walks.len()
        );
    }

    #[test]
    fn nested_if_inner_stmts_not_leaked_across_branches() {
        // Bug #1 (If-arm save/restore): when a nested `if` block processes its
        // then-branch, the inner_stmts state must be restored before descending
        // into the else-branch (or the next statement). Without the fix, the
        // broken `truncate(prev_len)` restored only to the pre-branch length,
        // but left the branch_preceding content in place for the outer caller.
        //
        // Concretely: a second callsite in the else-branch must NOT see the
        // let-bindings from the then-branch as preceding stmts.
        let caller_src = r#"
            fn caller(x: u32) {
                if x > 5 {
                    let y: u32 = 42;
                    callee(y);
                } else {
                    callee(x);
                }
            }
        "#;
        let caller_fn: ItemFn = parse_fn(caller_src);
        let pre = atomic_ge(var("x"), const_int(10));

        let walks = walk_callsites_to_entry(&caller_fn, "callee", &["x".to_string()], pre);

        assert_eq!(walks.len(), 2, "two callsites: one in then, one in else");
        // The else-branch callsite (second walk) must not have y substituted.
        // It only has `x` as its argument — the entry WP should still refer
        // to `x`, not to `42`.
        let else_entry = walks[1].entry_wp();
        let json = serde_json::to_string(else_entry.as_formula()).unwrap();
        assert!(
            json.contains("\"x\""),
            "else-branch entry WP should reference x, not be ground: {}",
            json
        );
    }

    #[test]
    fn callsite_inside_binary_expr_is_found() {
        // Bug #2: when a callsite appears inside a binary expression such as
        // `if callee(x) > 0 {}` or `let z = callee(x) + 1;`, the walk must
        // descend into both sides of the binary and find it. Before the fix
        // the `_ => {}` arm silently dropped these callsites.
        let caller_src = r#"
            fn caller(x: u32) {
                let z = callee(x) + 1;
            }
        "#;
        let caller_fn: ItemFn = parse_fn(caller_src);
        let pre = atomic_ge(var("x"), const_int(10));

        let walks = walk_callsites_to_entry(&caller_fn, "callee", &["x".to_string()], pre);

        assert_eq!(
            walks.len(),
            1,
            "callsite inside binary expr must be found (got {} walks)",
            walks.len()
        );
    }

    #[test]
    fn callsite_inside_paren_expr_is_found() {
        // Bug #2: callsite nested inside a parenthesized expression must
        // be discovered.
        let caller_src = r#"
            fn caller(x: u32) {
                let z = (callee(x));
            }
        "#;
        let caller_fn: ItemFn = parse_fn(caller_src);
        let pre = atomic_ge(var("x"), const_int(10));

        let walks = walk_callsites_to_entry(&caller_fn, "callee", &["x".to_string()], pre);

        assert_eq!(
            walks.len(),
            1,
            "callsite inside paren must be found (got {} walks)",
            walks.len()
        );
    }

    #[test]
    fn binary_expr_actual_lifts_semantically_not_by_tokens() {
        // Bug #3: when the actual argument is a binary expression like
        // `40u32 + 2`, the walk must lift it via `lift_expr_to_term`
        // to a structural Ctor("+", [40, 2]) rather than a token-string
        // placeholder. Two semantically-equivalent calls get distinct CIDs
        // (40+2 vs 2+40), but within one call the lifted term is stable.
        let caller_src = r#"
            fn caller() {
                callee(40u32 + 2u32);
            }
        "#;
        let caller_fn: ItemFn = parse_fn(caller_src);
        let pre = atomic_ge(var("x"), const_int(10));

        let walks = walk_callsites_to_entry(&caller_fn, "callee", &["x".to_string()], pre);

        assert_eq!(walks.len(), 1);
        let callsite_arrival = &walks[0].arrivals[0];
        let json = serde_json::to_string(callsite_arrival.wp.as_formula()).unwrap();
        // The lifted term should encode the + ctor, not a raw token string.
        assert!(
            json.contains("\"+\""),
            "binary arg should be lifted to Ctor(+, ...) not token string: {}",
            json
        );
        // Must not contain the "<expr:..." placeholder prefix.
        assert!(
            !json.contains("<expr:"),
            "binary arg must not use token-string placeholder: {}",
            json
        );
    }

    #[test]
    fn awaited_let_binding_reaches_later_consumer_pre_as_structural_seam() {
        let caller_src = r#"
            async fn caller() {
                let x = producer().await;
                consumer(x);
            }
        "#;
        let caller_fn: ItemFn = parse_fn(caller_src);
        let pre = atomic_ge(var("x"), const_int(6));

        let walks = walk_callsites_to_entry(&caller_fn, "consumer", &["x".to_string()], pre);

        assert_eq!(walks.len(), 1, "consumer callsite should be found");
        let entry_wp = walks[0].entry_wp();
        let json = serde_json::to_string(entry_wp.as_formula()).unwrap();
        assert!(
            json.contains("\"await\""),
            "await seam should survive let-substitution into consumer pre: {}",
            json
        );
        assert!(
            json.contains("\"producer\""),
            "producer call should survive under await seam: {}",
            json
        );
        assert!(
            !json.contains("\"x\""),
            "the local x should be substituted by producer().await: {}",
            json
        );
    }
}
