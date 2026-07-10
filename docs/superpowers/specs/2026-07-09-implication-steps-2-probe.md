# Probe: Implication steps 2+ (feed-fold Obligations) — 2026-07-09

**Lane:** epic #3809, serialized behind solve-api capstone #4014 (merged).
**Status:** PROBE ONLY — no build. Design decisions flagged below; do not guess in the proving core.

## 0. Rebase / main state

| Item | State |
|------|--------|
| `origin/main` HEAD | `fbcf2f59a` — #4014 capstone *delete pool_only_inputs* (solve is one path, zero project FS) |
| Also on main | fractions #4008, pathlib #4011, coverage issue context, auto-mode #4007 stack |
| Shared checkout | `part-3809-delete-pool-only-inputs` (ahead 1 / behind 1 of origin/main — same capstone content vs merge commit) |
| Battleaxe | ssh mux idle; no active cargo storm observed |
| Worktree for build | **not created yet** — probe only |

Implication step 1: #3972 merge `f911abef4` / commit `aa5e7d9d1`.

---

## 1. What step 1 (#3972) delivered

**Decision (T):** implication = spoken Obligation. One CID: carried == checked == spoken.

### Seal mapping

| Obligation (`as_implies` operands) | Implication memento field |
|------------------------------------|---------------------------|
| `post` (left of `post ⊃ pre`) | antecedent: `formula_endpoint_cid(post)` + slot `"post"` |
| `pre` (right of `post ⊃ pre`) | consequent: `formula_endpoint_cid(pre)` + slot `"pre"` |

### Concrete artifacts

- `sugar_claim_envelope::{seal_spoken_obligation, spoken_obligation_content_cid, spoken_obligation_proof_bytes}`
  - Pure under fixed seal seed/timestamp (`OBLIGATION_SEAL_*`)
  - Reuses `mint_implication` / `ImplicationMember` — **no parallel type**
  - Hardcodes mint `verdict: "holds"` (existing mint convention; **not** a solver claim — step 1 PR said so explicitly)
- `sugar_linker::Obligation` is `pub`; methods:
  - `as_implies()` → `IrFormula::Implies { operands: [post, pre] }`
  - `seal_as_implication()` → seal
  - `implication_content_cid()` → content CID
- Positive `speak_implication` + re-speak + first-speaker-wins (`sugar-verifier/tests/utterance.rs`)
- Seal purity tests in `mint_bridge_implication.rs`

### What step 1 explicitly did **not** do

- Did **not** un-stub `CallSite::implication()` (tree still returns `None`)
- Did **not** change linker discharge math
- Did **not** connect sealed edges into a real solve / pool feed path
- Real `post ⊃ pre` discharge stayed on the linker (in isolation of the seal)

---

## 2. Stub current behavior

### `sugar-compiler` tree (`tree.rs`)

```text
// Module doc: contract/implication are LINK-time (#3831) stubs.
// No RPC. Binding is solve()-time (SEAM 5).

pub fn contract(&self) -> EdgeTarget<Contract> { EdgeTarget::Unbound }

pub fn implication(&self) -> Option<Implication> { None }
```

- `Implication` placeholder type only carries `pre: IrFormulaPlaceholder` — **not** the full `{post, pre}` Obligation shape.
- Protocol pin: `protocol/specs/2026-07-08-enumeration-protocol.md` §5 — always `None` / Unbound; binding is `ProofGraph::solve`'s job.
- `fold_claim_tree` walks **facts + universes only** — never calls `implication()`:

```text
call_sites → universe? + assertions → facts
// no implication fold arm
```

### Linker Obligation path (live mint, link-local discharge)

In `sugar-linker/src/lib.rs` per bound edge:

1. Resolve `source_post` / `target_pre` from contracts
2. `ObligationState::derive(post, pre)` → Pending / CallerPostAbsent / VacuousPreAbsent
3. `obligation_evidence_term` → wire `evidenceTerm` from `Obligation::as_implies` JSON (carried == checked projection)
4. `discharge_obligation`:
   - structural short-circuits
   - JCS reflexive equality
   - else SMT plan on `post ⊃ pre`
5. Map verdict → LinkerError kinds (`UnprovableObligation`, `ImplicationUnprovable`, …)

`seal_as_implication` exists on `Obligation` but is **not** called on the production link path.

### Orchestrate two-beat solve (critical split)

`sugar-compiler/src/orchestrate.rs`:

