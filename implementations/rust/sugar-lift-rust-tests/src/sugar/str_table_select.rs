// SPDX-License-Identifier: Apache-2.0
//
// `StrTableSelectSugar`: general Sugar for `literal_byte_array[bv32_expr]` in
// term position.  Fires BEFORE `IndexSugar` via the `comes_before: &["index"]`
// ordering when the container is a literal byte/char sequence AND the index
// expression contains bit-operation operators (`<<`, `>>`, `&`, `|`, `^`) --
// the pattern produced by base64 and other bit-interleaving algorithms.
//
// Emits:
//   `Term::Ctor { name: "str.table-select", args: [str_const(alpha), bv32_idx] }`
//
// The SMT backend (the `str.table-select` arm in `emit_term_with_expected`)
// lowers this to a nested `(ite (= idx K) cp ...)` codepoint-lookup chain
// over the alphabet string.  Callers wrap the Int codepoint result with
// `str.from_code` to obtain a one-character String.
//
// GENERAL (not base64-specific): the alphabet can be any ASCII-valued byte
// table.  The base64 `internal_encode` function discharges as a CONSEQUENCE of
// these general composable Sugars -- no base64-specific code appears here.
//
// SOUND: only literal containers whose every element has a byte-range
// (0..=255) const value are matched.  Non-literal containers (struct fields,
// runtime slices) and plain const-integer indexes fall through to `IndexSugar`.

use std::rc::Rc;

use sugar_ir_symbolic::{str_const, Term};

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::{ConstVal, Desugared, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "str_table_select",
        &["index"],
        recognize,
    );

/// Recognizer for `literal_byte_array[bv32_expr]`.
///
/// Fires only when:
///   1. The expression is `Expr::Index` (gate: `index_receiver()` returns `Some`)
///   2. The index sub-expression contains at least one bit-operation operator
///      (`<<`, `>>`, `&`, `|`, `^`) -- bv32 Sugar will reduce it to a bv32 Ctor
///   3. The container sub-expression resolves to a literal composite sequence
///
/// Returns `None` for plain const indexes (handled by `IndexSugar` via
/// `ground_literal_index`) and for non-literal containers.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Must be Expr::Index -- index_receiver() returns Some only for that variant.
    let container_frag = frag.index_receiver()?;
    let idx_frag = frag.index_index()?;
    // Only intercept bv32-like index expressions.  A plain integer literal
    // index const-folds cleanly inside `IndexSugar::ground_literal_index`;
    // stealing it here would duplicate that path with no benefit.
    if !idx_frag.index_contains_bv_op_frag() {
        return None;
    }
    // Container must be a literal composite sequence (e.g. a literal byte array).
    let literal_container = container_frag.build_literal_sequence_composite_frag(fcx)?;
    Some(Box::new(StrTableSelectSugar {
        literal_container: SugarBody::from_node(literal_container),
        idx: SugarBody::term_frag(&idx_frag, fcx),
    }))
}

/// `StrTableSelectSugar` node.  Holds pre-built child Sugar bodies.
/// Children are evaluated lazily in `desugar`, mirroring the `IndexSugar` pattern.
pub(crate) struct StrTableSelectSugar {
    /// Literal container composite (a fixed byte/char array in scope).
    literal_container: SugarBody<CompositeFloor>,
    /// Index expression -- expected to reduce to a bv32 Ctor term.
    idx: SugarBody<TermFloor>,
}

