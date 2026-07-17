# Equality vocabulary #4371 — adjudicated + residual closed

## Ruling (T, 2026-07-13)

Neither `=` nor `py.eq` is the global vocabulary. Equality resolves **per atom**
at construction, by sort warrant:

1. **Same-sort warrant** → FOL `=` (exact; no loss).
2. **Int vs Real** → stated `py.eq` + explicit `py.eq(x,y) → to_real(x)=y`
   promotion bridge. No Number supersort.
3. **Opaque / overridable `__eq__`** → stated `py.eq`, no silent rewrite.

FOL `=` is denotation; Python `==` is computation. They coincide only when
sorts prove they do.

## Door

- `resolve_equality_atom` in
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/equality_atom.py`
- Entered from `FloorValue.equals` / `OpaqueOpCallsite.equals`
- Entered from `ChainedCompareSugar` Eq/NotEq pairs (residual of #4383 closed
  here: chain no longer hardcodes `py_eq`)

## Instruments

- `tests/test_equality_per_atom.py` — three arms + reverse mixed order +
  typed `Eq` fence + chained door + static R(chained_eq_hardcode_py_eq)=0
- Prior: `test_py_atoms.py`, DualGroundEqFace pins (structural dual scope only)

## Shell deleted

The chain helper's hardcoded `py_eq` / `not_(py_eq)` for Eq/NotEq — the last
construction path that ignored the #4371 table after #4383.
