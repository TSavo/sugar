// SPDX-License-Identifier: Apache-2.0
//
// `CallSugar`: the CONSTRUCTIVE term node for a free-function call `f(a, b, ...)` --
// the `Expr::Call` arm of `translate_term_in_scope` (NOT `Expr::MethodCall`, which is
// its own arm and its own future node). It is the term-floor sibling of `IndexSugar`:
// a composite term `Sugar` that builds each argument as a child `Sugar`, reads each
// child's `Term` back out through `Desugared::into_term`, and emits the EXACT
// `Term::Ctor` the arm's constructive tail produces:
//
//   Term::Ctor { name: format!("call:{}", expr_head_key(&func)), args: <arg terms> }
//
// The recognizer captures the raw function expression and raw arguments. `desugar`
// computes the func-head key and builds each child argument lazily, in source order,
// once the full binding context is available.
//
// THE RECOGNIZER PREAMBLE. The `Expr::Call` shape has an EARLY-RETURN
// recognizer BEFORE the constructive tail:
//
//   if let Some(term) = type_id_of_call_term(&call.func, call.args.len())? {
//       return Ok(term);
//   }
//
// That `TypeId::of::<T>()` const-fold (and its own `?`-propagated `Err`) is owned by
// `recognize`: it decides whether the constructive `call:` ctor is reached at all.
// `CallSugar` is the CONSTRUCTIVE COMPOSER ONLY -- it is built only after the preamble
// has been cleared, and then emits the `call:` ctor.

use std::rc::Rc;

use sugar_ir_symbolic::{str_const, Term};
use syn::Expr;

use crate::sugar::factory::{
    compat_reduction, FactoryGap, FactoryReduction, SugarBody, SugarBuildCtx, TermFloor,
};
use crate::sugar::monadic::{none_term, some_term};
use crate::sugar::term_leaf::reasoned_incomplete;
use crate::{
    const_fold_int_term, const_fold_u128_term, expr_head_key, num, type_id_of_call_term, u128_term,
    Desugared, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::fallback_term("call", recognize);

/// TERM recognizer for `Expr::Call`. Mirrors the source-of-truth arm in order: the
/// `TypeId::of` const-fold preamble FIRST (a resolved term, or a reasoned-Incomplete on
/// `Err`), then the constructive `call:<head>` ctor over the arg children ([`CallSugar`]).
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Call(call) = expr else {
        return None;
    };
    if type_id_of_call_decision(&call.func, call.args.len()).is_some() {
        return Some(Box::new(CallSugar::TypeId {
            func: call.func.as_ref().clone(),
            arg_len: call.args.len(),
        }));
    }
    Some(Box::new(CallSugar::Constructive {
        func: call.func.as_ref().clone(),
        args: call
            .args
            .iter()
            .map(|arg| SugarBody::term(arg, fcx))
            .collect(),
    }))
}

/// A free-function call `f(a, b, ...)` in term position, composed as a node whose
/// `desugar` emits the `call:<head>` ctor over its argument child terms (the
/// constructive tail of the `Expr::Call` arm). See the module header.
pub(crate) enum CallSugar {
    TypeId {
        func: Expr,
        arg_len: usize,
    },
    Constructive {
        func: Expr,
        args: Vec<SugarBody<TermFloor>>,
    },
}

impl CallSugar {
    #[allow(dead_code)]
    pub(crate) fn new(func: Expr, args: Vec<SugarBody<TermFloor>>) -> Self {
        CallSugar::Constructive { func, args }
    }
}

fn type_id_of_call_decision(func: &Expr, arg_len: usize) -> Option<Result<(), String>> {
    if arg_len != 0 {
        return None;
    }
    let Expr::Path(path) = func else {
        return None;
    };
    if !is_type_id_of_path(&path.path) {
        return None;
    }
    let Some(last) = path.path.segments.last() else {
        return None;
    };
    let syn::PathArguments::AngleBracketed(args) = &last.arguments else {
        return Some(Err(
            "TypeId::of requires exactly one type argument".to_string()
        ));
    };
    if args.args.len() != 1 {
        return Some(Err(
            "TypeId::of requires exactly one type argument".to_string()
        ));
    }
    let Some(syn::GenericArgument::Type(_)) = args.args.first() else {
        return Some(Err("TypeId::of requires a type argument".to_string()));
    };
    Some(Ok(()))
}

