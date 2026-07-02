# MementoPool Typed-Member Campaign - IDD Plan

> **For agentic workers:** This is a CAMPAIGN plan, not an implementation patch. Do not start the storage migration from this document's branch. The MemberKind rung (#3054) has re-merged; dispatch the migration one measured slice at a time from current main. Instruments come before drains, every slice is red-first, and every behavior claim must be backed by RSS, audit, and byte-compat evidence.

**Goal:** Migrate `MementoPool` member storage from raw `serde_json::Value` envelope trees to typed member values, while preserving the verifier's proof/report JSON byte-for-byte and keeping every anchoring, signature, CID, and proof API refusal intact. The win is substrate memory: the pool should stop retaining a raw JSON tree for every member after the member has already earned its way through the proof graph boundary.

**Decision of record (T, 2026-07-02):** Do this as a ratcheted verifier-pipeline campaign, not as a single heroic PR. The pool type change is the center, but the risk is in the consumers. Each consumer family gets its own red-first slice, and each slice must prove both that it removed raw member-envelope dependence and that it did not move user-visible proof semantics.

## Foundations already laid

The campaign leans on three completed ladder rungs:

| Foundation | What it gives this campaign | How slices use it |
|---|---|---|
| `MementoCid` (#3052) | Pool keys and cross-pool references are parsed before lookup. | Typed members stay keyed by `MementoCid`; no slice reintroduces raw CID strings as lookup keys. |
| `AnchoredMember` (#3051) | There is one production constructor for "this member was recomputed, signature-checked, and accepted." | The storage migration changes what an anchored member yields to the pool, not whether anchoring runs. Raw insertion remains test-only. |
| `MemberKind` (#3054) | Member-kind branching is an exhaustive enum instead of string matching. | Per-kind consumer slices match on typed kind, never on wire strings. |

The proof graph stays the ingress authority. `ProofGraph` still owns catalog decoding, canonical bytes, and member lookup. This campaign changes verifier pool retention and downstream access, not the proof graph's on-disk or in-memory catalog format.

## Current measured shape

This plan was drafted while #3054 was being re-merged and then rebased after the replacement landed. Slice 1 still refreshes this table from live main before recording the first `R(raw-pool-member-access)` vector.

| Surface | Current shape | Target shape |
|---|---|---|
| Pool storage | `MementoPool::mementos: BTreeMap<MementoCid, Json>` | `BTreeMap<MementoCid, Arc<Member>>` or a small typed pool wrapper with no retained raw JSON envelope tree. |
| Pool ingress | `MementoPool::insert(AnchoredMember)` stores `(MementoCid, Json)` from `AnchoredMember::into_parts`. | `AnchoredMember` still gates ingress, then yields typed member storage and the typed key. |
| Test fixtures | `insert_unanchored_for_tests` is cfg(test) and loud. | Remains cfg(test), but feeds typed fixture values or a named test-only wrapper. |
| Proof API audit | Guards proof catalog side-door reads and writes. | Gains a raw-pool-member axis before migration starts. |
| RSS floor | `tools/perf/verify-rss.sh` and the RSS smoke gate are live. | Every storage-changing slice records before/after RSS; perf claims without numbers do not count. |
| JSON/report output | Current reports are the compatibility contract. | Byte-identical unless a slice explicitly stops for a soundness finding. |

## Campaign law

1. **Instrument before changing storage.** Slice 1 extends `proof_api_audit` to report raw verifier pool member access. The audit must name every current offender and the replacement accessor shape before the pool type changes.
2. **Red-first every slice.** A compile failure from changing a type is an acceptable red-first transcript. So is an audit row that names a raw pool read. A green-by-accident migration is not acceptable.
3. **Anchoring is sacred.** Do not change CID recomputation, JCS canonicalization, signature verification, or `ProofGraph` catalog validation. `AnchoredMember` remains the only production way into the pool.
4. **Typed storage is not typed semantics drift.** The verifier's reports, proof loading decisions, obligation verdicts, and refusal paths must remain byte-compatible unless the slice uncovers a genuine pre-existing soundness bug. If that happens, stop and file or dispatch the soundness issue explicitly.
5. **Ratchets move in the same PR.** A slice that removes raw pool reads also tightens the audit expectation. No slice may widen the proof API allowlist just to pass.
6. **Perf evidence is local and repeatable.** RSS and Dhat numbers are taken on the same box, same synthetic fixture, same command shape, before and after the slice.

## Instruments

### Instrument A - proof API raw-pool audit

Extend `sugar-cli/tests/proof_api_audit.rs` with a new axis for verifier-pool member access. It should report production code that:

- Reads `pool.mementos` values as `serde_json::Value`.
- Calls envelope-shape helpers such as `member_kind`, `member_body`, or `member_field` on values reached from the pool.
- Branches on wire member-kind strings downstream of the pool.
- Reconstructs proof-member shape by JSON pointer instead of using typed accessors.

The audit should exempt the proof-envelope owner crate, serde/Display boundaries, and cfg(test) fixture helpers. The initial PR for this instrument records the current `R(raw-pool-member-access)` vector and the replacement path for each row.

### Instrument B - RSS floor and Dhat attribution

Every storage-changing slice records the same fixture before and after the change. Run the final `verify-rss.sh` line three times per side when making a perf claim:

```bash
cd implementations/rust
cargo build -p sugar-cli --bin sugar -p sugar-ir-compiler-smt-lib --bin sugar-ir-smt-lib
cargo run -p sugar-cli --example synthetic_rss_fixture -- /tmp/sugar-rss-synthetic-120 120 --compiler target/debug/sugar-ir-smt-lib
cd ../..
tools/perf/verify-rss.sh --project-root /tmp/sugar-rss-synthetic-120 --sugar implementations/rust/target/debug/sugar --label <slice> -- --quiet
```

When the slice changes retained member storage, also run a Dhat sample with `--features dhat-heap` to show whether `serde_json::Value` member-envelope frames moved in the expected direction. The RSS floor is a guardrail, not a marketing number: if the memory result is flat, the slice can still land if it reduced architectural risk and did not regress the floor.

### Instrument C - byte compatibility

For each implementation slice, build a baseline binary from that slice's base commit, run the same verify/report fixture with the baseline and changed binaries, and compare emitted JSON by `cmp` plus SHA. This is the acceptance bar for consumers that serialize reports.

### Instrument D - structural grep

Each slice includes a structural proof in the PR body:

```bash
rg -n 'pool\.mementos|member_kind\(|member_body\(|member_field\(|"/envelope/|"/header/|"/body/"' implementations/rust
```

The PR lists remaining hits and classifies them as owner-crate boundary, cfg(test) fixture, raw IR formula data, or future-slice debt.

## Ratchet vector

| Signal | Starts as | Target |
|---|---|---|
| `R(pool-json-storage)` | 1 architectural offender: pool stores raw member envelope JSON. | 0 after the storage shell slice. |
| `R(raw-pool-member-access)` | Measured by Slice 1. | 0 at campaign close. |
| `R(member-kind-string-branching)` | 0 after #3054 re-merge. | Must stay 0. |
| `R(production-unanchored-insert)` | 0 after #3051. | Must stay 0. |
| `R(byte-drift)` | 0. | Must stay 0 unless a separate soundness issue is filed and accepted. |
| `R(RSS-regression)` | Green under the armed floor. | Must stay green; expected delta is lower retained heap after the storage slice. |

## Slices

### Slice 0 - Plan PR

Land this document only. No storage code, no audit code, and no migration.

Exit: plan reviewed and merged as "Part 1 of #3041 (migration plan)".

### Slice 1 - Audit and measurement instrument

Add the raw-pool-member axis to `proof_api_audit`. Run it red against current main and pin the `R(raw-pool-member-access)` vector. Record a fresh RSS baseline and one Dhat attribution run on the synthetic fixture.

Likely offenders to classify, not fix in this slice:

- Callsite enumeration and target resolution.
- Consistency/runner candidate collection.
- Report and witness-report rendering.
- Bridge and effect-site indexing in the load path.
- Test fixture pools that intentionally bypass production anchoring.

Exit: the audit names every production raw-pool member reader and points at a typed accessor or slice owner.

### Slice 2 - Storage shell and load ingress

Change the pool's member value type from raw `Json` to a typed member value. The exact storage wrapper is chosen in the slice, but it must satisfy:

- Key remains `MementoCid`.
- Production insertion still requires `AnchoredMember`.
- The pool does not retain the raw member envelope JSON tree.
- Test-only unanchored insertion remains cfg(test) and loudly named.
- Temporary compatibility accessors, if needed, are private and counted by the audit.

The red-first transcript is the compile failure caused by flipping the pool value type. The green condition is that `load_all_proofs` constructs the typed pool and all current tests pass via temporary compatibility where needed.

Exit: `R(pool-json-storage)=0`, `R(production-unanchored-insert)=0`, byte-compatible verifier output, RSS/Dhat recorded.

### Slice 3 - Load-time indexes and bridge maps

Move load-time indexing off raw envelope JSON:

- Contract bodyCid validation reads typed contract data.
- Bridge indexes use typed bridge/member fields.
- Effect-site annotations and opacity indexes use typed fields.
- Name/body CID indexes preserve the same values and ordering.
- Class-shape and formula payloads remain raw IR/formula data where no typed member model owns them yet; classify those explicitly.

Exit: no load-path JSON-pointer or wire-kind branching remains outside proof-envelope boundaries.

### Slice 4 - Callsite enumeration and target resolution

Migrate the high-fanout verifier consumers:

- `enumerate_callsites` builds `CallSite` from typed members.
- Target resolution and bridge followups use typed accessors.
- Any `BridgePin` or `MemberKind` branching stays exhaustive.

This slice is where most behavior-risk lives, so it gets positive/twin tests for representative contract, bridge, self-pinned, and missing-target cases.

Exit: callsite rows and `.verify.json` are byte-identical; raw-pool audit rows for enumeration/target resolution are removed.

### Slice 5 - Consistency, runner, and solver-facing consumers

Migrate consistency planning and runner handoff surfaces:

- Candidate obligations and member metadata come from typed pool accessors.
- Solver-facing structs do not recover raw member shape from JSON.
- Existing `SolverSeat` exhaustiveness remains intact.

If another in-flight SolverSeat slice owns a file, defer the conflicting hunk and keep the audit row named rather than merging blind.

Exit: sugar-verifier tests green, audit rows for runner/consistency removed, report JSON byte-compatible.

### Slice 6 - Reports, witnesses, CLI surfaces, and fixtures

Finish presentation and test-helper consumers:

- Report and witness-report renderers use typed member data.
- CLI commands that inspect loaded proofs use typed pool accessors.
- Fixture helpers either construct anchored members or use `insert_unanchored_for_tests`.
- No production code calls test-only insertion.

Exit: `proof_api_audit` raw-pool-member axis reaches stable zero; sugar-proof-envelope, sugar-verifier, and sugar-cli suites are green; RSS floor remains green.

### Slice 7 - Compatibility cleanup

Delete temporary compatibility accessors and reduce any remaining raw JSON references to clearly owned boundaries:

- Proof graph/catalog decoding.
- Serde/Display boundaries.
- Raw IR formula or class-shape payloads not represented by typed member structs.
- cfg(test) fixtures.

Exit: structural grep and proof_api_audit agree on zero production raw member-envelope reads from the verifier pool.

## Byte-compat bar

Every implementation slice must include:

1. Baseline binary built from the slice base.
2. Changed binary built from the slice branch.
3. Same fixture path, same command, same environment.
4. `cmp` and SHA evidence for emitted verify/report JSON.

If the bytes differ, the slice stops. Either prove the difference is a deliberate soundness fix and file/link that issue, or repair the migration until the bytes match.

## Anti-goals

- Do not change proof catalog wire format.
- Do not change CID format, hash computation, JCS canonicalization, or signature verification.
- Do not soften loader refusals or add legacy-shape allowlists.
- Do not migrate all consumers in one PR.
- Do not treat RSS improvement as a substitute for byte compatibility or audit zero.
- Do not remove existing corruption pins just because `AnchoredMember` centralizes the check; list redundancies only after the constructor proves them.
- Do not type raw IR formula payloads under this issue unless a consumer slice proves that it is required for member-envelope storage.

## Campaign closure

The campaign closes when:

1. `MementoPool` no longer stores raw JSON member-envelope trees.
2. Production pool insertion is still anchored-only.
3. `proof_api_audit` reports zero production raw-pool member access.
4. `MemberKind` string branching remains zero.
5. RSS floor is green and after-storage measurements are recorded.
6. Verifier/report JSON is byte-compatible across the migration.
7. `sugar-proof-envelope`, `sugar-verifier`, and `sugar-cli` pass their full package suites on the final slice.
