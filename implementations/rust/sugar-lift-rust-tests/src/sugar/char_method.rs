// SPDX-License-Identifier: Apache-2.0
//
// TERM/CONSTRAINT recognizers for pure total `char` methods. This sugar has no
// effect verdict of its own: it composes typed child floors, or bubbles a child
// Incomplete unchanged.

use std::rc::Rc;

use sugar_ir_symbolic::{eq, num, str_const, ConstValue, Formula, Term};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::monadic::{none_term, some_term};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    bool_const, callsite_assertion_name, AssertionFactKind, Desugared, Outcome, Sugar, SugarCtx,
    Warrant,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "char_literal_method",
    &["to_string", "method"],
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
                #[test]
                fn t_char_method_good() {
                    assert_eq!('x'.to_ascii_uppercase(), 'X');
                }
            "#,
        r#"
                #[test]
                fn t_char_method_bad() {
                    assert_eq!('x'.to_ascii_uppercase(), 'Y');
                }
            "#,
    ),
    recognize,
);

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::with_ordering(
    "constraint_char_literal_method",
    SugarRole::Constraint,
    &["constraint_string_predicate", "constraint_bool_expr"],
    crate::sugar::claim::SugarWitnesses::Pending,
    recognize_constraint,
);

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let stripped = frag.strip_refs_groups();
    // call_method_key() returns None for non-MethodCall.
    let method_key = stripped.call_method_key()?;
    if stripped.call_has_turbofish() {
        return None;
    }
    let receiver_frag = stripped.call_receiver()?;
    if receiver_frag.definitely_not_char_receiver() {
        return None;
    }
    let arg_count = stripped.call_arg_count();
    let args = stripped.call_args();

    let kind = match method_key.as_str() {
        m if is_bool_method(m) && arg_count == 0 => CharMethodKind::Bool {
            method: m.to_string(),
        },
        "to_ascii_uppercase" if arg_count == 0 => CharMethodKind::AsciiUpper,
        "to_ascii_lowercase" if arg_count == 0 => CharMethodKind::AsciiLower,
        "to_uppercase" if arg_count == 0 => CharMethodKind::UnicodeUpper,
        "to_lowercase" if arg_count == 0 => CharMethodKind::UnicodeLower,
        "to_string"
            if arg_count == 0 && receiver_frag.char_to_string_receiver_resolves_literal(fcx) =>
        {
            CharMethodKind::ToString
        }
        "len_utf8" if arg_count == 0 => CharMethodKind::LenUtf8,
        "to_digit" if arg_count == 1 => CharMethodKind::ToDigit {
            radix: SugarBody::term_frag(&args[0], fcx),
        },
        _ => return None,
    };

    Some(Box::new(CharMethodSugar {
        receiver: SugarBody::term_frag(&receiver_frag, fcx),
        kind,
    }))
}

fn recognize_constraint(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let stripped = frag.strip_refs_groups();
    let method_key = stripped.call_method_key()?;
    if stripped.call_has_turbofish() {
        return None;
    }
    if stripped.call_arg_count() != 0 {
        return None;
    }
    let receiver_frag = stripped.call_receiver()?;
    if receiver_frag.definitely_not_char_receiver() {
        return None;
    }
    if !is_bool_method(&method_key) {
        return None;
    }

    Some(Box::new(CharBoolConstraintSugar {
        method: method_key,
        receiver: SugarBody::term_frag(&receiver_frag, fcx),
    }))
}

fn is_bool_method(method: &str) -> bool {
    matches!(
        method,
        "is_alphabetic"
            | "is_numeric"
            | "is_ascii"
            | "is_alphanumeric"
            | "is_whitespace"
            | "is_uppercase"
            | "is_lowercase"
    )
}

