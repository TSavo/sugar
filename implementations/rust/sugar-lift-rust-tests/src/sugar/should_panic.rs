// SPDX-License-Identifier: Apache-2.0
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
//     - EMPTY (no liftable callsites, e.g. macro-only body) → synthetic opaque
//       panic fact: the `#[should_panic]` attribute IS the assertion.
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
    AssertionEntry, AssertionFactKind, FactoryAuditLog, LiftOptions, ReductionCtx,
    should_panic_temporal_callsite_records, temporal_panic_freedom_entry,
};

use sugar_ir_symbolic::{atomic_, str_const};

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
            // The `#[should_panic]` attribute IS the assertion — warrant it with an opaque
            // synthetic panic fact so the locus classifies as warranted, not dark/unresolved.
            entries.push(opaque_warrant_entry(test_name));
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
                entries.push(entry);
            }
            // If both prefix AND terminal produced None (all calls opaque-bailed), still
            // warrant the locus via the opaque fallback rather than leaving it dark.
            if entries.is_empty() {
                entries.push(opaque_warrant_entry(test_name));
            }
        }
    }
}

/// Synthetic `AssertionEntry` for `#[should_panic]` functions with no liftable temporal
/// callsites. The `#[should_panic]` attribute warrants that the function panics; emit an
/// opaque panic fact so the locus classifies as warranted rather than unresolved.
pub(crate) fn opaque_warrant_entry(test_name: &str) -> AssertionEntry {
    let subject = str_const(format!("{test_name}#should_panic_opaque"));
    AssertionEntry {
        name: Some(format!("{test_name}::should_panic_opaque")),
        atom: atomic_("panic", vec![subject]),
        fact_span: None,
        kind: AssertionFactKind::Warranted,
        claim_count: 0,
    }
}
