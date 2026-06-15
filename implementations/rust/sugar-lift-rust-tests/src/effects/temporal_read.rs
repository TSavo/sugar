// SPDX-License-Identifier: Apache-2.0
//
// TemporalReadEffect -- a read of a mutable container (a[i]).
//
// Moved verbatim from lib.rs in the file-split refactor (one file per
// SideEffect). Behaviour-preserving: each effect's reason()/boundary() is
// byte-identical to the monolith; only its physical location changed.

use super::{SideEffect, SourceMemento};

/// TEMPORAL-READ: a read of a MUTABLE container (`a[i]` where `a` is a provably-`mut`
/// local that the `mut` oracle flags). The container may be index-assigned or
/// method-mutated between program points, so `index(a, i)` has no single timeless `t`
/// -- the read is sequence/position dependent. The mirror, for an index READ, of the
/// already-terminal `temporally unstable` reason (a term reading a MUTATED local).
///
/// THE DRAIN: this boundary fell to the silent-shrug (unclassified) pile because its
/// reason ("mutable container is not temporally stable") was never added to the
/// terminal whitelist, even though it is the SAME provable order-loss effect as the
/// whitelisted `temporally unstable`. Typing it as a `SideEffect` (and whitelisting
/// its reason) moves these effect-shaped cases unclassified -> refused.
///
/// SOUNDNESS: emitted ONLY when the `mut` oracle (`scope.is_mut_local`) PROVES the
/// container is a mutable local. A non-`mut` (provably-immutable) container reads as a
/// stable `index(a,i)` term and never reaches here -- so this can only refuse a
/// genuinely-mutable read, never a pure one.
pub(crate) struct TemporalReadEffect {
    pub(crate) boundary: String,
}

impl SideEffect for TemporalReadEffect {
    fn reason(&self) -> String {
        // Carries the existing index-read substring so a single whitelist entry
        // ("mutable container is not temporally stable") recognizes it; the
        // `unsupported term` prefix the term path already attaches is preserved by
        // the emit site, so this is the bare boundary clause.
        format!(
            "unsupported term `{}`: mutable container is not temporally stable",
            self.boundary
        )
    }
    fn boundary(&self) -> SourceMemento {
        SourceMemento {
            boundary: self.boundary.clone(),
        }
    }
}
