// SPDX-License-Identifier: Apache-2.0
//
// `OptionAdaptorSugar`: value-level std `Option`/`Result` adaptors over grounded
// monadic terms. This owns `.map(|x| ...)`, `.and_then(|x| Some(..))`,
// `.filter(..)`, `.ok_or(..)`, `.map_err(..)`, `.unwrap_or(default)`,
// `.unwrap_or_else(..)`, and `.unwrap_or_default()` as monadic value sugar,
// separate from sequence `MapSugar`.

use std::{collections::BTreeMap, rc::Rc};

use sugar_ir_symbolic::{ConstValue, Sort, Term};
use syn::{Expr, GenericArgument, Path, PathArguments, Type};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{
    compat_reduction, FactoryGap, FactoryReduction, SugarBody, SugarBuildCtx,
};
use crate::sugar::monadic::{
    err_term, is_grounded_literal_term, none_term, ok_term, some_term, OPT_NONE, OPT_SOME, RES_ERR,
    RES_OK,
};
use crate::sugar::option_unwrap::receiver_resolves_monadic_source;
use crate::{
    bool_const, const_eval, const_eval_unary_closure, const_fold_int_term, const_fold_u128_term,
    num, primitive_int_term, str_const, strip_refs_groups, u128_term, ConstVal, Desugared, Effect,
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
            Some(OptionAdaptorSugar::new(
                SugarBody::term(&call.receiver, fcx),
                Kind::Map(f.clone()),
            ))
        }
        ("and_then", 1) => {
            let Expr::Closure(f) = &call.args[0] else {
                return None;
            };
            Some(OptionAdaptorSugar::new(
                SugarBody::term(&call.receiver, fcx),
                Kind::AndThen(f.clone()),
            ))
        }
        ("filter", 1) => {
            let Expr::Closure(f) = &call.args[0] else {
                return None;
            };
            Some(OptionAdaptorSugar::new(
                SugarBody::term(&call.receiver, fcx),
                Kind::Filter(f.clone()),
            ))
        }
        ("ok_or", 1) => Some(OptionAdaptorSugar::new(
            SugarBody::term(&call.receiver, fcx),
            Kind::OkOr(SugarBody::term(&call.args[0], fcx)),
        )),
        ("map_err", 1) => {
            let Expr::Closure(f) = &call.args[0] else {
                return None;
            };
            Some(OptionAdaptorSugar::new(
                SugarBody::term(&call.receiver, fcx),
                Kind::MapErr(f.clone()),
            ))
        }
        ("unwrap_or", 1) => Some(OptionAdaptorSugar::new(
            SugarBody::term(&call.receiver, fcx),
            Kind::UnwrapOr(SugarBody::term(&call.args[0], fcx)),
        )),
        ("unwrap_or_else", 1) => {
            let Expr::Closure(f) = &call.args[0] else {
                return None;
            };
            Some(OptionAdaptorSugar::new(
                SugarBody::term(&call.receiver, fcx),
                Kind::UnwrapOrElse(f.clone()),
            ))
        }
        ("unwrap_or_default", 0) => Some(OptionAdaptorSugar::new(
            SugarBody::term(&call.receiver, fcx),
            Kind::UnwrapOrDefault {
                default: default_term_for_receiver(&call.receiver, fcx, 0),
            },
        )),
        _ => None,
    }
}

enum Kind {
    Map(syn::ExprClosure),
    AndThen(syn::ExprClosure),
    Filter(syn::ExprClosure),
    OkOr(SugarBody),
    MapErr(syn::ExprClosure),
    UnwrapOr(SugarBody),
    UnwrapOrElse(syn::ExprClosure),
    UnwrapOrDefault { default: Option<Rc<Term>> },
}

struct OptionAdaptorSugar {
    receiver: SugarBody,
    kind: Kind,
}

impl OptionAdaptorSugar {
    fn new(receiver: SugarBody, kind: Kind) -> Box<dyn Sugar> {
        Box::new(Self { receiver, kind })
    }
}

