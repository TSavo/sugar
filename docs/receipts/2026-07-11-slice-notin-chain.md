# Slice / NotIn / chained compare floors

## Shipped
1. **SliceSubscriptSugar** — `x[a:b:c]` → `py.slice_subscript` coordinate
2. **NotInOpSugar** — `not in` → `not(py.in(...))`
3. **ChainedCompareSugar** — `a < b < c` → conjunction of pairwise atoms

## Suite (itsdangerous sdist)
See PR for measured lifted/refused after ship.
