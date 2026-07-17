# Loud-bounded-timeout classification for #4894 (2026-07-17)

## Battleaxe classification checkpoint

The classification replay moved from the contended local Mac to battleaxe.
Three remote shards run concurrently, while every shard remains sequential
internally.  The committed recensus records 293 timeouts but did not retain
their filename artifact.  Replaying the documented snapshot
`b4ee8c01228ba1e9ac1720d701d548fbb2861da6` with the closest available remote
runtime (CPython 3.14.3; the census used 3.14.4) reproduced 237 timeout
identities.  The other 56 remain an explicit identity-unavailable residual;
they are not counted as completed.

The append-only ledger currently contains 28 final rows:

| Verdict | Files |
|---|---:|
| `completes-at-bound` | 11 |
| `completes-with-panic` | 17 |
| `bare-exception` | 0 |
| `hang-at-max-bound` | 0 |
| **Reconstructed identities pending** | **209** |
| **Original identities unavailable** | **56** |

The three 60 → 120 → 300 second battleaxe shards remain in progress.  This
checkpoint is intentionally draft testimony: `28 + 209 + 56 = 293`, so no
timeout has been silently reclassified or removed from the conservation
account.

## Why this pass exists

The #4775/#4872 recensus
(`docs/python-corpus-fatal-recensus-4775-2026-07-17.md`) classified every
assertion-bearing NumPy+pandas file at a **10-second discovery bound**:

| Terminal at 10s | Files |
|---|---:|
| completed | 481 |
| typed `FactoryPanic` | 245 |
| bare exception | 13 |
| **provisional timeout** | **293** |
| crash/signal/transport | 0 |

`481 + 245 + 13 + 293 = 1,032`. Conservation held. The risk named in #4894 is
that as the typed 245 drain, the undifferentiated 293-timeout blob becomes the
next way the wall stays non-total. A loud timeout is honest only when it is a
host/bound artifact — not product non-termination wearing a stopwatch.

## Instrument

