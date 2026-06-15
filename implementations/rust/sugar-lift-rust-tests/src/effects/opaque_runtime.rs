// SPDX-License-Identifier: Apache-2.0
//
// OpaqueRuntimeEffect -- bin-2 runtime data, not source-constructible.
//
// Moved verbatim from lib.rs in the file-split refactor (one file per
// SideEffect). Behaviour-preserving: each effect's reason()/boundary() is
// byte-identical to the monolith; only its physical location changed.

use super::{SideEffect, SourceMemento};

/// OPAQUE-RUNTIME (bin-2): the iterated / asserted value is RUNTIME data -- a param, a
/// runtime call result, an opaque receiver -- not constructible from source literals.
/// There is no construction to walk, so no finite universe to emit. A source property.
pub(crate) struct OpaqueRuntimeEffect {
    pub(crate) boundary: String,
    /// True for an effectful ACCESSOR (`.with` / `.with_unfilled_buf`) over opaque
    /// state; false for a plain opaque RECEIVER (`coll.iter().for_each(..)` where
    /// `coll` is runtime). Selects the matching proto reason (both `bin-2` terminal).
    pub(crate) accessor: bool,
}

impl SideEffect for OpaqueRuntimeEffect {
    fn reason(&self) -> String {
        if self.accessor {
            "assertion in a closure over an opaque/effectful accessor (bin-2: runtime \
             data, not constructible from source literals); refused"
                .to_string()
        } else {
            "assertion in a closure over an opaque runtime receiver (bin-2: runtime data, \
             not constructible from source literals); refused"
                .to_string()
        }
    }
    fn boundary(&self) -> SourceMemento {
        SourceMemento {
            boundary: self.boundary.clone(),
        }
    }
}
