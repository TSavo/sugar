#[cfg(test)]
mod tests {
    use base64::encoded_len;

    #[test]
    fn test_encoded_len_unpadded_3_wrong_value() {
        // HONEST negative control derived from base64 0.22.1 tests/encode.rs::encoded_len_unpadded.
        // The real value of encoded_len(3, false).unwrap() is 4. We assert a SINGLE WRONG value
        // (3) -- NOT a self-contradiction. base64's byte/length values are not FOL-computable, so
        // the symbolic consistency check cannot pin them (it honestly refuses, per #2813); the
        // TEETH live in the witness dimension: re-running this test panics (3 != 4), so the
        // witness REFUSES. A wrong value is caught by re-execution, not by a tautological
        // contradiction that would refute for any function.
        assert_eq!(3, encoded_len(3, false).unwrap());
    }
}
