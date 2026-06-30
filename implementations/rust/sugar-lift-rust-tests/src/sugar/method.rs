// SPDX-License-Identifier: Apache-2.0
//
// `MethodSugar` + the TERM recognizer for `Expr::MethodCall`.
//
// MethodSugar owns method callsite identity, not method-specific value semantics
// and not runtime effects. It completes the receiver child first, then arg children
// in source order, and emits `method:<m>` over `[receiver, args..]`. Child effects
// bubble up unchanged. A receiver/arg that completes as a non-term is an impossible
// construction state and panics loudly.

use std::rc::Rc;

use sugar_ir_symbolic::{make_var, Term};

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    angle_args_key, is_consuming_iterator_method, receiver_is_versioned_iterator, Desugared,
    Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::fallback_term("method", recognize);

/// TERM recognizer for `Expr::MethodCall`.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let method = frag.call_method_key()?;
    let receiver = frag.call_receiver()?;
    let args = frag.call_args();
    Some(Box::new(MethodSugar::new(
        method,
        SugarBody::term_frag(&receiver, fcx),
        args.iter()
            .map(|arg| SugarBody::term_frag(arg, fcx))
            .collect(),
    )))
}

/// The `method:<m>` ctor key: `method.turbofish` appends the angle-args key.
pub(crate) fn method_key(call: &syn::ExprMethodCall) -> String {
    match &call.turbofish {
        Some(args) => format!("{}{}", call.method, angle_args_key(args)),
        None => call.method.to_string(),
    }
}

/// Method-call term nodes are constructed with their receiver/arg bodies. The
/// only source-derived payload retained by this generic bridge is the stable
/// method key; value semantics belong to specific method sugars and floors.
enum MethodSugar {
    Constructive {
        method: String,
        receiver: SugarBody<TermFloor>,
        args: Vec<SugarBody<TermFloor>>,
    },
}

impl MethodSugar {
    fn new(
        method: impl Into<String>,
        receiver: SugarBody<TermFloor>,
        args: Vec<SugarBody<TermFloor>>,
    ) -> Self {
        MethodSugar::Constructive {
            method: method.into(),
            receiver,
            args,
        }
    }
}

