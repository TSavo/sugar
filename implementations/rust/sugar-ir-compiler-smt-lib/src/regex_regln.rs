//! Regex → z3 RegLan lowering for the `@Pattern` regex universe (Door 3).
//!
//! THE LAW: we REFUTE, we do not SOLVE. Given a regex AND a candidate string,
//! `(str.in_re subject <regln>)` decides membership — the total, decidable,
//! given-both check. We never synthesize a matching string; we never approximate
//! the language. A regex feature we cannot render as a *regular* language is
//! REFUSED BY NAME (`Err(RegexError::NotRegular)`), the floor row stands, and the
//! caller refuses the universe atom. silent=0 structural: every supported token
//! lowers to an exact RegLan constructor; every unsupported token errors loudly.
//!
//! THE OATH IS THE VENDOR'S. The regex string passed here is the verbatim
//! `@Pattern(regexp="…")` literal walked from the vendor's annotation AST — never
//! authored by this kit. This module only LOWERS it.
//!
//! Supported (regular) subset, lowered to z3's native RegLan theory:
//!   - literals (incl. escaped metacharacters \. \* \+ …)         → str.to_re
//!   - character classes  [a-z]  [^…]  [abc]  [a-zA-Z0-9]          → re.range / re.union;
//!                                                                    negated → re.allchar ∩ re.comp
//!   - the dot `.`        (one char except newline, regex default) → re.allchar ∩ re.comp(\n)
//!                                                                    (exactly one non-newline char)
//!   - quantifiers  *  +  ?  {n}  {n,}  {n,m}                       → re.* re.+ re.opt re.loop
//!   - alternation  a|b                                            → re.union
//!   - grouping     (…)  (?:…)                                     → grouping only
//!   - concatenation                                               → re.++
//!   - anchors      ^  $   (z3 str.in_re is already whole-string)  → identity
//!   - predefined classes  \d \D \w \W \s \S                       → re.range / re.union;
//!                                                                    negated → re.allchar ∩ re.comp
//!
//! REFUSED BY NAME (not a regular language — never rendered):
//!   - backreferences        \1 \2 …  (?P=name) \k<name>
//!   - lookahead / lookbehind (?= (?! (?<= (?<!
//!   - named/other group extensions (?<name> (?P<name> (?> atomic, possessive +?…)
//!   - inline flags          (?i) (?s) … (we do not silently change semantics)

use std::fmt;

/// Why a regex could not be lowered. Every variant names the offending feature
/// so the kit can REFUSE BY NAME — the language is never approximated.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RegexError {
    /// A feature that is provably not a regular language (refuse by name).
    NotRegular(String),
    /// A syntactically malformed regex literal (refuse by name).
    Malformed(String),
}

impl fmt::Display for RegexError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            RegexError::NotRegular(feat) => write!(
                f,
                "regex feature {feat} is not a regular language — not rendered"
            ),
            RegexError::Malformed(msg) => write!(f, "malformed regex literal: {msg}"),
        }
    }
}

impl std::error::Error for RegexError {}

/// Lower a regex literal to a z3 RegLan term string.
///
/// Returns `Ok(regln)` for the supported regular subset, or `Err` (naming the
/// feature) for anything not a regular language or malformed. The returned string
/// is a complete `RegLan` s-expression suitable as the second argument of
/// `(str.in_re subject …)`.
pub fn regex_to_regln(pattern: &str) -> Result<String, RegexError> {
    let chars: Vec<char> = pattern.chars().collect();
    let mut p = Parser {
        chars: &chars,
        pos: 0,
    };
    let node = p.parse_alternation()?;
    if p.pos != chars.len() {
        return Err(RegexError::Malformed(format!(
            "unconsumed input at position {}",
            p.pos
        )));
    }
    Ok(node.to_regln())
}

// ── Regex AST ─────────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
enum Node {
    /// Empty language element matching the empty string: re.to_re "".
    Empty,
    /// A single literal character.
    Lit(char),
    /// Any character (the dot). Lowered to the non-newline complement.
    AnyChar,
    /// A character class: ranges/singletons, optionally negated.
    Class {
        items: Vec<ClassItem>,
        negated: bool,
    },
    /// Concatenation of nodes (re.++).
    Concat(Vec<Node>),
    /// Alternation of nodes (re.union).
    Alt(Vec<Node>),
    /// Quantified node.
    Star(Box<Node>),
    Plus(Box<Node>),
    Opt(Box<Node>),
    /// Bounded repetition {n,m}; m=None means unbounded {n,}.
    Loop(Box<Node>, u32, Option<u32>),
}

