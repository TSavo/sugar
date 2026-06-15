// SPDX-License-Identifier: Apache-2.0
//
// A CLOSED `try_fold` / `try_rfold` VALUE evaluator (T 2026-06-15).
//
// The 6 `coretests/tests/iter/adapters/{map,enumerate,filter_map}.rs` `try_fold`
// rows have the shape
//
//     assert_eq!(<seq-chain>.try_fold(INIT, f), <other-chain>.try_fold(INIT, f))
//
// where `<seq-chain>` is a CLOSED literal range threaded through pure adaptors
// (`map`/`enumerate`/`filter_map`), `INIT` is a literal, and `f` is a PURE closure
// returning `Option<_>` via a width-checked `T::checked_add(..)` (the `?` operator
// short-circuits to `None`). Both operands are a FINITE construction from source
// literals -- no runtime data -- so each side reduces to ONE concrete `Option<i*>`.
//
// This module symbolically executes that reduction, EXACT-OR-BAIL, and materializes
// the result back to a `Some(n)` / `None` literal `Expr`. The caller
// (`translate_term_in_scope`) then translates that literal through the ORDINARY term
// path: `Some(11250)` lifts to `Ctor("call:Some", [Int(11250)])`, so the outer
// `assert_eq!` becomes a GROUNDED equality `Some(a) == Some(b)`. The teeth follow
// for free from the existing ctor-equality semantics: a bad-twin whose side grounds
// to a DIFFERENT `Some(b)` is `call:Some[a] == call:Some[b]` with `a != b`, which is
// z3-UNSAT (a real refutation) -- byte-identical to the struct/enum-ctor teeth.
//
// SOUNDNESS (EXACT-OR-BAIL, the cardinal rule): every step is exact-or-`None`. The
// instant any piece is outside the certain set -- a non-literal endpoint, an opaque
// element, an unmodeled closure body, an arithmetic overflow at the DECLARED width,
// a division by zero, a mutable / unresolvable binding -- we return `None` and the
// operand stays in its existing (unclassified) refusal. A wrong BAIL is a safe
// under-claim; a wrong VALUE would be a fake-discharge, so we never guess. The
// arithmetic regime mirrors `const_eval`'s i128 carrier with an EXPLICIT
// per-operation width clamp (`i8`/`i32`/`usize`/...), because `T::checked_*`'s
// overflow boundary is exactly `T`'s range -- modeling it at the wrong width would
// be a fake-dig.

use std::collections::BTreeMap;

use syn::{Expr, ExprClosure, Pat};

use crate::{
    closure_single_param_ident, const_eval, const_int, strip_refs_groups, ConstVal,
    TemporalScope,
};

/// The maximum element count the evaluator will unroll (mirrors `SUGAR_SEQ_CAP`).
const TRY_FOLD_SEQ_CAP: usize = 4096;

/// The integer width a `T::checked_*` call computes in. The `checked_*` family
/// returns `None` exactly when the mathematical result is outside `T`'s range, so
/// modeling the overflow boundary requires the DECLARED width -- a wrong width would
/// be a fake-dig.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum IntWidth {
    I8,
    I16,
    I32,
    I64,
    I128,
    Isize,
    U8,
    U16,
    U32,
    U64,
    U128,
    Usize,
}

impl IntWidth {
    fn from_type_name(name: &str) -> Option<IntWidth> {
        Some(match name {
            "i8" => IntWidth::I8,
            "i16" => IntWidth::I16,
            "i32" => IntWidth::I32,
            "i64" => IntWidth::I64,
            "i128" => IntWidth::I128,
            "isize" => IntWidth::Isize,
            "u8" => IntWidth::U8,
            "u16" => IntWidth::U16,
            "u32" => IntWidth::U32,
            "u64" => IntWidth::U64,
            "u128" => IntWidth::U128,
            // `usize`/`isize` are platform-width; the sweep pins a 64-bit target
            // (`--rustc-cfg` carries `target_pointer_width = "64"`), and the corpus
            // values here are tiny, so the 64-bit range is exact for them. We still
            // clamp to the 64-bit range (never i128) so a value a 32-bit target
            // would reject is NOT silently accepted -- a safe under-claim.
            "usize" => IntWidth::Usize,
            _ => return None,
        })
    }

