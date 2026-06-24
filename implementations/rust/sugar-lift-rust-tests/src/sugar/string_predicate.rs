// SPDX-License-Identifier: Apache-2.0
//
// StringPredicateSugar: constraint-shaped stdlib string/char predicates. These
// outrank the generic boolean-predicate fallback so `assert!(s.starts_with("x"))`
// emits the string-theory atom it states, not `method:starts_with(...) == true`.

use std::rc::Rc;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{FloorRead, FormatValueFloor, SugarBody, SugarBuildCtx};
use crate::sugar::format::{FmtValue, IntKind};
use crate::{
    callsite_assertion_name, simple_path_name, strip_refs_groups, AssertionFactKind, Desugared,
    Effect, Outcome, Sugar, SugarCtx, Warrant,
};
use sugar_ir_symbolic::{and_, atomic_, eq, gte, lte, num, str_const, Formula, Term};
use syn::{Expr, ExprLit, ExprMethodCall, Lit};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_string_predicate",
    SugarRole::Constraint,
    recognize,
);

#[derive(Clone, Copy)]
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
    receiver_name: Option<String>,
    receiver: PredicateOperand,
    arg: PredicateArg,
    kind: StringPredicateKind,
}

enum PredicateOperand {
    Value(SugarBody<FormatValueFloor>),
    ByteString(Vec<u8>),
    Child(Box<PredicateOperand>),
}

enum PredicateArg {
    None,
    Operand(PredicateOperand),
}

enum PredicateLiteral {
    String(String),
    Char(char),
    Byte(u8),
    ByteString(Vec<u8>),
}

trait LiteralVisitor {
    type Output;

    fn visit_string(self, value: String) -> Self::Output;
    fn visit_char(self, value: char) -> Self::Output;
    fn visit_byte(self, value: u8) -> Self::Output;
    fn visit_byte_string(self, value: Vec<u8>) -> Self::Output;
}

impl PredicateLiteral {
    fn accept<V: LiteralVisitor>(self, visitor: V) -> V::Output {
        match self {
            PredicateLiteral::String(value) => visitor.visit_string(value),
            PredicateLiteral::Char(value) => visitor.visit_char(value),
            PredicateLiteral::Byte(value) => visitor.visit_byte(value),
            PredicateLiteral::ByteString(value) => visitor.visit_byte_string(value),
        }
    }
}

struct StringValueVisitor<'a> {
    owner: &'a str,
}

impl LiteralVisitor for StringValueVisitor<'_> {
    type Output = String;

    fn visit_string(self, value: String) -> Self::Output {
        value
    }

    fn visit_char(self, value: char) -> Self::Output {
        if self.owner == "eq_ignore_ascii_case" {
            return value.to_string();
        }
        panic!("{} receiver did not dispatch to StringLiteral", self.owner)
    }

    fn visit_byte(self, _value: u8) -> Self::Output {
        panic!("{} receiver did not dispatch to StringLiteral", self.owner)
    }

    fn visit_byte_string(self, _value: Vec<u8>) -> Self::Output {
        panic!("{} receiver did not dispatch to StringLiteral", self.owner)
    }
}

struct PatternValueVisitor<'a> {
    owner: &'a str,
}

impl LiteralVisitor for PatternValueVisitor<'_> {
    type Output = String;

    fn visit_string(self, value: String) -> Self::Output {
        value
    }

    fn visit_char(self, value: char) -> Self::Output {
        value.to_string()
    }

    fn visit_byte(self, _value: u8) -> Self::Output {
        panic!(
            "{} argument did not dispatch to StringLiteral/CharLiteral",
            self.owner
        )
    }

    fn visit_byte_string(self, _value: Vec<u8>) -> Self::Output {
        panic!(
            "{} argument did not dispatch to StringLiteral/CharLiteral",
            self.owner
        )
    }
}

struct IsAsciiVisitor<'a> {
    local_scope: &'a str,
}

