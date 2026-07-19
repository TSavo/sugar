# sklearn python.factory residual remeasure (#5274) — 2026-07-18

**Owner-bucket delta**, not a full 12/12 board. Remeasured the **212** historical
loud-fatal sklearn files from pin `95e58d0ff` shards at post-#5269 main kit
sources (worktree pin `0f3b5a0e1`, which includes Delete composite `#5269`,
TupleUnpack leaf owns `#5258`, dataclass ClassDef `#5267`, SetComp `#5279`,
computed Call `#5281`).

## Method

1. Harvest `terminal_rows` with `category=factory-construction-panic` from
   historical sklearn shards
   (`.worktrees/vendor-recensus-requests-datetime/target/vendor-recensus/sklearn-shard{0,1,2}.json`).
2. Re-run each file via `corpus_fatal_triage.py --child-file` against installed
   scikit-learn **1.9.0** (CPython 3.12) with current kit `PYTHONPATH`.
3. Rank remaining panics by exact gap fingerprint
   `(owner, gap_kind, gap_locus, observed, requested)`.
4. For residual `python.factory` rows, resolve blame AST for exact missing shape.

Silent must stay **0** (no completed-file silent accounting observed).

## Terminal conservation (historical 212 PF set)

| Terminal | Count |
|---|---:|
| factory-construction-panic | **196** |
| completed | **11** |
| timeout-or-hang | **5** |
| bare / crash / silent | **0** |

**Historical `python.factory` mass was 195 / 212.** After main Sugar merges, only
**12 / 212** remain `owner=python.factory`. The other historical factory files
mostly advanced to **typed floors** (especially FunctionCallable), not soft
effects.

## Owner families among remaining 196 panics (descending mass)

| Mass | Owner family | Notes |
|---:|---|---|
| **117** | `FunctionCallable decorator factory:wraps` | Floor: missing callsite body for decorator factory `wraps` |
| **20** | `FunctionCallable` | Floor: `ImportAliasValue` decorator substitution |
| **12** | **`python.factory`** | See exact shapes below — this issue's residual |
| **10** | `TemporalContext` | `__file__`, `xp_capabilities_table`, mmap names, … |
| **8** | `ConstructorCallSugar` | Inherited / recursive constructor graphs |
| **4** | `RuntimeEffect` | setitem / union-type operands |
| **4** | `subtract` | Term/Tuple/List floors |
| ≤3 each | bitwise_or, RaiseSugar, multiply, ForSugar floor, ClassDef adjacent, … | one-offs |

## Exact `python.factory` missing shapes (12 files)

| Mass | Exact missing shape | Sugar family direction | Loci |
|---:|---|---|---|
| **8** | `For` target = **flat tuple with Starred rest** `for name, trans, *_ in …` | **new** `StarredTupleForSugar` (or SequenceUnpack-style for-target family). *Not* an owns/new bug: `TupleForSugar` / `NestedTupleForSugar` deliberately exclude stars | **Single production locus:** `sklearn/compose/_column_transformer.py:617` — also blamed from 7 test files that import that path |
| **2** | `ClassDef` residual | separate ClassDef arms | `sklearn/utils/tests/test_deprecation.py:94` — `@deprecated()` decorated class (identity-decorator recognition gap); `sklearn/utils/tests/test_set_output.py:313` — `ClassDef` **with keywords** (`auto_wrap_output_keys=…`) |
| **1** | `Try` with finally + nested try in finally cleanup | TrySugar residual / finally control | `sklearn/model_selection/tests/test_validation.py:2024` |
| **1** | `Call` residual | CallSugar residual | `sklearn/svm/tests/test_svm.py:322` — `(lambda: clf.coef_)()` under `pytest.raises` |

### Starred-For representatives (8 files, one AST shape)

All eight resolve to the same production statement:

```python
for name, trans, *_ in self._iter(
    fitted=True,
    column_as_labels=False,
    skip_empty_columns=True,
    skip_drop=True,
):
```

Files:

- `sklearn/compose/_column_transformer.py` (definition)
- `sklearn/frozen/tests/test_frozen.py`
- `sklearn/metrics/_plot/tests/test_common_curve_display.py`
- `sklearn/metrics/_plot/tests/test_confusion_matrix_display.py`
- `sklearn/metrics/_plot/tests/test_precision_recall_display.py`
- `sklearn/metrics/_plot/tests/test_roc_curve_display.py`
- `sklearn/utils/_repr_html/tests/test_features.py`
- `sklearn/utils/_repr_html/tests/test_estimator.py`

## Implementation decision (this pass)

**No Sugar PR.** There is no clear owns/new partition bug analogous to
TupleUnpack (`#5258`). Residual factory mass is:

1. a **new** starred for-target family (8 files / 1 locus), or
2. ClassDef keyword / non-identity decorator arms (2), or
3. Try/Call one-offs (2).

Dominant remaining mass on the historical set is **not** `python.factory` — it is
`FunctionCallable` wraps (**117**). That is a separate Sugar/floor family and
must not be closed with vendor-name special cases or panic swallows.

## Timeouts (separate axis — do not convert)

5 files hit the 60s child wrapper on this remeasure:

- `sklearn/compose/tests/test_column_transformer.py`
- `sklearn/ensemble/_hist_gradient_boosting/tests/test_binning.py`
- `sklearn/linear_model/tests/test_ransac.py`
- `sklearn/linear_model/tests/test_sgd.py`
- `sklearn/utils/tests/test_stats.py`

## Floors held

| Floor | Value |
|---|---|
| silent | **0** |
| bare exception | **0** |
| process crash | **0** |
| vendor-name special cases | none introduced |

## Provenance

| Axis | Value |
|---|---|
| Historical pin / shards | `95e58d0ff` sklearn-shard{0,1,2}.json |
| Kit sources remeasured | worktree `0f3b5a0e1` (post Delete/TupleUnpack/ClassDef/SetComp/Call) |
| scikit-learn | 1.9.0 |
| Interpreter | CPython 3.12 (recensus venv) |
| Artifact | `.receipts/5274-sklearn-factory/owner-bucket-remeasure-summary.json` |

## Dispatch order for next family PRs

1. **FunctionCallable `wraps` decorator factory floor** — 117 files (largest unlock on this set; not python.factory).
2. **FunctionCallable ImportAliasValue decorator substitution** — 20 files.
3. **StarredTupleForSugar** — 8 files / 1 locus (`name, x, *_`).
4. ClassDef keyword + non-identity decorator residuals — 2 files.
5. Try finally residual + Call residual — 1 each.
6. TemporalContext / ConstructorCall / RuntimeEffect floors — separate axes.

## Related

- #5274 this residual lane
- #5254 shape-split / family drain
- #5258 TupleUnpack leaf owns (landed)
- #5269 composite Delete (landed)
- #5233 historical 12/12 board
