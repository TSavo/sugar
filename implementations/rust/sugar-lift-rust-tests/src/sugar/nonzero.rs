// SPDX-License-Identifier: Apache-2.0
//
// `NonZeroSugar`: `NonZero::<T>::new(literal)` and `.get()` over a NonZero-derived
// literal are stdlib value sugar. They are structural wrappers around the integer
// value, with `new(0)` represented as `Option::None`.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, ExprPath, PathArguments, Type};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{ExactInt, NumericFloor};
use crate::sugar::monadic::{none_term, some_term};
use crate::sugar::term_dispatch::{
    MonadicFloorAccept, MonadicFloorVisitor, ScalarFloorAccept, ScalarFloorVisitor,
};
use crate::{str_const, strip_refs_groups, token_key, Desugared, Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const NEW_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("nonzero_new", SugarRole::Term, recognize_new);

pub(crate) const ASSOC_CONST_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "nonzero_assoc_const",
    SugarRole::Term,
    recognize_assoc_const,
);

pub(crate) const GET_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("nonzero_get", SugarRole::Term, recognize_get);

fn recognize_assoc_const(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Path(path) = expr else {
        return None;
    };
    let (kind, konst) = nonzero_assoc_const_path(path)?;
    Some(Box::new(NonZeroAssocConstSugar { kind, konst }))
}

fn recognize_new(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Call(call) = expr else {
        return None;
    };
    if call.args.len() != 1 || !is_nonzero_new_func(&call.func) {
        return None;
    }
    Some(Box::new(NonZeroNewSugar {
        value: SugarBody::term(&call.args[0], fcx),
        site: token_key(expr),
    }))
}

fn recognize_get(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "get" || !call.args.is_empty() || !is_nonzero_derived(&call.receiver) {
        return None;
    }
    Some(Box::new(NonZeroGetSugar {
        receiver: SugarBody::term(&call.receiver, fcx),
        site: token_key(expr),
    }))
}

struct NonZeroAssocConstSugar {
    kind: NonZeroIntegerKind,
    konst: String,
}

impl Sugar for NonZeroAssocConstSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        let term = nonzero_assoc_const_term(self.kind, &self.konst).unwrap_or_else(|| {
            panic!(
                "NonZero associated constant `{}` did not reduce to a scalar floor",
                self.konst
            )
        });
        debug!(
            target: "sugar_lift_rust_tests::sugar::nonzero",
            konst = self.konst.as_str(),
            "resolved NonZero associated constant axiom"
        );
        Outcome::Complete(Desugared::Term(term))
    }
}

struct NonZeroNewSugar {
    value: SugarBody<TermFloor>,
    site: String,
}

impl Sugar for NonZeroNewSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let value = match self.value.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_term()
                .unwrap_or_else(|| panic!("NonZero::new argument completed as non-term")),
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        value.accept_scalar_floor(NonZeroNewVisitor { site: &self.site })
    }
}

struct NonZeroNewVisitor<'a> {
    site: &'a str,
}

impl ScalarFloorVisitor for NonZeroNewVisitor<'_> {
    type Output = Outcome;

    fn visit_numeric(self, floor: NumericFloor) -> Self::Output {
        let is_zero = numeric_floor_is_zero(floor);
        let value = floor.term().unwrap_or_else(|| {
            panic!(
                "NonZero::new numeric floor did not reify as a term for `{}`",
                self.site
            )
        });
        self.complete(value, is_zero)
    }

    fn visit_bool(self, _value: bool) -> Self::Output {
        panic!("NonZero::new received a bool floor for `{}`", self.site)
    }

    fn visit_char(self, value: char) -> Self::Output {
        self.complete(str_const(value.to_string()), value == '\0')
    }

    fn visit_runtime(self, _term: &Rc<Term>) -> Self::Output {
        Outcome::Incomplete(Effect::RuntimeNumericOperand {
            boundary: self.site.to_string(),
            operation: "NonZero::new".to_string(),
            kind: "scalar".to_string(),
        })
    }
}

