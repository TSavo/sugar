# Prosecution report: numpy f2py2e.py:668 residual (#4025)

**Date:** 2026-07-10  
**Author:** T Savo \<evilgenius@nefariousplan.com\>  
**Part of:** #4025, #4016, #3809  
**Does not close or fix** any of those issues.

---

## Diagnosis (instrumented — not guessed)

#4023 made function-body assertion enumeration total. Residual #4025 is **not**
an enumeration hole.

| stage | measured on installed numpy `f2py2e.py` |
|-------|------------------------------------------|
| enclosing function | `run_compile` line 592 — in `local_function_defs` |
| surfaces under `run_compile` | `[(668, 4)]` — collected |
| assert form | `assert len(flib_flags) <= 2, repr(flib_flags)` — 2-arg, `LtE` |
| catalog | `ComparisonAssertionSugar` **owns** the shape |
| mini fixture (param only) | factory_walk warranted; silent=0 |
| full file before fix | factory_walk **empty at 668**; silent_loci=`[668]` |

**Where it fell silent:** `_needed_prior_assignment_sites` expands free name
`flib_flags` through mutator history (`sys.argv = …` at **line 625**). That
prior folds Incomplete → `_prior_assignment_effect_lift` emits
`PriorAssignmentTypedEffect` **only at locus 625**. Dual-axis accounting keys
on-disk asserts by **(file, line, col)** of the assert → 668 never cited →
Crime 1 `stated → ∅`.

**Ruled out:**

1. 2-arg assert form — msg is irrelevant; mini with msg lifts.
2. `len(x) <= N` unowned — catalog owns it; bare free-name build succeeds.
3. Function not in `local_functions` — `run_compile` is present; surface listed.

**Bare-ctx proof (no prior fold):**

```text
ComparisonAssertionSugar(
  operator='LtE',
  left=call:len(flib_flags),
  right=2,
)
```

So the shape **can** lift when free names stay free.

---

## Fix (factory surface)

In `_lift_assertion_via_factory`:

1. Try assertion ctx **with** prior fold (unchanged best-effort reduce).
2. On `_PriorAssignmentEffect`: **retry bare** ctx (function params only, no
   prior fold). Symbolic comparison sugars own free-name shapes.
3. If bare also fails: prior effect **at prior locus** (preserves existing
   prior-assignment teeth) **and** cite the assertion via source memento at
   the assert span so dual-axis cannot leave `stated → ∅`.

No new formula sugar. No fabrication. No ratchet hardcode.

---

## Measured receipts

### Residual

| locus | after fix |
|-------|-----------|
| `f2py2e.py:668` | `ComparisonAssertionSugar` warranted on factory_walk |
| dual-axis silent at 668 | `[]` |
| file `silently_unaccounted` | `0` |
| IR | `f2py2e::run_compile::assert:668:4::assertion` |

### Teeth

| check | result |
|-------|--------|
| 2-arg `assert len(x) <= 2, repr(x)` stated+warranted | pass |
| mutator prior chain does not silence assert | pass |
| LtE bad-twin (catalog witness shape) sat/unsat flip | pass |
| prior-assignment effect still at assignment locus | pass (regression) |

### Witness corpus

See PR body for measured `55 passed` line (run once).

---

## Files

| path | role |
|------|------|
| `.../factory/literal_call_report.py` | bare-retry + assert cite on prior block |
| `.../tests/test_f2py2e_len_comparison_residual.py` | teeth + residual |
| this report | long form |