#[derive(Debug, Clone)]
enum ClassItem {
    Single(char),
    Range(char, char),
}

impl Node {
    fn to_regln(&self) -> String {
        match self {
            Node::Empty => "(str.to_re \"\")".to_string(),
            Node::Lit(c) => format!("(str.to_re \"{}\")", esc_smt_str(*c)),
            // The regex dot matches EXACTLY ONE char except newline (default, no
            // DOTALL). z3's `re.comp` is complement over Σ* (all strings), so a bare
            // `(re.comp (str.to_re "\n"))` would also match the empty string and
            // multi-char strings — over-broad. Intersect with `re.allchar` (the
            // language of single characters) to pin it to one non-newline char.
            // (Over-broadness is the SAFE direction — it can only MISS a refutation,
            // never manufacture a false one — but the atom must lower the language
            // the vendor wrote, not a superset of it.)
            Node::AnyChar => single_char_complement("(str.to_re \"\\u{a}\")"),
            Node::Class { items, negated } => {
                let inner = union_of(
                    items
                        .iter()
                        .map(|it| match it {
                            ClassItem::Single(c) => {
                                format!("(str.to_re \"{}\")", esc_smt_str(*c))
                            }
                            ClassItem::Range(a, b) => {
                                format!(
                                    "(re.range \"{}\" \"{}\")",
                                    esc_smt_str(*a),
                                    esc_smt_str(*b)
                                )
                            }
                        })
                        .collect::<Vec<_>>(),
                );
                if *negated {
                    // A negated class `[^…]` matches exactly ONE char NOT in the set.
                    // Same `re.comp` over-broadness as the dot — pin to one char via
                    // intersection with re.allchar.
                    single_char_complement(&inner)
                } else {
                    inner
                }
            }
            Node::Concat(parts) => {
                if parts.is_empty() {
                    "(str.to_re \"\")".to_string()
                } else if parts.len() == 1 {
                    parts[0].to_regln()
                } else {
                    let rendered: Vec<String> = parts.iter().map(|n| n.to_regln()).collect();
                    format!("(re.++ {})", rendered.join(" "))
                }
            }
            Node::Alt(parts) => union_of(parts.iter().map(|n| n.to_regln()).collect()),
            Node::Star(n) => format!("(re.* {})", n.to_regln()),
            Node::Plus(n) => format!("(re.+ {})", n.to_regln()),
            Node::Opt(n) => format!("(re.opt {})", n.to_regln()),
            Node::Loop(n, lo, hi) => match hi {
                Some(h) => format!("((_ re.loop {} {}) {})", lo, h, n.to_regln()),
                // {n,} unbounded = (re.++ ((_ re.loop n n) X) (re.* X))
                None => format!(
                    "(re.++ ((_ re.loop {} {}) {}) (re.* {}))",
                    lo,
                    lo,
                    n.to_regln(),
                    n.to_regln()
                ),
            },
        }
    }
}

/// Lower a "single char NOT in L" element (the regex dot, and negated classes
/// `[^…]`) to a RegLan term that matches EXACTLY ONE character outside `inner`.
/// `re.comp` alone is complement over Σ* (matches "" and multi-char strings too),
/// so we intersect with `re.allchar` (the language of single characters) to pin
/// cardinality to one. `inner` is an already-rendered RegLan term.
fn single_char_complement(inner: &str) -> String {
    format!("(re.inter re.allchar (re.comp {inner}))")
}

/// Build a right-folded `(re.union …)` over already-rendered RegLan terms.
/// z3's re.union is binary; we nest. Single element passes through.
fn union_of(mut terms: Vec<String>) -> String {
    if terms.is_empty() {
        // Empty union = empty set = re.none. Reachable only for an empty class,
        // which the parser rejects as malformed before this point.
        return "re.none".to_string();
    }
    if terms.len() == 1 {
        return terms.pop().unwrap();
    }
    let mut iter = terms.into_iter().rev();
    let mut acc = iter.next().unwrap();
    for t in iter {
        acc = format!("(re.union {} {})", t, acc);
    }
    acc
}