impl Sugar for StrTableSelectSugar {
    /// Desugar to `Ctor("str.table-select", [str_const(alpha), bv32_idx])`.
    ///
    /// The alpha string is built from the literal container's element codepoints
    /// (must all be byte values 0..=255).  The bv32_idx is the reduced index term.
    ///
    /// The SMT backend lowers the resulting Ctor to a nested ite-chain codepoint
    /// lookup (see the `str.table-select` arm in `emit_term_with_expected`).
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        // Reduce the container to the literal element sequence.
        let seq = match self.literal_container.reduce(ctx) {
            Outcome::Complete(d) => match d.into_seq() {
                Some(seq) => seq,
                None => table_select_gap("literal container reduced to non-Seq floor"),
            },
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        // Build the alphabet string from the element codepoints.
        // Every element must have a const-known byte value (0..=255).
        let alpha: Option<String> = seq
            .iter()
            .map(|elem| {
                elem.value.as_ref().and_then(|v| match v {
                    ConstVal::Char(c) => Some(*c),
                    _ => v
                        .as_int()
                        .and_then(|n| u8::try_from(n).ok())
                        .map(|b| b as char),
                })
            })
            .collect();
        let Some(alpha) = alpha else {
            table_select_gap(
                "literal container element is not a byte codepoint (0..=255); \
                 StrTableSelectSugar requires a byte-valued literal array",
            )
        };
        // Reduce the index expression to its term (expected: a bv32 Ctor).
        let idx = match self.idx.reduce(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(t) => t,
                None => table_select_gap("index did not reduce to a term floor"),
            },
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        // Emit Ctor("str.table-select", [str_const(alpha), idx_term]).
        // The SMT backend (str.table-select arm in emit_term_with_expected) lowers
        // this to an ite-chain codepoint lookup over the alphabet.
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: "str.table-select".to_string(),
            args: vec![str_const(alpha), idx],
        })))
    }
}

