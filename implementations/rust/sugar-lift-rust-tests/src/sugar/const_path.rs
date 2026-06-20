// SPDX-License-Identifier: Apache-2.0
//
// `ConstSugar`: a compiler-known `const` path is transparent to its initializer.
// The compiler already proved the path resolves for compiling code; the factory's
// job is to recurse into the initializer instead of freezing the path as a free var.

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::term_leaf::resolved_term;
use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::{const_path_key, num, str_const, u128_term, Outcome, Sugar, SugarCtx};
use syn::{Expr, ExprPath, Type};
use tracing::debug;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("const", SugarRole::Term, SugarPriority::Tertiary, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if let Some(value) = primitive_assoc_const_expr(expr) {
        debug!(
            target: "sugar_lift_rust_tests::sugar::const_path",
            path = %crate::token_key(expr),
            term = ?value,
            "resolved primitive associated const compiler axiom"
        );
        return Some(resolved_term(value));
    }
    let (name, path) = simple_const_path(expr)?;
    if fcx.resolving_const_path(&name) {
        return None;
    }
    let init = fcx.scope().const_expr_for_path(path)?;
    let child_fcx = fcx.with_const_path(&name);
    Some(Box::new(ConstSugar {
        name,
        inner: build_term(&init, &child_fcx),
    }))
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

fn primitive_assoc_const_expr(expr: &Expr) -> Option<Rc<Term>> {
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

fn primitive_assoc_const_value(path: &syn::Path) -> Option<Rc<Term>> {
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

fn primitive_assoc_const_parts(ty: &str, konst: &str) -> Option<Rc<Term>> {
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

pub(crate) struct ConstSugar {
    #[allow(dead_code)]
    name: String,
    inner: Box<dyn Sugar>,
}

impl Sugar for ConstSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.inner.desugar(ctx)
    }
}
