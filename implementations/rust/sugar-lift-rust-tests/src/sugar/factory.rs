// SPDX-License-Identifier: Apache-2.0
//
//! The recursive Sugar factory (`SugarFactory`): **AST node in, Sugar out.**
//!
//! `build(expr) -> Box<dyn Sugar>` is the ONE named, TOTAL, recursive entry that
//! lifts an expression's TERM SUBLANGUAGE — it IS the former
//! `translate_term_in_scope` 30-arm `match`, relocated arm-for-arm into the factory
//! so the dispatch lives in ONE place and nothing falls back to a legacy match.
//! `translate_term_in_scope` survives only as a THIN ADAPTER over `build`
//! (`build(expr, &fcx).desugar(&ctx).into_term()`); the fat match no longer exists
//! anywhere except here.
//!
//! ## The three laws
//!
//! 1. **TOTAL.** Every `Expr` maps to *some* `Box<dyn Sugar>`. A term shape with no
//!    constructible value becomes a reasoned leaf — a [`ReasonedHitSugar`] carrying
//!    the arm's EXACT refusal string, or [`UnsupportedSugar`] for the bare structural
//!    backstop — NEVER a silent skip. `build` cannot return `None`.
//! 2. **RECURSIVE.** A composite term node builds each operand with `build(child)` and
//!    composes the child Sugar; transparent wrappers (`Paren`/`Group`) recurse
//!    straight through. `desugar` then collapses the whole tree inside-out, reading
//!    each child's `Term` back out through `Desugared::into_term`.
//! 3. **NEVER DECIDE EARLY (the sin).** `build` only *recognizes and news*; degeneracy
//!    is a LEAF property (`Lit` → `Dug`; `&mut x` / raw pointer / mut-local macro →
//!    `Hit`) that propagates for free through compose-and-propagate composites.
//!
//! ## Term arms and the seven nodes
//!
//! The constructive composites reuse the seven term nodes in `src/sugar/`:
//! `CompareSugar` (a `cmp:*` comparison), `BinOpSugar` (an arithmetic op), `CallSugar`
//! (a free `f(..)` call), `IndexSugar` (a general `a[i]`), `PathSugar` (a name read),
//! `UnarySugar` (`-x`/`!x`/`*p`), `TermLiteralSugar` (a scalar literal). The remaining
//! arms build their `Term::Ctor` through small inline thin nodes ([`CtorSugar`] for a
//! named ctor over child terms; [`ResolvedTermSugar`]/[`ReasonedHitSugar`] for an
//! arm whose preamble already computed a term / a refusal). Each arm preserves its
//! source-of-truth ctor name, arg order, preamble order, and refusal STRINGS exactly.
//!
//! ## The composite/statement dispatch
//!
//! [`build_composite`] is the DISTINCT dispatch the collector's statement / sequence
//! sites consume via `.dug()` — a `ForLoop`/`If`/`Match` statement, a `fold`/`for_each`
//! quantifier terminal, a literal-array sequence floor. It is NOT the term lifter (an
//! `Expr::Array` there is the SEQUENCE floor `Seq`, not the `literal_aggregate` Term;
//! a `MethodCall` there is the `FoldSugar`/`ForEachSugar` composite, not the `method:`
//! ctor). The two roles genuinely differ for `Array`/`Repeat`/`MethodCall`, so they
//! are two entries sharing the node library — never one function serving both.

use std::collections::{BTreeMap, BTreeSet};
use std::rc::Rc;

use sugar_ir_symbolic::{make_var, num, str_const, Term};
use syn::{Expr, Pat, Stmt};

