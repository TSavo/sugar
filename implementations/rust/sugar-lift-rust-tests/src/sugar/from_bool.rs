// SPDX-License-Identifier: Apache-2.0
//
// Primitive `<IntT>::from(..)` / `IntT::from(..)` sugar.
//
// The call head owns only the destination type. The argument is constructed as a
// typed term body and dispatches as the source floor: bool -> 0/1, char -> codepoint
// for destinations Rust implements, numeric -> checked std `From` conversion.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, PathArguments, Type};

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{
    from_impl_exists, primitive_int_kind, ExactInt, IntKind, NumericFloor,
};
use crate::sugar::ip_addr::{primitive_int_from_literal_ip, LiteralIp};
use crate::sugar::term_dispatch::{ScalarFloorAccept, ScalarFloorVisitor};
use crate::{token_key, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("from_bool", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Call(call) = expr else {
        return None;
    };
    if call.args.len() != 1 {
        return None;
    }
    let dst = primitive_int_from_kind(&call.func)?;
    Some(Box::new(FromPrimitiveSugar {
        arg: SugarBody::term(&call.args[0], fcx),
        dst,
        site: token_key(expr),
    }))
}

struct FromPrimitiveSugar {
    arg: SugarBody<TermFloor>,
    dst: IntKind,
    site: String,
}

impl Sugar for FromPrimitiveSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let arg = match self.arg.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_term()
                .unwrap_or_else(|| panic!("primitive From argument completed as non-term")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        arg.accept_scalar_floor(PrimitiveFromVisitor {
            dst: self.dst,
            site: &self.site,
        })
    }
}

struct PrimitiveFromVisitor<'a> {
    dst: IntKind,
    site: &'a str,
}

impl ScalarFloorVisitor for PrimitiveFromVisitor<'_> {
    type Output = Outcome;

    fn visit_numeric(self, floor: NumericFloor) -> Self::Output {
        let NumericFloor::Typed { value, kind } = floor else {
            panic!(
                "primitive From `{}` received an untyped numeric floor for `{}`",
                self.dst.name, self.site
            );
        };
        if !from_impl_exists(kind, self.dst) {
            panic!(
                "primitive From `{}` received source type `{}` the compiler would reject for `{}`",
                self.dst.name, kind.name, self.site
            );
        }
        let term = value.term_for_kind(self.dst).unwrap_or_else(|| {
            panic!(
                "primitive From `{}` value did not fit destination for `{}`",
                self.dst.name, self.site
            )
        });
        Outcome::Complete(Desugared::Term(term))
    }

    fn visit_bool(self, value: bool) -> Self::Output {
        let term = ExactInt::Unsigned(u128::from(value))
            .term_for_kind(self.dst)
            .unwrap_or_else(|| {
                panic!(
                    "primitive From `{}` could not lower bool for `{}`",
                    self.dst.name, self.site
                )
            });
        Outcome::Complete(Desugared::Term(term))
    }

    fn visit_char(self, value: char) -> Self::Output {
        if !char_from_impl_exists(self.dst) {
            panic!(
                "primitive From `{}` does not implement From<char> for `{}`",
                self.dst.name, self.site
            );
        }
        let term = ExactInt::Unsigned(u128::from(u32::from(value)))
            .term_for_kind(self.dst)
            .unwrap_or_else(|| {
                panic!(
                    "primitive From `{}` could not lower char for `{}`",
                    self.dst.name, self.site
                )
            });
        Outcome::Complete(Desugared::Term(term))
    }

    fn visit_ip(self, _term: &Rc<Term>, ip: LiteralIp) -> Self::Output {
        Outcome::Complete(Desugared::Term(primitive_int_from_literal_ip(
            ip, self.dst, self.site,
        )))
    }

    fn visit_runtime(self, _term: &Rc<Term>) -> Self::Output {
        Outcome::Incomplete(Effect::RuntimeNumericOperand {
            boundary: self.site.to_string(),
            operation: "From".to_string(),
            kind: self.dst.name.to_string(),
        })
    }
}

fn char_from_impl_exists(dst: IntKind) -> bool {
    !dst.signed && dst.bits >= 32
}

/// `<IntT>::from` (qself) or `IntT::from` (two-segment path) where `IntT` is a known
/// primitive integer type. Anything else (a user type, a float, `char`, a longer
/// path) is NOT a std primitive-integer `From` and is declined.
fn primitive_int_from_kind(func: &Expr) -> Option<IntKind> {
    let Expr::Path(path) = func else {
        return None;
    };
    let Some(last) = path.path.segments.last() else {
        return None;
    };
    if last.ident != "from" || !matches!(last.arguments, PathArguments::None) {
        return None;
    }
    if let Some(qself) = &path.qself {
        return primitive_int_type_kind(&qself.ty);
    }
    if path.path.segments.len() == 2
        && matches!(path.path.segments[0].arguments, PathArguments::None)
    {
        primitive_int_kind(&path.path.segments[0].ident.to_string())
    } else {
        None
    }
}

fn primitive_int_type_kind(ty: &Type) -> Option<IntKind> {
    let Type::Path(path) = ty else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    match path.path.segments.last() {
        Some(seg) if matches!(seg.arguments, PathArguments::None) => {
            primitive_int_kind(&seg.ident.to_string())
        }
        _ => None,
    }
}
