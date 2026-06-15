// SPDX-License-Identifier: Apache-2.0
//
// IterAdvanceEffect -- a captured iterator is advanced.
//
// Moved verbatim from lib.rs in the file-split refactor (one file per
// SideEffect). Behaviour-preserving: each effect's reason()/boundary() is
// byte-identical to the monolith; only its physical location changed.

use super::{SideEffect, SourceMemento};

/// ITER-ADVANCE: the body advances a captured iterator (`iter.next()` / `nth += 1`),
/// a sequence/position-dependent side effect. Distinct CAUSE from `MutationEffect`
/// (no captured-state assignment is needed), but the SAME terminal class -- the
/// observed value is per-iteration, not timeless. (Carried under the side-effecting
/// closure-body proto reason today; typed here as its own named boundary.)
pub(crate) struct IterAdvanceEffect {
    pub(crate) boundary: String,
}

impl SideEffect for IterAdvanceEffect {
    fn reason(&self) -> String {
        "assertion in a side-effecting closure body (mutates captured state / \
         advances an iterator); not a pure point-wise claim; refused"
            .to_string()
    }
    fn boundary(&self) -> SourceMemento {
        SourceMemento {
            boundary: self.boundary.clone(),
        }
    }
}