use crate::sugar::array_repeat::decompose_array_repeat;
use crate::sugar::binop::BinOpSugar;
use crate::sugar::call::CallSugar;
use crate::sugar::closure_adaptor::decompose_closure_adaptor;
use crate::sugar::compare::CompareSugar;
use crate::sugar::conditional::decompose_if;
use crate::sugar::control_flow_term::decompose_control_flow_term;
use crate::sugar::fold::decompose_fold;
use crate::sugar::forall::{decompose_for_each, decompose_for_loop};
use crate::sugar::index::IndexSugar;
use crate::sugar::literal::LiteralSugar;
use crate::sugar::match_node::decompose_match;
use crate::sugar::match_scrutinee::decompose_match_scrutinee;
use crate::sugar::path::PathSugar;
use crate::sugar::temporal_read::decompose_temporal_read;
use crate::sugar::term_leaf::{ReasonedHitSugar, ResolvedTermSugar};
use crate::sugar::term_literal::TermLiteralSugar;
use crate::sugar::unary::UnarySugar;
use crate::sugar::format as format_mod;
use crate::try_fold_eval;
use crate::{
    angle_args_key, bool_const, closure_adaptor_refusal, const_eval, const_index_term_in_scope,
    is_consuming_iterator_method, is_immutable_value_expr, is_shared_dyn_any_type,
    is_unqualified_local_name, literal_aggregate_term_in_scope, macro_literal_contains_mut_local,
    names_referenced_in_expr, path_to_variant_string, receiver_is_versioned_iterator,
    relation_from_binop, repeat_count_literal, scalar_cast_type_key, scope_const_block_locals,
    term_binop_name, token_key, translate_expression_only_block_in_scope, type_key,
    type_id_of_call_term, ConstVal, Desugared, Effect, LiftOptions, Outcome, Sugar, SugarCtx,
    TemporalScope, UnsupportedTermCause,
};

/// What `build` needs from its environment to construct a node: the temporal
/// `scope` (binding / mutability oracle), the lift `options`, and the in-scope
/// `let` initializers (`name -> &init_expr`) that binding-resolving decomposers
/// (`fold`, `for_each`, `closure_adaptor`) capture. This is the BUILD-time env;
/// the dual [`SugarCtx`] is the DESUGAR-time env. Bundled so the recursive arms
/// stay terse — `build(child, fcx)`.
pub(crate) struct FactoryCtx<'a, 'e> {
    pub(crate) scope: &'a TemporalScope,
    pub(crate) options: &'a LiftOptions,
    pub(crate) let_inits: &'a BTreeMap<String, &'e Expr>,
}

