# Loud-bounded-timeout classification for #4894 (2026-07-17)

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

### Escalation bounds

`10s` (discovery) → `60s` → `120s` → `300s`. Single-lane sequential only.
Timeouts are never reclassified as complete without recording the successful
bound. No panic/refusal is weakened.

### Residual R axes

| Axis | Meaning |
|---|---|
| `R_timeout_blob_classified` | Files with a final ledger verdict (measured) |
| `R_unclassified_timeout_blob` / `R_pending` | Seed or pool rows still without a final verdict |
| `hang_at_max_bound_count` | Genuine non-termination mass at 300s |
| `R_live_factory_panic_files` | Panic rows recovered from the former timeout blob |
| `perf_candidate_count` | Completes that needed >120s |

Instrument exit is **red** while `R_pending + hang_at_max_bound_count > 0`.

## Measurement boundary (this wave)

- Worktree: `fleet-issue-4894` @ main base `9fe134453` (+ local instrument)
- Python 3.14.4, NumPy 2.5.1, pandas 3.0.3
- Host: single-lane sequential child processes (`PYTHONFAULTHANDLER=1`)
- First shard: size-biased seed of 42 assertion-bearing files (known 120s+
  hangers ordered last) to produce early evidence without monopolizing the
  multi-fleet host for a full 293×300s worst-case wall clock

## First-shard ledger (live; append-only)

Source of truth: `docs/ledgers/loud-timeout-classification-4894.jsonl`.

| File | Verdict | Bound | Owner / note |
|---|---|---:|---|
| `numpy/ma/tests/test_core.py` | **completes-with-panic** | 60s | `FormatDunderCallSugar callsite receiver` — Floor/Projection missing callsite body for `MaskedArray` |
| `numpy/_core/tests/test_multiarray.py` | not timeout at 10s | — | discovery miss under current head/load (not blob mass) |
| `numpy/_core/tests/test_umath.py` | not timeout at 10s | — | same |
| `numpy/lib/tests/test_function_base.py` | not timeout at 10s | — | same |
| `numpy/_core/tests/test_numeric.py` | not timeout at 10s | — | same |

### First-shard counts (at instrument PR time)

| Axis | Count |
|---|---:|
| Timeout-blob rows with final verdict | **1** |
| `completes-with-panic` | **1** |
| `completes-at-bound` | 0 |
| `hang-at-max-bound` | 0 |
| `bare-exception` | 0 |
| Seed scanned (incl. not-timeout) | 5+ (run in progress / residual) |
| Recensus provisional timeout residual R | **292** remaining of original 293 identity (live rediscovery may differ) |

## Ranked recovered panic owners (from timeout blob so far)

| Rank | Owner | Files | Representative |
|---:|---|---:|---|
| 1 | `FormatDunderCallSugar callsite receiver` | **1** | `numpy/ma/tests/test_core.py` |

This owner was **invisible** to the #4775 typed ranking because the file timed
out at 10s before the panic terminal. Escalation surfaces it as ordinary
dispatchable construction mass.

## Dispatchable buckets (filed when pattern is clear)

| Bucket | Pattern | Disposition |
|---|---|---|
| Recovered typed panic — FormatDunderCallSugar / MaskedArray callsite | Floor Projection missing body | Fold into live factory-panic dispatch (same ranking as #4775 owners); not a new timeout class |
| PERF lane (>120s completes) | none yet in ledger | Open separate fatal-perf issue when count ≥1 with clear shape |
| Hang at 300s | none yet; recensus sample named `pandas/tests/io/formats/test_to_string.py` and `pandas/tests/reshape/merge/test_multi.py` as 120s+ long runners | When confirmed at 300s: file budget-exceeded product terminal issue |

## How to continue (fix-forward)

```bash
# 1) Rediscover live timeout list at 10s (single lane)
.venv/bin/python implementations/python/sugar-lift-py-tests/scripts/classify_loud_timeouts.py \
  --discover-timeouts docs/ledgers/loud-timeout-discovery-10s-4894.json \
  --discovery-bound 10

# 2) Escalate only the timeout blob (resume-safe)
.venv/bin/python implementations/python/sugar-lift-py-tests/scripts/classify_loud_timeouts.py \
  --files-from docs/ledgers/loud-timeout-discovery-10s-4894.json \
  --skip-discovery \
  --escalation-bounds 60,120,300 \
  --resume \
  --ledger docs/ledgers/loud-timeout-classification-4894.jsonl \
  --summary docs/ledgers/loud-timeout-classification-4894-summary.json

# 3) Focused instrument
.venv/bin/python -m pytest -q \
  implementations/python/sugar-lift-py-tests/tests/test_classify_loud_timeouts.py
```

## Floors preserved

- No panic/refusal weakened
- No timeout silently reclassified as complete/dropped
- No bound raised to invent green without recording the successful bound
- Wall conservation: silent = 0; hang remains explicit until product budget terminal exists

## Predicted Epsilon R (this PR)

| Axis | Δ | Why |
|---|---:|---|
| timeout-blob instrument | 0 → executable | classifier + red residual axes |
| `R_timeout_blob_classified` | +1 (first shard) | `test_core.py` panic at 60s |
| typed panic owners recovered from blob | +1 family | FormatDunderCallSugar callsite |
| hang / perf product terminals | 0 | not yet confirmed at 300s / >120s complete |
| panic/refusal floors | 0 | measurement only |
