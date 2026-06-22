// SPDX-License-Identifier: Apache-2.0
//
// `OptionAdaptorSugar`: value-level std `Option`/`Result` adaptors over grounded
// monadic terms. This owns `.map(|x| ...)`, `.unwrap_or(default)`, and
// `.unwrap_or_default()` as monadic value sugar, separate from sequence `MapSugar`.

use std::{collections::BTreeMap, rc::Rc};

use sugar_ir_symbolic::{ConstValue, Sort, Term};
use syn::{Expr, GenericArgument, Path, PathArguments, Type};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
use crate::sugar::monadic::{
    err_term, is_grounded_literal_term, none_term, ok_term, some_term, OPT_NONE, OPT_SOME, RES_ERR,
    RES_OK,
};
use crate::sugar::option_unwrap::receiver_resolves_monadic_source;
use crate::{
    bool_const, const_eval_unary_closure, const_fold_int_term, const_fold_u128_term, num,
    primitive_int_term, str_const, strip_refs_groups, u128_term, ConstVal, Desugared, Effect,
    Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("option_adaptor", SugarRole::Term, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !receiver_resolves_monadic_source(&call.receiver, fcx, 0) {
        return None;
    }
    match (call.method.to_string().as_str(), call.args.len()) {
        ("map", 1) => {
            let Expr::Closure(f) = &call.args[0] else {
                return None;
            };
            Some(Box::new(OptionAdaptorSugar {
                receiver: (*call.receiver).clone(),
                kind: Kind::Map(f.clone()),
                let_inits: capture_let_inits(fcx),
            }))
        }
        ("unwrap_or", 1) => Some(Box::new(OptionAdaptorSugar {
            receiver: (*call.receiver).clone(),
            kind: Kind::UnwrapOr(call.args[0].clone()),
            let_inits: capture_let_inits(fcx),
        })),
        ("unwrap_or_default", 0) => Some(Box::new(OptionAdaptorSugar {
            receiver: (*call.receiver).clone(),
            kind: Kind::UnwrapOrDefault,
            let_inits: capture_let_inits(fcx),
        })),
        _ => None,
    }
}

enum Kind {
    Map(syn::ExprClosure),
    UnwrapOr(Expr),
    UnwrapOrDefault,
}

struct OptionAdaptorSugar {
    receiver: Expr,
    kind: Kind,
    let_inits: BTreeMap<String, Expr>,
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

impl Sugar for OptionAdaptorSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let stable = stable_let_bindings(ctx.scope);
        let let_inits: BTreeMap<String, &Expr> = stable
            .iter()
            .map(|(name, init)| (name.clone(), init))
            .chain(
                self.let_inits
                    .iter()
                    .map(|(name, init)| (name.clone(), init)),
            )
            .collect();
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let receiver = match build_term(&self.receiver, &fcx).desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        match &self.kind {
            Kind::Map(f) => {
                if let Some(payload) = option_payload(&receiver) {
                    return desugar_option_map(f, payload);
                }
                if let Some(payload) = result_payload(&receiver) {
                    return desugar_result_map(f, payload);
                }
                Outcome::from_opt(None)
            }
            Kind::UnwrapOr(default) => {
                let default = match build_eager_default(default, &fcx, ctx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                if let Some(payload) = option_payload(&receiver) {
                    return desugar_option_unwrap_or(payload, default);
                }
                if let Some(payload) = result_payload(&receiver) {
                    return desugar_result_unwrap_or(payload, default);
                }
                Outcome::from_opt(None)
            }
            Kind::UnwrapOrDefault => {
                if let Some(payload) = option_payload(&receiver) {
                    return desugar_option_unwrap_or_default(payload, &self.receiver, &fcx);
                }
                if let Some(payload) = result_payload(&receiver) {
                    return desugar_result_unwrap_or_default(payload, &self.receiver, &fcx);
                }
                Outcome::from_opt(None)
            }
        }
    }
}

enum ResultPayload {
    Ok(Rc<Term>),
    Err(Rc<Term>),
}

fn option_payload(term: &Rc<Term>) -> Option<Option<Rc<Term>>> {
    match term.as_ref() {
        Term::Ctor { name, args } if name == OPT_SOME && args.len() == 1 => {
            Some(Some(Rc::clone(&args[0])))
        }
        Term::Ctor { name, args } if name == OPT_NONE && args.is_empty() => Some(None),
        _ => None,
    }
}

fn result_payload(term: &Rc<Term>) -> Option<ResultPayload> {
    match term.as_ref() {
        Term::Ctor { name, args } if name == RES_OK && args.len() == 1 => {
            Some(ResultPayload::Ok(Rc::clone(&args[0])))
        }
        Term::Ctor { name, args } if name == RES_ERR && args.len() == 1 => {
            Some(ResultPayload::Err(Rc::clone(&args[0])))
        }
        _ => None,
    }
}

fn desugar_option_map(f: &syn::ExprClosure, payload: Option<Rc<Term>>) -> Outcome {
    match payload {
        Some(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "map", OPT_SOME) {
                return outcome;
            }
            let Some(value) = term_to_const_val(&inner) else {
                return Outcome::from_opt(None);
            };
            let Some(mapped) = const_eval_unary_closure(f, &value) else {
                return Outcome::from_opt(None);
            };
            let Some(term) = const_val_to_term(&mapped) else {
                return Outcome::from_opt(None);
            };
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "map",
                "resolved Option::map stdlib axiom over Some"
            );
            Outcome::Dug(Desugared::Term(some_term(term)))
        }
        None => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "map",
                "resolved Option::map stdlib axiom over None"
            );
            Outcome::Dug(Desugared::Term(none_term()))
        }
    }
}

