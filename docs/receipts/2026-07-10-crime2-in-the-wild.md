# Crime 2 in the wild — measurement receipt (handoff M)

**Date:** 2026-07-10  
**HEAD:** post-`6a8a4df` measurement on agent main  
**Issue class:** #4016 Crime 2 (`forged_warrant`) — dig floor without `warrantingAssert`  
**Mode:** read-only measure; no production code change  

## Method

1. **Library source sample** — assert-preferring random sample of **60** `.py` files each under installed `numpy` / `pandas` (venv `2.4.6` / `3.0.3`).  
   Per file (subprocess isolation): `build_literal_call_report` → `account_lift_coverage` Crime2 axis.  
2. **Consumer opaque-op snippets** — small tests calling `np.array(...).sum()`, `pd.Series(...).sum/mean()`, plus control dig-floor snippet (`len` body).  

Raw JSON:  
- `docs/receipts/2026-07-10-crime2-numpy-pandas-wild.json`  
- `docs/receipts/2026-07-10-crime2-consumer-opaque-ops.json`  

## Results

### A. Library source (n=60 each)

| vendor | files_ok | dig_floors | warranted | **forged_warrant** | gate |
|--------|----------|------------|-----------|--------------------|------|
| **numpy** | 56 | **0** | 0 | **0** | green (vacuous) |
| **pandas** | 60 | **0** | 0 | **0** | green (vacuous) |

- numpy: 4 timeouts/errors; no dig-floor diagnostics in successful lifts.  
- **No Crime 2 indictment** — residual is not forged warrants; the detector saw **zero floors**.

### B. Consumer opaque ops

| snippet | dig_floors | forged_warrant | other diagnostics |
|---------|------------|----------------|-------------------|
| `len` body (control) | 1 | **0** (warrant stamped) | dig-floor + agreement |
| `np.array.sum` truth/lie | **0** | **0** | **`dig-boundary`** |
| `pd.Series.sum/mean` | **0** | **0** | **`dig-boundary`** |

Control proves the Crime 2 path is live (floor + stamp).  
Numpy/pandas **method digs stop at dig-boundary** (incomplete / unreadable body), so they never emit `kind=dig-floor` and never enter the forged-warrant count.

## Interpretation

| Question | Answer |
|----------|--------|
| Is `forged_warrant > 0` on numpy/pandas in this sample? | **No** |
| Does that mean Crime 2 is “clean” on those vendors? | **Only vacuously** — no dig floors, so nothing to forge |
| Where do opaque vendor digs go? | **`dig-boundary`** (refuse / incomplete), not literal/effect floor |
| statistics (#4020) | Had floors with stamps → gate 0 with real dig-floor mass |

**Doctrine:** Crime 2 prosecutes *forged floors*. Incomplete dig without floor is a different residual (Minority / dig-boundary / FactoryGap class) — do **not** re-label it Crime 2.

## Indictments

| ID | Action |
|----|--------|
| Crime 2 count on numpy/pandas wild sample | **No issue** — `forged_warrant == 0` |
| Follow-up (optional) | Track “opaque vendor digs die at dig-boundary so Crime 2 is unexercised” as a **measurement gap**, not a forged-warrant RED |

## Counts to paste

```
numpy  sample_n=60 files_ok=56 dig_floors=0 forged_warrant=0
pandas sample_n=60 files_ok=60 dig_floors=0 forged_warrant=0
control len-floor: dig_floors=1 forged_warrant=0 (warranted)
consumer np/pd sum|mean: dig_floors=0 dig-boundary present forged_warrant=0
```
