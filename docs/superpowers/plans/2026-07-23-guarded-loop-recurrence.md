# Guarded Loop Recurrence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct symbolic loops and comprehensions as guarded `LoopConstructionV1` recurrences whose exact completed faces flow downstream through `LoopProjectedBinding` in `BindingEntryV1`.

**Architecture:** A source-tree recurrence projector seals the existing loop graph and returns runtime projected binding states; block substitution sequences those states before downstream loads. Comprehensions reuse that projector as nested guarded flat-maps while concrete dissolution remains a proven optimization.

**Tech Stack:** Python 3.12 source tree and lift tests, closed JCS/BLAKE3 loop wire, ExitSet semantics, pytest, battleaxe wrappers.

## Global Constraints

- Symbolic loops are guarded recurrences, never universals, bounded semantic unrolls, or callbacks.
- Use the existing `LoopConstructionV1` and the sole runtime `BindingEntryV1` carrier.
- Never fabricate a value from a CID or authorize a binding by target spelling.
- Unsupported symbolic/unbounded cases remain typed-loud.
- Heavy builds and measurements run on battleaxe only.
- Rebase onto current `origin/main` before review; push an open PR and do not merge it.

---

### Task 1: Executable lane instrument

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd/guarded_loop_recurrence.py`
- Create: `implementations/python/sugar-lift-py-tests/tests/test_guarded_loop_recurrence_idd.py`

**Interfaces:**
- Produces: `GuardedLoopRecurrenceFinding`, `scan_guarded_loop_recurrence(root: Path) -> tuple[...]`, and a report with numeric `R` plus offender locations and replacement shapes.

- [ ] Write tests planting each forbidden side door and a lawful projected recurrence.
- [ ] Run the focused pytest and confirm failures because the scanner/report is absent.
- [ ] Implement structural recognition of universal/fold loop substitution, ambient maps, CID-derived values, and missing downstream projection.
- [ ] Run the focused pytest; require exact offender sets and `R`.
- [ ] Commit the red instrument and its initial current-main measurement.

### Task 2: Runtime projected binding state

**Files:**
- Modify: `implementations/python/sugar-source-tree/src/sugar_source_tree/binding_state.py`
- Modify: `implementations/python/sugar-source-tree/tests/test_runtime_binding_entry_v1.py`

**Interfaces:**
- Produces: `LoopProjectedCompletedFace` and `LoopProjectedBinding`, admitted by `BindingState` and sealed only from authenticated completed-face states.

- [ ] Add truthful and lying tests for exact face retention, target mismatch, missing testimony, and CID-as-value rejection.
- [ ] Run the focused pytest and confirm the new types are absent.
- [ ] Add the two frozen runtime state types without adding another entry/map model.
- [ ] Extend sealing/substitution joins to preserve both guarded faces or raise `BindingStateWireGap`.
- [ ] Run the focused binding tests and the IDD instrument.
- [ ] Commit the runtime carrier change.

### Task 3: Loop recurrence projection and temporal sequencing

**Files:**
- Create: `implementations/python/sugar-source-tree/src/sugar_source_tree/loop_recurrence.py`
- Modify: `implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py`
- Create: `implementations/python/sugar-source-tree/tests/test_guarded_loop_recurrence.py`

**Interfaces:**
- Consumes: existing `LoopConstructionV1`, ExitSet/control-effect testimony, and `LoopProjectedBinding`.
- Produces: `project_loop_recurrence(loop, scope, trace_builder) -> LoopRecurrenceProjection` with constructed loop sugar, completed faces, outward halted faces, and post-bindings.

- [ ] Add red twins for continue latch, break completion, exhaustion-only else, halted propagation, both guarded faces, and downstream load consumption.
- [ ] Confirm the focused suite fails on the current universal/fold path.
- [ ] Build the loop graph from authenticated pre-state, operation, body ExitSet, and exact control-effect routing.
- [ ] Replace symbolic loop `substitution_binding` synthesis with recurrence projection and sequence it in `_substitute_body` before the tail.
- [ ] Keep `ForUniversalSugar` restricted to early-exit-free state-free facts and keep unsupported graphs typed-loud.
- [ ] Run focused recurrence, binding, wire, sole-path, and loop-control tests.
- [ ] Commit symbolic loop recurrence construction.

### Task 4: Comprehension nested flat-map recurrence

**Files:**
- Modify: `implementations/python/sugar-source-tree/src/sugar_source_tree/loop_recurrence.py`
- Modify: `implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py`
- Create: `implementations/python/sugar-source-tree/tests/test_comprehension_guarded_recurrence.py`

**Interfaces:**
- Produces: `project_comprehension_recurrence(node, scope) -> ComprehensionRecurrenceProjection` using nested generator recurrence, filter guard faces, collection-builder testimony, and explicit exhaustion.

- [ ] Add red truthful/lying twins for two-generator flat-map ordering, filter true/false routing, dict key/value construction, generator laziness, and symbolic typed-loud residue.
- [ ] Confirm failures arise from missing recurrence construction.
- [ ] Reuse the loop projector for each generator; route false filters to the owning latch and true filters inward.
- [ ] Feed authenticated yielded testimony to list/set/dict/generator builders and require exhaustion to close.
- [ ] Preserve the existing proven finite dissolution path as an optimization.
- [ ] Run focused comprehension, recurrence, and IDD tests.
- [ ] Commit comprehension recurrence construction.

### Task 5: Battleaxe measurement, rebase, and publication

**Files:**
- Modify only if receipts expose a lane-owned defect.

**Interfaces:**
- Produces: complete base/head numeric receipts and an open GitHub PR.

- [ ] Run formatting and focused Python checks; run heavy compile/census commands through battleaxe only.
- [ ] Record discovered/completed, `R`, timeout, non-native-red, auditor-error, side-door, and panic-catch counts for base and head.
- [ ] Fetch and rebase onto the latest `origin/main`.
- [ ] Re-run the exact focused and battleaxe commands after rebase.
- [ ] Inspect the complete diff, commit as `T Savo <evilgenius@nefariousplan.com>`, and push with tracking.
- [ ] Open a draft PR targeting `main`, leave it unmerged, and report the PR number plus honest numeric delta.
