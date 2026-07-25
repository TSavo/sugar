# Pass 3 board — pandas control-effect census @ `d94f67a31`

**Authority:** provisional checkpoint reconstruction  
**Source:** `.sugar/pandas-four-axis-census-d94f67a31/control-effect/checkpoint.jsonl`  
**Rows:** 1415 / 1415 (full manifest)  
**Lease:** completed/findings; `measuredCommit=d94f67a3149ea2aceee4f9a8cff0397b6f6d374a`  
**Machine board:** `pass3-board.json` beside the checkpoint on battleaxe

## Honest classification (from checkpoint, not pre-Merkle numbers)

### File outcomes
| category | files |
|----------|------:|
| completed | 635 |
| **backend-defect** | **780** |

### Stop-the-line instrument defect
**780 files** failed with:

```text
ValueError: 'dynamic-export' is not a valid WithConstructionGapKind
```

This is **not** residual silence. Export-resolution kinds rode into
`ContextManagerResolutionConstructionGap` without enum membership. Construction
With mass is **understated** until this is fixed and the axis is re-measured.

### Construction residuals (among completed files only)
| family | count |
|--------|------:|
| ContextManagerResolutionConstructionGap | 65 |
| SugarNotWritten | 38 |
| UnsupportedWithBindingTarget | 4 |
| ConstructedValueTestimonyNotWritten | 4 |

**CM membrane axes (R_cm_* sums):** assertion 3 · protocol-resource 8 · derived 0  
**With partition (from families + cm keys, completed only):**
- assertion-related: **3**
- resource-related: **104** (incl. 65 CM resolution + 31 other-manager + 8 protocol)
- other: **4**

→ Construction endgame is still **With**, but the **true** With count requires
re-census after the dynamic-export instrument fix (780 files re-enter the board).

### Desugar residuals (occurrence totals)
| | |
|--|--:|
| **R_desugar** | **2508** |
| AttributeStoreRuntimeEffect | 753 |
| RaiseEffect | 738 |
| NameErrorEffect | 386 |
| SubscriptStoreRuntimeEffect | 296 |
| DynamicUnpackAssignSugar.desugar | 291 |
| (store-matching keys sum) | **1340** |

**Desugar construction panics (list length):** **359** across **15 owners**  
| owner | n |
|-------|--:|
| contains | 215 |
| attribute | 94 |
| guarded | 20 |
| ground_index_error | 7 |
| SetValue.contains | 5 |
| add / multiply / … | rest |

These are **typed Floor gaps** (“write more Floor”), not one amorphous 1074-blob
from another instrument. Distinct mechanisms → rank and drain by owner mass.
**contains + attribute** are ~86% of measured desugar construction panics.

**Desugar defects (list length):** **143**  
| shape | n |
|-------|--:|
| ContractConditionalConstructionV1 missing attr | 49 |
| conditional-expression arm NotImplementedError | 44 |
| **ExitSet has no attribute value** | **26** (#6285 family) |
| SourceFragment.compare_le | 11 |
| Incomplete has no value | 3 |
| other | rest |

## Pass 3 priority decision

| Priority | Item | Why |
|----------|------|-----|
| **0** | Fix `WithConstructionGapKind` for `dynamic-export` (+ safe parse) | 780/1415 files instrument-crashed; construction board is incomplete |
| **1** | Re-aggregate construction With after fix (or focused re-census) | Exact assertion vs resource counts for dispatch |
| **2** | Floor mechanisms: **contains** (215) then **attribute** (94) | Majority of desugar construction panics; typed product gaps |
| **3** | **ExitSet.value** / term-position (#6285) | Live correctness defect among desugar defects |
| **4** | With drain — two contracts, one ExitSet algebra | After true With mass is known |
| **5** | Store desugar (1340) by measured owners | AttributeStore / SubscriptStore / DynamicUnpack |
| **6** | Remaining desugar defect families | Conditional construction, etc. |
| **7** | Full re-census pandas → NumPy under authenticated identity (#6290) | Bank ΔR |

## With design (unchanged)
Two semantic verbs, one control mechanism:
1. **Assertion / effect-boundary With**
2. **Resource / protocol With**

## Notes on prior board numbers
User-reported 5,021 With / 1,074 desugar panics may reflect a different
occurrence reader or pre-instrument-fix projection. **This pass-3 board uses
checkpoint list lengths and R_* sums only.** After priority-0 fix, re-measure
before claiming With partition mass.

## Suite identity
#6290 landed on main (`df408100e`). Suite reports can now be authoritative when
identity resolves. Re-run suite after lease quiet; authenticate receipts only
on exact reconstructability.
