# Probe: module-level assertion surface (read-only)

**Date:** 2026-07-10  
**Author:** T Savo \<evilgenius@nefariousplan.com\>  
**Part of:** #4016, #4013, #4024  
**Status:** read-only probe — do **not** edit `literal_call_report.py` while #4023 is open  
**Cite for residuals:** #4023 only (no invented line numbers)

---

## Why this probe exists

#4023 makes assertion enumeration total over **FUNCTION** bodies (nested
if/try/for/with/match + name-collision fix). Its corpus receipts leave two
residuals:

| residual (from #4023 only) | surface |
|----------------------------|---------|
| numpy `f2py2e.py:668` — still un-audited after function totality | function-body residual → indictment [#4025](https://github.com/TSavo/sugar/issues/4025) |
| pandas `expr.py:258` — module-level assert (parent=`Module`) | **this surface** → indictment [#4024](https://github.com/TSavo/sugar/issues/4024) |

This note names the **module-level** seam so prosecution after #4023 merges can
build cleanly. No code changes here.

---

## Where module-level asserts get enumerated today

**They don't.** The lift path only enumerates asserts under functions.

### Seam (post-#4023 shape — read on branch `part-4017-lift-statistics-isfinite`)

File: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory/literal_call_report.py`

**1. Collect function defs only**

```text
local_function_defs = [
    frag for frag in root_frag.walk()
    if frag.observed in {"FunctionDef", "AsyncFunctionDef"}
]
```

**2. For each function, recursive Assert collect**

```text
_iter_function_assertion_surfaces(fn)
  → visit every Assert under fn.function_body()
  → recurse via frag.fragments() through if/try/for/with/match/…
  → skip nested FunctionDef / AsyncFunctionDef / ClassDef / Lambda
    (those scopes are their own def entries)
```

**3. Lift only those**

```text
for fn in local_function_defs:
    for stmt in _iter_function_assertion_surfaces(fn):
        _lift_assert(stmt, fn=fn, …, module_statements=module_statements, …)
```

There is **no** second loop over module-body statements that feeds Assert nodes
into `_lift_assert`.

### What `_module_statements` does (and does not)

```text
_module_statements(root_frag)
  → list of top-level module statements
```

Used as **prior-assignment context** when lifting asserts *inside* functions
(`_prior_assignment_sites` walks `module_statements` then `fn.function_body()`).
It is **not** an assertion enumeration source. A module-level `Assert` sitting
in that list is never selected for lift.

### Confirmed drop

A module-level assert (direct child of `Module`, not any `FunctionDef`) has:

- no entry in `local_function_defs` as an assert surface parent  
- no visit from `_iter_function_assertion_surfaces` (requires FunctionDef)  
- no alternate `_lift_assert` call site in `build_literal_call_report`

Independent dual-axis census still **states** it → Crime 1 shape
`stated → ∅` (`silently_unaccounted`). #4023 residual: pandas `expr.py:258`.

---

## Seam for the future fix — same pattern, module scope

### Enumeration: same recursive-collect pattern at module scope

**Not a wholly separate collector algorithm.** Reuse the #4023 visit pattern:

| piece | function surface (#4023) | module surface (needed) |
|-------|--------------------------|-------------------------|
| root of walk | `fn.function_body()` | module body statements (`_module_statements(root_frag)` or equivalent root suite) |
| collect | `Assert` nodes | same |
| recurse | `frag.fragments()` through control-flow | same (module can host if/try at top level too) |
| skip | FunctionDef / AsyncFunctionDef / ClassDef / Lambda | **same skip set** — those scopes already enumerated via `local_function_defs` |

A thin `_iter_module_assertion_surfaces(root)` (or generalize
`_iter_function_assertion_surfaces` to “assertion surfaces under this suite,
skipping nested scopes”) is the clean shape: **same recursive pattern,
applied at module scope**.

### Lift parent: module is a distinct *context*, not a second crime

`_lift_assert` currently requires `fn: SourceFragment` (FunctionDef) for:

- dig / prior-assign (`_prior_assignment_sites` uses `fn.function_body()`)  
- factory build context keyed on the enclosing function  

So the **enumeration hole** is module-scope collect; the **lift adaptation** is
module-as-parent (or optional `fn=None` / module surface) so priors use only
module statements before the assert line — without inventing a fake FunctionDef.

That is one surface (module-level asserts), two mechanical pieces:

1. **Enumerate** — same recursive collect at module scope.  
2. **Lift** — existing assert door with module parent context (not a new formula
   sugar; not fabrication).

Do **not** fold module asserts into an arbitrary FunctionDef to “reuse”
`fn=` — that would lie about provenance.

---

## Out of scope for this probe

- **numpy `f2py2e.py:668`** — #4023 says this is a FunctionDef-body assert that
  remains silent *after* function totality. Separate indictment #4025; not the
  module-level hole.
- Editing `literal_call_report.py` while #4023 is open — forbidden; this probe
  is read-only.
- Invented residual counts beyond #4023’s sample tables.

---

## Hand-off for prosecution (#4024, after #4023 merges)

1. Land #4023 (function totality) first — do not race edits to the same file.  
2. Add module-scope Assert enumeration (same recursive pattern + nested-scope skip).  
3. Wire `_lift_assert` (or thin wrapper) with module parent / prior-assign.  
4. Prove `expr.py:258` speaks (warranted or refused-loud); ratchet residual
   silent for that locus off the wall without hardcoding green.  
5. Optional teeth: tiny fixture with module-level `assert` only — must appear in
   stated and leave `silently_unaccounted` only if still dropped.

---

## Links

| ref | role |
|-----|------|
| [#4023](https://github.com/TSavo/sugar/pull/4023) | Function-body totality; measured residuals (only numbers cited) |
| [#4024](https://github.com/TSavo/sugar/issues/4024) | Prosecute module-level assertion surface (pandas `expr.py:258` + any module-level) |
| [#4025](https://github.com/TSavo/sugar/issues/4025) | Prosecute numpy `f2py2e.py:668` function-body residual |
| [#4016](https://github.com/TSavo/sugar/issues/4016) | Minority Report campaign epic |
| [#4013](https://github.com/TSavo/sugar/issues/4013) | Dual-axis / silent residue instrument |
