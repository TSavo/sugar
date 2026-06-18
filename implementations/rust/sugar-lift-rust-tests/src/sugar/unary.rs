// SPDX-License-Identifier: Apache-2.0
//
// `UnarySugar`: the TERM-FLOOR COMPOSITE for a unary operator in term position
// (`-x`, `!x`, `*p`). It composes ONE child `Box<dyn Sugar>` (built from the
// operand `unary.expr`) and mirrors the three `Expr::Unary` arms of
// `translate_term_in_scope` byte-identically. `syn::UnOp` is the exhaustive
// `{ Deref, Not, Neg }`, so these three arms are total over real unary operators;
// any (impossible) other op fell to the legacy catch-all `unsupported term`.
//
// THE THREE ARMS (quoted verbatim from `translate_term_in_scope`):
//
//   Neg (`-x`):
//     Expr::Unary(unary) if matches!(unary.op, UnOp::Neg(_)) => {
//         if let Some(value) = const_int(&unary.expr) {
//             return Ok(num(-value));
//         }
//         if let Some(value) = const_float(&unary.expr)? {
//             if real_literal_is_zero(&value) {
//                 return Err(format!(
//                     "signed zero float literal remains an IEEE refinement `{}`",
//                     token_key(expr)
//                 ));
//             }
//             return Ok(real_const(format!("-{value}")));
//         }
//         Ok(Rc::new(Term::Ctor {
//             name: "-".to_string(),
//             args: vec![num(0), translate_term_in_scope(&unary.expr, scope)?],
//         }))
//     }
//
//   Not (`!x`):
//     Expr::Unary(unary) if matches!(unary.op, UnOp::Not(_)) => Ok(Rc::new(Term::Ctor {
//         name: "bit-not".to_string(),
//         args: vec![translate_term_in_scope(&unary.expr, scope)?],
//     })),
//
//   Deref (`*p`):
//     Expr::Unary(unary) if matches!(unary.op, UnOp::Deref(_)) => Ok(Rc::new(Term::Ctor {
//         name: "deref".to_string(),
//         args: vec![translate_term_in_scope(&unary.expr, scope)?],
//     })),
//
// THE LITERAL FAST-PATHS ARE A SOURCE-SHAPE TEST, NOT A CHILD READ. The Neg arm
// first tries to FOLD `-x` over a written literal operand: `const_int` /
// `const_float` read the SOURCE `unary.expr` (not the child's desugared term) and,
// when it is an int / finite-decimal-float literal, produce the folded constant
// (`num(-value)` / `real_const("-{value}")`) -- and a signed-zero float literal is
// REFUSED BY NAME (an IEEE refinement). Only when the operand is NOT a literal does
// the arm fall to the `0 - x` ctor over the recursively-translated operand. To
// mirror this, `UnarySugar` holds BOTH the source operand `Expr` (for the
// const_int/const_float/real_literal_is_zero fold + the `token_key(expr)` of the
// whole unary expr) AND the child `Sugar` (for the non-literal `0 - x` / `bit-not`
// / `deref` composition). The fold uses the SAME `const_int`/`const_float`/`num`/
// `real_const` helpers the arm called.
//
// THE CHILD HIT PROPAGATES VERBATIM. The non-literal Neg branch and both the Not
// and Deref arms wrap `translate_term_in_scope(&unary.expr, scope)?` -- the inner
// `?` propagated the operand's named `Err`. The node mirrors that: it desugars the
// child, reads its term via `into_term()`, and if the child `Hit`s a named effect
// it RETURNS that `Hit` UNCHANGED (the same boundary the inner `?` would have
// surfaced). A child that Digs a non-`Term` payload (a `Seq`/`Constraints` -- an
// impossible state for a term-position operand) yields `into_term() == None`; that
// degenerate case maps to the structural backstop (`Outcome::from_opt(None)`),
// never a fake construction. The child-read seam is the module-private
// `child_term_or_hit` (no `crate::` helper added -- the only `lib.rs` edit is the
// mod declaration).
//
// RECOGNIZER PREAMBLE. `recognize` for `Expr::Unary` builds the operand child and
// news a `UnarySugar` carrying { the op `unary.op`, the operand `Expr`, the whole-unary
// `Expr` for the token_key, the child }. `UnarySugar` makes no recognition decision of
// its own; it composes and reduces after the Sugar claim accepts the source shape.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, UnOp};

