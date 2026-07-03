# Multi-Solver Protocol

**Status:** v1.2.0 normative
**Date:** 2026-04-30
**Catalog property:** `multi-solver-protocol` (CID in `protocol/specs/2026-04-30-protocol-catalog.json`)
**Owner:** verifier crate
**Related:**
- `protocol/specs/2026-04-30-ir-compiler-protocol.md` (IR compiler dispatch)
- `protocol/specs/2026-04-30-memento-envelope-grammar.md` (implication memento shape)
- `protocol/specs/2026-04-30-handshake-algorithm.md` (Tier 1 / 2 / 3 discharge tiers)

## 1. Motivation

The verifier's Stage 6 historically invoked Z3 as a single subprocess
per call site. Real-world fragments span theories no single solver
optimally covers (strings, bitvectors, linear arithmetic, quantified
integers, ...), and a single solver's failure mode is opaque. The
multi-solver upgrade generalizes Stage 6 to compose any number of
solvers under one of four execution modes.

This spec defines:
1. The `[solvers]` configuration grammar in `.sugar/config.toml`.
2. The four execution modes (single, chain, portfolio, dispatch) with
   exact semantics for each verdict.
3. Disagreement handling under consensus mode.
4. The per-solver implication-memento provenance rule (each unsat
   witness is its own memento).
5. The trust-model knob `min_solver_witnesses`.

## 2. Configuration grammar

```toml
[solvers]
# Exactly one of {default, chain, portfolio, dispatch} should be set.
# Precedence (first match wins): default -> chain -> portfolio ->
# dispatch. If none are set, the verifier falls back to single-Z3.
default = "z3"                                       # OR
chain = ["z3", "cvc5"]                               # OR
portfolio = ["z3", "cvc5", "bitwuzla"]               # OR
mode = "first-wins"  or  "consensus"                 # required when portfolio set

# Spec-only in v0; future versions enforce.
min_solver_witnesses = 2

[solvers.z3]
binary = "z3"                  # path or shorthand "stub:<verdict>"
ir_compiler = "smt-lib-v2.6"   # tag matching the per-solver IR compiler
timeout_seconds = 5
flags = ["-T:5"]
version = "4.13.0"             # surfaced in mementos and the report

[solvers.cvc5]
binary = "cvc5"
ir_compiler = "smt-lib-v2.6"
flags = ["--produce-models"]
version = "1.2.0"

[solvers.bitwuzla]
binary = "bitwuzla"
ir_compiler = "smt-lib-v2.6-bv"
version = "0.7.0"

[solvers.dispatch]
"strings" = "cvc5"
"bitvectors" = "bitwuzla"
"linear-arithmetic" = "z3"
"default" = "z3"
```

### 2.1 Stub solvers

For tests, CI, and the multi-solver demo, the verifier supports a
`binary = "stub:<verdict>"` shorthand. Recognized verdicts:

| Shorthand          | Verdict produced              |
|--------------------|-------------------------------|
| `stub:unsat`       | `Discharged`                  |
| `stub:sat`         | `Unsatisfied`                 |
| `stub:undecidable` | `Undecidable`                 |
| `stub:timeout`     | `Undecidable`, `timed_out=true` |
| `stub:disagreement`| `Disagreement`                |

Stub solvers produce the verdict immediately (or after `with_delay` if
constructed in code) and stamp a deterministic version string of the
form `stub-<verdict>`.

## 3. Execution modes

All modes return a triple: `(ObligationVerdict, String reason,
Vec<SolverInvocation>)`. The runner aggregates the third element into
per-solver telemetry that flows into the report.

### 3.1 Single

Invoke the named solver once. The solver's verdict is the call site's
verdict.

### 3.2 Chain

Iterate the configured solver list. For each solver:
- If it returns `Discharged` or `Unsatisfied` (definitive), STOP and
  return that verdict.
- If it returns `Undecidable` (timeout, parse error, "unknown"), record
  the invocation and proceed to the next solver.

If every solver returns Undecidable, the call site verdict is
Undecidable and the reason includes the last solver's diagnostic.

Telemetry: every attempted solver appears in `Vec<SolverInvocation>`,
with `authoritative = true` only on the one whose verdict is being
returned.

### 3.3 Portfolio (first-wins)

Spawn all solvers in parallel via rayon. Collect their results. Sort
by wall-clock time, then by solver name (deterministic tiebreak). The
first definitive verdict in that ordering wins.

If every solver is Undecidable, the call site is Undecidable.

> **Cancellation note.** v0 does not implement subprocess cancellation;
> remaining solvers continue until natural completion or timeout.
> "First-wins" is therefore "first to *return* a definitive verdict,"
> not "first to *start*." The plan-execution semantics is preserved by
> the post-collection sort; what we lose is wall-clock parallel speedup
> on long-tail solvers. v1 will add `oneshot::Sender` cancellation.

### 3.4 Portfolio (consensus)

Spawn all solvers in parallel. Filter to the subset that returned a
definitive verdict.

- If the definitive subset is empty: return Undecidable.
- If all definitive verdicts are equal: return that verdict.
- If they disagree (some `Discharged`, some `Unsatisfied`): this is a
  **SOLVER DISAGREEMENT**. The verifier:
  - Logs a `warning: portfolio[consensus]: SOLVER DISAGREEMENT: <by-solver list>`
    line to stderr (loud by design; this is a soundness signal).
  - Returns the special verdict `ObligationVerdict::Disagreement`.
  - Increments `TierStats.disagreements`.
  - Does NOT mint an implication memento (no consensus = no signed
    witness).