fn desugar_result_map(f: &syn::ExprClosure, payload: ResultPayload) -> Outcome {
    match payload {
        ResultPayload::Ok(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "map", RES_OK) {
                return outcome;
            }
            let Some(value) = term_to_const_val(&inner) else {
                return Outcome::from_opt(None);
            };
            let Some(mapped) = const_eval_unary_closure(f, &value) else {
                return Outcome::from_opt(None);
            };
            let Some(term) = const_val_to_term(&mapped) else {
                return Outcome::from_opt(None);
            };
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "map",
                "resolved Result::map stdlib axiom over Ok"
            );
            Outcome::Dug(Desugared::Term(ok_term(term)))
        }
        ResultPayload::Err(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "map", RES_ERR) {
                return outcome;
            }
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "map",
                "resolved Result::map stdlib axiom over Err"
            );
            Outcome::Dug(Desugared::Term(err_term(inner)))
        }
    }
}

fn desugar_option_unwrap_or(payload: Option<Rc<Term>>, default: Rc<Term>) -> Outcome {
    match payload {
        Some(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "unwrap_or", OPT_SOME) {
                return outcome;
            }
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "unwrap_or",
                "resolved Option::unwrap_or stdlib axiom over Some"
            );
            Outcome::Dug(Desugared::Term(inner))
        }
        None => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "unwrap_or",
                "resolved Option::unwrap_or stdlib axiom over None"
            );
            Outcome::Dug(Desugared::Term(default))
        }
    }
}

fn desugar_result_unwrap_or(payload: ResultPayload, default: Rc<Term>) -> Outcome {
    match payload {
        ResultPayload::Ok(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "unwrap_or", RES_OK) {
                return outcome;
            }
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "unwrap_or",
                "resolved Result::unwrap_or stdlib axiom over Ok"
            );
            Outcome::Dug(Desugared::Term(inner))
        }
        ResultPayload::Err(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "unwrap_or", RES_ERR) {
                return outcome;
            }
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "unwrap_or",
                "resolved Result::unwrap_or stdlib axiom over Err"
            );
            Outcome::Dug(Desugared::Term(default))
        }
    }
}

fn desugar_option_unwrap_or_default(
    payload: Option<Rc<Term>>,
    receiver: &Expr,
    fcx: &SugarBuildCtx,
) -> Outcome {
    match payload {
        Some(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "unwrap_or_default", OPT_SOME) {
                return outcome;
            }
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "unwrap_or_default",
                "resolved Option::unwrap_or_default stdlib axiom over Some"
            );
            Outcome::Dug(Desugared::Term(inner))
        }
        None => {
            let Some(default) = default_term_for_receiver(receiver, fcx, 0) else {
                return Outcome::from_opt(None);
            };
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "unwrap_or_default",
                "resolved Option::unwrap_or_default stdlib axiom over None"
            );
            Outcome::Dug(Desugared::Term(default))
        }
    }
}

fn desugar_result_unwrap_or_default(
    payload: ResultPayload,
    receiver: &Expr,
    fcx: &SugarBuildCtx,
) -> Outcome {
    match payload {
        ResultPayload::Ok(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "unwrap_or_default", RES_OK) {
                return outcome;
            }
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "unwrap_or_default",
                "resolved Result::unwrap_or_default stdlib axiom over Ok"
            );
            Outcome::Dug(Desugared::Term(inner))
        }
        ResultPayload::Err(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "unwrap_or_default", RES_ERR) {
                return outcome;
            }
            let Some(default) = default_term_for_receiver(receiver, fcx, 0) else {
                return Outcome::from_opt(None);
            };
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "unwrap_or_default",
                "resolved Result::unwrap_or_default stdlib axiom over Err"
            );
            Outcome::Dug(Desugared::Term(default))
        }
    }
}

