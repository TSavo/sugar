// rust-regex-membership NON-REGULAR suite (REFUSE BY NAME).
//
// A backreference / lookahead is NOT a regular language — it is not expressible as
// a z3 RegLan term. WALK OR SILENCE, CLOSE THE HOUSE: the kit refuses such a pattern
// BY NAME at lift time (mirroring the Java PatternUniverseWalker), via the SINGLE
// regex→RegLan lowering authority (`regex_regln`) as the regularity oracle. NO
// `str.in-regex` membership row is emitted — the language is NEVER approximated, the
// weak floor stands, and the refusal names the offending feature. This is the teeth
// against a fake-dig: a non-regular pattern is never silently admitted as a
// trivially-true membership.

pub struct Regex;
impl Regex {
    pub fn new(_pat: &str) -> Result<Regex, ()> {
        Ok(Regex)
    }
    pub fn is_match(&self, _s: &str) -> bool {
        true
    }
}

#[cfg(test)]
mod tests {
    use super::Regex;

    // BACKREFERENCE `(a)\1` — not a regular language. REFUSED BY NAME.
    #[test]
    fn backreference_is_refused() {
        assert!(Regex::new("(a)\\1").unwrap().is_match("aa"));
    }

    // LOOKAHEAD `foo(?=bar)` — not a regular language. REFUSED BY NAME.
    #[test]
    fn lookahead_is_refused() {
        assert!(Regex::new("foo(?=bar)").unwrap().is_match("foobar"));
    }
}
