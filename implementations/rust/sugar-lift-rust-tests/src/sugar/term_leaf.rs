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
//     leaf simply Digs that term: `desugar -> Outcome::Dug(Desugared::Term(t))`. This
//     is the dual of an `Err`-side `ReasonedHitSugar` and carries NO recursion (the
//     term is already built).
//
//   * `ReasonedHitSugar` — a "reasoned-Hit" leaf: the arm produced an `Err(reason)`
//     in the legacy `translate_term_in_scope` (a `term_binop_name` `None`
//     "unsupported term operator", an `is_immutable_value_expr`-failing `&mut`, a
//     raw pointer, a non-scalar cast, an `..rest` struct literal, a mut-local macro,
//     the `other =>` "unsupported term" catch-all, ...). The leaf Hits the SAME
//     reason string verbatim, carried as `Effect::Unsupported { reason }` — the
//     terminal, loud, reasoned bail (NEVER a silent skip). Consumed by the thin
//     `translate_term_in_scope` adapter via `effect.reason()`, this reproduces the
//     legacy `Err(reason)` byte-identically, so the wire format (CID + counts) is
//     conserved.
//
// These are the term-dispatch analogue of `factory::UnsupportedSugar` (the bare
// structural backstop), but EARNED: they carry the arm's own pre-built term / reason,
// not the generic structural-backstop string. They never DECIDE the walk — the arm
// already did; the leaf just holds the verdict so it propagates inside-out through the
// composite term nodes for free.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::{Desugared, Effect, Outcome, Sugar, SugarCtx};

/// The "resolved term" leaf: holds an already-built `Rc<Term>` and Digs it. Built by
/// a factory term arm whose preamble computed a concrete term (a folded literal, a
/// const-index, a `TypeId::of` ctor, a dissolved `format!` string, ...). `ctx` is
/// unused: the term is fixed at construction.
pub(crate) struct ResolvedTermSugar {
    pub(crate) term: Rc<Term>,
}

impl Sugar for ResolvedTermSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Dug(Desugared::Term(Rc::clone(&self.term)))
    }
}

/// The "reasoned-Hit" leaf: holds the verbatim reason string a legacy
/// `translate_term_in_scope` arm produced via `Err(reason)`, and Hits
/// `Effect::Unsupported { reason }`. The thin adapter renders it back through
/// `effect.reason()`, reproducing the legacy `Err` byte-identically. `ctx` is unused.
pub(crate) struct ReasonedHitSugar {
    pub(crate) reason: String,
}

impl Sugar for ReasonedHitSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Hit(Effect::Unsupported {
            reason: self.reason.clone(),
        })
    }
}

/// Box an already-built `Rc<Term>` as the term-floor "resolved term" leaf. The shared
/// constructor the term recognizers use for an arm whose preamble computed a concrete
/// term (a folded literal, a const-index, a `TypeId::of` ctor, a dissolved `format!`
/// string, an array/tuple aggregate, a closure / macro EUF symbol, ...).
pub(crate) fn resolved_term(term: Rc<Term>) -> Box<dyn Sugar> {
    Box::new(ResolvedTermSugar { term })
}

/// Box a verbatim refusal string as the term-floor "reasoned-Hit" leaf. The shared
/// constructor the term recognizers use for an arm that produced an `Err(reason)`.
pub(crate) fn reasoned_hit(reason: String) -> Box<dyn Sugar> {
    Box::new(ReasonedHitSugar { reason })
}
