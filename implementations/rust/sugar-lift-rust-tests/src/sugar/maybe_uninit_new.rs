// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `MaybeUninit::new(<const-eval literal>).assume_init()`.
//
// When the argument to `new` is a source literal, the MaybeUninit wrapper is
// fully transparent: `assume_init` is identity and the value IS the literal.
// This gives z3 TEETH: `MaybeUninit::new(7).assume_init() == 8` becomes UNSAT
// (refutable) instead of SAT-against-an-opaque-EUF.
//
// Scope / guard:
//   * ONLY `MaybeUninit::new(<const-eval literal>).assume_init()` is warranted.
//   * A runtime or non-literal argument to `new` returns `None` here; the
//     generic method sugar handles it opaquely (never fabricate).
//   * `MaybeUninit::uninit().assume_init()` does NOT match (receiver is not
//     `new(<literal>)`); it falls through to the generic method sugar.
//   * `MaybeUninit::zeroed()` is out of scope for this recognizer.
//
// Ambiguity guard: this recognizer fires ONLY on the very specific two-call
// chain `.assume_init()` over `MaybeUninit::new(<lit>)`. Any future same-role
// overlap must declare a `comes_before` edge instead of relying on catalog order.

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{build_term_frag, SugarBuildCtx};
use crate::sugar::source_fragment::SourceFragment;
use crate::{Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "maybe_uninit_new",
    &["method"],
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
            use std::mem::MaybeUninit;

            #[test]
            fn t_maybe_uninit_new_good() {
                let got = unsafe { MaybeUninit::new(7_u32).assume_init() };
                assert_eq!(got, 7);
            }
        "#,
        r#"
            use std::mem::MaybeUninit;

            #[test]
            fn t_maybe_uninit_new_bad() {
                let got = unsafe { MaybeUninit::new(7_u32).assume_init() };
                assert_eq!(got, 8);
            }
        "#,
    ),
    recognize,
);

// FULLY MIGRATED (Phase-3 ratchet): no as_expr(), no raw Expr:: / MethodCall
// field access in the recognize body. Uses call_method_key(), call_arg_count(),
// call_receiver(), strip_refs_groups(), call_func(), path_has_qself(),
// path_penultimate_ident(), path_last_segment_ident(), call_args(), and
// is_const_eval_literal() exclusively. build_term_frag() from factory.rs builds
// the inner term without escaping to raw syn here.
fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Outer must be `.assume_init()` with no extra arguments.
    if frag.call_method_key()?.as_str() != "assume_init" {
        return None;
    }
    if frag.call_arg_count() != 0 {
        return None;
    }
    // Receiver must be `MaybeUninit::new(<const-eval literal>)`.
    let receiver_frag = frag.call_receiver()?;
    let inner_frag = receiver_frag.strip_refs_groups();
    // Inner call must have exactly one argument.
    if inner_frag.call_arg_count() != 1 {
        return None;
    }
    // Function must be `MaybeUninit::new` path: no qself, 2+ segments,
    // second-to-last == "MaybeUninit", last == "new".
    // Turbofish form `MaybeUninit::<u32>::new(7)` is accepted (type args on
    // segments are ignored -- we only inspect the ident of each segment).
    let func_frag = inner_frag.call_func()?.strip_refs_groups();
    if func_frag.path_has_qself() {
        return None;
    }
    if func_frag.path_penultimate_ident()?.as_str() != "MaybeUninit" {
        return None;
    }
    if func_frag.path_last_segment_ident()?.as_str() != "new" {
        return None;
    }
    // Argument must be a const-eval literal (Expr::Lit or negated literal).
    let arg_frag = inner_frag.call_args().into_iter().next()?;
    if !arg_frag.is_const_eval_literal() {
        return None;
    }
    Some(Box::new(AssumeInitLiteralSugar {
        inner: build_term_frag(&arg_frag, fcx),
    }))
}

/// Thin passthrough: desugar to whatever the literal's term is.
struct AssumeInitLiteralSugar {
    inner: Box<dyn Sugar>,
}

