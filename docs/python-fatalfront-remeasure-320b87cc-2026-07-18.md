# Python fatal-frontier re-measure at `320b87cc` (2026-07-18)

## Authoritative headline

**220 of 1,032 assertion-bearing NumPy and pandas files remain on the fatal
frontier at pinned commit
`320b87cc13375bbdb887e57d1ff4a46100767390`.**

The post-escalation terminal vector is:

| Terminal | Files |
|---|---:|
| Completed | **812** |
| Typed `FactoryPanic` | **190** |
| Bare exception | **28** |
| Native process crash | **0** |
| Loud-bounded timeout at 300 seconds | **2** |
| **Assertion-bearing total** | **1,032** |

Conservation holds exactly: `812 + 190 + 28 + 0 + 2 = 1,032`. No row is silently
reclassified as complete, and no panic or refusal was changed by this
measurement.

Machine ledger (authoritative numbers + ranked owners + escalation rows):

- `docs/ledgers/recensus-1032-live/merged-post-escalation.json`
- Discovery merge: `docs/ledgers/recensus-1032-live/merged.json`
- Per-shard receipts: `docs/ledgers/recensus-1032-live/shard{0,1,2}.json`
- Escalation detail: `docs/ledgers/recensus-1032-live/timeout-escalation.json`

## Measurement boundary and provenance

- Git snapshot: `320b87cc13375bbdb887e57d1ff4a46100767390` (`origin/main` at measure time)
- Measured UTC: `2026-07-18T01:58:38Z` (post-escalation merge)
- Discovery started UTC: `2026-07-18T01:18:27Z`
- Remote host: battleaxe
- Remote workspace:
  `/home/tsavo/remote/fatal-recensus-refresh-320b87cc/sugar`
- Private venv: `.venv-recensus` (not shared `.venv` / `.mint-venv`)
- Corpus packages: NumPy **2.5.1**, pandas **3.0.3**
- Python: **3.12.3**
- Instrument:
  `implementations/python/sugar-lift-py-tests/scripts/corpus_fatal_triage.py`
- Layout: three concurrent shards (`--shard-count 3`), sequential children
  within each shard
- Discovery bound: **10 seconds** per assertion-bearing file
- Escalation bounds for the nine discovery timeouts: **60, 120, then 300**
  seconds

This supersedes the #5048 pin
(`docs/python-fatalfront-remeasure-5048-2026-07-17.md` at
`ac0343f17…`) as the live dispatch map for current main.

## Corpus census

| Axis | Count |
|---|---:|
| Python files | 1,828 |
| Files without assertions | 796 |
| Files with assertions | **1,032** |
| Assertions in AST census | 20,769 |

## Discovery (10s) then post-escalation

| Terminal | Discovery @10s | Post-escalation |
|---|---:|---:|
| Completed | 806 | **812** |
| Typed `FactoryPanic` | 189 | **190** |
| Bare exception | 28 | **28** |
| Process crash | 0 | **0** |
| Loud timeout | 9 | **2** |
| Fatal frontier | 226 | **220** |

Escalation of the nine discovery timeouts:

| Discovery timeouts | Final terminal |
|---:|---|
| 6 | completed |
| 1 | typed `FactoryPanic` (`TemporalContext`) |
| 2 | still timeout @300s |

## Delta vs the #5048 pin (`ac0343f17`)

| Axis | #5048 pin | Current (`320b87cc`) | Delta |
|---|---:|---:|---:|
| Completed | 832 | **812** | **−20** |
| Typed `FactoryPanic` | 181 | **190** | **+9** |
| Bare exception | 15 | **28** | **+13** |
| Native process crash | 4 | **0** | **−4** |
| Loud timeout | 0 | **2** | **+2** |
| Remaining frontier | 200 | **220** | **+20** |

The 200-file pin is **stale**. Main advanced through construction, dig, and
report lanes (including #5078/#5104 paint law, #5117 guarded dig, import-alias
report coordinates, and related Python-engine work). Re-measure is required;
the prior pin must not be used as live `R`.

