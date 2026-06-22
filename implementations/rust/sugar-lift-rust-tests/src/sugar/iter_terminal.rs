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
// elements and wrap that extremum via `MonadicSugar`'s `opt:some` (the empty Seq, which
// `LiteralSugar` declines, never reaches the reduction -> stays opaque, no fake-`None`).
// THE PREDICATE-POSITIONAL terminals (`.find(p)`/`.position(p)`) const-evaluate the
// closure (the SAME `const_eval_unary_closure` floor `MapSugar`/`FilterSugar` use) over
// each literal element; `.find` grounds the FIRST satisfying element to `opt:some(elem)`,
// `.position` grounds its INDEX to `opt:some(idx)`, and no match grounds to `opt:none`.
// THE PREDICATE-BOOL terminals (`.any(p)`/`.all(p)`) const-evaluate the closure over each
// element and OR (`any`) / AND (`all`) the per-element bools to a GROUNDED bool const.
//
// This is the TERM-position node. It declares it comes before `method::recognize`, so a
// shape-matched terminal gets the first chance to compose to the literal floor instead of
// immediately becoming the opaque `method:<m>` EUF ctor. Receiver ownership is decided at
// desugar time: a literal `Seq` reduces, a structural bail falls back to `MethodSugar`, and
// a named `Hit` propagates.
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
// THE HARD SOUNDNESS LINE. The node Digs ONLY when the WHOLE receiver chain desugars to a
// LITERAL `Seq`. If the receiver desugar `Hit`s -- the base was an effect / runtime call /
// opaque collection (`someFileIo.iter()`, `make_ys().iter()`) -- the `Hit` is PROPAGATED
// VERBATIM. A literal element that is not an exact integer const (a float / string /
// opaque element) bails the whole reduction (EXACT-OR-BAIL), then the generic method
// fallback owns the term. There are no fake-digs: every grounded value carries the real
// reduction, so a wrong-expected twin is z3-UNSAT (the teeth), not a vacuously-satisfiable
// opaque accessor.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{make_var, num, ConstValue, Sort, Term};
use syn::{Expr, Stmt};
use tracing::debug;

use crate::sugar::factory::{build_composite, build_term, has_composite, SugarBuildCtx};
use crate::sugar::literal::EMPTY_DOMAIN_REASON;
use crate::sugar::method;
use crate::sugar::method_family;
use crate::sugar::monadic;
use crate::sugar::term_leaf::reasoned_hit;
use crate::{
    closure_body_is_side_effecting, closure_single_param_ident, const_eval_unary_closure,
    const_fold_acc_update, const_fold_int_term, const_int_acc_init, parse_int_lit,
    simple_path_name, strip_refs_groups, ConstVal, Desugared, DesugaredElem, Effect, Outcome,
    Sugar, SugarCtx,
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
    /// `.nth(k)` -- the element at position `k` (or `None` past the end).
    Nth(usize),
    /// `.last()` -- the element at position `len-1` (or `None` for the empty Seq).
    Last,
    /// `.min()` -- the minimum int element wrapped in `Some` (the empty Seq, which the
    /// `LiteralSugar` floor declines, never reaches here).
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
}

/// TERM recognizer for the iterator scalar-reduction terminals. `Some` only when the
/// method is a recognized reduction. Recognition captures the raw receiver only; the
/// receiver chain is composed to a literal `Seq` lazily in `desugar`, where the live SSA
/// binding/temporal context exists. Any receiver that cannot compose to a text-determined
/// sequence structurally bails to the opaque `method:` fallback, while named receiver
/// `Hit`s propagate.
///
/// The soundness line is the receiver `Outcome`: a `Dug(Seq)` is the only path to a
/// grounded value; a named `Hit` poisons the terminal and propagates; a structural bail
/// emits the opaque fallback. So the node can only ever ground-with-teeth, propagate a
/// real boundary, or reproduce the baseline opaque term -- never reduce-to-maybe-wrong.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let terminal = recognize_terminal(call)?;
    Some(Box::new(IterTerminalSugar {
        terminal,
        inner: (*call.receiver).clone(),
        fallback: expr.clone(),
        let_inits: capture_let_inits(fcx),
    }))
}

pub(crate) fn recognizes_monadic_terminal(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return false;
    };
    let Some(terminal) = recognize_terminal(call) else {
        return false;
    };
    if !matches!(terminal, Terminal::Next) || !stable_next_snapshot_receiver(&call.receiver, fcx, 0)
    {
        return false;
    }
    if let Some(name) = simple_path_name(&call.receiver) {
        if fcx.scope().is_consumed_iterator_local(&name)
            && fcx.scope().temporal_rewrite_expr_for(&name).is_none()
        {
            return false;
        }
    }
    recognizes_scan_inner(&call.receiver, fcx) || has_composite(&call.receiver, fcx)
}

