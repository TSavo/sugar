# Historical exact-pin board at `95e58d0ff` — COMPLETE 12/12 (2026-07-18)

**Status: HISTORICAL measurement — complete conserved board.**

Main has moved past this pin (dataclass ClassDef `#5267`, composite Delete `#5269`,
and later). These counts are the **authoritative historical baseline at
`95e58d0ff`**. They are for priority and provenance only — **not** a regression
baseline against current main, and **not** a claim that vendor walls are zero.

## Provenance (binding)

| Axis | Value |
|---|---|
| Sugar pin | `95e58d0ff24cdd8966f8f92f5a791bbb67e1b009` (post-#5250 native shapes) |
| Interpreter | CPython **3.12.3** (producer + aggregator) |
| NumPy / pandas | **2.5.1** / **3.0.3** |
| pandas shards | 3 concurrent, 30s per-file, `corpus_fatal_triage.py` |
| pandas machine ledger | `vendor-recensus-requests-datetime/target/vendor-recensus/pandas-shard{0,1,2}.json` + `pandas-merged.json` |

## Scope distinction

| Domain | Controlled | Not claimed |
|---|---|---|
| Permanent CI floors (kit roots) | side doors, ownership, panic-catch, vendor-name, silent, bare, native | Installed numpy/pandas/… walls complete |
| This board | Honest terminals on assertion-bearing vendor files at pin | Current main equals this pin |

## Axes (non-overlapping)

- **Loud-fatal files** = typed `FactoryPanic` files only
- **Native crash / bare exception / timeout** = separate file columns
- **Unclassified** = factory-walk **rows** on completed files (not file mass)
- **Silent** must be 0 (assertion conservation)

## Complete 12/12 board

| Corpus | Assertion-bearing files | Loud-fatal (FactoryPanic) | `python.factory` | Unclassified walk rows | Native crash | Bare | Timeout | Silent |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| NumPy | 142 | 40 | 10 | 1,299 | 0 | 0 | 11 | 0 |
| **pandas** | **890** | **341** | **287** | **8,470** | **0** | **0** | **3** | **0** |
| SciPy | 278 | 168 | 70 | 595 | 0 | 0 | 10 | 0 |
| Pydantic | 223 | 104 | 38 | 2,340 | 0 | 1 | 3 | 0 |
| SQLAlchemy | 320 | 199 | 17 | 209 | 0 | 1 | **47** | 0 |
| scikit-learn | 271 | 212 | 195 | 544 | 0 | 0 | 2 | 0 |
| Requests | 8 | 2 | 0 | 393 | 0 | 0 | 0 | 0 |
| Cryptography | 7 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| Polars | 12 | 8 | 0 | 1 | 0 | 0 | 0 | 0 |
| datetime | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| itsdangerous | 1 | 0 | 0 | 22 | 0 | 0 | 0 | 0 |
| logos | 10 | 0 | 0 | 12 | 0 | 0 | 0 | 0 |
| **TOTAL 12/12** | **2,163** | **1,078** | **618** | **13,885** | **0** | **2** | **76** | **0** |

### pandas conservation (exact)

```text
890 assertion-bearing
  = 546 completed
  + 341 FactoryPanic
  + 0 bare
  + 0 crash
  + 3 timeout
  + 0 transport
  + 0 silent

Completed-file assertions: 8,068 lifted/cited + 452 refused loud + 0 silent = 8,520 stated
Factory walk (completed files): 75,505 warranted + 8,470 unclassified
```

### pandas `python.factory` owners (341 panic files total; 287 factory)

| Count | Coarse observed | Notes |
|---:|---|---|
| **266** | `Delete` statement | Dominant; many via stdlib `contextlib` blame path |
| **21** | `Assign` statement | Tuple unpack leaves (attr/subscript/nested) |

Detailed leaf shapes among resolved Assign rows include dual-Attribute unpack,
dual-Subscript unpack, nested name tuples. Delete rows at this pin predate
composite Delete ownership on later main (`#5269`).

## Primary frontiers (from this historical vector)

1. **`python.factory` missing Sugars** — **618** files. Split by source shape; drain by family.
2. **Unclassified factory-walk rows** — **13,885**. Permanent axis `R_factory_walk_unclassified` (not subsumed by `R_silent=0`).
3. **Timeouts** — **76** files (SQLAlchemy 47). Independent red axis; never convert to effects.
4. **Bare exceptions** — **2** files. Independent red axis.
5. **Native crashes** — **0** on measured corpora (keep floor).

## Shape-dispatch priority (post-this-board)

| Priority | Family | Historical mass signal |
|---|---|---|
| 1 | Delete non-name / multi-target | pandas 266 + SciPy ~19 at pin (pre-#5269) |
| 2 | TupleUnpack attr/subscript leaves | pandas Assign unpack + NumPy/SciPy dual-subscript |
| 3 | ClassDef residual | Pydantic/SQLAlchemy mass; dataclass path later on main |
| 4 | sklearn Call / other factory residual | scikit-learn 195 factory |

Re-measure **affected** families from current main after `#5267` / `#5269` — do not
treat this board as live residual after those merges.

## Refresh rule

Full-board recensus only after major Sugar-family merges. Between full boards,
re-run **owner-bucket deltas** only.

## Related

- #5233 recensus fleet issue
- #5252 / PR #5255 — `R_factory_walk_unclassified` floor
- #5254 shape-split / Sugar-family drain
- #5258 TupleUnpack leaf owns
- `docs/contributing/python-sole-construction.md`
