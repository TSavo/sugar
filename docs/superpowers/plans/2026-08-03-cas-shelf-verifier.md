# CAS Shelf Verifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make filesystem-CAS verification accept byte-identical cross-OS artifacts while preserving source and payload refusals and naming read-only recovery honestly.

**Architecture:** Keep the existing local artifact verifier strict. Add a shelf-only verifier that owns payload-address and stable-manifest authentication, and carry an explicit read-only transport fact from the battleaxe Docker mount to recovery.

**Tech Stack:** Bash, embedded Python 3, BLAKE3, SHA-256, Docker bind mounts.

## Global Constraints

- Never delete, chmod, or rewrite the live battleaxe shelf cell.
- Wrong source stamp and wrong payload remain loud, named refusals.
- Local target/cache verification remains strict over Cargo and Rust identity.
- `cargo -Vv` host OS residue is not filesystem-CAS payload identity.

---

### Task 1: Pin the shelf-verification arms

**Files:**
- Create: `tests/sugarbin_shelf_manifest_identity.sh`
- Modify: `tests/sugarbin_shelf_content_addressed.sh`

**Interfaces:**
- Consumes: `bin/sugarbin`, a temporary shelf, fixed source stamp, and fake Cargo/Rust executables.
- Produces: end-to-end cross-OS, wrong-source, wrong-payload, and local-strict testimony.

- [ ] **Step 1: Write the failing contract**

Build and publish a temporary executable with Cargo OS `Ubuntu 24.4`. Clear
only the temporary target/cache, change the fake Cargo OS to `Debian 12`, and
resolve with builds disabled. Assert a shelf hit and zero build calls. Plant a
wrong manifest `sourceStamp` and a wrong gzipped payload in separate copies and
assert their distinct named crimes.

- [ ] **Step 2: Verify RED**

Run `bash tests/sugarbin_shelf_manifest_identity.sh "$PWD"`.

Expected: the cross-OS arm exits nonzero after `artifact identity mismatch:
cargo`; the present recovery reason is also too broad.

- [ ] **Step 3: Pin the one-door call**

Extend `tests/sugarbin_shelf_content_addressed.sh` to require the shelf-only
verifier and forbid the filesystem-shelf candidate from using the strict local
verifier.

### Task 2: Split CAS membership from local build identity

**Files:**
- Modify: `bin/sugarbin`
- Test: `tests/sugarbin_shelf_manifest_identity.sh`
- Test: `tests/sugarbin_shelf_content_addressed.sh`

**Interfaces:**
- Consumes: candidate path, source stamp, build identity, CAS key, and cell.
- Produces: `verify_filesystem_shelf_artifact` with named status and crimes.

- [ ] **Step 1: Implement the minimal verifier**

Recompute BLAKE3, compare the CAS address, parse the manifest, verify SHA-256
and stable fields, and emit `crime=shelf-manifest-parse-failed` or
`crime=shelf-manifest-identity-mismatch field=<field>`. Exclude only diagnostic
`rustc` and `cargo` strings. Leave `verify_artifact_manifest` unchanged.

- [ ] **Step 2: Route only filesystem-shelf reads through it**

Replace the duplicated address check and strict verifier call in
`pull_from_filesystem_shelf`. On refusal, remove only temporary materialization
and enter the existing recovery path.

- [ ] **Step 3: Verify GREEN**

Run all three commands:

```bash
bash tests/sugarbin_shelf_manifest_identity.sh "$PWD"
bash tests/sugarbin_shelf_content_addressed.sh "$PWD"
bash tests/sugarbin_artifact_manifest.sh "$PWD"
```

Expected: all pass; the final command proves local target/cache strictness.

### Task 3: Name read-only recovery separately

**Files:**
- Modify: `bin/lib/sugar-bx.sh`
- Modify: `bin/sugarbin`
- Test: `tests/sugarbin_shelf_manifest_identity.sh`
- Test: `tests/sugarbin_shelf_peer_evictable.sh`

**Interfaces:**
- Consumes: `SUGAR_BINARY_SHELF_READ_ONLY=1` from a read-only Docker bind.
- Produces: `crime=read-only-shelf-recovery`; writable unevictability retains `crime=unevictable-shelf-cell`.

- [ ] **Step 1: Add the failing read-only arm**

Invoke recovery with `SUGAR_BINARY_SHELF_READ_ONLY=1` and a planted mismatch.
Assert the read-only crime and that the cell remains. Invoke without the fact
against a non-removable fixture and assert the ownership/mode crime remains.

- [ ] **Step 2: Carry mount authority and implement refusal**

Set the environment fact in both battleaxe Docker paths whenever the shelf
mount is read-only, and `0` only for the existing publication-enabled path.
Check it before attempting eviction.

- [ ] **Step 3: Verify GREEN and hygiene**

Run:

```bash
bash tests/sugarbin_shelf_manifest_identity.sh "$PWD"
bash tests/sugarbin_shelf_peer_evictable.sh "$PWD"
bash -n bin/sugarbin bin/lib/sugar-bx.sh tests/sugarbin_shelf_manifest_identity.sh
git diff --check
```

Expected: every command exits zero.

### Task 4: Bank and publish

**Files:**
- Modify: only the files named above and the design/plan documents.

**Interfaces:**
- Consumes: focused receipts and current `origin/main`.
- Produces: one clean branch and pull request linked to #7260.

- [ ] **Step 1: Commit the focused repair**

Record all focused receipts and explicit non-claims in the commit message.

- [ ] **Step 2: Preflight against current main**

Verify remote head, parent/merge-base, branch-tree scope, zero deletions, no
foreign commits, and the sealed closing-account digest.

- [ ] **Step 3: Push and open the PR**

State that no live shelf cell was mutated, broad battleaxe/package scale is
unmeasured until landing, and #6982 moved payload addressing but left
build-specific identity in the CAS manifest.

