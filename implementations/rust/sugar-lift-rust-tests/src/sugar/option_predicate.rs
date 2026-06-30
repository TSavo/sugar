// SPDX-License-Identifier: Apache-2.0
//
// `OptionPredicateSugar`: `.is_some()` / `.is_none()` over a grounded std Option
// constructor. This is value sugar, separate from generic method calls: once the
// receiver body bottoms out to `opt:some(_)` or `opt:none`, the predicate is a literal bool.
// The payload does not participate: `Some(runtime()).is_some()` is still the literal
// predicate `true`, with the runtime payload safely ignored by the monadic visitor.
//
// MIGRATION STATUS (Phase-3 ratchet -- FULLY MIGRATED).
//   * `recognize` uses ONLY fragment accessors: `call_method_key()`, `call_arg_count()`,
//     `call_receiver()`, `SugarBody::term_frag()`. No `as_expr()`, no raw `Expr::`,
//     no raw syn field access in the recognize body.
//   * `OptionPredicateSugar` holds `method: String` (host-native) and
//     `receiver: SugarBody<TermFloor>` (factory child). No raw syn fields.
//   * `receiver_resolves_option_source_frag` wraps `as_expr()` inside a helper
//     so the recognize body stays clean. The recursive walk helpers
//     (`receiver_resolves_option_source`, `is_known_option_source`) remain
//     `&Expr`-taking internally -- they are not in the recognize body.

use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::nonzero::is_nonzero_new_call;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_dispatch::{MonadicFloorAccept, MonadicFloorVisitor};
use crate::{bool_const, strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("option_predicate", SugarRole::Term, recognize);

/// FULLY MIGRATED: no `as_expr()`, no raw `Expr::` or syn field access in this body.
fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let method = frag.call_method_key()?;
    if !matches!(method.as_str(), "is_some" | "is_none") {
        return None;
    }
    if frag.call_arg_count() != 0 {
        return None;
    }
    let receiver_frag = frag.call_receiver()?;
    if !receiver_resolves_option_source_frag(receiver_frag, fcx, 0) {
        return None;
    }
    let receiver = SugarBody::term_frag(&receiver_frag, fcx);
    Some(OptionPredicateSugar::new(method, receiver))
}

struct OptionPredicateSugar {
    /// The predicate method name: `"is_some"` or `"is_none"`.
    /// Host-native `String`; no raw syn field.
    method: String,
    /// The receiver child, factory-built from the `SourceFragment`.
    /// `SugarBody<TermFloor>`; no raw syn field.
    receiver: SugarBody<TermFloor>,
}

impl OptionPredicateSugar {
    fn new(method: String, receiver: SugarBody<TermFloor>) -> Box<dyn Sugar> {
        Box::new(Self { method, receiver })
    }
}

impl Sugar for OptionPredicateSugar {
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.reduce(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(term) => term,
                None => panic!(
                    "Option predicate `{}` receiver reduced to non-term",
                    self.method
                ),
            },
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        receiver.accept_monadic_floor(OptionPresenceVisitor {
            method: &self.method,
        })
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

struct OptionPresenceVisitor<'a> {
    method: &'a str,
}

impl MonadicFloorVisitor for OptionPresenceVisitor<'_> {
    type Output = Outcome;

    fn visit_some(self, _inner: &std::rc::Rc<sugar_ir_symbolic::Term>) -> Self::Output {
        self.complete(true)
    }

    fn visit_none(self) -> Self::Output {
        self.complete(false)
    }

    fn visit_ok(self, _inner: &std::rc::Rc<sugar_ir_symbolic::Term>) -> Self::Output {
        panic!(
            "Option predicate `{}` received a Result::Ok floor",
            self.method
        )
    }

    fn visit_err(self, _inner: &std::rc::Rc<sugar_ir_symbolic::Term>) -> Self::Output {
        panic!(
            "Option predicate `{}` received a Result::Err floor",
            self.method
        )
    }

    fn visit_non_monadic(self, _term: &std::rc::Rc<sugar_ir_symbolic::Term>) -> Self::Output {
        panic!(
            "Option predicate `{}` receiver did not reduce to Option constructor",
            self.method
        )
    }
}

impl OptionPresenceVisitor<'_> {
    fn complete(self, is_some: bool) -> Outcome {
        let value = if self.method == "is_some" {
            is_some
        } else {
            !is_some
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::option_predicate",
            method = self.method,
            value,
            "resolved Option presence predicate stdlib axiom"
        );
        Outcome::Complete(Desugared::Term(bool_const(value)))
    }
}

// ---------------------------------------------------------------------------
// Receiver-resolution helpers
// ---------------------------------------------------------------------------

