# Four-axis pandas census — a02ebbe3e

**Measured commit: `a02ebbe3ed37d6d7cdd6b3108ba1da09504ba0d4`** (stated directly
here regardless of tooling emission; `environment-identity.json` is not the
authority for this run and no authenticated suite identity exists for it yet).

**Evidence status: completed, commit-pinned, provisional.**

| | |
|---|---|
| corpus | pandas 3.0.3, 1421 `*.py` files |
| corpusCid | `22196d8904677ce92cdfbc0e0c0049ad7075ebc6ce56fc0336e3e6a51382cdd9` |
| host | battleaxe, 32 cores, load 6.81 → 15.04 during the measured section |
| lease | BX lease held, class `pandas-four-axis-census-bx`, `completed/zero-findings` |
| rows | `rows-bx.jsonl`, 1421 rows, wrapper exit 0 |

## Conservation

**Every corpus file measured exactly once. 1421 rows, 1421 distinct keys, 1421
corpus files, one corpus CID.**

Reconciliation method: **`(corpusCid, idx, rel, sha256)`**. The sha256 of the
file's bytes authenticates the thing measured, so no reconciliation can pair
two different files that happened to sort into the same slot. Position is not
identity, and count is not conservation.

The 0–121 prefix was re-measured rather than resumed: no durable per-occurrence
rows for it exist anywhere reachable (the Mac, the branches, battleaxe — only
the stale d94f67a31 board). Reconciling by authenticated occurrence identity
against rows that cannot be read is not reconciliation. Measuring 0–1420 makes
conservation checkable instead of asserted, at a cost of 122 files.

## Terminal status, each separately

| quantity | value |
|---|---|
| `R(timeout)` | **0** |
| crashes | **0** |
| malformed rows | **0** |
| duplicate rows | **0** |
| cross-file occurrence-key collisions | **0** |
| contamination (`No module named 'sugar`) | **0** |
| completed | **1421 / 1421** |

`R(timeout) = 0` corpus-wide, at a 300s per-file bound, on an uncontended box.
Index 121 `core/generic.py` — the file that used to eat the deadline —
**completed**. This is the confirmation the assertion-With drain was waiting on.

## The four axes, never merged

| axis | a02ebbe3e |
|---|---|
| `R_construction` | **5088** |
| `R_desugar` | **8596** |
| `desugarConstructionPanics` | **960** |
| `desugarDefects` | **407** |
| file-level construction panics | 0 |

`R_construction` families: With 5021, Try 33, Assign 25, AnnAssign 6, Constant 3.

## `R_desugar` split — the raw figure overstates the work by ~147x

Derived from the **authenticated occurrence-key prefix**, not family names.

| bucket | prefix | count |
|---|---|---|
| 1. correctly constructed effects — **accounted semantics, not work** | `site:` / `occurrence:` / `occurrence-cid:` | **8538** |
| 2. explicit incomplete obligations — owed | `boundary:` | **0** |
| 3. construction panics/gaps — owed | `desugar-call:` | **58** |
| 4. implementation defects | (own axis) | 407 |

**Owed desugar work is 58, not 8596.**

Bucket 1 owners: SubscriptStoreRuntimeEffect 3209, AttributeStoreRuntimeEffect
2335, RaiseEffect 1546, NameErrorEffect 1071, SequenceUnpackRuntimeEffect 270,
SubscriptDeleteRuntimeEffect 41, PowerRuntimeEffect 33, BitwiseXorRuntimeEffect
13, UnaryPlusRuntimeEffect 9, SubtractRuntimeEffect 6,
SubscriptResultRuntimeEffect 4, MatrixMultiplyRuntimeEffect 1.

Bucket 3 owners: `YieldSuspensionSugar.desugar` 32, `YieldFromSugar.desugar` 17,
`matches_raise_effect` 8, `ClassDefinitionSugar.desugar` 1.

## ΔR on the conserved set

Both runs reached terminal `completed` on all 1421 files — the baseline carried
no per-file deadline and recorded no crashes or file-level panics. **So the
conserved set is the whole corpus and the newly-measurable category is EMPTY.**
It is non-empty only against a run that carried a per-file deadline; against
this baseline `core/generic.py` was already producing rows (75 occurrences, 20
panics, 8 defects), so none of its rows are "newly visible" here.

