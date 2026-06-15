// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Closure`: an opaque `closure:<body>` EUF symbol keyed by
// its body text + the version-aware terms of its captured free vars; an ambiguous
// capture refuses. Byte-identical to the `Expr::Closure` arm of the old fat factory.

use std::collections::BTreeSet;
use std::rc::Rc;

use sugar_ir_symbolic::{make_var, Term};

use crate::sugar::factory::FactoryCtx;
use crate::sugar::term_leaf::{reasoned_hit, resolved_term};
use crate::{is_unqualified_local_name, names_referenced_in_expr, token_key, Sugar};
use syn::{Expr, Pat};

/// TERM recognizer for `Expr::Closure`.
pub(crate) fn recognize(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Closure(closure) = expr else {
        return None;
    };
    let scope = fcx.scope;
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
                return Some(reasoned_hit(format!(
                    "closure captures ambiguous local `{name}`; refused"
                )));
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
