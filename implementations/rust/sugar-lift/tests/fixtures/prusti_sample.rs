// Fixture: a representative slice of liftable #[prusti::*] annotations.
// NOT compiled (this file has no Cargo target); the lift adapter parses
// it as text via syn.

#[prusti::requires(x > 0)]
#[prusti::ensures(result >= 0)]
fn prusti_sqrt(x: i64) -> i64 {
    x
}

#[prusti_contracts::requires(n >= 0)]
fn prusti_factorial_safe(n: i64) -> i64 {
    n
}

#[prusti::ensures(result > 0)]
fn prusti_always_positive() -> i64 {
    1
}

#[prusti::invariant(x != 0)]
fn prusti_divisor(x: i64) -> i64 {
    x
}

// Deliberately skipped pattern: #[prusti::predicate] is in the v0 skip
// list and emits a structured warning.
#[prusti::predicate]
fn prusti_is_nonneg(x: i64) -> bool {
    x >= 0
}
