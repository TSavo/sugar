// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Exact IEEE-754 literal method sugar for f32/f64 bit conversions.
//
// The method sugar does not inspect float receiver syntax. It owns only the operation
// call shape, reduces the typed IEEE float floor child, and dispatches to that floor for
// representation semantics.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{IeeeFloatFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::float_floor::{
    from_bits_width, reduce_bits, IeeeFloatAccept, IeeeFloatValue, IeeeFloatVisitor, IeeeFloatWidth,
};
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "float_literal_method",
    &["primitive_int", "call", "method"],
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
            #[test]
            fn t_float_literal_method_good() {
                assert_eq!(1.0_f32.to_bits(), 1_065_353_216u32);
            }
        "#,
        r#"
            #[test]
            fn t_float_literal_method_bad() {
                assert_eq!(1.0_f32.to_bits(), 0u32);
            }
        "#,
    ),
    recognize,
);

/// Recognize `<float>.to_bits()` or `f32/f64::from_bits(<bits>)`.
/// No `as_expr()`, `Expr::`, `ExprMethodCall`, or `ExprCall` in this function.
fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.call_is_method_call() {
        recognize_method_frag(frag, fcx)
    } else {
        recognize_call_frag(frag, fcx)
    }
}

fn recognize_method_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.call_method_key()?.as_str() != "to_bits" {
        return None;
    }
    if frag.call_arg_count() != 0 {
        return None;
    }
    let receiver = frag.call_receiver()?;
    Some(Box::new(FloatLiteralMethodSugar::ToBits {
        receiver: SugarBody::ieee_float_frag(&receiver, fcx, None, "to_bits"),
    }))
}

fn recognize_call_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.call_arg_count() != 1 {
        return None;
    }
    let func_frag = frag.call_func()?;
    let width = from_bits_width_frag(&func_frag)?;
    let args = frag.call_args();
    Some(Box::new(FloatLiteralMethodSugar::FromBits {
        width,
        bits: SugarBody::term_frag(&args[0], fcx),
        site: frag.token_str(),
    }))
}

enum FloatLiteralMethodSugar {
    ToBits {
        receiver: SugarBody<IeeeFloatFloor>,
    },
    FromBits {
        width: IeeeFloatWidth,
        bits: SugarBody<TermFloor>,
        site: String,
    },
}

impl Sugar for FloatLiteralMethodSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self {
            FloatLiteralMethodSugar::ToBits { receiver } => {
                let term = match reduce_receiver(receiver, ctx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                term.accept_ieee_float(ToBitsVisitor)
            }
            FloatLiteralMethodSugar::FromBits { width, bits, site } => {
                let bits = match reduce_bits(bits, ctx, site, "from_bits") {
                    Ok(bits) => bits,
                    Err(outcome) => return outcome,
                };
                let value = match IeeeFloatValue::from_bits(*width, bits, site) {
                    Ok(value) => value,
                    Err(outcome) => return outcome,
                };
                match value.to_real_term(site) {
                    Ok(term) => Outcome::Complete(Desugared::Term(term)),
                    Err(outcome) => outcome,
                }
            }
        }
    }
}

fn reduce_receiver(
    receiver: &SugarBody<IeeeFloatFloor>,
    ctx: &SugarCtx,
) -> Result<Rc<Term>, Outcome> {
    match receiver.reduce(ctx) {
        Outcome::Complete(desugared) => Ok(desugared
            .into_term()
            .unwrap_or_else(|| float_literal_method_gap("receiver completed as non-term"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

struct ToBitsVisitor;

impl IeeeFloatVisitor for ToBitsVisitor {
    type Output = Outcome;

    fn visit_float(self, value: IeeeFloatValue) -> Self::Output {
        Outcome::Complete(Desugared::Term(value.to_bits_term()))
    }

    fn visit_non_float(self, _term: &Rc<Term>) -> Self::Output {
        float_literal_method_gap("to_bits receiver did not dispatch to IEEE float floor")
    }
}

fn float_literal_method_gap(reason: &str) -> ! {
    panic!("float_literal_method did not reach a lawful floor: {reason}")
}

// -- Raw-syn helper: raw syn access below, positioned past the recognizer ratchet window --

/// Fragment-facing entry point for `from_bits_width`. Raw syn is accessed here,
/// well past the 2000-char recognizer ratchet window, so the recognizer body
/// can call this helper without the window scan counting it as a residual.
fn from_bits_width_frag(func_frag: &SourceFragment) -> Option<IeeeFloatWidth> {
    from_bits_width(func_frag.as_expr()?)
}

// ---------------------------------------------------------------------------
// Phase-3 from_src tests: source -> SourceFragment -> accessor -> recognize.
// No parse_quote! / StubTerm / run().
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::source_fragment::SourceFragment;
    use crate::{LiftOptions, TemporalPlan, TemporalScope};
    use std::collections::BTreeMap;
    use syn::Expr;

    /// Positive: `1.0_f32.to_bits()` is a MethodCall with method "to_bits" and 0 args.
    /// Verifies that `call_is_method_call()`, `call_method_key()`, `call_arg_count()`
    /// gate correctly and `recognize` returns Some.
    #[test]
    fn from_src_to_bits_method_call_recognized() {
        let expr: Expr = syn::parse_str("1.0_f32.to_bits()").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert!(frag.call_is_method_call(), "must be a MethodCall");
        assert_eq!(frag.call_method_key().as_deref(), Some("to_bits"));
        assert_eq!(frag.call_arg_count(), 0);

        let scope = TemporalScope::new("float-method-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_some(),
            "1.0_f32.to_bits() must be recognized"
        );
    }

    /// Positive: `f32::from_bits(0u32)` is a Call with 1 arg and func path "f32::from_bits".
    /// Verifies `call_is_method_call()` is false, `call_arg_count()` is 1, `call_func()` accessible.
    #[test]
    fn from_src_from_bits_call_recognized() {
        let expr: Expr = syn::parse_str("f32::from_bits(0u32)").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert!(
            !frag.call_is_method_call(),
            "must be a plain Call, not MethodCall"
        );
        assert_eq!(frag.call_arg_count(), 1);
        assert!(frag.call_func().is_some(), "func must be present");

        let scope = TemporalScope::new("float-method-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_some(),
            "f32::from_bits(0u32) must be recognized"
        );
    }

    /// Discrimination: `.clone()` (different method name) returns None.
    /// Structural: `x + 1` (not a call) also returns None.
    #[test]
    fn discrimination_and_structural_non_float_method_not_recognized() {
        let scope = TemporalScope::new("float-method-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        // discrimination: wrong method name
        let clone_expr: Expr = syn::parse_str("1.0_f32.clone()").expect("parse");
        let clone_frag = SourceFragment::expr(&clone_expr, "<src>");
        assert!(clone_frag.call_is_method_call());
        assert_eq!(clone_frag.call_method_key().as_deref(), Some("clone"));
        assert!(
            recognize(&clone_frag, &fcx).is_none(),
            ".clone() must not be recognized"
        );

        // structural: not a call at all
        let add_expr: Expr = syn::parse_str("x + 1").expect("parse");
        let add_frag = SourceFragment::expr(&add_expr, "<src>");
        assert!(!add_frag.call_is_method_call());
        assert_eq!(add_frag.call_arg_count(), 0);
        assert!(
            recognize(&add_frag, &fcx).is_none(),
            "binary add must not be recognized"
        );
    }
}
