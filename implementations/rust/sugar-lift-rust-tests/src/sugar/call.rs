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
// THE FUNC-HEAD KEY IS CAPTURED AT CONSTRUCTION. The function head (`f`, `Path::seg`,
// a paren/group-wrapped path, ...) is NOT runtime state -- it is a syntactic key the
// arm computes with `expr_head_key(&call.func)`. So `CallSugar` holds the already-
// computed `String` (the decomposer calls `expr_head_key` once, at build time) rather
// than re-walking the `func` expr in `desugar`. The result is byte-identical: the same
// `format!("call:{key}")` name the arm emits.
//
// THE ARGS ARE PRE-BUILT CHILD SUGAR. Each argument is held as a `Box<dyn Sugar>`
// (built by the factory from the arg `Expr`), composed IN SOURCE ORDER. `desugar`
// digs each child and collects its `Term`, preserving order, exactly as the arm's
// `for arg in &call.args { args.push(translate_term_in_scope(arg, scope)?); }` loop
// does. A child that does not reduce to a term (`into_term` -> `None`) bails the whole
// node (the byte-identical structural backstop, the old `?`-propagated `Err`); a child
// that `Hit`s a named order-loss boundary propagates that `Hit` VERBATIM (the old
// named `Err` the inner `translate_term_in_scope?` produced).
//
// THE ROUTER PREAMBLE IS NOT THIS NODE'S JOB. The `Expr::Call` arm has an EARLY-RETURN
// recognizer BEFORE the constructive tail:
//
//   if let Some(term) = type_id_of_call_term(&call.func, call.args.len())? {
//       return Ok(term);
//   }
//
// That `TypeId::of::<T>()` const-fold (and its own `?`-propagated `Err`) is a ROUTER
// concern: it decides whether the constructive `call:` ctor is reached at all. It lives
// in the factory arm the coordinator wires (the decomposer / dispatch that builds this
// node ONLY when the preamble did not already return). `CallSugar` is the CONSTRUCTIVE
// COMPOSER ONLY -- it assumes the preamble has been cleared and emits the `call:` ctor.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;

use crate::{expr_head_key, Desugared, Outcome, Sugar, SugarCtx};

/// A free-function call `f(a, b, ...)` in term position, composed as a node whose
/// `desugar` emits the `call:<head>` ctor over its argument child terms (the
/// constructive tail of the `Expr::Call` arm). See the module header.
pub(crate) struct CallSugar {
    /// The function-head key, computed ONCE at construction via `expr_head_key(&func)`
    /// (a syntactic key, not runtime state). The emitted ctor name is
    /// `format!("call:{head_key}")` -- byte-identical to the arm.
    head_key: String,
    /// The argument child `Sugar`s, IN SOURCE ORDER. `desugar` digs each, reading its
    /// `Term` back out through `into_term`; the collected terms are the ctor `args`.
    args: Vec<Box<dyn Sugar>>,
}

impl CallSugar {
    /// Build a `CallSugar` from the already-computed func-head key and the pre-built
    /// argument children (in source order). The decomposer calls `expr_head_key(&func)`
    /// once and hands the resulting `String` here; the args are built by the factory.
    pub(crate) fn new(head_key: impl Into<String>, args: Vec<Box<dyn Sugar>>) -> Self {
        CallSugar {
            head_key: head_key.into(),
            args,
        }
    }

    /// Convenience: compute the func-head key from the `func` expr (via the shared
    /// `expr_head_key`) and build the node. Mirrors how the arm computes the name --
    /// `format!("call:{}", expr_head_key(&call.func))` -- so the call site need not
    /// reach for the helper itself.
    pub(crate) fn from_func(func: &Expr, args: Vec<Box<dyn Sugar>>) -> Self {
        CallSugar::new(expr_head_key(func), args)
    }
}

impl Sugar for CallSugar {
    /// Dig each argument child to its `Term` (in source order), then emit the
    /// `call:<head>` ctor over the collected terms -- the constructive tail of the
    /// `Expr::Call` arm, byte-identical. A child that `Hit`s a named order-loss
    /// boundary propagates that `Hit` verbatim (the old named inner `Err`); a child
    /// that digs to a non-term `Desugared` (`into_term` -> `None`) bails the node via
    /// the structural backstop (`Outcome::from_opt(None)`, the old `?`-propagated
    /// generic refusal).
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let mut args = Vec::new();
        for arg in &self.args {
            let term = match arg.desugar(ctx) {
                Outcome::Dug(d) => match d.into_term() {
                    Some(t) => t,
                    None => return Outcome::from_opt(None),
                },
                Outcome::Hit(e) => return Outcome::Hit(e),
            };
            args.push(term);
        }
        Outcome::Dug(Desugared::Term(Rc::new(Term::Ctor {
            name: format!("call:{}", self.head_key),
            args,
        })))
    }
}

