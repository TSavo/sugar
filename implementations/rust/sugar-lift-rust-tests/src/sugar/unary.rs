// SPDX-License-Identifier: Apache-2.0
//
// `UnarySugar`: the TERM-FLOOR COMPOSITE for a unary operator in term position
// (`-x`, `!x`, `*p`). It composes ONE child `Box<dyn Sugar>` (built from the
// operand `unary.expr`) and mirrors the three `Expr::Unary` arms of
// `translate_term_in_scope` byte-identically. `syn::UnOp` is non-exhaustive; any
// future operator is a construction gap until a sugar arm exists.
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
//                 panic!("signed zero float literal needs the owning float floor");
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
// THE LITERAL FAST-PATHS ARE CHILD-FLOOR READS. The Neg arm first asks the child for
// its reduced term floor. Integer and Real floors fold directly; signed-zero Real
// remains a named IEEE effect; otherwise the arm falls to the `0 - x` ctor over the
// recursively-translated operand.
//
// THE CHILD INCOMPLETE PROPAGATES VERBATIM. The non-literal Neg branch and both the Not
// and Deref arms wrap `translate_term_in_scope(&unary.expr, scope)?` -- the inner
// `?` propagated the operand's named `Err`. The node mirrors that: it desugars the
// child, reads its term via `into_term()`, and if the child `Incomplete`s a named effect
// it RETURNS that `Incomplete` UNCHANGED (the same boundary the inner `?` would have
// surfaced). A child that completes a non-`Term` payload (a `Seq`/`Constraints` -- an
// impossible state for a term-position operand) panics loudly instead of manufacturing
// a terminal verdict. The child-read seam is the module-private
// `child_term_or_hit` (no `crate::` helper added -- the only `lib.rs` edit is the
// mod declaration).
//
// RECOGNIZER PREAMBLE. `recognize` for `Expr::Unary` builds the operand child and
// news a `UnarySugar` carrying { the op `UnaryOpKind`, the source key, the child }.
// `UnarySugar` makes no recognition decision of its own; it composes and reduces after
// the Sugar claim accepts the source shape.
//
// MIGRATION STATUS (Phase-3 ratchet -- FULLY MIGRATED).
//   * `recognize` uses ONLY `SourceFragment::unary_op_kind()` and
//     `SourceFragment::unary_operand()` -- no `as_expr()` shim, no raw `Expr::`
//     match, no raw `syn::UnOp` access.
//   * `UnarySugar` holds `op: UnaryOpKind` (a crate-local enum; no raw syn)
//     and `site: String`. No raw syn fields.

use std::rc::Rc;

use sugar_ir_symbolic::{ConstValue, Term};

use crate::sugar::factory::{IeeeFloatFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::float_floor::{IeeeFloatAccept, IeeeFloatValue, IeeeFloatVisitor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    bool_const, num, real_const, real_literal_is_zero, Desugared, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "unary",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_unary_good() {
                    assert_eq!(-5, -5);
                }
            "#,
            r#"
                #[test]
                fn t_unary_bad() {
                    assert_eq!(-5, -6);
                }
            "#,
        ),
        recognize,
    );

/// Operator kind for a `UnaryOp` expression -- replaces raw `syn::UnOp` in the struct.
/// `syn::UnOp` is `#[non_exhaustive]`; an unknown future operator routes to `None`
/// from `recognize` (no node is constructed) rather than being stored here.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum UnaryOpKind {
    /// `-x`
    Neg,
    /// `!x`
    Not,
    /// `*p`
    Deref,
}

/// TERM recognizer for `Expr::Unary`: news a [`UnarySugar`] over the operand child.
/// Byte-identical to the `Expr::Unary` arm -- `UnarySugar` owns the per-`UnaryOpKind`
/// arm selection + the Neg literal fast-paths.
///
/// FULLY MIGRATED: no `as_expr()`, no raw `Expr::` or `UnOp::` access in this body.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let op = match frag.unary_op_kind()? {
        "Neg" => UnaryOpKind::Neg,
        "Not" => UnaryOpKind::Not,
        "Deref" => UnaryOpKind::Deref,
        _ => return None, // unknown future syn::UnOp -- construction gap
    };
    let operand_frag = frag.unary_operand()?;
    let deref_operand_is_mutable_alias = (op == UnaryOpKind::Deref)
        && operand_frag
            .path_simple_ident()
            .as_deref()
            .is_some_and(|name| fcx.scope().mutable_alias_base(name).is_some());
    Some(Box::new(UnarySugar {
        op,
        site: frag.token_str(),
        inner: SugarBody::term_frag(&operand_frag, fcx),
        float_inner: (op == UnaryOpKind::Neg)
            .then(|| SugarBody::ieee_float_frag(&operand_frag, fcx, None, "unary_neg")),
        deref_operand_is_mutable_alias,
    }))
}

