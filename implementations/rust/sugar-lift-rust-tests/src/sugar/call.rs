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
// The recognizer captures the function-head key and typed argument bodies at
// construction. `desugar` only reduces those bodies and composes the term floor.
//
// THE RECOGNIZER PREAMBLE. The `Expr::Call` shape has an EARLY-RETURN
// recognizer BEFORE the constructive tail:
//
//   if let Some(term) = type_id_of_call_term(&call.func, call.args.len())? {
//       return Ok(term);
//   }
//
// That `TypeId::of::<T>()` const-fold is owned by the recognizer: it decides whether
// the constructive `call:` ctor is reached at all. A malformed `TypeId::of` shape is
// a construction gap and panics instead of manufacturing an effect. `CallSugar` is the
// CONSTRUCTIVE COMPOSER ONLY -- it is built only after the preamble has been cleared,
// and then emits the `call:` ctor.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{str_const, Term};
use syn::Expr;

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::monadic::{none_term, some_term};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_leaf::resolved_term;
use crate::{
    assoc_call_key, const_eval, const_fold_int_term, const_fold_u128_term, const_val_term, num,
    resolve_value_call_inline, type_id_of_call_term, u128_term, Desugared, Effect, Outcome, Sugar,
    SugarCtx, MAX_VALUE_CALL_INLINE_DEPTH,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::fallback_term(
        "call",
        crate::sugar::claim::SugarWitnesses::pinned_catch(
            "#3415 family i: generic call EUF semantic lie remains SAT",
        ),
        recognize,
    );

/// Resolve and exact-or-bail inline a visible pure value call for caller-owned
/// sugar such as literal function maps.
///
/// Ordinary call terms still compose as `call:f(args)` so source contracts can
/// link at the callsite. This helper is only for sugars whose own semantics
/// require evaluating a callback over literal data. The substituted body is
/// reduced through the literal floor. The result commits only if that floor owns
/// the substituted value completely; otherwise this helper exact-bails and the
/// ordinary call owner keeps the opaque call term.
pub(crate) fn try_inline_value_call(
    ctx: &SugarCtx,
    func: &Expr,
    args: &[Expr],
) -> Result<Option<Rc<Term>>, Effect> {
    if ctx.macro_depth >= MAX_VALUE_CALL_INLINE_DEPTH {
        return Ok(None);
    }
    let Some(inlined) = resolve_value_call_inline(func, args, ctx.scope, ctx.options) else {
        return Ok(None);
    };
    let Some(inlined) = inline_visible_value_calls(ctx, &inlined, ctx.macro_depth + 1) else {
        return Ok(None);
    };
    if let Some(term) =
        const_eval(&inlined, &BTreeMap::new()).and_then(|value| const_val_term(&value))
    {
        if let Some(name) = value_call_support_key(func) {
            ctx.scope.record_inlined_value_helper(&name);
        }
        Ok(Some(term))
    } else {
        Ok(None)
    }
}

/// Inline visible pure value calls inside a substituted helper body for exact
/// callback evaluation. Ordinary call sugar still owns source callsites and
/// emits opaque `call:*` terms; this pass is only the caller-requested
/// evaluation path, and the grounded-term gate below decides whether it commits.
fn inline_visible_value_calls(ctx: &SugarCtx, expr: &Expr, depth: usize) -> Option<Expr> {
    if depth >= MAX_VALUE_CALL_INLINE_DEPTH {
        return None;
    }
    match expr {
        Expr::Call(call) => {
            let args = call
                .args
                .iter()
                .map(|arg| inline_visible_value_calls(ctx, arg, depth + 1))
                .collect::<Option<Vec<_>>>()?;
            if let Some(resolved) =
                resolve_value_call_inline(&call.func, &args, ctx.scope, ctx.options)
            {
                return inline_visible_value_calls(ctx, &resolved, depth + 1);
            }
            let mut out = call.clone();
            out.func = Box::new(inline_visible_value_calls(ctx, &call.func, depth + 1)?);
            out.args = args.into_iter().collect();
            Some(Expr::Call(out))
        }
        Expr::Binary(binary) => {
            let mut out = binary.clone();
            out.left = Box::new(inline_visible_value_calls(ctx, &binary.left, depth + 1)?);
            out.right = Box::new(inline_visible_value_calls(ctx, &binary.right, depth + 1)?);
            Some(Expr::Binary(out))
        }
        Expr::Unary(unary) => {
            let mut out = unary.clone();
            out.expr = Box::new(inline_visible_value_calls(ctx, &unary.expr, depth + 1)?);
            Some(Expr::Unary(out))
        }
        Expr::Paren(paren) => {
            let mut out = paren.clone();
            out.expr = Box::new(inline_visible_value_calls(ctx, &paren.expr, depth + 1)?);
            Some(Expr::Paren(out))
        }
        Expr::Group(group) => {
            let mut out = group.clone();
            out.expr = Box::new(inline_visible_value_calls(ctx, &group.expr, depth + 1)?);
            Some(Expr::Group(out))
        }
        Expr::Reference(reference) => {
            let mut out = reference.clone();
            out.expr = Box::new(inline_visible_value_calls(ctx, &reference.expr, depth + 1)?);
            Some(Expr::Reference(out))
        }
        Expr::Cast(cast) => {
            let mut out = cast.clone();
            out.expr = Box::new(inline_visible_value_calls(ctx, &cast.expr, depth + 1)?);
            Some(Expr::Cast(out))
        }
        Expr::Array(array) => {
            let mut out = array.clone();
            out.elems = array
                .elems
                .iter()
                .map(|elem| inline_visible_value_calls(ctx, elem, depth + 1))
                .collect::<Option<Vec<_>>>()?
                .into_iter()
                .collect();
            Some(Expr::Array(out))
        }
        Expr::Tuple(tuple) => {
            let mut out = tuple.clone();
            out.elems = tuple
                .elems
                .iter()
                .map(|elem| inline_visible_value_calls(ctx, elem, depth + 1))
                .collect::<Option<Vec<_>>>()?
                .into_iter()
                .collect();
            Some(Expr::Tuple(out))
        }
        Expr::Field(field) => {
            let mut out = field.clone();
            out.base = Box::new(inline_visible_value_calls(ctx, &field.base, depth + 1)?);
            Some(Expr::Field(out))
        }
        Expr::MethodCall(call) => {
            let mut out = call.clone();
            out.receiver = Box::new(inline_visible_value_calls(ctx, &call.receiver, depth + 1)?);
            out.args = call
                .args
                .iter()
                .map(|arg| inline_visible_value_calls(ctx, arg, depth + 1))
                .collect::<Option<Vec<_>>>()?
                .into_iter()
                .collect();
            Some(Expr::MethodCall(out))
        }
        _ => Some(expr.clone()),
    }
}

/// The source-support key of a value call, peeling `Paren`/`Group`.
/// Free functions use `f`; associated impl functions use `Type::f`, matching the
/// impl method registry's identity so support records cannot collide on bare
/// method names like `new` / `get`.
fn value_call_support_key(func: &Expr) -> Option<String> {
    let inner = match func {
        Expr::Paren(p) => &*p.expr,
        Expr::Group(g) => &*g.expr,
        other => other,
    };
    let Expr::Path(path) = inner else { return None };
    if path.qself.is_some() {
        return None;
    }
    if let Some(ident) = path.path.get_ident() {
        return Some(ident.to_string());
    }
    let (self_ty, name) = assoc_call_key(&path.path)?;
    Some(format!("{self_ty}::{name}"))
}

/// Fragment-taking wrapper for `type_id_of_call_decision`. All `as_expr()` and raw
/// `Expr::` access lives HERE -- outside the `recognize` body -- so the `recognize`
/// body stays clean (ratchet-excluded per Phase-3 migration).
fn frag_type_id_decision(frag: &SourceFragment) -> Option<Result<(), String>> {
    let expr = frag.as_expr()?;
    let Expr::Call(call) = expr else {
        return None;
    };
    type_id_of_call_decision(&call.func, call.args.len())
}

/// Fragment-taking wrapper for `type_id_of_call_term`. All `as_expr()` and raw
/// `Expr::` access lives HERE -- outside the `recognize` body -- so the `recognize`
/// body stays clean (ratchet-excluded per Phase-3 migration).
/// Returns `Result<_, String>` matching `type_id_of_call_term`'s signature.
fn frag_type_id_term(frag: &SourceFragment) -> Result<Option<Rc<Term>>, String> {
    let expr = frag
        .as_expr()
        .expect("frag_type_id_term: non-expr fragment");
    let Expr::Call(call) = expr else {
        panic!("frag_type_id_term: not a Call fragment")
    };
    type_id_of_call_term(&call.func, call.args.len())
}

/// TERM recognizer for `Expr::Call`. Mirrors the source-of-truth arm in order: the
/// `TypeId::of` const-fold preamble FIRST (a resolved term, or a construction gap on
/// malformed syntax), then the constructive `call:<head>` ctor over the arg children
/// ([`CallSugar`]).
///
/// MIGRATION STATUS (Phase-3 ratchet -- FULLY MIGRATED).
///   * Signature: `&SourceFragment` (not raw `&Expr`).
///   * Body: zero `as_expr()`/`as_stmt()`/`as_item()` calls; zero raw `Expr::`/`Stmt::`/
///     `Item::` matches. Raw-syn access lives in the private helpers above and in
///     `factory.rs::SugarBody::term_frag` (both ratchet-excluded).
///   * `CallSugar` struct holds `SugarBody<TermFloor>` children and a `String` head key;
///     no raw `syn` in the struct.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.observed() != "Call" {
        return None;
    }
    if frag_type_id_decision(frag).is_some() {
        return Some(match frag_type_id_term(frag) {
            Ok(Some(term)) => resolved_term(term),
            Ok(None) => {
                panic!("TypeId::of call did not resolve; write more Sugar for this AST")
            }
            Err(reason) => {
                panic!(
                    "TypeId::of call is not structurally constructible: {reason}; write more Sugar for this AST"
                )
            }
        });
    }
    Some(Box::new(CallSugar::Constructive {
        head_key: frag
            .call_head_key()
            .expect("recognize: Call fragment has no head key"),
        args: frag
            .call_args()
            .iter()
            .map(|arg| SugarBody::term_frag(arg, fcx))
            .collect(),
    }))
}

