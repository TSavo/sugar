// SPDX-License-Identifier: Apache-2.0
//
// `ConstSugar`: a compiler-known `const` path is transparent to its initializer.
// The compiler already proved the path resolves for compiling code; recognition
// constructs the initializer body up front instead of freezing the path as a free var.

use std::rc::Rc;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{primitive_int_kind, typed_int_term, ExactInt, IntKind};

use sugar_ir_symbolic::Term;

use crate::{const_path_key, str_const, token_key, Desugared, Outcome, Sugar, SugarCtx};
use syn::{Expr, ExprPath, Type};
use tracing::debug;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("const", &["path"], recognize);

pub(crate) const COMPOSITE_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::composite("const_composite", recognize_composite);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if let Some(term) = primitive_assoc_const_term(expr) {
        return Some(ConstSugar::new_primitive(token_key(expr), term));
    }
    let (name, path) = simple_const_path(expr)?;
    if fcx.resolving_const_path(&name) {
        return None;
    }
    let ConstBody::Term(body) = construct_const_body(&name, path, fcx, ConstBodyRole::Term)? else {
        return None;
    };
    Some(ConstSugar::new_path(name, body))
}

fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let (name, path) = simple_const_path(expr)?;
    if fcx.resolving_const_path(&name) {
        return None;
    }
    let ConstBody::Composite(body) =
        construct_const_body(&name, path, fcx, ConstBodyRole::Composite)?
    else {
        return None;
    };
    Some(ConstCompositeSugar::new(name, body))
}

fn simple_const_path(expr: &Expr) -> Option<(String, &syn::Path)> {
    let Expr::Path(ExprPath {
        qself: None, path, ..
    }) = expr
    else {
        return None;
    };
    let name = const_path_key(path)?;
    Some((name, path))
}

fn primitive_assoc_const_expr(expr: &Expr) -> Option<PrimitiveAssocConst> {
    let Expr::Path(path) = expr else {
        return None;
    };
    if let Some(qself) = &path.qself {
        let ty = primitive_type_name(&qself.ty)?;
        let konst = path.path.segments.last()?.ident.to_string();
        return primitive_assoc_const_parts(&ty, &konst);
    }
    primitive_assoc_const_value(&path.path)
}

fn primitive_assoc_const_value(path: &syn::Path) -> Option<PrimitiveAssocConst> {
    if path.segments.len() != 2 {
        return None;
    }
    if path
        .segments
        .iter()
        .any(|segment| !matches!(segment.arguments, syn::PathArguments::None))
    {
        return None;
    }
    let ty = path.segments[0].ident.to_string();
    let konst = path.segments[1].ident.to_string();
    primitive_assoc_const_parts(&ty, &konst)
}

fn primitive_assoc_const_parts(ty: &str, konst: &str) -> Option<PrimitiveAssocConst> {
    primitive_assoc_const_known(ty, konst).then(|| PrimitiveAssocConst {
        ty: ty.to_string(),
        konst: konst.to_string(),
    })
}

fn primitive_assoc_const_known(ty: &str, konst: &str) -> bool {
    matches!(
        (ty, konst),
        (
            "i8" | "i16"
                | "i32"
                | "i64"
                | "i128"
                | "isize"
                | "u8"
                | "u16"
                | "u32"
                | "u64"
                | "u128"
                | "usize",
            "MIN" | "MAX" | "BITS"
        ) | ("char", "MAX")
    )
}

fn primitive_assoc_const_term(expr: &Expr) -> Option<Rc<Term>> {
    let parts = primitive_assoc_const_expr(expr)?;
    primitive_assoc_const_parts_term(&parts.ty, &parts.konst)
}

fn primitive_assoc_const_parts_term(ty: &str, konst: &str) -> Option<Rc<Term>> {
    match (ty, konst) {
        ("char", "MAX") => Some(str_const(char::MAX.to_string())),
        (_, "BITS") => primitive_assoc_bits_term(ty),
        (_, "MIN" | "MAX") => primitive_assoc_int_limit_term(ty, konst),
        _ => None,
    }
}

fn primitive_assoc_bits_term(ty: &str) -> Option<Rc<Term>> {
    let source_kind = primitive_int_kind(ty)?;
    let u32_kind = primitive_int_kind("u32")?;
    typed_int_term(ExactInt::Unsigned(u128::from(source_kind.bits)), u32_kind)
}

fn primitive_assoc_int_limit_term(ty: &str, konst: &str) -> Option<Rc<Term>> {
    let kind = primitive_int_kind(ty)?;
    let value = primitive_assoc_limit_value(kind, konst)?;
    typed_int_term(value, kind)
}

fn primitive_assoc_limit_value(kind: IntKind, konst: &str) -> Option<ExactInt> {
    match (kind.signed, konst) {
        (true, "MIN") => Some(ExactInt::Signed(signed_min_for_kind(kind)?)),
        (true, "MAX") => Some(ExactInt::Signed(signed_max_for_kind(kind)?)),
        (false, "MIN") => Some(ExactInt::Unsigned(0)),
        (false, "MAX") => Some(ExactInt::Unsigned(unsigned_max_for_kind(kind)?)),
        _ => None,
    }
}

