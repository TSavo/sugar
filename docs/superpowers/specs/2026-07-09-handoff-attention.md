# Handoff (2026-07-09, rev 9)

Main is green (by per-PR battleaxe corpus receipts). Live queue below.

---

## Driving: solve is API-driven, CLI is a client

Solve reads NOTHING from the project filesystem. Inputs arrive as content-addressed mementos over the one API; CLI and LSP are clients that feed. End goal: `delete pool_only_inputs`. Plan: `docs/superpowers/specs/2026-07-09-solve-api-driven-plan.md`. **None of the 8 disk-reads need a new protocol verb.**

**Cuts landed:** #4 config (#3983) · #6 witness resolvers (#3985) · #2 named inputs (#3987) · #8 runs-seal (#3990) · #5 locus/scope (#3992) · #7 tier-2 disk vestige delete (#4005, −522 lines). All byte-identical (DoD FS=0) + corpus 55/55.

**In flight (97109):** the capstone — `delete pool_only_inputs`. After it, solve is ONE path, zero project FS, by construction. That closes the series.

---

## INDEPENDENT — NEXT (T; python/doc-side, zero rust-core collision)

**Ongoing (infinite runway):**
- **F. More real-name logos.** 11+ proven. Added length/bounds class: sha256 digest length, uuid.bytes length, md5 digest_size, struct.calcsize (also advances L). Keep going.
- **G. More vendors (coordinate coverage).** numpy/pandas/statistics/decimal done (R=0); `fractions` in flight (97118, #4008). Next: `csv`, `datetime`, `pathlib`.
- **H. PyCon demo narrative / README arc** (your voice) — the inline-editor moment + the wall of real-name proofs.

**NEW lanes (higher-leverage than more-of-the-same):**
- **L. A DIFFERENT bug-shape class.** Every logo so far is the padding/strip class (`¬suffix-of("=")`). Prove a genuinely different correctness property so the wall isn't one trick: a **stated-vector equality** (e.g. HMAC-SHA256 digest == expected hex), a **length/bounds invariant**, or an **ordering** property. This is the highest-value next logo — it shows breadth, not repetition.
- **J. Cross-library COMPOSITION proof** (the "water through the pipe" story). A real chain where library A's output feeds library B and correctness threads end-to-end (e.g. `base64.urlsafe_b64encode(...)` then `itsdangerous` sign, good vs tampered). The Aug composition-story milestone; python-side.
- **I. Logo gallery / index doc.** One page listing every proven logo: library · bug shape · receipt · SCOPE. The wall made legible — PyCon showcase + product front page.

---

## INDEPENDENT — DONE (T)
- A numpy R==0 ratchet (#3997) · B coordinate bad-twins (#3986) · C re-sweep 187/187 (#3993) · D 2nd logo (#3993) · E multi-arg bad-twins (#3991) · #3958 free-name (#3982) · F logos 3-7 (#3998/#3999) · G statistics (#4001) · G decimal (#4003) · L length/bounds logos (#4004).

---

## Serialized behind one-solve (I drive, after 97109 finishes)
- **AUTO MODE (#4007) — the LSP-only capability the CLI structurally can't have.** A `.proof` is derived, not shipped: its CID is a pure function of the source bytes. A `pip install`ed lib with no `.proof` is a **cache miss, not a black hole** — source + frontend membrane = ProofIR = `.proof`, recomputable any time. On an unresolved symbol the LSP reaches for the vendor source physically present in site-packages, lifts it through the one RPC, mints+seals the `.proof` into the pool keyed by source CID, completes the link. Lazy lift-on-demand, memoized forever by content address. Solve still reads ZERO project FS — the **client** (warm, sitting on the source tree) does the read and feeds the memento; that is why the one-shot CLI can't have it. Auto-lift harvests only what the source **states** (vendor tests ARE the spec): lib with a test suite → real contracts day one, no vendor cooperation; lib with no assertions → honestly-empty, zero rows, no false green. Kills the "nobody ships proofs so the ecosystem is dark" worry outright. Builds ON TOP of the solve API (client-feed path over the pool), not into it — so it is cleanly serialized behind the zero-FS capstone. DoD in #4007.
- Implication steps 2+: un-stub `CallSite::implication()` + feed-fold from real link-time Obligations into the pool. Overlaps one-solve on `consistency.rs`/`orchestrate.rs`/`runner.rs`.
- Enumerate→LSP as one composition. Overlaps one-solve on `sugar-lsp` files.

---

## Landed this session (context)
Real-pandas squiggle gated 3.4 ms (#3934/#3940). Enumeration descent complete; `SourceMemento[path]` over-encoding reverted (#3950). Witness-as-verb complete (#3959/#3962/#3964). Implication step 1 (#3972). numpy 182→0. Real-name logos (itsdangerous #3960/#3977, stdlib base64 #3993, length/bounds #4004). Solve-API cuts #4/#6/#2/#8/#5/#7.

---

## Process
- `watch_worker` unreliable — poll. Busy-worker dispatch fails silently. Swap fresh at ~180k context; force-swap if looping. Long reports → write to a file.
- Solve cuts all touch `runner.rs` — strictly sequential, rebase each on prior merged cut.
- Paste the actual `55 passed` count in every PR; verify-before-ship.
- ONE PR per doc change.
- Shared checkout hazard: `/Users/tsavo/sugar` gets branch-switched by the capstone worker mid-flight — do handoff doc edits via the GitHub API (create_or_update_file off main), never via that working tree.
- CI CAVEAT: fast admin-merges cancel each commit's CI before it completes — main is green by per-PR corpus receipts, NOT by a completed CI run. Let CI finish on a HEAD periodically for a real end-to-end green.
- Doctrine: idempotency + no-double-entry + warm-FS=0 + no-invalidation = ONE thing (CID-keyed pool). "The existing thing already IS the pool."