/// A free-function call `f(a, b, ...)` in term position, composed as a node whose
/// `desugar` emits the `call:<head>` ctor over its argument child terms (the
/// constructive tail of the `Expr::Call` arm). See the module header.
pub(crate) enum CallSugar {
    Constructive {
        head_key: String,
        args: Vec<SugarBody<TermFloor>>,
    },
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
    /// `Expr::Call` arm, byte-identical. A child that `Incomplete`s a named boundary
    /// propagates that `Incomplete` verbatim; a child
    /// that completes to a non-term `Desugared` is an impossible construction state and
    /// panics loudly.
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self {
            CallSugar::Constructive { head_key, args } => {
                let mut terms = Vec::new();
                for arg in args {
                    let term = match arg.reduce(ctx) {
                        Outcome::Complete(d) => match d.into_term() {
                            Some(t) => t,
                            None => {
                                panic!(
                                    "call `{}` argument completed a non-Term where a Term was required; write more Sugar for this AST",
                                    head_key
                                );
                            }
                        },
                        Outcome::Incomplete(e) => return Outcome::Incomplete(e),
                    };
                    terms.push(term);
                }
                if terms.len() == 1 {
                    if let Some(term) = fold_char_from_u32_call(head_key, &terms[0]) {
                        return Outcome::Complete(Desugared::Term(term));
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
                    if let Some(arith_op) = arith_trait_method_op(head_key) {
                        let folded = Rc::new(Term::Ctor {
                            name: arith_op.to_string(),
                            args: terms.clone(),
                        });
                        if let Some(value) = const_fold_u128_term(&folded) {
                            return Outcome::Complete(Desugared::Term(u128_term(value)));
                        }
                        if let Some(value) = const_fold_int_term(&folded) {
                            return Outcome::Complete(Desugared::Term(num(value)));
                        }
                    }
                }
                Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
                    name: format!("call:{head_key}"),
                    args: terms,
                })))
            }
        }
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
        "from_u32" | "char::from_u32" | "core::char::from_u32" | "std::char::from_u32"
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
    // `CallSugar` is the CONSTRUCTIVE composer: given a captured function-head key
    // and typed argument bodies, it emits the `call:<head>` ctor over the child terms.
    // These tests exercise that constructive tail directly through the real factory
    // path, asserting the exact emitted ctor (name + args order) and verbatim child
    // `Incomplete` propagation.
    //
    // `from_src_*` tests exercise the Phase-3 migrated `recognize` path:
    //   source -> SourceFragment -> observed -> recognize -> reduce -> floor.
    // No parse_quote!, no StubTerm, no run().
    use super::*;
    use crate::{
        expr_head_key, sugar_ctx, Desugared, Effect, FloatWidthScope, LiftOptions, Outcome,
        ReductionCtx, Sugar, TemporalPlan, TemporalScope,
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

    fn effect_body(reason: &'static str) -> SugarBody<TermFloor> {
        struct ChildEffect {
            reason: &'static str,
        }

        impl Sugar for ChildEffect {
            fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
                Outcome::Incomplete(Effect::AmbiguousTemporalIdentity {
                    reason: self.reason.to_string(),
                })
            }
        }

        SugarBody::from_node(Box::new(ChildEffect { reason }))
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
        let node = CallSugar::Constructive {
            head_key: "f".to_string(),
            args: vec![term_body("x"), term_body("y")],
        };
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
        let node = CallSugar::Constructive {
            head_key: "g".to_string(),
            args: Vec::new(),
        };
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
    fn imported_from_u32_folds_to_char_option() {
        let node = CallSugar::Constructive {
            head_key: "from_u32".to_string(),
            args: vec![term_body("97")],
        };
        let Outcome::Complete(Desugared::Term(term)) = run(&node) else {
            panic!("expected a Complete term");
        };
        match term.as_ref() {
            Term::Ctor { name, args } => {
                assert_eq!(name, "opt:some");
                assert_eq!(args.len(), 1);
                match args[0].as_ref() {
                    Term::Const {
                        value: sugar_ir_symbolic::ConstValue::String(value),
                        ..
                    } => assert_eq!(value, "a"),
                    other => panic!("expected char string payload, got {other:?}"),
                }
            }
            other => panic!("expected Option ctor, got {other:?}"),
        }
    }

    #[test]
    fn head_key_computed_from_func_expr() {
        // `from_func` is the construction-time adapter that turns syntax into the
        // stable head key. `desugar` never retains or reopens the raw function expr.
        let func = expr("h");
        let node = CallSugar::Constructive {
            head_key: expr_head_key(&func),
            args: vec![term_body("a")],
        };
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
        // A child that returns Incomplete aborts the whole node with that SAME
        // `Incomplete`; call sugar owns no effects of its own.
        let node = CallSugar::Constructive {
            head_key: "f".to_string(),
            args: vec![term_body("x"), effect_body("synthetic child effect")],
        };
        match run(&node) {
            Outcome::Incomplete(effect) => {
                let reason = effect.reason();
                assert!(
                    reason.contains("synthetic child effect"),
                    "unexpected reason: {reason}"
                );
            }
            Outcome::Complete(_) => {
                panic!("expected the child's Incomplete to propagate, got a Complete")
            }
        }
    }

    // -----------------------------------------------------------------------
    // Phase-3 from_src tests: source -> SourceFragment -> recognize -> floor
    // -----------------------------------------------------------------------

    /// Positive: `g(x, y)` -> recognized as Call -> `Ctor { name: "call:g", args: [Var("x"), Var("y")] }`.
    #[test]
    fn from_src_call_recognizes_and_emits_call_ctor() {
        use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
        use std::collections::BTreeMap;

        let src = "fn test() { g(x, y) }";
        let file = parse_file(src);
        let item = &file.items[0];
        let item_frag = SourceFragment::from_node(FragNode::Item(item), "test.rs");
        let body = item_frag.function_body().expect("function body");
        let call_frag = body.statements()[0].terms()[0];

        // observed: the fragment reports the Call grammar shape
        assert_eq!(call_frag.observed(), "Call");

        // head key via typed accessor (no as_expr in recognize body)
        assert_eq!(call_frag.call_head_key(), Some("g".to_string()));
        assert_eq!(call_frag.call_arg_count(), 2);

        // build: recognize via fragment accessors only
        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &syn::Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let sugar = recognize(&call_frag, &fcx).expect("recognize must claim Call");

        // floor: `call:g` ctor with args in source order
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut fw = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut fw, 0);
        let Outcome::Complete(Desugared::Term(term)) = sugar.desugar(&ctx) else {
            panic!("expected Complete Term from recognize path");
        };
        match &*term {
            Term::Ctor { name, args } => {
                assert_eq!(name, "call:g", "ctor name must be `call:<head>`");
                assert_eq!(args.len(), 2, "two positional args");
                let arg_names: Vec<_> = args
                    .iter()
                    .map(|a| match &**a {
                        Term::Var { name } => name.clone(),
                        other => panic!("expected Var arg, got {other:?}"),
                    })
                    .collect();
                assert_eq!(arg_names, vec!["x", "y"], "args must be in source order");
            }
            other => panic!("expected Ctor, got {other:?}"),
        }
    }

    /// Discrimination: a `BinOp` fragment must not be claimed by `call::recognize`.
    #[test]
    fn from_src_non_call_returns_none() {
        use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
        use std::collections::BTreeMap;

        let src = "fn test() { a + b }";
        let file = parse_file(src);
        let item = &file.items[0];
        let item_frag = SourceFragment::from_node(FragNode::Item(item), "test.rs");
        let body = item_frag.function_body().expect("function body");
        let binop_frag = body.statements()[0].terms()[0];

        assert_eq!(binop_frag.observed(), "BinOp");

        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &syn::Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        assert!(
            recognize(&binop_frag, &fcx).is_none(),
            "BinOp must not be claimed by call::recognize"
        );
    }

    /// Structural: an associated-function call `Foo::bar()` emits `call:Foo::bar`
    /// with an empty arg list, and `call_head_key` includes the full type-qualified name.
    #[test]
    fn from_src_assoc_call_head_key_includes_type_prefix() {
        use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
        use std::collections::BTreeMap;

        let src = "fn test() { Foo::bar() }";
        let file = parse_file(src);
        let item = &file.items[0];
        let item_frag = SourceFragment::from_node(FragNode::Item(item), "test.rs");
        let body = item_frag.function_body().expect("function body");
        let call_frag = body.statements()[0].terms()[0];

        assert_eq!(call_frag.observed(), "Call");
        assert_eq!(call_frag.call_head_key(), Some("Foo::bar".to_string()));
        assert_eq!(call_frag.call_arg_count(), 0);

        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &syn::Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let sugar = recognize(&call_frag, &fcx).expect("recognize must claim Call");

        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut fw = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut fw, 0);
        let Outcome::Complete(Desugared::Term(term)) = sugar.desugar(&ctx) else {
            panic!("expected Complete Term");
        };
        match &*term {
            Term::Ctor { name, args } => {
                assert_eq!(name, "call:Foo::bar", "qualified name in ctor");
                assert!(args.is_empty(), "nullary call emits empty args");
            }
            other => panic!("expected Ctor, got {other:?}"),
        }
    }
}
