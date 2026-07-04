// SPDX-License-Identifier: MIT OR Apache-2.0
//! The code under test: a tiny, correct adder. Every test below PASSES, so the
//! cargo-test witness package discharges by recompute (the suite re-runs, the
//! bundle cid reproduces, and every per-test witness reads "passed").

pub fn add(a: i64, b: i64) -> i64 {
    a + b
}

pub fn double(x: i64) -> i64 {
    x * 2
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adds_two_numbers() {
        assert_eq!(add(2, 3), 5);
    }

    #[test]
    fn doubles_a_number() {
        assert_eq!(double(21), 42);
    }

    #[test]
    fn add_is_commutative_at_a_point() {
        assert_eq!(add(7, 4), add(4, 7));
    }
}
