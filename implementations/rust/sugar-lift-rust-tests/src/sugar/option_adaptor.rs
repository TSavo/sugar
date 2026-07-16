// SPDX-License-Identifier: MIT OR Apache-2.0
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

use crate::sugar::claim::{ExprSugarClaim, SugarRole, SugarWitnesses};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::monadic::{
    err_term, is_grounded_literal_term, none_term, ok_term, some_term, OPT_NONE, OPT_SOME, RES_ERR,
    RES_OK,
};
use crate::sugar::option_unwrap::receiver_resolves_monadic_source;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    bool_const, const_eval, const_eval_unary_closure, const_fold_int_term, const_fold_u128_term,
    num, primitive_int_term, str_const, strip_refs_groups, u128_term, ConstVal, Desugared, Effect,
    Outcome, Sugar, SugarCtx,
};

pub(crate) const OPTION_MAP_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::with_ordering(
    "option_map",
    SugarRole::Term,
    &["map_term"],
    SugarWitnesses::pair(
        r#"
            #[test]
            fn t_option_map_good() {
                assert_eq!(Some(2_i32).map(|x| x + 3), Some(5_i32));
            }
        "#,
        r#"
            #[test]
            fn t_option_map_bad() {
                assert_eq!(Some(2_i32).map(|x| x + 3), Some(6_i32));
            }
        "#,
    ),
    recognize_option_map,
);

pub(crate) const OPTION_AND_THEN_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term(
    "option_and_then",
    SugarWitnesses::pair(
        r#"
            #[test]
            fn t_option_and_then_good() {
                assert_eq!(Some(2_i32).and_then(|x| Some(x + 3)), Some(5_i32));
            }
        "#,
        r#"
            #[test]
            fn t_option_and_then_bad() {
                assert_eq!(Some(2_i32).and_then(|x| Some(x + 3)), None::<i32>);
            }
        "#,
    ),
    recognize_option_and_then,
);

pub(crate) const OPTION_OR_ELSE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term(
    "option_or_else",
    SugarWitnesses::pair(
        r#"
            #[test]
            fn t_option_or_else_good() {
                assert_eq!(None::<i32>.or_else(|| Some(4_i32)), Some(4_i32));
            }
        "#,
        r#"
            #[test]
            fn t_option_or_else_bad() {
                assert_eq!(None::<i32>.or_else(|| Some(4_i32)), None::<i32>);
            }
        "#,
    ),
    recognize_option_or_else,
);

pub(crate) const OPTION_FILTER_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term(
    "option_filter",
    SugarWitnesses::pair(
        r#"
            #[test]
            fn t_option_filter_good() {
                assert_eq!(Some(4_i32).filter(|x| *x > 2), Some(4_i32));
            }
        "#,
        r#"
            #[test]
            fn t_option_filter_bad() {
                assert_eq!(Some(4_i32).filter(|x| *x > 2), None::<i32>);
            }
        "#,
    ),
    recognize_option_filter,
);

pub(crate) const OPTION_UNWRAP_OR_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term(
    "option_unwrap_or",
    SugarWitnesses::pair(
        r#"
            #[test]
            fn t_option_unwrap_or_good() {
                assert_eq!(None::<i32>.unwrap_or(9_i32), 9_i32);
            }
        "#,
        r#"
            #[test]
            fn t_option_unwrap_or_bad() {
                assert_eq!(None::<i32>.unwrap_or(9_i32), 8_i32);
            }
        "#,
    ),
    recognize_option_unwrap_or,
);

pub(crate) const OPTION_OK_OR_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term(
    "option_ok_or",
    SugarWitnesses::pair(
        r#"
            #[test]
            fn t_option_ok_or_good() {
                assert_eq!(None::<i32>.ok_or(7_i32), Err::<i32, i32>(7_i32));
            }
        "#,
        r#"
            #[test]
            fn t_option_ok_or_bad() {
                assert_eq!(None::<i32>.ok_or(7_i32), Ok::<i32, i32>(0_i32));
            }
        "#,
    ),
    recognize_option_ok_or,
);

pub(crate) const RESULT_MAP_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::with_ordering(
    "result_map",
    SugarRole::Term,
    &["map_term"],
    SugarWitnesses::pair(
        r#"
            #[test]
            fn t_result_map_good() {
                assert_eq!(Ok::<i32, i32>(2_i32).map(|x| x + 3), Ok::<i32, i32>(5_i32));
            }
        "#,
        r#"
            #[test]
            fn t_result_map_bad() {
                assert_eq!(Ok::<i32, i32>(2_i32).map(|x| x + 3), Ok::<i32, i32>(6_i32));
            }
        "#,
    ),
    recognize_result_map,
);

pub(crate) const RESULT_MAP_ERR_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term(
    "result_map_err",
    SugarWitnesses::pair(
        r#"
            #[test]
            fn t_result_map_err_good() {
                assert_eq!(Err::<i32, i32>(2_i32).map_err(|e| e + 3), Err::<i32, i32>(5_i32));
            }
        "#,
        r#"
            #[test]
            fn t_result_map_err_bad() {
                assert_eq!(Err::<i32, i32>(2_i32).map_err(|e| e + 3), Ok::<i32, i32>(5_i32));
            }
        "#,
    ),
    recognize_result_map_err,
);

pub(crate) const RESULT_AND_THEN_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term(
    "result_and_then",
    SugarWitnesses::pair(
        r#"
            #[test]
            fn t_result_and_then_good() {
                assert_eq!(Ok::<i32, i32>(2_i32).and_then(|x| Ok(x + 3)), Ok::<i32, i32>(5_i32));
            }
        "#,
        r#"
            #[test]
            fn t_result_and_then_bad() {
                assert_eq!(Ok::<i32, i32>(2_i32).and_then(|x| Ok(x + 3)), Err::<i32, i32>(5_i32));
            }
        "#,
    ),
    recognize_result_and_then,
);

pub(crate) const RESULT_OR_ELSE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term(
    "result_or_else",
    SugarWitnesses::pair(
        r#"
            #[test]
            fn t_result_or_else_good() {
                assert_eq!(Err::<i32, i32>(2_i32).or_else(|e| Ok(e + 3)), Ok::<i32, i32>(5_i32));
            }
        "#,
        r#"
            #[test]
            fn t_result_or_else_bad() {
                assert_eq!(Err::<i32, i32>(2_i32).or_else(|e| Ok(e + 3)), Err::<i32, i32>(2_i32));
            }
        "#,
    ),
    recognize_result_or_else,
);

