// SPDX-License-Identifier: Apache-2.0
//
// `IterTerminalSugar`: the iterator REDUCTION + POSITIONAL + EXTREMUM + PREDICATE
// terminals over a FINITE LITERAL domain. Each writes the EQUIVALENT FOL of its operation
// over the inner literal `Seq` -- the construction axiom applied to a terminal that
// collapses a sequence to a single value:
//
//   * `.sum()`     -> `num(Σ elements)`   (`[1,2,3,4,5].iter().sum()` -> `num(15)`)
//   * `.product()` -> `num(Π elements)`   (`[1,2,3,4,5].iter().product()` -> `num(120)`)
//   * `.count()`   -> `num(len)`          (`[1,2,3].iter().count()` -> `num(3)`)
//   * `.next()`    -> `Some(elem[0])`     (`[1,2,3].iter().next()` -> `opt:some(1)`)
//   * `.nth(k)`    -> `Some(elem[k])` or `None` past the end
//   * `.next_back()` / `.nth_back(k)` -> the same positional rule from the back
//   * `.last()`    -> `Some(elem[len-1])` (or `None` for the empty Seq)
//   * `.min()`     -> `Some(min element)` (`[3,1,2].iter().min()` -> `opt:some(1)`)
//   * `.max()`     -> `Some(max element)` (`[3,1,2].iter().max()` -> `opt:some(3)`)
//   * `.find(p)`   -> `Some(first elem where p)` or `None` (`opt:some`/`opt:none`)
//   * `.position(p)` -> `Some(index of first elem where p)` or `None`
//   * `.any(p)`    -> `bool(∨ p(elem))`   (`[1,2,3].iter().any(|x| *x>2)` -> `bool(true)`)
//   * `.all(p)`    -> `bool(∧ p(elem))`   (`[1,2,3].iter().all(|x| *x>0)` -> `bool(true)`)
//   * `.advance_by(n)` / `.advance_back_by(n)` -> `Ok(())` if `n <= len`, else
//     `Err(NonZero(n - len))` with the remaining count.
//
// THE EXTREMUM TERMINALS (`.min()`/`.max()`) fold to the min/max of the literal int
// elements and wrap that extremum via `MonadicSugar`'s `opt:some`; empty literal ranges
// ground to `opt:none`, while other empty literal domains still decline before reduction.
// THE PREDICATE-POSITIONAL terminals (`.find(p)`/`.position(p)`) const-evaluate the
// closure (the SAME `const_eval_unary_closure` floor `MapSugar`/`FilterSugar` use) over
// each literal element; `.find` grounds the FIRST satisfying element to `opt:some(elem)`,
// `.position` grounds its INDEX to `opt:some(idx)`, and no match grounds to `opt:none`.
// THE PREDICATE-BOOL terminals (`.any(p)`/`.all(p)`) const-evaluate the closure over each
// element and OR (`any`) / AND (`all`) the per-element bools to a GROUNDED bool const.
//
// This is the TERM-position node. It declares it comes before `method::recognize`, so a
// shape-matched terminal owns the source shape. Receiver ownership is decided at desugar
// time: a literal `Seq` reduces, a structural bail takes the factory gap path, and a
// named `Incomplete` propagates.
//
// THE POSITIONAL TERMINALS GROUND VIA `MonadicSugar`. The positional terminals return
// `Option<&T>`; we GROUND them to a `MonadicSugar` `Some(element)` / `None` constructed
// value (the reserved `opt:some`/`opt:none` ctor, an ALGEBRAIC DATATYPE in the IR->SMT
// compiler). `assert_eq!([1,2,3].iter().next(), Some(&1))` then composes as
// `eq(opt:some(1), opt:some(1))` -- both sides STRUCTURAL `Option` values, so z3 enforces
// constructor injectivity + distinctness. The bad twin `Some(&2)` is `eq(opt:some(1),
// opt:some(2))` -> z3-UNSAT (the teeth). This SUPERSEDES the old refusal: when `Some(_)`
// was lifted as the federated `call:eq:Some` EUF, a bad twin stayed z3-SAT (a FAKE-DIG),
// so the positional terminals had to stay opaque; with `MonadicSugar`'s ADT-backed
// `Option`/`Result` the bad-twin-UNSAT bar is met, so they ground honestly.
//
// THE HARD SOUNDNESS LINE. The node completes ONLY when the WHOLE receiver chain desugars to a
// LITERAL `Seq`. If the receiver desugar `Incomplete`s -- the base was an effect / runtime call /
// opaque collection (`someFileIo.iter()`, `make_ys().iter()`) -- the `Incomplete` is PROPAGATED
// VERBATIM. A literal element that is not an exact integer const (a float / string /
// opaque element) bails the whole reduction (EXACT-OR-GAP). There are no fake-completes:
// every grounded value carries the real reduction, so a wrong-expected twin is z3-UNSAT
// (the teeth), not a vacuously-satisfiable opaque accessor.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{make_var, num, ConstValue, Sort, Term};
use syn::{Expr, Stmt};
use tracing::debug;