- **Beat 1 `link_beat`:** plain `link()` (no solver registry). **Only** keeps `UnresolvedSymbol` / `SignatureMismatch`.  
  **Drops** all obligation-discharge errors (`UnprovableObligation` / `Implication*`) — by design: beat 2 is the authoritative discharge door (ambient facts, cross-proof conjoin that link doesn't see).
- **Beat 2:** `verify_consistency` → runner over the pool.

So linker Obligations are minted during `link()`, but their discharge **opinion is discarded** on the production solve door. Beat 2 never receives sealed implication mementos from those Obligations today.

### Cut #7 residue (tier-2 disk deleted, #4005)

- `try_tier2` / `mint_and_cache` disk path removed (~−522 lines)
- In-pool Tier 0c (`pool.can_implies`) **kept**
- `minted_sink` still threaded through `work_one` but **unused**:  
  `let _ = (n_cache, minted_sink, cfg);`  
  No production mint→pool of implications after discharge.

---

## 3. Concrete call chain: linker Obligation → pool → discharge

### Desired chain (what "feed-fold real Obligations into the pool" means)

```text
[contracts in pool]
    │
    ▼
derive_linker_inputs(pool)          // sugar-compiler/linker_inputs.rs
    │  LinkerInputs { contracts, edges }
    ▼
link / link_with_solvers            // sugar-linker
    │  per edge: Obligation { post, pre }
    │  as_implies / evidenceTerm
    │  (optional) discharge_obligation via SMT
    ▼
seal_as_implication()               // step 1 — existing memento shape
    │  antecedentHash = formula_endpoint_cid(post)
    │  consequentHash = formula_endpoint_cid(pre)
    │  slots post/pre, one CID
    ▼
FEED into pool                      // MISSING today
    │  speak_implication / push_implication / insert(AnchoredMember)
    │  or ProofGraph::feed(graph_from_implication(...)) then self_load
    ▼
Runner work_one Tier 0c             // sugar-verifier/runner.rs ~1669
    │  producer_post_for_arg_term → (post_formula, post_hash)
    │  consumer_pre_hash = formula_hash(pre)
    │  pool.can_implies(post_hash, pre_hash)
    │     → ProvenDirect / Transitive / Reflexive / Unknown
    ▼
if Unknown → Tier 1 hash eq → Tier 3 SMT on build_implication_obligation(post, pre)
```

### Discharge consumer (user asked consistency; live tier is runner)

| Location | Role |
|----------|------|
| **`runner.rs` Tier 0c** | **The** ImplicationMemento consumer: `pool.can_implies(post_hash, pre_hash)` → discharge with reason `tier0c: implication proven direct/transitive/reflexive` |
| `types.rs` `verify_implication` / `can_implies` | Scan `MemberKind::Implication` for matching `antecedentHash`/`consequentHash`; BFS transitive |
| `consistency.rs` | Beat-2 **driver** (`verify_consistency` → indexes → runner/solve). Does **not** itself call `can_implies`. Implication FOL nodes (`kind: implies`) appear as formula structure / body law, not the ImplicationMemento tier |
| `orchestrate.rs` | Beat 1 link filter + beat 2 `verify_consistency`; **no** Obligation→pool feed |

### Hash scheme risk (plumbing, but soundness-adjacent)

| Scheme | Path | Alpha-canonicalize? |
|--------|------|---------------------|
| Seal endpoint | `formula_endpoint_cid(IrFormula)` → `canonicalize_formula` → `jcs_cid_of_json` | **Yes** |
| Tier 0c lookup | `formula_hash(Json)` → JCS + blake3-512 | **No** |

Both produce `blake3-512:`-prefixed CIDs via the same hasher, but **binder-bearing formulas may diverge** after alpha-canon. Binder-free atomics likely match. Feed-fold must either align hashes or Tier 0c will miss (decorative miss, not false green — unless something else discharges).

---

## 4. What "feed-fold" requires (gap analysis)

| Gap | Today | Needed |
|-----|-------|--------|
| Un-stub `CallSite::implication()` | Always `None` | Return real edge data — but see design D1 |
| Fold arm | `fold_claim_tree` ignores implication | Some path must emit Implication members into graph/pool |
| Linker seal use | Seal API exists; never called on link production path | Call seal on real Obligations |
| Pool insert | No feed of link-time Obligations | Insert before / into beat 2 so Tier 0c can see them |
| `minted_sink` | Dead after cut #7 | Either revive as post-discharge insert or replace with explicit feed |
| Teeth | No solve-path twin for seal→Tier 0c | Truthful discharges; lying refuses |

---

## 5. DESIGN DECISIONS — STOP (do not guess in the proving core)

### D1. Where does `CallSite::implication()` live, and what does un-stub mean?

Enumerate-tree `CallSite` is **lift/enumerate-time**. Protocol §5 and module docs say implication is **LINK-time** (needs both contracts resolved). Returning a real Obligation from the enumerate tree without link resolution is a category error (same class as the dead lift-time `evidenceTerm` #3831 removed).

Options (pick one):

- **A. Tree stays stub; "un-stub" means a post-link / solve-time binding** on a different face (orchestrate / pool-derived edge / verifier CallSite), not `sugar.enumerate`.
- **B. Tree method becomes a lazy resolve** that requires already-fed universe contracts (still not full link-time bind).
- **C. Expand `Implication` to `{post, pre}` Obligation shape** and only populate after an explicit link pass threads results back onto tree nodes.

**Recommendation to freeze:** A or C with solve-time ownership; do not pretend enumerate can mint `post ⊃ pre`.

### D2. Seal ≠ discharge, but Tier 0c treats any Implication memento as proven

- `seal_spoken_obligation` / `mint_implication` always stamp `verdict: "holds"`.
- Step 1 docs: seal does **not** claim solver discharge.
- `verify_implication` / `can_implies` only match hashes — **no** solver re-check, **no** trusted-signer gate on the in-pool path (trusted signers were tier-2 disk; cut #7 removed that path).

Therefore:

> **If feed-fold seals every link Obligation and inserts it, a lying twin also gets `verdict: "holds"` and Tier 0c will discharge it → teeth FAIL (decorative / false green).**

Honest options:

1. **Prove-then-feed:** only insert Implication mementos **after** real discharge (linker `link_with_solvers` or runner Tier 3). Seal is cache/federation of *proven* edges. Bad twin never enters pool → Tier 0c Unknown → Tier 3 unsat/refuse.
2. **Seal-as-utterance, not as proof:** change Tier 0c / `can_implies` so seal-only mementos do not auto-discharge (e.g. require prover field, witness, trusted speaker, or separate kind). Then seal can feed freely; discharge still Tier 3.
3. **Feed obligations as work items, not ImplicationMementos:** fold the *formula* into Tier 3 obligation construction only; don't use Tier 0c for seal-only edges.

Step 1 + cut #7 trajectory leans toward **(1)** or a hybrid: client/federation feeds *proven* implications; solve may mint after discharge for reuse. **Do not implement (seal-all → insert) without T ruling.**

### D3. Who is the authority for first discharge — linker or beat 2?

Today: orchestrate **drops** linker implication errors; beat 2 owns discharge. Re-enabling linker discharge as authoritative would reverse that design. Feed-fold should probably:

- derive Obligations from the same resolved contracts beat 1 already binds,
- discharge (or accept pre-proven mementos) on the **beat 2 / runner** path,
- not re-introduce dual opinions (link says unsat, consistency says sat).

### D4. Teeth placement

Mandatory twin:

| Twin | Expected |
|------|----------|
| Truthful `post ⊃ pre` (e.g. `x≥5 ⊃ x≥0` or identical / solver-eq) | **Discharged** via implication tier (Tier 0c if fed proven, or Tier 3 if seal-only path refuses 0c) |
| Lying twin (e.g. `x≥0 ⊃ x≥5`) | **Must not discharge** (Unsatisfied / refuse / undecidable-as-refuse — not silent green) |

If breaking the feed does not flip the verdict, feed is decorative — do not ship.

Prefer an instrument that:

1. Builds two pools/graphs identical except implication feed content (or edge formulas),
2. Asserts sat vs unsat,
3. Optionally asserts reason contains `tier0c` when the design intends 0c (so we don't pass only via Tier 3 while claiming feed-fold).

---

## 6. Plumbing-only subset (safe after D2 ruling)

If T picks **prove-then-feed (D2.1)**:

1. Worktree off `origin/main` (`fbcf2f59a`+).
2. After beat-1 bind (or inside runner when both posts/pres known): build `Obligation::new(post, pre)`.
3. Discharge via existing Tier 3 / solver plan (or `link_with_solvers` only if D3 says so).
4. On `Discharged`: `seal_as_implication` → insert into pool (revive `minted_sink` or explicit feed before subsequent callsites / stages).
5. On non-discharge: do **not** insert; leave Tier 0c Unknown.
6. Un-stub: either expand tree API as post-link binding (D1.C) or document that `CallSite::implication()` remains enumerate-stub and the live face is orchestrate/runner (D1.A) — still need an API surface the task named.
7. Align `formula_endpoint_cid` with `formula_hash` for the formulas we seal (or hash the same way on both ends).
8. Bad-twin test as above; battleaxe **55/55**; PR "Part of #3809".

If T picks **seal-as-utterance (D2.2)**: different core change to `can_implies` — larger, soundness-critical, separate design.

---

## 7. Files that will move (after unblocking)

| File | Role |
|------|------|
| `sugar-compiler/src/tree.rs` | Un-stub / reshape `Implication` + `CallSite::implication` if D1 says tree |
| `sugar-compiler/src/feed_from_tree.rs` | Fold arm for implications if graph-feed path |
| `sugar-compiler/src/orchestrate.rs` | Feed between beat 1 and beat 2; do not re-voice linker discharge carelessly |
| `sugar-linker/src/lib.rs` | Optional: seal after discharge; already owns Obligation |
| `sugar-verifier/src/runner.rs` | Tier 0c consumer; revive minted_sink or explicit insert |
| `sugar-verifier/src/types.rs` | `can_implies` only if D2.2 |
| `sugar-claim-envelope` | Seal already done (step 1) |
| New test(s) | Bad-twin flip; prefer `sugar-compiler` or `sugar-verifier` integration |

---

## 8. Probe verdict

| Question | Answer |
|----------|--------|
| Step 1 delivered? | Seal + speak + pure CID; no solve feed |
| Stub today? | `CallSite::implication() → None`; fold ignores it; seal unused on link path |
| Discharge tier? | **Runner Tier 0c `pool.can_implies`**, driven under `verify_consistency` (not a separate consistency.rs ImplicationMemento scan) |
| Feed-fold just plumbing? | **No** — blocked on D1 (where un-stub lives) and especially **D2 (seal vs proven)** and D3 (authority) |
| Action | **STOP for T ruling on D1/D2/D3 before any proving-core edit** |

