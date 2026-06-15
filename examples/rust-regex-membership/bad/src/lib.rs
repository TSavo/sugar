// rust-regex-membership BAD suite (the TEETH).
//
// THE TEETH: a `str.in-regex(subject, pattern)` membership discharge is only
// honest if a WRONG subject is REFUTED. Here the subject does NOT match the walked
// regular language, so `str.in_re(subject, R)` is UNSAT — z3's string/regex theory
// refutes the membership by the language itself, not a within-test contradiction.
// The consistency row is REFUSED. This is the bad-twin that proves the lift has
// teeth: same atom shape as GOOD, a subject the regex rejects, z3-UNSAT.

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

    // Pattern ^[a-z][a-z0-9_]{2,15}$ REJECTS "Alice!": uppercase lead AND a '!' body
    // char outside the class. A claim that "Alice!" is_match-es this regex lifts to
    // str.in_re("Alice!", R) -> UNSAT. REFUTED by membership.
    #[test]
    fn uppercase_and_punct_subject_is_refuted() {
        assert!(Regex::new("^[a-z][a-z0-9_]{2,15}$")
            .unwrap()
            .is_match("Alice!"));
    }
}
