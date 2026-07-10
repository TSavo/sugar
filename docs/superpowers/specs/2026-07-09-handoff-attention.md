# Handoff: what needs attention (2026-07-09)

Coordinator handoff after a long fleet session on epic #3809. Main is green; ~40 PRs merged (#3931–#3971). This is not a status brag — it's the list of things that need eyes, ordered by how much they can bite.

---

## Fleet state (live workers)

| Worker | Lane | State | Risk |
|--------|------|-------|------|
| 97086 | implication = spoken Obligation (A) | Building step 1; **hit a seal-rule mismatch, reporting it** | context ~235k (swap after report) |
| 97102 | numpy construction-gap drain | Draining final floor totalizers, R ~4 | context ~184k (swap at idle) |

Both Grok agents. `watch_worker` is unreliable for them (false "finished"); **polling is the idle-detector**. Dispatch to a *busy* worker silently fails — the brief stays unsent in the composer (bracketed-paste Tab-commit does not submit). Only dispatch genuinely-idle workers; verify submission by reading back.

---

## Landed this session (done, gated)

- **Enumeration typed descent — complete.** `sugar.enumerate` returns self-locating `SourceMemento`s at every level (source→functions→call_sites→assertions→facts/universe). NOTE: an earlier `SourceMemento[path]` over-encoding was built (#3942–3947) then **reverted** (#3950, −1042 lines) — a `SourceMemento` is already self-locating (cid+file+span); the path was redundant. Wire proven self-locating e2e (#3951).
- **Real-kit LSP demo — proven + gated.** Real pandas → real lift → real UNSAT squiggle (#3934), skip=red on the gate box (#3936), consolidated DoD scoreboard (#3940): FS=0, byte-identical, **3.4 ms warm solve**, golden NDJSON byte-identical (#3938). The PyCon inline-editor moment is an engineering fact, not a bet.
- **Witness-as-verb — complete (F1-B).** SEAM 7 typed config (#3959), kit oracle is the one resolve door (#3962), env channel retired (#3964). `witness(packageCid)` is byte-identical across arm/oracle/warm/cold. This is `WitnessPool<CID, WitnessMemento>` made real — oracle RPC = resolve, Rust `package_outcome` = verify; no struct invented, no env, no cache-invalidation (CID-keyed cache never invalidates).
- **numpy construction-gap wall: R 182 → ~4.** Drains #3948–#3971. Remaining: `next_with`, `SymbolicValue.add_with`, `binary_operator_with` floor totalizers.
- **Coordinate/vendor-op coverage — done at real scale.** 187 real numpy/pandas API shapes, 0 gaps (#3944).
- **Kevlar (T's) membrane arc.** itsdangerous logo real-name proof, CI-ratcheted (#3960); census ratchet (#3957); corpus receipt that caught 2 reds (#3955); **#3956 discrimination boundary closed** (padding-only claim + wrong-unpadded twin).

---

## NEEDS ATTENTION (ordered by bite)

### 1. Implication seal-rule mismatch (BLOCKING, incoming)
97086 found a mismatch mapping `Obligation::as_implies` → `mint_implication`/`ImplicationMember`. T chose **A (implication = spoken Obligation)**: one content-addressed seal, carried==checked==spoken, one CID. The mismatch is a seal-rule detail T must resolve — a field the memento needs that the Obligation doesn't carry (or vice versa). Read the report when it lands; do not let the worker paper over it. The invariant that matters: `seal(Obligation)` is a pure function → same CID; two CIDs for one `post⊃pre` = a failing test.

### 2. #3956 discrimination boundary — **CLOSED (claim of record)**
Measured: wrong-but-unpadded RHS `b"cHJvdmVraXR"` (last char flipped, no trailing `=`) **discharges** under closed `¬suffix-of("=", out)`. Padding lie still unsat. Claim of record: logo is **padding / trailing-`=` only**, not full base64 injectivity. Instrument: `examples/itsdangerous-token-padding/{SCOPE.md,wrong-unpadded/,run-logo-receipt.sh}` — third twin expects **discharged** (out of scope ratchet). Stronger ambient (tower in ambient) still encoding-STOPs; do not silently expand the claim without a new twin.

### 3. #3958 free-name analysis (test gap)
Binding module-level constants into the dig temporal is correct, but rides entirely on resolving free names. A *shadowed* (local re-binds the name) or *conditionally-defined* module constant could be mis-bound or missed. Needs a bad-twin: a module constant shadowed by a local, confirm the dig binds the right one.

### 4. Receipt discipline — "paste the count, not the command"
Two floor-change PRs (#3967, #3968) merged with the corpus command named but the `55/55` **result blank**. The runs happened; the receipts under-reported. Fixed forward: #3969+ paste the actual `# 55 passed` line, and the rule is now in worker briefs. **Enforce this on every lane** — a named command with no output is not a receipt. This is the same masked-green class as #3924.

### 5. Corpus BETWEEN grounding-path merges (the #3924 lesson)
Focused per-PR receipts cannot see structural over-constraint; only the battleaxe witness corpus (fresh pool) catches a `truthful→unsat`. #3924 (tuple injectivity) merged on focused receipts and the corpus later caught the regression (fixed #3935). **Any PR touching lift grounding/floor gets a battleaxe corpus 55/55 IN the PR, and run the corpus between such merges — not after a batch.** Kevlar's membrane PRs also merged receipt-thin first (closed by #3955). Same timing risk.

### 6. Remaining ten-verb work (after implication)
Per the settled order: witness (done) → **implication (building)** → **solve-as-one-RPC** → optional lower. The big one is `solve`: the CRUX says cold-path vs warm-path is one operation (`solve(what was fed)`); residency is a cache, not a code path; the daemon is "solve that didn't say goodbye." DoD is byte-identical enriched verdict rows resident-or-fresh. This is the deepest remaining surgery — design-heavy, T shapes it.

### 7. numpy R → 0, then keep it there
Three floor totalizers left (`next_with`, `SymbolicValue.add_with`, `binary_operator_with`). After R=0: add a **totality-at-zero ratchet** so it can't silently climb (drains reveal masked gaps — R has bounced up mid-lane when a drain unmasked a deeper floor; a ratchet on the honest-0 is the guard).

### 8. Enumeration → LSP composition (open)
The enumerate wire returns self-locating mementos (proven e2e), and the real-kit LSP acceptance passes — but the *descent-through-enumerate feeding the LSP acceptance path* as one composition isn't wired end-to-end. Nice-to-have for the "one protocol drives the squiggle" story.

---

## Process notes (for whoever coordinates next)
- Merge-on-sight on green/known-baseline; admin-merge OK; **read the mechanism on grounding/soundness PRs**, not just the green.
- Worker context: swap fresh at ~180k+ (kill_worker force=true → spawn agent → re-dispatch); they degrade and reports scroll off the viewport past ~200k. For long reports, have the worker **write to a file** (`docs/superpowers/specs/…`) and read it — the TUI only shows the tail.
- kevlar.sindome@ = T's parallel stream; his PRs are his (merge + telemetry, read the mechanism, don't gate).
- The doctrine thread that unified this session: **idempotency + no-double-entry + warm-FS=0 + no-cache-invalidation are one thing — a CID-keyed map/pool.** Applied to witness (`WitnessPool`), and now to implication (spoken Obligation, one seal). Reach for "the existing thing already IS the pool," not "build the abstraction."