#[cfg(test)]
mod tests {
    // `CallSugar` is the CONSTRUCTIVE composer: given pre-built argument children and a
    // captured func-head key, it emits the `call:<head>` ctor over the child terms. The
    // tests exercise that constructive tail directly, with LOCAL stub children
    // (`StubTerm` digs to a fixed leaf term; `StubHit` Hits a named boundary), asserting
    // the EXACT emitted ctor (name + args order) and verbatim `Hit` propagation. A real
    // `SugarCtx` is built from the crate's own constructors (`TemporalScope::new` over a
    // `TemporalPlan::default`, an empty `ReductionCtx::from_items`, `LiftOptions::default`,
    // a fresh `FloatWidthScope`) via the `sugar_ctx` helper -- the stubs ignore `ctx`, so
    // any well-formed ctx exercises the dig/collect/emit path.
    use super::*;
    use crate::{
        sugar_ctx, Desugared, Effect, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, Sugar,
        SugarCtx, TemporalPlan, TemporalScope,
    };
    use sugar_ir_symbolic::{make_var, Term};
    use syn::Item;

    /// A test-double leaf `Sugar` that digs to a fixed `Var` term named `tag`, so a
    /// composite's collected-arg order is observable by the leaf names.
    struct StubTerm {
        tag: &'static str,
    }
    impl Sugar for StubTerm {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::Dug(Desugared::Term(make_var(self.tag)))
        }
    }

    /// A test-double leaf `Sugar` that Hits a named order-loss boundary, used to assert
    /// the composite propagates a child `Hit` verbatim.
    struct StubHit {
        boundary: &'static str,
    }
    impl Sugar for StubHit {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::Hit(Effect::TemporalRead {
                boundary: self.boundary.to_string(),
            })
        }
    }

    /// Run `node.desugar` against a freshly-built, minimal-but-real `SugarCtx`. The stub
    /// children ignore `ctx`, so the ctx contents are immaterial -- it need only be
    /// well-formed (the lifetime-heavy parts are owned by the caller's locals).
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
        let node = CallSugar::new(
            "f",
            vec![
                Box::new(StubTerm { tag: "x" }),
                Box::new(StubTerm { tag: "y" }),
            ],
        );
        let Outcome::Dug(Desugared::Term(term)) = run(&node) else {
            panic!("expected a Dug term");
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
        let node = CallSugar::new("g", Vec::new());
        let Outcome::Dug(Desugared::Term(term)) = run(&node) else {
            panic!("expected a Dug term");
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
        // `from_func` mirrors the arm's `expr_head_key(&call.func)`: a path head `h`
        // keys the ctor as `call:h`.
        let func: Expr = syn::parse_str("h").expect("parse func path");
        let node = CallSugar::from_func(&func, vec![Box::new(StubTerm { tag: "a" })]);
        let Outcome::Dug(Desugared::Term(term)) = run(&node) else {
            panic!("expected a Dug term");
        };
        match &*term {
            Term::Ctor { name, .. } => assert_eq!(name, "call:h"),
            other => panic!("expected a Ctor, got {other:?}"),
        }
    }

    #[test]
    fn propagates_child_hit_verbatim() {
        // A child that Hits a named order-loss boundary aborts the whole node with that
        // SAME `Hit` (the old named inner `translate_term_in_scope?` `Err`).
        let node = CallSugar::new(
            "f",
            vec![
                Box::new(StubTerm { tag: "x" }),
                Box::new(StubHit {
                    boundary: "mut[i]",
                }),
            ],
        );
        match run(&node) {
            Outcome::Hit(Effect::TemporalRead { boundary }) => {
                assert_eq!(boundary, "mut[i]");
            }
            Outcome::Hit(_) => panic!("expected the child's TemporalRead Hit, got a different Hit"),
            Outcome::Dug(_) => panic!("expected the child's Hit to propagate, got a Dug"),
        }
    }
}