    /// Inclusive `[min, max]` of this width, in the i128 carrier. `usize`/`isize`
    /// use the 64-bit range (the sweep's pinned target).
    fn range(self) -> (i128, i128) {
        match self {
            IntWidth::I8 => (i8::MIN as i128, i8::MAX as i128),
            IntWidth::I16 => (i16::MIN as i128, i16::MAX as i128),
            IntWidth::I32 => (i32::MIN as i128, i32::MAX as i128),
            IntWidth::I64 | IntWidth::Isize => (i64::MIN as i128, i64::MAX as i128),
            IntWidth::I128 => (i128::MIN, i128::MAX),
            IntWidth::U8 => (0, u8::MAX as i128),
            IntWidth::U16 => (0, u16::MAX as i128),
            IntWidth::U32 => (0, u32::MAX as i128),
            IntWidth::U64 | IntWidth::Usize => (0, u64::MAX as i128),
            IntWidth::U128 => (0, u128::MAX as i128),
        }
    }

    /// `Some(v)` if `v` fits this width exactly; `None` (overflow -> the modeled
    /// `checked_*` returns `None`) otherwise.
    fn clamp(self, v: i128) -> Option<i128> {
        let (lo, hi) = self.range();
        if v >= lo && v <= hi {
            Some(v)
        } else {
            None
        }
    }
}

/// The result of one fold side: a concrete `Option<i128>` (the threaded accumulator,
/// or `None` from a `checked_*` short-circuit).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum FoldOutcome {
    Some(i128),
    None,
}

/// PUBLIC ENTRY. If `expr` is a CLOSED `try_fold` / `try_rfold` value-expression
/// over a finite literal-construction domain with a pure `checked_*` closure,
/// evaluate it EXACTLY and return the materialized `Some(n)` / `None` literal `Expr`.
/// `None` (bail) for any other shape / any non-exact piece -- the operand then stays
/// in its existing refusal (a safe under-claim).
pub(crate) fn eval_try_fold_operand(expr: &Expr, scope: &TemporalScope) -> Option<Expr> {
    let outcome = eval_try_fold(expr, scope)?;
    materialize(outcome)
}

/// Materialize a `FoldOutcome` to its `Some(n)` / `None` literal `Expr`.
fn materialize(outcome: FoldOutcome) -> Option<Expr> {
    let s = match outcome {
        FoldOutcome::Some(n) => format!("Some({n})"),
        FoldOutcome::None => "None".to_string(),
    };
    syn::parse_str::<Expr>(&s).ok()
}

/// Evaluate a `try_fold` / `try_rfold` method call to its concrete `FoldOutcome`, or
/// `None` (bail). Resolves the receiver chain to a finite element sequence, the init
/// to a literal, and the closure (possibly a `let`-bound `&|..|`), then threads the
/// `Option` accumulator with `?`-short-circuit.
fn eval_try_fold(expr: &Expr, scope: &TemporalScope) -> Option<FoldOutcome> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    let reverse = match call.method.to_string().as_str() {
        "try_fold" => false,
        "try_rfold" => true,
        _ => return None,
    };
    if call.args.len() != 2 {
        return None;
    }
    // INIT must be a literal integer (the accumulator start).
    let init = const_int(&call.args[0])?;
    // The closure: either an inline `|acc, x| ..` or a `let`-bound `&|acc, x| ..`.
    let closure = resolve_closure(&call.args[1], scope)?;
    // The element sequence the fold consumes (forward order; reversed below for rfold).
    let mut seq = eval_seq_chain(&call.receiver, scope)?;
    if seq.is_empty() || seq.len() > TRY_FOLD_SEQ_CAP {
        // An empty sequence makes the fold yield `Some(init)` with no closure call --
        // that IS exact, but the corpus rows are non-empty; keep the non-empty guard
        // conservative (bail on empty rather than risk a vacuous claim).
        return None;
    }
    if reverse {
        seq.reverse();
    }
    thread_fold(init, &seq, &closure, scope)
}

