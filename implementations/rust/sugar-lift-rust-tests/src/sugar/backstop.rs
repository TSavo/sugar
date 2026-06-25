// SPDX-License-Identifier: Apache-2.0
//
// Structural backstop Sugar nodes.

use crate::{Outcome, Sugar, SugarCtx};

pub(crate) fn unsupported(reason: String) -> Box<dyn Sugar> {
    Box::new(UnsupportedSugar { reason })
}

struct UnsupportedSugar {
    reason: String,
}

impl Sugar for UnsupportedSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        factory_gap(&self.reason)
    }
}

fn factory_gap(reason: &str) -> ! {
    panic!("factory structural gap: {reason}")
}