impl NonZeroNewVisitor<'_> {
    fn complete(self, value: Rc<Term>, is_zero: bool) -> Outcome {
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
        Outcome::Complete(Desugared::Term(term))
    }
}

fn numeric_floor_is_zero(floor: NumericFloor) -> bool {
    match floor {
        NumericFloor::Untyped(value) => value == 0,
        NumericFloor::Typed {
            value: ExactInt::Signed(value),
            ..
        } => value == 0,
        NumericFloor::Typed {
            value: ExactInt::Unsigned(value),
            ..
        } => value == 0,
    }
}

struct NonZeroGetSugar {
    receiver: SugarBody<TermFloor>,
    site: String,
}

impl Sugar for NonZeroGetSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_term()
                .unwrap_or_else(|| panic!("NonZero::get receiver completed as non-term")),
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        receiver.accept_monadic_floor(NonZeroGetMonadicVisitor { site: &self.site })
    }
}

struct NonZeroGetMonadicVisitor<'a> {
    site: &'a str,
}

impl MonadicFloorVisitor for NonZeroGetMonadicVisitor<'_> {
    type Output = Outcome;

    fn visit_some(self, inner: &Rc<Term>) -> Self::Output {
        inner.accept_scalar_floor(NonZeroGetScalarVisitor { site: self.site })
    }

    fn visit_none(self) -> Self::Output {
        panic!(
            "NonZero::get received a None floor for `{}`; unwrap owns that literal panic",
            self.site
        )
    }

    fn visit_ok(self, _inner: &Rc<Term>) -> Self::Output {
        panic!(
            "NonZero::get received a Result::Ok floor for `{}`",
            self.site
        )
    }

    fn visit_err(self, _inner: &Rc<Term>) -> Self::Output {
        panic!(
            "NonZero::get received a Result::Err floor for `{}`",
            self.site
        )
    }

    fn visit_non_monadic(self, term: &Rc<Term>) -> Self::Output {
        term.accept_scalar_floor(NonZeroGetScalarVisitor { site: self.site })
    }
}

struct NonZeroGetScalarVisitor<'a> {
    site: &'a str,
}

impl ScalarFloorVisitor for NonZeroGetScalarVisitor<'_> {
    type Output = Outcome;

    fn visit_numeric(self, floor: NumericFloor) -> Self::Output {
        let value = floor.term().unwrap_or_else(|| {
            panic!(
                "NonZero::get numeric floor did not reify as a term for `{}`",
                self.site
            )
        });
        self.complete(value)
    }

    fn visit_bool(self, _value: bool) -> Self::Output {
        panic!("NonZero::get received a bool floor for `{}`", self.site)
    }

    fn visit_char(self, value: char) -> Self::Output {
        self.complete(str_const(value.to_string()))
    }

    fn visit_runtime(self, _term: &Rc<Term>) -> Self::Output {
        Outcome::Incomplete(Effect::RuntimeNumericOperand {
            boundary: self.site.to_string(),
            operation: "NonZero::get".to_string(),
            kind: "scalar".to_string(),
        })
    }
}

impl NonZeroGetScalarVisitor<'_> {
    fn complete(self, value: Rc<Term>) -> Outcome {
        debug!(
            target: "sugar_lift_rust_tests::sugar::nonzero",
            "resolved NonZero::get stdlib axiom to inner literal"
        );
        Outcome::Complete(Desugared::Term(value))
    }
}

pub(crate) fn is_nonzero_new_call(expr: &Expr) -> bool {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return false;
    };
    is_nonzero_new_func(&call.func)
}

#[derive(Clone, Copy)]
pub(crate) struct NonZeroIntegerKind {
    pub(crate) signed: bool,
    pub(crate) bits: u32,
    pub(crate) name: &'static str,
}

pub(crate) fn nonzero_assoc_const_expr(expr: &Expr) -> Option<(NonZeroIntegerKind, String)> {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return None;
    };
    nonzero_assoc_const_path(path)
}

