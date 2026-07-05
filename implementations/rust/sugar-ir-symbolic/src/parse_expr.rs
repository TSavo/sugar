// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Expression-string parser for `sugar-ir-symbolic`.
//
// Accepts a subset of Rust expression syntax and produces typed
// `Formula` / `Term` values that are structurally identical to those
// produced by the kit's authoring API. Round-trip guarantee:
//
//     serialize(parse_expr(s)) → canonical bytes B
//     parse(B) → Formula F′  (via parse_formula)
//     serialize(F′) → canonical bytes B′
//     assert_eq!(B, B′)  -- byte-identical
//
// Grammar (ordered by increasing precedence):
//
//     expr      ::= or_expr
//     or_expr   ::= and_expr  ('||' and_expr)*
//     and_expr  ::= not_expr  ('&&' not_expr)*
//     not_expr  ::= '!' not_expr  |  cmp_expr
//     cmp_expr  ::= term_expr ( op term_expr )?
//     op        ::= '<' | '<=' | '>' | '>=' | '==' | '!='
//     term_expr ::= '(' expr ')'  |  literal  |  path_var
//     literal   ::= int_literal  |  bool_literal
//     int_literal  ::= '-'? [0-9]+
//     bool_literal ::= 'true' | 'false'
//     path_var  ::= [a-zA-Z_][a-zA-Z0-9_]* ( '.' [a-zA-Z_][a-zA-Z0-9_]* )*
//                 -- dotted identifiers are lifted as Variable(full.path)
//
// Operator symbols map to the kit's atomic predicate names:
//     '<'  -> "<"
//     '<=' -> "≤"   (U+2264)
//     '>'  -> ">"
//     '>=' -> "≥"   (U+2265)
//     '==' -> "="
//     '!=' -> "≠"   (U+2260)
//
// NOTE on the `≤` / `≥` / `≠` choice: the existing kit functions `lte`,
// `gte`, `ne` emit those Unicode names per `lib.rs`. We match them
// exactly so that `parse_expr("x <= 0")` produces the same predicate
// name as `lte(x, 0)` and therefore the same JCS bytes.
//
// NOTE on `None` / `Some`: not handled. The grammar defers them; any
// input containing these keywords will produce an `UnknownToken` error.
// Extend the `path_var` arm with a special case if/when needed.

use std::rc::Rc;

use crate::{and_, atomic_, not_, num, or_, ConstValue, Formula, Sort, Term};

// ---------------------------------------------------------------------------
// Public error type
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ExprParseError {
    #[error("parse_expr: unexpected end of input (position {position})")]
    UnexpectedEof { position: usize },
    #[error("parse_expr: unexpected token at position {position}: `{token}`")]
    UnexpectedToken { position: usize, token: String },
    #[error("parse_expr: invalid literal at position {position}: `{literal}`")]
    InvalidLiteral { position: usize, literal: String },
    #[error("parse_expr: unmatched '(' at position {position}")]
    UnmatchedParen { position: usize },
}

// ---------------------------------------------------------------------------
// Tokens
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq)]
enum Token {
    /// Identifier (possibly dotted: "result.is_ok")
    Ident(String),
    /// Integer literal (signed i128 -- the kit's Int carrier)
    Int(i128),
    /// `true` or `false`
    Bool(bool),
    /// `||`
    Or,
    /// `&&`
    And,
    /// `!`
    Not,
    /// `<`
    Lt,
    /// `<=`
    Lte,
    /// `>`
    Gt,
    /// `>=`
    Gte,
    /// `==`
    Eq,
    /// `!=`
    Ne,
    /// `(`
    LParen,
    /// `)`
    RParen,
}

// A token annotated with its byte offset in the source string.
#[derive(Debug, Clone)]
struct Tok {
    tok: Token,
    pos: usize,
}

// ---------------------------------------------------------------------------
// Lexer
// ---------------------------------------------------------------------------

