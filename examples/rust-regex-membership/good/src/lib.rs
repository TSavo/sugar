// rust-regex-membership GOOD suite.
//
// A regex match is NOT runtime — it is first-order string theory:
//   re.is_match(s)  ⟺  str.in_re(s, R)
// where the pattern literal lowers to a z3 RegLan term. The kit LIFTS THE SHAPE;
// it never links or runs the `regex` crate. Each assertion below lifts to a
// `str.in-regex(subject, pattern)` membership atom — byte-identical to the Java
// `@Pattern` universe pass — whose subject is a MATCHING literal, so the membership
// is SAT and the consistency row DISCHARGES.
//
// The pattern operand is resolved COMPOSITIONALLY (it is an inner Sugar): an inline
// literal, a `const`-string, and a `concat!` all flow through the same desugar, so
// the membership came THROUGH a child resolve, not a hardcoded literal.

// A minimal stand-in so the fixture is self-contained Rust syntax. The lifter walks
// the AST shape `Regex::new(<pattern>) … is_match/find` — it NEVER links or runs this.
pub struct Regex;
impl Regex {
    pub fn new(_pat: &str) -> Result<Regex, ()> {
        Ok(Regex)
    }
    pub fn is_match(&self, _s: &str) -> bool {
        true
    }
    pub fn find<'a>(&self, _s: &'a str) -> Option<&'a str> {
        None
    }
}

// A `const`-string pattern, to prove the pattern operand resolves THROUGH a child
// desugar (the const/let resolver), not only an inline literal.
const HANDLE_PATTERN: &str = "^[a-z][a-z0-9_]{2,15}$";

#[cfg(test)]
mod tests {
    use super::{Regex, HANDLE_PATTERN};

    // INLINE literal pattern, MATCHING subject -> str.in_re("alice_01", R) -> SAT.
    #[test]
    fn inline_matching() {
        assert!(Regex::new("^[a-z][a-z0-9_]{2,15}$")
            .unwrap()
            .is_match("alice_01"));
    }

    // CONST-string pattern (composition): the pattern is resolved through the const
    // resolver, MATCHING subject -> SAT.
    #[test]
    fn const_pattern_matching() {
        assert!(Regex::new(HANDLE_PATTERN).unwrap().is_match("bob_2024"));
    }

    // CONCAT pattern (composition): a pure `concat!` of string literals resolves to
    // `^[0-9]+$`, MATCHING subject "42" -> SAT.
    #[test]
    fn concat_pattern_matching() {
        assert!(Regex::new(concat!("^", "[0-9]+", "$"))
            .unwrap()
            .is_match("42"));
    }

    // `find(..).is_some()` shape, MATCHING subject -> SAT.
    #[test]
    fn find_is_some_matching() {
        assert!(Regex::new("[a-z]+").unwrap().find("hello").is_some());
    }
}