use crate::sugar::factory::{
    build_composite, desugar_build_ctx, has_composite, CompositeFloor, SugarBody, SugarBuildCtx,
    TermFloor,
};
use crate::sugar::literal::EMPTY_DOMAIN_REASON;
use crate::sugar::method_family;
use crate::sugar::monadic;
use crate::sugar::sequence_floor::reduce_sequence_elem_term_floor;
use crate::sugar::term_dispatch::fold_int_terms;
use crate::{
    closure_adaptor_refusal, closure_body_is_side_effecting, closure_single_param_ident,
    const_eval_binary_option_closure, const_eval_unary_closure, const_fold_acc_update,
    const_fold_int_term, const_int, const_int_acc_init, const_val_term, parse_int_lit,
    refusal_disposition, simple_path_name, strip_refs_groups, token_key, ConstVal, Desugared,
    DesugaredElem, Disposition, Effect, Outcome, Sugar, SugarCtx, TemporalScope,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before("iter_terminal", &["method"], recognize);

/// Build a grounded boolean CONST term (`bool(b)`) for the `.any`/`.all` reductions. The
/// `Bool` sort meets the `assert_eq!(..., true)` RHS bool const structurally (z3 enforces
/// `true != false`), so a wrong-expected twin (`.any(..)` truly `true`, asserted `false`)
/// is z3-UNSAT -- the teeth. Mirrors the crate-private `bool_const` in `lib.rs`.
fn bool_term(b: bool) -> Rc<Term> {
    Rc::new(Term::Const {
        value: ConstValue::Bool(b),
        sort: Sort::bool(),
    })
}

/// Which terminal this node performs -- captured at construction from the method name.
enum Terminal {
    Sum,
    Product,
    Count,
    /// `.next()` -- the element at position 0 (or `None` for the empty Seq).
    Next,
    /// `.next_back()` -- the element at the final position (or `None` for the empty Seq).
    NextBack,
    /// `.nth(k)` -- the element at position `k` (or `None` past the end).
    Nth(usize),
    /// `.nth_back(k)` -- the element `k` from the back (or `None` past the end).
    NthBack(usize),
    /// `.last()` -- the element at position `len-1` (or `None` for the empty Seq).
    Last,
    /// `.min()` -- the minimum int element wrapped in `Some` (or `None` for empty ranges).
    Min,
    /// `.max()` -- the maximum int element wrapped in `Some`.
    Max,
    /// `.any(pred)` -- the OR of the per-element const-evaluated predicate bools.
    Any(syn::ExprClosure),
    /// `.all(pred)` -- the AND of the per-element const-evaluated predicate bools.
    All(syn::ExprClosure),
    /// `.find(pred)` -- the FIRST element satisfying `pred`, wrapped in `Some` (or `None`).
    Find(syn::ExprClosure),
    /// `.position(pred)` -- the INDEX of the first element satisfying `pred`, wrapped in
    /// `Some` (or `None`).
    Position(syn::ExprClosure),
    /// `.advance_by(n)` / `.advance_back_by(n)` -- a direct terminal over an immutable
    /// literal-domain iterator. The returned `Result<(), NonZero<usize>>` is structural:
    /// `Ok(())` when the iterator can advance fully, else `Err(remaining)`.
    AdvanceBy(Expr),
    /// `.reduce(|acc, x| expr)` -- fold with element[0] as the initial accumulator,
    /// returning `Option<T>`: `Some(result)` for a non-empty source, `None` for empty.
    /// The closure has the SAME type for both parameters (unlike `.fold(init, |acc, x|
    /// ...)`); the body is const-evaluated with `acc` and `x` bound at each step.
    Reduce(syn::ExprClosure),
    /// `.fold(init, |acc, x| expr)` -- fold from an explicit initializer and return the
    /// final accumulator value directly.
    Fold(Expr, syn::ExprClosure),
    /// `.try_fold(init, f)` / `.try_rfold(init, f)` -- fold from an explicit initializer
    /// through an `Option`-returning closure, short-circuiting to `None` or completing
    /// to `Some(acc)`.
    TryFold {
        init: Expr,
        func: Expr,
        reverse: bool,
    },
}

impl Terminal {
    fn returns_monadic_value(&self) -> bool {
        matches!(
            self,
            Terminal::Next
                | Terminal::NextBack
                | Terminal::Nth(_)
                | Terminal::NthBack(_)
                | Terminal::Last
                | Terminal::Min
                | Terminal::Max
                | Terminal::Find(_)
                | Terminal::Position(_)
                | Terminal::AdvanceBy(_)
                | Terminal::Reduce(_)
                | Terminal::TryFold { .. }
        )
    }
}

/// TERM recognizer for the iterator scalar-reduction terminals. `Some` only when the
/// method is a recognized reduction. Recognition captures the raw receiver only; the
/// receiver chain is composed to a literal `Seq` lazily in `desugar`, where the live SSA
/// binding/temporal context exists. Any receiver that cannot compose to a text-determined
/// sequence structurally bails to the factory gap path, while named receiver
/// `Incomplete`s propagate.
///
/// The soundness line is the receiver `Outcome`: a `Complete(Seq)` is the only path to a
/// grounded value; a named `Incomplete` poisons the terminal and propagates; a structural bail
/// stays structural. So the node can only ever ground-with-teeth, propagate a real boundary,
/// or gap -- never reduce-to-maybe-wrong.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let terminal = recognize_terminal(call)?;
    if !recognized_receiver_is_static_sequence(call, &terminal, fcx) {
        return None;
    }
    let advance_by_arg = advance_by_arg_body(&terminal, fcx);
    Some(Box::new(IterTerminalSugar {
        terminal,
        site_key: token_key(expr),
        closure_refusal: closure_adaptor_refusal(expr, fcx.scope()),
        receiver: IterTerminalReceiver::new((*call.receiver).clone()),
        advance_by_arg,
        let_inits: capture_let_inits(fcx),
    }))
}

fn recognized_receiver_is_static_sequence(
    call: &syn::ExprMethodCall,
    terminal: &Terminal,
    fcx: &SugarBuildCtx,
) -> bool {
    if let Terminal::Fold(_, closure) = terminal {
        if !fold_terminal_body_is_value_only(closure) {
            return false;
        }
    }
    if matches!(terminal, Terminal::Count) && receiver_is_chunk_window_shape(&call.receiver, fcx, 0)
    {
        return true;
    }
    if matches!(terminal, Terminal::Any(_) | Terminal::All(_)) && has_composite(&call.receiver, fcx)
    {
        return true;
    }
    // Bare-path `next`/`next_back` still belong to the cursor replay lane when
    // the receiver is literal-backed. `try_fold` consumes a cursor without
    // modeling the residual state here, so a direct local receiver must fall
    // through until a temporal sugar owns that rewrite.
    if terminal_consumes_cursor_without_replay(terminal)
        && direct_unrewritten_path_receiver(&call.receiver)
    {
        return false;
    }
    if direct_bound_cursor_receiver(&call.receiver, fcx) {
        return true;
    }
    receiver_resolves_static_sequence(&call.receiver, fcx, 0)
}

fn terminal_consumes_cursor_without_replay(terminal: &Terminal) -> bool {
    matches!(terminal, Terminal::TryFold { .. })
}

fn direct_unrewritten_path_receiver(expr: &Expr) -> bool {
    simple_path_name(expr).is_some()
}

fn direct_bound_cursor_receiver(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    let Some(name) = simple_path_name(expr) else {
        return false;
    };
    fcx.scope().temporal_rewrite_expr_for(&name).is_some()
        || fcx
            .scope()
            .unknown_iterator_consumption_reason(&name)
            .is_some()
        || fcx.scope().is_consumed_iterator_local(&name)
        || fcx.scope().is_mut_local(&name)
        || fcx.let_inits().contains_key(&name)
        || fcx.scope().stable_let_binding_for_term(&name).is_some()
}

fn receiver_is_chunk_window_shape(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::MethodCall(call) if call.args.len() == 1 => {
            const_int(&call.args[0]).is_some_and(|n| n > 0)
                && matches!(
                    call.method.to_string().as_str(),
                    "chunks"
                        | "chunks_mut"
                        | "chunks_exact"
                        | "chunks_exact_mut"
                        | "rchunks"
                        | "rchunks_mut"
                        | "rchunks_exact"
                        | "rchunks_exact_mut"
                        | "windows"
                )
        }
        Expr::Path(_) => simple_path_name(expr)
            .and_then(|name| {
                fcx.scope().temporal_rewrite_expr_for(&name).or_else(|| {
                    fcx.let_inits()
                        .get(&name)
                        .copied()
                        .or_else(|| fcx.scope().replayable_let_binding_for_source(&name))
                        .cloned()
                })
            })
            .is_some_and(|current| receiver_is_chunk_window_shape(&current, fcx, depth + 1)),
        Expr::Reference(reference) => {
            receiver_is_chunk_window_shape(&reference.expr, fcx, depth + 1)
        }
        Expr::Paren(paren) => receiver_is_chunk_window_shape(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => receiver_is_chunk_window_shape(&group.expr, fcx, depth + 1),
        _ => false,
    }
}

