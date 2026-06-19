// SPDX-License-Identifier: Apache-2.0
//
// StringPredicateSugar: constraint-shaped stdlib string/char predicates. These
// outrank the generic boolean-predicate fallback so `assert!(s.starts_with("x"))`
// emits the string-theory atom it states, not `method:starts_with(...) == true`.

use std::rc::Rc;

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::{
    callsite_assertion_name, token_key, AssertionFactKind, Desugared, Effect, Outcome, Sugar,
    SugarCtx, Warrant, STRUCTURAL_BACKSTOP_REASON,
};
use sugar_ir_symbolic::{and_, atomic_, eq, gte, lte, num, str_const, Formula, Term};
use syn::{Expr, ExprLit, ExprMethodCall, Lit};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_string_predicate",
    SugarRole::Constraint,
    SugarPriority::Primary,
    recognize,
);

enum StringPredicateKind {
    Contains,
    Prefix,
    Suffix,
    IsAscii,
    AsciiCharClass(&'static str),
    IsAlphabetic,
}

struct StringPredicateSugar {
    method: String,
    receiver: Box<dyn Sugar>,
    receiver_expr: Expr,
    args: Vec<Expr>,
    kind: StringPredicateKind,
}

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Paren(paren) => recognize(&paren.expr, fcx),
        Expr::Group(group) => recognize(&group.expr, fcx),
        Expr::MethodCall(call) => recognize_method(call, fcx),
        _ => None,
    }
}

