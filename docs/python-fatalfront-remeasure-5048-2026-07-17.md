# Python fatal-frontier re-measure for #5048 (2026-07-17)

## Authoritative headline

**200 of 1,032 assertion-bearing NumPy and pandas files remain on the fatal
frontier at current head.**

The post-escalation terminal vector is:

| Terminal | Files |
|---|---:|
| Completed | **832** |
| Typed `FactoryPanic` | **181** |
| Bare exception | **15** |
| Native process crash (`SIGSEGV`) | **4** |
| Loud-bounded timeout at 300 seconds | **0** |
| **Assertion-bearing total** | **1,032** |

Conservation holds exactly: `832 + 181 + 15 + 4 + 0 = 1,032`. No row is silently
reclassified as complete, and no panic or refusal was changed by this
measurement.

## Measurement boundary and provenance

- Git snapshot: `ac0343f17c28086f86adc49b19cf64ee0481e3e9`
- Remote host: battleaxe
- Remote execution: three concurrent shards, sequential children within each
  shard
- Instrument:
  `implementations/python/sugar-lift-py-tests/scripts/corpus_fatal_triage.py`
- Discovery bound: 10 seconds per assertion-bearing file
- Escalation bounds for the seven discovery timeouts: 60, 120, then 300 seconds
- Corpus packages: NumPy 2.5.1 and pandas 3.0.3
- Remote private environment: Python 3.12.3; no shared `.venv` or
  `.mint-venv` was modified
- Provenance-matched release `sugar` SHA-256:
  `1726fecd5bb1bcd1e1c236072f254c1377df0654e51a56634aff967cbe5c5262`

The current checkout was synchronized to battleaxe before both the release
build and the corpus pass. Main advanced five times during measurement through
16 intervening commits, including Python-engine changes. Every superseded
result set was discarded; each time
the branch and remote source were rebased, the release binary was rebuilt, and
the complete corpus plus timeout escalation was rerun. Only the snapshot above
is represented below. The first `bin/bcargo` attempt encountered the
known sugarbin shelf-miss/build-fallback failure before Cargo ran; the release
binary was therefore built directly in the synchronized remote Rust workspace.
The three triage lanes were launched through `BCARGO_FORCE_REMOTE=1 bin/brun`.

Corpus census:

| Axis | Count |
|---|---:|
| Python files | 1,828 |
| Files without assertions | 796 |
| Files with assertions | **1,032** |
| Assertions in AST census | 20,769 |

## Delta from the #4775 recensus

The comparison boundary is
`docs/python-corpus-fatal-recensus-4775-2026-07-17.md`, whose 10-second vector
was `481 completed / 245 typed panic / 13 bare exception / 293 timeout`.
The current figures below include escalation of every current discovery
timeout, so that the remaining frontier is authoritative rather than a
provisional timeout blob.

| Axis | #4775 | Current | Delta |
|---|---:|---:|---:|
| Completed | 481 | **832** | **+351** |
| Typed `FactoryPanic` | 245 | **181** | **-64** |
| Bare exception | 13 | **15** | **+2** |
| Native process crash | 0 | **4** | **+4** |
| Loud timeout | 293 | **0** | **-293** |
| Remaining frontier | 551 | **200** | **-351** |

Typed-owner counts do not move monotonically with the typed-panic total:
construction work retires old owners while formerly timed-out files expose new
typed terminals. The ranked current owner ledger below is the dispatch
authority.

## Ranked typed fatal owners

The following 31 owner buckets account for all 181 typed-panic files after
escalation.

