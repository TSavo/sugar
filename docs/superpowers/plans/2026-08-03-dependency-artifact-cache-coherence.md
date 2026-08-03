# Dependency Artifact Cache Construction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rehydrate dependency-artifact cache inputs through the one lawful graph constructor, making independent cached graph fields unrepresentable.

**Architecture:** Disable direct field allocation, route distribution and stdlib input variants through one constructor, and persist only primitive distribution file inputs in `dep-graph-v4`. Cache refusal invalidates one seat and executes the existing authenticated miss path.

**Tech Stack:** Python 3.12, frozen dataclasses, pickle cache, logging, pytest.

## Global Constraints

- No separate coherence predicate over `artifact_kind` and `distribution_name`.
- Cache v4 stores exactly schema and primitive recorded-file inputs.
- The miss path must perform real authenticated reconstruction; never return an empty or default graph.
- Lawful graph fields and artifact CID remain unchanged.
- The 94 off-population rows are not attributed to this defect.
- No battleaxe, census, pandas walk, or broad pytest run.

---

### Task 1: Prove the missing construction boundary

**Files:**
- Test: `implementations/python/sugar-lift-python-source/tests/test_dependency_artifact_cache_authority.py`

**Interfaces:**
- Consumes: current direct `DependencyArtifactGraph(...)` field initializer.
- Produces: red constructor and poisoned-cache teeth.

- [x] Write a direct-allocation tooth whose caught exception type must be named `DependencyArtifactConstructionError`.
- [x] Write a poisoned-v4 tooth that wraps and executes the real `_read_recorded_installation`, then asserts a non-empty rebuilt distribution graph, exact-seat invalidation evidence, and a clean replacement seat.
- [x] Run the two teeth unpiped; require failures for the missing construction boundary and the cache projection path, not collection or census errors.

### Task 2: Install one graph construction path

**Files:**
- Modify: `implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/dependency_artifact.py`

**Interfaces:**
- Consumes: closed distribution/stdlib input variants containing authenticated files and diagnostic paths.
- Produces: `_construct_from_authenticated_inputs(...) -> DependencyArtifactGraph` and named `DependencyArtifactConstructionError` for direct allocation.

- [x] Disable the dataclass-generated public initializer and make direct field allocation raise `DependencyArtifactConstructionError`.
- [x] Add closed distribution and stdlib input variants.
- [x] Move METADATA identity, module projection, CID derivation, and final allocation into `_construct_from_authenticated_inputs`.
- [x] Route live distribution and stdlib intake through that method without altering lawful output fields.
- [x] Run the constructor tooth unpiped and require green.

### Task 3: Persist and rehydrate inputs only

**Files:**
- Modify: `implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/dependency_artifact.py`
- Test: `implementations/python/sugar-lift-python-source/tests/test_dependency_artifact_cache_authority.py`

**Interfaces:**
- Consumes: primitive v4 file rows.
- Produces: constructed graph or visible exact-seat refusal returning `None`.

- [x] Write v4 seats with only `schema` and primitive `files` rows.
- [x] Require exact payload and file-row keys; construct every `AuthenticatedArtifactFileV1` before graph construction.
- [x] Preserve visible refusal, exact-seat invalidation, and requested-vs-derived CID authentication.
- [x] Run constructor, coherent-hit, poisoned-seat, and v3-successor teeth unpiped and require green.

### Task 4: Verify, publish, and open the PR

**Files:**
- Verify all files above.

**Interfaces:**
- Consumes: complete corrected diff based on `dfdd436b2c5d5c757a48019c62f06df04372c6ed`.
- Produces: pushed corrected branch and draft PR to main.

- [x] Run the full cache-authority file locally and selected real stdlib constructor consumers, unpiped.
- [ ] Run Black check and `git diff --check`.
- [ ] Commit only the four scoped files.
- [ ] Push a corrected branch without overwriting the superseded remote history.
- [ ] Open a draft PR with root cause, invariant, red/green evidence, exact test scope, and the explicit nonclaim about 94 rows.
