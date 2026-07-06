// Fixture: a representative slice of liftable #[flux::sig] annotations.
// NOT compiled (this file has no Cargo target); the lift adapter parses
// it as text via syn.

#[flux::sig(fn(x: i32{x > 0}) -> i32)]
fn flux_pos(x: i32) -> i32 {
    x
}

#[flux::sig(fn(x: i32) -> i32{r: r >= 0})]
fn flux_nonneg(x: i32) -> i32 {
    0
}

#[flux::sig(fn(x: i32{x > 0}) -> i32{r: r >= 0})]
fn flux_sqrt(x: i32) -> i32 {
    x
}

#[flux_rs::sig(fn(n: u32{n != 0}) -> u32)]
fn flux_nonzero(n: u32) -> u32 {
    n
}

// Deliberately skipped pattern: #[flux::trusted] is not #[flux::sig]
// and emits a structured warning.
#[flux::trusted]
fn flux_trusted() {}
