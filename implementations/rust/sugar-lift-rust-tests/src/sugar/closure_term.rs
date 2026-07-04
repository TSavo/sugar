// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Closure`: an opaque `closure:<body>` EUF symbol keyed by
// its body text + the version-aware terms of its captured free vars; an ambiguous
// capture refuses. Byte-identical to the `Expr::Closure` arm of the old fat factory.

use std::rc::Rc;

use sugar_ir_symbolic::{make_var, Term};

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_leaf::resolved_term;
use crate::{is_unqualified_local_name, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "closure_term",
        crate::sugar::claim::SugarWitnesses::reasoned_bucket(
            "closure term identity needs callable/closure witness machinery",
        ),
        recognize,
    );

struct ClosureAmbiguousCaptureSugar {
    name: String,
}

impl Sugar for ClosureAmbiguousCaptureSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::AmbiguousTemporalIdentity {
            reason: format!("closure captures ambiguous local `{}`; refused", self.name),
        })
    }
}

/// TERM recognizer for `Expr::Closure`. All raw syn access lives in the typed
/// accessors (`closure_body_frag`, `closure_param_names`, `closure_referenced_names`)
/// on `SourceFragment`; the recognize body itself holds no raw syn.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Gates on Expr::Closure; returns None for any other fragment kind.
    let body_key = frag.closure_body_frag()?.token_str();
    let scope = fcx.scope();
    let params = frag.closure_param_names();
    let mut args = Vec::new();
    for name in frag.closure_referenced_names() {
        if params.contains(&name) {
            continue;
        }
        if is_unqualified_local_name(&name) && scope.plan_versioned_contains(&name) {
            if scope.ambiguous_contains(&name) {
                return Some(Box::new(ClosureAmbiguousCaptureSugar { name }));
            }
            let vname = match scope.version_of(&name) {
                Some(v) => scope.temporal_rewrite_alias(&name, v),
                None => name.clone(),
            };
            args.push(make_var(vname));
        } else {
            args.push(make_var(name));
        }
    }
    Some(resolved_term(Rc::new(Term::Ctor {
        name: format!("closure:{body_key}"),
        args,
    })))
}