/// Escape a char for inside an SMT-LIB string literal.
fn esc_smt_str(c: char) -> String {
    match c {
        '"' => "\"\"".to_string(),
        '\u{0}'..='\u{1f}' | '\u{7f}' => format!("\\u{{{:x}}}", c as u32),
        _ => c.to_string(),
    }
}

// ── Recursive-descent parser ────────────────────────────────────────────────

struct Parser<'a> {
    chars: &'a [char],
    pos: usize,
}

impl<'a> Parser<'a> {
    fn peek(&self) -> Option<char> {
        self.chars.get(self.pos).copied()
    }
    fn next(&mut self) -> Option<char> {
        let c = self.chars.get(self.pos).copied();
        if c.is_some() {
            self.pos += 1;
        }
        c
    }
    fn eat(&mut self, c: char) -> bool {
        if self.peek() == Some(c) {
            self.pos += 1;
            true
        } else {
            false
        }
    }

    /// alternation := concat ('|' concat)*
    fn parse_alternation(&mut self) -> Result<Node, RegexError> {
        let mut branches = vec![self.parse_concat()?];
        while self.eat('|') {
            branches.push(self.parse_concat()?);
        }
        if branches.len() == 1 {
            Ok(branches.pop().unwrap())
        } else {
            Ok(Node::Alt(branches))
        }
    }

    /// concat := quantified*
    fn parse_concat(&mut self) -> Result<Node, RegexError> {
        let mut parts = Vec::new();
        loop {
            match self.peek() {
                None | Some('|') | Some(')') => break,
                _ => {
                    let atom = self.parse_quantified()?;
                    // Anchors (^ $) and other zero-width identity elements lower to
                    // `Empty`. In a concatenation re.++ ε is identity, so we drop
                    // bare Empty atoms — keeping anchors a true no-op and the
                    // rendered RegLan clean. (A standalone empty regex still yields
                    // Empty via the parts.is_empty() branch below.)
                    if !matches!(atom, Node::Empty) {
                        parts.push(atom);
                    }
                }
            }
        }
        if parts.is_empty() {
            Ok(Node::Empty)
        } else if parts.len() == 1 {
            Ok(parts.pop().unwrap())
        } else {
            Ok(Node::Concat(parts))
        }
    }

    /// quantified := atom quantifier?
    fn parse_quantified(&mut self) -> Result<Node, RegexError> {
        let atom = self.parse_atom()?;
        let node = match self.peek() {
            Some('*') => {
                self.pos += 1;
                Node::Star(Box::new(atom))
            }
            Some('+') => {
                self.pos += 1;
                Node::Plus(Box::new(atom))
            }
            Some('?') => {
                self.pos += 1;
                Node::Opt(Box::new(atom))
            }
            Some('{') => self.parse_brace_quantifier(atom)?,
            _ => return Ok(atom),
        };
        // Refuse non-regular quantifier modifiers: possessive (X*+) and the
        // lazy/reluctant marker (X*?) silently changes match semantics — refuse
        // by name rather than render a language the author did not write.
        match self.peek() {
            Some('+') => Err(RegexError::NotRegular("possessive quantifier".to_string())),
            Some('?') => Err(RegexError::NotRegular(
                "reluctant/lazy quantifier".to_string(),
            )),
            _ => Ok(node),
        }
    }

    /// brace := '{' n (',' m?)? '}'
    fn parse_brace_quantifier(&mut self, atom: Node) -> Result<Node, RegexError> {
        // consume '{'
        self.pos += 1;
        let lo = self.parse_uint()?;
        let node = if self.eat(',') {
            if self.peek() == Some('}') {
                Node::Loop(Box::new(atom), lo, None)
            } else {
                let hi = self.parse_uint()?;
                if hi < lo {
                    return Err(RegexError::Malformed(format!(
                        "quantifier {{{lo},{hi}}}: max < min"
                    )));
                }
                Node::Loop(Box::new(atom), lo, Some(hi))
            }
        } else {
            Node::Loop(Box::new(atom), lo, Some(lo))
        };
        if !self.eat('}') {
            return Err(RegexError::Malformed(
                "unterminated { } quantifier".to_string(),
            ));
        }
        Ok(node)
    }

