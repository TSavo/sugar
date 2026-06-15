// SPDX-License-Identifier: Apache-2.0
//
// MutationEffect -- captured-state mutation / iterator advance.
//
// Moved verbatim from lib.rs in the file-split refactor (one file per
// SideEffect). Behaviour-preserving: each effect's reason()/boundary() is
// byte-identical to the monolith; only its physical location changed.

use super::{SideEffect, SourceMemento};

/// MUTATION: the closure / loop body MUTATES captured or local state (`+=`, `&mut`,
/// `.push`, an assignment). The asserted value varies per iteration independently of
/// the bound var, so a single universal over it would be a false claim. A source
/// property -- no value lifter could read a single timeless `t`. (HALF 2 of the
/// fold-closure bucket.)
pub(crate) struct MutationEffect {
    pub(crate) boundary: String,
}

impl SideEffect for MutationEffect {
    fn reason(&self) -> String {
        // The proto string the collector already emits for this case (kept verbatim
        // so `refusal_disposition` classifies it terminal and the CID is conserved).
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