pub(crate) const RESULT_OK_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term(
    "result_ok",
    SugarWitnesses::pair(
        r#"
            #[test]
            fn t_result_ok_good() {
                assert_eq!(Ok::<i32, i32>(5_i32).ok(), Some(5_i32));
            }
        "#,
        r#"
            #[test]
            fn t_result_ok_bad() {
                assert_eq!(Ok::<i32, i32>(5_i32).ok(), None::<i32>);
            }
        "#,
    ),
    recognize_result_ok,
);

pub(crate) const RESULT_ERR_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term(
    "result_err",
    SugarWitnesses::pair(
        r#"
            #[test]
            fn t_result_err_good() {
                assert_eq!(Err::<i32, i32>(6_i32).err(), Some(6_i32));
            }
        "#,
        r#"
            #[test]
            fn t_result_err_bad() {
                assert_eq!(Err::<i32, i32>(6_i32).err(), None::<i32>);
            }
        "#,
    ),
    recognize_result_err,
);

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term(
    "option_adaptor",
    SugarWitnesses::pair(
        r#"
            #[test]
            fn t_option_adaptor_good() {
                assert_eq!(None::<i32>.unwrap_or_else(|| 5_i32), 5_i32);
            }
        "#,
        r#"
            #[test]
            fn t_option_adaptor_bad() {
                assert_eq!(None::<i32>.unwrap_or_else(|| 5_i32), 6_i32);
            }
        "#,
    ),
    recognize_legacy_option_adaptor,
);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Carrier {
    Option,
    Result,
    Any,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Method {
    Map,
    AndThen,
    OrElse,
    Filter,
    OkOr,
    MapErr,
    UnwrapOr,
    UnwrapOrElse,
    UnwrapOrDefault,
    Ok,
    Err,
}

fn recognize_option_map(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    debug_assert!(matches!("map", "map"));
    recognize_for(frag, fcx, Carrier::Option, Method::Map)
}

fn recognize_option_and_then(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    debug_assert!(matches!("and_then", "and_then"));
    recognize_for(frag, fcx, Carrier::Option, Method::AndThen)
}

fn recognize_option_or_else(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    debug_assert!(matches!("or_else", "or_else"));
    recognize_for(frag, fcx, Carrier::Option, Method::OrElse)
}

fn recognize_option_filter(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    debug_assert!(matches!("filter", "filter"));
    recognize_for(frag, fcx, Carrier::Option, Method::Filter)
}

fn recognize_option_unwrap_or(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    debug_assert!(matches!("unwrap_or", "unwrap_or"));
    recognize_for(frag, fcx, Carrier::Option, Method::UnwrapOr)
}

fn recognize_option_ok_or(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    debug_assert!(matches!("ok_or", "ok_or"));
    recognize_for(frag, fcx, Carrier::Option, Method::OkOr)
}

fn recognize_result_map(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    debug_assert!(matches!("map", "map"));
    recognize_for(frag, fcx, Carrier::Result, Method::Map)
}

fn recognize_result_map_err(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    debug_assert!(matches!("map_err", "map_err"));
    recognize_for(frag, fcx, Carrier::Result, Method::MapErr)
}

fn recognize_result_and_then(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    debug_assert!(matches!("and_then", "and_then"));
    recognize_for(frag, fcx, Carrier::Result, Method::AndThen)
}

fn recognize_result_or_else(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    debug_assert!(matches!("or_else", "or_else"));
    recognize_for(frag, fcx, Carrier::Result, Method::OrElse)
}

fn recognize_result_ok(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    debug_assert!(matches!("ok", "ok"));
    recognize_for(frag, fcx, Carrier::Result, Method::Ok)
}

fn recognize_result_err(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    debug_assert!(matches!("err", "err"));
    recognize_for(frag, fcx, Carrier::Result, Method::Err)
}

fn recognize_legacy_option_adaptor(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    recognize_for(frag, fcx, Carrier::Result, Method::UnwrapOr)
        .or_else(|| recognize_for(frag, fcx, Carrier::Any, Method::UnwrapOrElse))
        .or_else(|| recognize_for(frag, fcx, Carrier::Any, Method::UnwrapOrDefault))
}

fn recognize_for(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
    carrier: Carrier,
    method: Method,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !receiver_matches_carrier(&call.receiver, fcx, carrier) {
        return None;
    }
    let carrier = if carrier == Carrier::Any {
        visible_call_monadic_return(&call.receiver, fcx)
            .map(|(carrier, _)| carrier)
            .unwrap_or(Carrier::Any)
    } else {
        carrier
    };
    if method_from_call(&call.method.to_string(), call.args.len())? != method {
        return None;
    }
    match method {
        Method::Map => {
            let Expr::Closure(f) = &call.args[0] else {
                return None;
            };
            Some(OptionAdaptorSugar::new(
                SugarBody::term(&call.receiver, fcx),
                Kind::Map(f.clone()),
                carrier,
            ))
        }
        Method::AndThen => {
            let Expr::Closure(f) = &call.args[0] else {
                return None;
            };
            Some(OptionAdaptorSugar::new(
                SugarBody::term(&call.receiver, fcx),
                Kind::AndThen(f.clone()),
                carrier,
            ))
        }
        Method::OrElse => {
            let Expr::Closure(f) = &call.args[0] else {
                return None;
            };
            Some(OptionAdaptorSugar::new(
                SugarBody::term(&call.receiver, fcx),
                Kind::OrElse(f.clone()),
                carrier,
            ))
        }
        Method::Filter => {
            let Expr::Closure(f) = &call.args[0] else {
                return None;
            };
            Some(OptionAdaptorSugar::new(
                SugarBody::term(&call.receiver, fcx),
                Kind::Filter(f.clone()),
                carrier,
            ))
        }
        Method::OkOr => Some(OptionAdaptorSugar::new(
            SugarBody::term(&call.receiver, fcx),
            Kind::OkOr(SugarBody::term(&call.args[0], fcx)),
            carrier,
        )),
        Method::MapErr => {
            let Expr::Closure(f) = &call.args[0] else {
                return None;
            };
            Some(OptionAdaptorSugar::new(
                SugarBody::term(&call.receiver, fcx),
                Kind::MapErr(f.clone()),
                carrier,
            ))
        }
        Method::UnwrapOr => Some(OptionAdaptorSugar::new(
            SugarBody::term(&call.receiver, fcx),
            Kind::UnwrapOr(SugarBody::term(&call.args[0], fcx)),
            carrier,
        )),
        Method::UnwrapOrElse => {
            let Expr::Closure(f) = &call.args[0] else {
                return None;
            };
            Some(OptionAdaptorSugar::new(
                SugarBody::term(&call.receiver, fcx),
                Kind::UnwrapOrElse(f.clone()),
                carrier,
            ))
        }
        Method::UnwrapOrDefault => Some(OptionAdaptorSugar::new(
            SugarBody::term(&call.receiver, fcx),
            Kind::UnwrapOrDefault {
                default: default_term_for_receiver(&call.receiver, fcx, 0),
            },
            carrier,
        )),
        Method::Ok => Some(OptionAdaptorSugar::new(
            SugarBody::term(&call.receiver, fcx),
            Kind::Ok,
            carrier,
        )),
        Method::Err => Some(OptionAdaptorSugar::new(
            SugarBody::term(&call.receiver, fcx),
            Kind::Err,
            carrier,
        )),
    }
}

fn method_from_call(method: &str, arg_count: usize) -> Option<Method> {
    match (method, arg_count) {
        ("map", 1) => Some(Method::Map),
        ("and_then", 1) => Some(Method::AndThen),
        ("or_else", 1) => Some(Method::OrElse),
        ("filter", 1) => Some(Method::Filter),
        ("ok_or", 1) => Some(Method::OkOr),
        ("map_err", 1) => Some(Method::MapErr),
        ("unwrap_or", 1) => Some(Method::UnwrapOr),
        ("unwrap_or_else", 1) => Some(Method::UnwrapOrElse),
        ("unwrap_or_default", 0) => Some(Method::UnwrapOrDefault),
        ("ok", 0) => Some(Method::Ok),
        ("err", 0) => Some(Method::Err),
        _ => None,
    }
}

fn receiver_matches_carrier(expr: &Expr, fcx: &SugarBuildCtx, carrier: Carrier) -> bool {
    match carrier {
        Carrier::Option => receiver_resolves_option_source(expr, fcx, 0),
        Carrier::Result => receiver_resolves_result_source(expr, fcx, 0),
        Carrier::Any => receiver_resolves_monadic_source(expr, fcx, 0),
    }
}

fn receiver_resolves_option_source(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    if is_syntactic_option_ctor(expr)
        || is_known_option_source(expr, fcx)
        || crate::sugar::iter_terminal::recognizes_monadic_terminal(expr, fcx)
    {
        return true;
    }
    match strip_refs_groups(expr) {
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(|ident| ident.to_string()) else {
                return false;
            };
            if fcx.resolving_bound_path(&name) {
                return false;
            }
            let Some(init) = fcx.scope().stable_let_binding_for_term(&name) else {
                return false;
            };
            let child_fcx = fcx.with_bound_path(&name);
            receiver_resolves_option_source(init, &child_fcx, depth + 1)
        }
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "map" | "and_then" | "or_else" | "filter"
            ) =>
        {
            receiver_resolves_option_source(&call.receiver, fcx, depth + 1)
        }
        Expr::MethodCall(call)
            if matches!(call.method.to_string().as_str(), "ok" | "err") && call.args.is_empty() =>
        {
            receiver_resolves_result_source(&call.receiver, fcx, depth + 1)
        }
        Expr::Paren(paren) => receiver_resolves_option_source(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => receiver_resolves_option_source(&group.expr, fcx, depth + 1),
        _ => false,
    }
}