/// Resolve the second `try_fold` argument to its closure: an inline closure, a
/// parenthesised / reference-wrapped closure (`&|..|`), or a `let`-bound name whose
/// initializer is such a closure (`let f = &|..| ..;` then `try_fold(7, f)`). A
/// mutable binding is NOT resolved (it could be reassigned -> not a stable value).
fn resolve_closure(arg: &Expr, scope: &TemporalScope) -> Option<ExprClosure> {
    match strip_refs_groups(arg) {
        Expr::Closure(c) => Some(c.clone()),
        Expr::Path(p) => {
            let id = p.path.get_ident()?.to_string();
            if scope.is_mut_local(&id) {
                return None;
            }
            let init = scope.let_binding(&id)?;
            // Resolve one level (the corpus binds `let f = &|..|`); a binding to
            // another binding is uncommon and declined.
            match strip_refs_groups(init) {
                Expr::Closure(c) => Some(c.clone()),
                _ => None,
            }
        }
        _ => None,
    }
}

/// Build the finite element sequence the fold consumes, as a `Vec<ConstVal>`, by
/// interpreting the receiver adaptor chain over a CLOSED literal range. Supports the
/// closed set the corpus rows use: a base literal range, `.map(|x| <pure>)`,
/// `.enumerate()`, `.filter_map(|x| if .. { Some(<pure>) } else { None })`. A
/// `let`-bound receiver is resolved (immutable only). `None` (bail) for anything else.
fn eval_seq_chain(expr: &Expr, scope: &TemporalScope) -> Option<Vec<ConstVal>> {
    match strip_refs_groups(expr) {
        // Base case: a closed integer range `a..b` / `a..=b`.
        Expr::Range(r) => eval_range(r),
        // A `let`-bound receiver (`let it = (0..10).map(..); it.try_fold(..)`).
        Expr::Path(p) => {
            let id = p.path.get_ident()?.to_string();
            if scope.is_mut_local(&id) {
                return None;
            }
            let init = scope.let_binding(&id)?;
            eval_seq_chain(init, scope)
        }
        Expr::MethodCall(m) => {
            let method = m.method.to_string();
            match (method.as_str(), m.args.len()) {
                // Pass-through element-producing adaptors.
                ("iter" | "into_iter" | "cloned" | "copied" | "fuse" | "by_ref", 0) => {
                    eval_seq_chain(&m.receiver, scope)
                }
                ("rev", 0) => {
                    let mut s = eval_seq_chain(&m.receiver, scope)?;
                    s.reverse();
                    Some(s)
                }
                ("map", 1) => {
                    let c = resolve_closure(&m.args[0], scope)?;
                    let inner = eval_seq_chain(&m.receiver, scope)?;
                    let mut out = Vec::with_capacity(inner.len());
                    for v in inner {
                        out.push(eval_unary_closure(&c, &v)?);
                    }
                    Some(out)
                }
                ("enumerate", 0) => {
                    let inner = eval_seq_chain(&m.receiver, scope)?;
                    let mut out = Vec::with_capacity(inner.len());
                    for (i, v) in inner.into_iter().enumerate() {
                        out.push(ConstVal::Tuple(vec![ConstVal::Int(i as i128), v]));
                    }
                    Some(out)
                }
                ("filter_map", 1) => {
                    let c = resolve_closure(&m.args[0], scope)?;
                    let inner = eval_seq_chain(&m.receiver, scope)?;
                    let mut out = Vec::with_capacity(inner.len());
                    for v in inner {
                        // The filter_map closure returns `Option<_>`; evaluate it to a
                        // concrete `Some(_)`/`None` and keep the kept elements.
                        if let Some(kept) = eval_option_closure(&c, &v)? {
                            out.push(kept);
                        }
                    }
                    Some(out)
                }
                ("filter", 1) => {
                    let c = resolve_closure(&m.args[0], scope)?;
                    let inner = eval_seq_chain(&m.receiver, scope)?;
                    let mut out = Vec::with_capacity(inner.len());
                    for v in inner {
                        if eval_unary_closure(&c, &v)?.as_bool()? {
                            out.push(v);
                        }
                    }
                    Some(out)
                }
                _ => None,
            }
        }
        _ => None,
    }
}

/// Evaluate a closed integer range expression to its element `ConstVal::Int`s, EXACT-
/// OR-BAIL. Mirrors the `BoundedDomain::Range` arm of the `Sugar` floor.
fn eval_range(r: &syn::ExprRange) -> Option<Vec<ConstVal>> {
    // `const_eval` (not `const_int`) so a NEGATIVE literal bound (`-9..20`, a
    // `Unary(Neg, ..)` node) resolves -- `const_int` only accepts a bare int literal.
    let env = BTreeMap::new();
    let start = const_eval(r.start.as_deref()?, &env)?.as_int()?;
    let end_raw = const_eval(r.end.as_deref()?, &env)?.as_int()?;
    let inclusive = matches!(r.limits, syn::RangeLimits::Closed(_));
    let end = if inclusive { end_raw.checked_add(1)? } else { end_raw };
    if end < start || (end - start) > TRY_FOLD_SEQ_CAP as i128 {
        return None;
    }
    Some((start..end).map(ConstVal::Int).collect())
}

