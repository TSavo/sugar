// Slice A demo fixture — the LYING state.
//
// `checked_index` is a contracted helper whose precondition `x > 0` is the
// rule it needs its caller to establish. `test_index` calls it but its own
// postcondition does not structurally establish that rule, so
// `sugar-lsp --in-process` cannot discharge `post_caller ⊃ pre_callee` and
// refuses the obligation: a RED `implication-undecidable` diagnostic anchored
// at the `checked_index(7)` call site.
//
// The GREEN twin (green.rs) is this file with the `#[requires(x > 0)]` line
// removed: with no precondition there is no obligation, the bridge discharges
// vacuously, and the squiggle clears.
#[requires(x > 0)]
#[ensures(result >= 0)]
fn checked_index(x: i64) -> i64 { x }

#[ensures(result >= 0)]
fn test_index() -> i64 { checked_index(7) }
