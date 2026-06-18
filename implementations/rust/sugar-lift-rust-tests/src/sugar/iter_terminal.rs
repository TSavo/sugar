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
// This is the TERM-position node -- it declares a better TERM priority than
// `method::recognize`, so a recognized literal-domain reduction grounds to its
// value instead of the opaque `method:<m>` EUF ctor. A receiver chain the literal-Seq
// machinery does not own (`peel_fold_adaptors` -> `None`: an unknown adaptor, a closure
// adaptor that is not const-evaluable here, a `let`-bound receiver that does not resolve
// to a literal) is NOT recognized -> falls through to `MethodSugar` (the opaque `method:` ctor,
// established sound under-claim).
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
// THE HARD SOUNDNESS LINE. The node Digs ONLY when the WHOLE receiver chain bottoms out
// in a LITERAL `Seq`. `desugar` recurses on the pre-built inner seq-`Sugar` (a
// `LiteralSugar` base wrapped by the existing adaptor decorators). If that inner desugar
// `Hit`s -- the base was an effect / runtime call / opaque collection (`someFileIo.iter()`,
// `make_ys().iter()`) -- the `Hit` is PROPAGATED VERBATIM (refuse / blow up). A literal
// element that is not an exact integer const (a float / string / opaque element) bails the
// whole reduction (EXACT-OR-BAIL), the byte-identical structural backstop. There are no
// fake-digs: every grounded value carries the real reduction, so a wrong-expected twin is
// z3-UNSAT (the teeth), not a vacuously-satisfiable opaque accessor.

use std::rc::Rc;

use sugar_ir_symbolic::{num, ConstValue, Sort, Term};
use syn::Expr;

use crate::sugar::factory::{build_composite, FactoryCtx};
use crate::sugar::method;
use crate::sugar::method_family;
use crate::sugar::monadic;
use crate::{
    const_eval_unary_closure, parse_int_lit, strip_refs_groups, ConstVal, Desugared, Outcome,
    Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("iter_terminal", recognize);

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
#[derive(Clone)]
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
}

/// TERM recognizer for the iterator scalar-reduction terminals. `Some` only when the
/// method is a recognized reduction AND the receiver chain peels to a chain whose BASE is
/// a WRITTEN LITERAL `Seq` (a syntactic array `[..]` / closed range `a..b`). Any other
/// receiver (an unknown adaptor `peel` -> `None`, or a non-literal base -- `v[..4]`, a
/// `let`-bound name `translate_term_in_scope` cannot resolve, an opaque `io`, a runtime
/// `make_v()`) returns `None`, so generic `MethodSugar` owns the opaque `method:` ctor,
/// the established sound under-claim -- BYTE-IDENTICAL to baseline.
///
/// The SYNTACTIC-LITERAL GATE is the soundness line drawn at BUILD time (the factory
/// dispatch is build-time -- a recognizer that returns `Some` commits the node, so a
/// desugar-time `Hit` could NOT fall through). Only a written literal base is ever
/// recognized; an effect / runtime / opaque domain is NOT a syntactic literal -> never
/// reaches the reduction. As belt-and-suspenders, the node ALSO holds the opaque
/// `MethodSugar` fallback and emits IT (never refusing) if the literal desugar does
/// not cleanly ground (a non-const element under `.sum()`/`.product()`, an empty/oversize
/// domain) -- so the node can only ever ground-with-teeth or reproduce the baseline opaque
/// term, never turn a baseline lift into a refusal.
pub(crate) fn recognize(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let terminal = recognize_terminal(call)?;
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits) {
        return None;
    }
    // The opaque `method:` fallback -- the EXACT node `method::recognize`
    // builds for this same expr (built DIRECTLY, not via `build_term`, which would re-enter
    // this recognizer and loop). Emitted verbatim if the literal desugar does not cleanly
    // ground, so this node never refuses a form baseline lifted opaquely.
    let fallback = method::recognize(expr, fcx)?;
    Some(Box::new(IterTerminalSugar {
        terminal,
        inner: build_composite(&call.receiver, fcx),
        fallback,
    }))
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
        _ => return None,
    })
}