fn resolve_chunk_window_receiver<'a>(
    expr: &Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    scope: &'a TemporalScope,
    depth: usize,
) -> Option<Expr> {
    if depth > 8 {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::MethodCall(call)
            if call.args.len() == 1
                && const_int(&call.args[0]).is_some_and(|n| n > 0)
                && matches!(
                    call.method.to_string().as_str(),
                    "chunks"
                        | "chunks_mut"
                        | "chunks_exact"
                        | "chunks_exact_mut"
                        | "rchunks"
                        | "rchunks_mut"
                        | "rchunks_exact"
                        | "rchunks_exact_mut"
                        | "windows"
                ) =>
        {
            Some(expr.clone())
        }
        Expr::Path(_) => {
            let name = simple_path_name(expr)?;
            let current = scope
                .temporal_rewrite_expr_for(&name)
                .or_else(|| let_inits.get(&name).map(|init| (*init).clone()))
                .or_else(|| scope.replayable_let_binding_for_source(&name).cloned())?;
            resolve_chunk_window_receiver(&current, let_inits, scope, depth + 1)
        }
        Expr::Reference(reference) => {
            resolve_chunk_window_receiver(&reference.expr, let_inits, scope, depth + 1)
        }
        Expr::Paren(paren) => {
            resolve_chunk_window_receiver(&paren.expr, let_inits, scope, depth + 1)
        }
        Expr::Group(group) => {
            resolve_chunk_window_receiver(&group.expr, let_inits, scope, depth + 1)
        }
        _ => None,
    }
}

fn receiver_resolves_static_sequence(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    if receiver_has_unreplayable_iterator_source(expr, fcx, depth) {
        return false;
    }
    if recognizes_scan_inner(expr, fcx)
        || method_family::resolves_literal_sequence(expr, fcx.let_inits())
        || crate::resolves_literal_sequence_in_scope(expr, fcx)
        || receiver_has_static_sequence_len(expr, fcx, depth)
        || stable_monadic_terminal_receiver(expr, fcx, depth)
    {
        return true;
    }
    if let Some(active) = const_resolved_if_sequence_tail(expr, fcx) {
        return receiver_resolves_static_sequence(active, fcx, depth + 1);
    }
    let Some(name) = simple_path_name(expr) else {
        return false;
    };
    if let Some(current) = fcx.scope().temporal_rewrite_expr_for(&name) {
        return receiver_resolves_static_sequence(&current, fcx, depth + 1);
    }
    if fcx
        .scope()
        .unknown_iterator_consumption_reason(&name)
        .is_some()
        || fcx.scope().is_consumed_iterator_local(&name)
    {
        return false;
    }
    fcx.let_inits()
        .get(&name)
        .copied()
        .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
        .is_some_and(|current| receiver_resolves_static_sequence(current, fcx, depth + 1))
}

fn receiver_has_unreplayable_iterator_source(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    depth: usize,
) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Path(_) => simple_path_name(expr).is_some_and(|name| {
            fcx.scope().temporal_rewrite_expr_for(&name).is_none()
                && (fcx.scope().is_mut_local(&name)
                    || fcx
                        .scope()
                        .unknown_iterator_consumption_reason(&name)
                        .is_some()
                    || fcx.scope().is_consumed_iterator_local(&name))
        }),
        Expr::MethodCall(call) => {
            receiver_has_unreplayable_iterator_source(&call.receiver, fcx, depth + 1)
        }
        Expr::Reference(reference) => {
            receiver_has_unreplayable_iterator_source(&reference.expr, fcx, depth + 1)
        }
        Expr::Paren(paren) => {
            receiver_has_unreplayable_iterator_source(&paren.expr, fcx, depth + 1)
        }
        Expr::Group(group) => {
            receiver_has_unreplayable_iterator_source(&group.expr, fcx, depth + 1)
        }
        _ => false,
    }
}

fn const_resolved_if_sequence_tail<'a>(expr: &'a Expr, fcx: &SugarBuildCtx) -> Option<&'a Expr> {
    let Expr::If(if_expr) = strip_refs_groups(expr) else {
        return None;
    };
    let active_then = crate::const_fold_bool_guard(&if_expr.cond, fcx.options())?;
    if active_then {
        return single_expr_tail(&if_expr.then_branch.stmts);
    }
    let (_, else_expr) = if_expr.else_branch.as_ref()?;
    match strip_refs_groups(else_expr) {
        Expr::Block(block) => single_expr_tail(&block.block.stmts),
        Expr::If(_) => Some(else_expr),
        _ => None,
    }
}

fn single_expr_tail(stmts: &[Stmt]) -> Option<&Expr> {
    match stmts {
        [Stmt::Expr(expr, None)] => Some(expr),
        _ => None,
    }
}

fn receiver_has_static_sequence_len(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    method_family::literal_sequence_static_len_in_scope(expr, fcx.let_inits(), fcx.scope())
        .is_some()
        || method_family::literal_collection_adapter_static_len_in_scope(
            expr,
            fcx.let_inits(),
            fcx.scope(),
        )
        .is_some()
        || simple_path_name(expr)
            .and_then(|name| fcx.scope().temporal_rewrite_expr_for(&name))
            .is_some_and(|current| receiver_has_static_sequence_len(&current, fcx, depth + 1))
}

fn fold_terminal_body_is_value_only(closure: &syn::ExprClosure) -> bool {
    match strip_refs_groups(&closure.body) {
        Expr::Block(block) => matches!(block.block.stmts.as_slice(), [Stmt::Expr(_, None)]),
        _ => true,
    }
}

pub(crate) fn recognizes_monadic_terminal(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return false;
    };
    let Some(terminal) = recognize_terminal(call) else {
        return false;
    };
    let stable_receiver = stable_monadic_terminal_receiver(&call.receiver, fcx, 0);
    if !terminal.returns_monadic_value() || !stable_receiver {
        return false;
    }
    if let Some(name) = simple_path_name(&call.receiver) {
        if fcx.scope().is_consumed_iterator_local(&name)
            && fcx.scope().temporal_rewrite_expr_for(&name).is_none()
        {
            return false;
        }
    }
    stable_receiver
        || recognizes_scan_inner(&call.receiver, fcx)
        || has_composite(&call.receiver, fcx)
}

