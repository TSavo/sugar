# Solve is API-driven — pre-protocol disk-read collapse plan

**Date:** 2026-07-09  
**Issue:** Part of #3809 (never closes/fixes)  
**Status:** Plan locked for incremental PRs. #3981 deleted `warm_solve` but left
`pool_only_inputs` and eight disk side-channels inside cold solve. That is not done.

## Why (not “reconcile two paths”)

There is no cold/warm **solve**. The enumeration RPC protocol (#3809) delivers
facts as content-addressed mementos. The pool is a CID→memento map. Solve does
**not** read the project filesystem to find facts — faces (CLI, LSP) do that as
**clients** and feed the one solve API.

`pool_only_inputs` and the old `warm_solve` door only existed to say “skip those
filesystem reads.” The protocol already made those reads unnecessary for claim
facts. Remaining disk touches inside solve are **pre-protocol vestiges**.

### Target shape

```
CLI face                              LSP face
  plan / config / mint / fold           resident pool + overlay mint
  read disk as CLIENT                   (already API-shaped)
        │                                        │
        ▼                                        ▼
   feed: pool + SolveInputs (mementos / typed cfg)
        │                                        │
        └────────────────┬───────────────────────┘
                         ▼
                  ONE solve API
             (zero project FS by end of series)
```

- **Solve receives; it does not fetch.**
- Neither CLI nor LSP has a privileged path *inside* solve.
- When every input is client-fed, `pool_only_inputs` has nothing to decide and is **deleted**.
- “Warm” is not a path; it is the pool already containing the CID.

### End-state invariants

1. One solve over a client-fed pool + typed inputs.
2. Zero project FS inside solve (no WalkDir / `exists` / `read_dir` / config open / cache_dir / runs write).
3. Scope/membership = memento in pool (role + locus on memento), never disk.
4. CLI and LSP both thin clients of that API.
5. Byte-identical verdict rows face-for-face.
6. Battleaxe witness corpus: paste actual `55 passed` line in each PR.

---

## The eight disk-reads — move plan

| # | Disk-read inside solve (today) | How it moves | New protocol verb? |
|---|--------------------------------|--------------|--------------------|
| **1** | **Input artifact CID walk** — `discover_input_artifact_cids`: WalkDir + read `*.proof` under `project_root` / `extra_projects` / `extra_proof_files` (stamps proof-run header CIDs) | **CLI-client-fed as pool (+ `extra_proofs` / plan CIDs).** Always use `discover_input_artifact_cids_from_pool` (already exists). `load_pool` leaves solve; face loads or folds, then feeds. **Trivial** once cold entry is pure feed. | **No** |
| **2** | **link-bundle / plugin-registry discovery** — `discover_named_artifact_cid` for `link-bundle.json` / `plugin-registry.json` (proof-run header only) | **CLI-client-fed as addressed run inputs** (same shape as `PlanArtifactInput`: optional CID/bytes). Solve stamps what it was fed; absent → honest placeholder (today’s warm behavior). **Trivial.** | **No** |
| **3** | **`*.call-edges.json` WalkDir** — `call_edge_loader::load_call_edge_files` | **Trivial-delete** on protocol path. Edges come from **pool bridges + `enumerate_callsites`** (API already). Do not re-open FS if a project only has sidecars — that is a **lift/bridge emission gap**, not a solve FS API. | **No** (if bridges cover production). If sidecar-only production exists → **lift gap for T**, not a new solve verb. |
| **4** | **config.toml signers/solvers** — `load_trusted_implication_signers`; `SolversConfig::load(project_root)` when cfg empty | **CLI-client-fed as `trusted_implication_signers` + `solvers_config` / `legacy_z3_fallback`.** CLI already reads config for signers; must also load `[solvers]` and set `solvers_config`. Delete both disk loaders from `Runner` / `build_plan_and_registry`. **Trivial.** | **No** |
| **5** | **`Path::exists` locus preference + scope** — consumer-vs-vendor squiggle; `locus_in_scope` cold `exists()` | **Driven by pool/API metadata already on mementos:** always speaker role (Consumer beats Vendor); scope = path-prefix / relative locus vs client-fed scope. **Trivial-delete** of `exists()` branches once faces stamp `SpeakerRole` on load. Incomplete stamping = face bug, not solve FS. | **No** |
| **6** | **Witness `read_dir(.sugar/lift)`** — `find_witness_resolvers` cold branch | **CLI-client-fed as typed `WitnessDischargeContext.resolvers`** (CLI `discharge_config` already builds this). **Trivial-delete** of cold `read_dir`. (Oracle subprocess CWD via client-fed `project_dir` is not fact-fetch WalkDir.) | **No** |
| **7** | **Tier-2 implication cache** — `try_tier2(cache_dir)` read; `mint_and_cache` write under `cache_dir` | **CLI-client-fed as implication mementos in the pool** (or `extra_proofs`); solve looks up by property hash in-pool only. Newly minted implications returned on solve **result**; face may persist for next feed. Delete `cache_dir` I/O from discharge. **Medium** (request/response feed, not WalkDir). | **No new kit/enumerate verb.** Existing `ImplicationMemento` kind. Needs clear solve **request/response feed path** (design-shaped API surface work, not a new RPC). |
| **8** | **`.sugar/runs` write** — `write_proof_run_bundle(..., persist_to_disk)` | **Trivial-delete inside solve:** always seal in memory. **CLI client** writes durable receipt if the face wants it. | **No** |

### FLAG summary — new protocol verb?

| # | FLAG |
|---|------|
| 1, 2, 4, 5, 6, 8 | Safe to cut as CLI-client-fed or trivial-delete. **No new verb.** |
| 3 | Cut FS; if production is sidecar-only without bridges → **lift gap for T**, not a new solve verb. |
| 7 | **No new RPC verb**, but needs **API feed/sink for implication mementos** (existing memento kind). Medium; may pause for T if feed shape is disputed. |

**Nothing in the eight requires inventing a new enumeration/testimony/source RPC.** Do **not** invent verbs to keep FS inside solve.

### Related (not one of the eight, same law)

| Item | Disposition |
|------|-------------|
| `load_pool` / `load_all_proofs::run` inside `solve_project` | Must leave solve (face loads/folds). Structural with #1. |
| `compiler_registry::build(project_root)` in `Runner::new` | Prefer `new_with_compilers` only; CLI already builds from plan. |
| `project_root` on config | Scope / display / witness CWD label fed by client — not a fetch root inside solve. |

---

## PR order (one input-source per PR)

Each PR: byte-identical verdict rows; battleaxe corpus with **actual** `55 passed` line pasted; title  
`Part of #3809: solve is API-driven - <input-source> moves to the CLI client`  
(or equivalent for trivial-delete). Never closes/fixes #3809. Author: `T Savo <evilgenius@nefariousplan.com>`.

| Order | Input source | Title fragment | Risk |
|-------|--------------|----------------|------|
| **A** | #4 config signers/solvers | `config signers/solvers moves to the CLI client` | Low — CLI almost done |
| **B** | #1 input CIDs + `load_pool` leaves solve | `input CIDs + load_pool leave solve` | Medium structure |
| **C** | #2 named run inputs | `named run inputs (link-bundle / plugin-registry)` | Low |
| **D** | #3 call-edges FS delete | `call-edges FS delete (pool bridges only)` | Low if no sidecar-only gap |
| **E** | #5 locus/scope | `locus/scope speaker+prefix only` | Medium — stamping discipline |
| **F** | #6 witness resolvers | `witness resolvers typed-only` | Low |
| **G** | #7 tier-2 | `tier-2 via pool-fed implications` | Medium |
| **H** | #8 proof-run write | `proof-run seal memory-only; CLI persists` | Low |
| **I** | flag deletion | `delete pool_only_inputs` | Final — only when A–H green |

**Rule:** Only cut CLI-client-fed or trivial-delete items. Do **not** invent work around anything T must design; flag #7 feed shape if blocked.

---

## PR A scope (this cut)

**#4 only:** Solve must not open `.sugar/config.toml` for signers or `[solvers]`.

- Delete cold branches in `Runner::new_with_compilers` / `build_plan_and_registry` that call `load_trusted_implication_signers` and `SolversConfig::load`.
- CLI (`cmd_prove`, `cmd_verify`) reads config as client and sets `trusted_implication_signers` + `solvers_config` (signers already partly set).
- LSP builds the same fields when constructing resident context.
- `SolversConfig::load` remains a **client** helper, not a solve-path side-channel.
- Leave the other seven for later PRs; leave `pool_only_inputs` until I.

---

## Receipt template (every PR)

```
cargo test -p sugar-compiler --test prove_from_kit   # or focused suite
bin/bpytest tests/test_witness_verify.py tests/test_sugar_witness_instruments.py tests/test_witness_oracle.py
# paste: ======================== 55 passed in … ========================
```