    fn parse_uint(&mut self) -> Result<u32, RegexError> {
        let start = self.pos;
        while matches!(self.peek(), Some(c) if c.is_ascii_digit()) {
            self.pos += 1;
        }
        if self.pos == start {
            return Err(RegexError::Malformed(
                "expected integer in { } quantifier".to_string(),
            ));
        }
        let s: String = self.chars[start..self.pos].iter().collect();
        s.parse::<u32>()
            .map_err(|_| RegexError::Malformed(format!("integer overflow in quantifier: {s}")))
    }

    /// atom := group | class | dot | anchor | escape | literal
    fn parse_atom(&mut self) -> Result<Node, RegexError> {
        match self.peek() {
            Some('(') => self.parse_group(),
            Some('[') => self.parse_class(),
            Some('.') => {
                self.pos += 1;
                Ok(Node::AnyChar)
            }
            Some('^') | Some('$') => {
                // Anchors. z3 str.in_re is already whole-string membership, so a
                // leading ^ / trailing $ are identity. We accept them as a no-op
                // (empty-string element) so they vanish under concatenation.
                self.pos += 1;
                Ok(Node::Empty)
            }
            Some('\\') => self.parse_escape(),
            Some('*') | Some('+') | Some('?') | Some('{') => Err(RegexError::Malformed(
                "quantifier with no preceding atom".to_string(),
            )),
            Some(c) => {
                self.pos += 1;
                Ok(Node::Lit(c))
            }
            None => Ok(Node::Empty),
        }
    }

    /// group := '(' group-extension? alternation ')'
    fn parse_group(&mut self) -> Result<Node, RegexError> {
        // consume '('
        self.pos += 1;
        // Group extensions begin with '?'.
        if self.peek() == Some('?') {
            // Look at the extension marker.
            let marker = self.chars.get(self.pos + 1).copied();
            match marker {
                // Non-capturing group (?:…) — regular, just grouping.
                Some(':') => {
                    self.pos += 2;
                }
                // Lookahead (?= (?! , lookbehind (?<= (?<! — NOT regular.
                Some('=') => return Err(RegexError::NotRegular("lookahead (?=…)".to_string())),
                Some('!') => {
                    return Err(RegexError::NotRegular(
                        "negative lookahead (?!…)".to_string(),
                    ))
                }
                Some('<') => {
                    let m2 = self.chars.get(self.pos + 2).copied();
                    return match m2 {
                        Some('=') => Err(RegexError::NotRegular("lookbehind (?<=…)".to_string())),
                        Some('!') => Err(RegexError::NotRegular(
                            "negative lookbehind (?<!…)".to_string(),
                        )),
                        // (?<name>…) named-capture: capture is non-regular (it
                        // enables \k<name> backrefs); refuse by name.
                        _ => Err(RegexError::NotRegular(
                            "named-capture group (?<name>…)".to_string(),
                        )),
                    };
                }
                // (?P<name>…) / (?P=name) python-style named capture/backref.
                Some('P') => {
                    return Err(RegexError::NotRegular(
                        "named-capture/backref (?P…)".to_string(),
                    ))
                }
                // (?>…) atomic group — not regular.
                Some('>') => return Err(RegexError::NotRegular("atomic group (?>…)".to_string())),
                // Inline flags (?i) (?s) (?m)… silently change semantics — refuse.
                Some(c) if "imsxuU".contains(c) => {
                    return Err(RegexError::NotRegular(format!("inline flag (?{c}…)")))
                }
                _ => {
                    return Err(RegexError::Malformed(
                        "unrecognized group extension (?…)".to_string(),
                    ))
                }
            }
        }
        let inner = self.parse_alternation()?;
        if !self.eat(')') {
            return Err(RegexError::Malformed("unterminated group ( )".to_string()));
        }
        Ok(inner)
    }