/// The recursive Sugar factory and COMPLETE TERM LIFTER: an `Expr` in, a
/// `Box<dyn Sugar>` out whose `desugar(&ctx).into_term()` is the `Rc<Term>` the
/// former `translate_term_in_scope` arm for that shape produced (byte-identical
/// ctor names / arg order / refusal strings). TOTAL — every shape news a node
/// (a reasoned leaf for the no-value shapes). RECURSIVE — composite term nodes
/// build their operands with `build`. NEVER decides the walk early.
pub(crate) fn build(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    let scope = fcx.scope;
    match expr {
        // Expr::Lit(lit) => translate_lit(lit)
        Expr::Lit(lit) => Box::new(TermLiteralSugar { lit: lit.clone() }),

        // `const { EXPR }`: a bare-path const block is a NAME (sugar) -> reasoned Hit;
        // a computed const block translates its expression-only tail and scopes locals.
        Expr::Const(const_block) => {
            if let [Stmt::Expr(Expr::Path(_), None)] = const_block.block.stmts.as_slice() {
                let effect =
                    Effect::unsupported_term(&token_key(expr), UnsupportedTermCause::ConstBlockPath);
                return reasoned_hit(effect.reason());
            }
            match translate_expression_only_block_in_scope(&const_block.block, "const", scope) {
                Ok(term) => resolved_term(scope_const_block_locals(term, scope.local_scope())),
                Err(reason) => reasoned_hit(reason),
            }
        }

        // Unary: the three `syn::UnOp` arms (`-x` fold-or-`0 - x`, `!x` bit-not, `*p`
        // deref). `UnarySugar` owns the Neg literal fast-paths + the child recursion;
        // the factory hands it the op, the operand expr, the whole expr (for token_key),
        // and the child Sugar built from the operand.
        Expr::Unary(unary) => Box::new(UnarySugar {
            op: unary.op,
            operand: (*unary.expr).clone(),
            whole: expr.clone(),
            inner: build(&unary.expr, fcx),
        }),

        // Expr::Path(path) if is_ident("None") => Ctor "call:None" []
        Expr::Path(path) if path.path.is_ident("None") => resolved_term(Rc::new(Term::Ctor {
            name: "call:None".to_string(),
            args: Vec::new(),
        })),
        // Expr::Path(path) => make_var(scope.path_name(&path.path)?)
        Expr::Path(path) => Box::new(PathSugar { path: path.clone() }),

        // Expr::Call: TypeId::of preamble, then the `call:<head>` ctor over arg children.
        Expr::Call(call) => {
            match type_id_of_call_term(&call.func, call.args.len()) {
                Ok(Some(term)) => return resolved_term(term),
                Ok(None) => {}
                Err(reason) => return reasoned_hit(reason),
            }
            let args = call.args.iter().map(|arg| build(arg, fcx)).collect();
            Box::new(CallSugar::from_func(&call.func, args))
        }

        // Expr::Array / Expr::Tuple => literal_aggregate_term("Array"/"Tuple", elems)
        Expr::Array(array) => {
            match literal_aggregate_term_in_scope("Array", array.elems.iter(), expr, scope) {
                Ok(term) => resolved_term(term),
                Err(reason) => reasoned_hit(reason),
            }
        }
        Expr::Tuple(tuple) => {
            match literal_aggregate_term_in_scope("Tuple", tuple.elems.iter(), expr, scope) {
                Ok(term) => resolved_term(term),
                Err(reason) => reasoned_hit(reason),
            }
        }

        // Expr::Repeat `[elem; N]`: a literal count expands to the N-fold aggregate; a
        // non-literal count is the `ArrayRepeatSugar` refuse-shape (Effect::ArrayRepeat).
        Expr::Repeat(repeat) => {
            let Some(count) = repeat_count_literal(&repeat.len) else {
                return match decompose_array_repeat(expr) {
                    Some(node) => match node.desugar_ctx_free() {
                        Outcome::Hit(effect @ Effect::ArrayRepeat { .. }) => {
                            reasoned_hit(effect.reason())
                        }
                        _ => reasoned_hit(format!("unsupported term `{}`", token_key(expr))),
                    },
                    None => reasoned_hit(format!("unsupported term `{}`", token_key(expr))),
                };
            };
            const MAX_REPEAT: usize = 4096;
            if count > MAX_REPEAT {
                return reasoned_hit(format!(
                    "array-repeat length {count} exceeds the {MAX_REPEAT}-element \
                     expansion bound; refused by name: `{}`",
                    token_key(expr)
                ));
            }
            let elem_refs = std::iter::repeat(&*repeat.expr).take(count);
            match literal_aggregate_term_in_scope("Array", elem_refs, expr, scope) {
                Ok(term) => resolved_term(term),
                Err(reason) => reasoned_hit(reason),
            }
        }

        // Expr::Struct: a constructor `struct:<path>` with sorted `field:<name>` subctors.
        Expr::Struct(s) => {
            if s.rest.is_some() {
                return reasoned_hit(format!(
                    "struct literal with `..rest` is not fully pinned from the literal: `{}`",
                    token_key(expr)
                ));
            }
            let mut fields: Vec<(String, Box<dyn Sugar>)> = Vec::new();
            for fv in &s.fields {
                let fname = match &fv.member {
                    syn::Member::Named(id) => id.to_string(),
                    syn::Member::Unnamed(idx) => idx.index.to_string(),
                };
                fields.push((fname, build(&fv.expr, fcx)));
            }
            fields.sort_by(|a, b| a.0.cmp(&b.0));
            let field_ctors: Vec<Box<dyn Sugar>> = fields
                .into_iter()
                .map(|(fname, child)| {
                    Box::new(CtorSugar::new(format!("field:{fname}"), vec![child])) as Box<dyn Sugar>
                })
                .collect();
            Box::new(CtorSugar::new(
                format!("struct:{}", path_to_variant_string(&s.path)),
                field_ctors,
            ))
        }

        // Expr::MethodCall: the try_fold/format/closure-adaptor preamble, the
        // per-occurrence iterator-advance receiver tagging, then `method:<m>` over
        // [receiver, args..].
        Expr::MethodCall(call) => build_method_call_term(expr, call, fcx),

        // Expr::Await => Ctor "await" [base]
        Expr::Await(await_expr) => {
            Box::new(CtorSugar::new("await", vec![build(&await_expr.base, fcx)]))
        }

        // Expr::Reference: `&x` => ref; `&mut <immutable value>` => ref_mut; other
        // `&mut <place>` => reasoned Hit (mutable reference).
        Expr::Reference(reference) if reference.mutability.is_none() => {
            Box::new(CtorSugar::new("ref", vec![build(&reference.expr, fcx)]))
        }
        Expr::Reference(reference) if is_immutable_value_expr(&reference.expr) => {
            Box::new(CtorSugar::new("ref_mut", vec![build(&reference.expr, fcx)]))
        }
        Expr::Reference(reference) if reference.mutability.is_some() => {
            let effect = Effect::unsupported_term(
                &token_key(expr),
                UnsupportedTermCause::MutableReference,
            );
            reasoned_hit(effect.reason())
        }

        // Expr::RawAddr => reasoned Hit (raw pointer).
        Expr::RawAddr(_) => {
            let effect =
                Effect::unsupported_term(&token_key(expr), UnsupportedTermCause::RawPointer);
            reasoned_hit(effect.reason())
        }

        // Expr::Cast: a shared `dyn Any` cast or a scalar cast => `cast:<T>` over child;
        // otherwise reasoned Hit.
        Expr::Cast(cast) => {
            if is_shared_dyn_any_type(&cast.ty) {
                return Box::new(CtorSugar::new(
                    format!("cast:{}", type_key(&cast.ty)),
                    vec![build(&cast.expr, fcx)],
                ));
            }
            if let Some(cast_type) = scalar_cast_type_key(&cast.ty) {
                return Box::new(CtorSugar::new(
                    format!("cast:{cast_type}"),
                    vec![build(&cast.expr, fcx)],
                ));
            }
            reasoned_hit(format!("unsupported term `{}`", token_key(expr)))
        }

        // Expr::Range: `range`/`range_incl` over start (or 0) and end (or range_end_len).
        Expr::Range(range) => {
            let start: Box<dyn Sugar> = match &range.start {
                Some(expr) => build(expr, fcx),
                None => resolved_term(num(0)),
            };
            let end: Box<dyn Sugar> = match &range.end {
                Some(expr) => build(expr, fcx),
                None => resolved_term(make_var("range_end_len")),
            };
            let name = match range.limits {
                syn::RangeLimits::HalfOpen(_) => "range",
                syn::RangeLimits::Closed(_) => "range_incl",
            };
            Box::new(CtorSugar::new(name, vec![start, end]))
        }

        // Expr::Field => Ctor "field:<member>" [base]
        Expr::Field(field) => Box::new(CtorSugar::new(
            format!("field:{}", token_key(&field.member)),
            vec![build(&field.base, fcx)],
        )),

        // Expr::Index: const-index preamble, then the temporal-read refuse-shape, then
        // the general `index` ctor over [container, idx].
        Expr::Index(index) => {
            match const_index_term_in_scope(index, scope) {
                Ok(Some(term)) => return resolved_term(term),
                Ok(None) => {}
                Err(reason) => return reasoned_hit(reason),
            }
            if let Some(node) = decompose_temporal_read(expr, scope) {
                if let Outcome::Hit(effect @ Effect::TemporalRead { .. }) = node.desugar_ctx_free() {
                    return reasoned_hit(effect.reason());
                }
            }
            Box::new(IndexSugar::new(
                build(&index.expr, fcx),
                build(&index.index, fcx),
            ))
        }

        // Expr::Binary: the FormatSugar string-`+` hook, the comparison branch
        // (const-fold to Bool, else `cmp:*` ctor), then the arithmetic-op ctor (or the
        // op-name `None` "unsupported term operator" refusal).
        Expr::Binary(binary) => {
            if matches!(binary.op, syn::BinOp::Add(_)) {
                let stable = stable_let_bindings(scope);
                match format_mod::try_resolve_format(expr, &stable) {
                    Ok(Some(s)) => return resolved_term(str_const(s)),
                    Err(reason) => return reasoned_hit(reason),
                    Ok(None) => {}
                }
            }
            if let Some(rel) = relation_from_binop(&binary.op) {
                if let Some(ConstVal::Bool(b)) = const_eval(expr, &BTreeMap::new()) {
                    return resolved_term(bool_const(b));
                }
                return Box::new(CompareSugar {
                    left: build(&binary.left, fcx),
                    right: build(&binary.right, fcx),
                    rel,
                });
            }
            let Some(op) = term_binop_name(&binary.op) else {
                return reasoned_hit(format!(
                    "unsupported term operator `{}`",
                    token_key(expr)
                ));
            };
            Box::new(BinOpSugar {
                left: build(&binary.left, fcx),
                right: build(&binary.right, fcx),
                op_name: op,
            })
        }

        // Transparent wrappers: recurse straight through.
        Expr::Paren(paren) => build(&paren.expr, fcx),
        Expr::Group(group) => build(&group.expr, fcx),

        // Expr::Macro: the FormatSugar dig, the mut-local temporal-instability refusal,
        // then the opaque `macro:<tokens>` EUF var.
        Expr::Macro(m) => {
            let seg = m.mac.path.segments.last().map(|s| s.ident.to_string());
            if matches!(seg.as_deref(), Some("format") | Some("concat")) {
                let stable = stable_let_bindings(scope);
                match format_mod::try_resolve_format(expr, &stable) {
                    Ok(Some(s)) => return resolved_term(str_const(s)),
                    Err(reason) => return reasoned_hit(reason),
                    Ok(None) => {}
                }
            }
            let token_str = token_key(expr);
            let contains_mut_local = m.mac.tokens.clone().into_iter().any(|tt| match &tt {
                proc_macro2::TokenTree::Ident(id) => scope.is_mut_local(&id.to_string()),
                proc_macro2::TokenTree::Literal(lit) => {
                    let text = lit.to_string();
                    macro_literal_contains_mut_local(&text, scope)
                }
                _ => false,
            });
            if contains_mut_local {
                return reasoned_hit(format!(
                    "macro in term position references a `let mut` local; \
                     temporally unstable — refused: `{token_str}`"
                ));
            }
            resolved_term(make_var(format!("macro:{token_str}")))
        }

        // Expr::Closure: an opaque `closure:<body>` EUF symbol keyed by its body text +
        // the version-aware terms of its captured free vars; an ambiguous capture refuses.
        Expr::Closure(closure) => {
            let params: BTreeSet<String> = closure
                .inputs
                .iter()
                .filter_map(|p| match p {
                    Pat::Ident(id) => Some(id.ident.to_string()),
                    Pat::Type(t) => match &*t.pat {
                        Pat::Ident(id) => Some(id.ident.to_string()),
                        _ => None,
                    },
                    _ => None,
                })
                .collect();
            let mut args = Vec::new();
            for name in names_referenced_in_expr(&closure.body) {
                if params.contains(&name) {
                    continue;
                }
                if is_unqualified_local_name(&name) && scope.plan_versioned_contains(&name) {
                    if scope.ambiguous_contains(&name) {
                        return reasoned_hit(format!(
                            "closure captures ambiguous local `{name}`; refused"
                        ));
                    }
                    let vname = match scope.version_of(&name) {
                        Some(v) => format!("{name}@def{v}"),
                        None => name.clone(),
                    };
                    args.push(make_var(vname));
                } else {
                    args.push(make_var(name));
                }
            }
            resolved_term(Rc::new(Term::Ctor {
                name: format!("closure:{}", token_key(&closure.body)),
                args,
            }))
        }

        // VALUE-TRANSPARENT WRAPPERS: a single-tail `unsafe { expr }` / `{ expr }` block
        // is the value of its tail; any other block shape is refused by name.
        Expr::Unsafe(block) => match block.block.stmts.as_slice() {
            [Stmt::Expr(tail, None)] => build(tail, fcx),
            _ => reasoned_hit(format!("unsupported term `{}`", token_key(expr))),
        },
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [Stmt::Expr(tail, None)] => build(tail, fcx),
            _ => reasoned_hit(format!("unsupported term `{}`", token_key(expr))),
        },

        // Effectful control-flow (`try`/`async`/`?`): the `ControlFlowTermSugar`
        // refuse-shape (Effect::ControlFlow).
        Expr::TryBlock(_) | Expr::Async(_) | Expr::Try(_) => {
            match decompose_control_flow_term(expr) {
                Some(node) => match node.desugar_ctx_free() {
                    Outcome::Hit(effect @ Effect::ControlFlow { .. }) => {
                        reasoned_hit(effect.reason())
                    }
                    _ => reasoned_hit(format!("unsupported term `{}`", token_key(expr))),
                },
                None => reasoned_hit(format!("unsupported term `{}`", token_key(expr))),
            }
        }

        // The `other => Err("unsupported term ...")` catch-all of the source-of-truth.
        other => reasoned_hit(format!("unsupported term `{}`", token_key(other))),
    }
}