fn stable_monadic_terminal_receiver(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 16 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Array(_) | Expr::Range(_) => true,
        Expr::MethodCall(call) if call.args.is_empty() => {
            let method = call.method.to_string();
            matches!(
                method.as_str(),
                "iter"
                    | "into_iter"
                    | "cloned"
                    | "copied"
                    | "fuse"
                    | "peekable"
                    | "clone"
                    | "rev"
                    | "enumerate"
                    | "flatten"
                    | "to_vec"
                    | "as_slice"
                    | "to_owned"
                    | "into_vec"
            ) && stable_monadic_terminal_receiver(&call.receiver, fcx, depth + 1)
        }
        Expr::MethodCall(call) if call.args.len() == 1 => {
            let method = call.method.to_string();
            let arg_ok = match method.as_str() {
                "skip" | "take" | "step_by" => const_int(&call.args[0]).is_some(),
                "filter" | "map" | "filter_map" | "skip_while" | "take_while" | "inspect"
                | "flat_map" => matches!(strip_refs_groups(&call.args[0]), Expr::Closure(_)),
                _ => false,
            };
            arg_ok && stable_monadic_terminal_receiver(&call.receiver, fcx, depth + 1)
        }
        Expr::Call(call) if call.args.len() == 1 => {
            let Expr::Path(path) = call.func.as_ref() else {
                return false;
            };
            let is_into_iter = path
                .path
                .segments
                .last()
                .is_some_and(|seg| seg.ident == "into_iter")
                && path
                    .path
                    .segments
                    .iter()
                    .any(|seg| seg.ident == "IntoIterator");
            is_into_iter && stable_monadic_terminal_receiver(&call.args[0], fcx, depth + 1)
        }
        Expr::Path(_) => simple_path_name(expr)
            .and_then(|name| {
                if let Some(current) = fcx.scope().temporal_rewrite_expr_for(&name) {
                    return Some(current);
                }
                if fcx
                    .scope()
                    .unknown_iterator_consumption_reason(&name)
                    .is_some()
                    || fcx.scope().is_consumed_iterator_local(&name)
                {
                    return None;
                }
                fcx.let_inits()
                    .get(&name)
                    .copied()
                    .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
                    .cloned()
            })
            .is_some_and(|current| stable_monadic_terminal_receiver(&current, fcx, depth + 1)),
        _ => false,
    }
}

fn recognize_terminal(call: &syn::ExprMethodCall) -> Option<Terminal> {
    Some(match call.method.to_string().as_str() {
        // Scalar reductions, extremum terminals, and the nullary positional terminals
        // take no args.
        "sum" if call.args.is_empty() => Terminal::Sum,
        "product" if call.args.is_empty() => Terminal::Product,
        "count" if call.args.is_empty() => Terminal::Count,
        "next" if call.args.is_empty() => Terminal::Next,
        "next_back" if call.args.is_empty() => Terminal::NextBack,
        "last" if call.args.is_empty() => Terminal::Last,
        "min" if call.args.is_empty() => Terminal::Min,
        "max" if call.args.is_empty() => Terminal::Max,
        // `.nth(k)` takes exactly one int-literal index. A non-literal / wide
        // index is outside this terminal owner and remains a factory miss/gap.
        "nth" if call.args.len() == 1 => {
            let Expr::Lit(syn::ExprLit {
                lit: syn::Lit::Int(k),
                ..
            }) = strip_refs_groups(&call.args[0])
            else {
                return None;
            };
            let k = parse_int_lit(k).ok()?;
            let k = usize::try_from(k).ok()?;
            Terminal::Nth(k)
        }
        "nth_back" if call.args.len() == 1 => {
            let Expr::Lit(syn::ExprLit {
                lit: syn::Lit::Int(k),
                ..
            }) = strip_refs_groups(&call.args[0])
            else {
                return None;
            };
            let k = parse_int_lit(k).ok()?;
            let k = usize::try_from(k).ok()?;
            Terminal::NthBack(k)
        }
        // The closure-bearing predicate terminals take exactly one CLOSURE arg. A
        // non-closure arg (a fn path, a partially-applied predicate) is outside this
        // terminal owner and remains a factory miss/gap. The closure is const-evaluated
        // over each literal element at desugar; a closure that cannot const-eval (a
        // runtime capture, a multi-statement body) bails the reduction to the factory
        // gap path (never a fake-complete).
        "any" | "all" | "find" | "position" if call.args.len() == 1 => {
            let Expr::Closure(closure) = strip_refs_groups(&call.args[0]) else {
                return None;
            };
            let closure = closure.clone();
            match call.method.to_string().as_str() {
                "any" => Terminal::Any(closure),
                "all" => Terminal::All(closure),
                "find" => Terminal::Find(closure),
                "position" => Terminal::Position(closure),
                _ => unreachable!("guarded by the outer match arm"),
            }
        }
        // `advance_by`/`advance_back_by` are terminal Result-returning operations. Over a
        // direct literal-domain iterator they do not expose iterator state downstream; they
        // collapse to the std `Result` value for the requested count. The count itself still
        // recurses through the factory, so `v.len()`, `100 - v.len()`, consts, casts, etc.
        // compose normally.
        "advance_by" | "advance_back_by" if call.args.len() == 1 => {
            Terminal::AdvanceBy(call.args[0].clone())
        }
        // `.reduce(|acc, x| expr)` -- fold from element[0], returns `Option<T>`.
        // Requires a single closure arg; a non-closure (fn path, partially-applied)
        // remains a factory miss/gap.
        "reduce" if call.args.len() == 1 => {
            let Expr::Closure(closure) = strip_refs_groups(&call.args[0]) else {
                return None;
            };
            Terminal::Reduce(closure.clone())
        }
        // `.fold(init, |acc, x| expr)` -- explicit-initializer accumulator fold.
        // Requires a closure second arg; a function path stays outside this owner and
        // remains a factory miss/gap because this reducer cannot instantiate arbitrary code.
        "fold" if call.args.len() == 2 => {
            let Expr::Closure(closure) = strip_refs_groups(&call.args[1]) else {
                return None;
            };
            Terminal::Fold(call.args[0].clone(), closure.clone())
        }
        "try_fold" | "try_rfold" if call.args.len() == 2 => Terminal::TryFold {
            init: call.args[0].clone(),
            func: call.args[1].clone(),
            reverse: call.method == "try_rfold",
        },
        _ => return None,
    })
}

fn recognizes_scan_inner(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return false;
    };
    if call.method != "scan" || call.args.len() != 2 {
        return false;
    }
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits())
        && !has_composite(&call.receiver, fcx)
    {
        return false;
    }
    if const_int_acc_init(&call.args[0], fcx.let_inits()).is_none() {
        return false;
    }
    matches!(strip_refs_groups(&call.args[1]), Expr::Closure(closure) if closure.inputs.len() == 2)
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

fn advance_by_arg_body(terminal: &Terminal, fcx: &SugarBuildCtx) -> Option<SugarBody<TermFloor>> {
    match terminal {
        Terminal::AdvanceBy(arg) => Some(SugarBody::term(arg, fcx)),
        _ => None,
    }
}

