// SPDX-License-Identifier: Apache-2.0
//
// `IntPowSugar`: primitive integer `.pow(<literal exponent>)` as a compiler
// axiom. It has no effect verdict of its own: it composes typed child floors,
// or bubbles a child Incomplete unchanged.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{numeric_floor_from_term, PowVisitor};
use crate::sugar::primitive_int::{
    deferred_primitive_method_term, integer_receiver_can_ground_frag, is_deferred_primitive_term,
};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    const_fold_int_term, const_fold_u128_term, num, term_contains_curry_param, Desugared, Outcome,
    Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("int_pow", SugarRole::Term, recognize);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let stripped = frag.strip_refs_groups();
    if stripped.call_method_key().as_deref() != Some("pow") {
        return None;
    }
    if stripped.call_arg_count() != 1 {
        return None;
    }
    let receiver_frag = stripped.call_receiver()?;
    let args = stripped.call_args();
    let exponent_frag = &args[0];
    if !integer_receiver_can_ground_frag(&receiver_frag, fcx, 0)
        || !integer_receiver_can_ground_frag(exponent_frag, fcx, 0)
    {
        return None;
    }
    Some(Box::new(IntPowSugar {
        receiver: SugarBody::term_frag(&receiver_frag, fcx),
        exponent: SugarBody::term_frag(exponent_frag, fcx),
    }))
}

struct IntPowSugar {
    receiver: SugarBody<TermFloor>,
    exponent: SugarBody<TermFloor>,
}

impl Sugar for IntPowSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match term_body(&self.receiver, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let exponent = match term_body(&self.exponent, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        if term_contains_curry_param(&receiver)
            || term_contains_curry_param(&exponent)
            || is_deferred_primitive_term(&receiver)
        {
            return Outcome::Complete(Desugared::Term(deferred_primitive_method_term(
                "pow",
                receiver,
                vec![exponent],
            )));
        }
        let Some(exponent) = const_fold_int_term(&exponent)
            .or_else(|| const_fold_u128_term(&exponent).and_then(|n| i128::try_from(n).ok()))
        else {
            return Outcome::Complete(Desugared::Term(deferred_primitive_method_term(
                "pow",
                receiver,
                vec![exponent],
            )));
        };
        if exponent < 0 {
            panic!("int pow exponent is negative; Rust pow exponents must be unsigned");
        }
        let exponent =
            u32::try_from(exponent).unwrap_or_else(|_| panic!("int pow exponent does not fit u32"));
        let Some(floor) = numeric_floor_from_term(&receiver) else {
            return Outcome::Complete(Desugared::Term(deferred_primitive_method_term(
                "pow",
                receiver,
                vec![num(i128::from(exponent))],
            )));
        };
        let Some(result) = floor.accept(PowVisitor { exponent }) else {
            panic!(
                "int pow numeric floor could not compute a result; write the owning typed floor before Outcome"
            );
        };
        let Some(term) = result.term() else {
            panic!("int pow numeric floor could not reify its result term");
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::int_pow",
            exponent,
            ?floor,
            ?result,
            "resolved primitive integer pow compiler axiom"
        );
        Outcome::Complete(Desugared::Term(term))
    }
}

fn term_body(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_term()
            .unwrap_or_else(|| panic!("term body completed as non-term before int pow"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    fn pow_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        // The tail expression statement is the only statement;
        // `terms()` on the Expr stmt yields the single method-call expr child.
        let terms = stmts[0].terms();
        terms[0]
    }

    /// Positive: `2u32.pow(10u32)` -> observed "MethodCall", `call_method_key()` returns
    /// `"pow"`, `call_arg_count()` is 1. Syn wraps the literal receiver in a Paren node
    /// (disambiguation of `2.` vs float literal); `strip_refs_groups()` peels it to expose
    /// the underlying "PrimitiveLiteral". Struct holds `SugarBody<TermFloor>` x2 -- no raw syn.
    #[test]
    fn from_src_pow_observed_method_key_arg_count_receiver_and_exponent() {
        let file = parse_file("fn f() -> u32 { 2u32.pow(10u32) }");
        let frag = pow_expr_frag(&file, "f.rs");

        // observed shape
        assert_eq!(frag.observed(), "MethodCall");

        // method key via typed accessor -- no as_expr / Expr:: / MethodCall field access here
        assert_eq!(frag.call_method_key().as_deref(), Some("pow"));

        // arg count: exactly one (the exponent)
        assert_eq!(frag.call_arg_count(), 1);

        // receiver: syn wraps `2u32` in a Paren (method-call disambiguation); strip to literal
        let recv = frag.call_receiver().expect("receiver present");
        assert_eq!(recv.strip_refs_groups().observed(), "PrimitiveLiteral");

        // exponent arg: `10u32` is a PrimitiveLiteral fragment (not wrapped)
        let args = frag.call_args();
        assert_eq!(args[0].observed(), "PrimitiveLiteral");
    }

    /// Discrimination: `x.isqrt()` has method key `"isqrt"`, not `"pow"`, and
    /// `call_arg_count()` is 0, not 1. Proves the method-key guard rejects non-pow calls.
    #[test]
    fn discrimination_isqrt_does_not_match_pow_key_or_arg_count() {
        let file = parse_file("fn f(x: u32) -> u32 { x.isqrt() }");
        let frag = pow_expr_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert_ne!(frag.call_method_key().as_deref(), Some("pow"));
        assert_eq!(frag.call_arg_count(), 0);
    }

    /// Structural: a `BinOp` fragment returns `None` from `call_method_key()` and
    /// `call_receiver()` -- shape-specific accessors do not bleed across kinds.
    #[test]
    fn structural_binop_returns_none_from_call_method_accessors() {
        let file = parse_file("fn f(a: u32, b: u32) -> u32 { a + b }");
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = frag.function_body().unwrap();
        let stmts = body.statements();
        let terms = stmts[0].terms();
        let binop_frag = &terms[0];

        assert_eq!(binop_frag.observed(), "BinOp");
        assert_eq!(binop_frag.call_method_key(), None);
        assert!(binop_frag.call_receiver().is_none());
        // call_arg_count returns 0 for non-call shapes (empty vec)
        assert_eq!(binop_frag.call_arg_count(), 0);
    }
}
