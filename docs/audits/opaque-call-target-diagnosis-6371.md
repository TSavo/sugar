# `opaque-call-target` — what the largest term on the board actually is (#6371)

Diagnosis only. No detector weakened, no panic suppressed, no key restructured.
`WithConstructionGapKind.parse` keeps preserving unrecognised wire kinds.

Baseline read (conserved 1,421/1,421, pinned pandas 3.0.3):

```
gap:unrecognized:opaque-call-target:func    5737
gap:unrecognized:opaque-call-target:cast     709
```

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

Measured over pinned pandas 3.0.3 (`ast`, mirroring the production predicate;
20,437 source-opaque `Name`-callee occurrences):

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

**Second defect in mechanism O:** `opaque[0]` is first-hit-wins over a *set*.
When a definition has several unresolvable callees the key names one
arbitrarily and discards the rest, so the term is both symbol-carrying and
lossy — the count under `:func` is not "5,737 sites blocked on `func`", it is
"5,737 sites whose blocking set happened to sort `func` first".

## 2b. The kind vocabulary census — structural vs symbol-carrying

**The per-kind count board is not reproducible on the Mac under this brief**
(no lease, no census, no full sweep), and no file in the tree carries the
`gap:unrecognized:*` counts — `grep -rl "gap:unrecognized"` over the worktree
is empty, and `docs/ledgers/recensus-1032-live` predates the term. The counts
in the header are the coordinator's read of the battleaxe baseline. The
**vocabulary**, however, is fully derivable from the producers, and that is the
part that decides the fix.

Everything that can reach `_cm_resolution_bucket` comes from exactly five
producers:

| Producer | Kinds | Fused with a symbol? |
|---|---|---|
| `_install_derivation_gap` literals (`manager_summary_derivation.py:626, 680`) | `no-derived-contract`, `incomplete-call-actuals` | **no** — bare structural |
| import-binding resolution gap (`manager_summary_derivation.py:632-633`) | whatever `resolve_import_binding` returned, passed as bare `str(kind)` | **no** — **this site already does it right** |
| `ManagerConstructionGapV1` (`manager_construction.py:96-104`) via `_construction_gap_kind` (`:737`) | `artifact-mismatch`, `definition-missing`, `opaque-call-target`, `non-manager-result`, `call-binding`, `force-floor` | **yes** — all six get `:detail` appended |
| `ManagerProtocolConstructionGapV1` (`manager_protocol_construction.py:53-56`) via `:712` | `enter-missing`, `exit-missing`, `method-construction` | **yes** |
| `DerivedManagerSummaryGapV1` (`manager_summary_derivation.py:72-79`) via `:723` | `enter-may-halt`, `exit-may-halt`, `opaque-exit-truthiness` | **yes** |

**Split: 3 structural producers, 12 symbol-carrying kinds across 3 fused
producers.** The bare-`str(kind)` site at `:633` is the existing proof that
the unfused shape already works in this exact function — it is what the other
three sites should look like. Every kind that
carries a non-empty `detail` becomes a fused key, and every fused key falls
through `WithConstructionGapKind.parse` into `gap:unrecognized:*`. That is why
~6,500 of ~7,250 rows carry a kind the closed enum does not name: **not one
missing enum member, but twelve kinds × unbounded detail strings.** The
declared vocabulary can never catch up, because the cardinality of the fused
key set is the cardinality of the detail strings, which is unbounded by
construction.

Note the fusion is not uniform across `detail` shapes. `force-floor` composes
`f"{owner}:{observed}"` (`manager_construction.py`, `ConstructionPanic`
membrane), so `gap:unrecognized:force-floor:<owner>:<observed>` is a
**three**-segment fusion, and `detail` is truncated to 80 chars at `:745`. A
key that can be truncated is not an identity.

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
   - `unresolved-call-target` — line 423/452 where
     `_resolve_external_call_frame` returned `None` for a name that is not
     bound in the enclosing frame.
   - `non-name-call-target` — the same site where the callee name **is** bound
     as a parameter or local of the enclosing definition. This is decided by
     the frame's own binder set, which the construction already holds; it
     requires no vendor list and no spelling.
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

Splitting a bucket does not lower `R`. Expect the ~6,500 `gap:unrecognized:*`
rows to redistribute into named structural kinds with the total conserved:
that is the point. `Epsilon R = 0` on the total; the deliverable is that the
mass acquires a mechanism, and O-param becomes a capability the board can
track to zero instead of a spelling it cannot act on.

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
