# CI & Gate Architecture — Soundness and Completeness Boundaries

This document maps the real gates that define correctness-of-the-product itself: the teeth that catch false discharges, the source-audit ledger that enforces `silent=0`, the conformance suite that locks the CID, and the invariants that must never regress.

## Overview

Every merge to main runs **six gate suites** (via `make ci`), executed in sequence:
1. **check-cargo-entrypoint** — routing enforcement (Cargo commands via entrypoint)
2. **test-all** — the acid test (Rust + Python kit integration + concept-name ban)
3. **test-showcases** — 48 end-to-end demonstrations across 6 languages
4. **self-attest** — supply-chain binary CID pinning (dogfood on sugar itself)
5. **coretests-source-audit** — source-level loci classification (honest accounting)
6. **coretests-invariants** — exact-pin on counters (semantic gate; silent≡0, unclassified→0)

**Why this order matters:** gates run non-fail-fast on `test-all` (both Rust + Python even if one fails); conformance is outside the main CI loop (separate manual run); the coretests pin is the *last* gate, so a regression is caught only after proving the kit still lifts.

---

## Gate 1: Cargo Entrypoint Routing — `check-cargo-entrypoint`

**File:** `/Users/tsavo/provekit/.worktrees/sugar-20260628/tools/check-cargo-entrypoint.sh`

**Purpose:** Enforce that all Cargo invocations in the Makefile route through `$(CARGO)` or `$(CARGO_LOCAL)`, never raw `cargo`. This enables cross-language build coordination via `bcargo` (build-multiplexer) without hidden breakage on branches that haven't synchronized.

**What it checks:**
- Regex scan of Makefile for raw `cargo` commands (build, test, check, run, tree, clean)
- Fails if any found; pass is silent (no output = clean)
- Exit: 0 (pass), 1 (raw cargo found), 2 (Makefile missing)

**Audience:** Contributor (enforced locally before push, not consumed by end-user)

**Priority:** P1 — a raw `cargo test` on main masks test failures that CI would catch with proper kit coordination

**Existing coverage:** none (routing enforcement is tactical, not documented as separate doc)

---

## Gate 2a: Rust Integration Tests — `test-rust`

**Files:**
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/implementations/rust/Cargo.toml` (workspace root)
- Triggered by: `make test-rust` → `cargo test --release --manifest-path implementations/rust/Cargo.toml`

**Purpose:** Exercise the Rust kit's lifter and verifier against real source code, including cross-language RPC to the Python kit over JSON-RPC (PEP 1.7.0) for platform-semantics resolution. This is the primary integration gate; it also runs the **teeth-asymmetry discharge guard**.

**What it proves:**
- Every Rust crate in the workspace compiles and its tests pass
- Cross-language kit coordination works (Python kit spawned via RPC)
- False assertions are actively REFUTED (never discharged)
- Implication edges compose correctly across seam boundaries

**Key test:** `sugar_lift_rust_tests::teeth_asymmetry_discharge_guard` — soundness regression guard

**Audience:** Contributor

**Priority:** P0 — blocks all merges; false discharge is the cardinal sin

**Existing coverage:** 
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/implementations/rust/sugar-lift-rust-tests/tests/teeth_asymmetry_discharge_guard.rs` (soundness test; not a doc)
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/docs/INVARIANTS.md` (soundness framing)

---

## Gate 2b: Python Kit Tests — `test-python`

**Files:**
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/implementations/python/` (5 packages)
- Triggered by: `make test-python` → pytest in each package

**Purpose:** Verify Python test-lifter, source-lifter, witness resolver, and emission (pytest/unittest/hypothesis).

**What it proves:**
- Python lifter emits canonical JCS bytes byte-identical to Rust reference
- Witness packaging (blake3 + ed25519 signing) works
- Platform semantics (int/float/bool) resolve correctly