/// A unary operator in TERM position (`-x` / `!x` / `*p`). Composes ONE child
/// `Sugar` (the operand) and mirrors the matching `Expr::Unary` arm of
/// `translate_term_in_scope`. The Neg arm additionally folds literal child floors; see
/// the module header.
pub(crate) struct UnarySugar {
    /// The unary operator -- selects the arm (`Neg` -> fold-or-`0 - x`; `Not` ->
    /// `bit-not`; `Deref` -> `deref`).
    pub(crate) op: UnaryOpKind,
    /// The whole `-x` / `!x` / `*p` source key for named effects.
    pub(crate) site: String,
    /// The child `Sugar` built from the operand. Its `desugar(ctx).into_term()`
    /// mirrors `translate_term_in_scope(&unary.expr, scope)?`; a child `Incomplete`
    /// propagates verbatim.
    pub(crate) inner: SugarBody<TermFloor>,
    /// The same operand, typed as the IEEE float floor for `-<float>` sign-sensitive
    /// cases. `UnarySugar` only dispatches through it after the normal term floor says
    /// the operand is Real zero.
    pub(crate) float_inner: Option<SugarBody<IeeeFloatFloor>>,
    /// True only for `*alias_name` where `alias_name` is a temporal mutable-alias
    /// binding. This lets AliasFloor's post-write scalar value pass through deref
    /// without changing ordinary deref term emission (`*b` remains `deref(b)`).
    pub(crate) deref_operand_is_mutable_alias: bool,
}

/// Read a desugared CHILD outcome as the `Rc<Term>` an `Expr::Unary` arm would have
/// obtained from `translate_term_in_scope(&unary.expr, scope)?`. A child `Complete(Term)`
/// yields the term (`Ok`); a child `Incomplete(effect)` propagates VERBATIM (`Err(Incomplete)`) --
/// the same named boundary the inner `?` would have surfaced; a child that completes a
/// non-`Term` payload (impossible for a term-position operand) panics. Module-private
/// so no `crate::` helper is added.
fn child_term_or_hit(child: Outcome) -> Result<Rc<Term>, Outcome> {
    match child {
        Outcome::Complete(d) => match d.into_term() {
            Some(term) => Ok(term),
            None => unary_gap("unary child completed as non-term"),
        },
        hit @ Outcome::Incomplete(_) => Err(hit),
    }
}

fn reduce_child_term(child: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match child.reduce(ctx) {
        outcome => child_term_or_hit(outcome),
    }
}

fn unary_gap(reason: &str) -> ! {
    panic!("unary completed without an operand term floor: {reason}")
}

fn negated_zero_float_floor(
    child: &SugarBody<IeeeFloatFloor>,
    ctx: &SugarCtx,
    site: &str,
) -> Outcome {
    match child.reduce(ctx) {
        Outcome::Complete(desugared) => {
            let Some(term) = desugared.into_term() else {
                unary_gap("IEEE float negation child completed as non-term");
            };
            term.accept_ieee_float(UnaryNegFloatVisitor { site })
        }
        Outcome::Incomplete(effect) => Outcome::Incomplete(effect),
    }
}

struct UnaryNegFloatVisitor<'a> {
    site: &'a str,
}

impl IeeeFloatVisitor for UnaryNegFloatVisitor<'_> {
    type Output = Outcome;

    fn visit_float(self, value: IeeeFloatValue) -> Self::Output {
        match value.neg().to_real_term(self.site) {
            Ok(term) => Outcome::Complete(Desugared::Term(term)),
            Err(outcome) => outcome,
        }
    }

    fn visit_non_float(self, _term: &Rc<Term>) -> Self::Output {
        unary_gap("IEEE float negation child did not dispatch to float floor")
    }
}