    /// class := '[' '^'? class-item+ ']'
    fn parse_class(&mut self) -> Result<Node, RegexError> {
        // consume '['
        self.pos += 1;
        let negated = self.eat('^');
        let mut items: Vec<ClassItem> = Vec::new();
        // A ']' immediately after '[' or '[^' is a literal ']' (POSIX/PCRE rule).
        if self.peek() == Some(']') {
            self.pos += 1;
            items.push(ClassItem::Single(']'));
        }
        loop {
            match self.peek() {
                None => return Err(RegexError::Malformed("unterminated [ ] class".to_string())),
                Some(']') => {
                    self.pos += 1;
                    break;
                }
                Some('\\') => {
                    // Escaped class member — may be a predefined class or an
                    // escaped literal. Predefined classes inside [] contribute
                    // their items.
                    let pre = self.parse_class_escape()?;
                    items.extend(pre);
                }
                Some(c) => {
                    self.pos += 1;
                    // Range a-b? (but '-' as last char before ']' is a literal)
                    if self.peek() == Some('-')
                        && self.chars.get(self.pos + 1).is_some()
                        && self.chars.get(self.pos + 1) != Some(&']')
                    {
                        // consume '-'
                        self.pos += 1;
                        let end = match self.peek() {
                            Some('\\') => {
                                // escaped range end
                                let esc = self.parse_single_escape_char()?;
                                esc
                            }
                            Some(e) => {
                                self.pos += 1;
                                e
                            }
                            None => {
                                return Err(RegexError::Malformed(
                                    "unterminated range in [ ]".to_string(),
                                ))
                            }
                        };
                        if (end as u32) < (c as u32) {
                            return Err(RegexError::Malformed(format!(
                                "inverted range [{c}-{end}]"
                            )));
                        }
                        items.push(ClassItem::Range(c, end));
                    } else {
                        items.push(ClassItem::Single(c));
                    }
                }
            }
        }
        if items.is_empty() {
            return Err(RegexError::Malformed("empty [ ] class".to_string()));
        }
        Ok(Node::Class { items, negated })
    }

    /// A `\X` escape appearing OUTSIDE a class. Predefined classes become a
    /// Class node; backreferences are refused; otherwise a literal.
    fn parse_escape(&mut self) -> Result<Node, RegexError> {
        // consume '\'
        self.pos += 1;
        let c = self
            .next()
            .ok_or_else(|| RegexError::Malformed("trailing backslash".to_string()))?;
        match c {
            // Backreference \1..\9 — NOT regular.
            '1'..='9' => Err(RegexError::NotRegular(format!("backreference \\{c}"))),
            // \k<name> backreference.
            'k' => Err(RegexError::NotRegular(
                "backreference \\k<name>".to_string(),
            )),
            // Predefined classes.
            'd' => Ok(class_digit(false)),
            'D' => Ok(class_digit(true)),
            'w' => Ok(class_word(false)),
            'W' => Ok(class_word(true)),
            's' => Ok(class_space(false)),
            'S' => Ok(class_space(true)),
            // Common control escapes.
            'n' => Ok(Node::Lit('\n')),
            'r' => Ok(Node::Lit('\r')),
            't' => Ok(Node::Lit('\t')),
            'f' => Ok(Node::Lit('\u{c}')),
            'v' => Ok(Node::Lit('\u{b}')),
            '0' => Ok(Node::Lit('\u{0}')),
            // Anchors \b \B (word boundary) are zero-width and context-sensitive;
            // they are NOT a regular-language operator in the str.in_re model.
            'b' => Err(RegexError::NotRegular("word boundary \\b".to_string())),
            'B' => Err(RegexError::NotRegular("non-word-boundary \\B".to_string())),
            'A' => Err(RegexError::NotRegular(
                "start-of-input anchor \\A".to_string(),
            )),
            'Z' | 'z' => Err(RegexError::NotRegular(
                "end-of-input anchor \\Z".to_string(),
            )),
            'G' => Err(RegexError::NotRegular("match-reset anchor \\G".to_string())),
            // Otherwise: an escaped metacharacter or literal.
            other => Ok(Node::Lit(other)),
        }
    }

    /// A `\X` escape appearing INSIDE a class — returns the class items it adds.
    fn parse_class_escape(&mut self) -> Result<Vec<ClassItem>, RegexError> {
        // consume '\'
        self.pos += 1;
        let c = self
            .next()
            .ok_or_else(|| RegexError::Malformed("trailing backslash in class".to_string()))?;
        match c {
            'd' => Ok(vec![ClassItem::Range('0', '9')]),
            'w' => Ok(word_items()),
            's' => Ok(space_items()),
            // Negated predefined classes inside a [] are not expressible as a flat
            // item list without complementation; refuse by name rather than guess.
            'D' => Err(RegexError::NotRegular(
                "negated class \\D inside [ ]".to_string(),
            )),
            'W' => Err(RegexError::NotRegular(
                "negated class \\W inside [ ]".to_string(),
            )),
            'S' => Err(RegexError::NotRegular(
                "negated class \\S inside [ ]".to_string(),
            )),
            'n' => Ok(vec![ClassItem::Single('\n')]),
            'r' => Ok(vec![ClassItem::Single('\r')]),
            't' => Ok(vec![ClassItem::Single('\t')]),
            'f' => Ok(vec![ClassItem::Single('\u{c}')]),
            'v' => Ok(vec![ClassItem::Single('\u{b}')]),
            '0' => Ok(vec![ClassItem::Single('\u{0}')]),
            other => Ok(vec![ClassItem::Single(other)]),
        }
    }

