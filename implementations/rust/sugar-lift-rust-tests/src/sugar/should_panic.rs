// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `should_panic` — lift machinery for `#[test] #[should_panic]` functions.
//
// A `#[should_panic]` attribute asserts that the test function body panics.
// This module owns the ENTIRE should_panic dimension:
//
//  1. `has_attr` — attribute presence check (moved from lib.rs `has_should_panic_attr`).
//  2. `lift_entries_if_applicable` — single entry point called from `visit_test_fn`.
//     If the function carries `#[should_panic]`, walks the body temporal callsites
//     and emits assertion entries:
//     - PREFIX callsites → panic-freedom fact (NON-inverted, Warranted): setup
//       calls must reach normal-return.
//     - TERMINAL callsite → INVERTED panic-freedom fact (Warranted): the attribute
//       asserts this specific site panics.
//     - EMPTY or opaque terminal callsite → named refusal. The attribute says
//       the test panics, but without a text-determined terminal we have no teeth
//       for that claim.
//
// Design note — catalog wiring gap:
//   Architecturally `#[should_panic]` is an `Item::Fn`+attribute shape and belongs
//   in `catalog::ITEM_CLAIMS` as an `ItemSugarClaim`. The blocker is that
//   `SugarBuildCtx` does not carry `reducer`, which is needed to snapshot the
//   temporal registries for the function body scope. Threading `reducer` through
//   `SugarBuildCtx` (or a parallel `ItemFnBuildCtx`) would complete the wiring.
//   Until then `visit_test_fn` in lib.rs calls this module directly — ONE clean
//   call-site, all logic here, zero hardcoded `if` branches in lib.rs.

use syn::{Attribute, Stmt};

use crate::{
    should_panic_temporal_callsite_records, temporal_panic_freedom_entry, AssertionEntry,
    AssertionFactKind, FactoryAuditLog, LiftOptions, ReductionCtx,
};

pub(crate) const OPAQUE_TERMINAL_REASON: &str =
    "should_panic terminal panic not text-determined (opaque body)";

/// True iff the attribute list contains `#[should_panic]`.
pub(crate) fn has_attr(attrs: &[Attribute]) -> bool {
    attrs
        .iter()
        .any(|attr| attr.path().is_ident("should_panic"))
}

/// Emit assertion entries for a `#[should_panic]` test function body.
///
/// Checks `attrs` first — if there is no `#[should_panic]` attribute, returns
/// immediately (nothing to emit). Call unconditionally from `visit_test_fn`;
/// the guard is here, not at the call-site.
#[allow(clippy::too_many_arguments)]
pub(crate) fn lift_entries_if_applicable(
    attrs: &[Attribute],
    stmts: &[Stmt],
    test_name: &str,
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    entries: &mut Vec<AssertionEntry>,
    skipped: &mut Vec<String>,
    factory_audits: Option<&FactoryAuditLog>,
    macro_depth: usize,
) {
    if !has_attr(attrs) {
        return;
    }
    let records = should_panic_temporal_callsite_records(stmts, test_name, reducer);
    match records.split_last() {
        None => {
            // No liftable temporal callsites (e.g. macro-only body like `format!(...)`).
            // This is a named refusal, not a manufactured panic fact.
            skipped.push(OPAQUE_TERMINAL_REASON.to_string());
        }
        Some((last, prefix)) => {
            for record in prefix {
                if let Some(entry) = temporal_panic_freedom_entry(
                    record,
                    test_name,
                    options,
                    reducer,
                    factory_audits,
                    macro_depth,
                    AssertionFactKind::Warranted,
                    false,
                ) {
                    entries.push(entry);
                }
            }
            let mut terminal_emitted = false;
            if let Some(entry) = temporal_panic_freedom_entry(
                last,
                test_name,
                options,
                reducer,
                factory_audits,
                macro_depth,
                AssertionFactKind::Warranted,
                true,
            ) {
                terminal_emitted = true;
                entries.push(entry);
            }
            if !terminal_emitted {
                skipped.push(OPAQUE_TERMINAL_REASON.to_string());
            }
        }
    }
}