impl Sugar for UnarySugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.op {
            UnaryOpKind::Neg => {
                let child = match reduce_child_term(&self.inner, ctx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                if let Term::Const {
                    value: ConstValue::Int(value),
                    ..
                } = child.as_ref()
                {
                    return Outcome::Complete(Desugared::Term(num(value
                        .checked_neg()
                        .unwrap_or_else(|| unary_gap("integer negation overflowed")))));
                }
                if let Term::Const {
                    value: ConstValue::Real(value),
                    ..
                } = child.as_ref()
                {
                    if real_literal_is_zero(value) {
                        let Some(float_inner) = &self.float_inner else {
                            unary_gap("signed zero float literal needs the owning float floor");
                        };
                        return negated_zero_float_floor(float_inner, ctx, &self.site);
                    }
                    return Outcome::Complete(Desugared::Term(real_const(format!("-{value}"))));
                }
                Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
                    name: "-".to_string(),
                    args: vec![num(0), child],
                })))
            }
            UnaryOpKind::Not => {
                let child = match reduce_child_term(&self.inner, ctx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                if let Term::Const {
                    value: ConstValue::Bool(value),
                    ..
                } = child.as_ref()
                {
                    return Outcome::Complete(Desugared::Term(bool_const(!value)));
                }
                Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
                    name: "bit-not".to_string(),
                    args: vec![child],
                })))
            }
            UnaryOpKind::Deref => match reduce_child_term(&self.inner, ctx) {
                // `*&e == e`: dereferencing a SHARED borrow yields its pointee. A shared
                // borrow freezes its pointee for the borrow's lifetime (the borrow
                // checker forbids mutating the pointee while a `&` is live, and a shared
                // ref cannot mutate through itself), so the pointee read at `*r` IS the
                // text-determined value the inlined `ref(v)` carries. Cancel
                // `deref(ref(v))` to `v` so `*r` over a shared borrow of a local warrants
                // the value instead of an uninterpreted `deref(ref(..))` a bad twin could
                // mis-satisfy (the deref-read analog of the shared-`&` relation-surface
                // strip, #2321). ONLY the shared `ref` cancels: `ref_mut` is left intact
                // because a `&mut` deref can observe a value MUTATED through the alias
                // after the borrow, so canceling its binding-time snapshot would
                // false-discharge (`let mut x=5; let r=&mut x; *r+=1; assert_eq!(*r,5)`
                // -> `5==5` SAT). AliasFloor supplies a newer route for scalar `&mut`
                // aliases: after replaying `*p += 1`, the child floor is already the
                // pointee VALUE (`6`), not `ref_mut(5)`, so `deref(6)` collapses to `6`
                // only when the operand is a known temporal mutable-alias binding.
                // Ordinary non-alias derefs (`*b`) and opaque/raw pointer derefs are
                // unchanged.
                Ok(child) => {
                    if let Term::Ctor { name, args } = child.as_ref() {
                        if name == "ref" && args.len() == 1 {
                            return Outcome::Complete(Desugared::Term(Rc::clone(&args[0])));
                        }
                    }
                    if self.deref_operand_is_mutable_alias
                        && matches!(child.as_ref(), Term::Const { .. })
                    {
                        return Outcome::Complete(Desugared::Term(child));
                    }
                    Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
                        name: "deref".to_string(),
                        args: vec![child],
                    })))
                }
                Err(outcome) => outcome,
            },
        }
    }
}

#[cfg(test)]
mod tests {
    // The child-Incomplete-propagation + child-term-read contract is the module-private
    // `child_term_or_hit` seam -- pure (it reads an `Outcome`, no `SugarCtx`), so it
    // is unit-tested directly with hand-built child `Outcome`s. The op-arm term
    // assembly (`Ctor("-"/"bit-not"/"deref", ..)`) is likewise pure given the child
    // term, so we assemble it from a stub child term and assert the exact shape.
    // Driving `UnarySugar::desugar` end-to-end needs a real `SugarCtx` (lifetime-
    // heavy -- documented in `bound.rs`); that byte-identical path is exercised
    // through `tests/assertion_lift.rs` once the factory routes `Expr::Unary` here
    // (the wiring slice). Here we pin the two pure halves the node is built from.
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
    use crate::{make_var, Effect};

    // -- from_src tests: source -> fragment -> observed -> accessors -> floor --

