// SPDX-License-Identifier: Apache-2.0
//
// `ConstSugar`: a compiler-known `const` path is transparent to its initializer.
// The compiler already proved the path resolves for compiling code; the factory's
// job is to recurse into the initializer instead of freezing the path as a free var.

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::{const_path_key, Outcome, Sugar, SugarCtx};
use syn::{Expr, ExprPath};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("const", SugarRole::Term, SugarPriority::Tertiary, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
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