fn build_eager_default(
    default: &Expr,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
) -> Result<Rc<Term>, Outcome> {
    let term = match build_term(default, fcx).desugar(ctx) {
        Outcome::Dug(d) => match d.into_term() {
            Some(term) => term,
            None => return Err(Outcome::from_opt(None)),
        },
        Outcome::Hit(e) => return Err(Outcome::Hit(e)),
    };
    if !is_grounded_literal_term(term.as_ref()) {
        return Err(Outcome::Hit(Effect::Unsupported {
            reason: "monadic unwrap_or over non-literal default; refused".to_string(),
        }));
    }
    Ok(term)
}

fn ensure_grounded_payload(
    term: &Rc<Term>,
    method: &str,
    ctor: &'static str,
) -> Result<(), Outcome> {
    if is_grounded_literal_term(term.as_ref()) {
        return Ok(());
    }
    Err(Outcome::Hit(Effect::Unsupported {
        reason: format!("monadic `{method}` over non-literal `{ctor}` payload; refused"),
    }))
}

fn default_term_for_receiver(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> Option<Rc<Term>> {
    if depth > 8 {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Path(path) => {
            if path.qself.is_none() {
                if let Some(name) = path.path.get_ident().map(|ident| ident.to_string()) {
                    if !fcx.resolving_bound_path(&name) {
                        if let Some(init) = fcx.scope().stable_let_binding_for_term(&name) {
                            let child_fcx = fcx.with_bound_path(&name);
                            return default_term_for_receiver(init, &child_fcx, depth + 1);
                        }
                    }
                }
            }
            let ty = option_default_type(path)?;
            default_term_for_type(ty)
        }
        Expr::Call(call) => {
            let Expr::Path(path) = strip_refs_groups(&call.func) else {
                return None;
            };
            let ty = result_ok_default_type(&path.path)?;
            default_term_for_type(ty)
        }
        Expr::Paren(paren) => default_term_for_receiver(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => default_term_for_receiver(&group.expr, fcx, depth + 1),
        _ => None,
    }
}

fn option_default_type(path: &syn::ExprPath) -> Option<&Type> {
    let last = path.path.segments.last()?;
    if last.ident != "None" {
        return None;
    }
    first_type_arg(&last.arguments).or_else(|| {
        path.path.segments.iter().find_map(|seg| {
            (seg.ident == "Option")
                .then(|| first_type_arg(&seg.arguments))
                .flatten()
        })
    })
}

fn result_ok_default_type(path: &Path) -> Option<&Type> {
    let last = path.segments.last()?;
    if !matches!(last.ident.to_string().as_str(), "Ok" | "Err") {
        return None;
    }
    first_type_arg(&last.arguments).or_else(|| {
        path.segments.iter().find_map(|seg| {
            (seg.ident == "Result")
                .then(|| first_type_arg(&seg.arguments))
                .flatten()
        })
    })
}

fn first_type_arg(arguments: &PathArguments) -> Option<&Type> {
    let PathArguments::AngleBracketed(args) = arguments else {
        return None;
    };
    args.args.iter().find_map(|arg| match arg {
        GenericArgument::Type(ty) => Some(ty),
        _ => None,
    })
}

fn default_term_for_type(ty: &Type) -> Option<Rc<Term>> {
    let Type::Path(path) = ty else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    let ident = path.path.segments.last()?.ident.to_string();
    match ident.as_str() {
        "bool" => Some(bool_const(false)),
        "char" => Some(str_const("\0")),
        "String" => Some(str_const("")),
        "u128" => Some(u128_term(0)),
        "i8" | "i16" | "i32" | "i64" | "i128" | "isize" | "u8" | "u16" | "u32" | "u64"
        | "usize" => Some(Rc::new(Term::Const {
            value: ConstValue::Int(0),
            sort: Sort { name: ident },
        })),
        _ => None,
    }
}

fn term_to_const_val(term: &Rc<Term>) -> Option<ConstVal> {
    if let Some(value) = const_fold_u128_term(term) {
        return Some(ConstVal::UInt128(value));
    }
    if let Some(value) = const_fold_int_term(term) {
        return Some(ConstVal::Int(value));
    }
    match term.as_ref() {
        Term::Const {
            value: ConstValue::Bool(value),
            ..
        } => Some(ConstVal::Bool(*value)),
        _ => None,
    }
}

fn const_val_to_term(value: &ConstVal) -> Option<Rc<Term>> {
    match value {
        ConstVal::Int(n) => Some(num(*n)),
        ConstVal::PrimitiveInt { raw, kind } => primitive_int_term(*raw, *kind),
        ConstVal::UInt128(n) => Some(u128_term(*n)),
        ConstVal::Bool(b) => Some(bool_const(*b)),
        ConstVal::Char(ch) => Some(num(i128::from(u32::from(*ch)))),
        _ => None,
    }
}
