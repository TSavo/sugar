// SPDX-License-Identifier: Apache-2.0
//
// Structural backstop Sugar nodes.

use crate::{Outcome, Sugar, SugarCtx};

pub(crate) fn unsupported() -> Box<dyn Sugar> {
    Box::new(UnsupportedSugar)
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
