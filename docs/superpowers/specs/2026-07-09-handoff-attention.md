# Handoff (2026-07-09, rev 6)

Main is green (by per-PR battleaxe corpus receipts). Live queue below.

---

## Driving: solve is API-driven, CLI is a client

Solve reads NOTHING from the project filesystem. Inputs arrive as content-addressed mementos over the one API; CLI and LSP are clients that feed. End goal: `delete pool_only_inputs`. Plan: `docs/superpowers/specs/2026-07-09-solve-api-driven-plan.md`. **None of the 8 disk-reads need a new protocol verb.**

**Cuts landed:** #4 config (#3983) · #6 witness resolvers (#3985) · #2 named inputs (#3987) · #8 runs-seal (#3990) · #5 locus/scope (#3992). All byte-identical (DoD FS=0) + corpus 55/55.

**In flight (97109):** rebase #1 (#3989, conflicted on runner.rs); investigate #3 (sidecar call-edges) + #7 (tier-2 feed shape) and report; then the final `delete pool_only_inputs`.

**Flags (I surface only if real):** #3 = lift/bridge gap only if sidecar-only production exists; #7 = design-shaped feed path, report shape before building.

---

## Independent queue — ALL DONE (T)
- A numpy totality-at-zero ratchet → 97107 finishing (R=0 reached).
- B coordinate discrimination bad-twins → #3986.
- C real-scale re-sweep (187/187) → #3993.
- D second real-name logo (stdlib base64) → #3993. (#3994 is a divergent DUPLICATE — close it.)
- E multi-arg bad-twins (df.merge/pivot_table) → #3991.
- #3958 free-name bad-twin → #3982.

---

## Serialized behind one-solve (I drive, after 97109 finishes)
- Implication steps 2+: un-stub `CallSite::implication()` + feed-fold from real link-time Obligations into the pool. Overlaps one-solve on `consistency.rs`/`orchestrate.rs`/`runner.rs`.
- Enumerate→LSP as one composition. Overlaps one-solve on `sugar-lsp` files.

---

## Landed this session (context)
Real-pandas squiggle gated 3.4 ms (#3934/#3940). Enumeration descent complete; `SourceMemento[path]` over-encoding reverted (#3950). Witness-as-verb complete (#3959/#3962/#3964). Implication step 1 (#3972). numpy 182→0. Two real-name logos (itsdangerous #3960/#3977, stdlib base64 #3993). Solve-API cuts #4/#6/#2/#8/#5.

---

## Process
- `watch_worker` unreliable — poll. Busy-worker dispatch fails silently. Swap fresh at ~180k context; force-swap if looping. Long reports → write to a file.
- Solve cuts all touch `runner.rs` — strictly sequential, rebase each on prior merged cut.
- Paste the actual `55 passed` count in every PR; verify-before-ship.
- ONE PR per doc change.
- CI CAVEAT: fast admin-merges cancel each commit's CI before it completes — main is green by per-PR corpus receipts, NOT by a completed CI run. Let CI finish on a HEAD periodically for a real end-to-end green.
- Doctrine: idempotency + no-double-entry + warm-FS=0 + no-invalidation = ONE thing (CID-keyed pool). "The existing thing already IS the pool."
