// SPDX-License-Identifier: Apache-2.0
//
// LiteralIteratorQuantifierSugar: `iter().all(..)` / `iter().any(..)` in
// assertion position over finite literal domains. The receiver construction is
// the stdlib/compiler axiom; every closure body is lowered by the recursive
// constraint factory after substituting the pinned element.

use std::collections::BTreeMap;
use std::rc::Rc;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_constraint, SugarBuildCtx};
use crate::{
    ascii_byte_class_atom, ascii_char_class_atom, bool_const, closure_simple_param_name,
    literal_byte_string_value, literal_char_predicate_atom, literal_string_value,
    matches_param_receiver, scalar_iter_domain_elems, scalar_literal_array_elems, simple_path_name,
    substitute_expr, term_single_char_value, token_key, AssertionFactKind, Desugared, Effect,
    Outcome, Sugar, SugarCtx, Warrant, STRUCTURAL_BACKSTOP_REASON,
};
use sugar_ir_symbolic::{and_, eq, num, or_, str_const, Formula, Term};
use syn::{Expr, ExprClosure, ExprMethodCall};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_literal_iterator_quantifier",
    SugarRole::Constraint,
    recognize,
);

#[derive(Clone, Copy)]
enum Quantifier {
    All,
    Any,
}

#[derive(Clone, Copy)]
enum LiteralIteratorKind {
    Chars,
    Bytes,
}

struct LiteralIteratorQuantifierSugar {
    method: Quantifier,
    receiver: Expr,
    closure: ExprClosure,
}

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    recognize_method(call, fcx).map(|sugar| Box::new(sugar) as Box<dyn Sugar>)
}

fn recognize_method(
    call: &ExprMethodCall,
    fcx: &SugarBuildCtx,
) -> Option<LiteralIteratorQuantifierSugar> {
    let method = match call.method.to_string().as_str() {
        "all" if call.args.len() == 1 => Quantifier::All,
        "any" if call.args.len() == 1 => Quantifier::Any,
        _ => return None,
    };
    let Expr::Closure(closure) = call.args.first()? else {
        return None;
    };
    if closure.inputs.len() != 1 {
        return None;
    }
    if literal_iterator_elements(&call.receiver).is_none()
        && scalar_iter_domain_elems(&call.receiver, fcx.scope()).is_none()
        && scalar_iter_domain_elems_from_let_inits(&call.receiver, fcx.let_inits()).is_none()
    {
        return None;
    }
    Some(LiteralIteratorQuantifierSugar {
        method,
        receiver: (*call.receiver).clone(),
        closure: closure.clone(),
    })
}

impl Sugar for LiteralIteratorQuantifierSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let Some(param_name) = closure_simple_param_name(&self.closure) else {
            if literal_iterator_elements(&self.receiver).is_some()
                || scalar_iter_domain_elems(&self.receiver, ctx.scope).is_some()
            {
                return unsupported(format!(
                    "{} predicate requires a simple identifier parameter",
                    self.method.as_str()
                ));
            }
            return Outcome::Hit(Effect::Unsupported {
                reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
            });
        };

        if let Some((kind, elements)) = literal_iterator_elements(&self.receiver) {
            let mut atoms = Vec::new();
            for element in elements {
                let atom = match iterator_element_predicate_atom(
                    self.closure.body.as_ref(),
                    &param_name,
                    element,
                    kind,
                ) {
                    Ok(atom) => atom,
                    Err(reason) => return unsupported(reason),
                };
                atoms.push(atom);
            }
            return constraint(self.join(atoms), AssertionFactKind::Warranted, None);
        }

        let Some(elements) = scalar_iter_domain_elems(&self.receiver, ctx.scope) else {
            return Outcome::Hit(Effect::Unsupported {
                reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
            });
        };
        let mut atoms = Vec::new();
        let mut kind = AssertionFactKind::Support;
        for element in elements {
            let mut bindings = BTreeMap::new();
            bindings.insert(param_name.clone(), element);
            let body = substitute_expr(self.closure.body.as_ref(), &bindings);
            let empty = BTreeMap::new();
            let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &empty);
            let payload = match constraint_payload(&*build_constraint(&body, &fcx), ctx) {
                Ok(payload) => payload,
                Err(outcome) => return outcome,
            };
            if payload.kind.is_warranted() {
                kind = AssertionFactKind::Warranted;
            }
            atoms.push(payload.atom);
        }
        constraint(self.join(atoms), kind, None)
    }
}

