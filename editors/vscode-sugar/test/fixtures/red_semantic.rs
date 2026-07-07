// Slice B semantic fixture — the LYING state (z3-refuted RED).
//
// Identical to green_semantic.rs but the caller's postcondition is weakened
// from `result >= 5` to `result >= 0`. The linker's obligation
// `post_caller \u{2283} pre_callee` is now `result >= 0  \u{2283}  result >= 1`,
// which is NOT valid: z3 finds the counterexample result = 0. The daemon
// returns `implication-unprovable` and the `callee(x)` call site goes RED — the
// lie caught by the solver, live, before the file is saved.
//
// Under the structural (no-solver) degraded mode this same pair reports
// `implication-undecidable` for BOTH states, which is precisely why the
// semantic flip requires z3 and is the thing slice B adds.
#[requires(result >= 1)]
fn callee(x: i64) -> i64 { x }

#[ensures(result >= 0)]
fn caller(x: i64) -> i64 { callee(x) }
