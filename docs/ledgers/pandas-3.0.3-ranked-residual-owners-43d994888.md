# Ranked residual owners — pandas 3.0.3

Commit `43d9948881df3906aa4b99977f8ab14b4fc951f5`, corpus pin `bbb70a76f4032eda…`, 1421 files.

> **What this ranks, and what it refuses to.** Ranked by the dispatchable unit
> — `(owner × category)` — off one pinned baseline at one commit. Nothing is
> extrapolated from a sample and nothing is compared against the 1,415-file
> ledger, which is a different pandas.
>
> **The factoring-gap term is UNCLASSIFIED here and that is not a zero.** The
> `#6364` classifier produces its verdict as data on the exception; this census
> was stringifying the message and discarding it, so all 13 occurrences reached
> the ledger unclassified. The wiring is committed (`27e9e9a92`) and the split
> will be measured on the next run. It is reported as unmeasured rather than
> guessed.


## Denominator

```
enrolled                 1421
terminalRows             1421
completed                1415
corpusManifestCid        sha256:c267d971bb2d1a3dd65769bb76ce6efec080803fea51df3964353e8c9f073c03
missingFiles             []
duplicateFiles           []
malformedRows            []
complete                 True
```

## stableZero vector

`controlEffectStableZero` = **False**, `red` = **True**

```
completedDenominatorPositive     True
denominatorComplete              True
timeouts                         0
constructionPanics               0
factoringGaps                    13
unresolvableDispatchTargets      0
backendDefectFiles               4
desugarConstructionPanics        140
desugarDefects                   15
```

- 6 per-file terminal defect rows
- 140 desugar construction panics (construction-law None arms -- red, and never semantic R)
- 15 desugar defects
- 6 of 1421 enrolled files produced a terminal row that is not a completion (denominator is complete; the completion count is not)

## R_desugar is two numbers

Total 9952 = **58 owed work** + 9894 accounted semantics. Publishing the total as work overstates it by **171.6x**.

### Owed work, by owner

```
    29  YieldSuspensionSugar.desugar
    17  YieldFromSugar.desugar
    11  matches_raise_effect
     1  ClassDefinitionSugar.desugar
```

## Desugar construction panics, by (owner × files)

```
    44  in   30 files  guarded
    15  in   14 files  ground_index_error
    12  in   10 files  ContractConditionalConstructionV1.and_then
    12  in   10 files  outcome_to_exitset
    11  in   10 files  add
     8  in    7 files  bitwise_and
     7  in    7 files  attribute
     6  in    5 files  RuntimeEffect
     6  in    4 files  multiply
     5  in    5 files  subtract
     2  in    2 files  bitwise_invert
     2  in    2 files  bitwise_or
     2  in    2 files  ground_type_error
     1  in    1 files  collection build
     1  in    1 files  ground_assertion_error
     1  in    1 files  bitwise_xor
     1  in    1 files  truth
     1  in    1 files  divide
     1  in    1 files  unary_plus
     1  in    1 files  dict.subscript
```

## Factoring gaps

```
    13  UNCLASSIFIED (ledger predates #6364 classifier)
```

## Backend defects, by shape (not by file)

```
     4  spans.LineTable.line_col
     2  SourceCallBindingGap
```

## Site prevalence — a DENOMINATOR, never R

```
 27751  site:function-def
  7662  site:with-item
  7652  site:with-statement
   688  site:try-statement
```

Construction R over the whole corpus: **4**.

