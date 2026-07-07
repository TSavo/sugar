// Slice B semantic fixture — the TRUTHFUL state (z3-decided GREEN).
//
// The linker's obligation for the `callee(x)` bridge is
// `post_caller \u{2283} pre_callee` over the shared contract quantity `result`:
// here `result >= 5  \u{2283}  result >= 1`. Those predicates are NOT
// structurally equal and NOT vacuous, so the pure `link()` path can only report
// `implication-undecidable`. With the solver registry wired the daemon asks z3:
// is the implication valid? It is — z3 DISCHARGES it and the line is GREEN (no
// diagnostic). This is the semantic current: adjudication by z3, not structure.
//
// The RED twin (red_semantic.rs) is this file with ONE line changed — the
// caller's `#[ensures]` weakened to `result >= 0`, which does NOT imply
// `result >= 1` (counterexample result = 0): z3 refutes it and the line goes
// red with the unsat reason.
#[requires(result >= 1)]
fn callee(x: i64) -> i64 { x }

#[ensures(result >= 5)]
fn caller(x: i64) -> i64 { callee(x) }