fn table_select_gap(reason: &str) -> ! {
    panic!(
        "str_table_select Sugar completed without a lawful floor: {reason}; \
         add more Sugar for this AST shape"
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        sugar_ctx, Desugared, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, TemporalPlan,
        TemporalScope,
    };
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
    use std::collections::BTreeMap;
    use sugar_ir_symbolic::{ConstValue, Term};
    use syn::{parse_quote, Expr, Item};

    // ── from_src structural tests ─────────────────────────────────────────────

    fn index_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let frag = SourceFragment::from_node(FragNode::Item(&file.items[0]), file_str);
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        stmts[0].terms()[0]
    }

    /// Positive: `[65u8, 66u8, 67u8][(x >> 2) as usize]`
    ///   -> `observed()` is "Index"
    ///   -> `index_receiver()` exposes the container
    ///   -> `index_index().index_contains_bv_op_frag()` is true
    /// No as_expr / Expr:: / raw syn field access in this test body.
    #[test]
    fn from_src_index_observed_receiver_and_bv_op_gate() {
        let file = parse_file("fn f(x: usize) { [65u8, 66u8, 67u8][(x >> 2) as usize] }");
        let frag = index_expr_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "Index");
        assert!(frag.index_receiver().is_some(), "container must be accessible via index_receiver");
        let idx_frag = frag.index_index().expect("index sub-expr must be accessible");
        assert!(
            idx_frag.index_contains_bv_op_frag(),
            "index must contain a bit-operation operator"
        );
    }

    /// Discrimination: a plain const index `[65u8][2usize]` -- `index_index()` exists but
    /// `index_contains_bv_op_frag()` is false (no shift/bitwise op).
    #[test]
    fn from_src_plain_const_index_bv_op_gate_is_false() {
        let file = parse_file("fn f() { [65u8, 66u8][2usize] }");
        let frag = index_expr_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "Index");
        let idx_frag = frag.index_index().expect("index sub-expr present");
        assert!(
            !idx_frag.index_contains_bv_op_frag(),
            "plain literal index must NOT trigger bv-op gate"
        );
    }

    /// Structural: a `MethodCall` fragment returns `None` from `index_receiver` and
    /// `index_index` -- index accessors do not bleed across expression kinds.
    #[test]
    fn from_src_structural_method_call_returns_none_from_index_accessors() {
        let file = parse_file("fn f(x: u32) -> u32 { x.count_ones() }");
        let frag = index_expr_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert!(frag.index_receiver().is_none());
        assert!(frag.index_index().is_none());
    }

    // ── Recognizer gate tests ─────────────────────────────────────────────────

    fn recognize_and_run(source: Expr) -> Option<Outcome> {
        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = { let _frag = SourceFragment::expr(&source, "<src>"); recognize(&_frag, &fcx) }?;

        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut fw = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut fw, 0);
        Some(node.desugar(&ctx))
    }

    #[test]
    fn recognize_fires_for_literal_array_bv_op_index() {
        let expr: Expr = parse_quote!([65u8, 66u8, 67u8][(x >> 2) as usize]);
        assert!(
            recognize_and_run(expr).is_some(),
            "must recognize literal array with bv-op index"
        );
    }

    #[test]
    fn recognize_declines_for_plain_const_index() {
        // A bare const index (e.g. `arr[2]`) should fall through to IndexSugar.
        let expr: Expr = parse_quote!([65u8, 66u8, 67u8][2usize]);
        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        assert!(
            { let _frag = SourceFragment::expr(&expr, "<src>"); recognize(&_frag, &fcx) }.is_none(),
            "must NOT recognize a plain const index -- leave that for IndexSugar"
        );
    }

    #[test]
    fn recognize_declines_for_non_literal_container() {
        // A non-literal container (a variable holding an array) must not fire.
        let expr: Expr = parse_quote!(my_array[(x >> 2) as usize]);
        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        assert!(
            { let _frag = SourceFragment::expr(&expr, "<src>"); recognize(&_frag, &fcx) }.is_none(),
            "must NOT recognize a non-literal container"
        );
    }

    // ── Shape tests: emitted term structure ───────────────────────────────────

    #[test]
    fn emits_str_table_select_ctor_with_correct_alpha() {
        // [65u8, 66u8, 67u8][(x >> 2) as usize]
        //   => Ctor("str.table-select", [str_const("ABC"), <bv32_idx>])
        let expr: Expr = parse_quote!([65u8, 66u8, 67u8][(x >> 2) as usize]);
        let outcome = recognize_and_run(expr).expect("recognizer must fire");
        let Outcome::Complete(Desugared::Term(term)) = outcome else {
            panic!("expected Complete(Term), got something else");
        };
        match &*term {
            Term::Ctor { name, args } => {
                assert_eq!(name, "str.table-select", "ctor name must be str.table-select");
                assert_eq!(args.len(), 2, "must have exactly 2 args: [alpha, idx]");
                // First arg: the alpha string const
                match &*args[0] {
                    Term::Const {
                        value: ConstValue::String(s),
                        ..
                    } => {
                        assert_eq!(s, "ABC", "alpha must match the literal array codepoints");
                    }
                    other => panic!("expected String const as first arg, got {other:?}"),
                }
            }
            other => panic!("expected Ctor term, got {other:?}"),
        }
    }

    #[test]
    fn emits_str_table_select_with_bv_op_index_term() {
        // The index child must be a bv32 Ctor (the bit-op tree), NOT a literal.
        // [65u8, 66u8, 67u8][(x >> 2) as usize]
        //   => second arg must be a Ctor (the bv32.lshr from bv_binop, or at
        //      minimum NOT a const literal -- the child is built symbolically).
        let expr: Expr = parse_quote!([65u8, 66u8, 67u8][(x >> 2) as usize]);
        let outcome = recognize_and_run(expr).expect("recognizer must fire");
        let Outcome::Complete(Desugared::Term(term)) = outcome else {
            panic!("expected Complete(Term)");
        };
        if let Term::Ctor { name, args } = &*term {
            assert_eq!(name, "str.table-select");
            // The index arg (args[1]) should NOT be a plain Int const -- it must
            // be a Ctor (the bv32.lshr tree built by BvBinOpSugar) or a Var.
            assert!(
                !matches!(&*args[1], Term::Const { value: sugar_ir_symbolic::ConstValue::Int(_), .. }),
                "index arg must be symbolic (Ctor/Var), not a folded Int const"
            );
        } else {
            panic!("expected Ctor");
        }
    }
}
