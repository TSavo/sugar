// SPDX-License-Identifier: Apache-2.0
//
// Raw-pointer arithmetic (`ptr.wrapping_add(n)`, `wrapping_byte_add`, and their
// subtraction siblings) is address / provenance work, not primitive-integer
// wrapping math. Recognize it before `primitive_int` so literal integer wrapping
// stays on the numeric floor while pointer arithmetic stops at its real runtime
// operand boundary.

use syn::{Expr, Type};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    canonical_term_sig, simple_path_name, strip_refs_groups, Effect, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("raw_pointer_arithmetic", &["primitive_int"], recognize);

// FULLY MIGRATED (Phase-3 ratchet): no as_expr(), no raw Expr:: / MethodCall field
// access in the recognize body. Uses strip_refs_groups() + call_is_method_call() +
// call_target_name() + call_arg_count() + call_receiver() + call_args() +
// is_raw_pointer_value_in_scope() + SugarBody::term_frag() exclusively.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let stripped = frag.strip_refs_groups();
    if !stripped.call_is_method_call() {
        return None;
    }
    let method = stripped.call_target_name()?;
    if !matches!(
        method.as_str(),
        "wrapping_add" | "wrapping_sub" | "wrapping_byte_add" | "wrapping_byte_sub"
    ) {
        return None;
    }
    if stripped.call_arg_count() != 1 {
        return None;
    }
    let receiver_frag = stripped.call_receiver()?;
    if !receiver_frag.is_raw_pointer_value_in_scope(fcx, 0) {
        return None;
    }
    let args = stripped.call_args();
    Some(Box::new(RawPointerArithmeticSugar {
        receiver: SugarBody::term_frag(&receiver_frag, fcx),
        rhs: SugarBody::term_frag(&args[0], fcx),
        method,
    }))
}

struct RawPointerArithmeticSugar {
    receiver: SugarBody<TermFloor>,
    rhs: SugarBody<TermFloor>,
    method: String,
}

impl Sugar for RawPointerArithmeticSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_term()
                .unwrap_or_else(|| panic!("raw pointer arithmetic receiver completed as non-term")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        match self.rhs.reduce(ctx) {
            Outcome::Complete(d) => {
                d.into_term()
                    .unwrap_or_else(|| panic!("raw pointer arithmetic rhs completed as non-term"));
            }
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        }
        Outcome::Incomplete(Effect::RuntimeNumericOperand {
            boundary: canonical_term_sig(&receiver),
            operation: self.method.clone(),
            kind: "raw pointer".to_string(),
        })
    }
}

/// Returns `true` if `expr` is a raw-pointer value in scope: a cast to
/// `*const T`/`*mut T`, a path whose let-binding is typed or initialised as a
/// raw pointer, or a `Paren`/`Group` wrapping thereof. Depth is capped at 8.
/// Called by `SourceFragment::is_raw_pointer_value_in_scope` (the accessor that
/// hides all raw syn from recognize bodies).
pub(crate) fn raw_pointer_value_in_scope(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Cast(cast) if matches!(cast.ty.as_ref(), Type::Ptr(_)) => true,
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = simple_path_name(expr) else {
                return false;
            };
            if fcx
                .scope()
                .let_binding_expected_type(&name)
                .is_some_and(raw_pointer_type_key)
            {
                return true;
            }
            fcx.scope()
                .stable_let_binding_for_term(&name)
                .is_some_and(|init| raw_pointer_value_in_scope(init, fcx, depth + 1))
        }
        Expr::Paren(paren) => raw_pointer_value_in_scope(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => raw_pointer_value_in_scope(&group.expr, fcx, depth + 1),
        _ => false,
    }
}