impl Sugar for OptionAdaptorSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        let receiver = match term_from_body(&self.receiver, ctx, "option adaptor receiver") {
            Ok(term) => term,
            Err(reduction) => return reduction,
        };
        let outcome = match &self.kind {
            Kind::Map(f) => {
                if let Some(payload) = option_payload(&receiver) {
                    desugar_option_map(f, payload)
                } else if let Some(payload) = result_payload(&receiver) {
                    desugar_result_map(f, payload)
                } else {
                    Outcome::from_opt(None)
                }
            }
            Kind::AndThen(f) => {
                if let Some(payload) = option_payload(&receiver) {
                    desugar_option_and_then(f, payload)
                } else if let Some(payload) = result_payload(&receiver) {
                    desugar_result_and_then(f, payload)
                } else {
                    Outcome::from_opt(None)
                }
            }
            Kind::Filter(f) => {
                if let Some(payload) = option_payload(&receiver) {
                    desugar_option_filter(f, payload)
                } else {
                    Outcome::from_opt(None)
                }
            }
            Kind::OkOr(default) => {
                let default = match build_eager_default(default, ctx) {
                    Ok(term) => term,
                    Err(reduction) => return reduction,
                };
                if let Some(payload) = option_payload(&receiver) {
                    desugar_option_ok_or(payload, default)
                } else {
                    Outcome::from_opt(None)
                }
            }
            Kind::MapErr(f) => {
                if let Some(payload) = result_payload(&receiver) {
                    desugar_result_map_err(f, payload)
                } else {
                    Outcome::from_opt(None)
                }
            }
            Kind::UnwrapOr(default) => {
                let default = match build_eager_default(default, ctx) {
                    Ok(term) => term,
                    Err(reduction) => return reduction,
                };
                if let Some(payload) = option_payload(&receiver) {
                    desugar_option_unwrap_or(payload, default)
                } else if let Some(payload) = result_payload(&receiver) {
                    desugar_result_unwrap_or(payload, default)
                } else {
                    Outcome::from_opt(None)
                }
            }
            Kind::UnwrapOrElse(f) => {
                if let Some(payload) = option_payload(&receiver) {
                    desugar_option_unwrap_or_else(f, payload)
                } else if let Some(payload) = result_payload(&receiver) {
                    desugar_result_unwrap_or_else(f, payload)
                } else {
                    Outcome::from_opt(None)
                }
            }
            Kind::UnwrapOrDefault { default } => {
                if let Some(payload) = option_payload(&receiver) {
                    desugar_option_unwrap_or_default(payload, default.clone())
                } else if let Some(payload) = result_payload(&receiver) {
                    desugar_result_unwrap_or_default(payload, default.clone())
                } else {
                    Outcome::from_opt(None)
                }
            }
        };
        outcome_to_reduction(
            outcome,
            "option adaptor did not reduce to a terminal verdict",
        )
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

fn term_from_body(
    body: &SugarBody,
    ctx: &SugarCtx,
    label: &'static str,
) -> Result<Rc<Term>, FactoryReduction> {
    match body.reduce(ctx) {
        Ok(Outcome::Complete(d)) => d
            .into_term()
            .ok_or_else(|| Err(FactoryGap::new(format!("{label} reduced to non-term")))),
        Ok(Outcome::Incomplete(effect)) => Err(Ok(Outcome::Incomplete(effect))),
        Err(gap) => Err(Err(gap)),
    }
}

fn outcome_to_reduction(outcome: Outcome, gap_reason: &'static str) -> FactoryReduction {
    if outcome.is_structural_bail() {
        Err(FactoryGap::new(gap_reason))
    } else {
        Ok(outcome)
    }
}

#[derive(Clone)]
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

fn desugar_option_and_then(f: &syn::ExprClosure, payload: Option<Rc<Term>>) -> Outcome {
    match payload {
        Some(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "and_then", OPT_SOME) {
                return outcome;
            }
            let Some(value) = term_to_const_val(&inner) else {
                return Outcome::from_opt(None);
            };
            let Some(mapped) = const_eval_unary_option_closure(f, &value) else {
                return Outcome::from_opt(None);
            };
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "and_then",
                "resolved Option::and_then stdlib axiom over Some"
            );
            Outcome::Complete(Desugared::Term(option_payload_term(mapped)))
        }
        None => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "and_then",
                "resolved Option::and_then stdlib axiom over None"
            );
            Outcome::Complete(Desugared::Term(none_term()))
        }
    }
}

fn desugar_result_and_then(f: &syn::ExprClosure, payload: ResultPayload) -> Outcome {
    match payload {
        ResultPayload::Ok(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "and_then", RES_OK) {
                return outcome;
            }
            let Some(value) = term_to_const_val(&inner) else {
                return Outcome::from_opt(None);
            };
            let Some(mapped) = const_eval_unary_result_closure(f, &value) else {
                return Outcome::from_opt(None);
            };
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "and_then",
                "resolved Result::and_then stdlib axiom over Ok"
            );
            Outcome::Complete(Desugared::Term(result_payload_term(mapped)))
        }
        ResultPayload::Err(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "and_then", RES_ERR) {
                return outcome;
            }
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "and_then",
                "resolved Result::and_then stdlib axiom over Err"
            );
            Outcome::Complete(Desugared::Term(err_term(inner)))
        }
    }
}