| Rank | Owner | Files | Representative files |
|---:|---|---:|---|
| 1 | `TemporalContext` | **64** | `numpy/_core/tests/test_scalar_methods.py`; `numpy/_core/tests/test_simd.py`; `numpy/_core/tests/test_strings.py` |
| 2 | `ConstructorCallSugar` | **25** | `numpy/lib/tests/test_format.py`; `pandas/core/_numba/extensions.py`; `pandas/core/arrays/arrow/extension_types.py` |
| 3 | `SequentialDigBody` | **13** | `pandas/tests/indexes/datetimes/test_arithmetic.py`; `pandas/tests/io/sas/test_xport.py`; `pandas/tests/tseries/offsets/test_business_hour.py` |
| 4 | `subscript` | **9** | `pandas/tests/arithmetic/test_datetime64.py`; `pandas/tests/indexes/datetimes/test_datetime.py`; `pandas/tests/indexes/timedeltas/test_join.py` |
| 4 | `RuntimeEffect` | **9** | `pandas/tests/frame/methods/test_truncate.py`; `numpy/lib/tests/test_function_base.py`; `pandas/tests/frame/methods/test_replace.py` |
| 6 | `multiply` | **8** | `numpy/lib/tests/test_shape_base.py`; `pandas/tests/arithmetic/test_timedelta64.py`; `pandas/tests/indexes/test_common.py` |
| 7 | `WithSugar` | **5** | `numpy/_core/tests/test_arrayprint.py`; `pandas/tests/util/test_util.py`; `pandas/tests/io/formats/style/test_style.py` |
| 7 | `ImportAliasValue` | **5** | `pandas/tests/internals/test_api.py`; `pandas/tests/scalar/timestamp/test_constructors.py`; `numpy/_core/tests/test_deprecations.py` |
| 9 | `FunctionCallable` | **4** | `numpy/ma/tests/test_extras.py`; `pandas/tests/frame/test_subclass.py`; `pandas/tests/series/test_subclass.py` |
| 10 | `bitwise_or` | **3** | `pandas/core/arrays/sparse/array.py`; `pandas/core/arrays/base.py`; `numpy/f2py/tests/test_array_from_pyobj.py` |
| 10 | `add` | **3** | `pandas/tests/extension/decimal/test_decimal.py`; `pandas/core/window/rolling.py`; `pandas/tests/groupby/test_reductions.py` |
| 10 | `truth` | **3** | `numpy/_core/tests/test_numeric.py`; `numpy/testing/tests/test_utils.py`; `pandas/tests/io/test_http_headers.py` |
| 10 | `WhileSugar` | **3** | `pandas/io/sas/sas7bdat.py`; `pandas/io/stata.py`; `pandas/io/parsers/python_parser.py` |
| 10 | `RaiseSugar` | **3** | `numpy/f2py/tests/test_symbolic.py`; `pandas/io/html.py`; `pandas/tests/test_errors.py` |
| 15 | `ForSugar.static_unfold` | **2** | `numpy/_core/tests/test_dtype.py`; `numpy/_core/tests/test_scalarmath.py` |
| 15 | `divide` | **2** | `pandas/tests/indexes/timedeltas/test_arithmetic.py`; `pandas/tests/reductions/test_reductions.py` |
| 15 | `ImportAliasValue.truth` | **2** | `pandas/tests/computation/test_compat.py`; `pandas/tests/extension/test_arrow.py` |
| 15 | `ForElseSugar` | **2** | `pandas/_version.py`; `numpy/_core/tests/test_mem_overlap.py` |
| 15 | `ForSugar` | **2** | `pandas/core/reshape/reshape.py`; `numpy/_core/tests/test_cpu_features.py` |
| 15 | `FormatDunderCallSugar` | **2** | `pandas/tests/scalar/test_na_scalar.py`; `pandas/tests/io/formats/test_to_string.py` |
| 15 | `python.factory` | **2** | `pandas/core/computation/scope.py`; `pandas/tests/test_register_accessor.py` |
| 22 | `WithSugar manager result` | **1** | `numpy/_core/tests/test_overrides.py` |
| 22 | `subtract` | **1** | `numpy/testing/_private/utils.py` |
| 22 | `AttributeSugar` | **1** | `pandas/tests/extension/test_common.py` |
| 22 | `left_shift` | **1** | `numpy/_core/tests/test_half.py` |
| 22 | `modulo` | **1** | `numpy/polynomial/tests/test_classes.py` |
| 22 | `pandas/core/internals/managers.py:1399:34` | **1** | `pandas/core/internals/managers.py` |
| 22 | `bitwise_xor` | **1** | `pandas/core/ops/array_ops.py` |
| 22 | `floor_divide` | **1** | `pandas/tests/scalar/timedelta/test_arithmetic.py` |
| 22 | `bitwise_invert` | **1** | `pandas/tests/computation/test_eval.py` |
| 22 | `CallSiteValue.truth` | **1** | `pandas/tests/groupby/aggregate/test_other.py` |