fn eval_bool_method(method: &str, ch: char) -> Option<bool> {
    match method {
        "is_alphabetic" => Some(ch.is_alphabetic()),
        "is_numeric" => Some(ch.is_numeric()),
        "is_ascii" => Some(ch.is_ascii()),
        "is_alphanumeric" => Some(ch.is_alphanumeric()),
        "is_whitespace" => Some(ch.is_whitespace()),
        "is_uppercase" => Some(ch.is_uppercase()),
        "is_lowercase" => Some(ch.is_lowercase()),
        _ => None,
    }
}

struct CharMethodSugar {
    receiver: SugarBody<TermFloor>,
    kind: CharMethodKind,
}

enum CharMethodKind {
    Bool { method: String },
    AsciiUpper,
    AsciiLower,
    UnicodeUpper,
    UnicodeLower,
    ToString,
    LenUtf8,
    ToDigit { radix: SugarBody<TermFloor> },
}

struct CharBoolConstraintSugar {
    method: String,
    receiver: SugarBody<TermFloor>,
}

fn constraint(atom: Rc<Formula>, name: Option<String>) -> Outcome {
    Outcome::Complete(Desugared::Constraints {
        atom,
        n: 1,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name },
    })
}

fn method_assertion_name(method: &str, args: Vec<Rc<Term>>, local_scope: &str) -> Option<String> {
    let term = Term::Ctor {
        name: format!("method:{method}"),
        args,
    };
    callsite_assertion_name(&term, local_scope)
}

impl Sugar for CharBoolConstraintSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match term_body(&self.receiver, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let ch = require_char(&receiver, "char bool constraint receiver");
        let result = eval_bool_method(&self.method, ch)
            .unwrap_or_else(|| panic!("unknown char bool method `{}`", self.method));
        let name = method_assertion_name(
            &self.method,
            vec![receiver.clone()],
            ctx.scope.local_scope(),
        );
        constraint(eq(bool_const(result), bool_const(true)), name)
    }
}

impl Sugar for CharMethodSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match term_body(&self.receiver, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };

        let term = match &self.kind {
            CharMethodKind::Bool { method } => {
                if let Some(ch) = term_to_char(&receiver) {
                    let result = eval_bool_method(method, ch)
                        .unwrap_or_else(|| panic!("unknown char bool method `{method}`"));
                    bool_const(result)
                } else {
                    Rc::new(Term::Ctor {
                        name: format!("method:{method}"),
                        args: vec![receiver],
                    })
                }
            }
            CharMethodKind::AsciiUpper => {
                let ch = require_char(&receiver, "to_ascii_uppercase receiver");
                str_const(ch.to_ascii_uppercase().to_string())
            }
            CharMethodKind::AsciiLower => {
                let ch = require_char(&receiver, "to_ascii_lowercase receiver");
                str_const(ch.to_ascii_lowercase().to_string())
            }
            CharMethodKind::UnicodeUpper => {
                let ch = require_char(&receiver, "to_uppercase receiver");
                str_const(ch.to_uppercase().collect::<String>())
            }
            CharMethodKind::UnicodeLower => {
                let ch = require_char(&receiver, "to_lowercase receiver");
                str_const(ch.to_lowercase().collect::<String>())
            }
            CharMethodKind::ToString => match term_to_string_const(&receiver) {
                Some(value) => str_const(value),
                None => str_const(require_char(&receiver, "to_string receiver").to_string()),
            },
            CharMethodKind::LenUtf8 => {
                let ch = require_char(&receiver, "len_utf8 receiver");
                num(ch.len_utf8() as i128)
            }
            CharMethodKind::ToDigit { radix } => {
                let ch = require_char(&receiver, "to_digit receiver");
                let radix = match term_body(radix, ctx) {
                    Ok(term) => require_radix(&term),
                    Err(outcome) => return outcome,
                };
                match ch.to_digit(radix) {
                    Some(value) => some_term(num(i128::from(value))),
                    None => none_term(),
                }
            }
        };
        Outcome::Complete(Desugared::Term(term))
    }
}