/// The iterator scalar-reduction terminal node. Holds the pre-built inner seq-`Sugar`
/// (the LITERAL-domain receiver chain, guaranteed by the build-time syntactic gate) and
/// the captured reduction kind, plus the opaque `method:` ctor fallback. `desugar`
/// reduces the literal `Seq` to the scalar value term; if the elements are not cleanly
/// const-reducible (a non-const element under `.sum()`/`.product()`, an empty/oversize
/// domain), it emits the fallback (the baseline opaque term) rather than refusing.
struct IterTerminalSugar {
    terminal: Terminal,
    inner: Box<dyn Sugar>,
    fallback: Box<dyn Sugar>,
}

impl IterTerminalSugar {
    /// Reduce the literal `Seq` to the value term, or `None` if it does not cleanly
    /// ground (the caller then emits the opaque fallback). Never a guessed value: every
    /// `Some` carries the EXACT reduction.
    fn reduce(&self, ctx: &SugarCtx) -> Option<Desugared> {
        let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
        // `.count()` reduces structure (the LENGTH) -- it needs no per-element const, so a
        // non-const element array still grounds its length soundly.
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
                let v = elem.value.as_ref()?; // opaque element under the predicate -> bail
                if const_eval_unary_closure(pred, v)?.as_bool()? {
                    // `.position` grounds the INDEX (always a non-negative int); `.find`
                    // grounds the ELEMENT (must be an int for the `opt:some` field sort).
                    let n = if want_index { idx as i128 } else { v.as_int()? };
                    return Some(Desugared::Term(monadic::some_term(num(n))));
                }
            }
            // No element satisfied the predicate -- the value IS `None`.
            return Some(Desugared::Term(monadic::none_term()));
        }
        // PREDICATE-BOOL terminals (`.any(p)`/`.all(p)`): const-evaluate the closure over
        // each element and OR (`any`) / AND (`all`) the per-element bools to a GROUNDED
        // bool const. EXACT-OR-BAIL: an opaque element or a closure that cannot const-eval
        // to a bool -> `None` (the opaque fallback). NOTE: the bare `assert!([..].any(..))`
        // BOOL-ASSERTION form is intercepted upstream by `translate_literal_iterator_
        // assertion` (the forall conjunction/disjunction path); THIS node grounds the
        // TERM-position form (`assert_eq!([..].any(..), true)`), where the result is a
        // value, not the asserted boolean itself.
        if let Terminal::Any(pred) | Terminal::All(pred) = &self.terminal {
            let is_all = matches!(self.terminal, Terminal::All(_));
            let mut acc = is_all; // `all` folds from true (∧-identity); `any` from false.
            for elem in &seq {
                let v = elem.value.as_ref()?; // opaque element under the predicate -> bail
                let b = const_eval_unary_closure(pred, v)?.as_bool()?;
                acc = if is_all { acc && b } else { acc || b };
            }
            return Some(Desugared::Term(bool_term(acc)));
        }
        // `.sum()` / `.product()`: fold over the elements' EXACT integer const values.
        // EXACT-OR-BAIL: a non-integer / opaque element (a float / string / unresolved
        // element) -> `None` (emit the opaque fallback), never a guessed value.
        let init: i128 = match self.terminal {
            Terminal::Sum => 0,
            Terminal::Product => 1,
            // count / positional / extremum / predicate handled above.
            _ => return None,
        };
        let mut acc = init;
        for elem in &seq {
            let n = elem.value.as_ref().and_then(ConstVal::as_int)?;
            // Overflow -> bail (a wrapped result is a different value).
            acc = match self.terminal {
                Terminal::Sum => acc.checked_add(n)?,
                Terminal::Product => acc.checked_mul(n)?,
                _ => return None,
            };
        }
        Some(Desugared::Term(num(acc)))
    }
}

impl Sugar for IterTerminalSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        // GROUND the literal reduction with teeth, or emit the opaque baseline fallback.
        // The build-time syntactic gate guarantees the inner base is a written literal, so
        // `reduce` either returns the EXACT scalar or declines (a non-const element); it
        // never reduces over a runtime domain (that domain was filtered out at build).
        match self.reduce(ctx) {
            Some(d) => Outcome::Dug(d),
            None => self.fallback.desugar(ctx),
        }
    }
}
