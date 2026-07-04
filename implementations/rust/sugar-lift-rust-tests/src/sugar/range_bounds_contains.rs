// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `RangeBoundsContainsSugar`: a bound `RangeBounds` tuple receiver (`r.contains(&x)`,
// where `r = (Bound::Included(..), Bound::Excluded(..))`) is a trait-surface boundary.
// The receiver and needle children are still constructed as terms and reduced first;
// any child effect bubbles unchanged. If both children complete, the `RangeBounds`
// surface itself owns the named refusal instead of falling through `method` into a
// Composite factory gap for the tuple receiver.
//
// FULLY MIGRATED (Phase-3 ratchet): no as_expr(), no raw Expr::/Stmt::/Item:: access
// in the recognize body. Uses call_is_method_call(), call_target_name(), call_arg_count(),
// call_receiver(), strip_refs_groups(), path_simple_ident(), call_args(), and
// SugarBody::term_frag() exclusively. The scope/init check and is_range_bounds_tuple
// call live in is_receiver_range_bounds() which holds raw &Expr internally.

use quote::ToTokens;
use syn::{Expr, ExprPath};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{strip_refs_groups, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "range_bounds_contains",
    &["method"],
    crate::sugar::claim::SugarWitnesses::temporal_campaign(
        "family-j temporal quantifier cross-chain: RangeBounds contains facts",
    ),
    recognize,
);

// FULLY MIGRATED: no as_expr(), no raw Expr::/Stmt::/Item:: access here.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let call = frag.strip_refs_groups();
    if !call.call_is_method_call() {
        return None;
    }
    if call.call_target_name().as_deref() != Some("contains") {
        return None;
    }
    if call.call_arg_count() != 1 {
        return None;
    }
    let receiver_frag = call.call_receiver()?;
    let receiver_name = receiver_frag.strip_refs_groups().path_simple_ident()?;
    if !is_receiver_range_bounds(&receiver_name, fcx) {
        return None;
    }
    let args = call.call_args();
    Some(Box::new(RangeBoundsContainsSugar {
        receiver_name,
        receiver: SugarBody::term_frag(&receiver_frag, fcx),
        needle: SugarBody::term_frag(&args[0], fcx),
    }))
}

/// Returns `true` when `name` resolves to a `RangeBounds`-tuple init in scope.
/// Accesses raw `&Expr` internally -- intentionally kept out of the recognize body.
fn is_receiver_range_bounds(name: &str, fcx: &SugarBuildCtx) -> bool {
    let init = fcx
        .let_inits()
        .get(name)
        .copied()
        .or_else(|| fcx.scope().stable_let_binding_for_term(name));
    init.is_some_and(|expr| is_range_bounds_tuple(expr))
}

struct RangeBoundsContainsSugar {
    receiver_name: String,
    receiver: SugarBody<TermFloor>,
    needle: SugarBody<TermFloor>,
}

impl Sugar for RangeBoundsContainsSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.receiver.reduce(ctx) {
            Outcome::Complete(desugared) => {
                desugared.into_term().unwrap_or_else(|| {
                    panic!("RangeBounds receiver completed as non-term; write more Sugar")
                });
            }
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        }
        match self.needle.reduce(ctx) {
            Outcome::Complete(desugared) => {
                desugared.into_term().unwrap_or_else(|| {
                    panic!("RangeBounds contains needle completed as non-term; write more Sugar")
                });
            }
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        }
        Outcome::Incomplete(Effect::RangeBoundsRuntimeValue {
            boundary: self.receiver_name.clone(),
        })
    }
}

fn is_range_bounds_tuple(expr: &Expr) -> bool {
    let Expr::Tuple(tuple) = strip_refs_groups(expr) else {
        return false;
    };
    tuple.elems.len() == 2 && tuple.elems.iter().all(is_bound_expr)
}

fn is_bound_expr(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Call(call) => is_bound_ctor_path(&call.func),
        Expr::Path(path) => is_bound_variant_path(path, "Unbounded"),
        _ => false,
    }
}