/// Apply a single-param closure `|p| <pure-body>` to a concrete element, returning the
/// resulting `ConstVal` (mirrors `const_eval_unary_closure`, but accepts a `&p` /
/// tuple-free pattern via `closure_single_param_ident`). EXACT-OR-BAIL.
fn eval_unary_closure(closure: &ExprClosure, arg: &ConstVal) -> Option<ConstVal> {
    if closure.inputs.len() != 1 {
        return None;
    }
    let param = closure_single_param_ident(&closure.inputs[0])?;
    let mut env = BTreeMap::new();
    env.insert(param, arg.clone());
    let body = closure_body_expr(closure)?;
    const_eval(body, &env)
}

/// Apply an `Option`-returning single-param closure `|p| if <cond> { Some(<pure>) }
/// else { None }` (the `filter_map` predicate) to a concrete element. Returns
/// `Some(Some(v))` (kept, value `v`), `Some(None)` (dropped), or `None` (bail -- an
/// unmodeled body). EXACT-OR-BAIL.
fn eval_option_closure(closure: &ExprClosure, arg: &ConstVal) -> Option<Option<ConstVal>> {
    if closure.inputs.len() != 1 {
        return None;
    }
    let param = closure_single_param_ident(&closure.inputs[0])?;
    let mut env = BTreeMap::new();
    env.insert(param, arg.clone());
    let body = closure_body_expr(closure)?;
    eval_option_expr(body, &env)
}

/// Evaluate an expression whose VALUE is an `Option` (`Some(<pure>)`, `None`, or an
/// `if <pure-cond> { <opt> } else { <opt> }`) to a concrete `Option<ConstVal>`.
/// `None` (bail) for any other shape. EXACT-OR-BAIL.
fn eval_option_expr(expr: &Expr, env: &BTreeMap<String, ConstVal>) -> Option<Option<ConstVal>> {
    match expr {
        Expr::Paren(p) => eval_option_expr(&p.expr, env),
        Expr::Group(g) => eval_option_expr(&g.expr, env),
        Expr::Block(b) => match b.block.stmts.as_slice() {
            [syn::Stmt::Expr(e, None)] => eval_option_expr(e, env),
            _ => None,
        },
        // `None` constructor.
        Expr::Path(p) if p.path.is_ident("None") => Some(None),
        // `Some(<pure>)`.
        Expr::Call(c) => {
            let Expr::Path(p) = &*c.func else { return None };
            if !p.path.is_ident("Some") || c.args.len() != 1 {
                return None;
            }
            Some(Some(const_eval(&c.args[0], env)?))
        }
        // `if <pure-cond> { <opt> } else { <opt> }`.
        Expr::If(if_expr) => {
            // A `let` condition (a pattern guard) is not a pure boolean: `const_eval`
            // returns `None` for `Expr::Let`, so the `as_bool()?` below bails -- no
            // separate shape pre-filter needed.
            let cond = const_eval(&if_expr.cond, env)?.as_bool()?;
            let then_opt = eval_option_block(&if_expr.then_branch, env)?;
            let else_branch = if_expr.else_branch.as_ref()?;
            let else_opt = eval_option_expr(&else_branch.1, env)?;
            Some(if cond { then_opt } else { else_opt })
        }
        _ => None,
    }
}

/// Evaluate a `{ <opt-expr> }` block to its `Option<ConstVal>` value.
fn eval_option_block(
    block: &syn::Block,
    env: &BTreeMap<String, ConstVal>,
) -> Option<Option<ConstVal>> {
    match block.stmts.as_slice() {
        [syn::Stmt::Expr(e, None)] => eval_option_expr(e, env),
        _ => None,
    }
}