impl LiteralIteratorQuantifierSugar {
    fn join(&self, atoms: Vec<Rc<Formula>>) -> Rc<Formula> {
        match self.method {
            Quantifier::All => {
                if atoms.is_empty() {
                    eq(bool_const(true), bool_const(true))
                } else {
                    and_(atoms)
                }
            }
            Quantifier::Any => {
                if atoms.is_empty() {
                    eq(bool_const(true), bool_const(false))
                } else {
                    or_(atoms)
                }
            }
        }
    }
}

impl Quantifier {
    fn as_str(self) -> &'static str {
        match self {
            Quantifier::All => "all",
            Quantifier::Any => "any",
        }
    }
}

fn scalar_iter_domain_elems_from_let_inits(
    receiver: &Expr,
    let_inits: &BTreeMap<String, &Expr>,
) -> Option<Vec<Expr>> {
    let base = crate::iter_adaptor_base(receiver);
    if let Some(elems) = scalar_literal_array_elems(base) {
        return Some(elems);
    }
    let name = simple_path_name(base)?;
    scalar_literal_array_elems(let_inits.get(&name)?)
}

fn literal_iterator_elements(expr: &Expr) -> Option<(LiteralIteratorKind, Vec<Rc<Term>>)> {
    match expr {
        Expr::MethodCall(call) if call.args.is_empty() && call.method == "chars" => {
            let value = literal_string_value(&call.receiver)?;
            let elements = value
                .chars()
                .map(|ch| str_const(ch.to_string()))
                .collect::<Vec<_>>();
            Some((LiteralIteratorKind::Chars, elements))
        }
        Expr::MethodCall(call) if call.args.is_empty() && call.method == "iter" => {
            let bytes = literal_byte_string_value(&call.receiver)?;
            let elements = bytes.into_iter().map(|b| num(i128::from(b))).collect();
            Some((LiteralIteratorKind::Bytes, elements))
        }
        Expr::Paren(paren) => literal_iterator_elements(&paren.expr),
        Expr::Group(group) => literal_iterator_elements(&group.expr),
        _ => None,
    }
}

fn iterator_element_predicate_atom(
    body: &Expr,
    param_name: &str,
    element: Rc<Term>,
    iter_kind: LiteralIteratorKind,
) -> Result<Rc<Formula>, String> {
    let Expr::MethodCall(call) = body else {
        return Err(format!(
            "iterator closure body must be a simple method call, got `{}`",
            token_key(body)
        ));
    };
    if !call.args.is_empty() {
        return Err(format!(
            "iterator closure predicate `{}` expects no arguments",
            call.method
        ));
    }
    if !matches_param_receiver(&call.receiver, param_name) {
        return Err(format!(
            "iterator closure predicate must read its bound parameter `{param_name}`"
        ));
    }
    let method = call.method.to_string();
    match iter_kind {
        LiteralIteratorKind::Chars => ascii_char_class_atom(&method, element.clone())
            .or_else(|| {
                term_single_char_value(&element)
                    .and_then(|ch| literal_char_predicate_atom(&method, ch))
            })
            .ok_or_else(|| format!("unsupported char iterator predicate `{method}`")),
        LiteralIteratorKind::Bytes => ascii_byte_class_atom(&method, element)
            .ok_or_else(|| format!("unsupported byte iterator predicate `{method}`")),
    }
}

struct ConstraintPayload {
    atom: Rc<Formula>,
    kind: AssertionFactKind,
}

fn constraint_payload(node: &dyn Sugar, ctx: &SugarCtx) -> Result<ConstraintPayload, Outcome> {
    match node.desugar(ctx) {
        Outcome::Dug(Desugared::Constraints { atom, kind, .. }) => {
            Ok(ConstraintPayload { atom, kind })
        }
        Outcome::Dug(_) => Err(Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })),
        Outcome::Hit(effect) => Err(Outcome::Hit(effect)),
    }
}

fn constraint(atom: Rc<Formula>, kind: AssertionFactKind, name: Option<String>) -> Outcome {
    Outcome::Dug(Desugared::Constraints {
        atom,
        n: 1,
        kind,
        warrant: Warrant { name },
    })
}

fn unsupported(reason: String) -> Outcome {
    Outcome::Hit(Effect::Unsupported { reason })
}