    /// Parse a single escaped char (for use as a class range endpoint).
    fn parse_single_escape_char(&mut self) -> Result<char, RegexError> {
        // consume '\'
        self.pos += 1;
        let c = self
            .next()
            .ok_or_else(|| RegexError::Malformed("trailing backslash".to_string()))?;
        Ok(match c {
            'n' => '\n',
            'r' => '\r',
            't' => '\t',
            'f' => '\u{c}',
            'v' => '\u{b}',
            '0' => '\u{0}',
            other => other,
        })
    }
}

// ── Predefined character classes ─────────────────────────────────────────────

fn class_digit(negated: bool) -> Node {
    Node::Class {
        items: vec![ClassItem::Range('0', '9')],
        negated,
    }
}

fn word_items() -> Vec<ClassItem> {
    vec![
        ClassItem::Range('a', 'z'),
        ClassItem::Range('A', 'Z'),
        ClassItem::Range('0', '9'),
        ClassItem::Single('_'),
    ]
}

fn class_word(negated: bool) -> Node {
    Node::Class {
        items: word_items(),
        negated,
    }
}

fn space_items() -> Vec<ClassItem> {
    // PCRE \s = [ \t\n\r\f\v] (space, tab, newline, CR, form-feed, vtab).
    vec![
        ClassItem::Single(' '),
        ClassItem::Single('\t'),
        ClassItem::Single('\n'),
        ClassItem::Single('\r'),
        ClassItem::Single('\u{c}'),
        ClassItem::Single('\u{b}'),
    ]
}

