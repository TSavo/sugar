// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for pure total `char` methods over char literals (including
// stable SSA literal bindings). Recognition is intentionally lazy: it captures
// the raw receiver/args for the method shape, but the receiver is only proven
// char-literal-owned in `desugar`, after scope/binding context is available.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{eq, num, str_const, ConstValue, Formula, Term};
use syn::{Expr, ExprLit, Lit};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
use crate::sugar::monadic::{none_term, some_term};
use crate::{
    bool_const, callsite_assertion_name, strip_refs_groups, AssertionFactKind, Desugared, Outcome,
    Sugar, SugarCtx, Warrant,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("char_literal_method", &["method"], recognize);

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::with_ordering(
    "constraint_char_literal_method",
    SugarRole::Constraint,
    &["constraint_string_predicate", "constraint_bool_expr"],
    recognize_constraint,
);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.turbofish.is_some() {
        return None;
    }
    let method = call.method.to_string();
    if !is_supported_method(&method, call.args.len()) {
        return None;
    }
    if definitely_not_char_receiver(&call.receiver) {
        return None;
    }

    Some(Box::new(CharMethodSugar {
        method,
        receiver: call.receiver.as_ref().clone(),
        args: call.args.iter().cloned().collect(),
        let_inits: capture_let_inits(fcx),
    }))
}

fn recognize_constraint(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.turbofish.is_some() {
        return None;
    }
    let method = call.method.to_string();
    if !is_bool_method(&method) || !call.args.is_empty() {
        return None;
    }
    if definitely_not_char_receiver(&call.receiver) {
        return None;
    }

    Some(Box::new(CharBoolConstraintSugar {
        method,
        receiver: call.receiver.as_ref().clone(),
        let_inits: capture_let_inits(fcx),
    }))
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

fn merge_let_inits<'a>(
    stable: &'a BTreeMap<String, Expr>,
    captured: &'a BTreeMap<String, Expr>,
) -> BTreeMap<String, &'a Expr> {
    stable
        .iter()
        .map(|(name, init)| (name.clone(), init))
        .chain(captured.iter().map(|(name, init)| (name.clone(), init)))
        .collect()
}

fn is_supported_method(method: &str, argc: usize) -> bool {
    match method {
        "to_digit" => argc == 1,
        "is_alphabetic" | "is_numeric" | "is_ascii" | "is_alphanumeric" | "is_whitespace"
        | "is_uppercase" | "is_lowercase" | "to_ascii_uppercase" | "to_ascii_lowercase"
        | "len_utf8" => argc == 0,
        _ => false,
    }
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

fn method_returns_char(method: &str, argc: usize) -> bool {
    matches!(method, "to_ascii_uppercase" | "to_ascii_lowercase") && argc == 0
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

fn source_resolves_to_char(expr: &Expr, bindings: &BTreeMap<String, &Expr>) -> bool {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Char(_), ..
        }) => true,
        Expr::Path(path) if path.qself.is_none() => {
            let Some(id) = path.path.get_ident().map(ToString::to_string) else {
                return false;
            };
            let Some(bound) = bindings.get(&id).copied() else {
                return false;
            };
            let mut narrowed = bindings.clone();
            narrowed.remove(&id);
            source_resolves_to_char(bound, &narrowed)
        }
        Expr::MethodCall(call)
            if method_returns_char(&call.method.to_string(), call.args.len())
                && call.turbofish.is_none() =>
        {
            source_resolves_to_char(&call.receiver, bindings)
        }
        _ => false,
    }
}

fn term_to_char(term: &Rc<Term>) -> Option<char> {
    let Term::Const {
        value: ConstValue::String(value),
        ..
    } = term.as_ref()
    else {
        return None;
    };
    let mut chars = value.chars();
    let ch = chars.next()?;
    if chars.next().is_none() {
        Some(ch)
    } else {
        None
    }
}

fn term_to_radix(term: &Rc<Term>) -> Option<u32> {
    let Term::Const {
        value: ConstValue::Int(value),
        ..
    } = term.as_ref()
    else {
        return None;
    };
    u32::try_from(*value)
        .ok()
        .filter(|radix| (2..=36).contains(radix))
}