**Key suites:**
- `sugar-lift-py-tests` — test assertion lifting (55 tests)
- `sugar-lift-python-source` — source-level contract derivation
- `sugar-lift-py-pytest-witness` — witness resolution and signing
- `sugar-build-witness` — witness package construction

**Audience:** Contributor

**Priority:** P0 — blocks Python-using projects; completeness in Python universe

**Existing coverage:** None (individual package docs exist but no unified Python kit gate doc)

---

## Gate 2c: Concept-Name Ban — `check-no-concept-name`

**Files:** Makefile implicit (grep for `concept_name|conceptName` under `implementations/`)

**Purpose:** Enforce the hard law: no shared concept hub / cross-language identity layer. The CID IS the identity.

**What it checks:** Git grep for `concept_name` or `conceptName` anywhere under implementations/

**Audience:** Architect/Contributor (enforces design invariant)

**Priority:** P1 — federation collapses if concept naming sneaks back in

**Existing coverage:** INVARIANTS.md § VI (federation via CID-only, no hubs)

---

## Gate 3: End-to-End Showcase Receipts — `test-showcases`

**Files:** 48 example showcase scripts in `/Users/tsavo/provekit/.worktrees/sugar-20260628/examples/`

**Notable examples:**
- `rust-coretests-report/run.sh` — stdlib coverage ledger (measuring stick)
- `tokio-channel-implication-edge/run.sh` — async correctness (implication edges)
- `java-panama-bridge/run.sh` — FFI cross-language binding
- `python-literal-base64/run.sh` — seam closure and literal universe
- `forall-vampire-showcase/run.sh` — quantifier discharge via Vampire solver

**Purpose:** Prove that drop-in sugar works on real library code with zero changes. Each showcase runs the full pipeline: lift → compose → verify → witness check.

**What it proves:**
- Contract lifting works end-to-end for 6+ languages
- Proof composition closes at the seam (implication edges discharge)
- Witness verification recomputes CIDs and re-signs
- Multiple solver backends (z3, Vampire) interoperate

**Audience:** End-user (showcases are shipped in docs/examples/)

**Priority:** P0 — the product pitch is "prove real code"; if showcases fail, the pitch fails

**Existing coverage:**
- Each showcase has a README (e.g., `tokio-channel-implication-edge/README.md`)
- Aggregate: no single "gate narrative"

---

## Gate 4: Self-Attestation (Supply-Chain Binary CID) — `self-attest`

**Files:**
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/sugar-release.toml` (manifest)
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/implementations/rust/sugar-cli/src/cmd_release_gate.rs` (gate executor)

**Command:** `sugar package release --manifest sugar-release.toml --receipts <dir> [--verify-only]`

**Purpose:** Dogfood the coarse supply-chain pin ON SUGAR ITSELF. Mint content-addressed binary CIDs for `sugar` and `sugar-lift` binaries; pinned dependency vector (full Cargo.lock closure); coverage gate (every bin either pinned or explicitly excluded).

**What it proves:**
- Sugar's own artifacts are reproducibly content-addressed
- No dependency slips in or out silently (Cargo.lock change = CID change)
- A newly-added binary cannot be shipped unintentionally (coverage gate)
- The tool that verifies proofs is itself verified the same way (self-application ground zero)

**Invariants checked:**
- **binaryCid** pinned (SHA3-512 of sugar+sugar-lift binaries)
- **dependencyVectorsCid** pinned (content-address of entire Cargo.lock)
- **Coverage gate:** every workspace bin either in [[artifact]] or in [coverage] exclude list (N-1 of N pinned = 0)

**Audience:** Operator/Integrator (supply-chain integrity; proves no xz-class attack)

**Priority:** P0 — if supply chain gates are inert, the whole product is shadow

**Existing coverage:** None (gate exists, no doc; is part of internal INVARIANTS.md philosophy)

---

## Gate 5: Coretests Source Audit — `coretests-source-audit`