fn signed_min_for_kind(kind: IntKind) -> Option<i128> {
    if kind.bits >= 128 {
        Some(i128::MIN)
    } else {
        Some(-(1i128.checked_shl(kind.bits - 1)?))
    }
}

fn signed_max_for_kind(kind: IntKind) -> Option<i128> {
    if kind.bits >= 128 {
        Some(i128::MAX)
    } else {
        (1i128.checked_shl(kind.bits - 1)?).checked_sub(1)
    }
}

fn unsigned_max_for_kind(kind: IntKind) -> Option<u128> {
    if kind.bits >= 128 {
        Some(u128::MAX)
    } else {
        (1u128.checked_shl(kind.bits)?).checked_sub(1)
    }
}

fn primitive_type_name(ty: &Type) -> Option<String> {
    let Type::Path(path) = ty else {
        return None;
    };
    Some(path.path.segments.last()?.ident.to_string())
}

struct PrimitiveAssocConst {
    ty: String,
    konst: String,
}

pub(crate) enum ConstSugar {
    Primitive {
        path: String,
        term: Rc<Term>,
    },
    Path {
        name: String,
        body: SugarBody<TermFloor>,
    },
}

pub(crate) struct ConstCompositeSugar {
    name: String,
    body: SugarBody<CompositeFloor>,
}

impl ConstSugar {
    fn new_primitive(path: String, term: Rc<Term>) -> Box<dyn Sugar> {
        Box::new(Self::Primitive { path, term })
    }

    fn new_path(name: String, body: SugarBody<TermFloor>) -> Box<dyn Sugar> {
        Box::new(Self::Path { name, body })
    }
}

impl ConstCompositeSugar {
    fn new(name: String, body: SugarBody<CompositeFloor>) -> Box<dyn Sugar> {
        Box::new(Self { name, body })
    }
}

#[derive(Clone, Copy)]
enum ConstBodyRole {
    Term,
    Composite,
}

fn construct_const_body(
    name: &str,
    path: &syn::Path,
    fcx: &SugarBuildCtx,
    role: ConstBodyRole,
) -> Option<ConstBody> {
    let init = fcx.scope().const_expr_for_path(path)?;
    let child_fcx = fcx.with_const_path(name);
    Some(match role {
        ConstBodyRole::Term => ConstBody::Term(SugarBody::term(init.as_ref(), &child_fcx)),
        ConstBodyRole::Composite => {
            ConstBody::Composite(SugarBody::composite(init.as_ref(), &child_fcx))
        }
    })
}

enum ConstBody {
    Term(SugarBody<TermFloor>),
    Composite(SugarBody<CompositeFloor>),
}

impl Sugar for ConstSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self {
            ConstSugar::Primitive { path, term } => {
                debug!(
                    target: "sugar_lift_rust_tests::sugar::const_path",
                    path = path.as_str(),
                    term = ?term,
                    "resolved primitive associated const compiler axiom"
                );
                Outcome::Complete(Desugared::Term(Rc::clone(term)))
            }
            ConstSugar::Path { name, body } => {
                debug!(
                    target: "sugar_lift_rust_tests::sugar::const_path",
                    path = name.as_str(),
                    "reducing factory-constructed const body"
                );
                body.reduce(ctx)
            }
        }
    }
}

impl Sugar for ConstCompositeSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        debug!(
            target: "sugar_lift_rust_tests::sugar::const_path",
            path = self.name.as_str(),
            "reducing factory-constructed const composite body"
        );
        self.body.reduce(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sugar_ir_symbolic::ConstValue;

    fn assert_int_const(term: Rc<Term>, value: i128, sort_name: &str) {
        match term.as_ref() {
            Term::Const {
                value: ConstValue::Int(actual),
                sort,
            } => {
                assert_eq!(*actual, value);
                assert_eq!(sort.name, sort_name);
            }
            other => panic!("expected primitive integer const, got {other:?}"),
        }
    }

    #[test]
    fn primitive_assoc_int_limits_preserve_declared_floor_type() {
        assert_int_const(
            primitive_assoc_const_parts_term("u64", "MAX").expect("u64::MAX lowers"),
            i128::from(u64::MAX),
            "u64",
        );
        assert_int_const(
            primitive_assoc_const_parts_term("i64", "MIN").expect("i64::MIN lowers"),
            i128::from(i64::MIN),
            "i64",
        );
    }

    #[test]
    fn primitive_assoc_bits_lowers_to_rust_u32_floor() {
        assert_int_const(
            primitive_assoc_const_parts_term("u64", "BITS").expect("u64::BITS lowers"),
            i128::from(u64::BITS),
            "u32",
        );
    }
}
