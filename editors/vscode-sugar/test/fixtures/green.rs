// Slice A demo fixture — the TRUTHFUL state.
//
// Identical to red.rs but with the `#[requires(x > 0)]` line removed from
// `checked_index`. With no precondition there is no obligation to discharge:
// `sugar-lsp --in-process` discharges the bridge vacuously and emits zero
// diagnostics. The editor squiggle clears.
#[ensures(result >= 0)]
fn checked_index(x: i64) -> i64 { x }

#[ensures(result >= 0)]
fn test_index() -> i64 { checked_index(7) }
