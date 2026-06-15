// SPDX-License-Identifier: Apache-2.0
//
// The `SideEffect` hierarchy, one file per effect -- the typed BAIL, mirror of
// `Sugar`. Decomposed from the lib.rs monolith into a module tree. The trait
// `SideEffect`, the `SourceMemento` rope, and the `Outcome` enum stay here as
// the shared spine; each named effect lives in its own file.

use crate::*;

// ── The typed BAIL: a `SideEffect` hierarchy (the mirror of `Sugar`) ─────────
//
// `Sugar::desugar` is the DIG side -- it walks inward until it reaches literal
// truth (`Dug`). When the walk hits MONKEY BUSINESS -- a side effect, an opaque
// runtime value, an iterator advance, a mutable read -- the desugar bails. Today
// that bail is an untyped `None` + a reason STRING handled downstream by
// `refusal_disposition` (terminal-whitelist -> Refused, else Unclassified).
//
// `SideEffect` RETYPES that bail. A `SideEffect` is a NAMED, WARRANTED order-loss
// boundary: a structural property of the SOURCE (not a missing lift) that destroys
// the single timeless `t` a point-wise value claim needs. Each kind owns its own
// `reason()` (the proto refusal string, recognized as terminal by
// `refusal_disposition`) and its own `boundary()` (a `SourceMemento` -- the bail-side
// rope, mirroring the dig-side `Warrant`). The reason string is the wire format the
// existing collector emits into `skip_reasons`; minting it from a typed effect makes
// the BAIL a claim with a cause, not a bare string.
//
// SOUNDNESS (the critical line, do NOT cross it): a `SideEffect` is ONLY for a
// PROVABLE order-loss effect -- a syntactic mutation / `iter.next()` / `&mut` /
// `.push` on captured state, a genuinely runtime/opaque value (param, runtime call
// result, TLS, IO), a mutable-container read. A PURE-BUT-UNTRANSLATED term (a pure
// stdlib method we have not transcribed yet) is NOT a `SideEffect`: it stays
// UNCLASSIFIED (honest future work for a `Sugar`/`const_eval` arm). Reclassifying a
// pure-untranslated term as a `SideEffect` would be a FAKE-REFUSE -- mislabeling our
// own work as a source property. EFFECT-OR-LEAVE: if we cannot PROVE it is an
// order-loss effect, we leave it unclassified.

/// The bail-side rope: a `SourceMemento` ties a refusal to the source boundary that
/// warrants it (the span / token-key of the offending construct). The mirror of the
/// dig-side `Warrant` (which ropes a discharged constraint to the sugar that minted
/// it). `boundary` is the rendered token-key / description of the order-loss site.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct SourceMemento {
    /// The source construct that is the order-loss boundary (token-key / description).
    pub(crate) boundary: String,
}

/// A typed order-loss boundary -- the typed BAIL, mirror of `Sugar`. `reason()`
/// returns the terminal refusal string (recognized by `refusal_disposition`);
/// `boundary()` returns the `SourceMemento` warranting that the bail names a SOURCE
/// property. Each implementor is a single NAMED effect (a mutation, an iterator
/// advance, an opaque runtime value, TLS, IO, a mutable read). Adding an effect =
/// adding one struct with `reason()` + `boundary()`.
pub(crate) trait SideEffect {
    fn reason(&self) -> String;
    fn boundary(&self) -> SourceMemento;
}

/// The outcome of a desugar attempt, typed both ways. `Dug` reached truth (a
/// discharged `Desugared`); `Hit` struck a NAMED, WARRANTED order-loss boundary (a
/// terminal, loud refusal with a cause). This is the typed form of "Option<Desugared>
/// + reason string"; the collector unwraps it to the existing entries / skip_reasons
/// emission so the wire format (and thus the CID + counts) is unchanged.
#[allow(dead_code)]
pub(crate) enum Outcome {
    /// Reached truth: the desugared literal floor / emitted obligation. -> discharged.
    Dug(Desugared),
    /// Struck a named order-loss boundary. -> refused (terminal, loud, with cause).
    Hit(Box<dyn SideEffect>),
}

pub(crate) mod io;
pub(crate) mod iter_advance;
pub(crate) mod mutation;
pub(crate) mod opaque_runtime;
pub(crate) mod temporal_read;
pub(crate) mod tls;