| Piece | Path |
|---|---|
| Classifier | `implementations/python/sugar-lift-py-tests/scripts/classify_loud_timeouts.py` |
| Child payload | reuses `corpus_fatal_triage.py` (same terminal taxonomy as #4775) |
| Focused tests | `implementations/python/sugar-lift-py-tests/tests/test_classify_loud_timeouts.py` |
| Append-only ledger | `docs/ledgers/loud-timeout-classification-4894.jsonl` |
| Summary JSON | `docs/ledgers/loud-timeout-classification-4894-summary.json` |
| First-shard seed | `docs/ledgers/loud-timeout-first-shard-seed-4894.txt` |

### Verdicts (every timeout gets one; never silently dropped)

| Verdict | Meaning | Next owner |
|---|---|---|
| `completes-at-bound` | Finished with IR at bound B (10s discovery was tight) | not wall panic mass; flag `perf_candidate` if B or elapsed >120s |
| `completes-with-panic` | Typed `FactoryPanic` once given time | dispatch via `factory_panic_fronts` / owner ranking |
| `bare-exception` | Untyped exception once finished | triage bare-exception lane |
| `hang-at-max-bound` | Still non-terminating at 300s | **real frontier**: lift must emit loud budget-exceeded terminal |
| `other:*` | crash/signal/transport | keep loud; never reclassify as complete |

### Cause classes (tag every final ledger row)

| Tag | Label | Meaning |
|---|---|---|
| **A** | bound-tight | `completes-at-bound` with elapsed/bound ≤120s (10s discovery was operational) |
| **B** | hidden-panic | `completes-with-panic` → typed FactoryPanic owner (dispatchable fatal) |
| **C** | perf-complete | `completes-at-bound` with elapsed or bound >120s |
| **D** | hang | `hang-at-max-bound` at 300s — product needs budget-exceeded terminal |
| **E** | bare | `bare-exception` after long work |

Intermediate `timeout-at-bound` and `other:*` stay loud under their own labels
(not A–E product-cause tags). Summary prints `cause_class_counts`,
`ranked_B_owners`, and residual R.

### Escalation bounds

`10s` (discovery) → `60s` → `120s` → `300s`. Single-lane sequential only.
Timeouts are never reclassified as complete without recording the successful
bound. No panic/refusal is weakened.

### Residual R axes

| Axis | Meaning |
|---|---|
| `R_timeout_blob_classified` | Files with a final ledger verdict (measured) |
| `R_unclassified_timeout_blob` | Pure-timeout seed rows still without a final verdict (or unscanned pending) |
| `hang_at_max_bound_count` / class **D** | Genuine non-termination mass at 300s |
| `R_residual` | `R_unclassified_timeout_blob + hang_at_max_bound_count` |
| `R_live_factory_panic_files` / class **B** | Panic rows recovered from the former timeout blob |
| `perf_candidate_count` / class **C** | Completes that needed >120s |

Instrument exit is **red** while `R_residual > 0`.

## Measurement boundary (this wave)

- Worktree: `fleet-issue-4894` / branch `fleet/issue-4894-w7`
- Python 3.14.4, NumPy 2.5.1, pandas 3.0.3
- Host: single-lane sequential child processes (`PYTHONFAULTHANDLER=1`)
- First shard: size-biased seed of 42 assertion-bearing files (known long
  runners ordered last) — live rediscovery at 10s shows many prior seed
  members no longer time out under current head/load (not blob mass)

## First-shard ledger (live; append-only)

Source of truth: `docs/ledgers/loud-timeout-classification-4894.jsonl`.

| File | Verdict | Class | Bound | Elapsed | Owner |
|---|---|---|---:|---:|---|
| `numpy/ma/tests/test_core.py` | completes-with-panic | **B** | 60s | ~30s | `FormatDunderCallSugar callsite receiver` |
| `pandas/tests/io/test_sql.py` | completes-with-panic | **B** | 300s | ~197s | `WithSugar manager result` |
| `pandas/tests/tools/test_to_datetime.py` | completes-with-panic | **B** | 120s | ~57s | `SequentialDigBody` |
| `pandas/tests/extension/test_arrow.py` | completes-with-panic | **B** | 60s | ~36s | `ConstructorCallSugar` |
| `pandas/tests/frame/test_constructors.py` | completes-with-panic | **B** | 60s | ~10s | `TemporalContext` |
| `pandas/tests/indexing/test_loc.py` | completes-with-panic | **B** | 60s | ~52s | `RuntimeEffect` |
| `pandas/tests/reshape/merge/test_merge_asof.py` | completes-with-panic | **B** | 60s | ~29s | `SequentialDigBody` |
| `pandas/tests/reshape/merge/test_merge.py` | completes-with-panic | **B** | 300s | ~177s | `RuntimeEffect` |

Several large seed members finished inside the 10s discovery bound under current
head (e.g. `numpy/_core/tests/test_multiarray.py`, `test_umath.py`) — discovery
misses, not timeout-blob mass.

### Cause-class counts (first shard so far)

| Class | Count | Notes |
|---|---:|---|
| A bound-tight | 0 | none yet |
| **B hidden-panic** | **8** | all recovered finals so far |
| C perf-complete | 0 | none yet (panics are not C) |
| D hang | 0 | `test_to_string` / `test_multi` still queued last |
| E bare | 0 | none yet |

### Residual R (measured)

| Axis | Count |
|---|---:|
| `R_timeout_blob_classified` | **8** |
| Recensus provisional residual (≈293 − classified) | **~285** (live rediscovery may differ) |
| Seed rows still unscanned / incomplete | continue single-lane resume |
| `hang_at_max_bound_count` (D) | **0** |
| `R_residual` (unclassified pure-timeout seed + D) | **> 0** — instrument stays red |

## Ranked recovered B owners (from timeout blob so far)

| Rank | Owner | Files | Dispatch issue |
|---:|---|---:|---|
| 1 | `RuntimeEffect` | **2** | #4922 |
| 2 | `SequentialDigBody` | **2** | #4921 |
| 3 | `ConstructorCallSugar` | **1** | #4922 |
| 4 | `FormatDunderCallSugar callsite receiver` | **1** | #4917 |
| 5 | `TemporalContext` | **1** | #4922 |
| 6 | `WithSugar manager result` | **1** | #4918 |

These owners were **invisible** to the #4775 typed ranking when the file timed
out at 10s before the panic terminal. Escalation surfaces them as ordinary
dispatchable construction mass.

## Dispatchable buckets

| Bucket | Pattern | Disposition |
|---|---|---|
| Recovered B — FormatDunderCallSugar / MaskedArray | Floor Projection missing body | **#4917** |
| Recovered B — WithSugar manager result | manager result construction | **#4918** |
| Recovered B — SequentialDigBody | sequential dig body (2 files) | **#4921** |
| Recovered B — ConstructorCallSugar / TemporalContext / RuntimeEffect | mixed first-shard singles (RuntimeEffect×2) | **#4922** (split when R grows) |
| PERF lane (C) | none yet | Open fatal-perf issue when count ≥1 with clear shape |
| Hang at 300s (D) | none yet; seed queues `pandas/tests/io/formats/test_to_string.py` and `pandas/tests/reshape/merge/test_multi.py` last | When confirmed: file **budget-exceeded product terminal** issue (do not invent soft RuntimeEffect) |

## How to continue (fix-forward)

```bash
# 1) Rediscover live timeout list at 10s (single lane — do not parallelize)
.venv-4894/bin/python implementations/python/sugar-lift-py-tests/scripts/classify_loud_timeouts.py \
  --discover-timeouts docs/ledgers/loud-timeout-discovery-10s-4894.json \
  --discovery-bound 10

# 2) Escalate only the pure timeout blob (resume-safe, append-only ledger)
.venv-4894/bin/python implementations/python/sugar-lift-py-tests/scripts/classify_loud_timeouts.py \
  --files-from docs/ledgers/loud-timeout-discovery-10s-4894.json \
  --skip-discovery \
  --escalation-bounds 60,120,300 \
  --resume \
  --ledger docs/ledgers/loud-timeout-classification-4894.jsonl \
  --summary docs/ledgers/loud-timeout-classification-4894-summary.json

# 2b) Or resume the first-shard seed (mixed discovery)
.venv-4894/bin/python implementations/python/sugar-lift-py-tests/scripts/classify_loud_timeouts.py \
  --files-from docs/ledgers/loud-timeout-first-shard-seed-4894.txt \
  --discovery-bound 10 \
  --escalation-bounds 60,120,300 \
  --resume \
  --ledger docs/ledgers/loud-timeout-classification-4894.jsonl \
  --summary docs/ledgers/loud-timeout-classification-4894-summary.json

# 3) Focused instrument
.venv-4894/bin/python -m pytest -q \
  implementations/python/sugar-lift-py-tests/tests/test_classify_loud_timeouts.py

# 4) Summarize residual R (pure timeout seed + --skip-discovery)
.venv-4894/bin/python implementations/python/sugar-lift-py-tests/scripts/classify_loud_timeouts.py \
  --summarize-only \
  --files-from docs/ledgers/loud-timeout-discovery-10s-4894.json \
  --skip-discovery \
  --ledger docs/ledgers/loud-timeout-classification-4894.jsonl \
  --summary docs/ledgers/loud-timeout-classification-4894-summary.json
```

## Floors preserved

- No panic/refusal weakened
- No timeout silently reclassified as complete/dropped
- No bound raised to invent green without recording the successful bound
- Wall conservation: silent = 0; hang remains explicit until product budget terminal exists
- Single-lane classification only (no parallel children)

## Predicted Epsilon R (this PR)

| Axis | Δ | Why |
|---|---:|---|
| cause-class instrument | 0 → executable A–E tags + residual R | classifier + tests |
| `R_timeout_blob_classified` | +8 (first shard) | all class B so far |
| typed panic owners recovered from blob | +6 families | ranked B owners |
| dispatch issues filed | +4 | #4917 #4918 #4921 #4922 |
| hang / perf product terminals | 0 | not yet confirmed at 300s hang / >120s complete-with-IR |
| panic/refusal floors | 0 | measurement only |

**Leave #4894 OPEN** while `R_residual > 0` (unclassified timeout blob and/or D hang).
