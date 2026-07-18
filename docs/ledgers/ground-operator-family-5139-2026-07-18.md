# Ground operator family receipt (#5139)

Current-main validation at `b6c101d3e` found 18 live operator terminals:

| owner | live |
| --- | ---: |
| `bitwise_or` | 3 |
| `bitwise_and` | 2 |
| `bitwise_invert` | 1 |
| `bitwise_xor` | 1 |
| `left_shift` | 1 |
| `add` | 4 |
| `floor_divide` | 2 |
| `modulo` | 1 |
| `unary_minus` | 2 |
| `subtract` | 1 |

The older `NoneValue.bitwise_invert` row already completed on current main and
was not counted.

## Construction

- Concrete zero divisors construct a source-cited `ZeroDivisionError`
  exceptional exit.
- Boolean `&` and `~` use Python's exact ground semantics.
- `PredicateValue | SymbolicValue` preserves the exact symbolic operator
  coordinate.
- An already-selected exceptional exit propagates through floor division.

No RuntimeEffect constructor was added. Static native coordinates and
runtime-only call results still panic or remain at their pre-existing loud
runtime boundary.

## Conservation

| disposition | files |
| --- | ---: |
| completed | 3 |
| advanced to a distinct loud owner | 2 |
| unchanged loud | 13 |
| silent | 0 |
| total | 18 |

Completed:

- `numpy/random/tests/test_smoke.py`
- `pandas/core/arrays/base.py`
- `pandas/tests/indexes/timedeltas/test_arithmetic.py`

Advanced loud:

- `pandas/core/arrays/sparse/array.py`: `bitwise_or` to
  `TemporalContext(fill_value)`
- `pandas/tests/computation/test_eval.py`: `bitwise_invert` to
  `unary_minus(TrueBoolLiteralSugar)`

The bounded discrimination suite passes 28 tests, including all ground folds,
both zero-divisor exits, and a native-coordinate bad twin for each operator.
The real solver witness is truthful SAT and lying UNSAT.

The direct claim-mass tripwire result is 4 passed and the known current-main
requests regression failed at `cookies.py:147` (`ConstructorCallSugar`). The
four non-requests pins are green and this slice changes none of their pinned
fixtures.
