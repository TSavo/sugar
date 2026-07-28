# `opaque-call-target` — what the largest term on the board actually is (#6371)

Diagnosis only. No detector weakened, no panic suppressed, no key restructured.
`WithConstructionGapKind.parse` keeps preserving unrecognised wire kinds.

Baseline: `docs/ledgers/pandas-3.0.3-control-effect-9a78828ee.json` on
`origin/main`, corpus pin `docs/ledgers/pins/pandas-3.0.3.pin.json`, 1,421
enrolled / 1,416 completed, `R = 4`.

```
.cmResolutions["gap:unrecognized:opaque-call-target:func"]  = 5737   (79.0% of the board)
.cmResolutions["gap:unrecognized:opaque-call-target:cast"]  =  709
```

## The finding in one sentence

**`cmResolutions` is the field that REPLACED `cmMembranes` in the scoreboard
repair (#6332) precisely to stop bucketing With residual by pandas leaf-name
spelling — and 89.3% of its mass is now keyed by a pandas spelling.** The
replacement inherited the disease one layer down. And the largest term in it,
`opaque-call-target:func` at 79.0% of the whole board, is not a pandas symbol
at all: `func` is the conventional spelling of a **callable parameter**, so the
biggest number on the board is a missing capability wearing a vendor name.

## 1. The full provenance of one board term

`gap:unrecognized:opaque-call-target:func` is assembled at four separate
layers. Only the last two fuse a kind with a symbol.

| # | File:line | What it does |
|---|---|---|
| 1 | `implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/manager_construction.py:423` | mints `ManagerConstructionGapV1("opaque-call-target", resolved.cid, opaque[0])` — **kind and symbol are separate fields here.** |
| 2 | `implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/manager_summary_derivation.py:737` | `_construction_gap_kind()` returns `f"{kind}:{text}"` — **the fusion happens here.** |
| 3 | `implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/manager_summary_derivation.py:749-754` | `_install_derivation_gap()` stores that fused string as `ContextManagerResolutionGapV1.kind` |
| 4 | `implementations/python/sugar-lift-py-tests/scripts/control_effect_recensus.py:183` | `_cm_resolution_bucket()` sees `parse` fall through to `UNRECOGNIZED_RESOLUTION_KIND` and emits `f"gap:unrecognized:{kind}"` |

Two more copies of the same fusion sit inline at
`manager_summary_derivation.py:712` and `:723` (protocol-construction and
summary-derivation gaps), so the pattern is three sites, not one.

**The structural key already exists at every layer except the reporting one.**

- `ManagerConstructionGapV1` (`manager_construction.py:95-104`) declares `kind`
  as a closed `Literal` of six members with `detail` as its own field.
- `ContextManagerResolutionGapV1`
  (`implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/context_manager_resolution.py:85-91`)
  declares `target_symbol` beside `kind`, already separate.
- The wire decoder (`context_manager_resolution.py:346`) already **rejects**
  any gap whose `kind` is outside `_GAP_KINDS` (`:184`, ten members) and reads
  `targetSymbol` from its own field (`:356`).

So the source-derived path constructs, in process, a `ContextManagerResolutionGapV1`
that its own wire decoder would refuse as `malformed context-manager resolution gap`.
The fused key is not a schema the system declares anywhere. It is a string
built in the reporting layer that no reader validates.

## 2. Is it one mechanism or several? — **at least three, wearing one name**

`"opaque-call-target"` is returned from five sites in `manager_construction.py`
carrying two structurally different `detail` payloads:

**Mechanism R — recursion / no progress.** Lines 214, 314, 472. `detail` is the
literal `"recursive source call graph"`: re-entry of a frame already being
projected, a returned-callsite cycle, or a fixpoint loop that stops making
progress. **No symbol at all.** Same kind, different failure, different fix
(a cycle policy).

**Mechanism O — callee not resolvable through the export door.** Lines 423 and
452, `detail = opaque[0]`. A `Name` callee that is neither a module-level
definition (`definition_names`, `:385`) nor bound in the builtin temporal
(`_named_call_is_source_opaque`, `:549`) is handed to
`_resolve_external_call_frame`; if that returns `None` the name is appended to
`opaque` and **the first element wins**.

Mechanism O splits again on what actually binds the name. The predicate at
`:549` takes only `(name, definition_names, builtin_floor)` — **it never
consults the enclosing function's parameters or locals**, so a called
*parameter* is classified identically to a missing import.

Population context — every source-opaque `Name`-callee occurrence in pinned
pandas 3.0.3 (`ast`, mirroring the production predicate; 20,437 occurrences).
This is *not* the board's distribution, which is per `with` site; the board's
own six-symbol alphabet is attributed individually in section 2b:

| Class | Count | Share | What the name is |
|---|---|---|---|
| **O-import** | 18,607 | 91.0% | module-level import — a real external symbol outside the artifact |
| **O-local** | 1,060 | 5.2% | function-local binding — callee is a runtime value |
| **O-param** | 761 | 3.7% | **bound parameter — higher-order dispatch** |
| **O-unbound** | 9 | 0.04% | star-import / global / builtin shadow |

The two names on the board land in **different classes**:

- **`:cast` is O-import.** `typing.cast`, reached first in
  `core/nanops.py::nanmean`, `core/sorting.py::lexsort_indexer`,
  `compat/numpy/function.py::validate_argsort_with_ascending`. A stdlib symbol
  whose defining source is not in the distribution artifact. This is an
  **artifact-coverage** gap.
- **`:func` is O-param.** The definitions that emit it first are
  `core/array_algos/masked_accumulations.py::_cum_func`,
  `core/array_algos/masked_reductions.py::_reductions`,
  `core/array_algos/masked_reductions.py::_minmax`,
  `core/array_algos/take.py::_take_nd_ndarray`,
  `core/sorting.py::_nanargminmax`, `core/sample.py::preprocess_weights` —
  every one of which takes `func` as a **formal parameter and calls it**.
  This is a **missing capability**: calling a value, not a name. No export
  lookup can ever resolve it, because there is nothing to look up.

`func` is not a pandas symbol. It is the conventional spelling of a callable
parameter, and the 5,737 count is a handful of hot internal helpers amplified
across thousands of `with` sites. The largest term on the board is a
higher-order-dispatch capability gap that has been wearing a vendor-looking
name.

A fourth mechanism shows up only once the board's own symbols are attributed
(section 2b): `get_handle` is defined **inside** the artifact at
`pandas/io/common.py:660`, yet `_resolve_external_call_frame` returned `None`
for it. That is an export-door defect, not a coverage gap — and it is currently
invisible because it shares a bucket with the other three.

**Second defect in mechanism O:** `opaque[0]` is first-hit-wins over a *set*.
When a definition has several unresolvable callees the key names one
arbitrarily and discards the rest, so the term is both symbol-carrying and
lossy — the count under `:func` is not "5,737 sites blocked on `func`", it is
"5,737 sites whose blocking set happened to sort `func` first".

## 2b. The full kind census — from the authenticated ledger

Source: `git show origin/main:docs/ledgers/pandas-3.0.3-control-effect-9a78828ee.json`,
field `.cmResolutions`. Corpus pin `docs/ledgers/pins/pandas-3.0.3.pin.json`,
manifest `sha256:c267d971…`, 1,421 enrolled / 1,416 completed, `R = 4`,
`R_construction = 4`, `R_cm_derived_contract = 17`.

**Thirteen distinct keys, 7,264 rows.** The complete distribution:

| Count | Share | Class | Key |
|---:|---:|---|---|
| 5737 | 79.0% | **symbol-carrying** | `gap:unrecognized:opaque-call-target:func` |
| 715 | 9.8% | structural | `gap:dynamic-export` |
| 709 | 9.8% | **symbol-carrying** | `gap:unrecognized:opaque-call-target:cast` |
| 24 | 0.3% | structural | `gap:unrecognized:target-outside-binding` |
| 17 | 0.2% | structural | `derived-contract` *(the successes)* |
| 17 | 0.2% | **symbol-carrying** | `gap:unrecognized:non-manager-result:BlockValue` |
| 14 | 0.2% | structural | `gap:unrecognized:artifact-module-absent` |
| 9 | 0.1% | **symbol-carrying** | `gap:unrecognized:opaque-call-target:setTZ` |
| 8 | 0.1% | **symbol-carrying** | `gap:unrecognized:opaque-call-target:get_handle` |
| 7 | 0.1% | structural | `gap:no-derived-contract` |
| 5 | 0.1% | **symbol-carrying** | `gap:unrecognized:opaque-call-target:nullcontext` |
| 1 | 0.0% | **symbol-carrying** | `gap:unrecognized:force-floor:attribute:ObjectValue` |
| 1 | 0.0% | **symbol-carrying** | `gap:unrecognized:opaque-call-target:available_protocols` |

**Split: 777 structural (10.7%) / 6,487 symbol-carrying (89.3%).**

Only 17 rows out of 7,264 — 0.23% — are `derived-contract`, an actual success.

### The observed alphabet is SIX symbols, not forty

`opaque-call-target` accounts for 6,479 rows and carries exactly **six distinct
spellings**: `func`, `cast`, `setTZ`, `get_handle`, `nullcontext`,
`available_protocols`. `func` alone is **79.0% of the entire `cmResolutions`
board**.

This is the coordinator's point made numerically. The key is not exploding —
it is *concentrated*, and that concentration is exactly why it looks stable.
Rename `func` in six pandas helpers and 79% of the board changes spelling
overnight. A measurement that a vendor rename can move is not a measurement.

Two of the thirteen keys carry a **Sugar internal type name**, not a vendor
spelling: `non-manager-result:BlockValue` and `force-floor:attribute:ObjectValue`.
Those are a milder version of the same defect — an implementation detail
promoted to identity — but they are not vendor exposure. **The vendor exposure
is exactly the `opaque-call-target` family: 6,479 of 6,487 symbol-carrying rows.**

### Per-symbol mechanism attribution

Each of the six, classified by *what binds the name* at the definitions where
it is `opaque[0]` (`ast` over pinned pandas 3.0.3):

| Symbol | Rows | Binding | Mechanism |
|---|---:|---|---|
| `func` | 5737 | **parameter (13 defs) / local (7 defs)** | **callee is a VALUE** — no export lookup can ever resolve it |
| `setTZ` | 9 | **local** (`_testing/contexts.py::set_timezone`) | same — callee is a value |
| `cast` | 709 | import — `typing.cast` | **artifact coverage**: stdlib outside the distribution |
| `nullcontext` | 5 | import — `contextlib.nullcontext` | same |
| `get_handle` | 8 | import — **defined in-artifact** at `pandas/io/common.py:660` | **export-door defect**: `_resolve_external_call_frame` returned `None` for a symbol that IS in the artifact |
| `available_protocols` | 1 | not present in pandas at all | from another distribution in the graph; unclassified |

By row count, the three mechanisms behind `opaque-call-target`:

- **callee-is-a-value — 5,746 rows (79.1% of the board).** A *missing
  capability*. `_named_call_is_source_opaque` (`manager_construction.py:549`)
  takes only `(name, definition_names, builtin_floor)` and never consults the
  enclosing frame's binders, so calling a parameter is reported identically to
  calling a missing import.
- **artifact coverage — 714 rows (9.8%).** stdlib source not in the
  distribution artifact.
- **export-door defect — 8 rows.** An in-artifact symbol the export door
  failed to resolve. Small, but it is a *bug*, and today it is invisible
  because it shares a bucket with the other two.

**Mechanism R (recursion / no-progress) contributes ZERO rows on this corpus.**
It has never fired on pandas. So the conflation is not currently costing
measurement through R — the entire cost is that the two large symbol-carrying
mechanisms are indistinguishable, and 79% of the board is a capability gap
that reads as a vendor name.

### Why extending the enum is not the fix

Observed cardinality is six, but *declared* cardinality is unbounded: the fused
key set has the cardinality of the detail strings. `force-floor` composes a
**three**-segment key `f"{kind}:{owner}:{observed}"`, and `_construction_gap_kind`
truncates detail to 80 chars at `manager_summary_derivation.py:745`. A key that
can be truncated is not an identity, and a vocabulary that must enumerate
callee spellings is the `cmMembranes` name table rebuilt one layer down.

### The producers

Five sites reach `_cm_resolution_bucket`; three fuse, two do not:

| Producer | Kinds | Fused? |
|---|---|---|
| `_install_derivation_gap` literals (`:626, :680`) | `no-derived-contract`, `incomplete-call-actuals` | no |
| import-binding gap (`:632-633`) | passthrough `str(kind)` | **no — this site already does it right** |
| `ManagerConstructionGapV1` via `_construction_gap_kind` (`:737`) | 6 kinds | **yes** |
| `ManagerProtocolConstructionGapV1` via `:712` | 3 kinds | **yes** |
| `DerivedManagerSummaryGapV1` via `:723` | 3 kinds | **yes** |

The bare-`str(kind)` site at `:633` is the existing proof that the unfused
shape already works inside this exact function.

## 3. Relation to the `With` residual — **these are not With construction failures**

The baseline shows 7,663 `with` sites against 2 With-attributable construction
R, and total construction R of 4. These rows are not construction R and never
were.

They are **preconstruction derivation** outcomes: `derive_manager_summaries`
tried to derive a context-manager contract for a `with` item, could not reach a
`ConstructedManagerBehaviorV1`, and installed a `ContextManagerResolutionGapV1`
in place of a derived ref. The `With` node then raises
`ContextManagerResolutionConstructionGap` at `nodes.py:4453-4466` and reports
it. The failure is upstream of `With` entirely: `With` is the *reporter*, not
the *cause*. Every one of these rows is a manager-body construction failure
that a `with` statement happened to demand.

They are the same gap as the `With` residual only in the sense that `With` is
where they surface. Mechanism R (recursion) and mechanism O-param (higher-order
call) would block any caller of those definitions, `with` or not.

## 4. Proposed structural key — kind beside symbol

Carry what the mint already knows, and stop re-deriving it from a string.

1. **Add `detail` as a field on `ContextManagerResolutionGapV1`**, beside the
   existing `kind` and `target_symbol`. `_install_derivation_gap` passes the
   gap's `kind` and `detail` through unfused. Delete `_construction_gap_kind` (`:737`)
   and the two inline `f"{kind}:{detail}"` copies at
   `manager_summary_derivation.py:712` and `:723`.
2. **Split `opaque-call-target` into the mechanisms it is hiding**, at the
   mint in `manager_construction.py`, by *authenticated structural condition*
   — never by a name table:
   - `call-graph-cycle` — lines 214, 314, 472. Already symbol-free.
   - `value-call-target` — line 423/452 where the callee name **is** bound as
     a parameter or local of the enclosing definition. Decided by the frame's
     own binder set, which construction already holds; no vendor list, no
     spelling. **Predicted 5,746 rows (79.1%).**
   - `call-target-source-absent` — the callee resolves to a module the
     distribution artifact does not contain. **Predicted 714 rows.**
   - `call-target-export-unresolved` — the defining source **is** in the
     artifact but `_resolve_external_call_frame` returned `None`. The
     `get_handle` case; a real bug, currently invisible.
     **Predicted 8 rows.**

   The three are distinguished by conditions already evaluated at the mint:
   *is the name bound in this frame*, and *did artifact lookup find the module*.
   Neither reads a spelling.
3. **Carry the whole blocking set, not `opaque[0]`.** `detail` becomes the
   sorted tuple of unresolved callee names, so the term stops being
   order-dependent. The census buckets on the kind; the symbols ride as data
   for a human reading one row, never as identity.
4. **Extend `_GAP_KINDS` and `WithConstructionGapKind` with the new structural
   kinds**, so the source-derived path produces gaps its own wire decoder
   would accept. `parse`'s `UNRECOGNIZED_RESOLUTION_KIND` fallthrough **stays**
   — it is the thing that keeps a newly minted kind from re-aborting 780 files.
5. **`_cm_resolution_bucket` buckets on `kind` alone.** `gap:unrecognized:*`
   then means what it should: a kind this build does not yet name, not a
   spelling.

### Cost

**Reporting-layer change only. No wire-format change. No CID preimage change.
No repin.**

Verified: the fused string is written into `context.source_derived_contract_refs`
(`manager_summary_derivation.py:754`), an in-process dict on
`TreeConstructionContextV1` (`context_manager_resolution.py:161`). It has
exactly three consumers —

- `nodes.py:4440` → `_raise_resolution_gap` → panic message,
- `control_effect_recensus.py:195` → census tally,
- the dict itself.

It never reaches `_hash_json` / `encode_jcs`, and `ContextManagerResolutionGapV1`
has no `wire()` method. The CID-bearing table is the *authenticated* one
(`ResolvedContractRefsV1.table_cid`, `decode_resolved_contract_refs`), whose gap
rows are validated against `_GAP_KINDS` and have never carried a fused kind.

Adding new members to `_GAP_KINDS` (step 4) widens what the wire decoder
*accepts*; it does not change any preimage, because `byUseSite` hashes the
bytes actually present and no producer emits the new kinds over the wire today.

### What this costs on the board

Splitting a bucket does not lower `R`. `Epsilon R = 0` on the total: 7,264 rows
in, 7,264 rows out, redistributed from 13 keys (89.3% symbol-carrying) to a
closed structural vocabulary with **zero** symbol-carrying keys.

Predicted post-change `cmResolutions`, total conserved:

```
value-call-target                5746   (was opaque-call-target:{func,setTZ})
dynamic-export                    715   unchanged
call-target-source-absent         714   (was opaque-call-target:{cast,nullcontext})
target-outside-binding             24   unchanged
derived-contract                   17   unchanged
non-manager-result                 17   (was non-manager-result:BlockValue)
artifact-module-absent             14   unchanged
call-target-export-unresolved       8   (was opaque-call-target:get_handle)
no-derived-contract                 7   unchanged
force-floor                         1   (was force-floor:attribute:ObjectValue)
call-target-source-absent (+1)      1   available_protocols, pending attribution
                                 ----
                                 7264
```

The deliverable is that 79.1% of the board stops being a pandas spelling and
becomes `value-call-target`: a named capability the board can track to zero.

## Prior art this follows

`cmMembranes` → `cmResolutions` (#6332): bucket by authenticated structural
gap kind, not by a name table, and accept losing a partition rather than
publish a spelling as a measurement. Step 3 here takes the same trade — the
symbol set is carried as row data for human reading and is never a bucket key.

## Method

`ast` classification of pinned pandas 3.0.3 at
`/usr/local/lib/python3.14/site-packages/pandas`, mirroring
`_named_call_is_source_opaque` (`manager_construction.py:549`) and the
`opaque[0]` first-hit projection (`:423`). Scripts are diagnostic only and are
not checked in; both are reproducible from the description above in a few
lines.

Counts are read from the committed ledger, **not from disk**:
`git show origin/main:docs/ledgers/pandas-3.0.3-control-effect-9a78828ee.json`.
An earlier pass of this diagnosis reported the counts as absent from the tree.
That was a false negative from grepping a working checkout at `4730cbd3a`
while `origin/main` was `74d7bb1d3` — the stale-checkout defect class. Read
census artifacts from the ref.

No sweep, no census, and no lease were run for this diagnosis. `Delta R` is
unmeasured and unchanged: no executable path is touched.