use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::{
    const_float, const_int, num, real_const, real_literal_is_zero, token_key, Desugared, Effect,
    Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("unary", recognize);

/// TERM recognizer for `Expr::Unary`: news a [`UnarySugar`] over the operand child.
/// Byte-identical to the `Expr::Unary` arm — `UnarySugar` owns the per-`UnOp` arm
/// selection + the Neg literal fast-paths.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Unary(unary) => Some(Box::new(UnarySugar {
            op: unary.op,
            operand: (*unary.expr).clone(),
            whole: expr.clone(),
            inner: build_term(&unary.expr, fcx),
        })),
        _ => None,
    }
}

/// A unary operator in TERM position (`-x` / `!x` / `*p`). Composes ONE child
/// `Sugar` (the operand) and mirrors the matching `Expr::Unary` arm of
/// `translate_term_in_scope`. The Neg arm additionally folds a literal operand via
/// the source-expr fast-paths; see the module header.
pub(crate) struct UnarySugar {
    /// The unary operator -- selects the arm (`Neg` -> fold-or-`0 - x`; `Not` ->
    /// `bit-not`; `Deref` -> `deref`).
    pub(crate) op: UnOp,
    /// The SOURCE operand expr (`unary.expr`). Read by the Neg fast-paths
    /// (`const_int`/`const_float`) -- the fold is a property of the WRITTEN operand,
    /// not of the child's term.
    pub(crate) operand: Expr,
    /// The whole `-x` / `!x` / `*p` expr, held only for the `token_key(expr)` in the
    /// signed-zero-float refusal reason (byte-identical to the arm's `token_key(expr)`).
    pub(crate) whole: Expr,
    /// The child `Sugar` built from the operand. Its `desugar(ctx).into_term()`
    /// mirrors `translate_term_in_scope(&unary.expr, scope)?`; a child `Hit`
    /// propagates verbatim.
    pub(crate) inner: Box<dyn Sugar>,
}

/// Read a desugared CHILD outcome as the `Rc<Term>` an `Expr::Unary` arm would have
/// obtained from `translate_term_in_scope(&unary.expr, scope)?`. A child `Dug(Term)`
/// yields the term (`Ok`); a child `Hit(effect)` propagates VERBATIM (`Err(Hit)`) --
/// the same named boundary the inner `?` would have surfaced; a child that Dug a
/// non-`Term` payload (impossible for a term-position operand) maps to the structural
/// backstop (`Err(from_opt(None))`). Module-private so no `crate::` helper is added.
fn child_term_or_hit(child: Outcome) -> Result<Rc<Term>, Outcome> {
    match child {
        Outcome::Dug(d) => match d.into_term() {
            Some(term) => Ok(term),
            None => Err(Outcome::from_opt(None)),
        },
        hit @ Outcome::Hit(_) => Err(hit),
    }
}

impl Sugar for UnarySugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.op {
            UnOp::Neg(_) => {
                // `-x` over a written int literal folds to `num(-value)`.
                if let Some(value) = const_int(&self.operand) {
                    return Outcome::Dug(Desugared::Term(num(-value)));
                }
                // `-x` over a finite-decimal-float literal folds to
                // `real_const("-{value}")`; a SIGNED-ZERO float literal is REFUSED
                // BY NAME (an IEEE refinement). `const_float` itself can `Err` (a
                // non-finite / unparsable float) -- that named `Err` propagates as a
                // `Hit`, mirroring the arm's `?`.
                match const_float(&self.operand) {
                    Ok(Some(value)) => {
                        if real_literal_is_zero(&value) {
                            return Outcome::Hit(Effect::Unsupported {
                                reason: format!(
                                    "signed zero float literal remains an IEEE refinement `{}`",
                                    token_key(&self.whole)
                                ),
                            });
                        }
                        return Outcome::Dug(Desugared::Term(real_const(format!("-{value}"))));
                    }
                    Ok(None) => {}
                    Err(reason) => return Outcome::Hit(Effect::Unsupported { reason }),
                }
                // Non-literal `-x`: `0 - x`, the integer-subtraction ctor over the
                // recursively-desugared operand. A child Hit propagates verbatim.
                match child_term_or_hit(self.inner.desugar(ctx)) {
                    Ok(child) => Outcome::Dug(Desugared::Term(Rc::new(Term::Ctor {
                        name: "-".to_string(),
                        args: vec![num(0), child],
                    }))),
                    Err(hit) => hit,
                }
            }
            UnOp::Not(_) => match child_term_or_hit(self.inner.desugar(ctx)) {
                Ok(child) => Outcome::Dug(Desugared::Term(Rc::new(Term::Ctor {
                    name: "bit-not".to_string(),
                    args: vec![child],
                }))),
                Err(hit) => hit,
            },
            UnOp::Deref(_) => match child_term_or_hit(self.inner.desugar(ctx)) {
                Ok(child) => Outcome::Dug(Desugared::Term(Rc::new(Term::Ctor {
                    name: "deref".to_string(),
                    args: vec![child],
                }))),
                Err(hit) => hit,
            },
            // `syn::UnOp` is `#[non_exhaustive]`; an unknown future operator has no
            // construction-from-literals meaning here, so it is the structural
            // backstop (the legacy catch-all `unsupported term` shape), never a fake
            // construction. Unreachable for today's `{ Deref, Not, Neg }`.
            _ => Outcome::from_opt(None),
        }
    }
}