fn unit_term() -> Rc<Term> {
    make_var("literal:Tuple()")
}

fn term_as_usize(term: &Rc<Term>) -> Option<usize> {
    usize::try_from(const_fold_int_term(term)?).ok()
}

/// The iterator scalar-reduction terminal node. Holds the raw receiver expression and
/// the captured reduction kind. `desugar` lazily composes the receiver to a literal `Seq`
/// through the live build context, then reduces it to the scalar value term; if the
/// elements are not cleanly const-reducible, it structurally bails to the factory gap path.
struct IterTerminalSugar {
    terminal: Terminal,
    site_key: String,
    closure_refusal: Option<String>,
    receiver: IterTerminalReceiver,
    advance_by_arg: Option<SugarBody<TermFloor>>,
    let_inits: BTreeMap<String, Expr>,
}

struct IterTerminalReceiver {
    source_expr: Expr,
}

impl IterTerminalReceiver {
    fn new(source_expr: Expr) -> Self {
        Self { source_expr }
    }

    fn body(&self, fcx: &SugarBuildCtx) -> SugarBody<CompositeFloor> {
        let source_expr = simple_path_name(&self.source_expr)
            .and_then(|name| fcx.scope().temporal_rewrite_expr_for(&name))
            .unwrap_or_else(|| self.source_expr.clone());
        SugarBody::from_node(
            crate::sugar::scan::try_build_scan_inner(&source_expr, fcx)
                .or_else(|| method_family::build_literal_sequence_composite(&source_expr, fcx))
                .unwrap_or_else(|| build_composite(&source_expr, fcx)),
        )
    }
}

impl IterTerminalSugar {
    fn advance_by_arg_term(&self, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
        let Some(arg) = &self.advance_by_arg else {
            iter_terminal_gap("advance_by terminal missing constructed argument body");
        };
        match arg.desugar(ctx) {
            Outcome::Complete(d) => d
                .into_term()
                .ok_or_else(|| iter_terminal_gap("advance_by argument reduced to non-Term")),
            Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
        }
    }

