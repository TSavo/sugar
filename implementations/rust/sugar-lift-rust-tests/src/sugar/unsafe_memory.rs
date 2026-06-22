// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for unsafe-memory writes. `clone_to_uninit` mutates raw /
// MaybeUninit storage, so a value flowing through it is not a timeless
// construction from source literals.

use syn::{visit::Visit, Expr, Stmt};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::term_leaf::reasoned_hit;
use crate::{token_key, Effect, Sugar};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("unsafe_memory", SugarRole::Term, recognize);

pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    is_unsafe_memory_method(&call.method)
        .then(|| reasoned_hit(runtime_memory_reason(&token_key(expr))))
}

pub(crate) fn unsafe_memory_boundary_stmts(stmts: &[Stmt]) -> bool {
    let mut scan = UnsafeMemoryScan::default();
    for stmt in stmts {
        scan.visit_stmt(stmt);
    }
    scan.found
}

pub(crate) fn runtime_memory_reason(boundary: &str) -> String {
    Effect::RuntimeExprStmt {
        boundary: boundary.to_string(),
    }
    .reason()
}

fn is_unsafe_memory_method(method: &syn::Ident) -> bool {
    method == "clone_to_uninit"
}

#[derive(Default)]
struct UnsafeMemoryScan {
    found: bool,
}

impl<'ast> Visit<'ast> for UnsafeMemoryScan {
    fn visit_expr_method_call(&mut self, call: &'ast syn::ExprMethodCall) {
        if is_unsafe_memory_method(&call.method) {
            self.found = true;
            return;
        }
        syn::visit::visit_expr_method_call(self, call);
    }
}