fn is_type_id_of_path(path: &syn::Path) -> bool {
    let segments = path.segments.iter().collect::<Vec<_>>();
    matches!(
        segments.as_slice(),
        [.., type_id, of]
            if type_id.ident == "TypeId" && of.ident == "of"
    )
}

impl Sugar for CallSugar {
    /// Dig each argument child to its `Term` (in source order), then emit the
    /// `call:<head>` ctor over the collected terms -- the constructive tail of the
    /// `Expr::Call` arm, byte-identical. A child that `Incomplete`s a named order-loss
    /// boundary propagates that `Incomplete` verbatim (the old named inner `Err`); a child
    /// that completes to a non-term `Desugared` (`into_term` -> `None`) bails the node via
    /// the structural backstop (`Outcome::from_opt(None)`, the old `?`-propagated
    /// generic refusal).
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        match self {
            CallSugar::TypeId { func, arg_len } => match type_id_of_call_term(func, *arg_len) {
                Ok(Some(term)) => Ok(Outcome::Complete(Desugared::Term(term))),
                Ok(None) => Err(FactoryGap::new(
                    "TypeId::of call did not resolve; write more Sugar for this AST",
                )),
                Err(reason) => Ok(reasoned_incomplete(reason).desugar(ctx)),
            },
            CallSugar::Constructive { func, args } => {
                let mut terms = Vec::new();
                for arg in args {
                    let term = match arg.reduce(ctx)? {
                        Outcome::Complete(d) => match d.into_term() {
                            Some(t) => t,
                            None => {
                                return Err(FactoryGap::new(format!(
                                    "call `{}` argument completed a non-Term where a Term was required; write more Sugar for this AST",
                                    expr_head_key(func)
                                )))
                            }
                        },
                        Outcome::Incomplete(e) => return Ok(Outcome::Incomplete(e)),
                    };
                    terms.push(term);
                }
                let head_key = expr_head_key(func);
                if terms.len() == 1 {
                    if let Some(term) = fold_char_from_u32_call(&head_key, &terms[0]) {
                        return Ok(Outcome::Complete(Desugared::Term(term)));
                    }
                }
                // ARITHMETIC TRAIT-METHOD FOLD: `Add::add(x, y)` → `x + y`, const-evaluated.
                // Maps std-ops trait method calls (Add::add, Sub::sub, Mul::mul, Div::div,
                // Rem::rem, Shl::shl, Shr::shr, BitAnd::bitand, BitOr::bitor, BitXor::bitxor)
                // to their equivalent arithmetic ctor names, then applies the same
                // `const_fold_int_term` / `const_fold_u128_term` that `BinOpSugar` uses. This
                // discharges `assert_eq!(result, Op::method(lhs, rhs))` assertions where `lhs`
                // and `rhs` are let-bound literal values (including `&rhs` ref forms, which
                // `const_fold_int_term` now transparently strips). Without this fold the call
                // emits an opaque `call:Add::add(...)` EUF that the SMT cannot evaluate.
                if terms.len() == 2 {
                    if let Some(arith_op) = arith_trait_method_op(&head_key) {
                        let folded = Rc::new(Term::Ctor {
                            name: arith_op.to_string(),
                            args: terms.clone(),
                        });
                        if let Some(value) = const_fold_u128_term(&folded) {
                            return Ok(Outcome::Complete(Desugared::Term(u128_term(value))));
                        }
                        if let Some(value) = const_fold_int_term(&folded) {
                            return Ok(Outcome::Complete(Desugared::Term(num(value))));
                        }
                    }
                }
                Ok(Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
                    name: format!("call:{head_key}"),
                    args: terms,
                }))))
            }
        }
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

fn fold_char_from_u32_call(head_key: &str, arg: &Rc<Term>) -> Option<Rc<Term>> {
    if !is_char_from_u32_head(head_key) {
        return None;
    }
    let codepoint = const_fold_u128_term(arg)
        .and_then(|value| u32::try_from(value).ok())
        .or_else(|| const_fold_int_term(arg).and_then(|value| u32::try_from(value).ok()))?;
    Some(match char::from_u32(codepoint) {
        Some(ch) => some_term(str_const(ch.to_string())),
        None => none_term(),
    })
}

fn is_char_from_u32_head(head_key: &str) -> bool {
    matches!(
        head_key,
        "char::from_u32" | "core::char::from_u32" | "std::char::from_u32"
    )
}