impl Sugar for MethodSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self {
            MethodSugar::Constructive {
                method,
                receiver,
                args,
            } => {
                let mut receiver = match receiver.reduce(ctx) {
                    Outcome::Complete(d) => match d.into_term() {
                        Some(t) => t,
                        None => {
                            panic!(
                                "method `{method}` receiver completed a non-Term where a Term was required; write more Sugar for this AST"
                            );
                        }
                    },
                    Outcome::Incomplete(e) => return Outcome::Incomplete(e),
                };
                if is_consuming_iterator_method(method) {
                    if let Term::Var { name } = receiver.as_ref() {
                        if receiver_is_versioned_iterator(name, ctx.scope) {
                            let occ = ctx.scope.bump_consuming_occurrence(name);
                            if occ > 0 {
                                receiver = make_var(format!("{name}@adv{occ}"));
                            }
                        }
                    }
                }
                let mut terms = vec![receiver];
                for arg in args {
                    let term = match arg.reduce(ctx) {
                        Outcome::Complete(d) => match d.into_term() {
                            Some(t) => t,
                            None => {
                                panic!(
                                    "method `{method}` argument completed a non-Term where a Term was required; write more Sugar for this AST"
                                );
                            }
                        },
                        Outcome::Incomplete(e) => return Outcome::Incomplete(e),
                    };
                    terms.push(term);
                }
                Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
                    name: format!("method:{method}"),
                    args: terms,
                })))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::source_fragment::{FragNode, SourceFragment};
    use crate::{
        sugar_ctx, Desugared, Effect, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, Sugar,
        TemporalPlan, TemporalScope,
    };
    use sugar_ir_symbolic::Term;
    use syn::{Expr, Item};

    fn expr(src: &str) -> Expr {
        syn::parse_str(src).expect("parse expr")
    }

    fn term_body(src: &str) -> SugarBody<TermFloor> {
        let parsed = expr(src);
        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        SugarBody::term(&parsed, &fcx)
    }

    fn effect_body(reason: &'static str) -> SugarBody<TermFloor> {
        struct ChildEffect {
            reason: &'static str,
        }

        impl Sugar for ChildEffect {
            fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
                Outcome::Incomplete(Effect::AmbiguousTemporalIdentity {
                    boundary: "child".to_string(),
                    reason: self.reason.to_string(),
                })
            }
        }

        SugarBody::from_node(Box::new(ChildEffect { reason }))
    }

    fn run(node: &MethodSugar) -> Outcome {
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let mut fw = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut fw, 0);
        node.desugar(&ctx)
    }

    fn ctor_arg_vars(term: &Term) -> Vec<String> {
        let Term::Ctor { args, .. } = term else {
            panic!("expected a Ctor, got {term:?}");
        };
        args.iter()
            .map(|a| match &**a {
                Term::Var { name } => name.clone(),
                other => panic!("expected a Var arg, got {other:?}"),
            })
            .collect()
    }

    #[test]
    fn emits_method_ctor_with_receiver_then_args() {
        let node = MethodSugar::new("get", term_body("receiver"), vec![term_body("idx")]);

        let Outcome::Complete(Desugared::Term(term)) = run(&node) else {
            panic!("expected a Complete term");
        };

        match &*term {
            Term::Ctor { name, .. } => assert_eq!(name, "method:get"),
            other => panic!("expected a Ctor, got {other:?}"),
        }
        assert_eq!(
            ctor_arg_vars(&term),
            vec!["receiver".to_string(), "idx".to_string()]
        );
    }

    #[test]
    fn method_does_not_own_starts_with_refusal() {
        let node = MethodSugar::new(
            "starts_with",
            term_body("receiver"),
            vec![term_body("needle")],
        );

        let Outcome::Complete(Desugared::Term(term)) = run(&node) else {
            panic!("expected method bridge, not a method-owned effect");
        };

        match &*term {
            Term::Ctor { name, args } => {
                assert_eq!(name, "method:starts_with");
                assert_eq!(args.len(), 2);
            }
            other => panic!("expected a Ctor, got {other:?}"),
        }
    }

    #[test]
    fn propagates_receiver_effect_verbatim() {
        let node = MethodSugar::new(
            "touch",
            effect_body("synthetic receiver effect"),
            Vec::new(),
        );

        match run(&node) {
            Outcome::Incomplete(effect) => {
                let reason = effect.reason();
                assert!(
                    reason.contains("synthetic receiver effect"),
                    "unexpected receiver effect: {reason}"
                );
            }
            Outcome::Complete(_) => panic!("expected receiver effect to bubble up"),
        }
    }

    #[test]
    fn propagates_argument_effect_verbatim() {
        let node = MethodSugar::new(
            "touch",
            term_body("receiver"),
            vec![effect_body("synthetic argument effect")],
        );

        match run(&node) {
            Outcome::Incomplete(effect) => {
                let reason = effect.reason();
                assert!(
                    reason.contains("synthetic argument effect"),
                    "unexpected argument effect: {reason}"
                );
            }
            Outcome::Complete(_) => panic!("expected argument effect to bubble up"),
        }
    }

    #[test]
    fn non_term_receiver_is_a_gap_not_an_effect() {
        struct NonTermReceiver;

        impl Sugar for NonTermReceiver {
            fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
                Outcome::Complete(Desugared::LiteralString("not a receiver term".to_string()))
            }
        }

        let node = MethodSugar::new(
            "touch",
            SugarBody::from_node(Box::new(NonTermReceiver)),
            Vec::new(),
        );

        let panic = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| run(&node)));
        assert!(panic.is_err(), "non-term receiver must gap loudly");
    }

    // -- from_src tests: source -> SourceFragment -> observed -> recognize -> floor --------
    // No parse_quote!, no StubTerm, no run() helper.

    #[test]
    fn from_src_builds_method_ctor_floor() {
        // source -> SourceFragment -> observed -> recognize -> desugar -> Term floor
        let e = expr("receiver.get(idx)");
        let frag = SourceFragment::from_node(FragNode::Expr(&e), "<test>");

        assert_eq!(
            frag.observed(),
            "MethodCall",
            "observed shape must be MethodCall"
        );

        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let sugar = recognize(&frag, &fcx).expect("recognize must accept a MethodCall fragment");

        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut fw = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut fw, 0);

        let Outcome::Complete(Desugared::Term(term)) = sugar.desugar(&ctx) else {
            panic!("expected a Complete term from MethodCall");
        };
        let Term::Ctor { name, args } = &*term else {
            panic!("expected a Ctor term, got {term:?}");
        };
        assert_eq!(name, "method:get");
        assert_eq!(args.len(), 2, "receiver + one positional arg");
    }

    #[test]
    fn from_src_turbofish_key_included() {
        // turbofish: receiver.parse::<i32>() -> method key "parse::<i32>"
        let e = expr("receiver.parse::<i32>()");
        let frag = SourceFragment::from_node(FragNode::Expr(&e), "<test>");

        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let sugar = recognize(&frag, &fcx).expect("recognize must accept turbofish MethodCall");

        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut fw = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut fw, 0);

        let Outcome::Complete(Desugared::Term(term)) = sugar.desugar(&ctx) else {
            panic!("expected a Complete term from turbofish MethodCall");
        };
        let Term::Ctor { name, .. } = &*term else {
            panic!("expected a Ctor term, got {term:?}");
        };
        assert_eq!(
            name, "method:parse::<i32>",
            "turbofish must appear in the method key"
        );
    }

    #[test]
    fn from_src_rejects_non_method_call() {
        // discrimination: plain Call is NOT a MethodCall; recognize must return None.
        let e = expr("foo(idx)");
        let frag = SourceFragment::from_node(FragNode::Expr(&e), "<test>");

        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_none(),
            "method recognizer must not claim a plain function Call"
        );
    }
}