fn term_body(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_term()
            .unwrap_or_else(|| panic!("term body completed as non-term before char method"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn term_to_string_const(term: &Rc<Term>) -> Option<String> {
    let Term::Const {
        value: ConstValue::String(value),
        ..
    } = term.as_ref()
    else {
        return None;
    };
    Some(value.clone())
}

fn term_to_char(term: &Rc<Term>) -> Option<char> {
    let value = term_to_string_const(term)?;
    let mut chars = value.chars();
    let ch = chars.next()?;
    if chars.next().is_none() {
        Some(ch)
    } else {
        None
    }
}

fn require_char(term: &Rc<Term>, context: &str) -> char {
    term_to_char(term).unwrap_or_else(|| {
        panic!("{context} did not reduce to a literal char; write the owning Sugar before Outcome")
    })
}

fn require_radix(term: &Rc<Term>) -> u32 {
    let Term::Const {
        value: ConstValue::Int(value),
        ..
    } = term.as_ref()
    else {
        panic!("to_digit radix did not reduce to an integer literal; write the owning Sugar before Outcome");
    };
    u32::try_from(*value)
        .ok()
        .filter(|radix| (2..=36).contains(radix))
        .unwrap_or_else(|| panic!("to_digit radix is outside 2..=36; no char-method Effect exists"))
}

#[cfg(test)]
mod tests {
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    fn method_call_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    /// Positive: `'a'.to_uppercase()` -- observed "MethodCall", method key is
    /// "to_uppercase", no turbofish, receiver is a Char literal (not
    /// `definitely_not_char_receiver`). Struct holds `SugarBody<TermFloor>` +
    /// `CharMethodKind` -- no raw syn fields.
    #[test]
    fn from_src_char_to_uppercase_method_key_no_turbofish_char_receiver() {
        // The inner .to_uppercase() call is what the sugar recognizes.
        // Peel the outer .collect::<String>() via call_receiver().
        let file = parse_file("fn f() -> String { 'a'.to_uppercase().collect::<String>() }");
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        let outer = &stmts[0].terms()[0]; // collect::<String>()
        assert_eq!(outer.observed(), "MethodCall");
        let to_upper = outer.call_receiver().expect("collect has a receiver");
        let stripped = to_upper.strip_refs_groups();
        assert_eq!(stripped.observed(), "MethodCall");
        assert_eq!(stripped.call_method_key().as_deref(), Some("to_uppercase"));
        assert!(!stripped.call_has_turbofish());
        assert_eq!(stripped.call_arg_count(), 0);
        let recv = stripped
            .call_receiver()
            .expect("to_uppercase has a receiver");
        // Char literal -- NOT definitely_not_char_receiver
        assert!(!recv.definitely_not_char_receiver());
    }

    /// Discrimination: an integer literal receiver is `definitely_not_char_receiver`.
    /// Proves the guard correctly rejects non-char callers.
    #[test]
    fn discrimination_int_receiver_is_definitely_not_char() {
        let file = parse_file("fn f() { let _ = 42u32.to_string(); }");
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = frag.function_body().expect("fn has body");
        let stmts = body.statements();
        let val_frag = stmts[0].assign_value().expect("let has value");
        let stripped = val_frag.strip_refs_groups();
        assert_eq!(stripped.observed(), "MethodCall");
        let recv = stripped.call_receiver().expect("method has receiver");
        assert!(recv.strip_refs_groups().definitely_not_char_receiver());
    }

    /// Structural: a `BinOp` fragment returns `None` from `call_method_key()` and
    /// `false` from `call_has_turbofish()`. Shape-specific accessors do not bleed
    /// across node kinds.
    #[test]
    fn structural_binop_returns_none_from_call_method_accessors() {
        let file = parse_file("fn f(a: u32, b: u32) -> u32 { a + b }");
        let frag = method_call_frag(&file, "f.rs");
        assert_eq!(frag.observed(), "BinOp");
        assert_eq!(frag.call_method_key(), None);
        assert!(!frag.call_has_turbofish());
        assert!(frag.call_receiver().is_none());
    }
}
