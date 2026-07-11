# py.eq structural dual — NaN scope pin

## Watch
Python `==` is non-reflexive (`nan != nan`), so symbolic == emits `py.eq` not SMT `=`.

#4137 treats `py.eq` as an equality *atom name* for structural dual only via
`ground_term_const_equality` (term + ground value). That is sound for
`A()==3 ∧ A()==4`. It must **not** become a general `py.eq` → `=` rewrite or
reflexive identity (`py.eq(x,x)`).

## Pinned
- Doc on `is_structural_equality_atom`
- Tests: var reflexivity, single face, const-const non-orient; dual still unsat