In v0, disagreements are flagged in the report and counted; they do
NOT become a new memento role. The follow-up spec
`disagreement-memento-protocol.md` will define a "verdict-disagreement"
memento that signs the conflict for downstream auditors.

### 3.5 Per-fragment dispatch

Inspect the formula's atomic predicates and sort domains; pick the
matching solver from the dispatch table:

| Theory fragment      | Heuristic                                                  |
|----------------------|------------------------------------------------------------|
| `strings`            | any atom in `{length, matches, contains, prefix-of, suffix-of, str.++, str.len, str.indexof}` OR any sort named `String`. |
| `bitvectors`         | any atom in `{bvadd, bvsub, bvmul, bvand, bvor, bvxor, bvnot, bvshl, bvlshr, bvashr, bvult, bvule, bvugt, bvuge, bvslt, bvsle, bvsgt, bvsge}` OR any sort whose name starts with `BitVec`/`bv`/`BV`. |
| `linear-arithmetic`  | any atom in `{>, <, >=, <=, =, +, -, *}` over Int/Real, when neither strings nor bitvectors apply. |
| `default`            | everything else.                                            |

Precedence: strings > bitvectors > linear-arithmetic > default. The
walker is conservative: anything it cannot classify falls to `default`.
If the matching theory tag has no entry AND `default` has no entry,
the call site is Undecidable with a "no matching solver and no default"
reason.

## 4. Per-solver IR-compiler dispatch

Each solver carries an `ir_compiler` tag (default: `smt-lib-v2.6`).
The verifier consults this tag when emitting the SMT-LIB script for
that solver. v0 only ships the `smt-lib-v2.6` compiler (in the
`sugar-ir-compiler-smt-lib` crate that the IR-compiler agent
landed); the field is plumbed through to the SolverConfig record so
future compilers (`smt-lib-v2.6-bv` for Bitwuzla, `tptp` for Vampire,
etc.) drop in by name with no other code changes.

## 5. Per-solver implication-memento provenance

When a portfolio mode produces multiple definitive verdicts, the
verifier mints **one implication memento per discharging solver**.
Memento body fields:

| Field             | Value                                            |
|-------------------|--------------------------------------------------|
| `antecedentHash`  | producer-side post hash (BLAKE3-512)             |
| `consequentHash`  | consumer-side pre hash (BLAKE3-512)              |
| `prover`          | `<solver-name>@<solver-version>`                 |
| `proverRunMs`     | wall-clock time for that solver's invocation     |
| `producerPubkey`  | ed25519 pubkey of the verifier that minted it    |

All other fields per `memento-envelope-grammar.md`.

The cache filename embeds the prover tag so multiple per-solver
mementos for the same `(antecedentHash, consequentHash)` pair coexist
on disk: `<propertyHash>-<safe-prover>.proof`.

The lattice holds them all. The verifier never deduplicates witnesses
by property hash; each signature is its own piece of evidence.

## 6. Trust model: `min_solver_witnesses`

A verifier configured with `min_solver_witnesses = N` requires N
distinct solvers to have signed an implication memento for a given
`(antecedentHash, consequentHash)` pair before accepting a Tier 2
cache hit.

> **v0 status.** The field is parsed from `.sugar/config.toml` and
> stored in the SolversConfig but the runner does not enforce the
> gate. Tier-2 cache hits in v0 require exactly one signed implication
> memento. v0.1 will count distinct solvers per
> `(antecedentHash, consequentHash)` group at Tier-2 lookup and
> reject below-threshold hits.

## 7. Report breakdown

`TierStats` carries:

```rust
pub struct TierStats {
    pub discharged_by_hash: usize,
    pub discharged_by_cache: usize,
    pub vacuous_discharge: usize,
    pub solved_and_minted: usize,
    pub residue: usize,
    pub violations: usize,
    pub disagreements: usize,
    pub solver_invocations: usize,
    pub per_solver: BTreeMap<String, SolverStats>,
}

pub struct SolverStats {
    pub discharged: usize,
    pub unsatisfied: usize,
    pub undecidable: usize,
    pub timeouts: usize,
    pub wall_clock: Duration,
    pub version: String,
}
```

The legacy `z3_invocations` field is retained as a method that returns
`solver_invocations` so existing demo drivers keep compiling.

## 8. Acceptance

This spec is satisfied by the implementation in
`implementations/rust/sugar-verifier/src/solvers/` and the demo at
`examples/multi-solver-demo/`.

- `cargo build --release -p sugar-verifier` succeeds.
- `cargo test --release -p sugar-verifier` passes (existing tests
  green plus integration coverage in
  `tests/multi_solver_modes.rs` and unit coverage in
  `src/solvers/{config,dispatch,plan,registry}.rs`).
- The multi-solver demo runs end-to-end with stub solvers in CI.
- The Stage 4 handshake demo (real Z3 path) keeps round-tripping
  green via the explicit `RunnerConfig::legacy_z3_fallback`
  compatibility hatch.

## 9. Open follow-ups

- **Disagreement memento role.** Promote the consensus-disagreement
  signal from a TierStats counter to a signed memento envelope so
  auditors downstream can verify that two solvers disagreed. New
  schema CID, new memento `kind = "verdict-disagreement"`.
- **Subprocess cancellation.** Add a `oneshot::Sender` cancellation
  channel so portfolio first-wins terminates remaining subprocesses
  the moment a definitive verdict lands.
- **Witness-count enforcement.** Implement `min_solver_witnesses`
  during Tier-2 cache lookup.
- **Compiler-by-tag selection.** Once the IR-compiler agent ships the
  `IrCompilerRegistry`, route per-solver SMT emission through the
  `ir_compiler` tag instead of always using the bundled
  `sugar-ir-compiler-smt-lib`.