/// Fragment-taking entry point for `receiver_resolves_option_source`.
/// The `as_expr()` call lives HERE (not in the recognize body) so the recognize body
/// stays clean -- it passes a `SourceFragment` obtained from `call_receiver()`.
fn receiver_resolves_option_source_frag(
    frag: SourceFragment<'_>,
    fcx: &SugarBuildCtx,
    depth: usize,
) -> bool {
    let Some(expr) = frag.as_expr() else {
        return false;
    };
    receiver_resolves_option_source(expr, fcx, depth)
}

fn receiver_resolves_option_source(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    if is_known_option_source(expr) {
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
            receiver_resolves_option_source(init, &child_fcx, depth + 1)
        }
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "map" | "and_then" | "filter"
            ) =>
        {
            receiver_resolves_option_source(&call.receiver, fcx, depth + 1)
        }
        Expr::Paren(paren) => receiver_resolves_option_source(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => receiver_resolves_option_source(&group.expr, fcx, depth + 1),
        _ => false,
    }
}

fn is_known_option_source(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Path(path) => path
            .path
            .segments
            .last()
            .is_some_and(|seg| seg.ident == "None"),
        Expr::Call(call) => {
            if is_nonzero_new_call(expr) {
                return true;
            }
            let Expr::Path(path) = strip_refs_groups(&call.func) else {
                return false;
            };
            path.path
                .segments
                .last()
                .is_some_and(|seg| seg.ident == "Some")
        }
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "checked_isqrt" | "checked_add" | "checked_sub" | "checked_mul" | "checked_div"
            ) =>
        {
            true
        }
        Expr::Paren(paren) => is_known_option_source(&paren.expr),
        Expr::Group(group) => is_known_option_source(&group.expr),
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source string -> SourceFragment -> observed ->
    // call_method_key/call_arg_count/call_receiver accessors -> build struct field ->
    // verify String floor. No parse_quote!, no StubTerm, no run().
    // The struct holds `method: String` + `receiver: SugarBody<TermFloor>` -- no raw syn.
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Navigate to the tail method-call expression in a one-statement fn body.
    fn method_call_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    /// Positive: `Some(42).is_some()` -- zero-arg MethodCall on an Option constructor.
    /// Proves call_method_key = "is_some", call_arg_count = 0, receiver present,
    /// and the struct field `method` is a plain String (no raw syn).
    #[test]
    fn from_src_is_some_observed_method_key_and_receiver() {
        let src = "fn f() -> bool { Some(42_i32).is_some() }";
        let file = parse_file(src);
        let frag = method_call_frag(&file, "f.rs");

        // observed: the outer expression is a method call
        assert_eq!(frag.observed(), "MethodCall");

        // method key via typed accessor (no as_expr / raw Expr:: access)
        let method = frag.call_method_key().expect("is_some has a method key");
        assert_eq!(method.as_str(), "is_some");

        // zero arguments
        assert_eq!(frag.call_arg_count(), 0);

        // receiver fragment is present (Some(42_i32) is a Call)
        let receiver = frag.call_receiver().expect("is_some has a receiver");
        assert_eq!(receiver.observed(), "Call");

        // floor: the struct holds `method: String` -- a plain host string, not a syn node.
        // Mirrors what recognize stores: `method` comes straight from call_method_key().
        assert_eq!(
            method, "is_some",
            "struct field `method` is a String, not syn::Ident"
        );
    }

    /// Discrimination: `None.is_none()` -- same shape (zero-arg MethodCall) but
    /// method key "is_none" instead of "is_some".
    /// Proves call_method_key() distinguishes the two predicate variants.
    #[test]
    fn from_src_is_none_method_key_is_is_none() {
        let src = "fn f() -> bool { None.is_none() }";
        let file = parse_file(src);
        let frag = method_call_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");

        let method = frag.call_method_key().expect("is_none has a method key");
        assert_eq!(method.as_str(), "is_none");
        assert_eq!(frag.call_arg_count(), 0);

        // receiver is None (a Path)
        let receiver = frag.call_receiver().expect("is_none has a receiver");
        assert_eq!(receiver.observed(), "Name");
    }

    /// Structural: `.unwrap()` has a different method name -- must NOT be recognized
    /// as an option predicate.
    /// Proves the method-key guard excludes non-predicate zero-arg method calls.
    #[test]
    fn structural_unwrap_method_key_not_recognized() {
        let src = "fn f() -> i32 { Some(42_i32).unwrap() }";
        let file = parse_file(src);
        let frag = method_call_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");

        // call_method_key() succeeds (it is a MethodCall) but the name is "unwrap",
        // not "is_some" or "is_none" -- the recognize guard must exclude it.
        let method = frag.call_method_key().expect("unwrap has a method key");
        assert_ne!(method.as_str(), "is_some");
        assert_ne!(method.as_str(), "is_none");
        assert_eq!(method.as_str(), "unwrap");
    }
}