fn desugar_option_filter(f: &syn::ExprClosure, payload: Option<Rc<Term>>) -> Outcome {
    match payload {
        Some(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "filter", OPT_SOME) {
                return outcome;
            }
            let Some(value) = term_to_const_val(&inner) else {
                return Outcome::from_opt(None);
            };
            let Some(keep) = const_eval_unary_closure(f, &value).and_then(|value| value.as_bool())
            else {
                return Outcome::from_opt(None);
            };
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "filter",
                keep,
                "resolved Option::filter stdlib axiom over Some"
            );
            Outcome::Complete(Desugared::Term(if keep {
                some_term(inner)
            } else {
                none_term()
            }))
        }
        None => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "filter",
                "resolved Option::filter stdlib axiom over None"
            );
            Outcome::Complete(Desugared::Term(none_term()))
        }
    }
}

fn desugar_option_ok_or(payload: Option<Rc<Term>>, default: Rc<Term>) -> Outcome {
    match payload {
        Some(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "ok_or", OPT_SOME) {
                return outcome;
            }
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "ok_or",
                "resolved Option::ok_or stdlib axiom over Some"
            );
            Outcome::Complete(Desugared::Term(ok_term(inner)))
        }
        None => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "ok_or",
                "resolved Option::ok_or stdlib axiom over None"
            );
            Outcome::Complete(Desugared::Term(err_term(default)))
        }
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
            Outcome::Complete(Desugared::Term(some_term(term)))
        }
        None => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "map",
                "resolved Option::map stdlib axiom over None"
            );
            Outcome::Complete(Desugared::Term(none_term()))
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
            Outcome::Complete(Desugared::Term(ok_term(term)))
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
            Outcome::Complete(Desugared::Term(err_term(inner)))
        }
    }
}

fn desugar_result_map_err(f: &syn::ExprClosure, payload: ResultPayload) -> Outcome {
    match payload {
        ResultPayload::Ok(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "map_err", RES_OK) {
                return outcome;
            }
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "map_err",
                "resolved Result::map_err stdlib axiom over Ok"
            );
            Outcome::Complete(Desugared::Term(ok_term(inner)))
        }
        ResultPayload::Err(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "map_err", RES_ERR) {
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
                method = "map_err",
                "resolved Result::map_err stdlib axiom over Err"
            );
            Outcome::Complete(Desugared::Term(err_term(term)))
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
            Outcome::Complete(Desugared::Term(inner))
        }
        None => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "unwrap_or",
                "resolved Option::unwrap_or stdlib axiom over None"
            );
            Outcome::Complete(Desugared::Term(default))
        }
    }
}

fn desugar_option_unwrap_or_else(f: &syn::ExprClosure, payload: Option<Rc<Term>>) -> Outcome {
    match payload {
        Some(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "unwrap_or_else", OPT_SOME) {
                return outcome;
            }
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "unwrap_or_else",
                "resolved Option::unwrap_or_else stdlib axiom over Some"
            );
            Outcome::Complete(Desugared::Term(inner))
        }
        None => {
            let Some(default) =
                const_eval_nullary_closure(f).and_then(|value| const_val_to_term(&value))
            else {
                return Outcome::from_opt(None);
            };
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "unwrap_or_else",
                "resolved Option::unwrap_or_else stdlib axiom over None"
            );
            Outcome::Complete(Desugared::Term(default))
        }
    }
}

fn desugar_result_unwrap_or_else(f: &syn::ExprClosure, payload: ResultPayload) -> Outcome {
    match payload {
        ResultPayload::Ok(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "unwrap_or_else", RES_OK) {
                return outcome;
            }
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "unwrap_or_else",
                "resolved Result::unwrap_or_else stdlib axiom over Ok"
            );
            Outcome::Complete(Desugared::Term(inner))
        }
        ResultPayload::Err(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "unwrap_or_else", RES_ERR) {
                return outcome;
            }
            let Some(value) = term_to_const_val(&inner) else {
                return Outcome::from_opt(None);
            };
            let Some(default) =
                const_eval_unary_closure(f, &value).and_then(|value| const_val_to_term(&value))
            else {
                return Outcome::from_opt(None);
            };
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "unwrap_or_else",
                "resolved Result::unwrap_or_else stdlib axiom over Err"
            );
            Outcome::Complete(Desugared::Term(default))
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
            Outcome::Complete(Desugared::Term(inner))
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
            Outcome::Complete(Desugared::Term(default))
        }
    }
}

fn desugar_option_unwrap_or_default(
    payload: Option<Rc<Term>>,
    default: Option<Rc<Term>>,
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
            Outcome::Complete(Desugared::Term(inner))
        }
        None => {
            let Some(default) = default else {
                return Outcome::from_opt(None);
            };
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "unwrap_or_default",
                "resolved Option::unwrap_or_default stdlib axiom over None"
            );
            Outcome::Complete(Desugared::Term(default))
        }
    }
}