impl LiteralVisitor for IsAsciiVisitor<'_> {
    type Output = Outcome;

    fn visit_string(self, value: String) -> Self::Output {
        let receiver = str_const(value);
        let name = method_assertion_name("is_ascii", vec![receiver.clone()], self.local_scope);
        constraint(atomic_("str.is_ascii", vec![receiver]), name)
    }

    fn visit_char(self, value: char) -> Self::Output {
        let receiver = str_const(value.to_string());
        let name = method_assertion_name("is_ascii", vec![receiver.clone()], self.local_scope);
        constraint(atomic_("str.is_ascii", vec![receiver]), name)
    }

    fn visit_byte(self, value: u8) -> Self::Output {
        constraint(eq(bool_const(value.is_ascii()), bool_const(true)), None)
    }

    fn visit_byte_string(self, value: Vec<u8>) -> Self::Output {
        let atoms = value
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
}

struct AsciiClassVisitor<'a> {
    owner: &'a str,
    atom_name: &'a str,
}

impl LiteralVisitor for AsciiClassVisitor<'_> {
    type Output = (bool, Rc<Term>);

    fn visit_string(self, _value: String) -> Self::Output {
        panic!(
            "{} receiver did not dispatch to CharLiteral/ByteLiteral",
            self.owner
        )
    }

    fn visit_char(self, value: char) -> Self::Output {
        (
            eval_ascii_char_class(value, self.atom_name),
            str_const(value.to_string()),
        )
    }

    fn visit_byte(self, value: u8) -> Self::Output {
        (
            eval_ascii_byte_class(value, self.atom_name),
            str_const(char::from(value).to_string()),
        )
    }

    fn visit_byte_string(self, _value: Vec<u8>) -> Self::Output {
        panic!(
            "{} receiver did not dispatch to CharLiteral/ByteLiteral",
            self.owner
        )
    }
}

struct AlphabeticVisitor<'a> {
    owner: &'a str,
}

impl LiteralVisitor for AlphabeticVisitor<'_> {
    type Output = (bool, Rc<Term>);

    fn visit_string(self, _value: String) -> Self::Output {
        panic!("{} receiver did not dispatch to CharLiteral", self.owner)
    }

    fn visit_char(self, value: char) -> Self::Output {
        (value.is_alphabetic(), str_const(value.to_string()))
    }

    fn visit_byte(self, _value: u8) -> Self::Output {
        panic!("{} receiver did not dispatch to CharLiteral", self.owner)
    }

    fn visit_byte_string(self, _value: Vec<u8>) -> Self::Output {
        panic!("{} receiver did not dispatch to CharLiteral", self.owner)
    }
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
            if call.args.len() != 1 {
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
            if !call.args.is_empty() {
                return None;
            }
            StringPredicateKind::IsAscii
        }
        "is_ascii_alphabetic" => {
            if !call.args.is_empty() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_alphabetic")
        }
        "is_ascii_digit" => {
            if !call.args.is_empty() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_digit")
        }
        "is_ascii_alphanumeric" => {
            if !call.args.is_empty() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_alphanumeric")
        }
        "is_ascii_octdigit" => {
            if !call.args.is_empty() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_octdigit")
        }
        "is_ascii_lowercase" => {
            if !call.args.is_empty() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_lowercase")
        }
        "is_ascii_uppercase" => {
            if !call.args.is_empty() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_uppercase")
        }
        "is_ascii_hexdigit" => {
            if !call.args.is_empty() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_hexdigit")
        }
        "is_ascii_punctuation" => {
            if !call.args.is_empty() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_punctuation")
        }
        "is_ascii_graphic" => {
            if !call.args.is_empty() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_graphic")
        }
        "is_ascii_whitespace" => {
            if !call.args.is_empty() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_whitespace")
        }
        "is_ascii_control" => {
            if !call.args.is_empty() {
                return None;
            }
            StringPredicateKind::AsciiCharClass("str.is_ascii_control")
        }
        "eq_ignore_ascii_case" => {
            // Concrete-fold: both receiver and argument must be string/char literals.
            if call.args.len() != 1 {
                return None;
            }
            StringPredicateKind::AsciiEqIgnoreCase
        }
        "is_alphabetic" => {
            if !call.args.is_empty() {
                return None;
            }
            StringPredicateKind::IsAlphabetic
        }
        _ => return None,
    };

    Some(Box::new(StringPredicateSugar {
        method,
        receiver_name: simple_path_name(&call.receiver),
        receiver: PredicateOperand::new(&call.receiver, fcx),
        arg: predicate_arg(call, kind, fcx),
        kind,
    }))
}