impl Sugar for AssumeInitLiteralSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.inner.desugar(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::factory::SugarBuildCtx;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
    use crate::{LiftOptions, TemporalPlan, TemporalScope};

    /// Walk into `fn f() { <tail_expr> }` and return the single tail expression
    /// fragment. Mirrors the helper used in result_predicate.rs tests.
    fn tail_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    fn make_fcx<'a>(
        scope: &'a TemporalScope,
        options: &'a LiftOptions,
        let_inits: &'a std::collections::BTreeMap<String, &'a syn::Expr>,
    ) -> SugarBuildCtx<'a, 'a> {
        SugarBuildCtx::new(scope, options, let_inits)
    }

    /// Positive: `MaybeUninit::new(7u32).assume_init()` is classified as
    /// `"MethodCall"`, `call_method_key()` returns `"assume_init"`,
    /// `call_arg_count()` is 0, `call_receiver()` yields a `"Call"` fragment
    /// (the `MaybeUninit::new(7u32)` call), its func path has the right idents,
    /// and its single arg `is_const_eval_literal()`. `recognize()` returns `Some`.
    /// No as_expr / Expr:: / MethodCall field access in this test body.
    #[test]
    fn from_src_assume_init_observed_method_key_receiver_and_literal_arg() {
        let file = parse_file("fn f() -> u32 { MaybeUninit::new(7u32).assume_init() }");
        let frag = tail_expr_frag(&file, "f.rs");

        // observed: outer is a method call
        assert_eq!(frag.observed(), "MethodCall");

        // method key via typed accessor -- no raw Expr:: access
        assert_eq!(frag.call_method_key().as_deref(), Some("assume_init"));

        // assume_init takes no explicit args
        assert_eq!(frag.call_arg_count(), 0);

        // receiver is MaybeUninit::new(7u32): a plain Call
        let recv = frag.call_receiver().expect("receiver present");
        let inner = recv.strip_refs_groups();
        assert_eq!(inner.observed(), "Call");
        assert_eq!(inner.call_arg_count(), 1);

        // func path: no qself, penultimate == "MaybeUninit", last == "new"
        let func = inner.call_func().expect("func present").strip_refs_groups();
        assert!(!func.path_has_qself());
        assert_eq!(
            func.path_penultimate_ident().as_deref(),
            Some("MaybeUninit")
        );
        assert_eq!(func.path_last_segment_ident().as_deref(), Some("new"));

        // arg is a const-eval literal
        let args = inner.call_args();
        assert_eq!(args.len(), 1);
        assert!(
            args[0].is_const_eval_literal(),
            "7u32 must be a const-eval literal"
        );

        // build: recognize claims this site
        let scope = TemporalScope::new("maybe-uninit-new-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);
        assert!(
            recognize(&frag, &fcx).is_some(),
            "recognize should claim MaybeUninit::new(7u32).assume_init()"
        );
    }

    /// Discrimination: `MaybeUninit::uninit().assume_init()` has outer method
    /// `"assume_init"` with 0 args and the right outer shape, but its receiver
    /// `uninit()` is a call with 0 args (not 1), so `recognize()` returns `None`.
    /// Proves the inner-call-arg-count guard fires correctly.
    #[test]
    fn discrimination_uninit_assume_init_not_claimed() {
        // syn will parse this syntactically even though it is semantically
        // unsound; we only need the shape.
        let file = parse_file("fn f() -> u32 { MaybeUninit::uninit().assume_init() }");
        let frag = tail_expr_frag(&file, "f.rs");

        assert_eq!(frag.call_method_key().as_deref(), Some("assume_init"));
        assert_eq!(frag.call_arg_count(), 0);

        // inner receiver (uninit()) has 0 args, not 1 -- guard fires here
        let recv = frag.call_receiver().expect("receiver");
        let inner = recv.strip_refs_groups();
        assert_eq!(inner.call_arg_count(), 0);

        let scope = TemporalScope::new("maybe-uninit-new-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);
        assert!(
            recognize(&frag, &fcx).is_none(),
            "recognize must NOT claim MaybeUninit::uninit().assume_init()"
        );
    }

    /// Structural: a `BinOp` fragment returns `None` from `call_method_key()` and
    /// `call_receiver()` -- the recognizer's first guard fires and `recognize`
    /// returns `None`. Proves typed accessors are shape-specific.
    #[test]
    fn structural_binop_call_method_key_returns_none() {
        let file = parse_file("fn f(a: i32, b: i32) -> i32 { a + b }");
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = frag.function_body().unwrap();
        let stmts = body.statements();
        let terms = stmts[0].terms();
        let binop_frag = &terms[0];

        assert_eq!(binop_frag.observed(), "BinOp");
        // call_method_key returns None for non-MethodCall shapes
        assert_eq!(binop_frag.call_method_key(), None);
        // recognize short-circuits immediately on the None method key
        let scope = TemporalScope::new("maybe-uninit-new-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);
        assert!(
            recognize(binop_frag, &fcx).is_none(),
            "BinOp must not be claimed"
        );
    }
}