fn desugar_result_unwrap_or_default(payload: ResultPayload, default: Option<Rc<Term>>) -> Outcome {
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
            Outcome::Complete(Desugared::Term(inner))
        }
        ResultPayload::Err(inner) => {
            if let Err(outcome) = ensure_grounded_payload(&inner, "unwrap_or_default", RES_ERR) {
                return outcome;
            }
            let Some(default) = default else {
                return Outcome::from_opt(None);
            };
            debug!(
                target: "sugar_lift_rust_tests::sugar::option_adaptor",
                method = "unwrap_or_default",
                "resolved Result::unwrap_or_default stdlib axiom over Err"
            );
            Outcome::Complete(Desugared::Term(default))
        }
    }
}

fn build_eager_default(default: &SugarBody, ctx: &SugarCtx) -> Result<Rc<Term>, FactoryReduction> {
    let term = match term_from_body(default, ctx, "monadic eager default") {
        Ok(term) => term,
        Err(reduction) => return Err(reduction),
    };
    if !is_grounded_literal_term(term.as_ref()) {
        return Err(Ok(Outcome::Incomplete(Effect::Unsupported {
            reason: "monadic unwrap_or over non-literal default; refused".to_string(),
        })));
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
    Err(Outcome::Incomplete(Effect::Unsupported {
        reason: format!("runtime Option/Result payload, not literal (`{method}` over `{ctor}`)"),
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

fn option_payload_term(payload: Option<Rc<Term>>) -> Rc<Term> {
    match payload {
        Some(term) => some_term(term),
        None => none_term(),
    }
}

fn result_payload_term(payload: ResultPayload) -> Rc<Term> {
    match payload {
        ResultPayload::Ok(term) => ok_term(term),
        ResultPayload::Err(term) => err_term(term),
    }
}

fn const_eval_unary_option_closure(
    closure: &syn::ExprClosure,
    arg: &ConstVal,
) -> Option<Option<Rc<Term>>> {
    let mut env = BTreeMap::new();
    bind_const_arg(closure.inputs.first()?, arg, &mut env)?;
    monadic_option_expr(closure_value_body(closure)?, &env)
}

fn const_eval_unary_result_closure(
    closure: &syn::ExprClosure,
    arg: &ConstVal,
) -> Option<ResultPayload> {
    let mut env = BTreeMap::new();
    bind_const_arg(closure.inputs.first()?, arg, &mut env)?;
    monadic_result_expr(closure_value_body(closure)?, &env)
}

fn const_eval_nullary_closure(closure: &syn::ExprClosure) -> Option<ConstVal> {
    if !closure.inputs.is_empty() {
        return None;
    }
    const_eval(closure_value_body(closure)?, &BTreeMap::new())
}

fn closure_value_body(closure: &syn::ExprClosure) -> Option<&Expr> {
    match closure.body.as_ref() {
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [syn::Stmt::Expr(expr, None)] => Some(expr),
            _ => None,
        },
        expr => Some(expr),
    }
}

fn bind_const_arg(
    pat: &syn::Pat,
    arg: &ConstVal,
    env: &mut BTreeMap<String, ConstVal>,
) -> Option<()> {
    match pat {
        syn::Pat::Ident(ident) if ident.subpat.is_none() => {
            env.insert(ident.ident.to_string(), arg.clone());
            Some(())
        }
        syn::Pat::Wild(_) => Some(()),
        syn::Pat::Paren(paren) => bind_const_arg(&paren.pat, arg, env),
        syn::Pat::Reference(reference) => bind_const_arg(&reference.pat, arg, env),
        syn::Pat::Type(typed) => bind_const_arg(&typed.pat, arg, env),
        _ => None,
    }
}

fn monadic_option_expr(expr: &Expr, env: &BTreeMap<String, ConstVal>) -> Option<Option<Rc<Term>>> {
    match strip_refs_groups(expr) {
        Expr::Path(path)
            if path
                .path
                .segments
                .last()
                .is_some_and(|seg| seg.ident == "None") =>
        {
            Some(None)
        }
        Expr::Call(call) if call.args.len() == 1 => {
            let Expr::Path(path) = strip_refs_groups(&call.func) else {
                return None;
            };
            if !path
                .path
                .segments
                .last()
                .is_some_and(|seg| seg.ident == "Some")
            {
                return None;
            }
            let value = const_eval(call.args.first()?, env)?;
            Some(Some(const_val_to_term(&value)?))
        }
        _ => None,
    }
}

fn monadic_result_expr(expr: &Expr, env: &BTreeMap<String, ConstVal>) -> Option<ResultPayload> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.args.len() != 1 {
        return None;
    }
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    let value = const_eval(call.args.first()?, env)?;
    let term = const_val_to_term(&value)?;
    match path.path.segments.last()?.ident.to_string().as_str() {
        "Ok" => Some(ResultPayload::Ok(term)),
        "Err" => Some(ResultPayload::Err(term)),
        _ => None,
    }
}
