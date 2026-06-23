// SPDX-License-Identifier: Apache-2.0
//
// StringPredicateSugar: constraint-shaped stdlib string/char predicates. These
// outrank the generic boolean-predicate fallback so `assert!(s.starts_with("x"))`
// emits the string-theory atom it states, not `method:starts_with(...) == true`.

use std::{collections::BTreeMap, rc::Rc};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
use crate::{
    callsite_assertion_name, token_key, AssertionFactKind, Desugared, Effect, Outcome, Sugar,
    SugarCtx, Warrant, STRUCTURAL_BACKSTOP_REASON,
};
use sugar_ir_symbolic::{and_, atomic_, eq, gte, lte, num, str_const, Formula, Term};
use syn::{Expr, ExprLit, ExprMethodCall, Lit};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_string_predicate",
    SugarRole::Constraint,
    recognize,
);

enum StringPredicateKind {
    Contains,
    Prefix,
    Suffix,
    IsAscii,
    /// Concrete-fold: run the actual ASCII predicate on the host char/byte literal.
    /// `&'static str` is the SMT atom name (kept for warrant naming only).
    AsciiCharClass(&'static str),
    IsAlphabetic,
    /// `s1.eq_ignore_ascii_case(s2)` — both sides are string/char literals;
    /// evaluate on the host and lower to `eq(bool(result), bool(true))`.
    AsciiEqIgnoreCase,
}

struct StringPredicateSugar {
    method: String,
    receiver_expr: Expr,
    args: Vec<Expr>,
    kind: StringPredicateKind,
}

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Paren(paren) => recognize(&paren.expr, fcx),
        Expr::Group(group) => recognize(&group.expr, fcx),
        Expr::MethodCall(call) => recognize_method(call),
        _ => None,
    }
}