fn receiver_resolves_result_source(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    if is_syntactic_result_ctor(expr)
        || crate::sugar::inspect::is_stable_result_source(strip_refs_groups(expr), fcx)
        || crate::sugar::array_try_from::folds_to_result(strip_refs_groups(expr), fcx)
    {
        return true;
    }
    match strip_refs_groups(expr) {
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(|ident| ident.to_string()) else {
                return false;
            };
            if fcx.resolving_bound_path(&name) {
                return false;
            }
            let Some(init) = fcx.scope().stable_let_binding_for_term(&name) else {
                return false;
            };
            let child_fcx = fcx.with_bound_path(&name);
            receiver_resolves_result_source(init, &child_fcx, depth + 1)
        }
        Expr::MethodCall(call) if call.method == "ok_or" && call.args.len() == 1 => {
            receiver_resolves_option_source(&call.receiver, fcx, depth + 1)
        }
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "map" | "and_then" | "map_err" | "or_else"
            ) =>
        {
            receiver_resolves_result_source(&call.receiver, fcx, depth + 1)
        }
        Expr::Paren(paren) => receiver_resolves_result_source(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => receiver_resolves_result_source(&group.expr, fcx, depth + 1),
        _ => false,
    }
}

fn is_known_option_source(expr: &Expr, _fcx: &SugarBuildCtx) -> bool {
    if crate::sugar::nonzero::is_nonzero_new_call(strip_refs_groups(expr)) {
        return true;
    }
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return false;
    };
    matches!(
        call.method.to_string().as_str(),
        "checked_isqrt" | "checked_mul" | "checked_add" | "checked_sub" | "checked_div"
    )
}

fn is_syntactic_option_ctor(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Path(path) => path_ends_with(path, "None"),
        Expr::Call(call) if call.args.len() == 1 => {
            let Expr::Path(path) = strip_refs_groups(&call.func) else {
                return false;
            };
            path_ends_with(path, "Some")
        }
        _ => false,
    }
}

fn is_syntactic_result_ctor(expr: &Expr) -> bool {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return false;
    };
    if call.args.len() != 1 {
        return false;
    }
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return false;
    };
    path_ends_with(path, "Ok") || path_ends_with(path, "Err")
}

fn path_ends_with(path: &syn::ExprPath, name: &str) -> bool {
    path.path
        .segments
        .last()
        .is_some_and(|seg| seg.ident == name)
}

enum Kind {
    Map(syn::ExprClosure),
    AndThen(syn::ExprClosure),
    OrElse(syn::ExprClosure),
    Filter(syn::ExprClosure),
    OkOr(SugarBody<TermFloor>),
    MapErr(syn::ExprClosure),
    UnwrapOr(SugarBody<TermFloor>),
    UnwrapOrElse(syn::ExprClosure),
    UnwrapOrDefault { default: Option<Rc<Term>> },
    Ok,
    Err,
}

struct OptionAdaptorSugar {
    receiver: SugarBody<TermFloor>,
    kind: Kind,
    // The Carrier the RECOGNIZER used to match this call site (#3445 Part 1
    // slice, collapse family). `recognize_for` already knows this
    // syntactically -- `Carrier::Option` / `Carrier::Result` are each reached
    // through a single dedicated entry point (`OPTION_UNWRAP_OR_EXPR_SUGAR`,
    // the legacy `option_adaptor` Result arm), so the family is ESTABLISHED at
    // recognize time even when the receiver later reduces to a SYMBOLIC (not
    // concrete Some/None/Ok/Err) value. `Carrier::Any` (the legacy
    // `unwrap_or_else` / `unwrap_or_default` dispatch, which accepts either
    // monadic source syntactically) carries no such fact -- a symbolic
    // receiver under `Carrier::Any` cannot be assigned a family without
    // guessing, so it stays a named typed effect rather than a guarded split.
    carrier: Carrier,
}

