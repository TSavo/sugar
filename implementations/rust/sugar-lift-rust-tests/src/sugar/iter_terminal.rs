// SPDX-License-Identifier: Apache-2.0
//
// `IterTerminalSugar`: the iterator REDUCTION terminals (`.sum()` / `.product()` /
// `.count()`) over a FINITE LITERAL domain. Each writes the EQUIVALENT FOL of its
// operation over the inner literal `Seq` -- the construction axiom applied to a terminal
// that collapses a sequence to a single SCALAR value:
//
//   * `.sum()`     -> `num(Σ elements)`   (`[1,2,3,4,5].iter().sum()` -> `num(15)`)
//   * `.product()` -> `num(Π elements)`   (`[1,2,3,4,5].iter().product()` -> `num(120)`)
//   * `.count()`   -> `num(len)`          (`[1,2,3].iter().count()` -> `num(3)`)
//
// This is the TERM-position node -- it sits in the term registry BEFORE
// `method_call_term::recognize`, so a recognized literal-domain reduction grounds to its
// value instead of the opaque `method:<m>` EUF ctor. A receiver chain the literal-Seq
// machinery does not own (`peel_fold_adaptors` -> `None`: an unknown adaptor, a closure
// adaptor that is not const-evaluable here, a `let`-bound receiver that does not resolve
// to a literal) is NOT recognized -> falls through to the opaque `method:` ctor (the
// established sound under-claim).
//
// WHY ONLY THE SCALAR REDUCTIONS (and not `.next()`/`.nth()`/`.min()`/`.max()`). The
// positional / extremal terminals return `Option<&T>`; `assert_eq!(<term>, Some(&1))`
// is lifted by `assertion_entry_from_relation` as the FEDERATED user-type-equality
// shape `call:eq:Some(lhs, rhs) == true` (a `Some(_)` operand is a user `PartialEq`
// dispatch we do NOT interpret -- an opaque EUF call). A standalone bad twin
// (`Some(&2)`) then stays z3-SAT (the opaque `eq:Some` call can equal `true`), so the
// dig would NOT meet the HARD SOUNDNESS bad-twin-UNSAT bar -- it would be a FAKE-DIG.
// Those forms therefore stay REFUSED (the opaque `method:` ctor), honest future work for
// when the lifter gains value-level `Option` equality. The scalar reductions compare
// against a bare int literal, so `=( Σ, k )` IS value-refutable (a wrong `k` is z3-UNSAT)
// -- the only forms grounded here.
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
use crate::{peel_fold_adaptors, strip_refs_groups, ConstVal, Desugared, Outcome, Sugar, SugarCtx};

/// Which reduction this node performs -- captured at construction from the method name.
#[derive(Clone, Copy)]
enum Terminal {
    Sum,
    Product,
    Count,
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
    if !call.args.is_empty() {
        return None;
    }
    let terminal = match call.method.to_string().as_str() {
        "sum" => Terminal::Sum,
        "product" => Terminal::Product,
        "count" => Terminal::Count,
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
    /// Reduce the literal `Seq` to the scalar value term, or `None` if it does not cleanly
    /// ground (the caller then emits the opaque fallback). Never a guessed value: every
    /// `Some` carries the EXACT reduction.
    fn reduce(&self, ctx: &SugarCtx) -> Option<Desugared> {
        let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
        // `.count()` reduces structure (the LENGTH) -- it needs no per-element const, so a
        // non-const element array still grounds its length soundly.
        if matches!(self.terminal, Terminal::Count) {
            return Some(Desugared::Term(num(seq.len() as i128)));
        }
        // `.sum()` / `.product()`: fold over the elements' EXACT integer const values.
        // EXACT-OR-BAIL: a non-integer / opaque element (a float / string / unresolved
        // element) -> `None` (emit the opaque fallback), never a guessed value.
        let init: i128 = match self.terminal {
            Terminal::Sum => 0,
            Terminal::Product => 1,
            Terminal::Count => return None, // handled above
        };
        let mut acc = init;
        for elem in &seq {
            let n = elem.value.as_ref().and_then(ConstVal::as_int)?;
            // Overflow -> bail (a wrapped result is a different value).
            acc = match self.terminal {
                Terminal::Sum => acc.checked_add(n)?,
                Terminal::Product => acc.checked_mul(n)?,
                Terminal::Count => return None,
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
