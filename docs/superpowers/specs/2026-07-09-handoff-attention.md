# Handoff (2026-07-09, rev 2)

Main is green; ~45 PRs merged this session (#3931–#3977). This handoff is **the work not currently in flight** — the things that will get lost if they aren't written down, since the two live workers are on the one-solve deletion and the numpy wall.

---

## THE THING TO GET RIGHT (read first): one solve, no disk-read path

There is a leftover **disk-reading path** in solve — `sugar_compiler::orchestrate::warm_solve` (a separate function forcing `pool_only_inputs = true`), plus cold branches in `consistency.rs` (`locus_in_scope`'s `candidate.exists()`, `WitnessDischargeContext`'s `read_dir(.sugar/lift)`).

**It should not exist, and the enumeration protocol is exactly why.** Once every fact enters solve as a content-addressed memento over the one RPC (enumerate returns self-locating `SourceMemento`s by CID; the pool is a CID→memento map), solve never reads the project filesystem to find facts — the protocol delivers them. So `Path::exists` / `read_dir` on the discharge path are **vestiges from before the enumeration protocol**. `warm_solve` and `pool_only_inputs` only ever existed to *skip* those reads; the protocol already made the reads unnecessary. This is not "two paths to reconcile" — it is one path (the protocol/pool) plus dead code to delete.

The collapse: delete the disk-read branches; delete `warm_solve` as a separate function; scope/membership becomes "is the memento in the pool," never a disk stat; FS reads = 0 **always**, not "when warm"; one solve over the pool; byte-identical verdict rows; corpus 55/55. **If any cold branch is genuinely load-bearing** — something enters via disk that the protocol does NOT deliver as a memento — that is a real gap in the enumeration protocol and must be surfaced; otherwise it is dead, delete it.

(Worker 97105 is on this now. It's in the handoff because it's the load-bearing correction, not because it's un-owned.)

**Coordinator note to self:** this class of thing — a second path that shouldn't exist — gets fixed silently. It is not a decision, not a question for T. I failed that here: burned a long exchange treating dead code as a mystery and manufacturing a "decision" out of it. Fix vestiges, don't narrate them, don't spend T's attention on implementation cleanup.

---

## NOT IN FLIGHT — pick these up

### 1. Implication, steps 2+ (paused). Step 1 landed (#3972: seal the linker's `post ⊃ pre` Obligation as the existing implication memento — one CID, pure function, byte-identical, no parallel type). Remaining: un-stub `CallSite::implication()` (tree still returns `None`) and the feed-fold that produces implications from real link-time Obligations into the pool, so implications are produced end-to-end, not just speakable in tests. Execution, not a decision. Same discipline: CID-idempotent, byte-identical, corpus 55/55. Resume once 97105 is clear of the shared files.

### 2. #3958 free-name bad-twin. Module-constant binding (#3958) rides on free-name resolution. A *shadowed* (local re-binds the name) or *conditionally-defined* module constant could be mis-bound or missed. Needs one bad-twin: a module constant shadowed by a local, confirm the dig binds the right one. Small, real.

### 3. numpy totality-at-zero ratchet. The wall is at R≈0 (worker 97102 finishing). After R=0, add a **gate that asserts numpy+pandas construction-gap R == 0 on battleaxe** so it can't silently climb — drains have unmasked deeper gaps mid-lane, so honest-0 needs a guard, not just a one-time measurement.

### 4. Enumeration → LSP as one composition (nice-to-have). The enumerate wire returns self-locating mementos (proven e2e #3951), and the real-kit LSP acceptance passes (#3934) — but the descent-through-enumerate *feeding* the LSP acceptance path as one composition isn't wired end-to-end. Completes the "one protocol drives the squiggle" story.

---

## Landed this session (done, gated) — context, not to-do

- Real-pandas red squiggle proven + gated (#3934/#3936/#3940): FS=0, byte-identical, ~3.4 ms, golden NDJSON byte-identical (#3938). (An earlier *mock*-sourced version was wrongly called "the demo" — caught, replaced.)
- Enumeration typed descent complete; an over-encoded `SourceMemento[path]` layer built then reverted (#3950, −1042 lines — a memento is already self-locating).
- Witness-as-verb complete (#3959/#3962/#3964): `WitnessPool<CID,WitnessMemento>` made real — oracle resolves, Rust verifies, no env, no cache-invalidation.
- Implication step 1 (#3972). numpy wall 182→≈0 (#3948–#3976). Logo real-name proof CI-ratcheted (#3960) + padding-boundary scoped (#3977, `SCOPE.md`).

---

## Process
- `watch_worker` unreliable (false "finished") — poll to detect idle. Dispatch to a *busy* worker fails silently (brief stays unsent). Swap workers fresh at ~180k context; long reports scroll off past ~200k — have them write to a file and read it.
- Merge-on-sight on green/known-baseline; **read the mechanism** on grounding/soundness PRs.
- Receipt discipline: paste the actual `55 passed` count, not just the command. Run the battleaxe corpus BETWEEN grounding-path merges (the #3924 lesson) — focused receipts miss structural over-constraint.
- kevlar.sindome@ = T's parallel stream; his PRs are his (merge + telemetry, read, don't gate).
- The unifying doctrine: idempotency + no-double-entry + warm-FS=0 + no-cache-invalidation are ONE thing — a CID-keyed pool. Reach for "the existing thing already IS the pool," never "build the abstraction" or "add a second path." The disk-read vestige being deleted is the counter-example.
