# #4017 Prosecution Report — total assertion-surface enumeration

**Branch:** `part-4017-lift-statistics-isfinite`  
**Worktree:** `.worktrees/4017-statistics-silent-isfinite`  
**Author:** T Savo \<evilgenius@nefariousplan.com\>  
**Part of:** #4017, #4016, #3809  

## Diagnosis (recap)

Silent residue was **not** an `_isfinite` formula gap. `assert not _isfinite(...)`
already lifts via `NotSugar` → `CallTruthAssertionSugar` when presented.

Drop site: `build_literal_call_report` only walked **direct** `FunctionDef.body`
children, so nested asserts under if/try/except/for/with/match never reached
`_lift_assert`. Second totality hole: assert enumeration used a **bare-name**
`local_functions` map, so duplicate method names (`__init__`/`apply`/…) dropped
all but one def's asserts.

## Fix (option A)

1. **`_iter_function_assertion_surfaces(fn)`** — recursive collect of every
   `Assert` under a function via `SourceFragment.fragments()`, skipping nested
   FunctionDef/ClassDef/Lambda (own surfaces).
2. **Enumerate every FunctionDef/AsyncFunctionDef fragment** from `walk()`, not
   unique bare names. Dig map remains name-keyed for call resolution.
3. **Peel `UnaryOp`/`Not` in `_factory_assertion_derived_context`** so dig of
   `assert not callee(...)` matches plain `assert callee(...)` (teeth; not a new
   formula sugar).

No new formula recognizer. No reducer/inline bypass. No ratchet hardcode.

## Receipts (battleaxe, `BCARGO_REMOTE_ROOT=…/sugar-bcargo-4017-isfinite`)

### Statistics (first indictment)

| | stated | lifted | refused | silently_unaccounted |
|--|--------|--------|---------|----------------------|
| **before** (#4015 / top-level-only) | 4 | 1 | 0 | **3** |
| **after** | 4 | 4 | 0 | **0** |

Nested `assert not _isfinite` at `_sum` / `_ss` / `_exact_ratio` now warranted
via `NotSugar`. Ratchet
`test_statistics_majority_silent_unaccounted_gate_is_zero` **GREEN** because
silent loci empty — ratchet body untouched.

### Bad-twin (solo-per-test)

```
test_nested_not_isfinite_bad_twin_flips_via_witness PASSED
  truthful: nested `assert not _isfinite(1)` + body `return False` → sat
  lying:    nested `assert not _isfinite(1)` + body `return True`  → unsat
```

### Structural

- nested if/except assert enumerated + warranted  
- same-name methods each keep their asserts  
- control-flow collector skips nested def  

### Test runs (battleaxe)

```
test_nested_assertion_surface_totality.py + test_lift_coverage_harness.py + test_not_sugar.py
============================== 24 passed in 2.93s ==============================

test_sugar_witness_instruments.py
============================== 45 passed in 35.96s ==============================
```

(Witness instrument suite is currently 45 tests; older “55/55” notes refer to a
prior corpus size. R-vectors in that suite remain zero-enrolled.)

### Corpus-wide vendor dual-axis (literal_call_report path, first N py files)

| vendor | files | stated | nested (before silent≈) | after silent | after lifted | after refused |
|--------|-------|--------|-------------------------|--------------|--------------|---------------|
| statistics | 1 | 4 | **3** | **0** | 4 | 0 |
| decimal | 1 | 0 | 0 | 0 | 0 | 0 |
| fractions | 1 | 0 | 0 | 0 | 0 | 0 |
| pathlib | 1 | 0 | 0 | 0 | 0 | 0 |
| numpy (sample 120) | 120 | 47 | **34** | **1** | 46 | 0 |
| pandas (sample 120) | 120 | 137 | **54** | **1** | 136 | 0 |

**Loud prior-silent-loss findings (campaign scaling):**

- **numpy:** ~34 nested asserts were invisible under the old walk; after totality,
  46/47 spoken. Residual **1 silent**: `f2py2e.py:668`
  `assert len(flib_flags) <= 2, repr(...)` — top-level FunctionDef assert that
  still does not emit a source-audit locus (not refused-loud). Follow-up
  indictment: that lift path must speak (warranted or refused).
- **pandas:** ~54 nested + name-collision losses; after totality 136/137 spoken.
  Residual **1 silent**: `expr.py:258` `assert not intersection, _msg` — **module
  body** assert (parent=`Module`), outside FunctionDef surface. Follow-up:
  module-level assertion surfaces.
- **decimal / fractions / pathlib** (stdlib single-module files on battleaxe
  3.12): zero `assert` statements on disk → silent 0 both before and after
  (no nested residue to enfranchise).

Do **not** hide the residual silent=1 rows: they are real next indictments, not
proof the gate is fully green corpus-wide.

## Files touched

- `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory/literal_call_report.py`
- `implementations/python/sugar-lift-py-tests/tests/test_nested_assertion_surface_totality.py` (new)
- `implementations/python/sugar-lift-py-tests/tests/test_lift_coverage_harness.py` (headline after-fix)
- diagnosis/receipts under `docs/superpowers/specs/`