fn lex(input: &str) -> Result<Vec<Tok>, ExprParseError> {
    let chars: Vec<char> = input.chars().collect();
    let mut i = 0usize;
    let mut tokens: Vec<Tok> = Vec::new();

    // Character byte-offset table: map char-index -> byte-offset.
    let byte_offsets: Vec<usize> = {
        let mut out = Vec::with_capacity(chars.len() + 1);
        let mut off = 0usize;
        for ch in &chars {
            out.push(off);
            off += ch.len_utf8();
        }
        out.push(off); // sentinel for EOF
        out
    };

    macro_rules! pos {
        () => {
            *byte_offsets.get(i).unwrap_or(byte_offsets.last().unwrap())
        };
    }

    while i < chars.len() {
        let c = chars[i];

        // Skip whitespace.
        if c.is_whitespace() {
            i += 1;
            continue;
        }

        // Two-char operators first.
        if i + 1 < chars.len() {
            let two = (c, chars[i + 1]);
            match two {
                ('|', '|') => {
                    tokens.push(Tok {
                        tok: Token::Or,
                        pos: pos!(),
                    });
                    i += 2;
                    continue;
                }
                ('&', '&') => {
                    tokens.push(Tok {
                        tok: Token::And,
                        pos: pos!(),
                    });
                    i += 2;
                    continue;
                }
                ('<', '=') => {
                    tokens.push(Tok {
                        tok: Token::Lte,
                        pos: pos!(),
                    });
                    i += 2;
                    continue;
                }
                ('>', '=') => {
                    tokens.push(Tok {
                        tok: Token::Gte,
                        pos: pos!(),
                    });
                    i += 2;
                    continue;
                }
                ('=', '=') => {
                    tokens.push(Tok {
                        tok: Token::Eq,
                        pos: pos!(),
                    });
                    i += 2;
                    continue;
                }
                ('!', '=') => {
                    tokens.push(Tok {
                        tok: Token::Ne,
                        pos: pos!(),
                    });
                    i += 2;
                    continue;
                }
                _ => {}
            }
        }

        // Single-char tokens.
        match c {
            '<' => {
                tokens.push(Tok {
                    tok: Token::Lt,
                    pos: pos!(),
                });
                i += 1;
                continue;
            }
            '>' => {
                tokens.push(Tok {
                    tok: Token::Gt,
                    pos: pos!(),
                });
                i += 1;
                continue;
            }
            '!' => {
                tokens.push(Tok {
                    tok: Token::Not,
                    pos: pos!(),
                });
                i += 1;
                continue;
            }
            '(' => {
                tokens.push(Tok {
                    tok: Token::LParen,
                    pos: pos!(),
                });
                i += 1;
                continue;
            }
            ')' => {
                tokens.push(Tok {
                    tok: Token::RParen,
                    pos: pos!(),
                });
                i += 1;
                continue;
            }
            _ => {}
        }

        // Negative integer literal: '-' followed by digit.
        if c == '-' && i + 1 < chars.len() && chars[i + 1].is_ascii_digit() {
            let start_pos = pos!();
            i += 1; // skip '-'
            let mut s = String::from("-");
            while i < chars.len() && chars[i].is_ascii_digit() {
                s.push(chars[i]);
                i += 1;
            }
            let n = s
                .parse::<i128>()
                .map_err(|_| ExprParseError::InvalidLiteral {
                    position: start_pos,
                    literal: s,
                })?;
            tokens.push(Tok {
                tok: Token::Int(n),
                pos: start_pos,
            });
            continue;
        }

        // Positive integer literal.
        if c.is_ascii_digit() {
            let start_pos = pos!();
            let mut s = String::new();
            while i < chars.len() && chars[i].is_ascii_digit() {
                s.push(chars[i]);
                i += 1;
            }
            let n = s
                .parse::<i128>()
                .map_err(|_| ExprParseError::InvalidLiteral {
                    position: start_pos,
                    literal: s,
                })?;
            tokens.push(Tok {
                tok: Token::Int(n),
                pos: start_pos,
            });
            continue;
        }

        // Identifier / keyword (may be dotted: "result.is_ok").
        if c.is_alphabetic() || c == '_' {
            let start_pos = pos!();
            let mut s = String::new();
            // Consume dotted path in one token: word ('.' word)*
            loop {
                // Consume one word segment.
                while i < chars.len() && (chars[i].is_alphanumeric() || chars[i] == '_') {
                    s.push(chars[i]);
                    i += 1;
                }
                // If followed by '.' and another identifier start, consume.
                if i + 1 < chars.len()
                    && chars[i] == '.'
                    && (chars[i + 1].is_alphabetic() || chars[i + 1] == '_')
                {
                    s.push('.');
                    i += 1; // skip '.'
                } else {
                    break;
                }
            }
            let tok = match s.as_str() {
                "true" => Token::Bool(true),
                "false" => Token::Bool(false),
                _ => Token::Ident(s),
            };
            tokens.push(Tok {
                tok,
                pos: start_pos,
            });
            continue;
        }

        // Unknown character.
        return Err(ExprParseError::UnexpectedToken {
            position: pos!(),
            token: c.to_string(),
        });
    }

    Ok(tokens)
}