Notable composition shifts:

- All four prior `SIGSEGV` crash rows are gone (crash mass **0**).
- Bare-exception mass grew (+13), dominated by relative-import `package=`
  failures and the cython-function isinstance class.
- Two identities remain loud timeouts at 300s (see ledger below); they are
  not folded into completed or typed.

Between `ac0343f17` and `320b87cc` there are **27** commits on main; this
document does not invent a per-commit attribution. The exact authority is the
vector at the pinned SHA above.

## Ranked typed fatal owners

The following **37** owner buckets account for all **190** typed-panic files
after escalation. Owner counts do not move monotonically with the typed total:
construction retires old owners while formerly completed or timed-out files
expose new typed terminals.

| Rank | Owner | Files | Representative files |
|---:|---|---:|---|
| 1 | `TemporalContext` | **58** | `numpy/f2py/tests/test_crackfortran.py`; `pandas/core/arrays/string_arrow.py`; `pandas/core/generic.py` |
| 2 | `AppendCallSugar` | **26** | `pandas/io/common.py`; `pandas/io/formats/format.py`; `pandas/tests/indexes/multi/test_reshape.py` |
| 3 | `ConstructorCallSugar` | **23** | `pandas/core/_numba/extensions.py`; `pandas/core/arrays/arrow/extension_types.py`; `pandas/core/arrays/period.py` |
| 4 | `multiply` | **7** | `numpy/_core/tests/test_simd.py`; `numpy/_core/tests/test_indexing.py`; `numpy/lib/tests/test_nanfunctions.py` |
| 5 | `ImportAliasValue` | **6** | `pandas/tests/internals/test_api.py`; `pandas/tests/scalar/timestamp/test_constructors.py`; `numpy/_core/tests/test_deprecations.py` |
| 6 | `RuntimeEffect` | **5** | `pandas/tests/extension/uuid/test_uuid.py`; `pandas/tests/groupby/test_apply.py`; `pandas/tests/io/excel/test_readers.py` |
| 7 | `FunctionCallable` | **4** | `numpy/ma/tests/test_extras.py`; `pandas/_testing/asserters.py`; `pandas/tests/io/test_feather.py` |
| 7 | `RaiseSugar` | **4** | `pandas/core/indexes/period.py`; `pandas/core/indexes/base.py`; `numpy/f2py/tests/test_symbolic.py` |
| 7 | `SequentialDigBody` | **4** | `pandas/core/indexing.py`; `pandas/tests/arrays/categorical/test_astype.py`; `pandas/tests/config/test_localization.py` |
| 7 | `add` | **4** | `pandas/tests/extension/decimal/test_decimal.py`; `pandas/core/window/rolling.py`; `pandas/tests/groupby/test_reductions.py` |
| 7 | `WithSugar` | **4** | `pandas/tests/util/test_util.py`; `pandas/tests/io/formats/style/test_style.py`; `pandas/tests/io/excel/test_xlrd.py` |
| 12 | `CallSiteValue.truth` | **3** | `numpy/_core/tests/test_scalar_methods.py`; `numpy/lib/tests/test_format.py`; `pandas/tests/groupby/aggregate/test_other.py` |
| 12 | `bitwise_or` | **3** | `pandas/core/arrays/sparse/array.py`; `pandas/core/arrays/base.py`; `numpy/f2py/tests/test_array_from_pyobj.py` |
| 12 | `truth` | **3** | `numpy/_core/tests/test_numeric.py`; `numpy/testing/tests/test_utils.py`; `pandas/tests/io/test_http_headers.py` |
| 12 | `WhileSugar` | **3** | `pandas/io/sas/sas7bdat.py`; `pandas/io/stata.py`; `pandas/io/parsers/python_parser.py` |
| 16 | `ForSugar.static_unfold` | **2** | `numpy/_core/tests/test_dtype.py`; `numpy/_core/tests/test_scalarmath.py` |
| 16 | `bitwise_and` | **2** | `numpy/random/tests/test_smoke.py`; `pandas/core/indexes/datetimes.py` |
| 16 | `unary_minus` | **2** | `pandas/tests/arithmetic/test_datetime64.py`; `pandas/tests/arithmetic/test_timedelta64.py` |
| 16 | `divide` | **2** | `pandas/tests/extension/base/methods.py`; `pandas/tests/reductions/test_reductions.py` |
| 16 | `floor_divide` | **2** | `pandas/tests/indexes/timedeltas/test_arithmetic.py`; `pandas/tests/scalar/timedelta/test_arithmetic.py` |
| 16 | `ForElseSugar` | **2** | `pandas/_version.py`; `numpy/_core/tests/test_mem_overlap.py` |
| 16 | `ForSugar` | **2** | `pandas/core/reshape/reshape.py`; `numpy/_core/tests/test_cpu_features.py` |
| 16 | `ImportAliasValue.truth` | **2** | `pandas/tests/computation/test_compat.py`; `pandas/tests/extension/test_arrow.py` |
| 16 | `FormatDunderCallSugar` | **2** | `pandas/tests/scalar/test_na_scalar.py`; `pandas/tests/io/formats/test_to_string.py` |
| 16 | `bitwise_invert` | **2** | `pandas/tests/tools/test_to_numeric.py`; `pandas/tests/computation/test_eval.py` |
| 16 | `python.factory` | **2** | `pandas/core/computation/scope.py`; `pandas/tests/test_register_accessor.py` |
| 27 | `WithSugar manager result` | **1** | `numpy/_core/tests/test_overrides.py` |
| 27 | `subtract` | **1** | `numpy/testing/_private/utils.py` |
| 27 | `AttributeSugar` | **1** | `pandas/tests/extension/test_common.py` |
| 27 | `.venv-recensus/lib/python3.12/site-packages/pandas/core/frame.py:130:15` | **1** | `pandas/tests/frame/test_subclass.py` |
| 27 | `left_shift` | **1** | `numpy/_core/tests/test_half.py` |
| 27 | `numpy/f2py/f2py2e.py:642:23` | **1** | `numpy/f2py/f2py2e.py` |
| 27 | `modulo` | **1** | `numpy/polynomial/tests/test_classes.py` |
| 27 | `pandas/core/internals/managers.py:1399:34` | **1** | `pandas/core/internals/managers.py` |
| 27 | `bitwise_xor` | **1** | `pandas/core/ops/array_ops.py` |
| 27 | `subscript` | **1** | `pandas/io/parsers/c_parser_wrapper.py` |
| 27 | `GetattrBuiltinSugar` | **1** | `pandas/tests/arrays/categorical/test_operators.py` |

