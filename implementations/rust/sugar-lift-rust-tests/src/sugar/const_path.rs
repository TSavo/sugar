// SPDX-License-Identifier: Apache-2.0
//
// `ConstSugar`: a compiler-known `const` path is transparent to its initializer.
// The compiler already proved the path resolves for compiling code; recognition
// constructs the initializer body up front instead of freezing the path as a free var.

use std::rc::Rc;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{
    compat_reduction, FactoryGap, FactoryReduction, SugarBody, SugarBuildCtx,
};

use sugar_ir_symbolic::Term;

use crate::{const_path_key, num, str_const, u128_term, Desugared, Outcome, Sugar, SugarCtx};
use syn::{Expr, ExprPath, Type};
use tracing::debug;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("const", &["path"], recognize);

pub(crate) const COMPOSITE_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::composite("const_composite", recognize_composite);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if primitive_assoc_const_expr(expr).is_some() {
        return Some(ConstSugar::new_primitive(expr.clone()));
    }
    let (name, path) = simple_const_path(expr)?;
    if fcx.resolving_const_path(&name) {
        return None;
    }
    let body = construct_const_body(&name, path, fcx, ConstBodyRole::Term)?;
    Some(ConstSugar::new_path(name, body))
}

fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let (name, path) = simple_const_path(expr)?;
    if fcx.resolving_const_path(&name) {
        return None;
    }
    let body = construct_const_body(&name, path, fcx, ConstBodyRole::Composite)?;
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
    let value = match (ty, konst) {
        ("i8", "MIN") => num(i128::from(i8::MIN)),
        ("i8", "MAX") => num(i128::from(i8::MAX)),
        ("i8", "BITS") => num(i128::from(i8::BITS)),
        ("i16", "MIN") => num(i128::from(i16::MIN)),
        ("i16", "MAX") => num(i128::from(i16::MAX)),
        ("i16", "BITS") => num(i128::from(i16::BITS)),
        ("i32", "MIN") => num(i128::from(i32::MIN)),
        ("i32", "MAX") => num(i128::from(i32::MAX)),
        ("i32", "BITS") => num(i128::from(i32::BITS)),
        ("i64", "MIN") => num(i128::from(i64::MIN)),
        ("i64", "MAX") => num(i128::from(i64::MAX)),
        ("i64", "BITS") => num(i128::from(i64::BITS)),
        ("i128", "MIN") => num(i128::MIN),
        ("i128", "MAX") => num(i128::MAX),
        ("i128", "BITS") => num(i128::from(i128::BITS)),
        ("isize", "MIN") => num(isize::MIN as i128),
        ("isize", "MAX") => num(isize::MAX as i128),
        ("isize", "BITS") => num(i128::from(isize::BITS)),
        ("u8", "MIN") => num(i128::from(u8::MIN)),
        ("u8", "MAX") => num(i128::from(u8::MAX)),
        ("u8", "BITS") => num(i128::from(u8::BITS)),
        ("u16", "MIN") => num(i128::from(u16::MIN)),
        ("u16", "MAX") => num(i128::from(u16::MAX)),
        ("u16", "BITS") => num(i128::from(u16::BITS)),
        ("u32", "MIN") => num(i128::from(u32::MIN)),
        ("u32", "MAX") => num(i128::from(u32::MAX)),
        ("u32", "BITS") => num(i128::from(u32::BITS)),
        ("u64", "MIN") => num(i128::from(u64::MIN)),
        ("u64", "MAX") => num(i128::from(u64::MAX)),
        ("u64", "BITS") => num(i128::from(u64::BITS)),
        ("u128", "MIN") => u128_term(u128::MIN),
        ("u128", "MAX") => u128_term(u128::MAX),
        ("u128", "BITS") => num(i128::from(u128::BITS)),
        ("usize", "MIN") => num(usize::MIN as i128),
        ("usize", "MAX") => num(usize::MAX as i128),
        ("usize", "BITS") => num(i128::from(usize::BITS)),
        ("char", "MAX") => str_const(char::MAX.to_string()),
        _ => return None,
    };
    Some(value)
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
    Primitive { expr: Expr },
    Path { name: String, body: SugarBody },
}

pub(crate) struct ConstCompositeSugar {
    name: String,
    body: SugarBody,
}

impl ConstSugar {
    fn new_primitive(expr: Expr) -> Box<dyn Sugar> {
        Box::new(Self::Primitive { expr })
    }

    fn new_path(name: String, body: SugarBody) -> Box<dyn Sugar> {
        Box::new(Self::Path { name, body })
    }
}

impl ConstCompositeSugar {
    fn new(name: String, body: SugarBody) -> Box<dyn Sugar> {
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
) -> Option<SugarBody> {
    let init = fcx.scope().const_expr_for_path(path)?;
    let child_fcx = fcx.with_const_path(name);
    Some(match role {
        ConstBodyRole::Term => SugarBody::term(init.as_ref(), &child_fcx),
        ConstBodyRole::Composite => SugarBody::composite(init.as_ref(), &child_fcx),
    })
}

impl Sugar for ConstSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        match self {
            ConstSugar::Primitive { expr } => {
                let Some(value) = primitive_assoc_const_term(expr) else {
                    return Err(FactoryGap::new(format!(
                        "primitive associated const `{}` recognized but did not reduce",
                        crate::token_key(expr)
                    )));
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::const_path",
                    path = %crate::token_key(expr),
                    term = ?value,
                    "resolved primitive associated const compiler axiom"
                );
                Ok(Outcome::Complete(Desugared::Term(value)))
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

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

impl Sugar for ConstCompositeSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        debug!(
            target: "sugar_lift_rust_tests::sugar::const_path",
            path = self.name.as_str(),
            "reducing factory-constructed const composite body"
        );
        self.body.reduce(ctx)
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}
