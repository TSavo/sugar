// SPDX-License-Identifier: Apache-2.0
//
// The two TERM-DISPATCH LEAVES the factory's term arms bottom out in when an arm's
// own PREAMBLE (not a child recursion) already decided the verdict:
//
//   * `ResolvedTermSugar` — a "resolved term" leaf: the arm's preamble computed a
//     concrete `Rc<Term>` (a `translate_lit` scalar, a `type_id_of_call_term`
//     const-fold, a `const_index_term_in_scope` digit-index, a folded `try_fold`
//     value, a dissolved `format!` `str_const`, a const-folded comparison Bool, a
//     `literal_aggregate_term` array/tuple, a closure / macro EUF symbol, ...). The
//     leaf simply completes that term: `desugar -> Outcome::Complete(Desugared::Term(t))`. This
//     is the dual of an `Err`-side `ReasonedIncompleteSugar` and carries NO recursion (the
//     term is already built).
//
//   * `ReasonedIncompleteSugar` — a legacy gap leaf: the arm produced an `Err(reason)`
//     in the old `translate_term_in_scope` (a `term_binop_name` `None`
//     "unsupported term operator", an `is_immutable_value_expr`-failing `&mut`, a
//     raw pointer, a non-scalar cast, an `..rest` struct literal, a mut-local macro,
//     the `other =>` "unsupported term" catch-all, ...). A legacy reason is NOT a
//     terminal effect. The owner must either construct a typed floor or return a typed
//     `Effect`; until then this leaf panics as a factory gap.
//
// These are the term-dispatch analogue of `backstop::UnsupportedSugar` (the bare
// structural backstop), but EARNED: they carry the arm's own pre-built term / reason,
// not the generic structural-backstop string. They never DECIDE the walk — the arm
// already did; the leaf just holds the verdict so it propagates inside-out through the
// composite term nodes for free.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::{Desugared, Outcome, Sugar, SugarCtx};

/// The "resolved term" leaf: holds an already-built `Rc<Term>` and completes it. Built by
/// a factory term arm whose preamble computed a concrete term (a folded literal, a
/// const-index, a `TypeId::of` ctor, a dissolved `format!` string, ...). `ctx` is
/// unused: the term is fixed at construction.
pub(crate) struct ResolvedTermSugar {
    pub(crate) term: Rc<Term>,
}

impl Sugar for ResolvedTermSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Complete(Desugared::Term(Rc::clone(&self.term)))
    }
}

/// A legacy reason leaf. This is an engine gap, not an honorable runtime effect: owners
/// that still reach this must be split into typed Complete/Incomplete sugar.
pub(crate) struct ReasonedIncompleteSugar {
    pub(crate) reason: String,
}

impl Sugar for ReasonedIncompleteSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        panic!(
            "legacy reason leaf reached desugar without a typed effect owner: {}",
            self.reason
        )
    }
}

/// Box an already-built `Rc<Term>` as the term-floor "resolved term" leaf. The shared
/// constructor the term recognizers use for an arm whose preamble computed a concrete
/// term (a folded literal, a const-index, a `TypeId::of` ctor, a dissolved `format!`
/// string, an array/tuple aggregate, a closure / macro EUF symbol, ...).
pub(crate) fn resolved_term(term: Rc<Term>) -> Box<dyn Sugar> {
    Box::new(ResolvedTermSugar { term })
}

/// Box a verbatim refusal string as the term-floor "reasoned-Incomplete" leaf. The shared
/// constructor the term recognizers use for an arm that produced an `Err(reason)`.
pub(crate) fn reasoned_incomplete(reason: String) -> Box<dyn Sugar> {
    Box::new(ReasonedIncompleteSugar { reason })
}
