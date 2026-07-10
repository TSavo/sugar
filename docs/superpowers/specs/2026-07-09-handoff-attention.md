# Handoff (2026-07-09, rev 4)

Main is green; ~55 PRs merged. Live queue: what I'm driving (fleet) + **independent tasks T can grab now** (python/doc-side, zero rust-core collision).

---

## Driving: solve is API-driven, CLI is a client

Solve reads NOTHING from the project filesystem. Every input arrives as a content-addressed memento over the one API. The CLI becomes a client that feeds inputs (same as the LSP). When solve only has what a client fed it, `pool_only_inputs` has nothing to decide and is deleted.

**Plan:** `docs/superpowers/specs/2026-07-09-solve-api-driven-plan.md` — 8 disk-reads to move. **Confirmed: NONE need a new protocol verb** (all CLI-client-fed or trivial-delete).

**Cuts landed:** #4 config signers/solvers (#3983) · #6 witness resolvers (#3985) · #2 named run inputs / link-bundle+registry (#3987). All byte-identical (DoD FS=0, byte-identical=true) + corpus 55/55.

**Remaining trivial cuts (97105 driving, one PR each):** #1 input-artifact CID walk · #8 `.sugar/runs` write · #5 `Path::exists` locus/scope. Then the two flagged items, then the final `delete pool_only_inputs`.

**Flagged — I investigate before touching, only surface to T if real:**
- #3 call-edges: trivial-delete IF pool bridges + `enumerate_callsites` cover production; sidecar-only production = a lift/bridge emission gap (would come to T).
- #7 tier-2 implication cache: no new verb, but needs a solve request/response feed path (design-shaped API surface). Report the shape before building.

---

## INDEPENDENT — T can grab now (python/doc-side, no rust-core collision)

### C. Real-scale numpy/pandas re-sweep. #3944 proved 187 real API shapes / 0 gaps. Re-run on current main to confirm the coverage held through all the R-drains (now R=0). A receipt, not a change.

### D. A SECOND real-name logo. itsdangerous is proven (#3960/#3977). Pick another real library with a real bug shape and prove it end-to-end the same way — a new "logos are the product" artifact, CI-ratcheted, with a SCOPE.md. High value, PyCon material.

### E. More loud coordinate bad-twins (the #3982/#3986 pattern) for surfaces #3986 didn't cover: multi-arg vendor methods (`df.merge(other)`, `df.pivot_table(...)`) — lying-arg discrimination pinned loud.

**DONE (off the list):**
- #3958 free-name bad-twin → #3982 (T). Dig already correct; pinned loud.
- B coordinate discrimination bad-twins (kwarg/chain/method/attr) → #3986 (T). Verify-before-ship applied.
- A numpy totality-at-zero ratchet → 97102 building it now (R=0 reached). If T wants it instead, tell me so I stop 97102.

---

## Serialized behind one-solve (I drive, after 97105 finishes the cuts)
- Implication steps 2+: un-stub `CallSite::implication()` + feed-fold producing implications from real link-time Obligations into the pool. Overlaps one-solve on `consistency.rs`/`orchestrate.rs`/`runner.rs`.
- Enumerate→LSP as one composition: descent-through-enumerate feeding the LSP acceptance path end-to-end. Overlaps one-solve on the `sugar-lsp` files.

---

## Landed this session (context, not to-do)
- Real-pandas red squiggle proven + gated (#3934/#3936/#3940): FS=0, byte-identical, ~3.4 ms. (A mock-sourced version was wrongly called "the demo" — caught, replaced.)
- Enumeration typed descent complete; over-encoded `SourceMemento[path]` reverted (#3950, -1042 lines).
- Witness-as-verb complete (#3959/#3962/#3964): `WitnessPool<CID,WitnessMemento>` — oracle resolves, Rust verifies, no env, no invalidation.
- Implication step 1 (#3972). numpy wall 182→0. Logo CI-ratcheted (#3960) + scoped (#3977). #3958 pinned (#3982). Coordinate bad-twins pinned (#3986). Solve-API cuts #4/#6/#2 (#3983/#3985/#3987).

---

## Process
- `watch_worker` unreliable — poll for idle. Dispatch to a busy worker fails silently. Swap workers fresh at ~180k context; long reports scroll off past ~200k — write to a file and read it.
- Merge-on-sight on green/known-baseline; read the mechanism on grounding/soundness PRs.
- Receipt discipline: paste the actual `55 passed` count. Verify-before-ship: combined corpus on branch BEFORE merge, not ship-then-corpus (kevlar applied this in #3986).
- ONE PR per doc change.
- Doctrine: idempotency + no-double-entry + warm-FS=0 + no-invalidation are ONE thing — a CID-keyed pool. "The existing thing already IS the pool," never "add a second path."