/// The `Expr::MethodCall` term arm: the try_fold/format/closure-adaptor preamble, the
/// per-occurrence consuming-iterator advance receiver tagging, then the `method:<m>`
/// ctor over `[receiver, args..]`. Byte-identical to the source-of-truth arm: a folded
/// `try_fold`/`try_rfold` value re-enters `build`; a dissolved `to_string()` is a
/// `str_const`; a closure-adaptor refusal is a reasoned Hit; otherwise the EUF
/// `method:` ctor with the receiver dug FIRST and the args in source order.
fn build_method_call_term(
    expr: &Expr,
    call: &syn::ExprMethodCall,
    fcx: &FactoryCtx,
) -> Box<dyn Sugar> {
    let scope = fcx.scope;
    // CLOSED try_fold / try_rfold: ground to a literal and re-build THAT.
    if matches!(call.method.to_string().as_str(), "try_fold" | "try_rfold") {
        if let Some(grounded) = try_fold_eval::eval_try_fold_operand(expr, scope) {
            return build(&grounded, fcx);
        }
    }
    // FormatSugar: `<literal>.to_string()` dissolves to a `str_const`.
    if call.method == "to_string" && call.args.is_empty() {
        let stable = stable_let_bindings(scope);
        match format_mod::try_resolve_format(expr, &stable) {
            Ok(Some(s)) => return resolved_term(str_const(s)),
            Err(reason) => return reasoned_hit(reason),
            Ok(None) => {}
        }
    }
    // A closure-bearing adaptor in term position refuses with collection provenance.
    if let Some(reason) = closure_adaptor_refusal(expr, scope) {
        return reasoned_hit(reason);
    }
    // The constructive `method:` ctor. The RECEIVER is dug first; a per-occurrence
    // consuming-iterator advance re-tags the receiver var (`@adv{n}`). The receiver
    // term must be computed up-front here (not by a child node) because the `@adv`
    // tagging reads the dug receiver Var name; we build the receiver child, dig it
    // ctx-free is not possible, so we compute the receiver TERM via a build+adapter
    // and wrap each arg as a child for the ctor. To stay byte-identical AND keep the
    // recursion through `build`, the receiver + args are pre-resolved into terms and
    // the whole `method:` ctor is emitted as a single resolved-or-Hit node.
    Box::new(MethodCallTermSugar {
        method: method_key(call),
        receiver: build(&call.receiver, fcx),
        is_consuming: is_consuming_iterator_method(&call.method.to_string()),
        args: call.args.iter().map(|arg| build(arg, fcx)).collect(),
    })
}

