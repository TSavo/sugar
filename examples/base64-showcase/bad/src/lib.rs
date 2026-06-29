// Base64-showcase bad suite.
//
// MARQUEE (WRONG): encode64("abc") == "XXXX"  [refuted via str.eq-bv-blocks]
//
// The encode64 body is CORRECT -- GenericBodySugar fires and emits the
// same str.eq-bv-blocks ambient post as in the good suite. But the test
// assertion claims the WRONG value "XXXX". The consistency pass conjoins:
//   and([
//     callresult = call:encode64("abc"),       -- EUF fact
//     "XXXX" = callresult,                     -- WRONG assertion
//     str.eq-bv-blocks(callresult,"abc",payload) -- ambient post (body)
//   ])
// The body post forces callresult = "YWJj"; the assertion claims "XXXX".
// Z3: raw-UNSAT -> UNSATISFIED (contradictory).  Symbolic teeth, no witness.
//
// The cargo test also panics at runtime ("YWJj" != "XXXX"), so the witness
// dimension independently refuses -- two independent refutation paths.

/// Same correct base64 encoder body as in the good suite.
/// GenericBodySugar fires and emits the str.eq-bv-blocks post.
fn encode64(value: &str) -> String {
    const ALPHA: &[u8] =
        b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let b0 = value.as_bytes()[0] as u32;
    let b1 = value.as_bytes()[1] as u32;
    let b2 = value.as_bytes()[2] as u32;
    [
        ALPHA[(b0 >> 2) as usize] as char,
        ALPHA[(((b0 & 3) << 4) | (b1 >> 4)) as usize] as char,
        ALPHA[(((b1 & 15) << 2) | (b2 >> 6)) as usize] as char,
        ALPHA[(b2 & 63) as usize] as char,
    ]
    .into_iter()
    .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::encoded_len;

    // ── Marquee (WRONG): UNSATISFIED via str.eq-bv-blocks consistency ────────

    #[test]
    fn marquee_encode64_wrong() {
        // WRONG: encode64("abc") is "YWJj", not "XXXX".
        // The body's str.eq-bv-blocks post forces callresult="YWJj";
        // this assertion claims "XXXX" -> UNSAT -> UNSATISFIED (refuted).
        // Also panics at runtime -> witness REFUSES independently.
        assert_eq!("XXXX", encode64("abc"));
    }

    // ── Integer wrong-value control (original wrong row) ─────────────────────

    #[test]
    fn test_encoded_len_unpadded_3_wrong_value() {
        // HONEST negative control: encoded_len(3, false).unwrap() is 4, not 3.
        // base64's length values are not FOL-computable so consistency refuses
        // (vacuity guard); the TEETH live in the witness dimension (runtime panic).
        assert_eq!(3, encoded_len(3, false).unwrap());
    }
}
