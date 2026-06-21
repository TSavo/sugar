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
// chain `.assume_init()` over `MaybeUninit::new(<lit>)`.  No other Primary
// Term recognizer in the catalog fires on that exact shape, so the priority
// cannot collide (#2308 trap).

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::{strip_refs_groups, Outcome, Sugar, SugarCtx};
use syn::{Expr, UnOp};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "maybe_uninit_new",
    SugarRole::Term,
    SugarPriority::Primary,
    recognize,
);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Outer must be `.assume_init()` with no extra arguments.
    let Expr::MethodCall(outer) = expr else {
        return None;
    };
    if outer.method != "assume_init" || !outer.args.is_empty() {
        return None;
    }
    // Receiver must be `MaybeUninit::new(<const-eval literal>)`.
    let inner_lit = maybe_uninit_new_literal(&outer.receiver)?;
    Some(Box::new(AssumeInitLiteralSugar {
        inner: build_term(inner_lit, fcx),
    }))
}

/// Return the literal argument of `MaybeUninit::new(<lit>)`, or `None`.
///
/// Accepts `MaybeUninit::new(7)` and the turbofish form
/// `MaybeUninit::<u32>::new(7)` (type args on the type segment are ignored;
/// we only require the last two path segments to be `MaybeUninit` + `new`).
fn maybe_uninit_new_literal(expr: &Expr) -> Option<&Expr> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.args.len() != 1 {
        return None;
    }
    if !is_maybe_uninit_new_func(&call.func) {
        return None;
    }
    let arg = &call.args[0];
    is_const_eval_literal(arg).then_some(arg)
}

/// `MaybeUninit::new` path: two or more segments, last is `new`,
/// second-to-last is `MaybeUninit` (any type arguments on either segment are
/// allowed — we check only the identifiers).
fn is_maybe_uninit_new_func(func: &Expr) -> bool {
    let Expr::Path(path_expr) = strip_refs_groups(func) else {
        return false;
    };
    if path_expr.qself.is_some() {
        return false;
    }
    let segs = &path_expr.path.segments;
    if segs.len() < 2 {
        return false;
    }
    let mut rev = segs.iter().rev();
    let last = rev.next().unwrap();
    let second_last = rev.next().unwrap();
    last.ident == "new" && second_last.ident == "MaybeUninit"
}

/// A source-text const-eval literal: an integer / float / bool / char / string /
/// byte-string literal, or a negated integer/float literal (`-7`).  Does NOT
/// include paths to named consts, function calls, or any runtime expression.
fn is_const_eval_literal(expr: &Expr) -> bool {
    match expr {
        Expr::Lit(_) => true,
        Expr::Unary(u) => matches!(u.op, UnOp::Neg(_)) && matches!(*u.expr, Expr::Lit(_)),
        _ => false,
    }
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
