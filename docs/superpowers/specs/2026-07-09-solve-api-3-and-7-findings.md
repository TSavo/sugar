# Solve API-driven — findings for cuts #3 and #7

**Date:** 2026-07-09  
**Issue:** Part of #3809 (never closes/fixes)  
**Context:** `docs/superpowers/specs/2026-07-09-solve-api-driven-plan.md`  
**Landed before this note:** #4 config (#3983), #6 witness resolvers (#3985), #2 named inputs (#3987), #8 runs-seal (#3990), #5 locus/scope (#3992), #1 input CIDs (#3989)

---

## #3 call-edges — SIDECAR-ONLY production?

### Answer: **NO**

Production discharge does **not** rely on sidecar-only `*.call-edges.json`. Edges that matter for verdicts come from **pool bridges + `enumerate_callsites`**. The cold WalkDir is a pre-protocol vestige that only fills `report.call_edges` telemetry. → **Trivial-delete** of the cold WalkDir.

### What solve does today

In `runner.rs` (`run_with_proof_run_inner` and the older `run_with_tiers` path):

```text
call_edges =
  if pool_only_inputs { [] }
  else { call_edge_loader::load_call_edge_files(project_root) }  // WalkDir *.call-edges.json

obligations = process_call_edges(call_edges, pool)
  → only pushes ResolvedCallEdge into report.call_edges   // telemetry

callsites = enumerate_callsites::run(pool)               // actual discharge graph
```

**Discharge never reads the sidecar.** Verdicts are driven by mementos already in the client-fed pool (bridges indexed as `bridges_by_symbol` / related) plus `enumerate_callsites`.

### Evidence

| Check | Result |
|-------|--------|
| Tracked `*.call-edges.json` in git | **0** (`git ls-files '*call-edges*'` empty) |
| Warm / `pool_only_inputs` path | Already skips WalkDir; canary `trap.call-edges.json` in `prove_from_kit` proves canaries do not change warm verdict rows |
| Cold path use of `process_call_edges` | Only `report.call_edges` population |
| Real face discharge | `enumerate_callsites::run(&pool)` only |

### Java panama dual-write (not a counterexample)

`implementations/java/sugar-lift-java-tests/src/JavaPanamaFfmRpc.java`:

1. Kit RPC response includes `"callEdges":[...]` (protocol / lift path).
2. Also writes disk sidecar `java-panama-ffm.call-edges.json` with comment *"Sidecar for the verifier's call_edge_loader"*.

`examples/java-panama-bridge/run.sh` asserts that sidecar exists after mint as a **lifter emission receipt**, not as the sole solve fact source. That is face/lifter FS, not solve FS. Deleting solve’s WalkDir does not require inventing a new verb; mint may keep writing the sidecar for its own checks.

### Disposition for cut #3

- **Delete** cold `call_edge_loader::load_call_edge_files` use from solve discharge paths (always empty / never call).
- Edges for discharge: pool bridges + `enumerate_callsites` only.
- Optional later (not required for this cut): faces that want `report.call_edges` populated can rebuild from pool/enumerate; not discharge-critical.
- **Not** a lift/bridge emission gap for T.
- **Do not** delete `pool_only_inputs` in this cut.

---

## #7 tier-2 implication cache — request/response feed shape

**Status:** Design report only. **Do not implement until T confirms.**

### Today (mostly vestigial on real faces)

| Path | Behavior |
|------|----------|
| **Lookup** | `try_tier2(cache_dir, post_hash, pre_hash, trusted_signers)` → `read_dir(cache_dir)` + scan `*.proof` for implication whose `propertyHash = BLAKE3("implication:" \|\| post \|\| ":" \|\| pre)` + Ed25519 against `trusted_implication_signers` |
| **Mint** | On Tier-3 unsat: `mint_and_cache` → `create_dir_all` + write `{property_stem}-{prover}.proof` under `cache_dir` + queue `(cid, envelope)` into `minted_sink` → pool insert + stamp `output_artifact_cids` |
| **CLI** | Does **not** set `cache_dir` / `mint_seed` / `mint_producer_id` on `RunnerConfig` → production CLI already skips disk lookup and mint-to-disk |
| **Warm** | `pool_only_inputs` + `cache_dir = None` already skip both FS paths |

### Already in-pool (no FS) — reuse this

**Tier 0c** in `work_one`:

```text
pool.can_implies(post_hash, pre_hash)
  → ProvenDirect { memento_cid }
  → ProvenTransitive { path }
  → ProvenReflexive
  → Unknown
```

Scans pool members with `MemberKind::Implication` by `antecedentHash` / `consequentHash` (existing `ImplicationMemento` kind). No new kit/enumerate/testimony RPC verb.

