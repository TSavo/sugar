# Historical exact-pin board at `95e58d0ff` (2026-07-18)

**Status: HISTORICAL measurement.** Published for priority and provenance only.

Main has moved to post-dataclass ClassDef construction (`26d6e220f` and later).
These counts remain useful for ordering Sugar-family drain work, but **must not**
be treated as the final conserved board or as a regression baseline against
current main.

## Provenance (binding for this document)

| Axis | Value |
|---|---|
| Sugar pin | `95e58d0ff24cdd8966f8f92f5a791bbb67e1b009` (post-#5250 native shapes) |
| Interpreter | CPython **3.12.3** (producer and aggregator) |
| NumPy / pandas | 2.5.1 / 3.0.3 |
| Scope note | CI permanent floors on main traverse **checked-in kit roots** only; they do **not** claim installed vendor walls are zero |

## Scope distinction (enforcement vs corpus)

| Domain | What is controlled | What is not claimed |
|---|---|---|
| Permanent CI floors | Side doors, ownership, panic-catch, vendor-name special case, silent, bare, native crash **in production kit trees** | Installed numpy/pandas/SciPy/… walls already complete |
| Exact-pin recensus | Honest terminal vectors on assertion-bearing vendor files | That current main equals this pin |

## INTERIM 11/12 board (pandas pending)

Loud-fatal = typed `FactoryPanic` files only. Crashes / bare / timeouts are
**separate** columns. Unclassified factory-walk is a **row** count, not file mass.
Silent must remain 0.

| Corpus | Assertion-bearing files | Loud-fatal | `python.factory` | Unclassified walk rows | Native crash | Bare | Timeout | Silent |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| NumPy | 142 | 40 | 10 | 1,299 | 0 | 0 | 11 | 0 |
| SciPy | 278 | 168 | 70 | 595 | 0 | 0 | 10 | 0 |
| Pydantic | 223 | 104 | 38 | 2,340 | 0 | 1 | 3 | 0 |
| Requests | 8 | 2 | 0 | 393 | 0 | 0 | 0 | 0 |
| datetime | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| itsdangerous | 1 | 0 | 0 | 22 | 0 | 0 | 0 | 0 |
| logos | 10 | 0 | 0 | 12 | 0 | 0 | 0 | 0 |
| Cryptography | 7 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| SQLAlchemy | 320 | 199 | 17 | 209 | 0 | 1 | **47** | 0 |
| scikit-learn | 271 | 212 | 195 | 544 | 0 | 0 | 2 | 0 |
| Polars | 12 | 8 | 0 | 1 | 0 | 0 | 0 | 0 |
| **INTERIM TOTAL (11)** | **1,273** | **737** | **331** | **5,415** | **0** | **2** | **73** | **0** |
| pandas | — | PENDING | PENDING | PENDING | — | — | — | — |

Source: #5233 interim aggregator comment (2026-07-18T20:08:07Z), superseding earlier 8/10 arithmetic.

### Conservation notes (selected)

- SQLAlchemy: `73 completed + 199 FactoryPanic + 1 bare + 47 timeout = 320`; timeouts stay timeout mass only.
- scikit-learn: `57 completed + 212 FactoryPanic + 2 timeout = 271`.
- Polars: `4 completed + 8 FactoryPanic = 12`.
- Pydantic factory-walk unclassified: **2,340** over 115 completed files (final replay).

## Primary frontiers (from this historical vector)

1. **`python.factory` missing Sugars** — 331 files across measured corpora; split by source shape and drain by Sugar family (see shape-split ledger / #5254).
2. **Unclassified factory-walk rows** — 5,415 rows; permanent axis `R_factory_walk_unclassified` (#5252); **not** subsumed by `R_silent=0`.
3. **Timeouts** — 73 files; SQLAlchemy dominates (47); drain independently, never convert to effects.
4. **Bare exceptions** — 2 files; independent red axis.
5. **Native crashes** — 0 on measured exact-pin corpora (encouraging; keep floor).

## Follow-on measurement (current main)

After major construction merges (e.g. dataclass-decorated `ClassDef` at `26d6e220f`):

1. Finish pandas exact-pin shard at `95e58d0ff` → close 12/12 historical board.
2. Re-run **affected owner buckets** from current main (not necessarily every corpus) to measure dataclass / Sugar-family delta.
3. Periodically full-board refresh after major family merges.

## Related instruments / PRs

- #5252 / PR #5255 — `R_factory_walk_unclassified` permanent floor instrument
- #5254 / PR #5258 — TupleUnpack leaf owns (attribute/subscript) shape drain
- #5233 — recensus fleet issue
- `docs/contributing/python-sole-construction.md` — governing law
