// SPDX-License-Identifier: Apache-2.0
//
// `IterTerminalSugar`: the iterator REDUCTION + POSITIONAL terminals over a FINITE
// LITERAL domain. Each writes the EQUIVALENT FOL of its operation over the inner literal
// `Seq` -- the construction axiom applied to a terminal that collapses a sequence to a
// single value:
//
//   * `.sum()`     -> `num(Σ elements)`   (`[1,2,3,4,5].iter().sum()` -> `num(15)`)
//   * `.product()` -> `num(Π elements)`   (`[1,2,3,4,5].iter().product()` -> `num(120)`)
//   * `.count()`   -> `num(len)`          (`[1,2,3].iter().count()` -> `num(3)`)
//   * `.next()`    -> `Some(elem[0])`     (`[1,2,3].iter().next()` -> `opt:some(1)`)
//   * `.nth(k)`    -> `Some(elem[k])` or `None` past the end
//   * `.last()`    -> `Some(elem[len-1])` (or `None` for the empty Seq)
//
// This is the TERM-position node -- it sits in the term registry BEFORE
// `method_call_term::recognize`, so a recognized literal-domain reduction grounds to its
// value instead of the opaque `method:<m>` EUF ctor. A receiver chain the literal-Seq
// machinery does not own (`peel_fold_adaptors` -> `None`: an unknown adaptor, a closure
// adaptor that is not const-evaluable here, a `let`-bound receiver that does not resolve
// to a literal) is NOT recognized -> falls through to the opaque `method:` ctor (the
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

use sugar_ir_symbolic::num;
use syn::Expr;

use crate::sugar::factory::FactoryCtx;
use crate::sugar::literal::LiteralSugar;
use crate::sugar::method_call_term;
use crate::sugar::monadic;
use crate::{
    parse_int_lit, peel_fold_adaptors, strip_refs_groups, ConstVal, Desugared, Outcome, Sugar,
    SugarCtx,
};

/// Which terminal this node performs -- captured at construction from the method name.
#[derive(Clone, Copy)]
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
}

/// TERM recognizer for the iterator scalar-reduction terminals. `Some` only when the
/// method is a recognized reduction AND the receiver chain peels to a chain whose BASE is
/// a WRITTEN LITERAL `Seq` (a syntactic array `[..]` / closed range `a..b`). Any other
/// receiver (an unknown adaptor `peel` -> `None`, or a non-literal base -- `v[..4]`, a
/// `let`-bound name `translate_term_in_scope` cannot resolve, an opaque `io`, a runtime
/// `make_v()`) returns `None`, so the walk falls through to `method_call_term` (the opaque
/// `method:` ctor, the established sound under-claim) -- BYTE-IDENTICAL to baseline.
///
/// The SYNTACTIC-LITERAL GATE is the soundness line drawn at BUILD time (the factory
/// dispatch is build-time -- a recognizer that returns `Some` commits the node, so a
/// desugar-time `Hit` could NOT fall through). Only a written literal base is ever
/// recognized; an effect / runtime / opaque domain is NOT a syntactic literal -> never
/// reaches the reduction. As belt-and-suspenders, the node ALSO holds the opaque
/// `method_call_term` fallback and emits IT (never refusing) if the literal desugar does
/// not cleanly ground (a non-const element under `.sum()`/`.product()`, an empty/oversize
/// domain) -- so the node can only ever ground-with-teeth or reproduce the baseline opaque
/// term, never turn a baseline lift into a refusal.
pub(crate) fn recognize(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let terminal = match call.method.to_string().as_str() {
        // Scalar reductions and the nullary positional terminals take no args.
        "sum" if call.args.is_empty() => Terminal::Sum,
        "product" if call.args.is_empty() => Terminal::Product,
        "count" if call.args.is_empty() => Terminal::Count,
        "next" if call.args.is_empty() => Terminal::Next,
        "last" if call.args.is_empty() => Terminal::Last,
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
        _ => return None,
    };
    // Peel the receiver adaptor chain to (base, ordered wrappers) EXACTLY as
    // `fold::decompose_seq` does. `None` (an unknown adaptor / unresolvable binding) ->
    // NOT RECOGNIZED -> fall through to the opaque ctor.
    let (base, adaptors) = peel_fold_adaptors(&call.receiver, fcx.let_inits, 0)?;
    // THE SYNTACTIC-LITERAL GATE: the base must be a WRITTEN literal array / range. A
    // non-literal base (`v[..4]` Index, a bare `let`-bound / opaque / runtime receiver
    // `peel` could not resolve to a literal) is NOT recognized -> fall through to the
    // opaque ctor (baseline). This is the build-time soundness boundary: we never even
    // construct the reduction over a non-literal domain.
    if !matches!(strip_refs_groups(base), Expr::Array(_) | Expr::Range(_)) {
        return None;
    }
    // Build the inner seq-`Sugar`: `LiteralSugar` base nested under the adaptor decorators
    // (base->terminal order), mirroring `fold::decompose_seq`.
    let mut inner: Box<dyn Sugar> = Box::new(LiteralSugar { base: base.clone() });
    for wrap in adaptors {
        inner = wrap(inner);
    }
    // The opaque `method:` fallback -- the EXACT node `method_call_term::recognize` builds
    // for this same expr (built DIRECTLY, not via `build_term`, which would re-enter this
    // recognizer and loop). `method_call_term` owns every `Expr::MethodCall`, so it always
    // `Some`s here; the `?` is a defensive no-op. Emitted verbatim if the literal desugar
    // does not cleanly ground, so this node never refuses a form baseline lifted opaquely.
    let fallback = method_call_term::recognize(expr, fcx)?;
    Some(Box::new(IterTerminalSugar {
        terminal,
        inner,
        fallback,
    }))
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
        if let Some(idx) = match self.terminal {
            Terminal::Next => Some(0usize),
            Terminal::Nth(k) => Some(k),
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
        // `.sum()` / `.product()`: fold over the elements' EXACT integer const values.
        // EXACT-OR-BAIL: a non-integer / opaque element (a float / string / unresolved
        // element) -> `None` (emit the opaque fallback), never a guessed value.
        let init: i128 = match self.terminal {
            Terminal::Sum => 0,
            Terminal::Product => 1,
            // count / positional handled above.
            Terminal::Count | Terminal::Next | Terminal::Nth(_) | Terminal::Last => return None,
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