fn is_bound_ctor_path(expr: &Expr) -> bool {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return false;
    };
    is_bound_variant_path(path, "Included") || is_bound_variant_path(path, "Excluded")
}

fn is_bound_variant_path(path: &ExprPath, variant: &str) -> bool {
    if path.qself.is_some() || path.path.segments.last().is_none_or(|s| s.ident != variant) {
        return false;
    }
    path.path
        .segments
        .iter()
        .any(|segment| segment.ident == "Bound")
        || path.path.to_token_stream().to_string() == variant
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source -> SourceFragment -> observed ->
    // call_target_name/call_arg_count/call_receiver/path_simple_ident/call_args ->
    // verify String floor. No parse_quote!, no StubTerm, no run().
    // Struct holds `receiver_name: String` + SugarBody children -- no raw syn.
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Navigate to the tail MethodCall term in a one-statement fn body.
    fn method_call_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    /// Positive: `r.contains(&x)` is a MethodCall with method "contains", 1 arg,
    /// and a single-ident receiver "r". Proves the full accessor chain the recognize
    /// body uses decodes the shape without any as_expr/raw Expr:: access, and that
    /// the derived receiver_name is a plain String (no raw syn in the struct field).
    #[test]
    fn from_src_contains_observed_method_name_arg_count_and_receiver_name() {
        let src = "fn f(r: bool, x: u32) -> bool { r.contains(&x) }";
        let file = parse_file(src);
        let frag = method_call_frag(&file, "f.rs");

        // observed: outer shape is a method call
        assert_eq!(frag.observed(), "MethodCall");

        // method name via typed accessor -- no as_expr / raw Expr::MethodCall field access
        assert_eq!(
            frag.call_target_name().as_deref(),
            Some("contains"),
            "call_target_name must return \"contains\""
        );

        // exactly 1 argument (the needle)
        assert_eq!(frag.call_arg_count(), 1);

        // receiver decodes to the simple ident "r" via strip_refs_groups + path_simple_ident
        let receiver_frag = frag.call_receiver().expect("contains has a receiver");
        let receiver_name: String = receiver_frag
            .strip_refs_groups()
            .path_simple_ident()
            .expect("receiver is a plain ident");
        assert_eq!(
            receiver_name.as_str(),
            "r",
            "struct field receiver_name is a host String derived from the fragment"
        );

        // needle arg: the single argument is present
        let args = frag.call_args();
        assert_eq!(args.len(), 1, "contains has exactly one argument");
        // The arg is &x (a reference to x); strip_refs_groups reaches the Name
        let needle_inner = args[0].strip_refs_groups();
        assert_eq!(needle_inner.observed(), "Name");
    }

    /// Discrimination: `v.len()` has method name "len", not "contains" -- the
    /// call_target_name() guard in recognize must exclude it.
    #[test]
    fn discrimination_non_contains_method_name_rejected() {
        let src = "fn f(v: &[i32]) -> usize { v.len() }";
        let file = parse_file(src);
        let frag = method_call_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert_ne!(
            frag.call_target_name().as_deref(),
            Some("contains"),
            "v.len() must not have method name \"contains\""
        );
    }

    /// Structural: `a + b` is a BinOp, not a MethodCall -- call_target_name(),
    /// call_arg_count(), and call_receiver() all report absence/zero. Proves the
    /// accessors are shape-gated and do not bleed across expression kinds.
    #[test]
    fn structural_binop_has_no_method_call_shape() {
        let src = "fn f(a: u32, b: u32) -> u32 { a + b }";
        let file = parse_file(src);
        let frag = method_call_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "BinOp");
        assert!(
            frag.call_target_name().is_none(),
            "BinOp must have no call_target_name"
        );
        assert_eq!(frag.call_arg_count(), 0, "BinOp has no call args");
        assert!(frag.call_receiver().is_none(), "BinOp has no call receiver");
    }
}
