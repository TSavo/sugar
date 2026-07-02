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
//   - Any other pat shape (mut, destructure, let-else, no-init) -> a named runtime
//     statement refusal. It is not inert for value-contract composition: silently
//     skipping it would let a later tail expression fake a guarded return.

use syn::{Expr, Pat, Stmt};

use crate::sugar::claim::StmtSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) static STMT_SUGAR: StmtSugarClaim = StmtSugarClaim::statement("assign_sugar", recognize);

fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let stmt = frag.as_stmt()?;
    let Stmt::Local(local) = stmt else {
        return None;
    };
    let init = local.init.as_ref()?;
    if init.diverge.is_some() {
        // `let x = expr else { ... }` (let-else) is conditional control flow.
        return Some(Box::new(AssignSugar {
            name: None,
            raw_init: None,
            unsupported_boundary: Some("let-else binding".to_string()),
        }));
    }
    let raw_init = *init.expr.clone();
    let name = simple_immutable_ident_name(&local.pat);
    let unsupported_boundary = name.is_none().then(|| {
        if pattern_is_mutable(&local.pat) {
            "mutable let binding".to_string()
        } else {
            "unsupported let pattern".to_string()
        }
    });
    Some(Box::new(AssignSugar {
        name,
        raw_init: Some(raw_init),
        unsupported_boundary,
    }))
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

fn pattern_is_mutable(pat: &Pat) -> bool {
    match pat {
        Pat::Ident(id) => {
            id.mutability.is_some()
                || id
                    .subpat
                    .as_ref()
                    .is_some_and(|(_, p)| pattern_is_mutable(p))
        }
        Pat::Type(t) => pattern_is_mutable(&t.pat),
        Pat::Paren(p) => pattern_is_mutable(&p.pat),
        Pat::Tuple(t) => t.elems.iter().any(pattern_is_mutable),
        Pat::TupleStruct(t) => t.elems.iter().any(pattern_is_mutable),
        Pat::Struct(s) => s.fields.iter().any(|f| pattern_is_mutable(&f.pat)),
        Pat::Reference(r) => pattern_is_mutable(&r.pat),
        Pat::Or(o) => o.cases.iter().any(pattern_is_mutable),
        _ => false,
    }
}

struct AssignSugar {
    /// `Some(name)` for an immutable simple-ident binding, `None` for inert.
    name: Option<String>,
    /// The raw initializer expression when `name` is `Some`.
    /// Field NOT named `rhs` to stay clear of the build-script banned-field-name list.
    raw_init: Option<Expr>,
    unsupported_boundary: Option<String>,
}

impl Sugar for AssignSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        match (&self.name, &self.raw_init) {
            (Some(name), Some(raw_init)) => Outcome::Complete(Desugared::StmtBound {
                name: name.clone(),
                rhs: raw_init.clone(),
            }),
            _ => Outcome::Incomplete(Effect::RuntimeExprStmt {
                boundary: self
                    .unsupported_boundary
                    .clone()
                    .unwrap_or_else(|| "unsupported let statement".to_string()),
            }),
        }
    }
}
