# Python corpus fatal-file triage for #4684 (2026-07-16)

## Measurement boundary

- Sugar source: `45e2bdee21dccc25fd1f04b3db768cbca85a82e5`
- Python: 3.14.4 in worktree-local `.venv-triage`
- NumPy: 2.5.1
- pandas: 3.0.3
- black: 26.5.1
- Instrument:
  `implementations/python/sugar-lift-py-tests/scripts/corpus_fatal_triage.py`

The parent AST-censuses the installed packages and starts a fresh child Python
process for every assertion-bearing file. A file counts as completed only when
`lift_file_payload` returns a completed payload. Exceptions, panics, signals,
transport deaths, and timeouts remain terminal; the instrument never emits or
counts a partial report.

The bulk run uses a 30-second per-file boundary. Its two timeout rows were
retried after the other workers stopped: `numpy/ma/tests/test_core.py` reached
its typed `FormatDunderCallSugar` FactoryPanic in 20.6 seconds, while
`pandas/tests/dtypes/test_dtypes.py` completed normally in 52.2 seconds. The
adjudicated table below records those actual terminal outcomes. The raw JSON
therefore remains reproducible without mislabeling host contention as a product
hang.

## Corpus arithmetic

| Axis | NumPy | pandas | Total |
|---|---:|---:|---:|
| Python files | 407 | 1,421 | **1,828** |
| Assertions in AST census | 3,226 | 17,543 | **20,769** |
| Files with assertions | 142 | 890 | **1,032** |
| Completed payloads | 45 | 411 | **456** |
| Failed loudly, no report | 97 | 479 | **576** |

`456 + 576 = 1,032`; every assertion-bearing file has exactly one terminal
classification.

## Ranked terminal categories

| Rank | Category | Files | Representative files | Likely owner |
|---:|---|---:|---|---|
| 1 | Typed factory construction panic | **570** | `numpy/_core/tests/test__exceptions.py`; `pandas/core/arrays/_mixins.py`; `pandas/core/apply.py` | Python Sugar/Floor construction owner named by each panic |
| 2 | Unsupported/bare exception | **6** | `numpy/_core/tests/test_function_base.py`; `numpy/_core/tests/test_longdouble.py`; `pandas/tests/tseries/offsets/test_offsets.py` | Python kit exception routing / runtime-boundary construction |
| 3 | Process crash or overflow (`SIGSEGV`, `SIGABRT`, allocator abort) | **0** | none | no live native-overflow sub-front measured |
| 4 | Transport disconnect | **0** | none | no live RPC/transport sub-front measured |
| 5 | Genuine timeout or hang after serial adjudication | **0** | none | no live hang sub-front measured |

The six bare exceptions are four `KeyError('numpy._core')` rows
(`test_longdouble.py`, `test_multiarray.py`, `test_multithreading.py`, and
`test_stringdtype.py`), one `RecursionError` (`test_function_base.py`), and one
`RuntimeError` for a runtime attribute-name boundary
(`pandas/tests/tseries/offsets/test_offsets.py`). They remain loud and emit no
partial report.

## Ranked typed construction fronts

The first panic is the terminal owner for a file. Owner totals group all
observed/requested fingerprints for that owner; exact-front totals preserve the
full fingerprint.

| Rank | Owner family | Files |
|---:|---|---:|
| 1 | `TemporalContext` missing value binding | **241** |
| 2 | `multiply` floor | **46** |
| 3 | `WithSugar` context-manager construction | **35** |
| 4 | `RaiseSugar` exception construction | **27** |
| 5 | `add` floor | **26** |
| 6 | `subscript` floor | **18** |
| 7 | `ConstructorCallSugar` | **17** |
| 8 | `append_with` floor | **16** |
| 9 | `MethodChainSugar` receiver construction | **15** |
| 10 | `python.factory` unsupported AST statement | **13** |

Largest exact fronts:

| Files | Typed fingerprint | Representative files |
|---:|---|---|
| **47** | `TemporalContext / Floor / Construction / result / value` | `pandas/io/parsers/base_parser.py`; `pandas/tests/frame/methods/test_select_dtypes.py` |
| **40** | `multiply / Floor / Construction / ListValue / stand on the multiplication floor` | `numpy/f2py/symbolic.py`; `pandas/tests/apply/test_frame_apply.py` |
| **33** | `TemporalContext / Floor / Construction / lib / value` | `pandas/tests/copy_view/test_astype.py`; `pandas/tests/frame/test_query_eval.py` |
| **31** | `WithSugar / Floor / Construction / raise-carrying callsite with-body / dig manager().__exit__ exception suppression contract` | `numpy/f2py/tests/test_f2py2e.py`; `pandas/tests/config/test_config.py` |
| **15** | `TemporalContext / Floor / Construction / _d / value` | `numpy/_core/tests/test_datetime.py`; `numpy/_core/tests/test_dtype.py` |
| **15** | `MethodChainSugar / Floor / Construction / unclassified chained-call receiver` | `pandas/plotting/_matplotlib/timeseries.py`; `pandas/tests/window/test_rolling.py` |

## Correction to #3732/#4680

The earlier in-process recensus reported 577 fatal files with 567
`FactoryPanic`, four 30-second timeouts, four `KeyError`, one `RecursionError`,
and one `RuntimeError`. Fresh-process replay plus serial timeout adjudication
corrects that to:

| Failure | Old | Current | Correction |
|---|---:|---:|---:|
| Typed FactoryPanic | 567 | **570** | +3 |
| Timeout/hang | 4 | **0** | -4 |
| KeyError | 4 | **4** | 0 |
| RecursionError | 1 | **1** | 0 |
| RuntimeError | 1 | **1** | 0 |
| **All fatal files** | **577** | **576** | **-1** |

The old 4,317 universe-absence rows remain a lower bound, not a whole-corpus
total: 576 files still halt before any report exists. This triage does not
weaken the factory, verifier, or report boundary and does not manufacture
partial output for those files.

## Reproduction

From the worktree-local editable install:

```bash
python implementations/python/sugar-lift-py-tests/scripts/corpus_fatal_triage.py \
  numpy --compact --output target/triage/numpy.json

for shard in 0 1 2 3; do
  python implementations/python/sugar-lift-py-tests/scripts/corpus_fatal_triage.py \
    pandas --shard-count 4 --shard-index "$shard" --compact \
    --output "target/triage/pandas-$shard.json"
done
```

The four pandas shards are deterministic partitions of the same sorted package
file list. Run them concurrently only when the host has capacity; retry every
bulk timeout alone before assigning a product category.

## Retirement paths

This PR adds an auditor over an open vendor boundary; it does not lower `R`.
Each typed panic already names its construction owner and requested floor. The
top three independent construction fronts are split into available follow-on
issues. The auditor can retire only when a stronger corpus runner records the
same per-file signal/exception testimony and deterministic front aggregation
without allowing a fatal producer to emit a report.
