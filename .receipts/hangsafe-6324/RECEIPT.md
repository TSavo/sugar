# #6324 — a partition is not an exponent

Every number here is read off a file in this directory. Nothing is inferred.

## What was measured, and how

`desugar_repro.py` is the bounded reproducer: the census's per-file body
(`open_source_file_for_construction` -> `fn.sugar()` -> `DesugarAxis.measure`)
plus a hard per-file SIGALRM deadline, so the first file that crosses is NAMED
with the stack captured **in the interrupted frame** instead of taking the run
down. The desugar half is load-bearing — a `fn.sugar()`-only sweep reports a
FALSE ZERO here.

Counters travel with every timing, because **wall time alone cannot separate
"more work" from "same work, slower."** Arm population (`exitset.arms_in_max`,
`arms_in_sum`, `pairwise_upper_bound`) is reported apart from normalization
work (`normalize_calls`), so a faster normalizer can never hide exponential
arm growth.

All runs: battleaxe, 32 cores, native as `tsavo`, under the host-wide heavy
measurement lease at `/var/tmp/sugar-heavy-measurement.lease`. That is the one
lease file every native measurement on this host contends on; the
`/home/runner/.cache/sugar/binaries/...` default is the per-container path and
does not exist here. Load is recorded with every timing.

Corpus: pandas 3.0.3, 1421 files, `corpusCid` identical to the `a02ebbe3e`
census.

## Three-file reproducer

| file | `a02ebbe3e` (`base.json`) | `a4eade69a` (`head.json`) | this branch (`three.json`) |
| --- | --- | --- | --- |
| `core/arrays/arrow/array.py` | 10.06s measured | **timeout 302.23s** | 2.80s measured |
| `core/reshape/pivot.py` | 5.98s measured | **timeout 300.56s** | 19.94s measured |
| `tests/extension/test_arrow.py` | 148.26s measured | **timeout 303.38s** | 4.67s measured |
| `R(timeout)` | 0 | **3** | **0** |

`arrow900.json` is `tests/extension/test_arrow.py` alone at a 900s deadline
during a loaded window (load 16-25): 42.51s, measured. It is here because an
intermediate run of that file crossed 300s entirely inside
`open_source_file_for_construction` -> dependency-artifact authentication, with
**every ExitSet counter at zero** — the load phase under contention, not the
arm explosion. Kept on the record rather than discarded.

## Arm population — the mechanism, not the clock

`exitset.arms_in_max`, the widest single `normalize` call:

| file | `a02ebbe3e` | `a4eade69a` | this branch |
| --- | --- | --- | --- |
| `core/arrays/arrow/array.py` | 230 | 436 | 10 |
| `core/reshape/pivot.py` | 0 | 1,304 | 0 |
| `tests/extension/test_arrow.py` | 0 | **131,364** | 2 |

`exitset.pairwise_upper_bound`:

| file | `a02ebbe3e` | `a4eade69a` | this branch |
| --- | --- | --- | --- |
| `core/arrays/arrow/array.py` | 118,472 | 64,823,682 | 3,294 |
| `core/reshape/pivot.py` | 343 | 105,745,446 | 1,894 |
| `tests/extension/test_arrow.py` | 2,050 | **8,946,911,919** | 4,335 |

`exitset.normalize_calls` on `core/reshape/pivot.py`: 735 -> 442,529 -> 18,418.

Two to five orders of magnitude more WORK, not the same work more slowly.

`head.json`'s `arm_construction_sites` carries the live SIGALRM stacks. Two
seats, both reached through `ExitSet.sequence`:

1. `sugar/if_exp_sugar.py:_join_arms` -> `ExitSet.union` -> `normalize`
2. `sugar/collection_sugar.py:_reduce_into` -> `and_then` -> `sequence`

## Full corpus census at this branch

`run_census_fix.sh` / `measured.sh` / `rows-fix.jsonl` / `board-fix.json`.
`run-meta.txt` records `ROWS_DURABLE=1421`, `LEASE_WRAPPER_EXIT=0`,
`FINAL_STATUS=completed/zero-findings`. The measured section REFUSES rather
than let a killed or partial run be banked as a zero: no `=== SUMMARY ===`
block, a vanished instrument tree, or fewer than 1421 durable rows each VOID
the run.

| axis | `a4eade69a` | this branch | delta |
| --- | --- | --- | --- |
| `R(timeout)` | 3 | **0** | **-3** |
| `terminalStatus.completed` | 1418 | **1421** | +3 |
| `R_construction` | 5,040 | 5,088 | +48 |
| `R_desugar` | 8,962 | 9,008 | +46 |
| `desugarConstructionPanics` | 1,184 | 1,194 | +10 |
| `desugarDefects` | 38 | 51 | +13 |

The `+48 / +46 / +10` are the three formerly-timed-out files contributing rows
they previously ABSORBED. The `a4eade69a` board's other axes were lower bounds
over 1418/1421; this one is complete over 1421/1421.

## #6319's 369-row drain: verified preserved, family by family

| desugar-defect family | `a4eade69a` | this branch |
| --- | --- | --- |
| `ContractConditionalConstructionV1` TypeError | 32 | **32** |
| `BindingStateWireGap` | 2 | **2** |
| `'ExitSet' has no attribute 'value'` | 2 | **2** |
| `util/_exceptions.py` TypeError | 1 | **1** |
| `ExitSetFactoringGap` | 1 | **14** |
| total | 38 | 51 |

Every #6319 family is byte-identical. The entire +13 is one family:
`ExitSetFactoringGap`, the preserved loud refusal, firing more often because
more completed faces now pass through `factor_completed`. Each row is a named
gap carrying owner, both guards, why the collapse would lose an outcome, and
the fix. It is tracked as its own axis in #6344 with the retirement path the
gap message already states — a stronger exclusivity proof, never a weaker gate
and never a materialized product.

No panic was converted back into a refusal; no detector was weakened; no test
was skipped or deleted; no red floor was suppressed.