    fn accepts_empty_sequence_for_source<'a>(
        &self,
        let_inits: &BTreeMap<String, &'a Expr>,
        scope: &'a TemporalScope,
    ) -> bool {
        match self.terminal {
            // `.reduce()`/`.fold()` define structural empty-sequence results for literal
            // arrays as well as ranges. Keep that existing owner broad.
            Terminal::Reduce(_) | Terminal::Fold(_, _) | Terminal::TryFold { .. } => true,
            // Range-family terminals have a real floor on empty/reversed literal ranges
            // (`count == 0`, positional terminals are `None`, predicates fold to their
            // identity). Do not generalize this to empty `sum`/`product`: those remain
            // outside this lane's range/range-bounds partition.
            Terminal::Count
            | Terminal::Next
            | Terminal::NextBack
            | Terminal::Nth(_)
            | Terminal::NthBack(_)
            | Terminal::Last
            | Terminal::Min
            | Terminal::Max
            | Terminal::Any(_)
            | Terminal::All(_)
            | Terminal::Find(_)
            | Terminal::Position(_)
            | Terminal::AdvanceBy(_) => {
                method_family::literal_range_sequence_static_len_in_scope(
                    &self.receiver.source_expr,
                    let_inits,
                    scope,
                )
                .is_some()
                    || (matches!(self.terminal, Terminal::Count)
                        && method_family::literal_collection_adapter_static_len_in_scope(
                            &self.receiver.source_expr,
                            let_inits,
                            scope,
                        )
                        .is_some())
            }
            Terminal::Sum | Terminal::Product => false,
        }
    }

    fn can_try_literal_sequence_family(&self) -> bool {
        matches!(
            self.terminal,
            Terminal::Sum | Terminal::Product | Terminal::Count
        )
    }

    fn desugar_seq_candidate(
        candidate: Box<dyn Sugar>,
        ctx: &SugarCtx,
        allow_empty_domain: bool,
    ) -> Result<Option<Vec<DesugaredElem>>, Outcome> {
        match candidate.desugar(ctx) {
            Outcome::Complete(d) => Ok(d.into_seq()),
            Outcome::Incomplete(effect)
                if allow_empty_domain && effect.is_literal_domain_reason(EMPTY_DOMAIN_REASON) =>
            {
                Ok(Some(Vec::new()))
            }
            Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
        }
    }

    fn verify_static_len_source(
        &self,
        source: &Expr,
        fcx: &SugarBuildCtx,
        ctx: &SugarCtx,
    ) -> Result<bool, Outcome> {
        let candidate = method_family::build_literal_sequence_composite(source, fcx)
            .unwrap_or_else(|| build_composite(source, fcx));
        match Self::desugar_seq_candidate(candidate, ctx, true) {
            Ok(Some(_)) => Ok(true),
            Ok(None) => Ok(false),
            Err(hit) => Err(hit),
        }
    }

    fn reduce_term_seq_terminal(
        &self,
        terms: Vec<Rc<Term>>,
        ctx: &SugarCtx,
        let_inits: &BTreeMap<String, &Expr>,
    ) -> Outcome {
        if let Terminal::AdvanceBy(_) = &self.terminal {
            let n_term = match self.advance_by_arg_term(ctx) {
                Ok(term) => term,
                Err(outcome) => return outcome,
            };
            let Some(n) = term_as_usize(&n_term) else {
                iter_terminal_gap(
                    "advance_by argument reduced but did not dispatch to a literal usize floor",
                );
            };
            let len = terms.len();
            let term = if n <= len {
                monadic::ok_term(unit_term())
            } else {
                monadic::err_term(num((n - len) as i128))
            };
            return Outcome::Complete(Desugared::Term(term));
        }
        if matches!(self.terminal, Terminal::Count) {
            return Outcome::Complete(Desugared::Term(num(terms.len() as i128)));
        }
        if let Terminal::TryFold { .. } = &self.terminal {
            let Some(values) = terms
                .iter()
                .map(const_val_from_term)
                .collect::<Option<Vec<_>>>()
            else {
                return self.named_closure_boundary(ctx).unwrap_or_else(|| {
                    iter_terminal_gap("try_fold term sequence did not reduce to literal values")
                });
            };
            let Some(term) = self.try_fold_values(values, ctx, let_inits) else {
                return self.named_closure_boundary(ctx).unwrap_or_else(|| {
                    iter_terminal_gap("try_fold term sequence did not reach an Option floor")
                });
            };
            return Outcome::Complete(Desugared::Term(term));
        }
        let positional_idx = match &self.terminal {
            Terminal::Next => Some(Some(0usize)),
            Terminal::NextBack => Some(terms.len().checked_sub(1)),
            Terminal::Nth(k) => Some(Some(*k)),
            Terminal::NthBack(k) => {
                let Some(offset) = k.checked_add(1) else {
                    return Outcome::Complete(Desugared::Term(monadic::none_term()));
                };
                Some(terms.len().checked_sub(offset))
            }
            Terminal::Last => Some(terms.len().checked_sub(1)),
            _ => None,
        };
        if let Some(idx) = positional_idx {
            let term = match idx.and_then(|idx| terms.get(idx)) {
                Some(term) => monadic::some_term(Rc::clone(term)),
                None => monadic::none_term(),
            };
            return Outcome::Complete(Desugared::Term(term));
        }
        match self.terminal {
            Terminal::Sum => Outcome::Complete(Desugared::Term(fold_int_terms("+", 0, terms))),
            Terminal::Product => Outcome::Complete(Desugared::Term(fold_int_terms("*", 1, terms))),
            _ => self.named_closure_boundary(ctx).unwrap_or_else(|| {
                iter_terminal_gap("iterator terminal cannot consume a curried term sequence yet")
            }),
        }
    }

    /// Reduce the literal `Seq` to the value term. Receiver composition happens here,
    /// at desugar time: named `Incomplete`s propagate, while a generic structural bail takes the
    /// factory gap path. Never a guessed value: every `Complete` carries the EXACT reduction.
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
        let let_inits: BTreeMap<String, &Expr> = stable
            .iter()
            .map(|(name, init)| (name.clone(), init))
            .chain(
                self.let_inits
                    .iter()
                    .map(|(name, init)| (name.clone(), init)),
            )
            .collect();
        let fcx = desugar_build_ctx(ctx.scope, ctx.options, &let_inits);
        // Consumed-iterator gate: apply it lazily, with the live temporal rewrite table.
        if let Some(name) = simple_path_name(&self.receiver.source_expr) {
            if let Some(reason) = ctx.scope.unknown_iterator_consumption_reason(&name) {
                return Outcome::Incomplete(Effect::AmbiguousTemporalIdentity {
                    boundary: name,
                    reason,
                });
            }
            if ctx.scope.is_consumed_iterator_local(&name)
                && ctx.scope.temporal_rewrite_expr_for(&name).is_none()
            {
                return Outcome::Incomplete(Effect::AmbiguousTemporalIdentity {
                    boundary: name.clone(),
                    reason: format!(
                        "consumed iterator `{name}` has no replayable temporal rewrite at this point; refused"
                    ),
                });
            }
        }
        if matches!(self.terminal, Terminal::Count) {
            if let Some(chunk_expr) =
                resolve_chunk_window_receiver(&self.receiver.source_expr, &let_inits, ctx.scope, 0)
            {
                if let Some(static_len) =
                    method_family::literal_collection_adapter_static_len_in_scope(
                        &chunk_expr,
                        &let_inits,
                        ctx.scope,
                    )
                {
                    match self.verify_static_len_source(&static_len.source, &fcx, ctx) {
                        Ok(true) => {
                            debug!(
                                target: "sugar_lift_rust_tests::sugar::iter_terminal",
                                len = static_len.len,
                                "reducing literal chunk/window count through verified length-only adapter"
                            );
                            return Outcome::Complete(Desugared::Term(num(static_len.len as i128)));
                        }
                        Ok(false) => iter_terminal_gap(
                            "verified chunk/window length source did not reduce to a sequence",
                        ),
                        Err(hit) => return hit,
                    }
                }
                let receiver = match strip_refs_groups(&chunk_expr) {
                    Expr::MethodCall(call) => call.receiver.as_ref(),
                    _ => &chunk_expr,
                };
                iter_terminal_gap(&format!(
                    "chunk/window count source `{}` has no literal sequence floor",
                    token_key(receiver)
                ));
            }
        }
        let static_empty_sequence = method_family::literal_sequence_static_len_in_scope(
            &self.receiver.source_expr,
            &let_inits,
            ctx.scope,
        ) == Some(0)
            || (matches!(self.terminal, Terminal::Count)
                && method_family::literal_collection_adapter_static_len_in_scope(
                    &self.receiver.source_expr,
                    &let_inits,
                    ctx.scope,
                )
                .is_some_and(|proof| proof.len == 0));
        let allow_empty_sequence =
            static_empty_sequence && self.accepts_empty_sequence_for_source(&let_inits, ctx.scope);
        let seq = if allow_empty_sequence {
            Vec::new()
        } else {
            let receiver_body = self.receiver.body(&fcx);
            match receiver_body.reduce(ctx) {
                Outcome::Complete(Desugared::TermSeq(terms)) => {
                    return self.reduce_term_seq_terminal(terms, ctx, &let_inits);
                }
                Outcome::Complete(d) => match d.into_seq() {
                    Some(seq) => seq,
                    None => iter_terminal_gap("iterator terminal receiver reduced to non-sequence"),
                },
                Outcome::Incomplete(effect)
                    if effect.is_literal_domain_reason(EMPTY_DOMAIN_REASON)
                        && allow_empty_sequence =>
                {
                    Vec::new()
                }
                Outcome::Incomplete(effect) if self.can_try_literal_sequence_family() => {
                    if let Some(candidate) = method_family::build_literal_sequence_composite(
                        &self.receiver.source_expr,
                        &fcx,
                    ) {
                        match Self::desugar_seq_candidate(candidate, ctx, allow_empty_sequence) {
                            Ok(Some(seq)) => seq,
                            Ok(None) => {
                                if let Terminal::Count = self.terminal {
                                    if let Some(static_len) =
                                        method_family::literal_collection_adapter_static_len_in_scope(
                                            &self.receiver.source_expr,
                                            &let_inits,
                                            ctx.scope,
                                        )
                                    {
                                        match self.verify_static_len_source(
                                            &static_len.source,
                                            &fcx,
                                            ctx,
                                        ) {
                                            Ok(true) => {
                                                debug!(
                                                    target: "sugar_lift_rust_tests::sugar::iter_terminal",
                                                    len = static_len.len,
                                                    "reducing literal collection count through verified length-only adapter"
                                                );
                                                    return Outcome::Complete(Desugared::Term(num(
                                                        static_len.len as i128,
                                                    )));
                                                }
                                            Ok(false) => iter_terminal_gap(
                                                "literal collection count static source did not reduce",
                                            ),
                                            Err(hit) => return hit,
                                        }
                                    }
                                }
                                iter_terminal_gap(
                                    "iterator terminal literal-sequence fallback missed",
                                );
                            }
                            Err(hit) => return hit,
                        }
                    } else if let Terminal::Count = self.terminal {
                        if let Some(static_len) =
                            method_family::literal_collection_adapter_static_len_in_scope(
                                &self.receiver.source_expr,
                                &let_inits,
                                ctx.scope,
                            )
                        {
                            match self.verify_static_len_source(&static_len.source, &fcx, ctx) {
                                Ok(true) => {
                                    debug!(
                                        target: "sugar_lift_rust_tests::sugar::iter_terminal",
                                        len = static_len.len,
                                        "reducing literal collection count through verified length-only adapter"
                                    );
                                    return Outcome::Complete(Desugared::Term(num(
                                        static_len.len as i128
                                    )));
                                }
                                Ok(false) => iter_terminal_gap(
                                    "literal collection count static source did not reduce",
                                ),
                                Err(hit) => return hit,
                            }
                        }
                        iter_terminal_gap(
                            "iterator terminal count had no sequence body or static length",
                        );
                    } else {
                        return Outcome::Incomplete(effect);
                    }
                }
                Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
            }
        };
        if let Terminal::AdvanceBy(_) = &self.terminal {
            let n_term = match self.advance_by_arg_term(ctx) {
                Ok(term) => term,
                Err(outcome) => return outcome,
            };
            let Some(n) = term_as_usize(&n_term) else {
                iter_terminal_gap(
                    "advance_by argument reduced but did not dispatch to a literal usize floor",
                );
            };
            let len = seq.len();
            debug!(
                target: "sugar_lift_rust_tests::sugar::iter_terminal",
                requested = n,
                len,
                "reducing literal-domain iterator advance terminal"
            );
            let term = if n <= len {
                monadic::ok_term(unit_term())
            } else {
                monadic::err_term(num((n - len) as i128))
            };
            return Outcome::Complete(Desugared::Term(term));
        }
        let positional_idx = match &self.terminal {
            Terminal::Next => Some(Some(0usize)),
            Terminal::NextBack => Some(seq.len().checked_sub(1)),
            Terminal::Nth(k) => Some(Some(*k)),
            Terminal::NthBack(k) => {
                let Some(offset) = k.checked_add(1) else {
                    return Outcome::Complete(Desugared::Term(monadic::none_term()));
                };
                Some(seq.len().checked_sub(offset))
            }
            Terminal::Last => Some(seq.len().checked_sub(1)),
            _ => None,
        };
        if let Some(idx) = positional_idx {
            let term = match idx.and_then(|idx| seq.get(idx)) {
                Some(elem) => {
                    match reduce_sequence_elem_term_floor(elem, "iter_terminal", &fcx, ctx) {
                        Ok(term) => monadic::some_term(term),
                        Err(outcome) => return outcome,
                    }
                }
                None => monadic::none_term(),
            };
            return Outcome::Complete(Desugared::Term(term));
        }
        let reduced = (|| {
            // `.count()` reduces structure (the LENGTH) after the receiver has composed to a
            // literal `Seq`. A receiver `Incomplete` has already propagated above.
            if matches!(self.terminal, Terminal::Count) {
                return Some(Desugared::Term(num(seq.len() as i128)));
            }
            // EXTREMUM terminals (`.min()`/`.max()`): fold over the elements' EXACT integer
            // const values and wrap the extremum in `MonadicSugar`'s `opt:some` (the result of
            // `.min()`/`.max()` is `Option<&T>`). EXACT-OR-BAIL: a non-int / opaque element
            // gaps. Empty literal ranges have the real floor `None`;
            // empty non-range literal domains still decline before this arm.
            if matches!(self.terminal, Terminal::Min | Terminal::Max) {
                if seq.is_empty() {
                    return Some(Desugared::Term(monadic::none_term()));
                }
                let mut ext: Option<i128> = None;
                for elem in &seq {
                    let n = elem.value.as_ref().and_then(ConstVal::as_int)?;
                    ext = Some(match (ext, &self.terminal) {
                        (None, _) => n,
                        (Some(cur), Terminal::Min) => cur.min(n),
                        (Some(cur), _) => cur.max(n),
                    });
                }
                // `seq` is non-empty (the `LiteralSugar` floor declines the empty Seq), so
                // `ext` is `Some`; guard defensively rather than unwrap.
                let n = ext?;
                return Some(Desugared::Term(monadic::some_term(num(n))));
            }
            // PREDICATE-POSITIONAL terminals (`.find(p)`/`.position(p)`): const-evaluate the
            // closure over each literal element (the SAME `const_eval_unary_closure` floor the
            // `MapSugar`/`FilterSugar` adaptors use), grounding the FIRST match to a
            // `MonadicSugar` `opt:some` (`.find` wraps the ELEMENT, `.position` wraps the
            // INDEX) and no match to `opt:none`. EXACT-OR-BAIL: an opaque element, a closure
            // that cannot const-eval to a bool, or a `.find` element that is not an int
            // gaps, never a guessed value.
            if let Terminal::Find(pred) | Terminal::Position(pred) = &self.terminal {
                let want_index = matches!(self.terminal, Terminal::Position(_));
                for (idx, elem) in seq.iter().enumerate() {
                    let v = elem.value.as_ref()?;
                    if const_eval_unary_closure(pred, v)?.as_bool()? {
                        let n = if want_index { idx as i128 } else { v.as_int()? };
                        return Some(Desugared::Term(monadic::some_term(num(n))));
                    }
                }
                return Some(Desugared::Term(monadic::none_term()));
            }
            // PREDICATE-BOOL terminals (`.any(p)`/`.all(p)`): const-evaluate the closure over
            // every literal element and reduce OR / AND to a ground bool const. EXACT-OR-BAIL:
            // any opaque element or non-const-evaluable closure gaps.
            if let Terminal::Any(pred) | Terminal::All(pred) = &self.terminal {
                let is_all = matches!(self.terminal, Terminal::All(_));
                let mut acc = is_all;
                for elem in &seq {
                    let v = elem.value.as_ref()?;
                    let b = const_eval_unary_closure(pred, v)?.as_bool()?;
                    acc = if is_all { acc && b } else { acc || b };
                }
                return Some(Desugared::Term(bool_term(acc)));
            }
            // `.reduce(|acc, x| expr)` -- fold with element[0] as the initial accumulator.
            // Empty source -> `opt:none`. Non-empty -> const-fold the closure over elements[1..]
            // seeded from element[0], then wrap the final value in `opt:some`.
            if let Terminal::Reduce(closure) = &self.terminal {
                if seq.is_empty() {
                    return Some(Desugared::Term(monadic::none_term()));
                }
                if closure.inputs.len() != 2 {
                    return None;
                }
                let acc_var = closure_single_param_ident(&closure.inputs[0])?;
                let item_var = closure_single_param_ident(&closure.inputs[1])?;
                let tail: &Expr = reduce_closure_tail(&closure.body)?;
                let first = seq[0]
                    .value
                    .as_ref()
                    .and_then(ConstVal::as_int)
                    .and_then(|n| i64::try_from(n).ok())?;
                let mut acc = first;
                for elem in &seq[1..] {
                    let item_val = elem
                        .value
                        .as_ref()
                        .and_then(ConstVal::as_int)
                        .and_then(|n| i64::try_from(n).ok())?;
                    let mut env: BTreeMap<String, i64> = BTreeMap::new();
                    env.insert(acc_var.clone(), acc);
                    env.insert(item_var.clone(), item_val);
                    acc = const_fold_acc_update(tail, &env)?;
                }
                return Some(Desugared::Term(monadic::some_term(num(i128::from(acc)))));
            }
            // `.fold(init, |acc, x| expr)` -- fold from the explicit initial accumulator.
            // The accumulator is threaded in source order (`a_i = f(a_{i-1}, n_i)`); every
            // element and every intermediate must remain exactly const-foldable.
            if let Terminal::Fold(init_expr, closure) = &self.terminal {
                if closure_body_is_side_effecting(&closure.body) || closure.inputs.len() != 2 {
                    return None;
                }
                let acc_var = closure_single_param_ident(&closure.inputs[0])?;
                let item_var = closure_single_param_ident(&closure.inputs[1])?;
                let tail: &Expr = reduce_closure_tail(&closure.body)?;
                let mut acc = const_int_acc_init(init_expr, &let_inits)?;
                for elem in &seq {
                    let item_val = elem
                        .value
                        .as_ref()
                        .and_then(ConstVal::as_int)
                        .and_then(|n| i64::try_from(n).ok())?;
                    let mut env: BTreeMap<String, i64> = BTreeMap::new();
                    env.insert(acc_var.clone(), acc);
                    env.insert(item_var.clone(), item_val);
                    acc = const_fold_acc_update(tail, &env)?;
                }
                return Some(Desugared::Term(num(i128::from(acc))));
            }
            if let Terminal::TryFold { .. } = &self.terminal {
                let values = seq
                    .iter()
                    .map(|elem| elem.value.clone())
                    .collect::<Option<Vec<_>>>()?;
                return self
                    .try_fold_values(values, ctx, &let_inits)
                    .map(Desugared::Term);
            }
            // Numeric reductions: exact const ints only. Empty product uses the Rust
            // multiplicative identity; empty sum uses additive identity.
            match self.terminal {
                Terminal::Sum => {
                    let mut total = 0i128;
                    for elem in &seq {
                        total = total.checked_add(elem.value.as_ref()?.as_int()?)?;
                    }
                    Some(Desugared::Term(num(total)))
                }
                Terminal::Product => {
                    let mut product = 1i128;
                    for elem in &seq {
                        product = product.checked_mul(elem.value.as_ref()?.as_int()?)?;
                    }
                    Some(Desugared::Term(num(product)))
                }
                _ => None,
            }
        })();
        match reduced {
            Some(d) => Outcome::Complete(d),
            None => self.named_closure_boundary(ctx).unwrap_or_else(|| {
                iter_terminal_gap(&format!(
                    "iterator terminal reduction did not reach a floor at `{}`",
                    self.site_key
                ))
            }),
        }
    }

    fn named_closure_boundary(&self, _ctx: &SugarCtx) -> Option<Outcome> {
        match self.terminal {
            Terminal::Any(_)
            | Terminal::All(_)
            | Terminal::Find(_)
            | Terminal::Position(_)
            | Terminal::Reduce(_)
            | Terminal::Fold(_, _)
            | Terminal::TryFold { .. } => {
                let reason = self.closure_refusal.clone()?;
                match refusal_disposition(&reason) {
                    Disposition::Refused => {
                        Some(Outcome::Incomplete(Effect::AmbiguousTemporalIdentity {
                            boundary: self.site_key.clone(),
                            reason,
                        }))
                    }
                    Disposition::Inactive | Disposition::Unclassified => iter_terminal_gap(&reason),
                }
            }
            _ => None,
        }
    }

    fn try_fold_values(
        &self,
        mut values: Vec<ConstVal>,
        ctx: &SugarCtx,
        let_inits: &BTreeMap<String, &Expr>,
    ) -> Option<Rc<Term>> {
        let Terminal::TryFold {
            init,
            func,
            reverse,
        } = &self.terminal
        else {
            return None;
        };
        if *reverse {
            values.reverse();
        }
        let closure = resolve_try_fold_closure(func, let_inits, ctx.scope, 0)?;
        if closure_body_is_side_effecting(&closure.body) {
            return None;
        }
        let mut acc = ConstVal::Int(i128::from(const_int_acc_init(init, let_inits)?));
        for value in values {
            let step = const_eval_binary_option_closure(&closure, &acc, &value)?;
            let Some(next_acc) = step else {
                return Some(monadic::none_term());
            };
            acc = next_acc;
        }
        Some(monadic::some_term(const_val_term(&acc)?))
    }
}

