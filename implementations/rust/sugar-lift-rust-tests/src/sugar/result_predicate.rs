// SPDX-License-Identifier: Apache-2.0
//
// `ResultPredicateSugar`: `.is_ok()` / `.is_err()` over a grounded std `Result`
// constructor. The sibling of `option_predicate` (`is_some`/`is_none`): once the
// receiver bottoms out to `res:ok(_)` or `res:err(_)`, the predicate is a literal
// bool, replacing the opaque `method:is_ok` EUF var (no teeth).
//
// EXACT-OR-PANIC AT DESUGAR. We claim only when the receiver is known to ground
// to `res:ok`/`res:err`: integer `try_from(literal)`, Result constructors, or
// adaptors that preserve the Result floor. Runtime/effectful children propagate
// their own Effect; a constructed receiver that is not a Result floor is a factory
// construction bug and panics.
//
// TEETH. `u8::try_from(256u16).is_err()` grounds to `res:err` -> `Bool(true)`;
// `.is_ok()` -> `Bool(false)` (z3-UNSAT if asserted).

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::term_dispatch::{MonadicFloorAccept, MonadicFloorVisitor};
use crate::{
    bool_const, const_fold_int_term, const_fold_u128_term, strip_refs_groups, Desugared, Outcome,
    Sugar, SugarCtx,
};

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
        receiver: SugarBody::term(&call.receiver, fcx),
        layout: layout_from_size_align_args(&call.receiver).map(|(size, align)| LayoutArgs {
            size: SugarBody::term(size, fcx),
            align: SugarBody::term(align, fcx),
        }),
    }))
}

struct ResultPredicateSugar {
    method: String,
    receiver: SugarBody<TermFloor>,
    layout: Option<LayoutArgs>,
}

struct LayoutArgs {
    size: SugarBody<TermFloor>,
    align: SugarBody<TermFloor>,
}

impl Sugar for ResultPredicateSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(layout) = &self.layout {
            let is_ok = match layout.is_ok(ctx) {
                Ok(value) => value,
                Err(outcome) => return outcome,
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
                "resolved Layout::from_size_align Result predicate compiler axiom"
            );
            return Outcome::Complete(Desugared::Term(bool_const(value)));
        }
        let receiver = match self.receiver.reduce(ctx) {
            Outcome::Complete(d) => d.into_term().unwrap_or_else(|| {
                panic!(
                    "Result predicate `{}` receiver reduced to non-term",
                    self.method
                )
            }),
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        receiver.accept_monadic_floor(ResultPresenceVisitor {
            method: &self.method,
        })
    }
}

impl LayoutArgs {
    fn is_ok(&self, ctx: &SugarCtx) -> Result<bool, Outcome> {
        let size = term_as_u128(&reduce_term_body(&self.size, ctx)?)
            .unwrap_or_else(|| panic!("Layout::from_size_align size did not reduce to integer"));
        let align = term_as_u128(&reduce_term_body(&self.align, ctx)?)
            .unwrap_or_else(|| panic!("Layout::from_size_align align did not reduce to integer"));
        if align == 0 || !align.is_power_of_two() {
            return Ok(false);
        }
        let rem = size % align;
        let rounded = if rem == 0 {
            size
        } else {
            let padding = align
                .checked_sub(rem)
                .unwrap_or_else(|| panic!("Layout::from_size_align align remainder underflowed"));
            let Some(rounded) = size.checked_add(padding) else {
                return Ok(false);
            };
            rounded
        };
        Ok(rounded <= isize::MAX as u128)
    }
}

fn reduce_term_body(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_term()
            .unwrap_or_else(|| panic!("Layout::from_size_align argument reduced to non-term"))),
        Outcome::Incomplete(e) => Err(Outcome::Incomplete(e)),
    }
}

struct ResultPresenceVisitor<'a> {
    method: &'a str,
}

impl MonadicFloorVisitor for ResultPresenceVisitor<'_> {
    type Output = Outcome;

    fn visit_some(self, _inner: &Rc<Term>) -> Self::Output {
        panic!(
            "Result predicate `{}` received an Option::Some floor",
            self.method
        )
    }

    fn visit_none(self) -> Self::Output {
        panic!(
            "Result predicate `{}` received an Option::None floor",
            self.method
        )
    }

    fn visit_ok(self, _inner: &Rc<Term>) -> Self::Output {
        self.complete(true)
    }

    fn visit_err(self, _inner: &Rc<Term>) -> Self::Output {
        self.complete(false)
    }

    fn visit_non_monadic(self, _term: &Rc<Term>) -> Self::Output {
        panic!(
            "Result predicate `{}` receiver did not reduce to Result constructor",
            self.method
        )
    }
}

impl ResultPresenceVisitor<'_> {
    fn complete(self, is_ok: bool) -> Outcome {
        let value = if self.method == "is_ok" {
            is_ok
        } else {
            !is_ok
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::result_predicate",
            method = self.method,
            value,
            "resolved Result presence predicate stdlib axiom"
        );
        Outcome::Complete(Desugared::Term(bool_const(value)))
    }
}

/// A receiver that grounds to a `Result` ctor: an integer `try_from(literal)`,
/// a literal-payload `Ok(..)`/`Err(..)`, or a no-op `inspect`/`inspect_err` chain over
/// one of those stable sources.
///
/// EXACT-OR-NONE AT RECOGNIZE: broad or effectful `Ok(io())` and transforming adaptors
/// stay outside this predicate owner. `inspect`/`inspect_err` itself owns its method
/// shape before the generic method sugar, so non-no-op inspect callbacks become gaps
/// instead of opaque predicate terms.
fn is_known_result_source(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    receiver_resolves_result_source(strip_refs_groups(expr), fcx, 0)
}

fn receiver_resolves_result_source(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    if is_syntactic_result_ctor(expr)
        || layout_from_size_align_candidate(expr, fcx)
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
        Expr::MethodCall(call) if call.method == "ok_or" && call.args.len() == 1 => {
            crate::sugar::option_unwrap::receiver_resolves_monadic_source(
                &call.receiver,
                fcx,
                depth + 1,
            )
        }
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "map" | "and_then" | "map_err"
            ) =>
        {
            receiver_resolves_result_source(&call.receiver, fcx, depth + 1)
        }
        Expr::Paren(paren) => receiver_resolves_result_source(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => receiver_resolves_result_source(&group.expr, fcx, depth + 1),
        _ => false,
    }
}

fn layout_from_size_align_candidate(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    let Some((size, align)) = layout_from_size_align_args(expr) else {
        return false;
    };
    crate::sugar::primitive_int::integer_receiver_can_ground(size, fcx, 0)
        && crate::sugar::primitive_int::integer_receiver_can_ground(align, fcx, 0)
}

fn layout_from_size_align_args(expr: &Expr) -> Option<(&Expr, &Expr)> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.args.len() != 2 {
        return None;
    }
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    let mut segments = path.path.segments.iter().rev();
    let method = segments.next()?;
    let ty = segments.next()?;
    if method.ident != "from_size_align" || ty.ident != "Layout" {
        return None;
    }
    Some((&call.args[0], &call.args[1]))
}

fn term_as_u128(term: &Rc<Term>) -> Option<u128> {
    const_fold_u128_term(term)
        .or_else(|| const_fold_int_term(term).and_then(|value| u128::try_from(value).ok()))
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