impl OptionAdaptorSugar {
    fn new(receiver: SugarBody<TermFloor>, kind: Kind, carrier: Carrier) -> Box<dyn Sugar> {
        Box::new(Self {
            receiver,
            kind,
            carrier,
        })
    }
}

impl Sugar for OptionAdaptorSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match term_from_body(&self.receiver, ctx, "option adaptor receiver") {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        match &self.kind {
            Kind::Map(f) => {
                if let Some(payload) = option_payload(&receiver) {
                    desugar_option_map(f, payload)
                } else if let Some(payload) = result_payload(&receiver) {
                    desugar_result_map(f, payload)
                } else {
                    option_adaptor_gap("map receiver completed without Option/Result floor")
                }
            }
            Kind::AndThen(f) => {
                if let Some(payload) = option_payload(&receiver) {
                    desugar_option_and_then(f, payload)
                } else if let Some(payload) = result_payload(&receiver) {
                    desugar_result_and_then(f, payload)
                } else {
                    option_adaptor_gap("and_then receiver completed without Option/Result floor")
                }
            }
            Kind::OrElse(f) => {
                if let Some(payload) = option_payload(&receiver) {
                    desugar_option_or_else(f, payload)
                } else if let Some(payload) = result_payload(&receiver) {
                    desugar_result_or_else(f, payload)
                } else {
                    option_adaptor_gap("or_else receiver completed without Option/Result floor")
                }
            }
            Kind::Filter(f) => {
                if let Some(payload) = option_payload(&receiver) {
                    desugar_option_filter(f, payload)
                } else {
                    option_adaptor_gap("filter receiver completed without Option floor")
                }
            }
            Kind::OkOr(default) => {
                let default = match build_eager_default(default, ctx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                if let Some(payload) = option_payload(&receiver) {
                    desugar_option_ok_or(payload, default)
                } else {
                    option_adaptor_gap("ok_or receiver completed without Option floor")
                }
            }
            Kind::MapErr(f) => {
                if let Some(payload) = result_payload(&receiver) {
                    desugar_result_map_err(f, payload)
                } else {
                    option_adaptor_gap("map_err receiver completed without Result floor")
                }
            }
            Kind::UnwrapOr(default) => {
                let default = match build_eager_default(default, ctx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                if let Some(payload) = option_payload(&receiver) {
                    desugar_option_unwrap_or(payload, default)
                } else if let Some(payload) = result_payload(&receiver) {
                    desugar_result_unwrap_or(payload, default)
                } else {
                    symbolic_unwrap_or_guarded_split(self.carrier, "unwrap_or", &receiver, default)
                }
            }
            Kind::UnwrapOrElse(f) => {
                if let Some(payload) = option_payload(&receiver) {
                    desugar_option_unwrap_or_else(f, payload)
                } else if let Some(payload) = result_payload(&receiver) {
                    desugar_result_unwrap_or_else(f, payload)
                } else {
                    option_adaptor_gap(
                        "unwrap_or_else receiver completed without Option/Result floor",
                    )
                }
            }
            Kind::UnwrapOrDefault { default } => {
                if let Some(payload) = option_payload(&receiver) {
                    desugar_option_unwrap_or_default(payload, default.clone())
                } else if let Some(payload) = result_payload(&receiver) {
                    desugar_result_unwrap_or_default(payload, default.clone())
                } else if let Some(default) = default.clone() {
                    symbolic_unwrap_or_guarded_split(
                        self.carrier,
                        "unwrap_or_default",
                        &receiver,
                        default,
                    )
                } else {
                    // No reified default term AND no concrete Some/Ok/Err payload:
                    // neither the family nor the none/err-arm value can be
                    // established from this call's own syntax. Named typed
                    // typed incomplete outcome, never a guess.
                    Outcome::Incomplete(Effect::UnestablishableMonadicFamily {
                        method: "unwrap_or_default".to_string(),
                    })
                }
            }
            Kind::Ok => {
                if let Some(payload) = result_payload(&receiver) {
                    desugar_result_ok(payload)
                } else {
                    option_adaptor_gap("ok receiver completed without Result floor")
                }
            }
            Kind::Err => {
                if let Some(payload) = result_payload(&receiver) {
                    desugar_result_err(payload)
                } else {
                    option_adaptor_gap("err receiver completed without Result floor")
                }
            }
        }
    }
}

// ── Symbolic-variant guarded split (#3445 Part 1 slice, collapse family) ───
//
// `unwrap_or`/`unwrap_or_default` over a receiver that reduced to a COMPLETE
// term but not a concrete `Some`/`None`/`Ok`/`Err` literal (a symbolic
// Option/Result: a Var, an opaque call result, ...) used to hit the panic
// arm (`option_adaptor_gap`). T's ruling (#3445) names the carrier: the
// reserved interpreted `adt.is_some`/`adt.is_none`/`adt.is_ok`/`adt.is_err`
// tester family (landed) and the native `opt:some#0`/`res:ok#0` payload
// selectors (PR #3758, landed), composed through the existing
// `cf_ite`/`cf_guarded` value-region carrier -- OptionAdaptorSugar stays a
// value producer whose produced value is itself a control-flow term:
//
//   cf_ite(adt.is_some(r), cf_guarded(adt.is_some(r), opt:some#0(r)),
//                          cf_guarded(adt.is_none(r), default))
//
// The FAMILY (Option vs Result) is never guessed from the value -- it comes
// from `Carrier`, which `recognize_for` fixed at RECOGNIZE time from the
// call's own syntax. `Carrier::Any` (the legacy `unwrap_or_else` /
// `unwrap_or_default` dispatch, which structurally accepts either monadic
// source) carries no such fact, so it cannot select a tester without
// guessing -- a named typed effect (`Effect::UnestablishableMonadicFamily`),
// never a panic and never a silent default family.
fn symbolic_unwrap_or_guarded_split(
    carrier: Carrier,
    method: &'static str,
    receiver: &Rc<Term>,
    default: Rc<Term>,
) -> Outcome {
    let (is_present, is_absent, selector) = match carrier {
        Carrier::Option => (ADT_IS_SOME, ADT_IS_NONE, OPT_SOME_SELECTOR),
        Carrier::Result => (ADT_IS_OK, ADT_IS_ERR, RES_OK_SELECTOR),
        Carrier::Any => {
            return Outcome::Incomplete(Effect::UnestablishableMonadicFamily {
                method: method.to_string(),
            });
        }
    };
    let is_present_term = Rc::new(Term::Ctor {
        name: is_present.to_string(),
        args: vec![Rc::clone(receiver)],
    });
    let is_absent_term = Rc::new(Term::Ctor {
        name: is_absent.to_string(),
        args: vec![Rc::clone(receiver)],
    });
    let some_arm_value = Rc::new(Term::Ctor {
        name: selector.to_string(),
        args: vec![Rc::clone(receiver)],
    });
    let some_arm = Rc::new(Term::Ctor {
        name: "cf_guarded".to_string(),
        args: vec![Rc::clone(&is_present_term), some_arm_value],
    });
    let none_arm = Rc::new(Term::Ctor {
        name: "cf_guarded".to_string(),
        args: vec![Rc::clone(&is_absent_term), default],
    });
    debug!(
        target: "sugar_lift_rust_tests::sugar::option_adaptor",
        method,
        carrier = ?carrier,
        "resolved symbolic Option/Result receiver through the adt.is_* guarded split (#3445)"
    );
    Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
        name: "cf_ite".to_string(),
        args: vec![is_present_term, some_arm, none_arm],
    })))
}