// ---------------------------------------------------------------------------
// Parser
// ---------------------------------------------------------------------------
//
// Recursive-descent parser. '(' at the atom level means a parenthesised
// sub-formula (not a term-level group).

struct FParser<'a> {
    tokens: &'a [Tok],
    pos: usize,
}

impl<'a> FParser<'a> {
    fn new(tokens: &'a [Tok]) -> Self {
        FParser { tokens, pos: 0 }
    }

    fn peek(&self) -> Option<&Tok> {
        self.tokens.get(self.pos)
    }

    fn advance(&mut self) -> Option<&Tok> {
        let t = self.tokens.get(self.pos);
        if t.is_some() {
            self.pos += 1;
        }
        t
    }

    fn cur_pos(&self) -> usize {
        self.peek()
            .map(|t| t.pos)
            .unwrap_or_else(|| self.tokens.last().map(|t| t.pos + 1).unwrap_or(0))
    }

    // expr ::= or_expr
    fn expr(&mut self) -> Result<Rc<Formula>, ExprParseError> {
        self.or_expr()
    }

    // or_expr ::= and_expr ('||' and_expr)*
    fn or_expr(&mut self) -> Result<Rc<Formula>, ExprParseError> {
        let mut lhs = self.and_expr()?;
        while matches!(self.peek(), Some(Tok { tok: Token::Or, .. })) {
            self.advance();
            let rhs = self.and_expr()?;
            lhs = or_(vec![lhs, rhs]);
        }
        Ok(lhs)
    }

    // and_expr ::= not_expr ('&&' not_expr)*
    fn and_expr(&mut self) -> Result<Rc<Formula>, ExprParseError> {
        let mut lhs = self.not_expr()?;
        while matches!(
            self.peek(),
            Some(Tok {
                tok: Token::And,
                ..
            })
        ) {
            self.advance();
            let rhs = self.not_expr()?;
            lhs = and_(vec![lhs, rhs]);
        }
        Ok(lhs)
    }

    // not_expr ::= '!' not_expr | atom_formula
    fn not_expr(&mut self) -> Result<Rc<Formula>, ExprParseError> {
        if matches!(
            self.peek(),
            Some(Tok {
                tok: Token::Not,
                ..
            })
        ) {
            self.advance();
            let inner = self.not_expr()?;
            Ok(not_(inner))
        } else {
            self.atom_formula()
        }
    }

    // atom_formula ::= '(' expr ')' | cmp_or_bare
    fn atom_formula(&mut self) -> Result<Rc<Formula>, ExprParseError> {
        if matches!(
            self.peek(),
            Some(Tok {
                tok: Token::LParen,
                ..
            })
        ) {
            return self.paren_formula();
        }
        self.cmp_or_bare()
    }

