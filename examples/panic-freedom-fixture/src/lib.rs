// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Panic-freedom fixture. Two production functions, each calling `Option::unwrap`
// (a PARTIAL: it panics when the Option is None). The substrate's job is to
// tell them apart:
//
//   * `guarded_unwrap`   -- the `.unwrap()` is DOMINATED by `if opt.is_some()`,
//                           so the partial's precondition (`is_some(opt)`) is
//                           established on the then-branch. The lifter wraps the
//                           then-branch in `cf_guarded(is_some(opt), ..)`; the
//                           verifier discharges the obligation
//                           `is_some(opt) => is_some(opt)` and reports the site
//                           PANIC-SAFE (K=1).
//
//   * `unguarded_unwrap` -- a bare `.unwrap()` with no dominating guard. The
//                           partial's pre is unprovable, so the site is honestly
//                           UNDECIDABLE (unproven). It is the NEGATIVE control:
//                           it must NOT be vacuous-passed as "cannot panic".
//
// Both call sites bridge into the rust-std shim's `option_unwrap` contract,
// whose PRE is `is_some(opt)`. The pre-bearing target selection is the
// soundness hinge: targeting the post-only `option_unwrap` would vacuous-pass
// the unguarded case (a false "cannot panic"). The unguarded -> undecidable
// detector below is the guarantee that the pre-bearing target was selected.

/// GUARDED: the `.unwrap()` runs only when `opt.is_some()` is established.
/// Panic-free, and provably so: the then-branch carries the `is_some` guard
/// that discharges `option_unwrap`'s precondition.
pub fn guarded_unwrap(opt: Option<i64>) -> i64 {
    if opt.is_some() {
        opt.unwrap()
    } else {
        0
    }
}

/// UNGUARDED: a bare `.unwrap()` with no dominating guard. This CAN panic (when
/// `opt` is `None`). The substrate must report it UNDECIDABLE -- it cannot show
/// the site does not panic -- and must NOT vacuous-pass it. The negative
/// control for the soundness gate.
pub fn unguarded_unwrap(opt: Option<i64>) -> i64 {
    opt.unwrap()
}
