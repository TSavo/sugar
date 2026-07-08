import Mathlib

set_option autoImplicit false

theorem sugar_obligation : ∀ (x : Int), (((x > 0) ∧ (x < 10)) -> (x > 0)) := by
  aesop

#print axioms sugar_obligation
