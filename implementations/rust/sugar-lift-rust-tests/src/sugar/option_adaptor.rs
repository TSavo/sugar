// SPDX-License-Identifier: Apache-2.0
//
// `OptionAdaptorSugar`: value-level std `Option` adaptors over grounded Option terms.
// This owns `.map(|x| ...)` and `.unwrap_or(default)` as Option sugar, separate from
// sequence `MapSugar`.

use std::rc::Rc;

use sugar_ir_symbolic::{ConstValue, Term};
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::monadic::{none_term, some_term, OPT_NONE, OPT_SOME};
use crate::{
    bool_const, const_eval_unary_closure, const_fold_int_term, const_fold_u128_term, num,
    primitive_int_term, strip_refs_groups, u128_term, ConstVal, Desugared, Outcome, Sugar,
    SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "option_adaptor",
    SugarRole::Term,
    SugarPriority::Primary,
    recognize,
);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !is_option_source(&call.receiver) {
        return None;
    }
    match (call.method.to_string().as_str(), call.args.len()) {
        ("map", 1) => {
            let Expr::Closure(f) = &call.args[0] else {
                return None;
            };
            Some(Box::new(OptionAdaptorSugar {
                receiver: build_term(&call.receiver, fcx),
                kind: Kind::Map(f.clone()),
            }))
        }
        ("unwrap_or", 1) => Some(Box::new(OptionAdaptorSugar {
            receiver: build_term(&call.receiver, fcx),
            kind: Kind::UnwrapOr(build_term(&call.args[0], fcx)),
        })),
        _ => None,
    }
}

fn is_option_source(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Path(path) => path
            .path
            .segments
            .last()
            .is_some_and(|seg| seg.ident == "None"),
        Expr::Call(call) => {
            let Expr::Path(path) = strip_refs_groups(&call.func) else {
                return false;
            };
            path.path
                .segments
                .last()
                .is_some_and(|seg| seg.ident == "Some")
        }
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "checked_isqrt" | "checked_add" | "checked_sub" | "checked_mul" | "checked_div"
            ) =>
        {
            true
        }
        Expr::MethodCall(call)
            if call.method == "map" && call.args.len() == 1 && is_option_source(&call.receiver) =>
        {
            true
        }
        Expr::Paren(paren) => is_option_source(&paren.expr),
        Expr::Group(group) => is_option_source(&group.expr),
        _ => false,
    }
}

enum Kind {
    Map(syn::ExprClosure),
    UnwrapOr(Box<dyn Sugar>),
}

struct OptionAdaptorSugar {
    receiver: Box<dyn Sugar>,
    kind: Kind,
}

impl Sugar for OptionAdaptorSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        match &self.kind {
            Kind::Map(f) => match option_payload(&receiver) {
                Some(Some(inner)) => {
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
                Some(None) => {
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::option_adaptor",
                        method = "map",
                        "resolved Option::map stdlib axiom over None"
                    );
                    Outcome::Dug(Desugared::Term(none_term()))
                }
                None => Outcome::from_opt(None),
            },
            Kind::UnwrapOr(default) => match option_payload(&receiver) {
                Some(Some(inner)) => {
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::option_adaptor",
                        method = "unwrap_or",
                        "resolved Option::unwrap_or stdlib axiom over Some"
                    );
                    Outcome::Dug(Desugared::Term(inner))
                }
                Some(None) => {
                    let default = match default.desugar(ctx) {
                        Outcome::Dug(d) => match d.into_term() {
                            Some(term) => term,
                            None => return Outcome::from_opt(None),
                        },
                        Outcome::Hit(e) => return Outcome::Hit(e),
                    };
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::option_adaptor",
                        method = "unwrap_or",
                        "resolved Option::unwrap_or stdlib axiom over None"
                    );
                    Outcome::Dug(Desugared::Term(default))
                }
                None => Outcome::from_opt(None),
            },
        }
    }
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