    fn unary_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        // The tail expression statement (`-x`, `!x`, `*p`) is the only statement;
        // `terms()` on the Expr stmt yields the single unary expr child.
        let terms = stmts[0].terms();
        terms[0]
    }

    /// Positive: `-x` is classified as `"UnaryOp"`, `unary_op_kind()` returns `"Neg"`,
    /// and `unary_operand()` yields a `"Name"` fragment for `x`. Struct holds
    /// `UnaryOpKind::Neg` -- no raw syn.
    #[test]
    fn from_src_neg_observed_op_kind_and_operand() {
        let file = parse_file("fn f(x: i64) -> i64 { -x }");
        let frag = unary_expr_frag(&file, "f.rs");

        // observed
        assert_eq!(frag.observed(), "UnaryOp");

        // op kind via typed accessor (no as_expr / Expr:: access here)
        assert_eq!(frag.unary_op_kind(), Some("Neg"));

        // operand: `x` is a Name
        let operand = frag.unary_operand().expect("operand present");
        assert_eq!(operand.observed(), "Name");

        // floor: decode to UnaryOpKind::Neg -- the struct holds this, not syn::UnOp
        let op_str = frag.unary_op_kind().unwrap();
        let op = match op_str {
            "Neg" => UnaryOpKind::Neg,
            "Not" => UnaryOpKind::Not,
            "Deref" => UnaryOpKind::Deref,
            _ => panic!("unexpected op kind: {op_str}"),
        };
        assert_eq!(op, UnaryOpKind::Neg);
    }

    /// Discrimination: `!flag` has op kind `"Not"` and operand `"Name"`.
    /// Proves `unary_op_kind()` distinguishes Not from Neg.
    #[test]
    fn discrimination_not_op_kind_is_not() {
        let file = parse_file("fn f(flag: bool) -> bool { !flag }");
        let frag = unary_expr_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "UnaryOp");
        assert_eq!(frag.unary_op_kind(), Some("Not"));
        let operand = frag.unary_operand().expect("operand present");
        assert_eq!(operand.observed(), "Name");
    }

    /// Structural: a `BinOp` fragment returns `None` from both `unary_op_kind()`
    /// and `unary_operand()` -- the accessors are shape-specific.
    #[test]
    fn structural_binop_returns_none_from_unary_accessors() {
        let file = parse_file("fn f(a: i64, b: i64) -> i64 { a + b }");
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = frag.function_body().unwrap();
        let stmts = body.statements();
        let terms = stmts[0].terms();
        let binop_frag = &terms[0];

        assert_eq!(binop_frag.observed(), "BinOp");
        assert_eq!(binop_frag.unary_op_kind(), None);
        assert!(binop_frag.unary_operand().is_none());
    }

    // -- pure unit tests (unchanged from pre-migration) -----------------------

    #[test]
    fn child_hit_propagates_verbatim() {
        // A child that returns Incomplete a named effect propagates UNCHANGED through the seam --
        // the same boundary the inner `?` would have surfaced.
        let child = Outcome::Incomplete(Effect::OpaqueRuntime {
            boundary: "child-boundary".to_string(),
            accessor: false,
        });
        match child_term_or_hit(child) {
            Err(Outcome::Incomplete(Effect::OpaqueRuntime { boundary, accessor })) => {
                assert_eq!(boundary, "child-boundary");
                assert!(!accessor);
            }
            _ => panic!("expected the child Incomplete, propagated verbatim"),
        }
    }

    #[test]
    fn child_dug_term_reads_through() {
        // A child that completes a `Term` yields that exact `Rc<Term>` for the parent to
        // wrap. (`Outcome` is not `Debug`, so we `match` rather than `.expect()`.)
        let child = Outcome::Complete(Desugared::Term(make_var("p".to_string())));
        match child_term_or_hit(child) {
            Ok(term) => assert!(matches!(&*term, Term::Var { name } if name == "p")),
            Err(_) => panic!("expected a completed term, got a Incomplete"),
        }
    }

    #[test]
    #[should_panic(expected = "unary child completed as non-term")]
    fn child_dug_non_term_panics() {
        // A child that completes a non-`Term` payload (impossible for a term-position
        // operand) panics, never a fake construction.
        let child = Outcome::Complete(Desugared::Seq(Vec::new()));
        let _ = child_term_or_hit(child);
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
