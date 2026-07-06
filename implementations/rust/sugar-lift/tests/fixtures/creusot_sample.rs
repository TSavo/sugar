// Fixture: a representative slice of liftable #[creusot::*] annotations.
// NOT compiled (this file has no Cargo target); the lift adapter parses
// it as text via syn.

#[creusot::requires(x > 0)]
#[creusot::ensures(result >= 0)]
fn creusot_sqrt(x: i64) -> i64 {
    x
}

#[creusot_contracts::requires(n >= 0)]
fn creusot_factorial_safe(n: i64) -> i64 {
    n
}

#[creusot::ensures(result > 0)]
fn creusot_always_positive() -> i64 {
    1
}

#[creusot::invariant(x != 0)]
fn creusot_divisor(x: i64) -> i64 {
    x
}

// Deliberately skipped pattern: #[creusot::law] is in the v0 skip list
// and emits a structured warning.
#[creusot::law]
fn creusot_lemma() {}