/// Maps arithmetic trait method `head_key`s (as produced by `expr_head_key`) to
/// the canonical arithmetic ctor names used by `const_fold_int_term` /
/// `const_fold_u128_term`.  Returns `None` for anything that is NOT a two-argument
/// arithmetic trait method, so the fold is only attempted when warranted.
fn arith_trait_method_op(head_key: &str) -> Option<&'static str> {
    match head_key {
        "Add::add" => Some("+"),
        "Sub::sub" => Some("-"),
        "Mul::mul" => Some("*"),
        "Div::div" => Some("int-div"),
        "Rem::rem" => Some("int-rem"),
        "Shl::shl" => Some("shift-left"),
        "Shr::shr" => Some("shift-right"),
        "BitAnd::bitand" => Some("bit-and"),
        "BitOr::bitor" => Some("bit-or"),
        "BitXor::bitxor" => Some("bit-xor"),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    // `CallSugar` is the CONSTRUCTIVE composer: given raw argument expressions and a
    // raw function expression, it lazily emits the `call:<head>` ctor over the child
    // terms. These tests exercise that constructive tail directly through the real
    // factory path, asserting the exact emitted ctor (name + args order) and verbatim
    // child `Incomplete` propagation.
    use super::*;
    use crate::{
        sugar_ctx, Desugared, Effect, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, Sugar,
        TemporalPlan, TemporalScope,
    };
    use sugar_ir_symbolic::Term;
    use syn::Item;

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

    /// Run `node.desugar` against a freshly-built, minimal-but-real `SugarCtx`.
    fn run(node: &CallSugar) -> Outcome {
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let mut fw = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut fw, 0);
        node.desugar(&ctx)
    }

    /// The leaf `Var` names of a ctor's args, in order -- the observable arg order.
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
    fn emits_call_ctor_with_args_in_order() {
        // `f(x, y)` -> `Ctor { name: "call:f", args: [Var(x), Var(y)] }` -- the exact
        // ctor the `Expr::Call` constructive tail emits, args in SOURCE ORDER.
        let node = CallSugar::new(expr("f"), vec![term_body("x"), term_body("y")]);
        let Outcome::Complete(Desugared::Term(term)) = run(&node) else {
            panic!("expected a Complete term");
        };
        match &*term {
            Term::Ctor { name, .. } => assert_eq!(name, "call:f"),
            other => panic!("expected a Ctor, got {other:?}"),
        }
        // Args preserved in source order (not sorted / reordered).
        assert_eq!(ctor_arg_vars(&term), vec!["x".to_string(), "y".to_string()]);
    }

    #[test]
    fn nullary_call_emits_empty_args() {
        // `g()` -> `Ctor { name: "call:g", args: [] }`.
        let node = CallSugar::new(expr("g"), Vec::new());
        let Outcome::Complete(Desugared::Term(term)) = run(&node) else {
            panic!("expected a Complete term");
        };
        match &*term {
            Term::Ctor { name, args } => {
                assert_eq!(name, "call:g");
                assert!(args.is_empty());
            }
            other => panic!("expected a Ctor, got {other:?}"),
        }
    }

    #[test]
    fn head_key_computed_from_func_expr() {
        // The function expression is retained raw and keyed lazily in `desugar`.
        let node = CallSugar::new(expr("h"), vec![term_body("a")]);
        let Outcome::Complete(Desugared::Term(term)) = run(&node) else {
            panic!("expected a Complete term");
        };
        match &*term {
            Term::Ctor { name, .. } => assert_eq!(name, "call:h"),
            other => panic!("expected a Ctor, got {other:?}"),
        }
    }

    #[test]
    fn propagates_child_hit_verbatim() {
        // A child that returns Incomplete aborts the whole node with that SAME `Incomplete` (the old named
        // inner `translate_term_in_scope?` `Err`).
        let node = CallSugar::new(expr("f"), vec![term_body("x"), term_body("&mut y")]);
        match run(&node) {
            Outcome::Incomplete(Effect::Unsupported { reason }) => {
                assert!(
                    reason.contains("unsupported term"),
                    "unexpected reason: {reason}"
                );
                assert!(reason.contains("mutable"), "unexpected reason: {reason}");
            }
            Outcome::Incomplete(_) => {
                panic!("expected the child's Unsupported Incomplete, got a different Incomplete")
            }
            Outcome::Complete(_) => {
                panic!("expected the child's Incomplete to propagate, got a Complete")
            }
        }
    }
}
