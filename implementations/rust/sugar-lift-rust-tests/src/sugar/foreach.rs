// SPDX-License-Identifier: Apache-2.0
//
// ForEach -- `<lit>.iter().for_each(..)`, desugars via ForAllSugar.
//
// Moved verbatim from lib.rs in the file-split refactor (one file per Sugar
// class). Behaviour-preserving: the desugar logic is byte-identical to the
// monolith; only its physical location changed.

use syn::{Expr, Pat, Stmt};

use crate::*;

use crate::sugar::forall::ForAllSugar;

/// Build a `ForEachSugar` from a `<receiver>.for_each(|v| body)` adaptor: the
/// receiver (less one element-producing adaptor) must resolve to a finite-
/// construction domain, the closure must bind one plain ident. None (bail)
/// otherwise. This is the front half of `try_lift_for_each_forall`.
pub(crate) fn decompose_for_each(expr: &Expr, scope: &TemporalScope) -> Option<ForAllSugar> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "for_each" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(closure) = &call.args[0] else {
        return None;
    };
    if closure.inputs.len() != 1 {
        return None;
    }
    let var = match &closure.inputs[0] {
        Pat::Ident(p) if p.subpat.is_none() => p.ident.to_string(),
        Pat::Reference(r) => match &*r.pat {
            Pat::Ident(p) if p.subpat.is_none() && r.mutability.is_none() => p.ident.to_string(),
            _ => return None,
        },
        _ => return None,
    };
    let base = iter_adaptor_base(&call.receiver);
    let domain = bounded_domain_from_expr(base, scope)?;
    let body_stmts: Vec<Stmt> = match &*closure.body {
        Expr::Block(b) => b.block.stmts.clone(),
        other => vec![Stmt::Expr(other.clone(), None)],
    };
    Some(ForAllSugar {
        var,
        domain,
        body_stmts,
        kind: "for_each",
    })
}
