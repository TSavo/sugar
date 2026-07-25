# Classification of the 16 sugar-source-tree reds

Measured on main `fce604d25` (2026-07-25): **16 failed, 485 passed**.

Judgment: **live law vs retired-architecture assumption**. Nobody had named this
distinction while the suite was quoted as "16 pre-existing."

## Summary

| Class | Count | Action |
|-------|------:|--------|
| Retired-architecture test expectations | 10 | Rewrite to live LoopRecurrence / typed Incomplete / class-field dig-cue |
| Live law — test helper API lag (parameter contracts) | 6 | Rewrite helpers to project coordinates without illegal `UniverseValue.post` |
| Live law — product false green | 0 confirmed after rewrites | (while True NormalExhaustion is intentional fuel exhaustion under live_loop) |
| Golden pin drift | 1 | Re-pin quirks corpus |

---

## Cluster A — Loop unroll (retired: factory-era SugarNotWritten / linear fold)

| Test | Old expectation | Live shape |
|------|-----------------|------------|
| `test_while_unroll::test_while_true_stays_loud` | `SugarNotWritten` at `sugar()` | `LoopRecurrenceSugar` + `NormalExhaustion` face (fuel; see `test_live_loop_post_projection`) |
| `test_while_unroll::test_symbolic_condition_stays_loud` | `SugarNotWritten` | Same — symbolic while projects false-test exhaustion |
| `test_for_unroll::test_symbolic_assert_only_loop_is_a_universal` | `invs()[0].kind == forall` | Loop recurrence + step equation, not factory FOL emit into invs |
| `test_for_unroll::test_symbolic_carried_accumulator_is_a_fold_coordinate` | `.value.post()` → `py.fold.Add` | `ExitSet` + `python:loop.post_binding` / recurrence |
| `test_for_unroll::test_accumulator_referencing_assert_stays_loud` | `SugarNotWritten` | Constructs under loop recurrence |
| `test_range_unroll::test_symbolic_range_bound_is_a_universal` | `forall` inv | Same as symbolic for |

**Authority:** `test_live_loop_post_projection.py`, `live_loop_construction.py`.

**Action:** Rewrite tests to assert `LoopRecurrenceSugar` / live post faces. Do not
restore factory SugarNotWritten.

---

## Cluster B — Comprehension "undecidable stays loud" (retired refusal shape)

| Test | Old | Live |
|------|-----|------|
| `test_listcomp_dissolves::test_undecidable_filtered_comprehension_stays_loud` | `SugarNotWritten` | `Complete` with `py.listcomp` + `python:loop.filter_guard` |

**Action:** Assert the typed filter-guard coordinate (honest residual), not silence.

---

## Cluster C — Exit builds (retired: refuse raise of lambda)

| Test | Old | Live |
|------|-----|------|
| `test_exit_builds::test_unwritten_raised_child_stays_loud` | `SugarNotWritten` at `sugar()` | `Incomplete(RaiseEffect)` with constructed `LambdaCallable` |

**Action:** Assert Incomplete raise of lambda (more honest than construction refuse).

---

## Cluster D — Class body Assign (retired: unsupported member)

| Test | Old | Live |
|------|-----|------|
| `test_source_visible_constructor_door::test_unknown_class_member_stays_typed_loud` | `SugarNotWritten` match Assign | `ClassDefinitionSugar` with field `call:make_state` (`body=None` dig cue) |

**Action:** Assert opaque call cue on free name, not unsupported Assign.

---

## Cluster E — Coordinate projection via `UniverseValue.post` (live law; helper lag)

| Tests | Failure |
|-------|---------|
| `test_computed_call` ×4 | `ConstructionPanic`: pending parameter contract demands |
| `test_slice_sugar` ×2 | Same |

**Live law:** `UniverseValue.post` must not project over undischarged
`ContractConditionalConstructionV1` (linker resume exclusive).

**Meaning is present:** call/slice terms sit on the conditional construction
`.value` (ReturnValue → CallSiteValue.term). Tests wrongly assumed bare
`.desugar().value.post()` without contracts.

**Action:** Project term from pending conditional value (or discharged post only).

---

## Cluster F — Golden corpus

| Test | Failure |
|------|---------|
| `test_corpus::test_pinned_golden_corpus_reproduces_byte_identically` | Module CID/span drift |

**Action:** Re-pin after intentional encoder/NodeShape changes (or regenerate golden).

---

## Not in this classification pass

- Integration twin `and_exit(exit_es, disposition=…)` — wait for #6257 merge.
- Try over ExitSet (#6242) — build ok, merge gated on post-Merkle census.
