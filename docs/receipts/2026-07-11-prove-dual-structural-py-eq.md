# Prove dual structural for `py.eq`

## Gap
Structural "equals both" only recognized IR atomic name `=`. Python asserts
mint `py.eq`, so dual `A()==3` / `A()==4` consistency-discharged (sat).

## Fix (sugar-verifier)
`is_structural_equality_atom`: `=` | `py.eq` for:
- `collect_ground_equalities` (pre-SMT dual)
- ambient ground callsite fact collection
- `is_ground_callsite_fact_formula`

Arithmetic operator ctors still non-values (#3924).

## Verify
- Rust: `pure_callsite_py_eq_value_contradiction_refuses_structurally`
- Python: `test_callsite_binary_witnesses` → 6 passed (truthful sat, lying unsat, dual structural)
