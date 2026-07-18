# Python bare-exception identity audit (#5101)

## Scope and provenance

This is the bounded revalidation of the 15 bare-exception identities recorded
at `ac0343f17`.  The pre-change replay was run from current-main commit
`303a542190ba80cb17ee93ba13ca7282cdaaa90b` with Python 3.14.4, NumPy 2.5.0,
pandas 3.0.3, and Black 26.5.1.  Each file ran alone with a 300 second ceiling;
the two files that did not reach a terminal remain explicit timeouts rather
than inferred successes.

Pre-change current-main vector:

| terminal | files |
|---|---:|
| bare `RecursionError` | 2 |
| bare nested-module `KeyError` | 4 |
| bare Cython `TypeError` | 7 |
| loud bounded timeout at 300s | 2 |

## Root causes and construction

Three decidable boundaries leaked Python exceptions:

1. Constructor method enumeration eagerly rebuilt the same constructor class.
   A build-set guard now ends a recursive constructor graph in a named
   `ConstructorCallSugar / recursive-constructor-method` panic.
2. `PathFinder.find_spec` was passed the fully-qualified child name together
   with the parent's search path.  Nested installed-source and native-extension
   lookup now passes the child component, so lookup does not import or depend
   on `sys.modules` parents.
3. `inspect.getsource` raises `TypeError`, not `OSError`, for Cython extension
   methods.  Such methods now remain coordinate-only instead of leaking a
   Python exception.

The second `RecursionError` was a recursive install-source dig in pandas
hashing.  Callsite cycle keys now use the existing heap-backed term-table CID
writer instead of recursive dataclass `repr`, and simultaneously nested dig
demands have an eight-level structural budget.  Exceeding it is the named
`CallSiteValue.add / callsite value demand budget exhausted` panic; deep valid
terms remain heap-bounded and are not rejected.

No runtime-effect constructor was added or widened.

## Per-file disposition

| file | current disposition | evidence / next named owner |
|---|---|---|
| `numpy/_core/tests/test_function_base.py` | promoted to named panic | `ConstructorCallSugar / recursive-constructor-method` |
| `pandas/core/util/hashing.py` | promoted to named panic | `CallSiteValue.add / callsite value demand budget exhausted` |
| `numpy/_core/tests/test_longdouble.py` | constructed | completes; 9/9 assertions cited |
| `numpy/_core/tests/test_multithreading.py` | constructed | completes; 5 cited + 18 loud refused |
| `numpy/_core/tests/test_stringdtype.py` | promoted to named panic | advances to `multiply / ListValue` |
| `numpy/random/_examples/cffi/extending.py` | constructed | nested native identity resolves; 1 loud refused, silent 0 |
| `pandas/tests/scalar/period/test_period.py` | constructed | Cython method stays coordinate-only; 284 cited + 1 refused |
| `pandas/tests/scalar/timedelta/methods/test_as_unit.py` | constructed | completes; 29/29 assertions cited |
| `pandas/tests/scalar/timedelta/test_timedelta.py` | promoted to named panic | advances to `divide / NativeCallableValue` |
| `pandas/tests/scalar/timestamp/methods/test_as_unit.py` | constructed | completes; 28/28 assertions cited |
| `pandas/tests/scalar/timestamp/methods/test_replace.py` | constructed | completes; 29/29 assertions cited |
| `pandas/tests/scalar/timestamp/test_timestamp.py` | constructed | completes; 257 cited + 3 refused |
| `pandas/tests/tseries/frequencies/test_freq_code.py` | constructed | completes; 4/4 assertions cited |
| `pandas/tests/io/test_stata.py` | drained from bare cohort; explicit timeout | no bare exception reproduced; still loud at the 300s local ceiling |
| `numpy/ma/tests/test_core.py` | promoted to named panic | advances to `ImportAliasValue / numpy._core.umath` |

The post-change vector is 9 completed, 5 named `FactoryPanic`, 1 explicit
bounded timeout, and **0 bare exceptions**.

## Conservation and focused receipts

The nine completed files contain 668 stated assertions: 645 are lifted/cited,
23 are loud refusals, and `silently_unaccounted = 0`.

Focused regressions cover:

- 5,000-deep callsite cycle-key construction through the iterative CID writer;
- the nested-dig budget's named panic;
- recursive constructor-method ownership;
- nested native-extension lookup without imported parents;
- Cython method source refusal as coordinate-only;
- nested source lookup without imported parents.

The runtime-effect constructor audit remains green:
`CONSTRUCTOR_SITES FAILED 0`.  Existing runtime effects in completed vendor
files were not created or changed by this lane.
