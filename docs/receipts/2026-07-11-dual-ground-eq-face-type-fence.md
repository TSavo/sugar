# DualGroundEqFace — type-system fence for py.eq dual

## Idea
Cut NaN / non-reflexivity loss off at the **type system**: dual structural
equality is not a bool predicate on atom names; it is a typed oriented face.

## Types
- `DualTerm` / `DualValue` — halves of a dual face
- `DualGroundEqFace` — sole construction via `try_from_atomic`
  - atom name `=` | `py.eq`
  - **and** `ground_term_const_equality` orientation
- `record_ground_equality(face: DualGroundEqFace, …)` — no free `&Json` pair

## Impossible without going through the door
- `py.eq(x, x)` reflexivity as structural identity
- treating bare `py.eq` as general `=` rewrite
- recording dual without term+value orientation

## Tests
`dual_ground_eq_face_is_sole_construction_door` + prior py_eq_* pins
