// SPDX-License-Identifier: Apache-2.0
//
// `CtorSugar`: the generic CONSTRUCTIVE named-ctor TERM node — the shared node the
// term arms whose `Term::Ctor` has no dedicated node build through (`ref`/`ref_mut`,
// `await`, `field:*`, `cast:*`, `range`/`range_incl`, `struct:*` + its `field:*`
// subctors). It completes each child to its `Term` in source order and emits
// `Term::Ctor { name, args }`. A child `Incomplete` propagates verbatim; a non-term child
// completes to the structural backstop (`from_opt(None)`). This was an inline node inside
// the old fat factory; it now lives in its own module so the factory holds no node
// structs — only the two registries and the two walks.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::{Desugared, Outcome, Sugar, SugarCtx};

/// A generic CONSTRUCTIVE named-ctor term node: completes each child to its `Term` in order
/// and emits `Term::Ctor { name, args }`.
pub(crate) struct CtorSugar {
    name: String,
    args: Vec<Box<dyn Sugar>>,
}

impl CtorSugar {
    pub(crate) fn new(name: impl Into<String>, args: Vec<Box<dyn Sugar>>) -> Self {
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
            let term = match arg.desugar(ctx) {
                Outcome::Complete(d) => match d.into_term() {
                    Some(t) => t,
                    None => return Outcome::from_opt(None),
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