Occurrence keys embed the corpus's absolute path and the two runs read the
corpus from different roots, so both sides are normalized to `<CORPUS>/…`
before comparison. The corpus is proven identical by CID, so the substitution
loses nothing.

| axis | d94f67a31 | a02ebbe3e | Δ | removed | added | unchanged |
|---|---|---|---|---|---|---|
| `R_construction` | 5088 | 5088 | **0** | 0 | 0 | 5088 |
| `R_desugar` | 8624 | 8596 | −28 | 1087 | 1059 | 7537 |
| `desugarConstructionPanics` | 1074 | 960 | −114 | 1004 | 890 | 70 |
| `desugarDefects` | 295 | 407 | **+112** | 3 | 115 | 292 |

`R_construction` is identity-level unchanged: 5088 of 5088 keys the same, zero
added, zero removed. #6315/#6316/#6317 touched no construction recognizer.

### What the raw −28 on `R_desugar` hides

The split moved even though the total barely did:

| bucket | d94f67a31 | a02ebbe3e | Δ |
|---|---|---|---|
| accounted semantics | 7483 | 8538 | **+1055** |
| owed (`desugar-call:`) | 1141 | 58 | **−1083** |

**Owed desugar work fell 95%.** Removed: `DynamicUnpackAssignSugar.desugar`
1084 refusals. Added: SequenceUnpackRuntimeEffect 270, RaiseEffect 253,
AttributeStoreRuntimeEffect 239, SubscriptStoreRuntimeEffect 159,
NameErrorEffect 131, SubscriptDeleteRuntimeEffect 6. That is #6316 converting a
soft typed refusal into real reduced semantics wherever the RHS floor can
answer the demand.

## Attribution

