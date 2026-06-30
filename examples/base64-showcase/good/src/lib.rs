// Base64-showcase good suite.
//
// MARQUEE: encode64("abc") == "YWJj"
//
// The two encoder functions below have bodies in EXACT GenericBodySugar shape:
//   const TABLE: &[u8] = b"...";
//   let bN = value.as_bytes()[N] as u32;
//   ...
//   [TABLE[(bv_expr) as usize] as char, ...].into_iter().collect()
//
// The RPC body lifter fires GenericBodySugar, emitting:
//   function-contract { bridgeSourceSymbol: "call:encode64",
//                       post: str.eq-bv-blocks(out, value, payload) }
//
// The consistency pass injects the function-contract post as an ambient post
// into every EUF assertion about call:encode64. For marquee_encode64:
//   inv = and([
//     callresult = call:encode64("abc"),       -- EUF fact
//     "YWJj" = callresult,                     -- assertion
//     str.eq-bv-blocks(callresult,"abc",payload) -- ambient post (body)
//   ])
// Z3 raw-SAT on this conjunction: SAT -> DISCHARGED.
//
// For bad/src/lib.rs the same body is used with WRONG expected value "XXXX";
// the body post forces callresult="YWJj", contradicting "XXXX" -> raw-UNSAT ->
// UNSATISFIED.

/// Standard base64 encoder -- 64-char alphabet, 3 bytes -> 4 chars.
/// GenericBodySugar recognizer shape: const TABLE + as_bytes()[N] assigns + array.collect().
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

/// Second encoder (generality proof): 20-char alphabet, 1 byte -> 2 chars.
/// Same GenericBodySugar code path, different table and byte count.
fn encode20(value: &str) -> String {
    const ALPHA: &[u8] = b"ABCDEFGHIJKLMNOPQRST";
    let b0 = value.as_bytes()[0] as u32;
    [
        ALPHA[(b0 & 15) as usize] as char,
        ALPHA[((b0 >> 4) & 15) as usize] as char,
    ]
    .into_iter()
    .collect()
}

/// Simple if/else selector -- symbolic if/else discharge proof.
/// Body has exactly two arms: `if b { 1 } else { 2 }`.
/// `emit_if_value` lifts this as:
///   and([implies(eq(b,true), eq(out,1)), implies(not(eq(b,true)), eq(out,2))])
/// The consistency pass substitutes the vendor-pinned argument and the solver
/// finds SAT -> DISCHARGED.
fn pick(b: bool) -> u32 {
    if b { 1 } else { 2 }
}

/// Guard-clause classifier -- symbolic nested-if discharge proof.
/// Body uses the three-arm guard-clause shape (two `if return` guards + tail 0).
/// `block_stmt_inv` via BlockSugar composes three guarded clauses:
///   and([implies(n>10, out==100),
///        implies(!n>10 /\ n>5, out==50),
///        implies(!n>10 /\ !n>5, out==0)])
/// At n=7 (vendor row) only the middle arm fires: out==50 SAT -> DISCHARGED.
fn classify(n: u32) -> u32 {
    if n > 10 { return 100; }
    if n > 5 { return 50; }
    0
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::decoded_len_estimate;
    use base64::encoded_len;

    // ── Marquee: str.eq-bv-blocks consistency DISCHARGED ─────────────────────

    #[test]
    fn marquee_encode64() {
        // encode64("abc") == "YWJj"
        // Lifts via GenericBodySugar to str.eq-bv-blocks; consistency:
        // body-post conjoined with assertion -> SAT -> DISCHARGED.
        assert_eq!("YWJj", encode64("abc"));
    }

    #[test]
    fn marquee_encode20() {
        // encode20("a") == "BG"  (ord('a')=97: low-nibble=1->'B', high-nibble=6->'G')
        // Same GenericBodySugar path, 20-char table, 1 byte: generality proof.
        assert_eq!("BG", encode20("a"));
    }

    // ── base64 vendor rows (encoded_len / decoded_len_estimate) ──────────────

    #[test]
    fn test_encoded_len_unpadded_0_exact_row() {
        // Vendor source: base64 0.22.1 tests/encode.rs::encoded_len_unpadded.
        // Exact row: encoded_len(0, false) == Some(0).
        assert_eq!(0, encoded_len(0, false).unwrap());
    }

    #[test]
    fn test_encoded_len_unpadded_1_exact_row() {
        // Vendor source: base64 0.22.1 tests/encode.rs::encoded_len_unpadded.
        // Exact row: encoded_len(1, false) == Some(2).
        assert_eq!(2, encoded_len(1, false).unwrap());
    }

    #[test]
    fn test_encoded_len_unpadded_2_exact_row() {
        // Vendor source: base64 0.22.1 tests/encode.rs::encoded_len_unpadded.
        // Exact row: encoded_len(2, false) == Some(3).
        assert_eq!(3, encoded_len(2, false).unwrap());
    }

    #[test]
    fn test_encoded_len_unpadded_3_exact_row() {
        // Vendor source: base64 0.22.1 tests/encode.rs::encoded_len_unpadded.
        // Exact row: encoded_len(3, false) == Some(4).
        assert_eq!(4, encoded_len(3, false).unwrap());
    }

    #[test]
    fn test_encoded_len_unpadded_5_exact_row() {
        // Vendor source: base64 0.22.1 tests/encode.rs::encoded_len_unpadded.
        // Exact row: encoded_len(5, false) == Some(7).
        assert_eq!(7, encoded_len(5, false).unwrap());
    }

    #[test]
    fn test_encoded_len_padded_1_exact_row() {
        // Vendor source: base64 0.22.1 tests/encode.rs::encoded_len_padded.
        // Exact row: encoded_len(1, true) == Some(4).
        assert_eq!(4, encoded_len(1, true).unwrap());
    }

    #[test]
    fn test_encoded_len_padded_4_exact_row() {
        // Vendor source: base64 0.22.1 tests/encode.rs::encoded_len_padded.
        // Exact row: encoded_len(4, true) == Some(8).
        assert_eq!(8, encoded_len(4, true).unwrap());
    }

    #[test]
    fn test_encoded_len_padded_7_exact_row() {
        // Vendor source: base64 0.22.1 tests/encode.rs::encoded_len_padded.
        // Exact row: encoded_len(7, true) == Some(12).
        assert_eq!(12, encoded_len(7, true).unwrap());
    }

    #[test]
    fn test_decoded_len_estimate_4_exact_row() {
        // Vendor source: base64 0.22.1 src/decode.rs::decoded_len_est.
        // Exact row: decoded_len_estimate(4) == 3.
        assert_eq!(3, decoded_len_estimate(4));
    }

    // ── if/else + nested-if symbolic discharge (factory BlockSugar) ───────────

    #[test]
    fn pick_if_else_discharged() {
        // pick(true) == 1.
        // Body: `if b { 1 } else { 2 }` -- single-tail if/else.
        // emit_if_value -> and([implies(eq(b,true),out==1), implies(!eq(b,true),out==2)]).
        // At b=true: only the first arm fires -> eq(out,1) SAT with vendor row 1 -> DISCHARGED.
        assert_eq!(1, pick(true));
    }

    #[test]
    fn classify_nested_if_discharged() {
        // classify(7) == 50.
        // Body: guard-clause shape; block_stmt_inv via BlockSugar.
        // At n=7: n>10 is false, n>5 is true -> middle arm: eq(out,50) SAT -> DISCHARGED.
        assert_eq!(50, classify(7));
    }
}