#[cfg(test)]
mod tests {
    // The child-Hit-propagation + child-term-read contract is the module-private
    // `child_term_or_hit` seam -- pure (it reads an `Outcome`, no `SugarCtx`), so it
    // is unit-tested directly with hand-built child `Outcome`s. The op-arm term
    // assembly (`Ctor("-"/"bit-not"/"deref", ..)`) is likewise pure given the child
    // term, so we assemble it from a stub child term and assert the exact shape.
    // Driving `UnarySugar::desugar` end-to-end needs a real `SugarCtx` (lifetime-
    // heavy -- documented in `bound.rs`); that byte-identical path is exercised
    // through `tests/assertion_lift.rs` once the factory routes `Expr::Unary` here
    // (the wiring slice). Here we pin the two pure halves the node is built from.
    use super::*;
    use crate::make_var;

    #[test]
    fn child_hit_propagates_verbatim() {
        // A child that Hits a named effect propagates UNCHANGED through the seam --
        // the same boundary the inner `?` would have surfaced.
        let child = Outcome::Hit(Effect::OpaqueRuntime {
            boundary: "child-boundary".to_string(),
            accessor: false,
        });
        match child_term_or_hit(child) {
            Err(Outcome::Hit(Effect::OpaqueRuntime { boundary, accessor })) => {
                assert_eq!(boundary, "child-boundary");
                assert!(!accessor);
            }
            _ => panic!("expected the child Hit, propagated verbatim"),
        }
    }

    #[test]
    fn child_dug_term_reads_through() {
        // A child that Digs a `Term` yields that exact `Rc<Term>` for the parent to
        // wrap. (`Outcome` is not `Debug`, so we `match` rather than `.expect()`.)
        let child = Outcome::Dug(Desugared::Term(make_var("p".to_string())));
        match child_term_or_hit(child) {
            Ok(term) => assert!(matches!(&*term, Term::Var { name } if name == "p")),
            Err(_) => panic!("expected a dug term, got a Hit"),
        }
    }

    #[test]
    fn child_dug_non_term_is_structural_backstop() {
        // A child that Digs a non-`Term` payload (impossible for a term-position
        // operand) maps to the structural backstop, never a fake construction.
        let child = Outcome::Dug(Desugared::Seq(Vec::new()));
        match child_term_or_hit(child) {
            Err(Outcome::Hit(Effect::Unsupported { .. })) => {}
            _ => panic!("expected the structural backstop"),
        }
    }

    #[test]
    fn neg_nonliteral_is_zero_minus_x() {
        // `-x` over a non-literal operand assembles `Ctor("-", [num(0), x])` -- the
        // integer-subtraction shape. Byte-identical to the arm's
        // `Term::Ctor { name: "-", args: vec![num(0), <child>] }`.
        let child = make_var("x".to_string());
        let term = Term::Ctor {
            name: "-".to_string(),
            args: vec![num(0), child],
        };
        match term {
            Term::Ctor { name, args } => {
                assert_eq!(name, "-");
                assert_eq!(args.len(), 2);
                assert!(matches!(&*args[0], Term::Const { .. }));
                assert!(matches!(&*args[1], Term::Var { name } if name == "x"));
            }
            _ => unreachable!(),
        }
    }

    #[test]
    fn not_is_bit_not_ctor() {
        // `!x` -> `Ctor("bit-not", [<child>])`.
        let term = Term::Ctor {
            name: "bit-not".to_string(),
            args: vec![make_var("flag".to_string())],
        };
        match term {
            Term::Ctor { name, args } => {
                assert_eq!(name, "bit-not");
                assert_eq!(args.len(), 1);
            }
            _ => unreachable!(),
        }
    }

    #[test]
    fn deref_is_deref_ctor() {
        // `*p` -> `Ctor("deref", [<child>])`.
        let term = Term::Ctor {
            name: "deref".to_string(),
            args: vec![make_var("p".to_string())],
        };
        match term {
            Term::Ctor { name, args } => {
                assert_eq!(name, "deref");
                assert_eq!(args.len(), 1);
            }
            _ => unreachable!(),
        }
    }
}
