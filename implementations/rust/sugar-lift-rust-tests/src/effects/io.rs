// SPDX-License-Identifier: Apache-2.0
//
// IoEffect -- the closure body performs IO.
//
// Moved verbatim from lib.rs in the file-split refactor (one file per
// SideEffect). Behaviour-preserving: each effect's reason()/boundary() is
// byte-identical to the monolith; only its physical location changed.

use super::{SideEffect, SourceMemento};

/// IO: the body performs IO (a `write` / `send` to a runtime sink). The observed
/// value is a runtime effect, not a constructed literal. A source property; carried
/// under the opaque-accessor proto reason. (`write`/`send` are in
/// `CLOSURE_BODY_MUTATING_METHODS`, so an IO closure body is caught as a mutation
/// today; named here so the catalog records the IO cause.)
pub(crate) struct IoEffect {
    pub(crate) boundary: String,
}

impl SideEffect for IoEffect {
    fn reason(&self) -> String {
        "assertion in a closure over an opaque/effectful accessor (bin-2: runtime \
         data, not constructible from source literals); refused"
            .to_string()
    }
    fn boundary(&self) -> SourceMemento {
        SourceMemento {
            boundary: self.boundary.clone(),
        }
    }
}
