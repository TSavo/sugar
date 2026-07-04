// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Shared TERM node for literal aggregate constructors (`Array`, `Tuple`, `Vec`).
// Recognizers only capture the typed element bodies; the literal-vs-aggregate
// key is decided lazily after each child has reduced to its real term floor.

use sugar_ir_symbolic::make_var;

use crate::sugar::factory::{SugarBody, TermFloor};
use crate::{canonical_term_sig, is_literal_identity_term, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) struct LiteralAggregateTermSugar {
    kind: &'static str,
    elems: Vec<SugarBody<TermFloor>>,
}

impl LiteralAggregateTermSugar {
    pub(crate) fn new(kind: &'static str, elems: Vec<SugarBody<TermFloor>>) -> Self {
        Self { kind, elems }
    }
}

impl Sugar for LiteralAggregateTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let mut args = Vec::with_capacity(self.elems.len());
        let mut all_literal = true;
        for elem in &self.elems {
            let term = match elem.reduce(ctx) {
                Outcome::Complete(desugared) => desugared.into_term().unwrap_or_else(|| {
                    panic!(
                        "{} aggregate child completed a non-Term where a Term was required",
                        self.kind
                    )
                }),
                Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
            };
            if !is_literal_identity_term(term.as_ref()) {
                all_literal = false;
            }
            args.push(term);
        }
        let inner = args
            .iter()
            .map(|arg| canonical_term_sig(arg))
            .collect::<Vec<_>>()
            .join(",");
        let prefix = if all_literal { "literal" } else { "agg" };
        Outcome::Complete(Desugared::Term(make_var(format!(
            "{prefix}:{}({inner})",
            self.kind
        ))))
    }
}
