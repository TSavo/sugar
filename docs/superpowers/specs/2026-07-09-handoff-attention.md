# Handoff (2026-07-09, rev 3)

Main is green; ~50 PRs merged this session. This handoff is the live queue: what I'm driving (fleet), and **independent tasks T can pick up right now** without colliding.

---

## THE TARGET I'm driving: solve is API-driven, CLI is a client

Settled with T. Solve reads **nothing** from the project filesystem. Every input arrives as a content-addressed memento over the one API, like every other fact. The **CLI becomes a separate client** of that API — it does the disk-reading as a client and *feeds* it in, exactly the way the LSP is a client. Neither CLI nor LSP has a privileged path inside solve; both are faces talking to the one API. When solve only ever has what a client fed it, `pool_only_inputs` has nothing to decide and is deleted.

**Progress:** #3981 deleted the separate `warm_solve` *function* (one door), but left `pool_only_inputs` as a "derived" flag with 8 disk-reads still inside cold solve. That's the partial step; the real target is above.

**In flight (97105):** per-input plan (`docs/superpowers/specs/2026-07-09-solve-api-driven-plan.md`) for moving each of the 8 out to the CLI client or an existing API verb, flagging any that genuinely need a NEW protocol verb (those are T's calls). First cut is PR A (config signers/solvers → CLI client). One input-source per PR, byte-identical verdict rows, corpus 55/55.

The 8 disk-reads to move: input artifact CID walk, link-bundle/plugin-registry discovery, `*.call-edges.json`, `config.toml` signers/solvers, `Path::exists` locus preference, witness `read_dir`, tier-2 cache, `.sugar/runs` write.

**Coordinator note to self:** a second path that shouldn't exist gets fixed silently — not surfaced as a decision, not spent on T's attention. I failed that (burned a long exchange treating dead code as a mystery). Fix vestiges, don't narrate them.

---

## INDEPENDENT — T can grab these now (python/doc-side, zero rust-core collision)

### A. numpy totality-at-zero ratchet. Wall is at R≈0 (97102 finishing the last drains). After R=0, a gate asserting numpy+pandas construction-gap R == 0 on battleaxe so it can't silently climb — drains have unmasked deeper gaps mid-lane, so honest-0 needs a guard. **Coordinate with 97102 (it may land this) — if T takes it, tell me so I stop 97102 from duplicating.**

### B. Loud discrimination bad-twins — **CLOSED** (#3982 pattern). Instruments: lying kwarg (`.sum(axis=0)` dual unsat), lying chain (`.dropna().mean()` dual unsat), method vs attribute (`.sum()` / `.empty` dual unsat) + bare-sum vs `kw:axis` distinct euf keys. See `tests/test_coordinate_loud_discrimination.py`. Combined probe on branch: 41 related passed before merge.


### C. Real-scale numpy/pandas re-sweep. #3944 proved 187 real API shapes, 0 gaps — re-run it on current main to confirm the coverage held through all the R-drains. Pure python, a receipt not a change.

**DONE (off the list): #3958 free-name bad-twin → #3982** (T). Dig already rebinds correctly for local shadow / formal shadow; pinned as a loud instrument. No production change needed.

---

## Serialized behind one-solve (I drive, after 97105 lands)
- **Implication steps 2+**: un-stub `CallSite::implication()` + the feed-fold producing implications from real link-time Obligations into the pool. Overlaps one-solve on `consistency.rs`/`orchestrate.rs`/`runner.rs`.
- **Enumerate→LSP as one composition**: descent-through-enumerate feeding the LSP acceptance path end-to-end. Overlaps one-solve on the `sugar-lsp` files.
Both rebase on post-one-solve main; then can run parallel to each other (tree/linker vs lsp).

---

## Landed this session (context, not to-do)
- Real-pandas red squiggle proven + gated (#3934/#3936/#3940): FS=0, byte-identical, ~3.4 ms. (An earlier mock-sourced version was wrongly called "the demo" — caught, replaced.)
- Enumeration typed descent complete; over-encoded `SourceMemento[path]` built then reverted (#3950, −1042 lines).
- Witness-as-verb complete (#3959/#3962/#3964): `WitnessPool<CID,WitnessMemento>` made real — oracle resolves, Rust verifies, no env, no cache-invalidation.
- Implication step 1 (#3972). numpy wall 182→≈0. Logo CI-ratcheted (#3960) + padding-boundary scoped (#3977). #3958 pinned (#3982).

---

## Process
- `watch_worker` unreliable — poll for idle. Dispatch to a *busy* worker fails silently (brief stays unsent). Swap workers fresh at ~180k context; long reports scroll off past ~200k — write to a file and read it.
- Merge-on-sight on green/known-baseline; read the mechanism on grounding/soundness PRs.
- Receipt discipline: paste the actual `55 passed` count, not just the command. Corpus BETWEEN grounding-path merges (#3924 lesson).
- ONE PR per doc change (I made a three-PR mess of an earlier handoff — don't).
- The unifying doctrine: idempotency + no-double-entry + warm-FS=0 + no-invalidation are ONE thing — a CID-keyed pool. "The existing thing already IS the pool," never "build the abstraction" or "add a second path."