**Files:**
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/examples/rust-coretests-report/corpus/` (Rust stdlib coretests)
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/examples/rust-coretests-report/run.sh` (entry point)

**Command:** `sugar lift --report` over a manifest-driven corpus (Rust nightly coretests)

**Purpose:** Honest accounting of EVERY assertion locus in the Rust standard library test suite. Classify each into:
- **warranted** — lifted to a checkable FOL fact
- **refused** — lifter declined with a named reason (loudly-bounded-lossy)
- **unresolved** — no Sugar for this shape yet (the roadmap, the honest dark)
- **support** — inert (doc-comment, compiler pragma; contains no assertion)
- **missing** — seen in source but neither lifted nor warned (SILENT DROP, unsound)

**The ledger rule:** `support` must NEVER hide unresolved. A FunctionDef/Import/ClassDef containing unannotated loci MUST be bucketed as `unresolved`, not `support` (fake denominator otherwise).

**Audience:** Contributor/Architect

**Priority:** P1 — drives the lift roadmap; silent drops are unsound; measuring stick visibility is non-negotiable

**Existing coverage:**
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/examples/rust-coretests-report/README.md` (ledger semantics)
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/docs/INVARIANTS.md` § VII-VIII (spirit of honest accounting)

---

## Gate 6: Coretests Invariants Pin — `coretests-invariants` (THE TEETH GATE)

