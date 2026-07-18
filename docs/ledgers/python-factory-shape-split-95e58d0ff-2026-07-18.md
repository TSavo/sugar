# python.factory shape split at `95e58d0ff` (2026-07-18)

**Census analysis, not a full board.** Exact-pin NumPy is complete; SciPy shards
are near-complete; pandas exact-pin still running in fleet. Shape mass below is
from exact `FactoryPanic` rows with `owner=python.factory`, refined by AST
target structure at the gap blame line.

## Method

1. Harvest `terminal_rows` with `category=factory-construction-panic` and
   `gap.owner=python.factory` from exact-pin shards.
2. Resolve blame source; parse the AST node at the blame line.
3. Shape key = structural target form (not vendor name):
   - `Assign/single/targets=Tuple[…]` with leaf kinds Name / Attribute / Subscript
   - `Delete/targets=…`
   - residual `While` / `AugAssign`

## Cross-corpus mass (NumPy exact-pin + SciPy 95e58 shards)

| Mass | Exact missing shape | Sugar family | Representative loci |
|---:|---|---|---|
| **22** | `Assign` tuple of **two Subscripts** `a[i], b[j] = …` | `TupleUnpackAssignSugar` → `SubscriptAssignSugar` leaves | `numpy/_core/tests/test_regression.py:2236`; `numpy/ma/core.py:7073`; SciPy signal/linalg |
| **19** | `Delete` (mostly stdlib `contextlib` attribute dels; blame path often unresolved under uv layout) | `DeleteSugar` / attribute-delete partition | SciPy stats / `_lib` via contextlib |
| **12** | `Assign` tuple of **three Attributes** `obj.x, obj.y, obj.z = …` | `TupleUnpackAssignSugar` → `AttributeAssignSugar` | SciPy `linalg/blas.py:382` |
| **6** | `Assign` tuple of **two Attributes** | same family | SciPy interpolate / integrate |
| **4** | `Assign` `Name + Subscript` mix | same family | SciPy pyprima |
| **2** | Nested `Tuple[Tuple[Name,Name]]` | same family (path-projected names) | NumPy f2py symbolic |
| ≤1 each | longer mixes, nested starred, `While`, nested-attr `AugAssign` | per residual | — |

**NumPy factory total:** 10 files → 9 dual-subscript / nested name unpack + 1 multi-attribute Delete.  
**SciPy factory total (8/8 shards observed):** 70 files, dominated by dual-subscript + attribute unpack + Delete.

## Root cause (not "missing AssignSugar")

`AssignSugar` only owns `name = rhs`. The factory panic text says
`create …assign.assign_sugar` because that is the generic Assign fallback label.
The real gap is:

- `TupleUnpackAssignSugar.new()` **already** builds Name / Attribute / Subscript
  leaves through existing store owners.
- `TupleUnpackAssignSugar.owns()` previously required **flat Name leaves only**,
  so every non-name unpack fell through to `python.factory`.

That is an owns/new partition bug, not a greenfield Sugar.

## Drain order (Sugar families, descending mass)

1. **TupleUnpack leaf owns** — claim Name-rooted Attribute / Subscript / nested
   leaves (this PR). Expected cross-corpus unblock: dual-subscript + attribute
   unpack families (~40+ of measured factory files; pandas still pending).
2. **Delete attribute multi-target** — extend `DeleteSugar` beyond name-only
   targets (or dedicated attribute-delete family). Mass ~19 SciPy (+ stdlib).
3. **Residual one-offs** — `While` statement owner residual; nested-attr
   `AugAssign`; mixed arity edge cases. Re-rank after (1)+(2).
4. **Unclassified walk rows** — separate axis (`R_factory_walk_unclassified`);
   do not fold into factory panic mass.

## Provenance

| Axis | Value |
|---|---|
| Pin | `95e58d0ff24cdd8966f8f92f5a791bbb67e1b009` |
| NumPy shards | `.numpy-recensus-95e58d0ff2` (16/16) |
| SciPy shards | `suite-red-a-c-4208/.receipts/scipy-recensus-95e58` |
| Interpreter | CPython 3.12.3 |
| NumPy / SciPy | 2.5.1 / 1.18.0 |

Pandas exact-pin shape mass will be merged into this ledger when fleet shards
land; do not aggregate pre-#5250 pandas owner counts.

## Related

- #5233 recensus board
- #5254 shape-split task
- #5252 `R_factory_walk_unclassified` (separate red axis)
