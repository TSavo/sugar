// SPDX-License-Identifier: Apache-2.0
//
// `IntMidpointSugar`: primitive integer `T::midpoint(a, b)` over text-determined
// operands is a stdlib/compiler axiom. The associated type supplies the width and
// signedness; desugar composes typed operand floors and emits the exact literal
// result when both operands bottom out.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use tracing::debug;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{
    numeric_floor_from_term, primitive_int_kind, IntKind, MidpointVisitor,
};
use crate::sugar::source_fragment::SourceFragment;
use crate::{canonical_term_sig, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("int_midpoint", &["call"], recognize);

// FULLY MIGRATED (Phase-3 ratchet): no as_expr(), no raw Expr:: / Call field
// access. Uses call_func(), call_arg_count(), call_args(), SugarBody::term_frag(),
// and SourceFragment path accessors exclusively.
fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let func_frag = frag.call_func()?; // ensures this is an Expr::Call
    if frag.call_arg_count() != 2 {
        return None;
    }
    let kind = midpoint_kind_frag(&func_frag)?;
    let args = frag.call_args();
    Some(Box::new(IntMidpointSugar {
        lhs: SugarBody::term_frag(&args[0], fcx),
        rhs: SugarBody::term_frag(&args[1], fcx),
        kind,
    }))
}

/// Determine the `IntKind` for a `T::midpoint` or `<T>::midpoint` func fragment.
/// Strips refs/groups, requires last path segment == "midpoint", then resolves
/// the type name from qself (`<u32>::midpoint`) or the penultimate segment
/// (`u32::midpoint`). All raw syn access lives in the SourceFragment accessors.
fn midpoint_kind_frag(func: &SourceFragment) -> Option<IntKind> {
    let stripped = func.strip_refs_groups();
    if stripped.path_last_segment_ident()?.as_str() != "midpoint" {
        return None;
    }
    // <T>::midpoint form: qself carries the type
    if let Some(ty_name) = stripped.path_qself_simple_type_name() {
        return primitive_int_kind(&ty_name);
    }
    // T::midpoint form: penultimate segment is the type
    let ty = stripped.path_penultimate_ident()?;
    primitive_int_kind(&ty)
}

struct IntMidpointSugar {
    lhs: SugarBody<TermFloor>,
    rhs: SugarBody<TermFloor>,
    kind: IntKind,
}

impl Sugar for IntMidpointSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let lhs = match term_body(&self.lhs, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let rhs = match term_body(&self.rhs, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let lhs_floor = match numeric_floor_from_term(&lhs) {
            Some(floor) => floor,
            None => return runtime_midpoint_operand(&lhs, self.kind),
        };
        let rhs_floor = match numeric_floor_from_term(&rhs) {
            Some(floor) => floor,
            None => return runtime_midpoint_operand(&rhs, self.kind),
        };
        let Some(result) = lhs_floor.accept(MidpointVisitor {
            rhs: rhs_floor,
            kind: self.kind,
        }) else {
            panic!(
                "int midpoint numeric floors could not compute a result; write the owning typed floor before Outcome"
            );
        };
        let Some(term) = result.term() else {
            panic!("int midpoint numeric floor could not reify its result term");
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::int_midpoint",
            kind = self.kind.name,
            ?lhs_floor,
            ?rhs_floor,
            ?result,
            "resolved primitive integer midpoint stdlib axiom"
        );
        Outcome::Complete(Desugared::Term(term))
    }
}

fn runtime_midpoint_operand(term: &Rc<Term>, kind: IntKind) -> Outcome {
    Outcome::Incomplete(Effect::RuntimeNumericOperand {
        boundary: canonical_term_sig(term),
        operation: "midpoint".to_string(),
        kind: kind.name.to_string(),
    })
}

