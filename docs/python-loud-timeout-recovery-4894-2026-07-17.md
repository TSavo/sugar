# Loud-timeout identity recovery for #4894

## Result

The deleted 53-file identity residual is recovered and replayed on
post-#4941/#4945 current main.  The canonical ledger now conserves every row:

| Verdict | Files |
|---|---:|
| `completes-at-bound` | 146 |
| `completes-with-panic` | 146 |
| `bare-exception` | 1 |
| `hang-at-max-bound` | 0 |
| **Total** | **293** |

The recovered 53 split is 26 completions, 26 typed construction panics, and
one `KeyError` bare exception.  Every recovered row terminated at the
60-second bound.  There are no new performance candidates and no genuine
300-second hangs.

## Recovery method

The recensus committed the count but deleted the filename artifact.  A direct
rerun could not reproduce membership because the original 10-second boundary
was host-load-dependent: the same pinned snapshot on an uncontended Python
3.14.4 Mac produced only 29 timeouts.

Recovery therefore used repeated identity testimony, never calibrated timing
as a verdict:

1. Preserve all 17 missing identities in the committed first-shard seed.
2. Preserve all 12 additional identities from the pinned local 10-second
   snapshot replay.
3. Run repeated, three-shard snapshot-only discovery on battleaxe and rank
   remaining candidates by independent timeout observations.
4. Select the 24 strongest repeated candidates with a deterministic filename
   tie-break, yielding exactly the missing 53 identities.
5. Replay those 53 against current optimized main at 60/120/300 seconds.

The recovery set is:

```text
numpy/_core/tests/test_datetime.py
numpy/_core/tests/test_multiarray.py
numpy/_core/tests/test_nditer.py
numpy/_core/tests/test_numeric.py
numpy/_core/tests/test_umath.py
numpy/f2py/crackfortran.py
numpy/lib/tests/test_function_base.py
numpy/lib/tests/test_io.py
numpy/linalg/_linalg.py
numpy/ma/core.py
numpy/random/tests/test_generator_mt19937.py
numpy/random/tests/test_random.py
numpy/random/tests/test_randomstate_regression.py
numpy/random/tests/test_regression.py
numpy/testing/_private/utils.py
pandas/core/array_algos/take.py
pandas/core/groupby/generic.py
pandas/core/reshape/merge.py
pandas/core/strings/accessor.py
pandas/io/formats/style.py
pandas/io/parsers/base_parser.py
pandas/tests/frame/indexing/test_where.py
pandas/tests/frame/methods/test_combine_first.py
pandas/tests/frame/methods/test_drop.py
pandas/tests/frame/methods/test_info.py
pandas/tests/frame/methods/test_quantile.py
pandas/tests/frame/methods/test_reindex.py
pandas/tests/frame/methods/test_rename.py
pandas/tests/frame/methods/test_reset_index.py
pandas/tests/frame/methods/test_sort_index.py
pandas/tests/frame/test_query_eval.py
pandas/tests/frame/test_stack_unstack.py
pandas/tests/frame/test_subclass.py
pandas/tests/groupby/test_categorical.py
pandas/tests/groupby/test_timegrouper.py
pandas/tests/indexes/multi/test_constructors.py
pandas/tests/indexes/multi/test_indexing.py
pandas/tests/indexes/multi/test_integrity.py
pandas/tests/indexes/multi/test_reindex.py
pandas/tests/indexes/multi/test_setops.py
pandas/tests/indexing/multiindex/test_loc.py
pandas/tests/indexing/multiindex/test_setitem.py
pandas/tests/io/excel/test_openpyxl.py
pandas/tests/io/excel/test_readers.py
pandas/tests/io/formats/style/test_html.py
pandas/tests/io/formats/style/test_style.py
pandas/tests/io/formats/style/test_to_latex.py
pandas/tests/plotting/frame/test_frame.py
pandas/tests/resample/test_resample_api.py
pandas/tests/strings/test_extract.py
pandas/tests/strings/test_split_partition.py
pandas/tests/strings/test_strings.py
pandas/tests/test_expressions.py
```

## Dispatchable hidden-panic ranking

The canonical summary folds all 146 hidden panics into ordinary fatal-frontier
owner buckets:

| Rank | Owner | Files |
|---:|---|---:|
| 1 | `TemporalContext` | 40 |
| 2 | `RuntimeEffect` | 33 |
| 3 | `SequentialDigBody` | 18 |
| 4 | `FunctionCallable` | 13 |
| 5 | `multiply` | 8 |
| 6 | `ImportAliasValue` | 4 |
| 7 | `WithSugar` | 4 |
| 8 | `ConstructorCallSugar` | 3 |
| 9 | `RaiseSugar` | 2 |
| 10 | `append_with` | 2 |
| 11 | `FormatDunderCallSugar callsite receiver` | 1 |
| 12 | `WithSugar manager result` | 1 |
| 13 | `add` | 1 |
| 14 | `bitwise_invert` | 1 |
| 15 | `bitwise_or` | 1 |
| 16 | `bitwise_xor` | 1 |
| 17 | `delitem` | 1 |
| 18 | `install_source_dig` | 1 |
| 19 | `pandas/tests/frame/methods/test_reset_index.py:536:19` | 1 |
| 20 | `pandas/tests/frame/test_query_eval.py:1110:13` | 1 |
| 21 | `pandas/tests/indexes/interval/test_indexing.py:350:14` | 1 |
| 22 | `pandas/tests/indexes/interval/test_interval.py:179:8` | 1 |
| 23 | `pandas/tests/indexes/multi/test_analytics.py:111:10` | 1 |
| 24 | `pandas/tests/indexes/period/test_setops.py:339:17` | 1 |
| 25 | `pandas/tests/indexes/test_base.py:646:15` | 1 |
| 26 | `pandas/tests/indexing/multiindex/test_loc.py:846:10` | 1 |
| 27 | `pandas/tests/reshape/concat/test_datetimes.py:108:19` | 1 |
| 28 | `power` | 1 |
| 29 | `subtract` | 1 |

The JSON summary remains the machine-readable dispatch surface, including
exact fingerprints and representative files.
