# Residual small-front validation for #5174

This ledger replays the five identities named by #5174 on branch
`fleet/5174-small-fronts` (receipt commit after amend) with Python 3.14.4,
NumPy 2.5.0, and pandas 3.0.3. A verdict in this document is authoritative only
for that measured tree. Prior sibling pin `bc32c5a10` (NumPy 2.5.1) recorded the
same disposition vector; this pin re-validates the three completes and the
loud 60s/300s timeouts on current main-line code.

## Disposition vector

| disposition | count |
| --- | ---: |
| completed singleton identities | 3 |
| loud timeout at 300 seconds | 2 |
| typed panic | 0 |
| bare exception | 0 |
| silent / empty success | 0 |

Conservation is `5 = 3 completed + 2 loud timeout + 0 silent`.

## Per-front ledger

| historical identity | current disposition | recognizer route / evidence |
| --- | --- | --- |
| `pandas/tests/frame/test_subclass.py` via `pandas/core/frame.py:130:15` | completed in 30.69s | Production `lift_file_payload` completes with 60 facts. Three named, genuinely-runtime `GetattrRuntimeEffect` rows remain; none is ground and none weakens the sealed runtime-effect door. Historical locus-named `RaiseValue` projection is no longer a top-level terminal. |
| `numpy/f2py/f2py2e.py:642:23` | completed in 6.46s | `IfSugar` selects `BoolOpSugar`, which short-circuits before `SubscriptSugar` and `InequalityOpSugar` demand the empty-list `[-1]` exceptional face. The file-backed truthful/lying witness pins this native route (`sat`/`unsat`). |
| `pandas/core/internals/managers.py:1399:34` | completed in 11.12s | Factory-selected `SubscriptSugar` / `MethodCallSugar` route retains the native `BlockPlacement.append` call coordinate; no inline AST predicate and no runtime effect is introduced. 98 facts, zero effects. |
| `pandas/tests/frame/test_block_internals.py` | timeout at 60s and 300s | still loud (subprocess `TimeoutExpired`). Prior 30s faulthandler sample was active in `TupleForSugar -> ForSugar._unfold_static -> IfSugar -> PredicateValue.binary_conditional`, repeatedly mapping a deep `GuardedValue`. Guarded-branch expansion, not a missing source-shape recognizer. |
| `pandas/tests/io/test_stata.py` | timeout at 60s and 300s | still loud (subprocess `TimeoutExpired`). Prior 30s faulthandler sample was in `copy._reconstruct` during source construction. No evidence warrants calling this complete or manufacturing a shape match. |

## Timeout measurements

| file | 60s (this pin) | 300s (this pin) |
| --- | ---: | ---: |
| `pandas/tests/frame/test_block_internals.py` | timeout (60.12s wall) | timeout (300.67s wall) |
| `pandas/tests/io/test_stata.py` | timeout (60.07s wall) | timeout (300.09s wall) |

Both timeouts remain frontier mass. They are bounded externally by the triage
instrument and were never swallowed, converted to an effect, or counted as
completion. The stack samples name the next performance/budget owners without
inventing recognizers:

- guarded-value branch expansion beneath finite loop replay;
- residual source-copy reconstruction in the Stata path.

## Factory doctrine receipt

No production recognizer was added in this lane because all three native
singleton shapes already route through factory-selected owners on current
main. In particular, this lane adds no `isinstance(ast.*)` chain, no bespoke
`_is_*` / `_matches_*` predicate, no ground runtime effect, and no empty-success
arm.

What retired: the three locus-named singleton `RaiseValue`/`Projection`
owner fronts (`frame.py:130:15`, `f2py2e.py:642:23`, `managers.py:1399:34`)
as residual #5174 mass — they complete under existing factory recognizers.
What stayed loud: the two @300s timeouts (honest non-termination / budget
frontier, not constructed green).