fn recognize_method(call: &ExprMethodCall, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let method = call.method.to_string();
    let kind = match method.as_str() {
        "contains" => {
            if call.args.len() != 1 || string_or_char_literal_term(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::Contains
        }
        "starts_with" => {
            if call.args.len() != 1 {
                return None;
            }
            StringPredicateKind::Prefix
        }
        "ends_with" => {
            if call.args.len() != 1 {
                return None;
            }
            StringPredicateKind::Suffix
        }
        "is_ascii" => {
            if !call.args.is_empty()
                || (string_or_char_literal_term(&call.receiver).is_none()
                    && literal_byte_string_value(&call.receiver).is_none())
            {
                return None;
            }
            StringPredicateKind::IsAscii
        }
        "is_ascii_alphabetic" => {
            if !call.args.is_empty() || char_literal_term(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_alphabetic")
        }
        "is_ascii_digit" => {
            if !call.args.is_empty() || char_literal_term(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_digit")
        }
        "is_ascii_alphanumeric" => {
            if !call.args.is_empty() || char_literal_term(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_alphanumeric")
        }
        "is_ascii_octdigit" => {
            if !call.args.is_empty() || char_literal_term(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_octdigit")
        }
        "is_ascii_lowercase" => {
            if !call.args.is_empty() || char_literal_term(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_lowercase")
        }
        "is_ascii_uppercase" => {
            if !call.args.is_empty() || char_literal_term(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_uppercase")
        }
        "is_ascii_hexdigit" => {
            if !call.args.is_empty() || char_literal_term(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_hexdigit")
        }
        "is_ascii_punctuation" => {
            if !call.args.is_empty() || char_literal_term(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_punctuation")
        }
        "is_ascii_graphic" => {
            if !call.args.is_empty() || char_literal_term(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_graphic")
        }
        "is_ascii_whitespace" => {
            if !call.args.is_empty() || char_literal_term(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_whitespace")
        }
        "is_ascii_control" => {
            if !call.args.is_empty() || char_literal_term(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_control")
        }
        "is_alphabetic" => {
            if !call.args.is_empty() || char_literal_value(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::IsAlphabetic
        }
        _ => return None,
    };

    Some(Box::new(StringPredicateSugar {
        method,
        receiver: build_term(&call.receiver, fcx),
        receiver_expr: (*call.receiver).clone(),
        args: call.args.iter().cloned().collect(),
        kind,
    }))
}

impl Sugar for StringPredicateSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.kind {
            StringPredicateKind::Contains => self.desugar_binary_string_predicate(ctx, "contains"),
            StringPredicateKind::Prefix => self.desugar_binary_string_predicate(ctx, "prefix-of"),
            StringPredicateKind::Suffix => self.desugar_binary_string_predicate(ctx, "suffix-of"),
            StringPredicateKind::IsAscii => self.desugar_is_ascii(ctx),
            StringPredicateKind::AsciiCharClass(atom_name) => {
                self.desugar_char_class(ctx, atom_name)
            }
            StringPredicateKind::IsAlphabetic => self.desugar_is_alphabetic(ctx),
        }
    }
}

impl StringPredicateSugar {
    fn desugar_binary_string_predicate(&self, ctx: &SugarCtx, atom_name: &str) -> Outcome {
        if self.args.len() != 1 {
            return unsupported(format!(
                "{} predicate expects one literal pattern",
                self.method
            ));
        }
        if let Some(recv_name) = simple_path_name(&self.receiver_expr) {
            if ctx.scope.is_mut_local(&recv_name) {
                return unsupported(format!(
                    "{} predicate over a MUTABLE-local receiver `{recv_name}` \
                     (bin-2: a slice/string mutated by side-effecting iteration, not \
                     constructed from source literals); refused",
                    self.method
                ));
            }
        }
        let receiver = match term_payload(&*self.receiver, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let Some(pattern) = string_or_char_literal_term(&self.args[0]) else {
            return unsupported(format!(
                "{} predicate needs a string/char literal pattern, got `{}`",
                self.method,
                token_key(&self.args[0])
            ));
        };
        let atom = if atom_name == "prefix-of" || atom_name == "suffix-of" {
            atomic_(atom_name, vec![pattern.clone(), receiver.clone()])
        } else {
            atomic_(atom_name, vec![receiver.clone(), pattern.clone()])
        };
        let name = method_assertion_name(
            &self.method,
            vec![receiver, pattern],
            ctx.scope.local_scope(),
        );
        constraint(atom, name)
    }

    fn desugar_is_ascii(&self, ctx: &SugarCtx) -> Outcome {
        if !self.args.is_empty() {
            return unsupported("is_ascii predicate expects no arguments".to_string());
        }
        if let Some(receiver) = string_or_char_literal_term(&self.receiver_expr) {
            let name =
                method_assertion_name("is_ascii", vec![receiver.clone()], ctx.scope.local_scope());
            return constraint(atomic_("str.is_ascii", vec![receiver]), name);
        }
        let Some(bytes) = literal_byte_string_value(&self.receiver_expr) else {
            return Outcome::Hit(Effect::Unsupported {
                reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
            });
        };
        let atoms = bytes
            .into_iter()
            .map(|b| byte_is_ascii_formula(num(i128::from(b))))
            .collect::<Vec<_>>();
        let atom = if atoms.is_empty() {
            eq(bool_const(true), bool_const(true))
        } else {
            and_(atoms)
        };
        constraint(atom, None)
    }

    fn desugar_char_class(&self, ctx: &SugarCtx, atom_name: &'static str) -> Outcome {
        if !self.args.is_empty() {
            return unsupported(format!("{} predicate expects no arguments", self.method));
        }
        let Some(receiver) = char_literal_term(&self.receiver_expr) else {
            return Outcome::Hit(Effect::Unsupported {
                reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
            });
        };
        let name = method_assertion_name(
            &self.method,
            vec![receiver.clone()],
            ctx.scope.local_scope(),
        );
        constraint(atomic_(atom_name, vec![receiver]), name)
    }

    fn desugar_is_alphabetic(&self, ctx: &SugarCtx) -> Outcome {
        if !self.args.is_empty() {
            return unsupported("is_alphabetic predicate expects no arguments".to_string());
        }
        let Some(ch) = char_literal_value(&self.receiver_expr) else {
            return Outcome::Hit(Effect::Unsupported {
                reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
            });
        };
        let receiver = str_const(ch.to_string());
        let name = method_assertion_name("is_alphabetic", vec![receiver], ctx.scope.local_scope());
        constraint(eq(bool_const(ch.is_alphabetic()), bool_const(true)), name)
    }
}

fn constraint(atom: Rc<Formula>, name: Option<String>) -> Outcome {
    Outcome::Dug(Desugared::Constraints {
        atom,
        n: 1,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name },
    })
}

fn term_payload(node: &dyn Sugar, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match node.desugar(ctx) {
        Outcome::Dug(desugared) => desugared.into_term().ok_or_else(|| {
            Outcome::Hit(Effect::Unsupported {
                reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
            })
        }),
        Outcome::Hit(effect) => Err(Outcome::Hit(effect)),
    }
}

fn method_assertion_name(method: &str, args: Vec<Rc<Term>>, local_scope: &str) -> Option<String> {
    let term = Term::Ctor {
        name: format!("method:{method}"),
        args,
    };
    callsite_assertion_name(&term, local_scope)
}

fn unsupported(reason: String) -> Outcome {
    Outcome::Hit(Effect::Unsupported { reason })
}

fn string_or_char_literal_term(expr: &Expr) -> Option<Rc<Term>> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Str(s), ..
        }) => Some(str_const(s.value())),
        Expr::Lit(ExprLit {
            lit: Lit::Char(c), ..
        }) => Some(str_const(c.value().to_string())),
        Expr::Paren(paren) => string_or_char_literal_term(&paren.expr),
        Expr::Group(group) => string_or_char_literal_term(&group.expr),
        _ => None,
    }
}

fn char_literal_term(expr: &Expr) -> Option<Rc<Term>> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Char(c), ..
        }) => Some(str_const(c.value().to_string())),
        Expr::Paren(paren) => char_literal_term(&paren.expr),
        Expr::Group(group) => char_literal_term(&group.expr),
        _ => None,
    }
}

fn char_literal_value(expr: &Expr) -> Option<char> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Char(c), ..
        }) => Some(c.value()),
        Expr::Paren(paren) => char_literal_value(&paren.expr),
        Expr::Group(group) => char_literal_value(&group.expr),
        _ => None,
    }
}

fn literal_byte_string_value(expr: &Expr) -> Option<Vec<u8>> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::ByteStr(bytes),
            ..
        }) => Some(bytes.value()),
        Expr::Paren(paren) => literal_byte_string_value(&paren.expr),
        Expr::Group(group) => literal_byte_string_value(&group.expr),
        _ => None,
    }
}

fn byte_is_ascii_formula(byte: Rc<Term>) -> Rc<Formula> {
    and_(vec![gte(byte.clone(), num(0)), lte(byte, num(127))])
}

fn bool_const(value: bool) -> Rc<Term> {
    Rc::new(Term::Const {
        value: sugar_ir_symbolic::ConstValue::Bool(value),
        sort: sugar_ir_symbolic::Sort::bool(),
    })
}

fn simple_path_name(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Path(path) => path
            .path
            .segments
            .last()
            .map(|segment| segment.ident.to_string()),
        Expr::Paren(paren) => simple_path_name(&paren.expr),
        Expr::Group(group) => simple_path_name(&group.expr),
        _ => None,
    }
}
