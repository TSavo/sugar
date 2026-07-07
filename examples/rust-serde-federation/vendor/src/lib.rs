#[cfg(test)]
mod tests {
    #[test]
    fn test_write_bool_exact_row() {
        // Vendor source: serde_json 1.0.150 tests/test.rs::test_write_bool,
        // exact row `(true, "true")` through test_encode_ok.
        let s = serde_json::to_string(&true).unwrap();

        assert_eq!(s, "true");
    }
}
