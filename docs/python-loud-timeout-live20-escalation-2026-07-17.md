# Live-20 timeout escalation (#4894)

Escalation of the **20** files that still timed out at 10s on the live rediscovery
(`docs/ledgers/loud-timeout-discovery-10s-4894-recensus-live.json`).

Bounds: 60 → 120 → 300 (skip-discovery). Single-lane. Progress heartbeats on.

## Results

| Verdict | Class | Count |
|---|---|---:|
| completes-at-bound | **A** | **11** |
| completes-with-panic | **B** | **9** |
| hang-at-max-bound | **D** | **0** |
| bare | **E** | **0** |
| perf-complete | **C** | **0** |

**Every live timeout finished by 60s.** Zero 300s hangs.

### B owners (dispatch)

| Owner | Files |
|---|---:|
| SequentialDigBody | 3 |
| TemporalContext | 2 |
| WithSugar | 2 |
| RuntimeEffect | 1 |
| (malformed owner string on test_loc) | 1 |

### Residual

- Live timeout fog @10s was **20**; after escalation **0** remain unclassified / hang.
- Product residual is the **9 typed B panics** (dispatchable), not stopwatch mass.