struct CharMethodSugar {
    method: String,
    receiver: Expr,
    args: Vec<Expr>,
    let_inits: BTreeMap<String, Expr>,
}

struct CharBoolConstraintSugar {
    method: String,
    receiver: Expr,
    let_inits: BTreeMap<String, Expr>,
}

impl CharMethodSugar {
    fn build_child_term(
        expr: &Expr,
        fcx: &SugarBuildCtx,
        ctx: &SugarCtx,
    ) -> Result<Rc<Term>, Outcome> {
        match build_term(expr, fcx).desugar(ctx) {
            Outcome::Dug(d) => d.into_term().ok_or_else(|| Outcome::from_opt(None)),
            Outcome::Hit(e) => Err(Outcome::Hit(e)),
        }
    }

    fn opaque_method_term(
        &self,
        receiver: Rc<Term>,
        fcx: &SugarBuildCtx,
        ctx: &SugarCtx,
    ) -> Outcome {
        let mut terms = vec![receiver];
        for arg in &self.args {
            let term = match Self::build_child_term(arg, fcx, ctx) {
                Ok(term) => term,
                Err(outcome) => return outcome,
            };
            terms.push(term);
        }
        Outcome::Dug(Desugared::Term(Rc::new(Term::Ctor {
            name: format!("method:{}", self.method),
            args: terms,
        })))
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

fn method_assertion_name(method: &str, args: Vec<Rc<Term>>, local_scope: &str) -> Option<String> {
    let term = Term::Ctor {
        name: format!("method:{method}"),
        args,
    };
    callsite_assertion_name(&term, local_scope)
}

impl Sugar for CharBoolConstraintSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let stable = stable_let_bindings(ctx.scope);
        let let_inits = merge_let_inits(&stable, &self.let_inits);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let receiver = match CharMethodSugar::build_child_term(&self.receiver, &fcx, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };

        if source_resolves_to_char(&self.receiver, &let_inits) {
            let Some(ch) = term_to_char(&receiver) else {
                return Outcome::from_opt(None);
            };
            let Some(result) = eval_bool_method(&self.method, ch) else {
                return Outcome::from_opt(None);
            };
            let name = method_assertion_name(
                &self.method,
                vec![receiver.clone()],
                ctx.scope.local_scope(),
            );
            return constraint(eq(bool_const(result), bool_const(true)), name);
        }

        let method_term = Rc::new(Term::Ctor {
            name: format!("method:{}", self.method),
            args: vec![receiver],
        });
        let name = callsite_assertion_name(&method_term, ctx.scope.local_scope());
        constraint(eq(method_term, bool_const(true)), name)
    }
}

impl Sugar for CharMethodSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let stable = stable_let_bindings(ctx.scope);
        let let_inits = merge_let_inits(&stable, &self.let_inits);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);

        let receiver = match Self::build_child_term(&self.receiver, &fcx, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        if !source_resolves_to_char(&self.receiver, &let_inits) {
            return self.opaque_method_term(receiver, &fcx, ctx);
        }
        let Some(ch) = term_to_char(&receiver) else {
            return Outcome::from_opt(None);
        };

        let term = match self.method.as_str() {
            method if is_bool_method(method) => {
                let Some(result) = eval_bool_method(method, ch) else {
                    return Outcome::from_opt(None);
                };
                bool_const(result)
            }
            "to_ascii_uppercase" => str_const(ch.to_ascii_uppercase().to_string()),
            "to_ascii_lowercase" => str_const(ch.to_ascii_lowercase().to_string()),
            "len_utf8" => num(ch.len_utf8() as i128),
            "to_digit" => {
                let Some(arg) = self.args.first() else {
                    return Outcome::from_opt(None);
                };
                let arg_term = match Self::build_child_term(arg, &fcx, ctx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                let Some(radix) = term_to_radix(&arg_term) else {
                    return Outcome::from_opt(None);
                };
                match ch.to_digit(radix) {
                    Some(value) => some_term(num(i128::from(value))),
                    None => none_term(),
                }
            }
            _ => return Outcome::from_opt(None),
        };
        Outcome::Dug(Desugared::Term(term))
    }
}
