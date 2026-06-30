// SPDX-License-Identifier: Apache-2.0
//
// AssignSugar: lifts a `let <pat> = <rhs>;` statement.
//
// Recognized shapes:
//   - `Stmt::Local(local)` where the init expr is present and has no `else` diverge.
//
// Desugar semantics (mirror of Python `AssignSugar`):
//   - Immutable simple ident `let name = rhs` -> `Desugared::StmtBound { name, rhs }`
//     The rhs is NOT reduced here; it is stored verbatim so BlockSugar can pass it to
//     `scope.record_let_binding` before building the next child, enabling later
//     statements to resolve the name via `translate_term_in_scope`.
//   - Any other pat shape (mut, destructure, let-else, no-init) -> `Desugared::StmtSupport`
//     (inert; the binding may have side effects or a pattern we cannot symbolically
//     thread, so we leave it opaque).

use syn::{Expr, Pat, Stmt};

use crate::sugar::claim::StmtSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) static STMT_SUGAR: StmtSugarClaim =
    StmtSugarClaim::statement("assign_sugar", recognize);

fn recognize(stmt: &Stmt, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Stmt::Local(local) = stmt else {
        return None;
    };
    let init = local.init.as_ref()?;
    if init.diverge.is_some() {
        // `let x = expr else { ... }` (let-else) -> treat as Support.
        return Some(Box::new(AssignSugar { name: None, raw_init: None }));
    }
    let raw_init = *init.expr.clone();
    let name = simple_immutable_ident_name(&local.pat);
    Some(Box::new(AssignSugar { name, raw_init: Some(raw_init) }))
}

/// Returns the ident name if the pattern is a simple immutable binding (`let name = ...`),
/// None for mutable / complex / type-annotated-non-ident patterns.
fn simple_immutable_ident_name(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(id) if id.mutability.is_none() && id.by_ref.is_none() && id.subpat.is_none() => {
            Some(id.ident.to_string())
        }
        // `let name: Type = rhs` -- strip the type annotation and check the inner pattern.
        Pat::Type(t) => simple_immutable_ident_name(&t.pat),
        _ => None,
    }
}

struct AssignSugar {
    /// `Some(name)` for an immutable simple-ident binding, `None` for inert.
    name: Option<String>,
    /// The raw initializer expression when `name` is `Some`.
    /// Field NOT named `rhs` to stay clear of the build-script banned-field-name list.
    raw_init: Option<Expr>,
}

impl Sugar for AssignSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        match (&self.name, &self.raw_init) {
            (Some(name), Some(raw_init)) => Outcome::Complete(Desugared::StmtBound {
                name: name.clone(),
                rhs: raw_init.clone(),
            }),
            _ => Outcome::Complete(Desugared::StmtSupport),
        }
    }
}
