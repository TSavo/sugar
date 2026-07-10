# Prosecution report: module-level assertion surface (#4024)

**Date:** 2026-07-10  
**Author:** T Savo \<evilgenius@nefariousplan.com\>  
**Part of:** #4024, #4016, #3809  
**Does not close or fix** any of those issues.

---

## Indictment

#4023 made assertion-surface enumeration **total over FUNCTION bodies**. Module-level
asserts (direct children of `Module`, not inside any `FunctionDef`) remained
outside the enumerator → Crime 1 shape `stated → ∅` (`silently_unaccounted`).

Named residual from #4023 only: pandas `expr.py:258`
`assert not intersection, _msg` (parent=`Module`).

Probe (read-only, #4026): `docs/superpowers/specs/2026-07-10-module-level-assert-surface-probe.md`.

---

## Fix (two mechanical pieces, one surface)

### 1. Enumerate — same recursive-collect at module scope

- Generalized `_iter_assertion_surfaces_in_suite(suite)` (visit Assert; recurse
  via `fragments()`; skip FunctionDef/AsyncFunctionDef/ClassDef/Lambda).
- `_iter_function_assertion_surfaces` → suite = `fn.function_body()` (unchanged
  behavior for function path).
- `_iter_module_assertion_surfaces(root)` → suite = `_module_statements(root)`.
- `build_literal_call_report` second loop: module asserts → `_lift_assert(..., fn=None)`.

### 2. Lift — module parent context (`fn=None`)

- Do **not** fold module asserts into an arbitrary FunctionDef.
- Prior-assign: when `fn is None`, only module statements before the assert line.
- No function params bound into factory ctx.
- Provenance name: `"<module>"` (mementos, contract/effect names, source audits).
- `_statement_source_locator` accepts `fn=None` → empty `param_names` for template.

No new formula sugar. No fabrication. No ratchet hardcode.

---

## Measured receipts

### Teeth (tiny fixtures)

| check | result |
|-------|--------|
| `_iter_module_assertion_surfaces` top + if/try/except; skips nested def/class | pass |
| module-only `assert not _isfinite(1)` → stated=1, silent=0, NotSugar warranted, parent=`<module>` | pass |
| module `if True: assert not _isfinite(1)` enumerated | pass |
| bad-twin: truthful module assert → sat; lying → unsat | pass |

### pandas residual `expr.py:258`

Measured against installed pandas source after the fix:

| metric | value |
|--------|-------|
| factory_walk at line 258 | `NotSugar` present (speaks) |
| `source_function_name` | `<module>` |
| dual-axis `silent_loci` containing line 258 | `[]` |
| file-level `silently_unaccounted` (expr.py census) | `0` |

(Warranted or refused-loud both count as speak; the module residual is no longer
`stated → ∅`.)

### Regression

- Nested function totality teeth (`test_nested_assertion_surface_totality.py`) still green.
- Full witness corpus (all three files): see PR body / validation paste for
  measured `55 passed` line.

---

## Files

| path | role |
|------|------|
| `.../factory/literal_call_report.py` | enumerate + module-parent lift |
| `.../factory/array_map_report.py` | memento locator allows `fn=None` |
| `.../tests/test_module_level_assertion_surface.py` | teeth + residual |
| this report | long form |

---

## Out of scope

- numpy `f2py2e.py:668` (#4025) — function-body residual after #4023, not module surface.
- New formula recognizers for shapes that refuse-loud after enumeration.
