// SPDX-License-Identifier: Apache-2.0
//
// `ResultPredicateSugar`: `.is_ok()` / `.is_err()` over a grounded std `Result`
// constructor. The sibling of `option_predicate` (`is_some`/`is_none`): once the
// receiver bottoms out to `res:ok(_)` or `res:err(_)`, the predicate is a literal
// bool, replacing the opaque `method:is_ok` EUF var (no teeth).
//
// EXACT-OR-NONE AT RECOGNIZE. We claim only when the receiver is known to ground
// to `res:ok`/`res:err`: integer `try_from(literal)`, literal-payload `Ok(..)`/
// `Err(..)`, or a no-op `inspect`/`inspect_err` chain over one of those stable
// sources. Runtime/effectful payloads, transforming adaptors, and non-no-op
// callbacks decline so existing opaque-EUF handling stands.
//
// TEETH. `u8::try_from(256u16).is_err()` grounds to `res:err` -> `Bool(true)`;
// `.is_ok()` -> `Bool(false)` (z3-UNSAT if asserted).

use std::collections::BTreeMap;

use sugar_ir_symbolic::Term;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
use crate::sugar::monadic::{is_grounded_literal_term, RES_ERR, RES_OK};
use crate::{bool_const, strip_refs_groups, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("result_predicate", SugarRole::Term, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let method = call.method.to_string();
    if !matches!(method.as_str(), "is_ok" | "is_err") || !call.args.is_empty() {
        return None;
    }
    if !is_known_result_source(&call.receiver, fcx) {
        return None;
    }
    Some(Box::new(ResultPredicateSugar {
        method,
        receiver: (*call.receiver).clone(),
        let_inits: capture_let_inits(fcx),
    }))
}

struct ResultPredicateSugar {
    method: String,
    receiver: Expr,
    let_inits: BTreeMap<String, Expr>,
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

impl Sugar for ResultPredicateSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let stable = stable_let_bindings(ctx.scope);
        let let_inits: BTreeMap<String, &Expr> = stable
            .iter()
            .map(|(name, init)| (name.clone(), init))
            .chain(
                self.let_inits
                    .iter()
                    .map(|(name, init)| (name.clone(), init)),
            )
            .collect();
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let receiver = match build_term(&self.receiver, &fcx).desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        let Some(presence) = result_presence(&receiver) else {
            return Outcome::from_opt(None);
        };
        let is_ok = match presence {
            Ok(is_ok) => is_ok,
            Err(kind) => {
                return Outcome::Hit(Effect::Unsupported {
                    reason: format!(
                        "Result `{}` over non-literal `{kind}` payload; refused",
                        self.method
                    ),
                })
            }
        };
        let value = if self.method == "is_ok" {
            is_ok
        } else {
            !is_ok
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::result_predicate",
            method = self.method.as_str(),
            value,
            "resolved Result presence predicate stdlib axiom"
        );
        Outcome::Dug(Desugared::Term(bool_const(value)))
    }
}

/// `Some(true)` for `res:ok`, `Some(false)` for `res:err`, `None` otherwise.
fn result_presence(term: &Term) -> Option<Result<bool, &'static str>> {
    match term {
        Term::Ctor { name, args } if name == RES_OK && args.len() == 1 => {
            if is_grounded_literal_term(args[0].as_ref()) {
                Some(Ok(true))
            } else {
                Some(Err(RES_OK))
            }
        }
        Term::Ctor { name, args } if name == RES_ERR && args.len() == 1 => {
            if is_grounded_literal_term(args[0].as_ref()) {
                Some(Ok(false))
            } else {
                Some(Err(RES_ERR))
            }
        }
        _ => None,
    }
}

/// A receiver that grounds to a `Result` ctor: an integer `try_from(literal)`,
/// a literal-payload `Ok(..)`/`Err(..)`, or a no-op `inspect`/`inspect_err` chain over
/// one of those stable sources.
///
/// EXACT-OR-NONE AT RECOGNIZE: broad or effectful `Ok(io())`, transforming adaptors,
/// and non-no-op inspect callbacks still decline to the opaque method path.
fn is_known_result_source(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    receiver_resolves_result_source(strip_refs_groups(expr), fcx, 0)
}

fn receiver_resolves_result_source(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    if is_syntactic_result_ctor(expr)
        || crate::sugar::inspect::is_stable_result_source(strip_refs_groups(expr), fcx)
    {
        return true;
    }
    match strip_refs_groups(expr) {
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(|ident| ident.to_string()) else {
                return false;
            };
            if fcx.resolving_bound_path(&name) {
                return false;
            }
            let Some(init) = fcx.scope().stable_let_binding_for_term(&name) else {
                return false;
            };
            let child_fcx = fcx.with_bound_path(&name);
            receiver_resolves_result_source(init, &child_fcx, depth + 1)
        }
        Expr::MethodCall(call) if call.method == "map" && call.args.len() == 1 => {
            receiver_resolves_result_source(&call.receiver, fcx, depth + 1)
        }
        Expr::Paren(paren) => receiver_resolves_result_source(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => receiver_resolves_result_source(&group.expr, fcx, depth + 1),
        _ => false,
    }
}

fn is_syntactic_result_ctor(expr: &Expr) -> bool {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return false;
    };
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return false;
    };
    call.args.len() == 1
        && path
            .path
            .segments
            .last()
            .is_some_and(|seg| matches!(seg.ident.to_string().as_str(), "Ok" | "Err"))
}