Minted envelopes already go into the **local** pool during solve; only **CIDs** appear on the proof-run header as `output_artifact_cids`. Envelope **bytes** are not exported on `ProofRunArtifact` today — they die with the ephemeral pool. That is the feed/sink gap.

### Target shape (concrete enough to approve)

```text
REQUEST (client face → solve)              RESPONSE (solve → face)
─────────────────────────────────          ─────────────────────────────────
pool: MementoPool                          ProofRunArtifact {
  // includes Implication members            // existing fields...
  // face loaded from prior persist          report, stats, memento, stages,
  //   and/or prior solve sink                 bundle_cid, bundle_bytes, ...
extra_proofs: Vec<ProofBytes>                minted_implications: Vec<MintedImplication>,
  // alt channel: implication catalogs       // NEW sink — full bodies for re-feed
  // as bytes that load as implications    }

cfg.trusted_implication_signers: Vec<String>  // already client-fed (cut #4)
cfg.mint_seed: Option<[u8; 32]>               // optional mint authority
cfg.mint_producer_id: Option<String>          // stamped into metadata

// DELETE from discharge path:
//   cfg.cache_dir (no longer consulted)
//   try_tier2(...) FS read_dir / read
//   mint_and_cache(...) create_dir_all / write
```

### `MintedImplication` (proposed sink element)

```text
MintedImplication {
  cid: MementoCid,              // content-addressed identity
  envelope: Json | Vec<u8>,     // full ImplicationMemento body
}
```

Memento content (already minted by `mint_and_cache` / claim-envelope shape):

- **header:** `kind: "implication"`, `antecedentHash`, `consequentHash`, `propertyHash`, `bindingHash`, `verdict`, `inputCids`, slots/CIDs as today  
- **metadata:** `producedBy`, `prover`, `producerPubkey`, optional `solverInput`, …  
- **envelope:** `signer`, `signature`, `declaredAt`

Lookup key for discharge remains the **hash pair** (`antecedentHash` / `consequentHash`) via `pool.can_implies` / tier0c. `propertyHash` stays on the memento for identity/naming; it is not a separate FS index.

### Face loop (persist + re-feed)

1. **After solve:** if `minted_implications` is non-empty, the face **may** persist under its own store (e.g. `.sugar/cache/…`). That is **client FS**, not solve.
2. **Before next solve:** face loads those implication mementos into the pool (or via `extra_proofs`).
3. **Solve:** lookup only in-pool (tier0c / `can_implies`). Never `cache_dir`.
4. **Mint (optional):** when `mint_seed` + `mint_producer_id` are set and Tier-3 unsat fires, mint into the **result sink** (and insert into the in-run pool for same-run reuse). Do **not** require or write `cache_dir`.

### What gets deleted from discharge

| Delete | Location |
|--------|----------|
| `try_tier2` FS `read_dir` / `read` | `handshake.rs` use from `runner.rs` cold branch |
| `mint_and_cache` `create_dir_all` / `write` | `runner.rs` |
| `RunnerConfig.cache_dir` consulted on discharge | field may remain briefly unused, then remove when nothing sets it |
| Cold `if !cfg.pool_only_inputs` gates around tier-2 | collapse once #7 lands |

### Design choice for T (confirm before build)

| Option | Shape | Notes |
|--------|-------|-------|
| **A (recommended)** | Pool is the only feed. Export `minted_implications: Vec<(MementoCid, Json)>` (or `Vec<MintedImplication>`) on `ProofRunArtifact`. Mint when seed+producer set, without `cache_dir` gate. Delete all cache_dir I/O from discharge. | Matches “one feed”; no second channel |
| **B** | Also add `RunnerConfig.fed_implications: Vec<ProofBytes>` separate from pool/`extra_proofs` | Redundant if pool is the feed; only if you want a typed dedicated field |

**Recommend A.** No new protocol verb. Existing `ImplicationMemento` kind.

### Out of scope for #7 cut

- Deleting `pool_only_inputs` (final series cut only after #3 and #7 green).
- Inventing new enumeration/testimony/source RPC.

---

## Series remainder (not this note’s work)

| Cut | Status |
|-----|--------|
| #3 call-edges FS delete | Ready: trivial-delete (this findings → NO sidecar-only) |
| #7 tier-2 via pool-fed implications | Wait for T approval of shape A/B |
| Final: delete `pool_only_inputs` | Only after every FS branch is gone |

---

## Receipt template (any following PR)

```
cargo test -p sugar-compiler --test prove_from_kit
# paste DoD: FS=0, byte-identical=true

cd implementations/python/sugar-lift-py-tests && ../../../bin/bpytest \
  tests/test_witness_verify.py tests/test_sugar_witness_instruments.py tests/test_witness_oracle.py
# paste: ======================== 55 passed in … ========================
```
