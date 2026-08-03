# Java Showcase Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire exactly 19 Java showcases with reversible, conserved, per-shard RETIRED testimony while preserving every in-scope failure.

**Architecture:** A source-controlled JSON manifest is the only retirement authority. A focused Python owner validates and partitions the existing Makefile roster; the Makefile executes only active rows while writing a conserved scope receipt, and CI embeds that receipt in each shard body.

**Tech Stack:** Python 3.12, GNU Make and shell, GitHub Actions YAML, JSON.

## Global Constraints

- Retirement must be a distinct outcome, never pass or fail.
- Exactly 19 Java paths are retired for reason `out of scope per scope ruling - Java`.
- Per shard, retired plus executed must equal enrolled.
- Removing a manifest entry must make the showcase execute again.
- Active Python-path and Rust CLI failures must retain their nonzero exit.

---

### Task 1: Pin the retirement authority and discrimination law

**Files:**
- Create: `.github/showcase-retirements.json`
- Create: `tools/showcase_scope.py`
- Create: `tests/test_showcase_retirement.py`

**Interfaces:**
- Consumes: the exact ordered `SHOWCASE_RUNS` roster and shard count/index.
- Produces: a validated JSON partition with `enrolled`, `executed`, and `retired` rows.

- [ ] Write tests for exact Java membership, named refusal arms, reversible removal, non-retired execution selection, and per-shard 5/4/5/5 conservation.
- [ ] Run the focused test and confirm it fails because the owner and manifest do not exist.
- [ ] Add the exact manifest and minimal validator/partitioner.
- [ ] Run the focused test and confirm every discrimination arm passes.

### Task 2: Integrate the partition into test-showcases

**Files:**
- Modify: `Makefile:396-566`
- Modify: `tests/test_showcase_retirement.py`

**Interfaces:**
- Consumes: `tools/showcase_scope.py partition` output.
- Produces: loud RETIRED lines, no execution for retired paths, unchanged execution and exit status for active paths, and a per-shard scope receipt.

- [ ] Add a harness tooth proving retired bodies do not run, active bodies do run and can fail, and deleting one retirement row reactivates that body.
- [ ] Run the harness tooth and confirm the current flat runner fails the retirement assertions.
- [ ] Route the runner through the partition and preserve the existing active failure path.
- [ ] Re-run the harness tooth and confirm conservation and both execution arms.

### Task 3: Seal retirement testimony in the CI shard body

**Files:**
- Modify: `.github/workflows/ci.yml:512-550`
- Modify: `tests/test_showcase_retirement.py`
- Modify: `tools/showcase_shard_attendance.py`

**Interfaces:**
- Consumes: the per-shard scope receipt and active `exit_code`.
- Produces: `showcase-shard-body.json` with distinct retired/executed rows and fail-closed conservation validation.

- [ ] Add artifact tests for distinct RETIRED state, exact reason, 5/4/5/5 distribution, conservation refusal, and active-red propagation.
- [ ] Run the focused tests and confirm the current body schema fails them.
- [ ] Embed and validate the scope receipt without changing active exit-code semantics.
- [ ] Re-run focused tests plus workflow YAML parsing and dispatchability checks.

### Task 4: Verify and publish

**Files:**
- Verify all files changed by Tasks 1-3.

- [ ] Run the full focused retirement contract.
- [ ] Run `git diff --check` and parse every workflow YAML document.
- [ ] Inspect the diff for exactly 19 Java rows, zero deletions, and zero non-Java retirement entries.
- [ ] Commit the scoped change, push the branch, and open the PR with predicted A2 movement and explicit non-claims.
- [ ] After landing, report observed per-shard A1/A2 and attendance; do not claim green while active findings remain.