/// Thread the `Option` accumulator over the element sequence, applying the fold
/// closure at each step with `?`-short-circuit. The closure body is a width-checked
/// `T::checked_*` call (returning `Option`) -- the single shape the corpus rows use.
/// Returns the final `FoldOutcome`, or `None` (bail) for any unmodeled closure shape.
fn thread_fold(
    init: i128,
    seq: &[ConstVal],
    closure: &ExprClosure,
    _scope: &TemporalScope,
) -> Option<FoldOutcome> {
    if closure.inputs.len() != 2 {
        return None;
    }
    // First param = accumulator (a plain ident). Second param = item: a plain ident
    // (whole element) OR a 2-tuple pattern `(i, x)` (an enumerate pair).
    let acc_var = closure_single_param_ident(&closure.inputs[0])?;
    let item_binder = parse_item_binder(&closure.inputs[1])?;
    let body = closure_body_expr(closure)?;

    let mut acc = init;
    for elem in seq {
        let mut env: BTreeMap<String, ConstVal> = BTreeMap::new();
        env.insert(acc_var.clone(), ConstVal::Int(acc));
        match &item_binder {
            ItemBinder::Whole(name) => {
                env.insert(name.clone(), elem.clone());
            }
            ItemBinder::Pair(c0, c1) => {
                let ConstVal::Tuple(parts) = elem else {
                    return None;
                };
                if parts.len() != 2 {
                    return None;
                }
                env.insert(c0.clone(), parts[0].clone());
                env.insert(c1.clone(), parts[1].clone());
            }
        }
        match eval_fold_step_body(body, &env)? {
            FoldOutcome::Some(next) => acc = next,
            FoldOutcome::None => return Some(FoldOutcome::None),
        }
    }
    Some(FoldOutcome::Some(acc))
}

/// The item-binder of a fold closure's second parameter.
enum ItemBinder {
    Whole(String),
    Pair(String, String),
}

fn parse_item_binder(pat: &Pat) -> Option<ItemBinder> {
    match pat {
        Pat::Tuple(t) if t.elems.len() == 2 => {
            let c0 = closure_single_param_ident(&t.elems[0])?;
            let c1 = closure_single_param_ident(&t.elems[1])?;
            Some(ItemBinder::Pair(c0, c1))
        }
        other => Some(ItemBinder::Whole(closure_single_param_ident(other)?)),
    }
}

/// Evaluate one fold-step body to a `FoldOutcome`. The corpus body is a width-checked
/// call `T::checked_op(<pure>, <pure>)` (the `?` in the source short-circuits the
/// whole fold; here the call ITSELF yields the `Option`, so a `None` step result is
/// the short-circuit). A `<pure>?` wrapper (`u8::checked_div(x, ..)?`) inside an
/// outer `checked_add` is handled by `eval_checked_call` recursively. EXACT-OR-BAIL.
fn eval_fold_step_body(body: &Expr, env: &BTreeMap<String, ConstVal>) -> Option<FoldOutcome> {
    eval_option_int_expr(body, env)
}

/// Evaluate an expression whose VALUE is an `Option<integer>` to a `FoldOutcome`.
/// Handles the `T::checked_*(a, b)` call family and a trailing `?` (`expr?` inside an
/// outer `checked_*`). The arguments are pure integer expressions (via `const_eval`),
/// EXCEPT that a nested `T::checked_*(..)?` argument is itself an `Option<int>` whose
/// `?` short-circuits. EXACT-OR-BAIL.
fn eval_option_int_expr(expr: &Expr, env: &BTreeMap<String, ConstVal>) -> Option<FoldOutcome> {
    match expr {
        Expr::Paren(p) => eval_option_int_expr(&p.expr, env),
        Expr::Group(g) => eval_option_int_expr(&g.expr, env),
        Expr::Block(b) => match b.block.stmts.as_slice() {
            [syn::Stmt::Expr(e, None)] => eval_option_int_expr(e, env),
            _ => None,
        },
        // `T::checked_op(a, b)` -> `Option<int>`.
        Expr::Call(_) => eval_checked_call(expr, env),
        // `Some(<pure-int>)` literal.
        // (Not in the corpus rows, but exact: `Some(x)` is `FoldOutcome::Some(x)`.)
        _ => None,
    }
}

