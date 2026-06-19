// SPDX-License-Identifier: Apache-2.0
//
// `ConstSugar`: a compiler-known `const` path is transparent to its initializer.
// The compiler already proved the path resolves for compiling code; the factory's
// job is to recurse into the initializer instead of freezing the path as a free var.

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::term_leaf::resolved_term;
use crate::{const_path_key, num, Outcome, Sugar, SugarCtx};
use syn::{Expr, ExprPath};
use tracing::debug;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("const", SugarRole::Term, SugarPriority::Tertiary, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let (name, path) = simple_const_path(expr)?;
    if fcx.resolving_const_path(&name) {
        return None;
    }
    if let Some(value) = primitive_assoc_const_value(path) {
        debug!(
            target: "sugar_lift_rust_tests::sugar::const_path",
            path = name.as_str(),
            value,
            "resolved primitive associated const compiler axiom"
        );
        return Some(resolved_term(num(value)));
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

fn primitive_assoc_const_value(path: &syn::Path) -> Option<i128> {
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
    match (ty.as_str(), konst.as_str()) {
        ("i8", "MIN") => Some(i128::from(i8::MIN)),
        ("i8", "MAX") => Some(i128::from(i8::MAX)),
        ("i16", "MIN") => Some(i128::from(i16::MIN)),
        ("i16", "MAX") => Some(i128::from(i16::MAX)),
        ("i32", "MIN") => Some(i128::from(i32::MIN)),
        ("i32", "MAX") => Some(i128::from(i32::MAX)),
        ("i64", "MIN") => Some(i128::from(i64::MIN)),
        ("i64", "MAX") => Some(i128::from(i64::MAX)),
        ("i128", "MIN") => Some(i128::MIN),
        ("i128", "MAX") => Some(i128::MAX),
        ("isize", "MIN") => Some(isize::MIN as i128),
        ("isize", "MAX") => Some(isize::MAX as i128),
        ("u8", "MIN") => Some(i128::from(u8::MIN)),
        ("u8", "MAX") => Some(i128::from(u8::MAX)),
        ("u16", "MIN") => Some(i128::from(u16::MIN)),
        ("u16", "MAX") => Some(i128::from(u16::MAX)),
        ("u32", "MIN") => Some(i128::from(u32::MIN)),
        ("u32", "MAX") => Some(i128::from(u32::MAX)),
        ("u64", "MIN") => Some(i128::from(u64::MIN)),
        ("u64", "MAX") => Some(i128::from(u64::MAX)),
        ("usize", "MIN") => Some(usize::MIN as i128),
        ("usize", "MAX") => Some(usize::MAX as i128),
        _ => None,
    }
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