// Reserved interpreted ADT discriminant testers (T's ruling, #3445 Part 1):
// emitter-rendered as NATIVE datatype testers, NEVER declared as EUF
// predicates. See `sugar-ir-compiler-smt-lib/src/emitter.rs`'s
// `ADT_IS_SOME`/`ADT_IS_NONE`/`ADT_IS_OK`/`ADT_IS_ERR` (the same reserved
// names; this is the producer side of that landed carrier).
const ADT_IS_SOME: &str = "adt.is_some";
const ADT_IS_NONE: &str = "adt.is_none";
const ADT_IS_OK: &str = "adt.is_ok";
const ADT_IS_ERR: &str = "adt.is_err";

// Reserved native monadic ADT payload selectors (PR #3758, landed): NEVER
// declared as uninterpreted functions -- they are the datatype's own
// projection accessors, see `is_monadic_field_accessor` in the emitter.
const OPT_SOME_SELECTOR: &str = "opt:some#0";
const RES_OK_SELECTOR: &str = "res:ok#0";

fn term_from_body(
    body: &SugarBody<TermFloor>,
    ctx: &SugarCtx,
    label: &'static str,
) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_term()
            .ok_or_else(|| option_adaptor_gap(&format!("{label} reduced to non-term"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn option_adaptor_gap(reason: &str) -> ! {
    panic!("option_adaptor completed without a monadic literal floor: {reason}")
}

#[derive(Clone)]
enum ResultPayload {
    Ok(Rc<Term>),
    Err(Rc<Term>),
}

impl ResultPayload {
    fn into_std(self) -> Result<Rc<Term>, Rc<Term>> {
        match self {
            Self::Ok(term) => Ok(term),
            Self::Err(term) => Err(term),
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
    let prepared = match prepare_option_payload(payload, "and_then") {
        Ok(prepared) => prepared,
        Err(outcome) => return outcome,
    };
    let mapped = prepared
        .map(|(_, value)| eval_unary_option_payload(f, &value))
        .and_then(|payload| payload);
    debug!(
        target: "sugar_lift_rust_tests::sugar::option_adaptor",
        method = "and_then",
        output = if mapped.is_some() { "Some" } else { "None" },
        "resolved Option::and_then through stdlib combinator floor"
    );
    Outcome::Complete(Desugared::Term(option_payload_term(mapped)))
}

fn desugar_result_and_then(f: &syn::ExprClosure, payload: ResultPayload) -> Outcome {
    let prepared = match prepare_result_ok_payload(payload, "and_then") {
        Ok(prepared) => prepared,
        Err(outcome) => return outcome,
    };
    let mapped =
        result_payload_from_std(prepared.and_then(|(_, value)| eval_unary_result_std(f, &value)));
    debug!(
        target: "sugar_lift_rust_tests::sugar::option_adaptor",
        method = "and_then",
        "resolved Result::and_then through stdlib combinator floor"
    );
    Outcome::Complete(Desugared::Term(result_payload_term(mapped)))
}

fn desugar_option_or_else(f: &syn::ExprClosure, payload: Option<Rc<Term>>) -> Outcome {
    let prepared = match prepare_option_payload(payload, "or_else") {
        Ok(prepared) => prepared.map(|(inner, _)| inner),
        Err(outcome) => return outcome,
    };
    let mapped = prepared.or_else(|| eval_nullary_option_payload(f));
    debug!(
        target: "sugar_lift_rust_tests::sugar::option_adaptor",
        method = "or_else",
        output = if mapped.is_some() { "Some" } else { "None" },
        "resolved Option::or_else through stdlib combinator floor"
    );
    Outcome::Complete(Desugared::Term(option_payload_term(mapped)))
}

fn desugar_result_or_else(f: &syn::ExprClosure, payload: ResultPayload) -> Outcome {
    let prepared = match prepare_result_err_payload(payload, "or_else") {
        Ok(prepared) => prepared,
        Err(outcome) => return outcome,
    };
    let mapped =
        result_payload_from_std(prepared.or_else(|(_, value)| eval_unary_result_std(f, &value)));
    debug!(
        target: "sugar_lift_rust_tests::sugar::option_adaptor",
        method = "or_else",
        "resolved Result::or_else through stdlib combinator floor"
    );
    Outcome::Complete(Desugared::Term(result_payload_term(mapped)))
}

fn desugar_option_filter(f: &syn::ExprClosure, payload: Option<Rc<Term>>) -> Outcome {
    let prepared = match prepare_option_payload(payload, "filter") {
        Ok(prepared) => prepared,
        Err(outcome) => return outcome,
    };
    let filtered = prepared.filter(|(_, value)| {
        const_eval_unary_closure(f, value)
            .and_then(|value| value.as_bool())
            .unwrap_or_else(|| {
                option_adaptor_gap("Option::filter closure did not reduce to a bool literal")
            })
    });
    let mapped = filtered.map(|(inner, _)| inner);
    debug!(
        target: "sugar_lift_rust_tests::sugar::option_adaptor",
        method = "filter",
        output = if mapped.is_some() { "Some" } else { "None" },
        "resolved Option::filter through stdlib combinator floor"
    );
    Outcome::Complete(Desugared::Term(option_payload_term(mapped)))
}

fn desugar_option_ok_or(payload: Option<Rc<Term>>, default: Rc<Term>) -> Outcome {
    let prepared = match prepare_option_payload(payload, "ok_or") {
        Ok(prepared) => prepared.map(|(inner, _)| inner),
        Err(outcome) => return outcome,
    };
    let mapped = match prepared.ok_or(default) {
        Ok(inner) => ResultPayload::Ok(inner),
        Err(default) => ResultPayload::Err(default),
    };
    debug!(
        target: "sugar_lift_rust_tests::sugar::option_adaptor",
        method = "ok_or",
        "resolved Option::ok_or through stdlib combinator floor"
    );
    Outcome::Complete(Desugared::Term(result_payload_term(mapped)))
}

fn desugar_option_map(f: &syn::ExprClosure, payload: Option<Rc<Term>>) -> Outcome {
    let prepared = match prepare_option_payload(payload, "map") {
        Ok(prepared) => prepared,
        Err(outcome) => return outcome,
    };
    let mapped = prepared.map(|(_, value)| eval_unary_const_term(f, &value, "Option::map"));
    debug!(
        target: "sugar_lift_rust_tests::sugar::option_adaptor",
        method = "map",
        output = if mapped.is_some() { "Some" } else { "None" },
        "resolved Option::map through stdlib combinator floor"
    );
    Outcome::Complete(Desugared::Term(option_payload_term(mapped)))
}

fn desugar_result_map(f: &syn::ExprClosure, payload: ResultPayload) -> Outcome {
    let prepared = match prepare_result_ok_payload(payload, "map") {
        Ok(prepared) => prepared,
        Err(outcome) => return outcome,
    };
    let mapped = result_payload_from_std(
        prepared.map(|(_, value)| eval_unary_const_term(f, &value, "Result::map")),
    );
    debug!(
        target: "sugar_lift_rust_tests::sugar::option_adaptor",
        method = "map",
        "resolved Result::map through stdlib combinator floor"
    );
    Outcome::Complete(Desugared::Term(result_payload_term(mapped)))
}

fn desugar_result_map_err(f: &syn::ExprClosure, payload: ResultPayload) -> Outcome {
    let prepared = match prepare_result_err_payload(payload, "map_err") {
        Ok(prepared) => prepared,
        Err(outcome) => return outcome,
    };
    let mapped = result_payload_from_std(
        prepared.map_err(|(_, value)| eval_unary_const_term(f, &value, "Result::map_err")),
    );
    debug!(
        target: "sugar_lift_rust_tests::sugar::option_adaptor",
        method = "map_err",
        "resolved Result::map_err through stdlib combinator floor"
    );
    Outcome::Complete(Desugared::Term(result_payload_term(mapped)))
}

fn desugar_option_unwrap_or(payload: Option<Rc<Term>>, default: Rc<Term>) -> Outcome {
    let prepared = match prepare_option_payload(payload, "unwrap_or") {
        Ok(prepared) => prepared.map(|(inner, _)| inner),
        Err(outcome) => return outcome,
    };
    let term = prepared.unwrap_or(default);
    debug!(
        target: "sugar_lift_rust_tests::sugar::option_adaptor",
        method = "unwrap_or",
        "resolved Option::unwrap_or through stdlib combinator floor"
    );
    Outcome::Complete(Desugared::Term(term))
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
                option_adaptor_gap("Option::unwrap_or_else closure did not reduce to a literal");
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
                option_adaptor_gap(
                    "Result::unwrap_or_else Err payload did not reduce to a const value",
                );
            };
            let Some(default) =
                const_eval_unary_closure(f, &value).and_then(|value| const_val_to_term(&value))
            else {
                option_adaptor_gap("Result::unwrap_or_else closure did not reduce to a literal");
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

fn desugar_result_ok(payload: ResultPayload) -> Outcome {
    let prepared = match prepare_result_ok_payload(payload, "ok") {
        Ok(prepared) => prepared.map(|(inner, _)| inner),
        Err(outcome) => return outcome,
    };
    let mapped = prepared.ok();
    debug!(
        target: "sugar_lift_rust_tests::sugar::option_adaptor",
        method = "ok",
        output = if mapped.is_some() { "Some" } else { "None" },
        "resolved Result::ok through stdlib combinator floor"
    );
    Outcome::Complete(Desugared::Term(option_payload_term(mapped)))
}

fn desugar_result_err(payload: ResultPayload) -> Outcome {
    let prepared = match prepare_result_err_payload(payload, "err") {
        Ok(prepared) => prepared.map_err(|(inner, _)| inner),
        Err(outcome) => return outcome,
    };
    let mapped = prepared.err();
    debug!(
        target: "sugar_lift_rust_tests::sugar::option_adaptor",
        method = "err",
        output = if mapped.is_some() { "Some" } else { "None" },
        "resolved Result::err through stdlib combinator floor"
    );
    Outcome::Complete(Desugared::Term(option_payload_term(mapped)))
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
                // Default::default() was not reified from type context. Inventing a
                // floor would be a fake dig; named incomplete, never a panic
                // (coretests-invariants used to die here on Err/None without Default).
                return Outcome::Incomplete(Effect::UnestablishableMonadicFamily {
                    method: "unwrap_or_default".to_string(),
                });
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
                // Same stop as the Option::None arm: Err path needs Default::default()
                // for the Ok type, and we have no reified term. Incomplete, not panic.
                return Outcome::Incomplete(Effect::UnestablishableMonadicFamily {
                    method: "unwrap_or_default".to_string(),
                });
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

fn build_eager_default(
    default: &SugarBody<TermFloor>,
    ctx: &SugarCtx,
) -> Result<Rc<Term>, Outcome> {
    let term = match term_from_body(default, ctx, "monadic eager default") {
        Ok(term) => term,
        Err(outcome) => return Err(outcome),
    };
    if !is_grounded_literal_term(term.as_ref()) {
        option_adaptor_gap("monadic eager default completed without a literal floor");
    }
    Ok(term)
}

fn prepare_option_payload(
    payload: Option<Rc<Term>>,
    method: &str,
) -> Result<Option<(Rc<Term>, ConstVal)>, Outcome> {
    payload
        .map(|inner| {
            ensure_grounded_payload(&inner, method, OPT_SOME)?;
            let Some(value) = term_to_const_val(&inner) else {
                option_adaptor_gap(&format!(
                    "Option::{method} payload did not reduce to a const value"
                ));
            };
            Ok((inner, value))
        })
        .transpose()
}

fn prepare_result_ok_payload(
    payload: ResultPayload,
    method: &str,
) -> Result<Result<(Rc<Term>, ConstVal), Rc<Term>>, Outcome> {
    match payload.into_std() {
        Ok(inner) => {
            ensure_grounded_payload(&inner, method, RES_OK)?;
            let Some(value) = term_to_const_val(&inner) else {
                option_adaptor_gap(&format!(
                    "Result::{method} Ok payload did not reduce to a const value"
                ));
            };
            Ok(Ok((inner, value)))
        }
        Err(inner) => {
            ensure_grounded_payload(&inner, method, RES_ERR)?;
            Ok(Err(inner))
        }
    }
}

fn prepare_result_err_payload(
    payload: ResultPayload,
    method: &str,
) -> Result<Result<Rc<Term>, (Rc<Term>, ConstVal)>, Outcome> {
    match payload.into_std() {
        Ok(inner) => {
            ensure_grounded_payload(&inner, method, RES_OK)?;
            Ok(Ok(inner))
        }
        Err(inner) => {
            ensure_grounded_payload(&inner, method, RES_ERR)?;
            let Some(value) = term_to_const_val(&inner) else {
                option_adaptor_gap(&format!(
                    "Result::{method} Err payload did not reduce to a const value"
                ));
            };
            Ok(Err((inner, value)))
        }
    }
}

fn eval_unary_const_term(
    closure: &syn::ExprClosure,
    arg: &ConstVal,
    label: &'static str,
) -> Rc<Term> {
    let Some(mapped) = const_eval_unary_closure(closure, arg) else {
        option_adaptor_gap(&format!("{label} closure did not reduce to a literal"));
    };
    let Some(term) = const_val_to_term(&mapped) else {
        option_adaptor_gap(&format!("{label} closure result did not reify to a term"));
    };
    term
}

fn eval_unary_option_payload(closure: &syn::ExprClosure, arg: &ConstVal) -> Option<Rc<Term>> {
    const_eval_unary_option_closure(closure, arg).unwrap_or_else(|| {
        option_adaptor_gap("Option callback did not reduce to an Option literal")
    })
}

fn eval_nullary_option_payload(closure: &syn::ExprClosure) -> Option<Rc<Term>> {
    const_eval_nullary_option_closure(closure)
        .unwrap_or_else(|| option_adaptor_gap("Option::or_else closure did not reduce to Option"))
}

fn eval_unary_result_std(closure: &syn::ExprClosure, arg: &ConstVal) -> Result<Rc<Term>, Rc<Term>> {
    match const_eval_unary_result_closure(closure, arg)
        .unwrap_or_else(|| option_adaptor_gap("Result callback did not reduce to a Result literal"))
    {
        ResultPayload::Ok(term) => Ok(term),
        ResultPayload::Err(term) => Err(term),
    }
}

fn result_payload_from_std(payload: Result<Rc<Term>, Rc<Term>>) -> ResultPayload {
    match payload {
        Ok(term) => ResultPayload::Ok(term),
        Err(term) => ResultPayload::Err(term),
    }
}

fn ensure_grounded_payload(
    term: &Rc<Term>,
    method: &str,
    ctor: &'static str,
) -> Result<(), Outcome> {
    if is_grounded_literal_term(term.as_ref()) {
        return Ok(());
    }
    Err(Outcome::Incomplete(Effect::RuntimeMonadicPayload {
        method: method.to_string(),
        ctor: ctor.to_string(),
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
            if let Some((_, default_ty)) = visible_call_monadic_return(expr, fcx) {
                return default_term_for_type(&default_ty);
            }
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

fn visible_call_monadic_return(expr: &Expr, fcx: &SugarBuildCtx) -> Option<(Carrier, Type)> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    let name = path.path.get_ident()?.to_string();
    let helper = fcx.scope().visible_fn(&name)?;
    let syn::ReturnType::Type(_, ty) = &helper.sig.output else {
        return None;
    };
    monadic_carrier_and_default_type(ty)
}

fn monadic_carrier_and_default_type(ty: &Type) -> Option<(Carrier, Type)> {
    let Type::Path(path) = ty else {
        return None;
    };
    let segment = path.path.segments.last()?;
    let carrier = match segment.ident.to_string().as_str() {
        "Option" => Carrier::Option,
        "Result" => Carrier::Result,
        _ => return None,
    };
    let PathArguments::AngleBracketed(args) = &segment.arguments else {
        return None;
    };
    let default_ty = args.args.iter().find_map(|arg| match arg {
        GenericArgument::Type(ty) => Some(ty.clone()),
        _ => None,
    })?;
    Some((carrier, default_ty))
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

fn const_eval_nullary_option_closure(closure: &syn::ExprClosure) -> Option<Option<Rc<Term>>> {
    if !closure.inputs.is_empty() {
        return None;
    }
    monadic_option_expr(closure_value_body(closure)?, &BTreeMap::new())
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

// ── #3445 Part 1 slice receipts: symbolic-variant collapse family ──────────
//
// `Carrier::Option`/`Carrier::Result` are the ONLY entry points that reach
// `Kind::UnwrapOr` today (`OPTION_UNWRAP_OR_EXPR_SUGAR` and the legacy
// `option_adaptor` claim's Result arm), so a real Rust fixture can never drive
// a symbolic RECEIVER through `Carrier::Any` for `unwrap_or` -- every existing
// symbolic-receiver source shape this crate recognizes (`checked_add` et al.
// over a runtime operand) becomes incomplete upstream as a runtime NUMERIC operand
// before the monadic receiver is even built (`RuntimeNumericOperand`), never
// reaching a bare symbolic Option/Result term. These receipts therefore
// exercise `symbolic_unwrap_or_guarded_split` directly against a synthesized
// symbolic receiver (`make_var`), then run the PRODUCTION SMT-LIB compiler +
// real z3 over the emitted term -- the same compile_asserted_formula_to_parts
// path `sugar-lift-rust-tests/tests/assertion_lift.rs`'s receipts use -- so
// the semantic claim (native tester + native selector + native `ite`, #3445
// Part 1 slice 2's emitter half) is checked for real, not asserted by string
// match.
#[cfg(test)]
mod symbolic_collapse_family_tests {
    use super::*;
    use sugar_ir_symbolic::{atomic_, eq, make_var, ContractDecl, Formula};

    fn z3_binary() -> String {
        std::env::var("Z3").unwrap_or_else(|_| "z3".to_string())
    }

    /// Compile `formula` (a `sugar_ir_symbolic::Formula`, the SAME kind this
    /// crate's real assertion pipeline emits) through the production
    /// SMT-LIB compiler, run real z3 over the result, and report SAT/UNSAT.
    /// Bridges via the SAME JSON round-trip
    /// `sugar-lift-rust-tests/tests/assertion_lift.rs`'s receipts use
    /// (`marshal_declarations` -> `serde_json` -> `CompilerInput::decode_json`).
    fn z3_check(formula: Rc<Formula>, label: &str) -> bool {
        let decl = ContractDecl {
            name: format!("collapse_family_{label}"),
            pre: None,
            post: None,
            inv: Some(formula),
            out_binding: "out".to_string(),
            evidence: None,
            panic_loci: vec![],
            concept_hint: None,
        };
        let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
        let parsed: serde_json::Value =
            serde_json::from_str(&doc).expect("marshaled declarations decode as JSON");
        let inv_json = parsed[0]["inv"].clone();
        let input =
            sugar_ir_compiler::CompilerInput::decode_json(inv_json).expect("decode IR-JSON inv");
        let sugar_ir_compiler::CompilerInput::Formula(ir_formula) = input else {
            panic!("expected a formula input");
        };
        let parts =
            sugar_ir_compiler_smt_lib::compile_asserted_formula_to_parts(ir_formula.formula())
                .expect("guarded-split formula must compile to SMT-LIB");
        let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
        let path = std::env::temp_dir().join(format!("sugar_3445_collapse_{label}.smt2"));
        std::fs::write(&path, &script).expect("write smt2");
        let out = std::process::Command::new(z3_binary())
            .arg(&path)
            .output()
            .expect("run z3");
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
            "guarded-split formula must be well-sorted:\n{stdout}\n--- {script}"
        );
        stdout.contains("sat") && !stdout.contains("unsat")
    }

    /// Conjoin: `r` IS the some/ok variant, its payload is `5`, and the
    /// guarded-split value equals `claimed`.
    fn some_arm_claim(carrier: Carrier, claimed: i128) -> Rc<Formula> {
        let r = make_var("r");
        let default = num(999); // never read on the some/ok arm
        let split = match symbolic_unwrap_or_guarded_split(carrier, "unwrap_or", &r, default) {
            Outcome::Complete(Desugared::Term(term)) => term,
            Outcome::Complete(_) => panic!("expected a Term, got a non-Term Desugared"),
            Outcome::Incomplete(_) => {
                panic!("expected a completed guarded-split term, got Incomplete")
            }
        };
        let (is_present, selector) = match carrier {
            Carrier::Option => (ADT_IS_SOME, OPT_SOME_SELECTOR),
            Carrier::Result => (ADT_IS_OK, RES_OK_SELECTOR),
            Carrier::Any => unreachable!("test only drives the established carriers"),
        };
        let is_present_fact = atomic_(is_present, vec![Rc::clone(&r)]);
        let payload_fact = eq(
            Rc::new(Term::Ctor {
                name: selector.to_string(),
                args: vec![Rc::clone(&r)],
            }),
            num(5),
        );
        let claim_fact = eq(split, num(claimed));
        sugar_ir_symbolic::connective_("and", vec![is_present_fact, payload_fact, claim_fact])
    }

    #[test]
    fn positive_symbolic_unwrap_or_discharges_through_guarded_split_option() {
        // r is established `Some`-shaped with payload 5; the guarded split's
        // some-arm reads `opt:some#0(r)`, so claiming the split equals 5 must
        // be SAT -- the native tester + native selector + native `ite`
        // actually thread the discriminant/projection laws.
        let sat = z3_check(
            some_arm_claim(Carrier::Option, 5),
            "positive_option_unwrap_or",
        );
        assert!(
            sat,
            "symbolic Option receiver unwrap_or must discharge through the guarded split (SAT)"
        );
    }

    #[test]
    fn positive_symbolic_unwrap_or_discharges_through_guarded_split_result() {
        let sat = z3_check(
            some_arm_claim(Carrier::Result, 5),
            "positive_result_unwrap_or",
        );
        assert!(
            sat,
            "symbolic Result receiver unwrap_or must discharge through the guarded split (SAT)"
        );
    }

    #[test]
    fn discrimination_lying_twin_flips_red_through_the_same_door() {
        // Same construction, same door (the guarded-split term), but the
        // claimed value (6) contradicts the established payload fact
        // (opt:some#0(r) = 5) via the SAME native selector -- must be UNSAT.
        let sat = z3_check(
            some_arm_claim(Carrier::Option, 6),
            "discrimination_lying_twin",
        );
        assert!(
            !sat,
            "lying twin (claimed value contradicts the established payload) must be UNSAT"
        );
    }

    #[test]
    fn structural_unestablishable_family_yields_typed_effect_not_panic() {
        // Carrier::Any (the legacy unwrap_or_else/unwrap_or_default dispatch)
        // carries no static Option-vs-Result fact. A symbolic receiver under
        // it must be incomplete by NAME -- never guess a family, never panic.
        let r = make_var("r");
        let default = num(9);
        let outcome =
            symbolic_unwrap_or_guarded_split(Carrier::Any, "unwrap_or_default", &r, default);
        match outcome {
            Outcome::Incomplete(Effect::UnestablishableMonadicFamily { method }) => {
                assert_eq!(method, "unwrap_or_default");
            }
            Outcome::Complete(_) => panic!(
                "unestablishable family must yield a typed Effect::UnestablishableMonadicFamily, \
                 not a completed Outcome (and never a panic)"
            ),
            Outcome::Incomplete(_) => panic!(
                "unestablishable family must yield Effect::UnestablishableMonadicFamily specifically, \
                 not some other Effect"
            ),
        }
    }

    #[test]
    fn err_unwrap_or_default_without_reified_default_is_incomplete_not_panic() {
        // Concrete Err payload but no Default::default() term reified from type
        // context — must not die in option_adaptor_gap (coretests-invariants).
        let err = Rc::new(Term::Ctor {
            name: RES_ERR.to_string(),
            args: vec![num(1)],
        });
        let payload = result_payload(&err).expect("Err ctor");
        let outcome = desugar_result_unwrap_or_default(payload, None);
        match outcome {
            Outcome::Incomplete(Effect::UnestablishableMonadicFamily { method }) => {
                assert_eq!(method, "unwrap_or_default");
            }
            Outcome::Complete(_) => panic!(
                "expected UnestablishableMonadicFamily Incomplete, got Complete"
            ),
            Outcome::Incomplete(_) => panic!(
                "expected UnestablishableMonadicFamily Incomplete, got other Incomplete"
            ),
        }
    }

    #[test]
    fn visible_helper_return_type_pins_monadic_family_and_default_type() {
        let result_ty: Type = syn::parse_str("Result<isize, &'static str>").unwrap();
        let option_ty: Type = syn::parse_str("Option<u8>").unwrap();

        let (result_carrier, result_default) =
            monadic_carrier_and_default_type(&result_ty).expect("Result return type");
        assert_eq!(result_carrier, Carrier::Result);
        assert_eq!(crate::token_key(result_default), "isize");

        let (option_carrier, option_default) =
            monadic_carrier_and_default_type(&option_ty).expect("Option return type");
        assert_eq!(option_carrier, Carrier::Option);
        assert_eq!(crate::token_key(option_default), "u8");
    }
}