pub(crate) fn nonzero_assoc_const_path(path: &ExprPath) -> Option<(NonZeroIntegerKind, String)> {
    let konst = path.path.segments.last()?.ident.to_string();
    if !matches!(konst.as_str(), "MIN" | "MAX" | "BITS") {
        return None;
    }
    let ty = if let Some(qself) = &path.qself {
        nonzero_kind_from_type(&qself.ty)?
    } else {
        let ty_segment = path.path.segments.iter().rev().nth(1)?;
        nonzero_kind_from_segment(ty_segment)?
    };
    Some((ty, konst))
}

fn nonzero_assoc_const_term(kind: NonZeroIntegerKind, konst: &str) -> Option<Rc<Term>> {
    let value = match konst {
        "BITS" => return Some(crate::num(i128::from(kind.bits))),
        "MIN" if kind.signed => signed_bounds(kind.bits)?.0,
        "MIN" => 1,
        "MAX" if kind.signed => signed_bounds(kind.bits)?.1,
        "MAX" => {
            let max = unsigned_max(kind.bits)?;
            return Some(unsigned_term(max, kind.bits));
        }
        _ => return None,
    };
    Some(crate::num(value))
}

fn nonzero_kind_from_type(ty: &Type) -> Option<NonZeroIntegerKind> {
    let Type::Path(path) = ty else {
        return None;
    };
    let segment = path.path.segments.last()?;
    nonzero_kind_from_segment(segment)
}

fn nonzero_kind_from_segment(segment: &syn::PathSegment) -> Option<NonZeroIntegerKind> {
    let ident = segment.ident.to_string();
    if ident == "NonZero" {
        let PathArguments::AngleBracketed(args) = &segment.arguments else {
            return None;
        };
        return args.args.iter().find_map(|arg| match arg {
            syn::GenericArgument::Type(ty) => primitive_kind_from_type(ty),
            _ => None,
        });
    }
    ident
        .strip_prefix("NonZero")
        .map(|suffix| suffix.to_ascii_lowercase())
        .and_then(|suffix| primitive_kind(&suffix))
}

fn primitive_kind_from_type(ty: &Type) -> Option<NonZeroIntegerKind> {
    let Type::Path(path) = ty else {
        return None;
    };
    primitive_kind(&path.path.segments.last()?.ident.to_string())
}

fn primitive_kind(name: &str) -> Option<NonZeroIntegerKind> {
    let (signed, bits, name) = match name {
        "i8" => (true, 8, "i8"),
        "i16" => (true, 16, "i16"),
        "i32" => (true, 32, "i32"),
        "i64" => (true, 64, "i64"),
        "i128" => (true, 128, "i128"),
        "isize" => (true, usize::BITS, "isize"),
        "u8" => (false, 8, "u8"),
        "u16" => (false, 16, "u16"),
        "u32" => (false, 32, "u32"),
        "u64" => (false, 64, "u64"),
        "u128" => (false, 128, "u128"),
        "usize" => (false, usize::BITS, "usize"),
        _ => return None,
    };
    Some(NonZeroIntegerKind { signed, bits, name })
}

fn signed_bounds(bits: u32) -> Option<(i128, i128)> {
    if bits == 128 {
        Some((i128::MIN, i128::MAX))
    } else {
        let max = (1i128.checked_shl(bits - 1)?).checked_sub(1)?;
        Some((-max - 1, max))
    }
}

fn unsigned_max(bits: u32) -> Option<u128> {
    if bits == 128 {
        Some(u128::MAX)
    } else {
        (1u128.checked_shl(bits)?).checked_sub(1)
    }
}

fn unsigned_term(value: u128, bits: u32) -> Rc<Term> {
    if bits == 128 {
        crate::u128_term(value)
    } else {
        crate::num(i128::try_from(value).expect("non-u128 unsigned max fits i128"))
    }
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