fn raw_pointer_type_key(key: &str) -> bool {
    key.trim_start().starts_with('*')
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source -> SourceFragment -> observed -> typed-accessor
    // asserts. No parse_quote!, no StubTerm, no run().
    // Proves: recognize body has zero as_expr/raw-syn; struct holds only
    // SugarBody<TermFloor> x2 + String -- no raw syn fields.
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Navigate to the tail expression in the first function's body.
    fn tail_expr<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        stmts[0].terms()[0]
    }

    /// Positive: `(p as *mut u8).wrapping_add(n)` -- a MethodCall with a
    /// raw-pointer Cast receiver and exactly one argument.
    /// Proves: observed is "MethodCall", call_target_name is "wrapping_add",
    /// call_arg_count is 1, and the receiver after strip_refs_groups() is a
    /// raw-ptr Cast. The source wraps the cast in parens (required for method
    /// call syntax), so the raw receiver fragment is "Paren"; strip_refs_groups()
    /// peels it to reveal the "Cast" underneath.
    #[test]
    fn from_src_wrapping_add_on_ptr_cast_shape() {
        let src = "fn f(p: usize, n: usize) -> *mut u8 { (p as *mut u8).wrapping_add(n) }";
        let file = parse_file(src);
        let frag = tail_expr(&file, "t.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert!(frag.call_is_method_call());
        assert_eq!(frag.call_target_name().as_deref(), Some("wrapping_add"));
        assert_eq!(frag.call_arg_count(), 1);

        let receiver = frag.call_receiver().expect("receiver present");
        // `(p as *mut u8)` is wrapped in parens for method-call syntax.
        assert_eq!(receiver.observed(), "Paren");
        // After stripping parens the inner Cast is exposed.
        let inner = receiver.strip_refs_groups();
        assert_eq!(inner.observed(), "Cast");
        assert!(
            inner.cast_is_raw_ptr(),
            "inner cast target must be a raw pointer (*mut u8)"
        );
    }

    /// Discrimination: `n.wrapping_add(1)` on an integer -- method name matches
    /// the recognizer's list but the receiver is a plain Name (not a ptr cast).
    /// Proves: call_target_name is "wrapping_add" and call_arg_count is 1, but
    /// receiver.cast_is_raw_ptr() is false -- so raw_pointer_value_in_scope would
    /// return false for this call's receiver.
    #[test]
    fn from_src_wrapping_add_on_integer_receiver_not_ptr() {
        let src = "fn f(n: usize) -> usize { n.wrapping_add(1) }";
        let file = parse_file(src);
        let frag = tail_expr(&file, "t.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert_eq!(frag.call_target_name().as_deref(), Some("wrapping_add"));
        assert_eq!(frag.call_arg_count(), 1);

        let receiver = frag.call_receiver().expect("receiver present");
        // `n` is a Name/Path, not a Cast -- must not be a raw pointer
        assert_eq!(receiver.observed(), "Name");
        assert!(
            !receiver.cast_is_raw_ptr(),
            "plain integer name is not a raw-pointer cast"
        );
    }

    /// Structural: `(p as *mut u8).offset(1)` -- the receiver IS a raw-pointer
    /// cast, but the method name "offset" is not in the recognizer's allowed list.
    /// Proves the method-name guard rejects non-wrapping pointer methods.
    #[test]
    fn from_src_offset_method_not_in_recognized_list() {
        let src = "fn f(p: usize) -> *mut u8 { (p as *mut u8).offset(1) }";
        let file = parse_file(src);
        let frag = tail_expr(&file, "t.rs");

        assert_eq!(frag.observed(), "MethodCall");
        let method = frag.call_target_name().expect("method name present");
        assert!(
            !matches!(
                method.as_str(),
                "wrapping_add" | "wrapping_sub" | "wrapping_byte_add" | "wrapping_byte_sub"
            ),
            "\"offset\" must not match the recognized method list"
        );
        // The receiver IS a raw-pointer cast (inside parens) -- rejection is from method name.
        let receiver = frag.call_receiver().expect("receiver present");
        assert_eq!(receiver.observed(), "Paren");
        assert!(
            receiver.strip_refs_groups().cast_is_raw_ptr(),
            "inner cast is still a raw-ptr cast"
        );
    }
}
