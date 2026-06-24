// SPDX-License-Identifier: Apache-2.0
//
// `CtorSugar`: the generic CONSTRUCTIVE named-ctor TERM node — the shared node the
// term arms whose `Term::Ctor` has no dedicated node build through (`ref`/`ref_mut`,
// `await`, `field:*`, `cast:*`, `range`/`range_incl`, `struct:*` + its `field:*`
// subctors). It completes each child to its `Term` in source order and emits
// `Term::Ctor { name, args }`. A child `Incomplete` propagates verbatim; a non-term child
// is a construction-law panic because `CtorSugar` is built only with `TermFloor`
// children. This was an inline node inside the old fat factory; it now lives in
// its own module so the factory holds no node structs -- only the registries and
// walks.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::sugar::factory::{SugarBody, TermFloor};
use crate::{Desugared, Outcome, Sugar, SugarCtx};

/// A generic CONSTRUCTIVE named-ctor term node: completes each child to its `Term` in order
/// and emits `Term::Ctor { name, args }`.
pub(crate) struct CtorSugar {
    name: String,
    args: Vec<SugarBody<TermFloor>>,
}

impl CtorSugar {
    pub(crate) fn new(name: impl Into<String>, args: Vec<SugarBody<TermFloor>>) -> Self {
        CtorSugar {
            name: name.into(),
            args,
        }
    }
}

impl Sugar for CtorSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let mut args = Vec::new();
        for arg in &self.args {
            let term = match arg.reduce(ctx) {
                Outcome::Complete(d) => match d.into_term() {
                    Some(t) => t,
                    None => ctor_gap(&self.name),
                },
                Outcome::Incomplete(e) => return Outcome::Incomplete(e),
            };
            args.push(term);
        }
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: self.name.clone(),
            args,
        })))
    }
}

fn ctor_gap(name: &str) -> ! {
    panic!(
        "CtorSugar `{name}` child completed a non-Term where a Term was required; write more Sugar for this AST"
    )
}