/// The `method:<m>` ctor key: `method.turbofish` appends the angle-args key.
fn method_key(call: &syn::ExprMethodCall) -> String {
    match &call.turbofish {
        Some(args) => format!("{}{}", call.method, angle_args_key(args)),
        None => call.method.to_string(),
    }
}

/// The CONSTRUCTIVE method-call term node: digs the receiver child FIRST, applies the
/// per-occurrence consuming-iterator `@adv{n}` re-tag (a runtime read of `ctx.scope`),
/// then digs the arg children in source order, and emits `method:<m>` over
/// `[receiver, args..]`. Byte-identical to the source-of-truth `Expr::MethodCall`
/// constructive tail. A child `Hit` propagates verbatim; a non-term child digs to the
/// structural backstop.
struct MethodCallTermSugar {
    method: String,
    receiver: Box<dyn Sugar>,
    is_consuming: bool,
    args: Vec<Box<dyn Sugar>>,
}

impl Sugar for MethodCallTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let mut receiver = match self.receiver.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(t) => t,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        if self.is_consuming {
            if let Term::Var { name } = receiver.as_ref() {
                if receiver_is_versioned_iterator(name, ctx.scope) {
                    let occ = ctx.scope.bump_consuming_occurrence(name);
                    if occ > 0 {
                        receiver = make_var(format!("{name}@adv{occ}"));
                    }
                }
            }
        }
        let mut args = vec![receiver];
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
            name: format!("method:{}", self.method),
            args,
        })))
    }
}