fn class_space(negated: bool) -> Node {
    Node::Class {
        items: space_items(),
        negated,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ok(p: &str) -> String {
        regex_to_regln(p).expect("should lower")
    }

    #[test]
    fn literal_string() {
        assert_eq!(
            ok("foo"),
            "(re.++ (str.to_re \"f\") (str.to_re \"o\") (str.to_re \"o\"))"
        );
    }

    #[test]
    fn char_class_range() {
        assert_eq!(ok("[a-z]"), "(re.range \"a\" \"z\")");
    }

    #[test]
    fn char_class_union() {
        // [a-zA-Z0-9] → nested re.union of three ranges.
        let r = ok("[a-zA-Z0-9]");
        assert!(r.contains("(re.range \"a\" \"z\")"), "{r}");
        assert!(r.contains("(re.range \"A\" \"Z\")"), "{r}");
        assert!(r.contains("(re.range \"0\" \"9\")"), "{r}");
        assert!(r.contains("re.union"), "{r}");
    }

    #[test]
    fn quantifiers() {
        assert_eq!(ok("a*"), "(re.* (str.to_re \"a\"))");
        assert_eq!(ok("a+"), "(re.+ (str.to_re \"a\"))");
        assert_eq!(ok("a?"), "(re.opt (str.to_re \"a\"))");
    }

    #[test]
    fn bounded_loop() {
        assert_eq!(ok("a{2,4}"), "((_ re.loop 2 4) (str.to_re \"a\"))");
        assert_eq!(ok("a{3}"), "((_ re.loop 3 3) (str.to_re \"a\"))");
        // {n,} unbounded
        let r = ok("a{2,}");
        assert!(r.contains("re.loop 2 2"), "{r}");
        assert!(r.contains("re.*"), "{r}");
    }

    #[test]
    fn alternation() {
        let r = ok("cat|dog");
        assert!(r.starts_with("(re.union"), "{r}");
    }

    #[test]
    fn anchors_are_identity() {
        // ^foo$ should lower the same as foo (anchors vanish).
        let anchored = ok("^foo$");
        let plain = ok("foo");
        assert_eq!(anchored, plain);
    }

    #[test]
    fn predefined_digit() {
        assert_eq!(ok("\\d"), "(re.range \"0\" \"9\")");
    }

    #[test]
    fn predefined_word() {
        let r = ok("\\w");
        assert!(r.contains("(re.range \"a\" \"z\")"), "{r}");
        assert!(r.contains("(str.to_re \"_\")"), "{r}");
    }

    #[test]
    fn dot_is_single_non_newline() {
        // Pinned to exactly one char via re.allchar ∩ comp(newline) — NOT the
        // over-broad bare re.comp (which would also match "" and multi-char).
        assert_eq!(
            ok("."),
            "(re.inter re.allchar (re.comp (str.to_re \"\\u{a}\")))"
        );
    }

    #[test]
    fn negated_class() {
        let r = ok("[^0-9]");
        // Single char not in [0-9]: re.allchar ∩ comp(range) — not over-broad re.comp.
        assert!(r.starts_with("(re.inter re.allchar (re.comp"), "{r}");
        assert!(r.contains("(re.range \"0\" \"9\")"), "{r}");
    }

    #[test]
    fn escaped_metachar_literal() {
        assert_eq!(ok("\\."), "(str.to_re \".\")");
        assert_eq!(
            ok("a\\+b"),
            "(re.++ (str.to_re \"a\") (str.to_re \"+\") (str.to_re \"b\"))"
        );
    }

    #[test]
    fn noncapturing_group() {
        // (?:ab)+ is regular grouping.
        let r = ok("(?:ab)+");
        assert!(r.starts_with("(re.+"), "{r}");
    }

    // ── Refuse-by-name (non-regular features) ──

    #[test]
    fn refuse_backreference() {
        let e = regex_to_regln("(a)\\1").unwrap_err();
        assert!(
            matches!(e, RegexError::NotRegular(ref s) if s.contains("backreference")),
            "{e}"
        );
    }

    #[test]
    fn refuse_lookahead() {
        let e = regex_to_regln("foo(?=bar)").unwrap_err();
        assert!(
            matches!(e, RegexError::NotRegular(ref s) if s.contains("lookahead")),
            "{e}"
        );
    }

    #[test]
    fn refuse_negative_lookahead() {
        let e = regex_to_regln("foo(?!bar)").unwrap_err();
        assert!(
            matches!(e, RegexError::NotRegular(ref s) if s.contains("lookahead")),
            "{e}"
        );
    }

    #[test]
    fn refuse_lookbehind() {
        let e = regex_to_regln("(?<=foo)bar").unwrap_err();
        assert!(
            matches!(e, RegexError::NotRegular(ref s) if s.contains("lookbehind")),
            "{e}"
        );
    }

    #[test]
    fn refuse_atomic_group() {
        let e = regex_to_regln("(?>ab)").unwrap_err();
        assert!(
            matches!(e, RegexError::NotRegular(ref s) if s.contains("atomic")),
            "{e}"
        );
    }

    #[test]
    fn refuse_possessive() {
        let e = regex_to_regln("a*+").unwrap_err();
        assert!(
            matches!(e, RegexError::NotRegular(ref s) if s.contains("possessive")),
            "{e}"
        );
    }

    #[test]
    fn refuse_word_boundary() {
        let e = regex_to_regln("\\bfoo\\b").unwrap_err();
        assert!(
            matches!(e, RegexError::NotRegular(ref s) if s.contains("boundary")),
            "{e}"
        );
    }

    #[test]
    fn refuse_inline_flag() {
        let e = regex_to_regln("(?i)foo").unwrap_err();
        assert!(
            matches!(e, RegexError::NotRegular(ref s) if s.contains("inline flag")),
            "{e}"
        );
    }

    #[test]
    fn malformed_unterminated_group() {
        assert!(matches!(
            regex_to_regln("(ab").unwrap_err(),
            RegexError::Malformed(_)
        ));
    }

    #[test]
    fn malformed_unterminated_class() {
        assert!(matches!(
            regex_to_regln("[a-z").unwrap_err(),
            RegexError::Malformed(_)
        ));
    }

    // ── The SPOTLIGHT regex: a permissive email pattern ──
    // ^[\w.+-]+@[\w-]+\.[a-z]+$ — accepts more than the author intuits.
    #[test]
    fn email_pattern_lowers() {
        let r = ok("^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$");
        assert!(r.contains("(str.to_re \"@\")"), "{r}");
        assert!(r.contains("re.+"), "{r}");
        assert!(r.contains("re.loop 2 2"), "{r}");
    }
}
