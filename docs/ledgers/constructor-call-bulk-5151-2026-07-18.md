# ConstructorCallSugar bulk initializer receipt (#5151)

## Boundary

Measured on Python 3.12.3 with NumPy 2.5.1 and pandas 3.0.3 in the
private battleaxe worktree
`/home/tsavo/remote/fatal-corpus-constructorcall-bulk-5151`.

The #5134 list contained 23 files. `ArrowPeriodType` is excluded because its
explicit-base initializer belongs to #5126. On final current main
`397eaf1a8`, 21 of the other 22 files remain live at
`owner=ConstructorCallSugar`; `pandas/tests/window/test_numba.py` already
advanced to a distinct `FunctionCallable` panic.

## Construction

The field-only constructor fast path remains intact. A local initializer is
routed through the existing contextualized statement reducer when it contains
an assertion, assignment data flow, `If`, `Raise`, or an authenticated
zero-argument `super()` receiver calling `__init__`. Positional and keyword
initializer arguments are reduced by the ordinary call machinery.

Source-body construction also carries already-constructed class fields through
the same descriptor-safe class-field constructor used by the fast path.
Arbitrary expressions, explicit-base calls, imports, pass-only initializers,
and unsupported/inherited shapes stay loud.

No RuntimeEffect constructor or empty-success arm was added.

## Named representative replay

| Representative | Current main | Branch |
| --- | --- | --- |
| `numpy/_core/tests/test_scalarinherit.py` | ConstructorCallSugar | ConstructorCallSugar |
| `numpy/f2py/symbolic.py` | ConstructorCallSugar | loud `add(ObjectValue)` |
| `numpy/lib/tests/test_stride_tricks.py` | ConstructorCallSugar | ConstructorCallSugar |
| `pandas/core/_numba/extensions.py` | ConstructorCallSugar | completed, 15 IR rows |
| `pandas/core/arrays/arrow/array.py` | ConstructorCallSugar | loud `TemporalContext(ArrowDtype)` |
| `pandas/core/arrays/boolean.py` | ConstructorCallSugar | completed, 8 IR rows |
| `pandas/core/arrays/interval.py` | ConstructorCallSugar | ConstructorCallSugar |
| `pandas/core/arrays/period.py` | ConstructorCallSugar | ConstructorCallSugar |
| `pandas/core/dtypes/dtypes.py` | ConstructorCallSugar | ConstructorCallSugar |
| `pandas/core/groupby/grouper.py` | ConstructorCallSugar | completed, 14 IR rows |
| `pandas/io/clipboard/__init__.py` | ConstructorCallSugar | ConstructorCallSugar |
| `pandas/io/formats/excel.py` | ConstructorCallSugar | loud `AttributeSugar(_call_uncached)` |
| `pandas/io/parquet.py` | ConstructorCallSugar | ConstructorCallSugar |
| `pandas/io/sql.py` | ConstructorCallSugar | ConstructorCallSugar |
| `pandas/plotting/_matplotlib/converter.py` | ConstructorCallSugar | ConstructorCallSugar |
| `pandas/tests/arrays/categorical/test_subclass.py` | ConstructorCallSugar | ConstructorCallSugar |
| `pandas/tests/io/formats/test_console.py` | ConstructorCallSugar | completed, 5 IR rows |
| `pandas/tests/io/test_pickle.py` | ConstructorCallSugar | ConstructorCallSugar |
| `pandas/tests/scalar/timestamp/test_arithmetic.py` | ConstructorCallSugar | ConstructorCallSugar |
| `pandas/tests/tslibs/test_conversion.py` | ConstructorCallSugar | ConstructorCallSugar |
| `pandas/tests/window/test_rolling.py` | ConstructorCallSugar | completed, 103 IR rows |
| `pandas/tests/window/test_numba.py` | loud FunctionCallable | loud FunctionCallable |

Live-owner conservation:

```text
21 ConstructorCallSugar
  -> 5 completed
   + 3 advanced to distinct loud owners
   + 13 unchanged ConstructorCallSugar
   + 0 silent
```

The already-advanced `test_numba.py` row remains loud and is not counted as
movement by this branch.

## Discrimination

- A concrete initializer `If` selects and preserves the reduced branch state.
- `self` assignment followed by positional or keyword
  `super().__init__` constructs.
- Static class fields survive the source-body path and retain descriptor
  refusal.
- Explicit-base initializer calls and arbitrary expression calls remain named
  `ConstructorCallSugar` panics.
- The truthful/lying witness is file-backed; truthful is SAT and the lying twin
  is UNSAT.

## Gates

Pinned Black 26.5.1 leaves the touched Python files clean. No effect constructor
site changed, so the RuntimeEffect constructor census is not applicable.

The final provenance-matched witness and direct claim-mass tripwire outputs are
recorded in the pull request after the final branch build.