fn recognize_method(call: &ExprMethodCall) -> Option<Box<dyn Sugar>> {
    let method = call.method.to_string();
    let kind = match method.as_str() {
        "contains" => {
            if call.args.len() != 1 || string_or_char_literal_term(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::Contains
        }
        "starts_with" => {
            if call.args.len() != 1 || string_or_char_literal_term(&call.args[0]).is_none() {
                return None;
            }
            StringPredicateKind::Prefix
        }
        "ends_with" => {
            if call.args.len() != 1 || string_or_char_literal_term(&call.args[0]).is_none() {
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
            if !call.args.is_empty() || byte_or_char_literal_value(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_alphabetic")
        }
        "is_ascii_digit" => {
            if !call.args.is_empty() || byte_or_char_literal_value(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_digit")
        }
        "is_ascii_alphanumeric" => {
            if !call.args.is_empty() || byte_or_char_literal_value(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_alphanumeric")
        }
        "is_ascii_octdigit" => {
            if !call.args.is_empty() || byte_or_char_literal_value(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_octdigit")
        }
        "is_ascii_lowercase" => {
            if !call.args.is_empty() || byte_or_char_literal_value(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_lowercase")
        }
        "is_ascii_uppercase" => {
            if !call.args.is_empty() || byte_or_char_literal_value(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_uppercase")
        }
        "is_ascii_hexdigit" => {
            if !call.args.is_empty() || byte_or_char_literal_value(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_hexdigit")
        }
        "is_ascii_punctuation" => {
            if !call.args.is_empty() || byte_or_char_literal_value(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_punctuation")
        }
        "is_ascii_graphic" => {
            if !call.args.is_empty() || byte_or_char_literal_value(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_graphic")
        }
        "is_ascii_whitespace" => {
            if !call.args.is_empty() || byte_or_char_literal_value(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_whitespace")
        }
        "is_ascii_control" => {
            if !call.args.is_empty() || byte_or_char_literal_value(&call.receiver).is_none() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_control")
        }
        "eq_ignore_ascii_case" => {
            // Concrete-fold: both receiver and argument must be string/char literals.
            if call.args.len() != 1 {
                return None;
            }
            if string_literal_string_value(&call.receiver).is_none() {
                return None;
            }
            if string_literal_string_value(&call.args[0]).is_none() {
                return None;
            }
            StringPredicateKind::AsciiEqIgnoreCase
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
            StringPredicateKind::AsciiEqIgnoreCase => self.desugar_eq_ignore_ascii_case(ctx),
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
        let receiver_node = build_term_in_ctx(&self.receiver_expr, ctx);
        let receiver = match term_payload(&*receiver_node, ctx) {
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
        // CONCRETE FOLD (Lane 5 teeth): lift the literal → evaluate the actual
        // std predicate on the host → lower the concrete bool.
        // z3 then checks `eq(bool(result), bool(true))` — UNSAT for negation →
        // DISCHARGED.  A bad-twin that asserts the wrong value emits
        // `eq(bool(false), bool(true))` → invariant UNSAT → REFUTED.
        if !self.args.is_empty() {
            return unsupported(format!("{} predicate expects no arguments", self.method));
        }
        let Some(ch) = byte_or_char_literal_value(&self.receiver_expr) else {
            return Outcome::Hit(Effect::Unsupported {
                reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
            });
        };
        let result = eval_ascii_char_class(ch, atom_name);
        let receiver = str_const(ch.to_string());
        let name = method_assertion_name(&self.method, vec![receiver], ctx.scope.local_scope());
        constraint(eq(bool_const(result), bool_const(true)), name)
    }

    /// `s1.eq_ignore_ascii_case(s2)` — both sides are string/char literals.
    /// Evaluate on the host and lower to `eq(bool(result), bool(true))`.
    fn desugar_eq_ignore_ascii_case(&self, ctx: &SugarCtx) -> Outcome {
        if self.args.len() != 1 {
            return unsupported("eq_ignore_ascii_case expects one argument".to_string());
        }
        let Some(recv_str) = string_literal_string_value(&self.receiver_expr) else {
            return Outcome::Hit(Effect::Unsupported {
                reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
            });
        };
        let Some(arg_str) = string_literal_string_value(&self.args[0]) else {
            return Outcome::Hit(Effect::Unsupported {
                reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
            });
        };
        // Run the REAL predicate on the host — stdlib is its own axiom.
        let result = recv_str.eq_ignore_ascii_case(&arg_str);
        let recv_term = str_const(recv_str);
        let arg_term = str_const(arg_str);
        let name = method_assertion_name(
            "eq_ignore_ascii_case",
            vec![recv_term, arg_term],
            ctx.scope.local_scope(),
        );
        constraint(eq(bool_const(result), bool_const(true)), name)
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

fn build_term_in_ctx(expr: &Expr, ctx: &SugarCtx) -> Box<dyn Sugar> {
    let stable = stable_let_bindings(ctx.scope);
    let let_inits = stable_let_refs(&stable);
    let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
    build_term(expr, &fcx)
}

fn stable_let_refs(stable: &BTreeMap<String, Expr>) -> BTreeMap<String, &Expr> {
    stable
        .iter()
        .map(|(name, init)| (name.clone(), init))
        .collect()
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

/// Evaluate the named ASCII char-class predicate on a concrete char.
/// The `atom_name` must be one of the `str.is_ascii_*` names used in
/// [`StringPredicateKind::AsciiCharClass`].
fn eval_ascii_char_class(ch: char, atom_name: &str) -> bool {
    match atom_name {
        "str.is_ascii_alphabetic" => ch.is_ascii_alphabetic(),
        "str.is_ascii_digit" => ch.is_ascii_digit(),
        "str.is_ascii_alphanumeric" => ch.is_ascii_alphanumeric(),
        "str.is_ascii_octdigit" => matches!(ch, '0'..='7'),
        "str.is_ascii_lowercase" => ch.is_ascii_lowercase(),
        "str.is_ascii_uppercase" => ch.is_ascii_uppercase(),
        "str.is_ascii_hexdigit" => ch.is_ascii_hexdigit(),
        "str.is_ascii_punctuation" => ch.is_ascii_punctuation(),
        "str.is_ascii_graphic" => ch.is_ascii_graphic(),
        "str.is_ascii_whitespace" => ch.is_ascii_whitespace(),
        "str.is_ascii_control" => ch.is_ascii_control(),
        _ => panic!("eval_ascii_char_class: unknown atom name `{atom_name}`"),
    }
}

/// Extract the concrete char from a char literal OR a byte literal (`b'A'`).
/// Byte literals are valid for all ASCII predicate calls — `b'A'.is_ascii_uppercase()`.
fn byte_or_char_literal_value(expr: &Expr) -> Option<char> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Char(c), ..
        }) => Some(c.value()),
        Expr::Lit(ExprLit {
            lit: Lit::Byte(b), ..
        }) => Some(char::from(b.value())),
        Expr::Paren(paren) => byte_or_char_literal_value(&paren.expr),
        Expr::Group(group) => byte_or_char_literal_value(&group.expr),
        _ => None,
    }
}

/// Extract the string value from a string literal or char literal (char → single-char string).
fn string_literal_string_value(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Str(s), ..
        }) => Some(s.value()),
        Expr::Lit(ExprLit {
            lit: Lit::Char(c), ..
        }) => Some(c.value().to_string()),
        Expr::Paren(paren) => string_literal_string_value(&paren.expr),
        Expr::Group(group) => string_literal_string_value(&group.expr),
        _ => None,
    }
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
