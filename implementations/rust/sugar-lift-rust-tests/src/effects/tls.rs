// SPDX-License-Identifier: Apache-2.0
//
// TlsEffect -- a thread_local!.with(..) opaque accessor.
//
// Moved verbatim from lib.rs in the file-split refactor (one file per
// SideEffect). Behaviour-preserving: each effect's reason()/boundary() is
// byte-identical to the monolith; only its physical location changed.

use super::{SideEffect, SourceMemento};

/// TLS: a `thread_local!` `.with(|x| ..)` -- the closure ranges over thread-local
/// runtime state, an opaque non-constructed value. A specialization of the opaque
/// accessor boundary (its proto reason). Named so the catalog records the TLS cause.
pub(crate) struct TlsEffect {
    pub(crate) boundary: String,
}

impl SideEffect for TlsEffect {
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