fn resolve_try_fold_closure<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    scope: &'a TemporalScope,
    depth: usize,
) -> Option<syn::ExprClosure> {
    if depth > 8 {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Closure(closure) => Some(closure.clone()),
        Expr::Reference(reference) => {
            resolve_try_fold_closure(&reference.expr, let_inits, scope, depth + 1)
        }
        Expr::Path(_) => {
            let name = simple_path_name(expr)?;
            let init = let_inits
                .get(&name)
                .copied()
                .or_else(|| scope.stable_let_binding_for_term(&name))?;
            resolve_try_fold_closure(init, let_inits, scope, depth + 1)
        }
        _ => None,
    }
}

fn const_val_from_term(term: &Rc<Term>) -> Option<ConstVal> {
    match term.as_ref() {
        Term::Const {
            value: ConstValue::Int(value),
            ..
        } => Some(ConstVal::Int(*value)),
        Term::Const {
            value: ConstValue::Bool(value),
            ..
        } => Some(ConstVal::Bool(*value)),
        Term::Const {
            value: ConstValue::String(value),
            ..
        } => {
            let mut chars = value.chars();
            let ch = chars.next()?;
            chars.next().is_none().then_some(ConstVal::Char(ch))
        }
        _ => None,
    }
}

fn iter_terminal_gap(reason: &str) -> ! {
    panic!("iterator terminal did not reach a lawful floor: {reason}")
}

impl Sugar for IterTerminalSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        // GROUND the literal reduction with teeth, or take the factory gap path.
        // Receiver composition is lazy: only a Complete literal sequence reaches `reduce`;
        // structural bail remains structural, and named Incomplete propagates unchanged.
        self.reduce(ctx)
    }
}

/// Extract the tail expression (the new accumulator value) from a reduce closure body.
/// Supports both direct expression bodies (`|a, b| a + b`) and block bodies with a
/// trailing expression (`|a, b| { ..stmts..; a + b }`). Returns `None` for block bodies
/// with no trailing expression (e.g. a block ending in a semicolon).
fn reduce_closure_tail(body: &Expr) -> Option<&Expr> {
    match body {
        Expr::Block(b) => {
            // Block body: the tail is the final expression-without-semicolon.
            let (tail, _) = b.block.stmts.split_last()?;
            match tail {
                Stmt::Expr(e, None) => Some(e),
                _ => None, // ends in a semicolon -> no tail expression -> bail
            }
        }
        other => Some(other), // direct expression body (`|a, b| a + b`)
    }
}