/// Evaluate a `T::checked_op(a, b)` call (or a bare `Some(int)`) to a `FoldOutcome`.
/// `a` and `b` are evaluated as pure integers via `eval_int_arg` (which itself
/// resolves a nested `T::checked_*(..)?` short-circuit). The op is computed in the
/// i128 carrier then CLAMPED to `T`'s declared width -- a result outside the width is
/// the `checked_*` `None`. EXACT-OR-BAIL.
fn eval_checked_call(expr: &Expr, env: &BTreeMap<String, ConstVal>) -> Option<FoldOutcome> {
    let Expr::Call(c) = expr else { return None };
    // `Some(<pure-int>)`.
    if let Expr::Path(p) = &*c.func {
        if p.path.is_ident("Some") && c.args.len() == 1 {
            let v = const_eval(&c.args[0], env)?.as_int()?;
            return Some(FoldOutcome::Some(v));
        }
        if p.path.is_ident("None") {
            return Some(FoldOutcome::None);
        }
    }
    // `T::checked_op(a, b)` -- a qualified path `<width>::<op>`.
    let (width, op) = checked_path(&c.func)?;
    if c.args.len() != 2 {
        return None;
    }
    let a = eval_int_arg(&c.args[0], env)?;
    let b = eval_int_arg(&c.args[1], env)?;
    let (a, b) = match (a, b) {
        (Some(a), Some(b)) => (a, b),
        // A `?`-short-circuit in an argument propagates `None`.
        _ => return Some(FoldOutcome::None),
    };
    let raw = match op {
        CheckedOp::Add => a.checked_add(b)?,
        CheckedOp::Sub => a.checked_sub(b)?,
        CheckedOp::Mul => a.checked_mul(b)?,
        CheckedOp::Div => {
            if b == 0 {
                // `checked_div(_, 0)` is `None` (NOT a panic).
                return Some(FoldOutcome::None);
            }
            a.checked_div(b)?
        }
        CheckedOp::Rem => {
            if b == 0 {
                return Some(FoldOutcome::None);
            }
            a.checked_rem(b)?
        }
    };
    match width.clamp(raw) {
        Some(v) => Some(FoldOutcome::Some(v)),
        None => Some(FoldOutcome::None),
    }
}

/// Evaluate a fold-closure ARGUMENT to a pure integer. `Some(v)` is the value;
/// `Some(None)`... no: returns `Option<Option<i128>>` where the OUTER `Option` is
/// bail (unmodeled) and the INNER is the `?`-short-circuit (`None` = short-circuit).
/// A plain pure expression resolves via `const_eval` (always `Some(Some(v))`). A
/// `T::checked_*(..)?` argument is the inner `Option<int>` whose `None` short-circuits
/// the enclosing call. EXACT-OR-BAIL.
fn eval_int_arg(expr: &Expr, env: &BTreeMap<String, ConstVal>) -> Option<Option<i128>> {
    match expr {
        Expr::Paren(p) => eval_int_arg(&p.expr, env),
        Expr::Group(g) => eval_int_arg(&g.expr, env),
        // `<checked-call>?` -- the inner `Option<int>`'s `None` short-circuits.
        Expr::Try(t) => match eval_checked_call(&t.expr, env)? {
            FoldOutcome::Some(v) => Some(Some(v)),
            FoldOutcome::None => Some(None),
        },
        // A pure integer expression (`2 * acc`, `x / (i + 1) + i`, a literal, ...).
        _ => Some(Some(const_eval(expr, env)?.as_int()?)),
    }
}

/// The `checked_*` op of this fold-step call.
#[derive(Clone, Copy)]
enum CheckedOp {
    Add,
    Sub,
    Mul,
    Div,
    Rem,
}

/// Recognise a `<width>::checked_<op>` qualified path (`i32::checked_add`,
/// `usize::checked_div`, `u8::checked_add`, ...). Returns `(width, op)` or `None`.
fn checked_path(func: &Expr) -> Option<(IntWidth, CheckedOp)> {
    let Expr::Path(p) = func else { return None };
    let segs = &p.path.segments;
    if segs.len() != 2 {
        return None;
    }
    let width = IntWidth::from_type_name(&segs[0].ident.to_string())?;
    let op = match segs[1].ident.to_string().as_str() {
        "checked_add" => CheckedOp::Add,
        "checked_sub" => CheckedOp::Sub,
        "checked_mul" => CheckedOp::Mul,
        "checked_div" => CheckedOp::Div,
        "checked_rem" => CheckedOp::Rem,
        _ => return None,
    };
    Some((width, op))
}