/// A generic CONSTRUCTIVE named-ctor term node: digs each child to its `Term` in order
/// and emits `Term::Ctor { name, args }`. The thin node for the term arms whose ctor
/// has no dedicated node (`ref`/`ref_mut`/`deref`-not, `await`, `field:*`, `cast:*`,
/// `range`/`range_incl`, `struct:*`/`field:*` subctors). A child `Hit` propagates
/// verbatim; a non-term child digs to the structural backstop (`from_opt(None)`).
struct CtorSugar {
    name: String,
    args: Vec<Box<dyn Sugar>>,
}

impl CtorSugar {
    fn new(name: impl Into<String>, args: Vec<Box<dyn Sugar>>) -> Self {
        CtorSugar {
            name: name.into(),
            args,
        }
    }
}

impl Sugar for CtorSugar {
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
            name: self.name.clone(),
            args,
        })))
    }
}

/// The in-scope IMMUTABLE `let` bindings (`name -> init`), used by the FormatSugar
/// hooks (`a + b`, `format!`, `.to_string()`): a `let mut` is excluded so a mutated
/// operand is never mis-dissolved. Byte-identical to the inline `stable` map the
/// source-of-truth arms built from `scope.let_bindings`.
fn stable_let_bindings(scope: &TemporalScope) -> BTreeMap<String, Expr> {
    scope
        .let_bindings_iter()
        .filter(|(name, _)| !scope.is_mut_local(name))
        .map(|(name, init)| (name.clone(), init.clone()))
        .collect()
}

