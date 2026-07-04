// SPDX-License-Identifier: MIT OR Apache-2.0
//! The code under test: a BROKEN adder. `add` is wrong (subtracts), so the test
//! that pins the correct answer FAILS. The witness package records the failure
//! honestly; discharge then REFUSES on the all-passed check.

pub fn add(a: i64, b: i64) -> i64 {
    a - b // BUG: should be a + b
}

pub fn double(x: i64) -> i64 {
    x * 2
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn doubles_a_number() {
        // This one is correct -> "passed".
        assert_eq!(double(21), 42);
    }

    #[test]
    fn adds_two_numbers() {
        // This one FAILS against the broken `add` -> "failed".
        assert_eq!(add(2, 3), 5);
    }
}
