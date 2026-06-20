// SPDX-License-Identifier: Apache-2.0
//
// `NonZeroSugar`: `NonZero::<T>::new(literal)` and `.get()` over a NonZero-derived
// literal are stdlib value sugar. They are structural wrappers around the integer
// value, with `new(0)` represented as `Option::None`.

use std::rc::Rc;

use sugar_ir_symbolic::{ConstValue, Term};
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::int_sqrt::term_as_int;
use crate::sugar::monadic::{none_term, some_term};
use crate::{const_fold_u128_term, strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const NEW_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "nonzero_new",
    SugarRole::Term,
    SugarPriority::Primary,
    recognize_new,
);

pub(crate) const GET_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "nonzero_get",
    SugarRole::Term,
    SugarPriority::Primary,
    recognize_get,
);

fn recognize_new(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Call(call) = expr else {
        return None;
    };
    if call.args.len() != 1 || !is_nonzero_new_func(&call.func) {
        return None;
    }
    Some(Box::new(NonZeroNewSugar {
        value: build_term(&call.args[0], fcx),
    }))
}

fn recognize_get(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "get" || !call.args.is_empty() || !is_nonzero_derived(&call.receiver) {
        return None;
    }
    Some(Box::new(NonZeroGetSugar {
        receiver: build_term(&call.receiver, fcx),
    }))
}

struct NonZeroNewSugar {
    value: Box<dyn Sugar>,
}

impl Sugar for NonZeroNewSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let value = match self.value.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        let Some(is_zero) = nonzero_scalar_is_zero(&value) else {
            return Outcome::from_opt(None);
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::nonzero",
            is_some = !is_zero,
            "resolved NonZero::new stdlib axiom"
        );
        let term = if is_zero {
            none_term()
        } else {
            some_term(value)
        };
        Outcome::Dug(Desugared::Term(term))
    }
}

fn nonzero_scalar_is_zero(term: &Rc<Term>) -> Option<bool> {
    nonzero_scalar_codepoint(term).map(|n| n == 0).or_else(|| {
        let value = const_fold_u128_term(term)?;
        Some(value == 0)
    })
}

fn nonzero_scalar_codepoint(term: &Rc<Term>) -> Option<i128> {
    term_as_int(term).or_else(|| char_literal_codepoint(term))
}

fn char_literal_codepoint(term: &Rc<Term>) -> Option<i128> {
    let Term::Const {
        value: ConstValue::String(value),
        sort,
    } = term.as_ref()
    else {
        return None;
    };
    if sort.name != "String" {
        return None;
    }
    let mut chars = value.chars();
    let ch = chars.next()?;
    chars.next().is_none().then_some(i128::from(u32::from(ch)))
}

struct NonZeroGetSugar {
    receiver: Box<dyn Sugar>,
}

impl Sugar for NonZeroGetSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        let Some(value) = unwrap_some(&receiver).or_else(|| {
            if term_as_int(&receiver).is_some() || const_fold_u128_term(&receiver).is_some() {
                Some(Rc::clone(&receiver))
            } else {
                None
            }
        }) else {
            return Outcome::from_opt(None);
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::nonzero",
            "resolved NonZero::get stdlib axiom to inner literal"
        );
        Outcome::Dug(Desugared::Term(value))
    }
}

pub(crate) fn is_nonzero_new_call(expr: &Expr) -> bool {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return false;
    };
    is_nonzero_new_func(&call.func)
}

fn is_nonzero_new_func(func: &Expr) -> bool {
    let Expr::Path(path) = strip_refs_groups(func) else {
        return false;
    };
    if path.qself.is_some() || path.path.segments.len() < 2 {
        return false;
    }
    let mut segments = path.path.segments.iter().rev();
    let Some(method) = segments.next() else {
        return false;
    };
    let Some(ty) = segments.next() else {
        return false;
    };
    method.ident == "new" && ty.ident.to_string().starts_with("NonZero")
}

fn is_nonzero_derived(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Call(_) => is_nonzero_new_call(expr),
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "expect" | "unwrap" | "isqrt" | "checked_isqrt" | "get"
            ) =>
        {
            is_nonzero_derived(&call.receiver)
        }
        _ => false,
    }
}

fn unwrap_some(term: &Rc<Term>) -> Option<Rc<Term>> {
    match term.as_ref() {
        Term::Ctor { name, args } if name == crate::sugar::monadic::OPT_SOME && args.len() == 1 => {
            Some(Rc::clone(&args[0]))
        }
        _ => None,
    }
}