/// Box an already-built `Rc<Term>` as the term-floor "resolved term" leaf.
fn resolved_term(term: Rc<Term>) -> Box<dyn Sugar> {
    Box::new(ResolvedTermSugar { term })
}

/// Box a verbatim refusal string as the term-floor "reasoned-Hit" leaf.
fn reasoned_hit(reason: String) -> Box<dyn Sugar> {
    Box::new(ReasonedHitSugar { reason })
}

// ── The composite / statement dispatch (consumed by the collector via `.dug()`) ─────

/// The recursive composite / sequence factory: the statement-position dispatch the
/// collector's `.dug()` sites consume. DISTINCT from `build` (the term lifter): an
/// `Expr::Array` here is the SEQUENCE floor (`LiteralSugar` -> `Seq`), a `MethodCall`
/// is a `fold`/`for_each` quantifier or a closure-adaptor (not the `method:` ctor), an
/// `If`/`Match`/`ForLoop` is the implication / conjunction composite. Total: an
/// unowned shape becomes the structural [`UnsupportedSugar`] backstop.
pub(crate) fn build_composite(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    match expr {
        Expr::Paren(p) => build_composite(&p.expr, fcx),
        Expr::Group(g) => build_composite(&g.expr, fcx),

        Expr::If(i) => boxed(decompose_if(i)),
        Expr::Match(m) => boxed(decompose_match(m, fcx.scope, fcx.options)),
        Expr::ForLoop(f) => boxed(decompose_for_loop(f, fcx.scope, fcx.let_inits)),

        Expr::Repeat(_) => boxed(decompose_array_repeat(expr)),

        Expr::TryBlock(_) | Expr::Async(_) | Expr::Try(_) => {
            boxed(decompose_control_flow_term(expr))
        }

        Expr::Array(_) | Expr::Range(_) => Box::new(LiteralSugar { base: expr.clone() }),

        Expr::MethodCall(_) => build_method_call_composite(expr, fcx),

        _ => unsupported(),
    }
}

/// The composite method-call recognizer chain: a `fold` terminal, a `for_each`
/// quantifier, a closure-bearing adaptor, then a match-scrutinee method shape. A
/// method call matching none of these reaches the structural backstop.
fn build_method_call_composite(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    if let Some(node) = decompose_fold(expr, fcx.let_inits) {
        return Box::new(node);
    }
    if let Some(node) = decompose_for_each(expr, fcx.scope, fcx.let_inits) {
        return Box::new(node);
    }
    if let Some(node) = decompose_closure_adaptor(expr, fcx.let_inits) {
        return Box::new(node);
    }
    if let Some(node) = decompose_match_scrutinee(expr) {
        return Box::new(node);
    }
    unsupported()
}

/// Box a recognized concrete node, or fall to the structural backstop when the
/// decomposer declined (`None`).
fn boxed<S: Sugar + 'static>(node: Option<S>) -> Box<dyn Sugar> {
    match node {
        Some(node) => Box::new(node),
        None => unsupported(),
    }
}

/// The structural backstop leaf.
fn unsupported() -> Box<dyn Sugar> {
    Box::new(UnsupportedSugar)
}

/// The structural backstop: an AST shape the composite Sugar pipeline does not own.
/// `desugar` is the byte-identical legacy `None` bail (`Outcome::from_opt(None)` ->
/// `Hit(Effect::Unsupported)` carrying the structural-backstop reason), discarded by a
/// `.dug()` consumer exactly as the old `None` was.
struct UnsupportedSugar;

impl Sugar for UnsupportedSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt(None)
    }
}