fn predicate_arg(
    call: &ExprMethodCall,
    kind: StringPredicateKind,
    fcx: &SugarBuildCtx,
) -> PredicateArg {
    match kind {
        StringPredicateKind::Contains
        | StringPredicateKind::Prefix
        | StringPredicateKind::Suffix => {
            PredicateArg::Operand(PredicateOperand::new(&call.args[0], fcx))
        }
        StringPredicateKind::AsciiEqIgnoreCase => {
            PredicateArg::Operand(PredicateOperand::new(&call.args[0], fcx))
        }
        StringPredicateKind::IsAscii
        | StringPredicateKind::AsciiCharClass(_)
        | StringPredicateKind::IsAlphabetic => PredicateArg::None,
    }
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
        if let Some(recv_name) = &self.receiver_name {
            if ctx.scope.is_mut_local(&recv_name) {
                return Outcome::Incomplete(Effect::TemporalRead {
                    boundary: recv_name.clone(),
                });
            }
        }
        let receiver = match self.receiver_string(ctx) {
            Ok(value) => str_const(value),
            Err(outcome) => return outcome,
        };
        let pattern = match &self.arg {
            PredicateArg::Operand(operand) => match operand.dispatch(ctx) {
                Ok(value) => str_const(value.accept(PatternValueVisitor {
                    owner: &self.method,
                })),
                Err(outcome) => return outcome,
            },
            _ => panic!("string predicate constructed without a typed pattern argument"),
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
        match self.receiver.dispatch(ctx) {
            Ok(value) => value.accept(IsAsciiVisitor {
                local_scope: ctx.scope.local_scope(),
            }),
            Err(outcome) => outcome,
        }
    }

    fn desugar_char_class(&self, ctx: &SugarCtx, atom_name: &'static str) -> Outcome {
        // CONCRETE FOLD (Lane 5 teeth): lift the literal → evaluate the actual
        // std predicate on the host → lower the concrete bool.
        // z3 then checks `eq(bool(result), bool(true))` — UNSAT for negation →
        // DISCHARGED.  A bad-twin that asserts the wrong value emits
        // `eq(bool(false), bool(true))` → invariant UNSAT → REFUTED.
        let (result, receiver) = match self.receiver.dispatch(ctx) {
            Ok(value) => value.accept(AsciiClassVisitor {
                owner: &self.method,
                atom_name,
            }),
            Err(outcome) => return outcome,
        };
        let name = method_assertion_name(&self.method, vec![receiver], ctx.scope.local_scope());
        constraint(eq(bool_const(result), bool_const(true)), name)
    }

    /// `s1.eq_ignore_ascii_case(s2)` — both sides are string/char literals.
    /// Evaluate on the host and lower to `eq(bool(result), bool(true))`.
    fn desugar_eq_ignore_ascii_case(&self, ctx: &SugarCtx) -> Outcome {
        let recv_str = match self.receiver_string(ctx) {
            Ok(value) => value,
            Err(outcome) => return outcome,
        };
        let arg_str = match &self.arg {
            PredicateArg::Operand(operand) => match operand.dispatch(ctx) {
                Ok(value) => value.accept(PatternValueVisitor {
                    owner: "eq_ignore_ascii_case",
                }),
                Err(outcome) => return outcome,
            },
            _ => panic!("eq_ignore_ascii_case constructed without typed string argument"),
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
        let (result, receiver) = match self.receiver.dispatch(ctx) {
            Ok(value) => value.accept(AlphabeticVisitor {
                owner: "is_alphabetic",
            }),
            Err(outcome) => return outcome,
        };
        let name = method_assertion_name("is_alphabetic", vec![receiver], ctx.scope.local_scope());
        constraint(eq(bool_const(result), bool_const(true)), name)
    }

    fn receiver_string(&self, ctx: &SugarCtx) -> Result<String, Outcome> {
        self.receiver.dispatch(ctx).map(|value| {
            value.accept(StringValueVisitor {
                owner: &self.method,
            })
        })
    }
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

impl PredicateOperand {
    fn new(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        match strip_refs_groups(expr) {
            Expr::Lit(ExprLit {
                lit: Lit::ByteStr(bytes),
                ..
            }) => PredicateOperand::ByteString(bytes.value()),
            Expr::Path(path) if path.qself.is_none() => {
                let Some(ident) = path.path.get_ident() else {
                    return PredicateOperand::Value(SugarBody::format_value(expr, fcx));
                };
                let name = ident.to_string();
                if fcx.resolving_bound_path(&name) {
                    return PredicateOperand::Value(SugarBody::format_value(expr, fcx));
                }
                if let Some(init) = fcx.scope().stable_let_binding_for_term(&name) {
                    let child_fcx = fcx.with_bound_path(&name);
                    return PredicateOperand::Child(Box::new(PredicateOperand::new(
                        init, &child_fcx,
                    )));
                }
                if let Some(init) = fcx.let_inits().get(&name).copied() {
                    let child_fcx = fcx.with_bound_path(&name);
                    return PredicateOperand::Child(Box::new(PredicateOperand::new(
                        init, &child_fcx,
                    )));
                }
                PredicateOperand::Value(SugarBody::format_value(expr, fcx))
            }
            _ => PredicateOperand::Value(SugarBody::format_value(expr, fcx)),
        }
    }

    fn dispatch(&self, ctx: &SugarCtx) -> Result<PredicateLiteral, Outcome> {
        match self {
            PredicateOperand::Value(body) => match body.reduce_format_value(ctx) {
                FloorRead::Complete(value) => Ok(PredicateLiteral::from_format_value(value)),
                FloorRead::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
            },
            PredicateOperand::ByteString(bytes) => Ok(PredicateLiteral::ByteString(bytes.clone())),
            PredicateOperand::Child(child) => child.dispatch(ctx),
        }
    }
}

impl PredicateLiteral {
    fn from_format_value(value: FmtValue) -> Self {
        match value {
            FmtValue::Str(value) => PredicateLiteral::String(value),
            FmtValue::Char(value) => PredicateLiteral::Char(value),
            FmtValue::Int {
                value,
                suffix: IntKind::U8,
            } => PredicateLiteral::Byte(
                u8::try_from(value).unwrap_or_else(|_| panic!("u8 format value escaped u8 range")),
            ),
            _ => panic!("predicate operand did not dispatch to a supported literal floor"),
        }
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

fn eval_ascii_byte_class(byte: u8, atom_name: &str) -> bool {
    match atom_name {
        "str.is_ascii_alphabetic" => byte.is_ascii_alphabetic(),
        "str.is_ascii_digit" => byte.is_ascii_digit(),
        "str.is_ascii_alphanumeric" => byte.is_ascii_alphanumeric(),
        "str.is_ascii_octdigit" => matches!(byte, b'0'..=b'7'),
        "str.is_ascii_lowercase" => byte.is_ascii_lowercase(),
        "str.is_ascii_uppercase" => byte.is_ascii_uppercase(),
        "str.is_ascii_hexdigit" => byte.is_ascii_hexdigit(),
        "str.is_ascii_punctuation" => byte.is_ascii_punctuation(),
        "str.is_ascii_graphic" => byte.is_ascii_graphic(),
        "str.is_ascii_whitespace" => byte.is_ascii_whitespace(),
        "str.is_ascii_control" => byte.is_ascii_control(),
        _ => panic!("eval_ascii_byte_class: unknown atom name `{atom_name}`"),
    }
}