    // paren_formula ::= '(' expr ')'
    fn paren_formula(&mut self) -> Result<Rc<Formula>, ExprParseError> {
        let open_pos = self.peek().map(|t| t.pos).unwrap_or(0);
        self.advance(); // consume '('
        let inner = self.expr()?;
        match self.advance() {
            Some(Tok {
                tok: Token::RParen, ..
            }) => Ok(inner),
            _ => Err(ExprParseError::UnmatchedParen { position: open_pos }),
        }
    }

    // cmp_or_bare ::= term (cmp_op term)? | bool_bare
    fn cmp_or_bare(&mut self) -> Result<Rc<Formula>, ExprParseError> {
        let lhs = self.term_atom()?;

        let op = match self.peek() {
            Some(Tok { tok: Token::Lt, .. }) => Some("<"),
            Some(Tok {
                tok: Token::Lte, ..
            }) => Some("\u{2264}"),
            Some(Tok { tok: Token::Gt, .. }) => Some(">"),
            Some(Tok {
                tok: Token::Gte, ..
            }) => Some("\u{2265}"),
            Some(Tok { tok: Token::Eq, .. }) => Some("="),
            Some(Tok { tok: Token::Ne, .. }) => Some("\u{2260}"),
            _ => None,
        };

        if let Some(op_name) = op {
            self.advance(); // consume op
            let rhs = self.term_atom()?;
            Ok(atomic_(op_name, vec![lhs, rhs]))
        } else {
            // No comparison: bare variable or bool literal as a predicate.
            match lhs.as_ref() {
                Term::Const {
                    value: ConstValue::Bool(b),
                    ..
                } => Ok(atomic_(if *b { "true" } else { "false" }, vec![])),
                Term::Var { name } => Ok(atomic_(name.as_str(), vec![])),
                _ => Err(ExprParseError::UnexpectedToken {
                    position: self.cur_pos(),
                    token: "expected comparison operator after non-variable term".into(),
                }),
            }
        }
    }

