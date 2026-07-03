// SPDX-License-Identifier: Apache-2.0
//
// `BvBinOpSugar`: the constructive bv32 term node for a BIT-OPERATION binary operator
// (`x << 2`, `a & b`, `x | y`, `a ^ b`, `n >> k`). It intercepts these operators
// BEFORE the broader `BinOpSugar` so they produce width-keyed bv32 ProofIR ctors
// (`"bv32.shl"` / `"bv32.lshr"` / `"bv32.and"` / `"bv32.or"` / `"bv32.xor"`) instead
// of the opaque uninterpreted ctors (`"shift-left"` / `"bit-and"` etc.) that the SMT
// backend cannot lower to bitvector semantics.
//
// The `comes_before: &["binop"]` ordering ensures the catalog dispatches here first.
// `BinOpSugar` remains the fallback for arithmetic operators (+/-/*/div/rem) that do
// not route here.
//
// Const-fold for fully ground operands: after assembling the `bv32.*` Ctor term,
// `const_fold_u128_term` is tried. That function now handles `bv32.*` ctors so ground
// bit-op expressions collapse to a literal without reaching the SMT backend.

use std::rc::Rc;

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_leaf::resolved_term;
use crate::{const_fold_u128_term, u128_term, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "bv_binop",
        &["binop"],
        crate::sugar::claim::SugarWitnesses::Pending,
        recognize,
    );

/// Recognizer for `Expr::Binary` with bit-operation operators.
///
/// Fires before `binop` for `Shl`/`Shr`/`BitAnd`/`BitOr`/`BitXor`. Returns `None`
/// for all other operators so the factory falls through to the arithmetic `binop` sugar.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Gate: must be a BinOp fragment with a bv32 bit-operation operator.
    let op_name = frag.binop_bv32_op_name()?;
    // Ground fast-path: if the whole expression const-evals to a scalar value, resolve
    // it immediately. This handles literals like `3u32 << 2` without building a bv32
    // Ctor at all.
    if let Some(term) = frag.binop_const_folded_term() {
        return Some(resolved_term(term));
    }
    let left_frag = frag.binop_left()?;
    let right_frag = frag.binop_right()?;
    Some(Box::new(BvBinOpSugar {
        left: SugarBody::term_frag(&left_frag, fcx),
        right: SugarBody::term_frag(&right_frag, fcx),
        op_name,
    }))
}

/// The constructive bv32 bit-operation node. `left`/`right` are the pre-built operand
/// children; `op_name` is the captured bv32 ctor name (e.g. `"bv32.shl"`). `desugar`
/// composes the children's terms and emits `Term::Ctor { name: op_name, args: [l, r] }`,
/// then attempts a ground const-fold via `const_fold_u128_term`.
pub(crate) struct BvBinOpSugar {
    pub(crate) left: SugarBody<TermFloor>,
    pub(crate) right: SugarBody<TermFloor>,
    pub(crate) op_name: &'static str,
}

impl Sugar for BvBinOpSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let lhs = match self.left.reduce(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(t) => t,
                None => {
                    bv_binop_gap("bv bit-op child completed as non-Term where a Term was required")
                }
            },
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        let rhs = match self.right.reduce(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(t) => t,
                None => {
                    bv_binop_gap("bv bit-op child completed as non-Term where a Term was required")
                }
            },
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        let term = Rc::new(sugar_ir_symbolic::Term::Ctor {
            name: self.op_name.to_string(),
            args: vec![lhs, rhs],
        });
        // Ground const-fold: bv32.* ctors with const args collapse to a u128 literal.
        if let Some(value) = const_fold_u128_term(&term) {
            return Outcome::Complete(Desugared::Term(u128_term(value)));
        }
        Outcome::Complete(Desugared::Term(term))
    }
}

fn bv_binop_gap(reason: &str) -> ! {
    panic!("bv bit-op did not reach lawful child floors: {reason}; write more Sugar for this AST")
}