fn stable_next_snapshot_receiver(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 16 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Array(_) | Expr::Range(_) => true,
        Expr::MethodCall(call) if call.args.is_empty() => {
            let method = call.method.to_string();
            matches!(
                method.as_str(),
                "iter" | "into_iter" | "cloned" | "copied" | "fuse"
            ) && stable_next_snapshot_receiver(&call.receiver, fcx, depth + 1)
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
            is_into_iter && stable_next_snapshot_receiver(&call.args[0], fcx, depth + 1)
        }
        Expr::Path(_) => simple_path_name(expr)
            .and_then(|name| fcx.scope().temporal_rewrite_expr_for(&name))
            .is_some_and(|current| stable_next_snapshot_receiver(&current, fcx, depth + 1)),
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
        "last" if call.args.is_empty() => Terminal::Last,
        "min" if call.args.is_empty() => Terminal::Min,
        "max" if call.args.is_empty() => Terminal::Max,
        // `.nth(k)` takes exactly one int-literal index. A non-literal / wide
        // index is NOT recognized -> fall through to the opaque ctor.
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
        // The closure-bearing predicate terminals take exactly one CLOSURE arg. A
        // non-closure arg (a fn path, a partially-applied predicate) is NOT recognized
        // here -> fall through to the opaque ctor. The closure is const-evaluated over
        // each literal element at desugar; a closure that cannot const-eval (a runtime
        // capture, a multi-statement body) bails the whole reduction to the opaque
        // fallback (never a fake-dig).
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
        // falls through to the opaque ctor.
        "reduce" if call.args.len() == 1 => {
            let Expr::Closure(closure) = strip_refs_groups(&call.args[0]) else {
                return None;
            };
            Terminal::Reduce(closure.clone())
        }
        // `.fold(init, |acc, x| expr)` -- explicit-initializer accumulator fold.
        // Requires a closure second arg; a function path stays with the ordinary method
        // fallback because this reducer cannot instantiate arbitrary code.
        "fold" if call.args.len() == 2 => {
            let Expr::Closure(closure) = strip_refs_groups(&call.args[1]) else {
                return None;
            };
            Terminal::Fold(call.args[0].clone(), closure.clone())
        }
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

fn unit_term() -> Rc<Term> {
    make_var("literal:Tuple()")
}

fn term_as_usize(term: &Rc<Term>) -> Option<usize> {
    usize::try_from(const_fold_int_term(term)?).ok()
}

/// The iterator scalar-reduction terminal node. Holds the raw receiver expression and
/// the captured reduction kind, plus the opaque `method:` ctor fallback. `desugar`
/// lazily composes the receiver to a literal `Seq`, then reduces it to the scalar value
/// term; if the elements are not cleanly const-reducible (a non-const element under
/// `.sum()`/`.product()`, an empty/oversize domain), it emits the fallback (the baseline
/// opaque term) rather than refusing.
struct IterTerminalSugar {
    terminal: Terminal,
    inner: Expr,
    fallback: Expr,
    let_inits: BTreeMap<String, Expr>,
}

impl IterTerminalSugar {
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
            Outcome::Dug(d) => Ok(d.into_seq()),
            Outcome::Hit(Effect::Unsupported { reason })
                if allow_empty_domain && reason == EMPTY_DOMAIN_REASON =>
            {
                Ok(Some(Vec::new()))
            }
            hit if hit.is_structural_bail() => Ok(None),
            hit => Err(hit),
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

    /// Reduce the literal `Seq` to the value term. Receiver composition happens here,
    /// at desugar time: named `Hit`s propagate, while a generic structural bail lets the
    /// caller emit the opaque fallback. Never a guessed value: every `Dug` carries the
    /// EXACT reduction.
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
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        // Consumed-iterator gate: apply it lazily, with the live temporal rewrite table.
        if let Some(name) = simple_path_name(&self.inner) {
            if let Some(reason) = ctx.scope.unknown_iterator_consumption_reason(&name) {
                return reasoned_hit(reason).desugar(ctx);
            }
            if ctx.scope.is_consumed_iterator_local(&name)
                && ctx.scope.temporal_rewrite_expr_for(&name).is_none()
            {
                // Opaque-EUF disposition: UNDECIDED (honest dark), never refused.
                return Outcome::from_opt(None);
            }
        }
        let inner = crate::sugar::scan::try_build_scan_inner(&self.inner, &fcx)
            .unwrap_or_else(|| build_composite(&self.inner, &fcx));
        let seq = match inner.desugar(ctx) {
            Outcome::Dug(d) => match d.into_seq() {
                Some(seq) => seq,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(Effect::Unsupported { reason })
                if reason == EMPTY_DOMAIN_REASON
                    && method_family::literal_sequence_static_len_in_scope(
                        &self.inner,
                        &let_inits,
                        ctx.scope,
                    ) == Some(0) =>
            {
                Vec::new()
            }
            hit if hit.is_structural_bail() && self.can_try_literal_sequence_family() => {
                if let Some(candidate) =
                    method_family::build_literal_sequence_composite(&self.inner, &fcx)
                {
                    match Self::desugar_seq_candidate(
                        candidate,
                        ctx,
                        method_family::literal_sequence_static_len_in_scope(
                            &self.inner,
                            &let_inits,
                            ctx.scope,
                        ) == Some(0),
                    ) {
                        Ok(Some(seq)) => seq,
                        Ok(None) => {
                            if let Terminal::Count = self.terminal {
                                if let Some(static_len) =
                                    method_family::literal_collection_adapter_static_len_in_scope(
                                        &self.inner,
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
                                            return Outcome::Dug(Desugared::Term(num(
                                                static_len.len as i128,
                                            )));
                                        }
                                        Ok(false) => return Outcome::from_opt(None),
                                        Err(hit) => return hit,
                                    }
                                }
                            }
                            return Outcome::from_opt(None);
                        }
                        Err(hit) => return hit,
                    }
                } else if let Terminal::Count = self.terminal {
                    if let Some(static_len) =
                        method_family::literal_collection_adapter_static_len_in_scope(
                            &self.inner,
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
                                return Outcome::Dug(Desugared::Term(num(static_len.len as i128)));
                            }
                            Ok(false) => return Outcome::from_opt(None),
                            Err(hit) => return hit,
                        }
                    }
                    return Outcome::from_opt(None);
                } else {
                    return Outcome::from_opt(None);
                }
            }
            hit if hit.is_structural_bail() => return Outcome::from_opt(None),
            hit => return hit,
        };
        if let Terminal::AdvanceBy(arg) = &self.terminal {
            let n_term = match build_term(arg, &fcx).desugar(ctx) {
                Outcome::Dug(d) => match d.into_term() {
                    Some(term) => term,
                    None => return Outcome::from_opt(None),
                },
                hit if hit.is_structural_bail() => return Outcome::from_opt(None),
                hit => return hit,
            };
            let Some(n) = term_as_usize(&n_term) else {
                return Outcome::from_opt(None);
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
            return Outcome::Dug(Desugared::Term(term));
        }
        Outcome::from_opt((|| {
            // `.count()` reduces structure (the LENGTH) after the receiver has composed to a
            // literal `Seq`. A receiver `Hit` has already propagated above.
            if matches!(self.terminal, Terminal::Count) {
                return Some(Desugared::Term(num(seq.len() as i128)));
            }
            // POSITIONAL terminals (`.next()`/`.nth(k)`/`.last()`): index the literal Seq and
            // GROUND to a `MonadicSugar` `Some(element)` / `None` (the ADT-backed `opt:some`/
            // `opt:none` ctor). An in-range element must be an EXACT integer const (the ADT
            // field sort is `Int`); a non-int element bails to the opaque fallback (never a
            // guessed value). An out-of-range index grounds to the structural `None`.
            if let Some(idx) = match &self.terminal {
                Terminal::Next => Some(0usize),
                Terminal::Nth(k) => Some(*k),
                Terminal::Last => seq.len().checked_sub(1),
                _ => None,
            } {
                return Some(match seq.get(idx) {
                    Some(elem) => {
                        let n = elem.value.as_ref().and_then(ConstVal::as_int)?;
                        Desugared::Term(monadic::some_term(num(n)))
                    }
                    // Past the end (or `.last()` on the empty Seq) -- the value IS `None`.
                    None => Desugared::Term(monadic::none_term()),
                });
            }
            // EXTREMUM terminals (`.min()`/`.max()`): fold over the elements' EXACT integer
            // const values and wrap the extremum in `MonadicSugar`'s `opt:some` (the result of
            // `.min()`/`.max()` is `Option<&T>`). EXACT-OR-BAIL: a non-int / opaque element ->
            // `None` (the opaque fallback). The empty Seq (which `LiteralSugar` declines, so it
            // never reaches here) would be the `opt:none` case -- it stays opaque, never a
            // fake-`None`.
            if matches!(self.terminal, Terminal::Min | Terminal::Max) {
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
            // that cannot const-eval to a bool, or a `.find` element that is not an int ->
            // `None` (the opaque fallback), never a guessed value.
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
            // any opaque element or non-const-evaluable closure -> `None` (opaque fallback).
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
        })())
    }
}

impl Sugar for IterTerminalSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        // GROUND the literal reduction with teeth, or emit the opaque baseline fallback.
        // Receiver composition is lazy: only a Dug literal sequence reaches `reduce`;
        // structural bail falls through to the generic method shape, and named Hits
        // propagate unchanged.
        match self.reduce(ctx) {
            Outcome::Dug(d) => Outcome::Dug(d),
            hit if hit.is_structural_bail() => {
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
                let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
                match method::recognize(&self.fallback, &fcx) {
                    Some(fallback) => fallback.desugar(ctx),
                    None => Outcome::from_opt(None),
                }
            }
            hit => hit,
        }
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