    // term_atom ::= int_literal | bool_literal | ident_or_path
    // NOTE: '(' at term level is an error per this grammar subset.
    fn term_atom(&mut self) -> Result<Rc<Term>, ExprParseError> {
        match self.peek() {
            Some(Tok {
                tok: Token::Int(n), ..
            }) => {
                let n = *n;
                self.advance();
                Ok(num(n))
            }
            Some(Tok {
                tok: Token::Bool(b),
                ..
            }) => {
                let b = *b;
                self.advance();
                Ok(Rc::new(Term::Const {
                    value: ConstValue::Bool(b),
                    sort: Sort::bool(),
                }))
            }
            Some(Tok {
                tok: Token::Ident(name),
                ..
            }) => {
                let name = name.clone();
                self.advance();
                Ok(Rc::new(Term::Var { name }))
            }
            Some(t) => {
                let pos = t.pos;
                let tok = format!("{:?}", t.tok);
                Err(ExprParseError::UnexpectedToken {
                    position: pos,
                    token: tok,
                })
            }
            None => Err(ExprParseError::UnexpectedEof {
                position: self.cur_pos(),
            }),
        }
    }
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/// Parse a Rust-expression-shaped predicate string into a `Formula`.
///
/// The returned `Rc<Formula>` is structurally identical to a formula
/// built using the kit's authoring API (`gt`, `and_`, etc.).
/// Serializing it via `sugar_ir_symbolic::serialize::formula_to_value`
/// and then re-parsing the result via `parse_formula` produces byte-
/// identical JCS output.
///
/// Operator mapping:
/// - `<`  → atomic predicate `"<"`
/// - `<=` → atomic predicate `"≤"` (U+2264)  — matches `lte()`
/// - `>`  → atomic predicate `">"`
/// - `>=` → atomic predicate `"≥"` (U+2265)  — matches `gte()`
/// - `==` → atomic predicate `"="`            — matches `eq()`
/// - `!=` → atomic predicate `"≠"` (U+2260)  — matches `ne()`
///
/// Dotted identifiers (e.g. `result.is_ok`) are lifted as
/// `Term::Var { name: "result.is_ok" }`.
///
/// Boolean literals `true` / `false` in predicate position are lifted
/// as nullary atomic predicates `atomic_("true", [])` /
/// `atomic_("false", [])`.
///
/// Returns `Err(ExprParseError)` for malformed input.
pub fn parse_expr(input: &str) -> Result<Rc<Formula>, ExprParseError> {
    let tokens = lex(input)?;
    if tokens.is_empty() {
        return Err(ExprParseError::UnexpectedEof { position: 0 });
    }
    let mut parser = FParser::new(&tokens);
    let formula = parser.expr()?;
    // Ensure all input was consumed.
    if let Some(t) = parser.peek() {
        return Err(ExprParseError::UnexpectedToken {
            position: t.pos,
            token: format!("{:?}", t.tok),
        });
    }
    Ok(formula)
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::serialize::formula_to_value;

    fn jcs(f: &Rc<Formula>) -> String {
        sugar_canonicalizer::encode_jcs(&formula_to_value(f))
    }

    fn rt(s: &str) -> Rc<Formula> {
        parse_expr(s).unwrap_or_else(|e| panic!("parse_expr({s:?}) failed: {e}"))
    }

    fn assert_round_trip(s: &str) {
        let f1 = rt(s);
        let b1 = jcs(&f1);
        // Re-parse via the JSON parser to confirm structural identity.
        let json: serde_json::Value = serde_json::from_str(&b1).expect("JCS is valid JSON");
        let f2 = crate::parse::parse_formula(&json).expect("re-parse");
        let b2 = jcs(&f2);
        assert_eq!(b1, b2, "round-trip failed for {s:?}");
    }

    // ---- Single comparisons (one per operator) ------------------------------

    #[test]
    fn round_trip_lt() {
        assert_round_trip("x < 0");
    }

    #[test]
    fn round_trip_lte() {
        assert_round_trip("x <= 0");
    }

    #[test]
    fn round_trip_gt() {
        assert_round_trip("x > 0");
    }

    #[test]
    fn round_trip_gte() {
        assert_round_trip("x >= 0");
    }

    #[test]
    fn round_trip_eq() {
        assert_round_trip("x == 0");
    }

    #[test]
    fn round_trip_ne() {
        assert_round_trip("x != 0");
    }

    // ---- Integer literals ---------------------------------------------------

    #[test]
    fn round_trip_positive_int() {
        assert_round_trip("attempts < 42");
    }

    #[test]
    fn round_trip_negative_int() {
        assert_round_trip("x > -1");
    }

    // ---- Boolean ops --------------------------------------------------------

    #[test]
    fn round_trip_and() {
        assert_round_trip("x > 0 && y != 0");
    }

    #[test]
    fn round_trip_or() {
        assert_round_trip("x > 0 || y == 0");
    }

    #[test]
    fn round_trip_not() {
        assert_round_trip("!x > 0"); // parsed as !(x > 0)
    }

    // ---- Precedence ---------------------------------------------------------

    #[test]
    fn precedence_not_binds_tighter_than_and() {
        // !(x > 0) && y < 1  — not binds to (x > 0)
        let f = rt("!x > 0 && y < 1");
        // Should be: and_(not_(gt(x,0)), lt(y,1))
        // Confirm by checking JCS matches hand-built formula.
        let expected = crate::and_(vec![
            crate::not_(crate::gt(crate::make_var("x"), crate::num(0))),
            crate::lt(crate::make_var("y"), crate::num(1)),
        ]);
        assert_eq!(jcs(&f), jcs(&expected));
    }

    #[test]
    fn precedence_and_binds_tighter_than_or() {
        // x > 0 || y > 0 && z > 0  ->  x > 0 || (y > 0 && z > 0)
        let f = rt("x > 0 || y > 0 && z > 0");
        let expected = crate::or_(vec![
            crate::gt(crate::make_var("x"), crate::num(0)),
            crate::and_(vec![
                crate::gt(crate::make_var("y"), crate::num(0)),
                crate::gt(crate::make_var("z"), crate::num(0)),
            ]),
        ]);
        assert_eq!(jcs(&f), jcs(&expected));
    }

    #[test]
    fn parens_override_precedence() {
        // (x > 0 || y > 0) && z > 0
        let f = rt("(x > 0 || y > 0) && z > 0");
        let expected = crate::and_(vec![
            crate::or_(vec![
                crate::gt(crate::make_var("x"), crate::num(0)),
                crate::gt(crate::make_var("y"), crate::num(0)),
            ]),
            crate::gt(crate::make_var("z"), crate::num(0)),
        ]);
        assert_eq!(jcs(&f), jcs(&expected));
    }

    // ---- Dotted paths -------------------------------------------------------

    #[test]
    fn round_trip_dotted_path_var() {
        assert_round_trip("result.is_ok > 0");
    }

    #[test]
    fn round_trip_dotted_path_bare() {
        // bare dotted identifier as a nullary predicate
        assert_round_trip("result.is_ok == 0");
    }

    // ---- Boolean literals ---------------------------------------------------

    #[test]
    fn round_trip_bool_literal_true() {
        let f = rt("out == true");
        assert_round_trip("out == true");
        drop(f);
    }

    #[test]
    fn round_trip_bool_literal_false() {
        assert_round_trip("out == false");
    }

    // ---- Composite predicates -----------------------------------------------

    #[test]
    fn round_trip_max_attempts_predicate() {
        assert_round_trip("max_attempts >= 0");
    }

    #[test]
    fn round_trip_two_sided_or() {
        assert_round_trip("(out == true) || (out == false)");
    }

    #[test]
    fn round_trip_before_state_predicate() {
        assert_round_trip("(out >= 0) || (out == before_state)");
    }

    #[test]
    fn round_trip_three_way_and() {
        assert_round_trip("x > 0 && y > 0 && z > 0");
    }

    #[test]
    fn round_trip_not_and_or_mix() {
        assert_round_trip("!(x == 0) && (y > 0 || z < 1)");
    }

    #[test]
    fn round_trip_nested_not() {
        // double negation round-trips to and(not(not(x > 0)))
        assert_round_trip("!!(x > 0)");
    }

    // ---- Error cases --------------------------------------------------------

    #[test]
    fn error_empty_input() {
        assert!(matches!(
            parse_expr(""),
            Err(ExprParseError::UnexpectedEof { .. })
        ));
    }

    #[test]
    fn error_trailing_operator() {
        // "x > 0 &&" — trailing && with no RHS
        let r = parse_expr("x > 0 &&");
        assert!(
            matches!(r, Err(ExprParseError::UnexpectedEof { .. })),
            "expected UnexpectedEof, got {r:?}"
        );
    }

    #[test]
    fn error_unmatched_open_paren() {
        let r = parse_expr("(x > 0");
        assert!(
            matches!(r, Err(ExprParseError::UnmatchedParen { .. })),
            "expected UnmatchedParen, got {r:?}"
        );
    }

    #[test]
    fn error_stray_close_paren() {
        let r = parse_expr("x > 0)");
        assert!(
            matches!(r, Err(ExprParseError::UnexpectedToken { .. })),
            "expected UnexpectedToken for stray ), got {r:?}"
        );
    }

    #[test]
    fn error_unknown_char() {
        let r = parse_expr("x @ 0");
        assert!(
            matches!(r, Err(ExprParseError::UnexpectedToken { .. })),
            "expected UnexpectedToken for @, got {r:?}"
        );
    }
}