// ---------------------------------------------------------------------------
// Phase-3 from_src tests: source -> SourceFragment -> observed -> accessor ->
// assert shape. No parse_quote!, no StubTerm, no run().
// ---------------------------------------------------------------------------
#[cfg(test)]
mod from_src_tests {
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Navigate to the tail-expression fragment of the first function in a one-liner.
    fn bv_binop_frag_from<'a>(file: &'a syn::File, src_name: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), src_name);
        let body = frag.function_body().expect("fn body");
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    /// Positive: `x << k` gives `binop_bv32_op_name() == Some("bv32.shl")`.
    #[test]
    fn from_src_shl_gives_bv32_shl_op_name() {
        let src = "fn f(x: u32, k: u32) -> u32 { x << k }";
        let file = parse_file(src);
        let frag = bv_binop_frag_from(&file, "f.rs");

        assert_eq!(frag.observed(), "BinOp");
        assert_eq!(frag.binop_bv32_op_name(), Some("bv32.shl"));
    }

    /// Discrimination: arithmetic `+` gives `binop_bv32_op_name() == None`.
    #[test]
    fn from_src_arithmetic_binop_bv32_op_name_is_none() {
        let src = "fn f(x: u32, y: u32) -> u32 { x + y }";
        let file = parse_file(src);
        let frag = bv_binop_frag_from(&file, "f.rs");

        assert_eq!(frag.observed(), "BinOp");
        assert_eq!(
            frag.binop_bv32_op_name(),
            None,
            "arithmetic + is not a bv32 op"
        );
    }

    /// Structural: `a << 2` — left/right children are accessible via frag accessors.
    #[test]
    fn from_src_shl_children_accessible_via_frag_accessors() {
        let src = "fn f(a: u32) -> u32 { a << 2 }";
        let file = parse_file(src);
        let frag = bv_binop_frag_from(&file, "f.rs");

        assert_eq!(frag.observed(), "BinOp");
        assert_eq!(frag.binop_bv32_op_name(), Some("bv32.shl"));
        let left = frag.binop_left().expect("left child");
        let right = frag.binop_right().expect("right child");
        assert_eq!(left.observed(), "Name", "left `a` is a Name");
        assert_eq!(
            right.observed(),
            "PrimitiveLiteral",
            "right `2` is a PrimitiveLiteral"
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Effect;
    use sugar_ir_symbolic::{make_var, ConstValue, Sort, Term};

    struct StubTerm(Rc<Term>);
    impl Sugar for StubTerm {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::Complete(Desugared::Term(Rc::clone(&self.0)))
        }
    }

    struct StubIncomplete;
    impl Sugar for StubIncomplete {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::Incomplete(Effect::Mutation {
                boundary: "stub".to_string(),
            })
        }
    }

    fn run(node: &dyn Sugar) -> Outcome {
        let scope = crate::TemporalScope::new("test", crate::TemporalPlan::default());
        let options = crate::LiftOptions::default();
        let items: Vec<syn::Item> = Vec::new();
        let reducer = crate::ReductionCtx::from_items(&items);
        let mut float_widths = crate::FloatWidthScope::new();
        let ctx = crate::sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        node.desugar(&ctx)
    }

    fn ctor_shape(t: &Term) -> (&str, &[Rc<Term>]) {
        match t {
            Term::Ctor { name, args } => (name.as_str(), args.as_slice()),
            _ => panic!("expected a Ctor term, got {t:?}"),
        }
    }

    fn var_name(t: &Term) -> &str {
        match t {
            Term::Var { name } => name.as_str(),
            _ => panic!("expected a Var term, got {t:?}"),
        }
    }

    fn int_const(t: &Term) -> i128 {
        match t {
            Term::Const {
                value: ConstValue::Int(v),
                ..
            } => *v,
            _ => panic!("expected an Int const, got {t:?}"),
        }
    }

    fn bv32_const(v: i64) -> Rc<Term> {
        Rc::new(Term::Const {
            value: ConstValue::Int(v as i128),
            sort: Sort {
                name: "u32".to_string(),
            },
        })
    }

    // ── Shape tests: symbolic operands → correct bv32 ctor ──────────────────

    #[test]
    fn shl_on_vars_emits_bv32_shl_ctor() {
        let node = BvBinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(make_var("x")))),
            right: SugarBody::from_node(Box::new(StubTerm(make_var("k")))),
            op_name: "bv32.shl",
        };
        let term = match run(&node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete"),
        };
        let (name, args) = ctor_shape(&term);
        assert_eq!(name, "bv32.shl");
        assert_eq!(args.len(), 2);
        assert_eq!(var_name(&args[0]), "x");
        assert_eq!(var_name(&args[1]), "k");
    }

    #[test]
    fn lshr_on_vars_emits_bv32_lshr_ctor() {
        let node = BvBinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(make_var("x")))),
            right: SugarBody::from_node(Box::new(StubTerm(make_var("k")))),
            op_name: "bv32.lshr",
        };
        let term = match run(&node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete"),
        };
        let (name, _) = ctor_shape(&term);
        assert_eq!(name, "bv32.lshr");
    }

    #[test]
    fn and_on_vars_emits_bv32_and_ctor() {
        let node = BvBinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(make_var("a")))),
            right: SugarBody::from_node(Box::new(StubTerm(make_var("b")))),
            op_name: "bv32.and",
        };
        let term = match run(&node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete"),
        };
        let (name, args) = ctor_shape(&term);
        assert_eq!(name, "bv32.and");
        assert_eq!(args.len(), 2);
    }

    #[test]
    fn or_on_vars_emits_bv32_or_ctor() {
        let node = BvBinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(make_var("x")))),
            right: SugarBody::from_node(Box::new(StubTerm(make_var("y")))),
            op_name: "bv32.or",
        };
        let term = match run(&node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete"),
        };
        let (name, _) = ctor_shape(&term);
        assert_eq!(name, "bv32.or");
    }

    #[test]
    fn xor_on_vars_emits_bv32_xor_ctor() {
        let node = BvBinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(make_var("a")))),
            right: SugarBody::from_node(Box::new(StubTerm(make_var("b")))),
            op_name: "bv32.xor",
        };
        let term = match run(&node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete"),
        };
        let (name, _) = ctor_shape(&term);
        assert_eq!(name, "bv32.xor");
    }

    /// The key composition test: `(x << 6) | y` lifts to
    /// `bv32.or(bv32.shl(x, 6), y)` — the plan's canonical shape.
    #[test]
    fn shl_or_composition_lifts_to_bv32_or_of_bv32_shl() {
        // Simulate `(x << 6) | y` by building two nodes manually.
        let inner = BvBinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(make_var("x")))),
            right: SugarBody::from_node(Box::new(StubTerm(bv32_const(6)))),
            op_name: "bv32.shl",
        };
        // Run inner first to get the Rc<Term> for bv32.shl(x,6)
        let scope = crate::TemporalScope::new("test", crate::TemporalPlan::default());
        let options = crate::LiftOptions::default();
        let items: Vec<syn::Item> = Vec::new();
        let reducer = crate::ReductionCtx::from_items(&items);
        let mut float_widths = crate::FloatWidthScope::new();
        let ctx = crate::sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        let shl_term = match inner.desugar(&ctx) {
            Outcome::Complete(d) => d.into_term().expect("shl Term"),
            Outcome::Incomplete(_) => panic!("inner shl incomplete"),
        };

        let outer = BvBinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(shl_term))),
            right: SugarBody::from_node(Box::new(StubTerm(make_var("y")))),
            op_name: "bv32.or",
        };
        let term = match outer.desugar(&ctx) {
            Outcome::Complete(d) => d.into_term().expect("outer Term"),
            Outcome::Incomplete(_) => panic!("outer or incomplete"),
        };

        // outer = bv32.or(bv32.shl(x, 6), y)
        let (outer_name, outer_args) = ctor_shape(&term);
        assert_eq!(outer_name, "bv32.or");
        assert_eq!(outer_args.len(), 2);

        let (inner_name, inner_args) = ctor_shape(&outer_args[0]);
        assert_eq!(inner_name, "bv32.shl");
        assert_eq!(inner_args.len(), 2);
        assert_eq!(var_name(&inner_args[0]), "x");
        assert_eq!(int_const(&inner_args[1]), 6);

        assert_eq!(var_name(&outer_args[1]), "y");
    }

    // ── Const-fold tests: ground operands → folded literal ──────────────────

    #[test]
    fn ground_shl_folds_to_literal() {
        // 1u32 << 4 == 16
        let node = BvBinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(bv32_const(1)))),
            right: SugarBody::from_node(Box::new(StubTerm(bv32_const(4)))),
            op_name: "bv32.shl",
        };
        let term = match run(&node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete"),
        };
        assert_eq!(int_const(&term), 16);
    }

    #[test]
    fn ground_lshr_folds_to_literal() {
        // 128 >> 3 == 16
        let node = BvBinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(bv32_const(128)))),
            right: SugarBody::from_node(Box::new(StubTerm(bv32_const(3)))),
            op_name: "bv32.lshr",
        };
        let term = match run(&node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete"),
        };
        assert_eq!(int_const(&term), 16);
    }

    #[test]
    fn ground_and_folds_to_literal() {
        // 0xFF & 0x0F == 0x0F
        let node = BvBinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(bv32_const(0xFF)))),
            right: SugarBody::from_node(Box::new(StubTerm(bv32_const(0x0F)))),
            op_name: "bv32.and",
        };
        let term = match run(&node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete"),
        };
        assert_eq!(int_const(&term), 0x0F);
    }

    #[test]
    fn ground_or_folds_to_literal() {
        // 0xF0 | 0x0F == 0xFF
        let node = BvBinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(bv32_const(0xF0)))),
            right: SugarBody::from_node(Box::new(StubTerm(bv32_const(0x0F)))),
            op_name: "bv32.or",
        };
        let term = match run(&node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete"),
        };
        assert_eq!(int_const(&term), 0xFF);
    }

    #[test]
    fn ground_xor_folds_to_literal() {
        // 0xAA ^ 0xFF == 0x55
        let node = BvBinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(bv32_const(0xAA)))),
            right: SugarBody::from_node(Box::new(StubTerm(bv32_const(0xFF)))),
            op_name: "bv32.xor",
        };
        let term = match run(&node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete"),
        };
        assert_eq!(int_const(&term), 0x55);
    }

    // ── Propagation tests: Incomplete child → propagated verbatim ───────────

    #[test]
    fn propagates_left_child_incomplete() {
        let node = BvBinOpSugar {
            left: SugarBody::from_node(Box::new(StubIncomplete)),
            right: SugarBody::from_node(Box::new(StubTerm(make_var("y")))),
            op_name: "bv32.shl",
        };
        match run(&node) {
            Outcome::Incomplete(Effect::Mutation { boundary }) => {
                assert_eq!(boundary, "stub");
            }
            _ => panic!("expected left child Incomplete(Mutation), got something else"),
        }
    }

    #[test]
    fn propagates_right_child_incomplete() {
        let node = BvBinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(make_var("x")))),
            right: SugarBody::from_node(Box::new(StubIncomplete)),
            op_name: "bv32.or",
        };
        match run(&node) {
            Outcome::Incomplete(Effect::Mutation { boundary }) => {
                assert_eq!(boundary, "stub");
            }
            _ => panic!("expected right child Incomplete(Mutation), got something else"),
        }
    }
}
