# #6284 NameError — correctness only (pandas)

**Authority:** bounded NameError replay  
**Pin:** `d94f67a31` → **Replay:** `c11767c5e`  
**Wall:** ~2434s bound vs ~1041s full census (bound was **not** cheaper here)

## Ledger (target family)

```text
#6284 semantic correctness: proven by twins
#6284 pandas NameErrorEffect Δ: 0
fabricated pandas rows: 0
legitimate pandas rows: 940
family subtraction: forbidden
```

## Scope of observed movements

Exact for the **replayed slice** (305 files that held all 940 NameError occurrences):

| Family | pinned → replay | Δ | Scope |
|--------|----------------:|--:|-------|
| NameErrorEffect | 940 → 940 | **0** | corpus-wide for this family (slice contained all occurrences) |
| SubscriptStoreRuntimeEffect | 1166 → 1161 | −5 | **slice-only** (1116 files not replayed) |
| YieldSuspensionSugar.desugar | 20 → 17 | −3 | **slice-only** |

No global `pinned − 8` projection. No 10.9% gain.

## Desugar ledger taxonomy

| Bucket | Role |
|--------|------|
| Correctly constructed effects | Accounted semantics (e.g. legitimate NameErrorEffect) — **not defects to eliminate** |
| Explicit incomplete obligations | Typed Incomplete / retained FOL obligations |
| Construction panics / gaps | Floor gaps, SugarNotWritten, resolution gaps |
| Implementation defects | Crashes, instrument false-red, hung measurement |

**Python done** does not require deleting legitimate effects. It requires every effect to be correctly constructed, routed, and accounted.

## Operational lesson

Bounded replay is not automatically cheaper. Use it only when the selected slice is demonstrably cheaper **or** uniquely sharp as a discriminator. After `R(timeout)=0` is restored, the next attribution run is a **full authenticated census** at current head — not projection of the unmeasured 1116 files.

## Machine board

See `nameerror-bounded-replay-c11767c5e.json` beside this note.
