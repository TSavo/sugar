# #4017 vendor dual-axis coverage receipts

Battleaxe, post total assertion-surface enumeration (+ name-collision fix).

## Method

- **before_silent_approx** = count of on-disk asserts that are *not* direct
  children of FunctionDef/AsyncFunctionDef body (nested control-flow). Under the
  pre-#4017 walk these never reached `_lift_assert` → silently_unaccounted.
- **after_*** = `account_lift_coverage` against `build_literal_call_report` for
  each scanned `.py` file.

## Table

| vendor | files | stated | nested (before silent≈) | after silent | after lifted | after refused | notes |
|--------|-------|--------|-------------------------|--------------|--------------|---------------|-------|
| statistics | 1 | 4 | **3** | **0** | 4 | 0 | first indictment green |
| decimal | 1 | 0 | 0 | 0 | 0 | 0 | no asserts on disk |
| fractions | 1 | 0 | 0 | 0 | 0 | 0 | no asserts on disk |
| pathlib | 1 | 0 | 0 | 0 | 0 | 0 | no asserts on disk (3.12 shell) |
| numpy | 120 | 47 | **34** | **1** | 46 | 0 | residual: f2py2e.py:668 |
| pandas | 120 | 137 | **54** | **1** | 136 | 0 | residual: module-level expr.py:258 |

## Residual silent (follow-up indictments — not hidden)

1. **numpy `f2py2e.py:668`** — FunctionDef-body assert still un-audited after
   enumeration; path must become warranted or refused-loud.
2. **pandas `expr.py:258`** — module-level assert (parent Module); function
   surface enumerator cannot see it. Needs module assertion surfaces.
