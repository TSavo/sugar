// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Closure`: an opaque `closure:<body>` EUF symbol keyed by
// its body text + the version-aware terms of its captured free vars; an ambiguous
// capture refuses. Byte-identical to the `Expr::Closure` arm of the old fat factory.

use std::collections::BTreeSet;
use std::rc::Rc;

use sugar_ir_symbolic::{make_var, Term};

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::term_leaf::resolved_term;
use crate::{
    is_unqualified_local_name, names_referenced_in_expr, token_key, Effect, Outcome, Sugar,
    SugarCtx,
};
use syn::{Expr, Pat};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("closure_term", recognize);

struct ClosureAmbiguousCaptureSugar {
    name: String,
}

impl Sugar for ClosureAmbiguousCaptureSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::AmbiguousTemporalIdentity {
            boundary: self.name.clone(),
            reason: format!("closure captures ambiguous local `{}`; refused", self.name),
        })
    }
}

/// TERM recognizer for `Expr::Closure`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Closure(closure) = expr else {
        return None;
    };
    let scope = fcx.scope();
    let params: BTreeSet<String> = closure
        .inputs
        .iter()
        .filter_map(|p| match p {
            Pat::Ident(id) => Some(id.ident.to_string()),
            Pat::Type(t) => match &*t.pat {
                Pat::Ident(id) => Some(id.ident.to_string()),
                _ => None,
            },
            _ => None,
        })
        .collect();
    let mut args = Vec::new();
    for name in names_referenced_in_expr(&closure.body) {
        if params.contains(&name) {
            continue;
        }
        if is_unqualified_local_name(&name) && scope.plan_versioned_contains(&name) {
            if scope.ambiguous_contains(&name) {
                return Some(Box::new(ClosureAmbiguousCaptureSugar { name }));
            }
            let vname = match scope.version_of(&name) {
                Some(v) => format!("{name}@def{v}"),
                None => name.clone(),
            };
            args.push(make_var(vname));
        } else {
            args.push(make_var(name));
        }
    }
    Some(resolved_term(Rc::new(Term::Ctor {
        name: format!("closure:{}", token_key(&closure.body)),
        args,
    })))
}
