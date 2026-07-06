// Fixture: a representative slice of liftable #[contracts::*]
// annotations. NOT compiled; the lift adapter parses it as text via
// syn.

#[requires(x > 0)]
#[ensures(ret >= 0)]
fn contracts_sqrt(x: i64) -> i64 {
    x
}

#[contracts::requires(n >= 0)]
fn factorial_safe(n: i64) -> i64 {
    n
}

#[ensures(ret > 0)]
fn always_positive() -> i64 {
    1
}

#[invariant(x != 0)]
fn divisor(x: i64) -> i64 {
    x
}