The locus-named `pandas/core/internals/managers.py:1399:34` row still needs a
stable semantic owner before dispatch. It remains counted and loud.

## Timeout escalation ledger

| File | Final verdict | Bound | Elapsed | Owner |
|---|---|---:|---:|---|
| `pandas/tests/io/test_stata.py` | bare exception | 300s | 84.895s | — |
| `numpy/ma/tests/test_core.py` | bare exception | 60s | 2.753s | — |
| `numpy/random/tests/test_random.py` | completed | 120s | 93.325s | — |
| `pandas/tests/dtypes/test_dtypes.py` | typed panic | 60s | 25.410s | `RuntimeEffect` |
| `numpy/_core/tests/test_shape_base.py` | completed | 60s | 35.456s | — |
| `numpy/random/tests/test_generator_mt19937.py` | completed | 60s | 47.224s | — |
| `numpy/random/tests/test_randomstate.py` | native crash | 120s | 65.114s | — |

No current identity remains timed out at 300 seconds, and no successful lift
needed a bound above 120 seconds. The two former timeout rows that exposed bare
exceptions and the one that exposed a native crash remain fatal frontier mass.

## Bare-exception ledger

The 15 bare exceptions remain frontier mass and are not folded into typed
owner counts.

| Exception | Files | Identities |
|---|---:|---|
| `RecursionError: maximum recursion depth exceeded` | **2** | `numpy/_core/tests/test_function_base.py`; `pandas/core/util/hashing.py` |
| `KeyError: 'numpy._core'` | **3** | `numpy/_core/tests/test_longdouble.py`; `numpy/_core/tests/test_multithreading.py`; `numpy/_core/tests/test_stringdtype.py` |
| `KeyError: 'numpy.random'` | **1** | `numpy/random/_examples/cffi/extending.py` |
| `TypeError: ... expected, got cython_function_or_method` | **7** | `pandas/tests/scalar/period/test_period.py`; `pandas/tests/scalar/timedelta/methods/test_as_unit.py`; `pandas/tests/scalar/timedelta/test_timedelta.py`; `pandas/tests/scalar/timestamp/methods/test_as_unit.py`; `pandas/tests/scalar/timestamp/methods/test_replace.py`; `pandas/tests/scalar/timestamp/test_timestamp.py`; `pandas/tests/tseries/frequencies/test_freq_code.py` |
| `TypeError: cannot unpack non-iterable function object` | **1** | `pandas/tests/io/test_stata.py` |
| `TypeError: 'dict_itemiterator' object cannot be interpreted as an integer` | **1** | `numpy/ma/tests/test_core.py` |

## Native crash ledger

Four child processes terminated with `SIGSEGV`. They remain distinct crash
frontier mass; they are neither bare Python exceptions nor bounded timeouts.

| File | Signal | Last visible class |
|---|---|---|
| `pandas/tests/series/test_formats.py` | `SIGSEGV` | install-source dig recursion |
| `pandas/tests/tseries/offsets/test_fiscal.py` | `SIGSEGV` | lift child |
| `pandas/tests/strings/test_strings.py` | `SIGSEGV` | lift child |
| `numpy/random/tests/test_randomstate.py` | `SIGSEGV` | iterative block/call reduction |

## Dispatch rule

This ledger is a current-head map, not permission to infer a fix from an owner
name. Every lane must replay its named representative against then-current
main before implementation. Decidable shapes must construct; genuine runtime
dependence may cross the sealed runtime-effect door; all other missing
construction remains a typed panic. Completed files, typed panics, bare
exceptions, and bounded timeouts stay disjoint terminal classes.