**Files:**
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/implementations/rust/coretests-invariants.json` (pinned snapshot)
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/scripts/check-coretests-invariants.py` (verification script)
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/implementations/rust/sugar-lift-rust-tests/src/bin/coretests_sweep.rs` (sweep binary)

**Command:**
```bash
coretests_sweep <corpus-dir> --rustc-cfg > /tmp/coretests-hermetic.out
python3 scripts/check-coretests-invariants.py /tmp/coretests-hermetic.out implementations/rust/coretests-invariants.json
```

**Purpose:** THE ACOUSTIC GATE. Hermetic sweep (no `--dissolve`, fully deterministic) of Rust 1.96.0 coretests over a pinned nightly toolchain. Compare OUTPUT EXACTLY to the pinned snapshot. CI goes RED when:
- A drain didn't drain (unclassified didn't move as claimed)
- A regression (unclassified increased vs prev_unclassified)
- A silent drop (silent ≠ 0)
- A corpus change (assertion_multiset_cid shifted without explanation)

**Pinned fields (exact match required):**

| Field | Current | Meaning |
|-------|---------|---------|
| `assertion_multiset_cid` | blake3-512:9500ba70… | SHA3-512 of all assertions in corpus (universe fingerprint) |
| `silent` | 0 | **HARD INVARIANT:** missing assertions (SILENT DROP FORBIDDEN) |
| `missing_assertions` | 0 | Source assertions not reached (total accounting) |
| `discharged` | 10544 | Lifted to FOL and solved (z3-UNSAT on negation) |
| `refused` | 1125 | Terminal, with named reason (loudly-bounded-lossy) |
| `unclassified` | 0 | No Sugar yet; roadmap (must not regress) |
| `callsite_expansion` | 4945 | Extra obligations mined from seam traversal |
| `prev_unclassified` | 0 | Direction guard (unclassified ≤ prev only) |
| `note` | free text | Commit narrative: what moved and why |

**The contract:** Every push predicts its effect and pins it. Reality is checked EXACTLY against the claim. To move a number, you update the JSON, run the gate, and prove the sweep matches.

**Why this is P0:**
- **silent==0** is the completeness invariant: no assertion is silently lost (total accounting closure)
- **unclassified→0** is the lift roadmap: progress is visible, not hidden
- **Exact pin prevents drift:** a "close enough" gate degrades to a trophy (squishy pass)
- **Re-pin narrative is auditable:** the commit explains the machinery change, corpus change, or drain

**Audience:** Contributor/Architect (this gate is where the product proves itself)

**Priority:** P0 — foundational; `silent==0` is a security invariant

**Existing coverage:**
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/examples/rust-coretests-report/README.md` (why the ledger exists)
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/docs/plans/2026-06-13-stdlib-unclassified-to-zero.md` (the unclassified→0 campaign)
- `/Users/tsavo/provekit/.worktrees/sugar-20260628/docs/INVARIANTS.md` (soundness philosophy)

---

## Cross-Language Conformance (Non-CI, Manual Gate)

**Files:** `/Users/tsavo/provekit/.worktrees/sugar-20260628/conformance/run.sh`

**Languages tested:** Rust (reference), Go, Java, Python, C++, C, Zig, C#, Ruby, Swift (10 total)

**Purpose:** Prove byte-for-byte JCS canonical equivalence across all language kits. Every kit asserts internally that its output matches the Rust reference. If a kit passes its own tests, cross-language equivalence is proven (no hand-waving, no "close enough").

**Why it's NOT in `make ci`:** Conformance is non-deterministic (long compile times, optional toolchains like Zig/Swift); it's run manually before major releases. Once proven, it stays proven (CID is immutable).

**Invariant:** If a kit is present and its toolchain is on PATH, conformance MUST pass. Absence of toolchain = SKIP (not failure). A real failure is a soundness regression (the CID changed in an unexpected way).

**Audience:** Integrator (before packaging a release)

**Priority:** P0 — federation **is** byte-identical CIDs; drift = broken federation

**Existing coverage:** None (gate works, not documented as separate doc)

---

## Soundness Invariants (Backbone)

These are the load-bearing laws that every gate enforces:

### 1. `false_discharges == 0` (Security)

**What it means:** A FALSE assertion is NEVER discharged (proved true when it is false).

**How it's guarded:**
- **Teeth-asymmetry test** (`test-rust` gate) — lifts false claims and asserts z3 REFUTES them (negation is UNSAT). A wrong value grounds to a concrete inequality that z3 cannot satisfy.
- **Body discharge** — never assumes callee's postcondition as an axiom; instead inlines the actual body definition (ground truth) via weakest-precondition evaluation.
- **Coverage in coretests sweep** — every shape lifted must either discharge (z3-UNSAT negation) or refuse (named residual); no "skip as pass."

**File:** `/Users/tsavo/provekit/.worktrees/sugar-20260628/implementations/rust/sugar-lift-rust-tests/tests/teeth_asymmetry_discharge_guard.rs` (366 lines; comprehensive fixture)

**Audience:** Architect/Contributor

**Priority:** P0 — if this breaks, the product IS the attack

---

### 2. `silent == 0` (Completeness)

**What it means:** No assertion is silently dropped from the accounting. Every assertion surface invocation is either lifted, refused (with reason), or counted as missing (structural dark, not a silent drop).

**How it's guarded:**
- **Coretests-invariants pin** — exact-match gate on `silent` field (line 3 of JSON). CI goes red if `silent` ≠ 0.
- **Source-audit ledger** (`coretests-source-audit`) — classifies every locus into warranted/refused/unresolved/support/missing. Rules prevent `support` from hiding unresolved loci.
- **Assertion-accounting ledger** — the `coretests_sweep` binary walks every test file, runs the lifter on each, and counts results.

**Why it matters:** Completeness is the inverse of false discharge. You can't falsely pass if you've accounted for everything.

**File:** `/Users/tsavo/provekit/.worktrees/sugar-20260628/scripts/check-coretests-invariants.py` (line 20: "missing assertions (SILENT): 0")

**Audience:** Architect/Contributor

**Priority:** P0 — together with false_discharges==0, this is the soundness pair

---

### 3. All Vectors Pinned (Conjunctive Pin Defense)

**What it means:** Correctness is defended along N independent vectors (supply-chain, binary, contract, witness, solver). To falsely pass, an attack must compromise ALL N. Removing one pin collapses to a single attack surface.

**Vectors:**
1. **Contract CID** — the lifted spec (content-addressed; lift-kit attack)
2. **Witness CID** — the re-run that demonstrates satisfaction (witness-oracle attack)
3. **Binary CID** — the solver binary (binary-tampering attack)
4. **Dependency Vector CID** — the Cargo.lock (supply-chain attack)
5. **Solver verdict** — z3/Vampire discharges the formula (solver compromise)

**How it's guarded:**
- `self-attest` pins binaryCid + dependencyVectorsCid for sugar itself
- Every `.proof` file's Merkle DAG closes to a root CID (memcmp(64))
- Bridge lifters pin contract-CID-to-symbol (cross-language binding)
- Witness verification re-derives CID and re-signs (recomputation, never trust)

**Audience:** Integrator/Operator

**Priority:** P1 — a missing pin is a backdoor

---

## The Gates Hierarchy: What Fails First

When `make ci` runs, failures surface in this order:

1. **check-cargo-entrypoint** fails → build issue is routing (dev error)
2. **test-rust** fails → integration or soundness issue (lift/verify bug)
3. **test-python** fails → Python kit out of sync (cross-language bug)
4. **check-no-concept-name** fails → architecture violation (federation compromise)
5. **test-showcases** fails → end-to-end pipeline broken (user-facing regression)
6. **self-attest** fails → supply-chain compromise (binary/dependency tampering)
7. **coretests-source-audit** fails → source audit diverged (corpus or lifter change)
8. **coretests-invariants** fails → accounting mismatch (THE TEETH, the last gate)

The last gate (coretests-invariants) is the loudest: "Your change predicted X, reality is Y. Fix it or document it and re-pin."

---

## Open Questions

1. **Conformance gate in CI?** Why is `conformance/run.sh` manual, not automatic in `make ci`? Is there a performance reason, or is it because multi-language toolchain setup is flaky? Should there be a CI-lite conformance (Rust+Python only)?

2. **coretests_sweep vs discharge_sweep distinction?** The Makefile mentions `discharge_sweep` as a binary but doesn't show it running in `make ci`. What does it do? Is it subsumed by `coretests_sweep`'s classification?

3. **Validator redundancy:** The coretests gate uses `check-coretests-invariants.py` (Python) to verify a Rust-generated sweep output. Is there a reason verification is not in Rust (the reference kit)? Could Python gate-verification compromise the gate?

4. **Z3 dependency:** The teeth-asymmetry test is Z3-gated (degrades to no-op if `/usr/local/bin/z3` is missing). Is this acceptable? Should Z3 presence be a hard requirement, or is the skip-on-absent strategy sound (assume CI has z3, local devs might not)?

5. **Quiet exclusions in release-gate:** The `sugar-release.toml` excludes 21 binaries (dev/test/RPC servers). How is it verified that a future PR doesn't accidentally ship an RPC server as a pinned artifact? Is the coverage gate sufficient?

6. **Silent vs missing distinction:** In the coretests ledger, what's the practical difference between `silent` (missing assertions in accounting) and `unresolved` (no sugar yet)? Both are dark, but one is "we didn't count it" (unsound) and one is "we saw it and decided not to lift" (honest). Is the boundary crisp in the lifter?

---

## Summary for Contributors

When you touch:
- **Rust assertion lifter** → `test-rust` + `coretests-invariants` must update (re-pin the discharged count)
- **Python kit** → `test-python` must pass; if you change canonical JCS output, `conformance` must re-pass
- **IR types** → all gates may shift (CID changes upstream); coretests-invariants re-pin mandatory
- **Discharge/solver integration** → `teeth_asymmetry_discharge_guard` + `coretests-invariants` (false_discharges check)
- **Witness resolution** → `test-showcases` + self-attest (binary CID changes if libsugar logic touched)

**The golden rule:** If your change moves unclassified/discharged/refused counts, update the JSON, run the gate, prove the sweep output matches, and document why in the `note` field. No squishy "close enough"; the gate is exact.