**#6315** — *Spread: compose operand ExitSets as factors instead of their
product (#6309)*, commit `8563b0dd0`. This is why `R(timeout) = 0` is
measurable at all: the factored `ExitSet.factor_completed` took the
`core/generic.py` reproducer from a 300s wall to a completed file, arm
population `6 → 264` at arity 2→8 down to `3 → 9`. Its one visible residue on
this board is a single `ExitSetFactoringGap` defect row —
`factor_completed cannot factor a completed face whose arms are not provably
exclusive` (owner `SymbolicValue / StringValue`) — a named, owned gap, not a
silent fallback.

**#6316** — *DynamicUnpackAssign: submit the unpack demand to the RHS value*,
commit `8e8e7c59a`. The largest mover on the board, in **both** directions, and
it must be read as one trade, not two facts:

- it drained **1084** `DynamicUnpackAssignSugar.desugar` refusals from the owed
  bucket and produced ~1059 accounted semantic effects in their place;
- it introduced **822 `DynamicUnpackAssignSugar` construction panics**, now
  86% of the whole panic axis (960).

This is a rung climbed on the enforcement ladder, not a regression: where the
RHS floor can answer, you now get reduced meaning; where it cannot, you get a
loud owned panic naming the missing floor instead of a soft refusal that banked
as measured. The 822 are the honest frontier the refusal was hiding, and they
are the largest single drainable family on this board.

Corroboration: the 1/6 stride sample at `e6d688d3c` that measured 20 panics in
236 files was taken **before** #6316 landed (`e6d688d3c` is an ancestor of
`a02ebbe3e` and contains no #6316). Its ~120-corpus-wide implication and this
run's 960 differ by ~840, which is the 822 new family plus churn. The two
measurements agree; they were taken across the commit that created the family.

**#6317** — *Floor: complex field arithmetic, uncapped sequence repetition,
term-bearing membership*, commit `a02ebbe3e`, the pin itself. Visible as
drained panic owners: `contains` 705 and `attribute` 219 removed, alongside
`add` 34, `guarded` 26, `ListValue.multiply` 19. The membership work is
partially residual — `ListValue.contains` 26, `TupleValue.contains` 18,
`StringValue.contains` 10, `SetValue.contains` 9 remain, now named per
receiver type rather than as one undifferentiated `contains`.

### The one axis that went the wrong way

`desugarDefects` **295 → 407 (+112)**, 115 added and only 3 removed. These are
implementation defects, not frontier:

| n | defect |
|---|---|
| 32 | `AttributeError: 'SourceFragment' object has no attribute 'compare_left'` |
| 22 | `NotImplementedError: a conditional-expression arm that reduces to an effect is not lifted yet` |
| 21 | `TypeError: ContractConditionalConstructionV1` |
| 17 | `AttributeError: 'ContractConditionalConstructionV1' object has no attribute 'guarded'` |
| 13 | `AttributeError: 'ExitSet' object has no attribute 'value'` |
| 9 | `AssertionError: ` (bare) |
| 1 | `ExitSetFactoringGap` (see #6315 above) |

`a4eade69a` (#6319, *An arm that halts is not an arm that is missing: ten
desugar defect families*) landed on main **after** this pin and targets exactly
this axis. It works — see below.

## Head measurement — a4eade69a (#6319)

A second full-corpus census at current main, same corpus CID, same harness,
1421/1421 rows, conserved. **It was not lease-wrapped** — it is a supporting
attribution measurement, not the primary board. Box load ~10 on 32 cores.

| axis | a02ebbe3e | a4eade69a | Δ |
|---|---|---|---|
| `R_construction` | 5088 | 5040 | −48 |
| `R_desugar` | 8596 | 8962 | +366 |
| `desugarConstructionPanics` | 960 | 1184 | +224 |
| `desugarDefects` | **407** | **38** | **−369** |
| `R(timeout)` | **0** | **3** | **+3** |

#6319 did what it says: **defects 407 → 38, a 91% drain**, and the drained
defects reappear as loud typed panics (+224: `guarded` 77, `IfExpSugar._join`
53, `collection ListValue` 50, `collection build` 32). An arm that halts is now
recorded as halting rather than as an `AttributeError`. `R_desugar`'s +366 is
entirely accounted semantics (8538 → 8904); the owed bucket is **58 at both
commits**, unmoved.

### Head regressed `R(timeout)` 0 → 3

Three files complete at `a02ebbe3e` and exceed the 300s bound at `a4eade69a`:

- idx 69 `core/arrays/arrow/array.py`
- idx 184 `core/reshape/pivot.py`
- idx 509 `tests/extension/test_arrow.py`

The box was at load ~10 on 32 cores, so this is not the contention artifact
that would appear on a loaded machine. Each timeout row is an **unmeasured
file** that also absorbs every panic and defect row it would have produced — so
the head figures for the other three axes are, strictly, lower bounds over
1418/1421 files, while the `a02ebbe3e` board is complete over 1421/1421.

## Fresh With partition

5021 With construction-gap sites, **0 unresolved**:

| bucket | sites |
|---|---|
| assertion / effect-boundary | **4125** |
| resource / protocol | **811** |
| unclassified | **85** |

The 4125 reproduces exactly at this pin. Top unclassified heads: `ctx` 6,
`rewrite_exception` 5, `tm.maybe_produces_warning` 4, `activated_tracemalloc`
4, `handle_data` 3, `reader` 3, `tm.set_locale` 3, `tm.with_csv_dialect` 3.

## Owner-ranked residuals

Panic axis (960): `DynamicUnpackAssignSugar` 822, `ListValue.contains` 26,
`TupleValue.contains` 18, `ground_index_error` 15, `add` 11,
`StringValue.contains` 10, `attribute` 10, `SetValue.contains` 9, `guarded` 7,
`RuntimeEffect` 6, `multiply` 6, `bitwise_and` 5, `subtract` 4, `bitwise_or` 2,
`ground_type_error` 2, then singletons.

One panic row carries a raw `<SourceFragment '…/tests/indexes/period/test_period.py' …>`
as its **owner** instead of an owner name. That is an instrument-hygiene defect
in the panic's own testimony, not a corpus finding: an owner field should name
an owner.

## The previous `timeouts = 0` was UNMEASURABLE, not measured-zero

This correction belongs in the record. `sugar_lift_py_tests.census` is one
process over the whole corpus: no slicing, no per-file deadline, no checkpoint.
**It had no deadline to cross.** So it could honestly print `timeouts = 0`
while `core/generic.py` hung, and a kill lost every row it had measured.

That is the same structural defect as the `fn.sugar()`-only false zero on the
desugar axis: **an instrument incapable of seeing the thing it reports as
zero.** A zero from an instrument with no boundary is not evidence of absence.

`four_axis_resume.py` is landed here as part of the receipt, not as scaffolding,
so the next census inherits a boundary: per-file child isolation, a hard
per-file deadline, a JSONL checkpoint keyed by
`(corpusCid, idx, rel, sha256)`, the desugar door through
`DesugarAxis.measure`, and the exact `sorted(root.rglob("*.py"))` order so
indices stay comparable across runs.

## #6320 — reproduced, and it is a DOOR difference, not a file difference

Per-phase probe on `core/generic.py` (index 121) at `a4eade69a`, each phase
under its own `SIGALRM` bound (`phase_probe.py`):

| phase | door | seconds |
|---|---|---|
| open | `SourceFile.from_path` — **what `census.py` calls** | **0.46** |
| open | `open_source_file_for_construction(..., populate_derived=True)` — the reproducer | **258.46** |
| construction | `fn.sugar()` × 223 functions | 3.58 |
| desugar | `DesugarAxis.measure` | 1.97 |

Same file, same commit, same process: **560x between the two open doors.** It
did not cross 300s at load ~10–14, but 258.46s is within 14% of the bound, so
whether it exceeds 300s is load-dependent; 258s is the real quantity.

**The census does not pass `populate_derived`.** It occurs in exactly two
places: `lift_rpc.py:200` (the parameter, defaulting `True`) and
`scripts/control_effect_recensus.py:271` (the only caller that passes it). So
#6315's arm-population wall and this open-phase wall are two different walls
behind two different doors, and the census never enters the slow one —
`core/generic.py` completes in 4.96s at `a02ebbe3e` and 6.41s at `a4eade69a`,
223/223 functions, 0 construction gaps.

`control_effect_recensus` calls the slow door **per file**, which is what any
control/effect census over this corpus is paying.

## Lease: `/var/tmp` did not serialize, and that is a defect in these two runs

`heavy_measurement_lease.py`'s `DEFAULT_LEASE_PATH` is
`/home/runner/.cache/sugar/binaries/.sugar-heavy-measurement.lease` — correct
**inside a runner container**. These runs are ssh-direct as `tsavo`, where
`/home/runner/.cache` does not exist, so they used `/var/tmp`, which the
module's own comment records as per-container on battleaxe and therefore
non-serializing.

`docker inspect` gives the host side of the bind mount:

```
/home/tsavo/.cache/sugar/binaries -> /home/runner/.cache/sugar/binaries
```

Taking **that** file blocks correctly: the owner at the time was
`class=python-sole-construction-floors`, `githubRunId=30201463426`. So real
concurrent heavy work was running that `/var/tmp` was not excluding.

Consequences, stated precisely:

- The three counting axes are **unaffected** — ratios survive contention.
- `R(timeout) = 3` at `a4eade69a` is **in question** and is being re-measured
  under the correct lease (`rows-head.jsonl`, `run_census_head.sh`).
- `R(timeout) = 0` at `a02ebbe3e` **stands**. Contention can only *add* timeout
  rows, never remove them, so an unserialized zero is conservative.

## Honesty — what was NOT measured

- **Nothing on this board is a wall-time claim.** Load is recorded per row
  (6.81 → 15.04). Counter ratios survive contention; wall times do not.
- The **Mac** was at load average 458 on 16 cores when this work started. The
  measurement was moved to battleaxe for that reason, after proving the corpus
  byte-identical by CID and the instrument identical on a 6-file slice across
  the python3.12/3.14 gap. `R(timeout)` is a wall-clock threshold and is the
  one axis contention destroys; measured at 30x oversubscription it would have
  manufactured timeout rows that look like product red and that silently
  absorb every row behind them.
- The a4eade69a head run is a **supporting attribution measurement and was not
  lease-wrapped**. The a02ebbe3e board is the primary result and was.
- No authenticated suite identity exists for this run; #6290 is merged but this
  census predates its authenticated rerun. Hence *provisional*.
- The old `d94f67a31` board is used **only** as the ΔR baseline over the
  conserved set. No number from it is quoted as current.

## Files

- `four_axis_resume.py` — per-file-isolated, resumable, sha-keyed harness
- `board.py` — renders this board; refuses (exit 1) when distinct keys ≠ 1421
- `delta.py` — conserved-set ΔR with occurrence-key path normalization
- `rows-bx.jsonl` — 1421 durable rows
- `board-a02ebbe3e.json`, `delta-d94f67a31-to-a02ebbe3e.json`
- `run_census_bx.sh`, `measured_bx.sh`, `run-meta-bx.txt`, `lease-record-bx.json`
