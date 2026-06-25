// SPDX-License-Identifier: Apache-2.0
//
// The TERM-DISPATCH LEAF the factory's term arms bottom out in when an arm's
// own PREAMBLE (not a child recursion) already computed a lawful floor:
//
//   * `ResolvedTermSugar` — a "resolved term" leaf: the arm's preamble computed a
//     concrete `Rc<Term>` (a `translate_lit` scalar, a `type_id_of_call_term`
//     const-fold, a `const_index_term_in_scope` digit-index, a folded `try_fold`
//     value, a dissolved `format!` `str_const`, a const-folded comparison Bool, a
//     `literal_aggregate_term` array/tuple, a closure / macro EUF symbol, ...). The
//     leaf simply completes that term: `desugar -> Outcome::Complete(Desugared::Term(t))`.
//     It carries NO recursion: the term is already built.
//
// There is intentionally no reasoned-incomplete leaf. A term arm that cannot construct a
// lawful floor must either decline construction and let the factory gap stay loud, or the
// source construct that truly owns a runtime/effect boundary must return a typed
// `Effect`.

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

/// Box an already-built `Rc<Term>` as the term-floor "resolved term" leaf. The shared
/// constructor the term recognizers use for an arm whose preamble computed a concrete
/// term (a folded literal, a const-index, a `TypeId::of` ctor, a dissolved `format!`
/// string, an array/tuple aggregate, a closure / macro EUF symbol, ...).
pub(crate) fn resolved_term(term: Rc<Term>) -> Box<dyn Sugar> {
    Box::new(ResolvedTermSugar { term })
}