fn term_body(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_term()
            .unwrap_or_else(|| panic!("term body completed as non-term before int midpoint"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

// ---------------------------------------------------------------------------
// Tests -- from_src harness: source -> SourceFragment -> accessor asserts.
// No parse_quote!, no StubTerm, no run().
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::source_fragment::{parse_file, SourceFragment};

    /// Navigate to the tail expression of the first fn in a source snippet.
    fn tail_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let syn::Item::Fn(f) = &file.items[0] else {
            panic!("expected fn item");
        };
        let tail = f.block.stmts.last().expect("fn has stmts");
        let syn::Stmt::Expr(e, _) = tail else {
            panic!("expected expr tail stmt");
        };
        SourceFragment::expr(e, file_str)
    }

    #[test]
    fn path_penultimate_and_last_segment_for_plain_path() {
        let src = "fn f() -> u32 { u32::midpoint(1u32, 3u32) }";
        let file = parse_file(src);
        let call = tail_expr_frag(&file, "f.rs");

        assert_eq!(call.observed(), "Call");
        assert_eq!(call.call_arg_count(), 2);

        let func_frag = call.call_func().expect("call has func");
        assert_eq!(func_frag.path_last_segment_ident().as_deref(), Some("midpoint"));
        assert_eq!(func_frag.path_penultimate_ident().as_deref(), Some("u32"));
        assert!(func_frag.path_qself_simple_type_name().is_none());
    }

    #[test]
    fn path_qself_type_name_for_angle_bracket_form() {
        let src = "fn f() -> i32 { <i32>::midpoint(1i32, 3i32) }";
        let file = parse_file(src);
        let call = tail_expr_frag(&file, "f.rs");

        let func_frag = call.call_func().expect("call has func");
        assert_eq!(func_frag.path_last_segment_ident().as_deref(), Some("midpoint"));
        assert_eq!(func_frag.path_qself_simple_type_name().as_deref(), Some("i32"));
        // qself path has no penultimate because the path only has "midpoint"
        assert!(func_frag.path_penultimate_ident().is_none());
    }

    #[test]
    fn midpoint_kind_frag_u32_plain_path() {
        let src = "fn f() -> u32 { u32::midpoint(1u32, 3u32) }";
        let file = parse_file(src);
        let call = tail_expr_frag(&file, "f.rs");
        let func = call.call_func().unwrap();
        let kind = midpoint_kind_frag(&func).expect("u32::midpoint -> IntKind");
        assert_eq!(kind.name, "u32");
        assert!(!kind.signed);
        assert_eq!(kind.bits, 32);
    }

    #[test]
    fn midpoint_kind_frag_i64_qself() {
        let src = "fn f() -> i64 { <i64>::midpoint(1i64, 3i64) }";
        let file = parse_file(src);
        let call = tail_expr_frag(&file, "f.rs");
        let func = call.call_func().unwrap();
        let kind = midpoint_kind_frag(&func).expect("<i64>::midpoint -> IntKind");
        assert_eq!(kind.name, "i64");
        assert!(kind.signed);
        assert_eq!(kind.bits, 64);
    }

    #[test]
    fn midpoint_kind_frag_wrong_method_returns_none() {
        // "from" is not "midpoint" -- should be rejected
        let src = "fn f() -> u32 { u32::from(1u8) }";
        let file = parse_file(src);
        let call = tail_expr_frag(&file, "f.rs");
        let func = call.call_func().unwrap();
        assert!(midpoint_kind_frag(&func).is_none(), "u32::from must not match midpoint");
    }

    #[test]
    fn midpoint_kind_frag_unknown_type_returns_none() {
        // "MyType::midpoint" -- not a primitive int type
        let src = "fn f() { MyType::midpoint(a, b) }";
        let file = parse_file(src);
        let call = tail_expr_frag(&file, "f.rs");
        let func = call.call_func().unwrap();
        assert!(midpoint_kind_frag(&func).is_none(), "unknown type must not match");
    }

    #[test]
    fn call_args_are_accessible_as_fragments() {
        let src = "fn f() -> u32 { u32::midpoint(2u32, 8u32) }";
        let file = parse_file(src);
        let call = tail_expr_frag(&file, "f.rs");

        assert_eq!(call.call_arg_count(), 2);
        let args = call.call_args();
        assert_eq!(args[0].observed(), "PrimitiveLiteral");
        assert_eq!(args[1].observed(), "PrimitiveLiteral");
        // Confirm the full pipeline: kind is resolved, args are fragments
        let func = call.call_func().unwrap();
        let kind = midpoint_kind_frag(&func).unwrap();
        assert_eq!(kind.name, "u32");
    }
}
