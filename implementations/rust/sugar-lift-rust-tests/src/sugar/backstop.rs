// SPDX-License-Identifier: Apache-2.0
//
// Structural backstop Sugar nodes.

use crate::{Outcome, Sugar, SugarCtx};

pub(crate) fn unsupported() -> Box<dyn Sugar> {
    Box::new(UnsupportedSugar)
}

pub(crate) fn boxed<S: Sugar + 'static>(node: Option<S>) -> Box<dyn Sugar> {
    match node {
        Some(node) => Box::new(node),
        None => unsupported(),
    }
}

struct UnsupportedSugar;

impl Sugar for UnsupportedSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        factory_gap("no sugar candidate reached this source shape")
    }
}

fn factory_gap(reason: &str) -> ! {
    panic!("factory structural gap: {reason}")
}