/// The closure body as a single expression: a bare expr, or a block whose ONLY
/// statement is a trailing expression (no side-effecting `let`s). `None` (bail) for a
/// multi-statement body.
fn closure_body_expr(closure: &ExprClosure) -> Option<&Expr> {
    match &*closure.body {
        Expr::Block(b) => match b.block.stmts.as_slice() {
            [syn::Stmt::Expr(e, None)] => Some(e),
            _ => None,
        },
        other => Some(other),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;
    use syn::Stmt;

    /// Build a `TemporalScope` for `block_src` (a `{ .. }` body) and record its simple
    /// `let` bindings -- mirroring exactly what the lift loop does at each statement, so
    /// the evaluator resolves `let f = &|..|` / `let mp = &|..|` the same way it does in
    /// production. Returns the scope plus the parsed statements (so a caller can pick the
    /// operand expr out of an `assert_eq!`).
    fn scope_for(block_src: &str) -> (crate::TemporalScope, Vec<Stmt>) {
        let block: syn::Block = syn::parse_str(block_src).expect("block parses");
        let stmts = block.stmts;
        let plan = crate::temporal_plan_for_stmts(&stmts, &BTreeSet::new());
        let mut scope = crate::TemporalScope::new("test", plan);
        for s in &stmts {
            if let Stmt::Local(local) = s {
                if let (Some(name), Some(init)) =
                    (crate::let_simple_binding(&local.pat), local.init.as_ref())
                {
                    if init.diverge.is_none() {
                        scope.record_let_binding(&name, (*init.expr).clone());
                    }
                }
            }
        }
        (scope, stmts)
    }

    /// Evaluate a standalone `try_fold` / `try_rfold` VALUE expr `operand_src` in the
    /// scope of `block_src`'s `let` bindings, returning the materialized literal as a
    /// string (`"Some(11250)"` / `"None"`), or `None` (bail).
    fn ground(block_src: &str, operand_src: &str) -> Option<String> {
        let (scope, _stmts) = scope_for(block_src);
        let expr: Expr = syn::parse_str(operand_src).expect("operand parses");
        eval_try_fold_operand(&expr, &scope).map(|e| quote::quote!(#e).to_string())
    }

    // EVALUATOR-VALIDATION: the materialized ABSOLUTE value must equal the value real
    // Rust std computes (hand-computed and cross-checked by running the exact assertion
    // in a Rust playground). NOT merely LHS==RHS -- the concrete `Some(n)`. A wrong value
    // here would mean a fake-dig, so we pin the absolute output of EACH side of all 6
    // rows. (These are the 6 `coretests/.../{map,enumerate,filter_map}.rs` `try_fold`
    // rows; the closures are bound as in the source.)

    const MAP_LETS: &str = "{ let f = &|acc, x| i32::checked_add(2 * acc, x); }";
    const ENUM_LETS: &str =
        "{ let f = &|acc, (i, x)| usize::checked_add(2 * acc, x / (i + 1) + i); }";
    const FM_LETS: &str = "{ let mp = &|x| if 0 <= x && x < 10 { Some(x * 2) } else { None }; \
                            let f = &|acc, x| i32::checked_add(2 * acc, x); }";

    #[test]
    fn evaluator_matches_hand_computed_map_row() {
        // map.rs:6  (0..10).map(|x| x+3).try_fold(7, f)  ==  (3..13).try_fold(7, f)
        // Both sides = Some(11250) in real Rust (hand-computed, verified in a playground).
        assert_eq!(
            ground(MAP_LETS, "(0..10).map(|x| x + 3).try_fold(7, f)").as_deref(),
            Some("Some (11250)")
        );
        assert_eq!(
            ground(MAP_LETS, "(3..13).try_fold(7, f)").as_deref(),
            Some("Some (11250)")
        );
        // map.rs:7  try_rfold -> Some(18431) both sides.
        assert_eq!(
            ground(MAP_LETS, "(0..10).map(|x| x + 3).try_rfold(7, f)").as_deref(),
            Some("Some (18431)")
        );
        assert_eq!(
            ground(MAP_LETS, "(3..13).try_rfold(7, f)").as_deref(),
            Some("Some (18431)")
        );
    }

    #[test]
    fn evaluator_matches_hand_computed_enumerate_row() {
        // enumerate.rs:100  (9..18).enumerate().try_fold(7, f)
        //                    == (0..9).map(|i| (i, i + 9)).try_fold(7, f)  -> Some(7379)
        assert_eq!(
            ground(ENUM_LETS, "(9..18).enumerate().try_fold(7, f)").as_deref(),
            Some("Some (7379)")
        );
        assert_eq!(
            ground(ENUM_LETS, "(0..9).map(|i| (i, i + 9)).try_fold(7, f)").as_deref(),
            Some("Some (7379)")
        );
        // enumerate.rs:101  try_rfold -> Some(7961).
        assert_eq!(
            ground(ENUM_LETS, "(9..18).enumerate().try_rfold(7, f)").as_deref(),
            Some("Some (7961)")
        );
        assert_eq!(
            ground(ENUM_LETS, "(0..9).map(|i| (i, i + 9)).try_rfold(7, f)").as_deref(),
            Some("Some (7961)")
        );
    }

    #[test]
    fn evaluator_matches_hand_computed_filter_map_row() {
        // filter_map.rs:32  (-9..20).filter_map(mp).try_fold(7, f)
        //                    == (0..10).map(|x| 2 * x).try_fold(7, f)  -> Some(9194)
        assert_eq!(
            ground(FM_LETS, "(-9..20).filter_map(mp).try_fold(7, f)").as_deref(),
            Some("Some (9194)")
        );
        assert_eq!(
            ground(FM_LETS, "(0..10).map(|x| 2 * x).try_fold(7, f)").as_deref(),
            Some("Some (9194)")
        );
        // filter_map.rs:33  try_rfold -> Some(23556).
        assert_eq!(
            ground(FM_LETS, "(-9..20).filter_map(mp).try_rfold(7, f)").as_deref(),
            Some("Some (23556)")
        );
        assert_eq!(
            ground(FM_LETS, "(0..10).map(|x| 2 * x).try_rfold(7, f)").as_deref(),
            Some("Some (23556)")
        );
    }

    #[test]
    fn bad_twin_grounds_to_a_different_literal_refutable() {
        // The TEETH at the evaluator level: changing the RHS init (7 -> 8) makes the two
        // sides ground to DIFFERENT literals (Some(11250) vs Some(12274)). The downstream
        // `assert_eq!` then lifts `call:Some[11250] == call:Some[12274]`, which z3
        // REFUTES (UNSAT) -- a real refutation, not a vacuous pass. (The z3-UNSAT step
        // itself is exercised end-to-end in the assertion_lift discrimination tests.)
        let good = ground(MAP_LETS, "(3..13).try_fold(7, f)");
        let twin = ground(MAP_LETS, "(3..13).try_fold(8, f)");
        assert_eq!(good.as_deref(), Some("Some (11250)"));
        assert_eq!(twin.as_deref(), Some("Some (12274)"));
        assert_ne!(good, twin, "a genuinely unequal fold must ground differently");
    }

    #[test]
    fn runtime_mutable_iterator_receiver_bails() {
        // SOUNDNESS: a `let mut iter = ..; iter.try_fold(0, ..)` is RUNTIME data (the
        // iterator is advanced by `.next()`), NOT a closed construction. The evaluator
        // MUST bail (return None) so the row keeps its existing runtime classification --
        // it must never fabricate a value for an advanced iterator.
        let block = "{ let mut iter = (0..40).map(|x| x + 10); }";
        let (scope, _s) = scope_for(block);
        let expr: Expr = syn::parse_str("iter.try_fold(0, i8::checked_add)").unwrap();
        assert_eq!(eval_try_fold_operand(&expr, &scope), None);
    }

    #[test]
    fn overflow_at_declared_width_grounds_to_none() {
        // A `checked_add` whose result exceeds the DECLARED width yields `None` (the
        // checked-op short-circuit). `i8::checked_add(100, 100)` overflows i8 (max 127),
        // so a one-element fold over `[100]` with `|acc, x| i8::checked_add(acc, x)`
        // starting at 100 grounds to `None`. (Validates the width clamp -- a fake-dig
        // would compute 200 in i128 and wrongly ground Some(200).)
        let block = "{ let g = &|acc, x| i8::checked_add(acc, x); }";
        assert_eq!(
            ground(block, "(100..101).try_fold(100, g)").as_deref(),
            Some("None")
        );
        // The same fold at i32 width does NOT overflow -> Some(200).
        let block32 = "{ let g = &|acc, x| i32::checked_add(acc, x); }";
        assert_eq!(
            ground(block32, "(100..101).try_fold(100, g)").as_deref(),
            Some("Some (200)")
        );
    }
}
