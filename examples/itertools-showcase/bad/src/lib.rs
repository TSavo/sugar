#[cfg(test)]
mod tests {
    use itertools::Itertools;

    #[test]
    fn join_many_contradiction() {
        // Negative control derived from itertools 0.14.0 tests/test_std.rs::join.
        // The real result of [1, 2, 3].iter().join(", ") is "1, 2, 3" but we also
        // assert it equals "1, 2, 3, 4", which is a contradiction.
        let many = [1, 2, 3];
        assert_eq!(many.iter().join(", "), "1, 2, 3");
        assert_eq!(many.iter().join(", "), "1, 2, 3, 4");
    }

    #[test]
    fn all_equal_contradiction() {
        // Negative control derived from itertools 0.14.0 tests/test_std.rs::all_equal.
        // "AAAAAAA".chars().all_equal() is true; the second assertion is the lie.
        assert!("AAAAAAA".chars().all_equal());
        assert!(!"AAAAAAA".chars().all_equal());
    }
}