Locus-named owners (site-package path / `f2py2e.py` / `managers.py`) still need
stable semantic owners before dispatch. They remain counted and loud.

Vs #5048 owner ranks (dispatch-relevant shifts only):

| Owner | #5048 | Current | Note |
|---|---:|---:|---|
| `TemporalContext` | 64 | **58** | still #1 |
| `AppendCallSugar` | (not top) | **26** | new large owner |
| `ConstructorCallSugar` | 25 | **23** | still large |
| `SequentialDigBody` | 13 | **4** | dig lanes reduced mass |
| `subscript` | 9 | **1** | residual-path work reduced mass |
| `RuntimeEffect` | 9 | **5** | ground residual retirement |

## Timeout escalation ledger

Nine identities timed out at the 10s discovery bound. Escalation used 60s,
then 120s, then 300s.

| File | Final verdict | Bound | Owner |
|---|---|---:|---|
| `pandas/core/dtypes/cast.py` | completed | 60s | — |
| `pandas/tests/io/test_sql.py` | typed panic | 60s | `TemporalContext` |
| `pandas/tests/dtypes/test_dtypes.py` | completed | 60s | — |
| `pandas/tests/io/pytables/test_store.py` | completed | 60s | — |
| `numpy/random/tests/test_generator_mt19937.py` | completed | 60s | — |
| `numpy/random/tests/test_randomstate.py` | completed | 120s | — |
| `numpy/random/tests/test_random.py` | completed | 300s | — |
| `pandas/tests/frame/test_block_internals.py` | **timeout** | 300s | — |
| `pandas/tests/io/test_stata.py` | **timeout** | 300s | — |

