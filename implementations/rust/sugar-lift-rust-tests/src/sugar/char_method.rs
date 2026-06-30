// SPDX-License-Identifier: Apache-2.0
//
// TERM/CONSTRAINT recognizers for pure total `char` methods. This sugar has no
// effect verdict of its own: it composes typed child floors, or bubbles a child
// Incomplete unchanged.

use std::rc::Rc;

use sugar_ir_symbolic::{eq, num, str_const, ConstValue, Formula, Term};
use syn::{Expr, ExprLit, Lit};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::monadic::{none_term, some_term};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    bool_const, callsite_assertion_name, strip_refs_groups, AssertionFactKind, Desugared, Outcome,
    Sugar, SugarCtx, Warrant,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("char_literal_method", &["to_string", "method"], recognize);

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::with_ordering(
    "constraint_char_literal_method",
    SugarRole::Constraint,
    &["constraint_string_predicate", "constraint_bool_expr"],
    recognize_constraint,
);

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.turbofish.is_some() || definitely_not_char_receiver(&call.receiver) {
        return None;
    }
    let method = call.method.to_string();
    let kind = match method.as_str() {
        method if is_bool_method(method) && call.args.is_empty() => CharMethodKind::Bool {
            method: method.to_string(),
        },
        "to_ascii_uppercase" if call.args.is_empty() => CharMethodKind::AsciiUpper,
        "to_ascii_lowercase" if call.args.is_empty() => CharMethodKind::AsciiLower,
        "to_uppercase" if call.args.is_empty() => CharMethodKind::UnicodeUpper,
        "to_lowercase" if call.args.is_empty() => CharMethodKind::UnicodeLower,
        "to_string"
            if call.args.is_empty()
                && char_to_string_receiver_resolves_literal(&call.receiver, fcx) =>
        {
            CharMethodKind::ToString
        }
        "len_utf8" if call.args.is_empty() => CharMethodKind::LenUtf8,
        "to_digit" if call.args.len() == 1 => CharMethodKind::ToDigit {
            radix: SugarBody::term(&call.args[0], fcx),
        },
        _ => return None,
    };

    Some(Box::new(CharMethodSugar {
        receiver: SugarBody::term(&call.receiver, fcx),
        kind,
    }))
}

fn recognize_constraint(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.turbofish.is_some()
        || !call.args.is_empty()
        || definitely_not_char_receiver(&call.receiver)
    {
        return None;
    }
    let method = call.method.to_string();
    if !is_bool_method(&method) {
        return None;
    }

    Some(Box::new(CharBoolConstraintSugar {
        method,
        receiver: SugarBody::term(&call.receiver, fcx),
    }))
}

fn definitely_not_char_receiver(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Char(_), ..
        }) => false,
        Expr::Lit(_) => true,
        Expr::MethodCall(call) => definitely_not_char_receiver(&call.receiver),
        _ => false,
    }
}

fn char_to_string_receiver_resolves_literal(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Char(_), ..
        }) => true,
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(|ident| ident.to_string()) else {
                return false;
            };
            if fcx.resolving_bound_path(&name) {
                return false;
            }
            let Some(init) = fcx
                .let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
            else {
                return false;
            };
            let child_fcx = fcx.with_bound_path(&name);
            char_to_string_receiver_resolves_literal(init, &child_fcx)
        }
        Expr::Paren(paren) => char_to_string_receiver_resolves_literal(&paren.expr, fcx),
        Expr::Group(group) => char_to_string_receiver_resolves_literal(&group.expr, fcx),
        _ => false,
    }
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
