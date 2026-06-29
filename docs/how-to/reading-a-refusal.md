<!--
  Reading a refusal — how to interpret what Sugar tells you when it doesn't print a clean green.
  Grounded in implementations/rust/sugar-cli/src/report_fmt.rs (status / reason / dischargeMethod
  / bodyDischargeTier; discharged / refused / refuted; the red condition) and the source-audit
  ledger (warranted / support / unresolved / refused / refuted) from examples/rust-coretests-report.
-->
# Reading a refusal

Sugar never fails silently. Every claim is discharged or accounted **by name**, and a "no" is a
*result*, not a crash. This page is how to read the result and what to do about it.

The golden rule first: **a refusal is a sound answer.** Silence is the bug Sugar exists to
prevent; a loud refusal is the product working. So the question is never "why did it break" —
it is "what did it tell me, and is that the truth?"

## Two surfaces

- **`sugar prove` / `sugar verify`** report *per claim*: was this obligation discharged, and how.
- **`sugar lift --report`** reports *per source locus*: an honest coverage ledger of everything
  the lifter saw.

Both also emit machine JSON (`.prove.json` and friends) with the same fields. When in doubt,
read the `reason`.

## Per-claim status (`sugar prove`)

Each row carries a `status`, a `reason`, a `dischargeMethod`, and sometimes a `bodyDischargeTier`:

- **`discharged`** — proven. Green. The `dischargeMethod` tells you *how*:
  - `reflexive` — trivial identity.
  - `consistency` — z3 found the conjoined invariants satisfiable (the callsite conjoin; see
    [bridges-and-composition](../contributing/bridges-and-composition.md)).
  - `hash-tier` — discharged by CID equality against a prior commitment; nothing re-proven.
  - `body-eq` (e.g. `body-eq-same-callee`) — discharged by body-level equality.
- **`refused`** — a sound "no": the lift hit a real effect, or could not reach a literal floor.
  Loudly-bounded-lossy, never silent. Not a bug — a boundary.
- **`refuted`** — a proven **contradiction**. z3 found the conjoined invariants UNSAT: your claim
  cannot coexist with an established one (often a vendor's contract conjoined at the same
  callsite). Red, and correct.

A run is **red** when `violations > 0`, there are load errors, a toolchain plan is `refuted`, or
there are no rows at all (`report_fmt.rs`). Toolchain plans show `declared` or `refuted` with
their own `reason`.

## Per-locus ledger (`sugar lift --report`)

```
source audit: loci=N warranted=… support=… refused=… refuted=… unresolved=…
```

- **`warranted`** — the locus lifted to a checkable FOL fact. This is real coverage.
- **`unresolved`** — *no Sugar for this shape yet.* The honest dark. Progress is driving
  `unresolved → 0` by writing lifters, not by hiding it.
- **`refused` / `refuted`** — loudly-bounded-lossy: a named effect, or a contradiction twin. A
  sound "no," not a dropped row.
- **`support`** — **inert source only**: comments, doc-comments, pragmas, directives — things
  that carry no assertion. A `FunctionDef`, `Import`, or `ClassDef` is *not* inert and must never
  land here; counting it as `support` credits a hidden hole as covered (a fake denominator). Such
  loci belong in `unresolved`.

## What to do about each

- **`refuted` (a contradiction).** The system is working. Read the `reason` and the conjoined
  contracts: your claim disagrees with an invariant that was established about the same callsite.
  Fix the claim, or fix the assumption — you don't get to out-vote a vendor about their own call.
- **`refused` (an effect or an unreachable floor).** Find the boundary. A real side effect (IO,
  mutation, nondeterminism) is an honest edge, not a failure. If the shape is *pure* and you
  expected it to lift, that points at a missing recognizer, not an effect.
- **`unresolved` (no Sugar yet).** There is no lifter for this shape. The fix is to write one —
  the [lifting rules](../contributing/lifting-rules.md) and the
  [factory/sugar/floor](../contributing/factory-sugar-floor.md) guideline are how. This is work
  made visible, which is the point.
- **`support` swallowing real loci.** If a function or import is counted as `support`, that is the
  fake-denominator bug; it belongs in `unresolved` where the gap is honest.
- **Load errors, `broken-oracle`, witness drift.** A witness that doesn't recompute is a different
  failure entirely — see [the witness oracle](../explanation/witness-oracle.md). `broken-oracle`
  means the resolver lied; *drift* means the behavior genuinely moved.

## Debugging a stubborn refusal

1. Read the `reason` field first (in the terminal, or grep it out of `.prove.json`). It names the
   locus, the obstacle, and usually the fix.
2. Decide which kind of "no" it is: a **contradiction** (`refuted` — a real disagreement), a
   **boundary** (`refused` — a real effect), or a **gap** (`unresolved` — no lifter). They have
   three different fixes; don't treat one as another.
3. If it's a contradiction, look at what got conjoined at the callsite — the inheritance and
   composition rules in [bridges-and-composition](../contributing/bridges-and-composition.md)
   explain which invariants met and why they clashed.
4. If it's a gap, the refusal is a to-do, not a defect. Write the Sugar.

---

Authoritative source: `implementations/rust/sugar-cli/src/report_fmt.rs` (the statuses, methods,
and the red condition) and `examples/rust-coretests-report/` (the source-audit ledger). See also:
[the witness oracle](../explanation/witness-oracle.md) · [bridges-and-composition](../contributing/bridges-and-composition.md) ·
[lifting rules](../contributing/lifting-rules.md).