### Remaining loud timeouts @300s

These two stay on the frontier as bounded timeouts. They are not completed,
not typed panics, and not bare exceptions.

1. `pandas/tests/frame/test_block_internals.py`
2. `pandas/tests/io/test_stata.py`

Further bound increases are optional and must remain loud if they still hang.

## Bare-exception ledger

The **28** bare exceptions remain frontier mass and are not folded into typed
owner counts.

| Exception | Files | Identities |
|---|---:|---|
| `TypeError: the 'package' argument is required to perform a relative import for '.overrides'` | **15** | `numpy/lib/tests/test_shape_base.py`; `numpy/linalg/tests/test_regression.py`; `pandas/tests/apply/test_frame_apply.py`; `pandas/tests/arrays/string_/test_string.py`; `pandas/tests/frame/test_reductions.py`; `numpy/_core/tests/test_memmap.py`; `numpy/lib/tests/test_function_base.py`; `numpy/ma/tests/test_core.py`; `numpy/_core/tests/test_function_base.py`; `numpy/_core/tests/test_multiarray.py`; `numpy/_core/tests/test_nditer.py`; `numpy/_core/tests/test_shape_base.py`; `numpy/linalg/_linalg.py`; `numpy/linalg/tests/test_linalg.py`; `numpy/ma/core.py` |
| `TypeError: … expected, got cython_function_or_method` | **7** | `pandas/tests/scalar/period/test_period.py`; `pandas/tests/scalar/timestamp/methods/test_replace.py`; `pandas/tests/tseries/frequencies/test_freq_code.py`; `pandas/tests/scalar/timedelta/test_timedelta.py`; `pandas/tests/scalar/timestamp/methods/test_as_unit.py`; `pandas/tests/scalar/timedelta/methods/test_as_unit.py`; `pandas/tests/scalar/timestamp/test_timestamp.py` |
| `KeyError: 'numpy._core'` | **3** | `numpy/_core/tests/test_longdouble.py`; `numpy/_core/tests/test_multithreading.py`; `numpy/_core/tests/test_stringdtype.py` |
| `TypeError: the 'package' argument is required to perform a relative import for '.numerictypes'` | **1** | `numpy/_core/tests/test_arrayprint.py` |
| `KeyError: 'numpy.random'` | **1** | `numpy/random/_examples/cffi/extending.py` |
| `RecursionError: maximum recursion depth exceeded` | **1** | `pandas/core/util/hashing.py` |

## Native crash ledger

**None.** Process-crash mass is 0 after escalation (was 4 at the #5048 pin).

## Dispatch rule

This ledger is a pinned-commit map, not permission to infer a fix from an owner
name. Every lane must replay its named representative against then-current
main before implementation. Decidable shapes must construct; genuine runtime
dependence may cross the sealed runtime-effect door; all other missing
construction remains a typed panic. Completed files, typed panics, bare
exceptions, and bounded timeouts stay disjoint terminal classes.

Live residual is typed B (owner ledger above), not stopwatches. The two @300s
timeouts are measurement incompleteness, not a stopwatch-driven construction
target.

## How to re-measure

From a release `sugar` on the pin SHA, with NumPy 2.5.1 and pandas 3.0.3
importable:

```bash
# three shards @10s discovery
python implementations/python/sugar-lift-py-tests/scripts/corpus_fatal_triage.py \
  --shard-count 3 --shard-index N --file-timeout 10 \
  --out docs/ledgers/recensus-1032-live/shardN.json

# escalate any timeout-or-hang rows at 60 / 120 / 300
# merge into docs/ledgers/recensus-1032-live/merged-post-escalation.json
```

Future readers must compare `git log <this-pin>..origin/main` for Python-lift
lanes as an estimate only. The exact authority remains **220 at
`320b87cc13375bbdb887e57d1ff4a46100767390`** until the next full recensus.
