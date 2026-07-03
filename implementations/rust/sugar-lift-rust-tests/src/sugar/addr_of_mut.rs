// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `addr_of_mut!(place)`: this constructs a write-capable
// raw-pointer capability. Construction is inert; assignment/call consumers own
// the temporal effect by delegating through the alias ledger.
//
// DEEP MIGRATION (Phase-3 ratchet -- FULLY MIGRATED).
//   * The recognize body uses ONLY SourceFragment typed accessors
//     (`macro_name`, `macro_args_with`, `SugarBody::term_frag`) -- no
//     `as_expr`, no raw `Expr::`/syn field access in the body.
//   * `AddrOfMutSugar` holds `target: SugarBody<TermFloor>` -- zero raw syn fields.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "addr_of_mut",
    &["macro_term"],
    crate::sugar::claim::SugarWitnesses::Pending,
    recognize,
);

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.macro_name().as_deref() != Some("addr_of_mut") {
        return None;
    }
    let mut target: Option<SugarBody<TermFloor>> = None;
    if !frag.macro_args_with(|arg_frag| {
        target = Some(SugarBody::term_frag(&arg_frag, fcx));
    }) {
        return None;
    }
    Some(Box::new(AddrOfMutSugar { target: target? }))
}

struct AddrOfMutSugar {
    target: SugarBody<TermFloor>,
}

impl Sugar for AddrOfMutSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let target = match self.target.reduce(ctx) {
            Outcome::Complete(desugared) => desugared
                .into_term()
                .unwrap_or_else(|| panic!("addr_of_mut! target completed as non-term")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: "addr_of_mut".to_string(),
            args: vec![target],
        })))
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::rc::Rc;

    use super::*;
    use crate::sugar::factory::SugarBuildCtx;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
    use crate::{
        sugar_ctx, Desugared, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, TemporalPlan,
        TemporalScope,
    };
    use sugar_ir_symbolic::Term;
    use syn::{Expr, Item};

    // Navigate to the tail expression inside `fn f(...) { <expr> }`.
    fn macro_frag_from_fn<'a>(file: &'a syn::File) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "test.rs");
        let body = frag.function_body().expect("fn body");
        let stmts = body.statements();
        stmts[0].terms()[0]
    }

    // -- from_src tests: source -> SourceFragment -> observed -> build -> floor --

    /// Positive: `addr_of_mut!(x)` is classified as `"Macro"`, recognized by the
    /// recognizer, and reduces to `Term::Ctor { name: "addr_of_mut", args: [Var("x")] }`.
    /// Struct holds `SugarBody<TermFloor>` -- no raw syn fields.
    #[test]
    fn from_src_addr_of_mut_recognized_and_reduces() {
        let file = parse_file("fn f(x: i32) { addr_of_mut!(x) }");
        let frag = macro_frag_from_fn(&file);

        // observed
        assert_eq!(frag.observed(), "Macro");
        // macro_name accessor (no as_expr / raw Expr:: in recognize body)
        assert_eq!(frag.macro_name().as_deref(), Some("addr_of_mut"));
        assert_eq!(frag.macro_arg_count(), Some(1));

        let scope = TemporalScope::new("addr-of-mut-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let sugar = recognize(&frag, &fcx).expect("addr_of_mut!(x) must be recognized");

        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        let Outcome::Complete(Desugared::Term(term)) = sugar.desugar(&ctx) else {
            panic!("expected Complete(Term)");
        };
        let Term::Ctor { name, args } = term.as_ref() else {
            panic!("expected Ctor, got {term:?}");
        };
        assert_eq!(name, "addr_of_mut");
        assert_eq!(args.len(), 1);
        assert!(matches!(args[0].as_ref(), Term::Var { name } if name == "x"));
    }

    /// Discrimination: a macro with a different name (`vec!`) is NOT recognized.
    /// Same `"Macro"` observed shape -- proves the name check distinguishes correctly.
    #[test]
    fn from_src_different_macro_name_not_recognized() {
        let file = parse_file("fn f() { vec![1, 2, 3] }");
        let frag = macro_frag_from_fn(&file);

        assert_eq!(frag.observed(), "Macro");
        assert_ne!(frag.macro_name().as_deref(), Some("addr_of_mut"));

        let scope = TemporalScope::new("addr-of-mut-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        assert!(
            recognize(&frag, &fcx).is_none(),
            "vec![...] must not be recognized by addr_of_mut"
        );
    }

    /// Structural: a non-Macro fragment (`BinOp`) returns `None` from `macro_name()`
    /// and `None` from `recognize` -- confirms the accessor is shape-specific.
    #[test]
    fn from_src_non_macro_fragment_not_recognized() {
        let file = parse_file("fn f(a: i32, b: i32) -> i32 { a + b }");
        let frag = macro_frag_from_fn(&file);

        assert_eq!(frag.observed(), "BinOp");
        assert_eq!(frag.macro_name(), None);

        let scope = TemporalScope::new("addr-of-mut-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        assert!(
            recognize(&frag, &fcx).is_none(),
            "BinOp must not be recognized by addr_of_mut"
        );
    }

    // -- end-to-end reduce (unchanged behavior) --

    fn reduce(src: &str) -> Rc<Term> {
        let expr: Expr = syn::parse_str(src).expect("parse addr_of_mut expr");
        let scope = TemporalScope::new("addr-of-mut-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = {
            let frag = SourceFragment::expr(&expr, "<src>");
            recognize(&frag, &fcx)
        }
        .expect("addr_of_mut sugar recognizes");
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        let Outcome::Complete(Desugared::Term(term)) = node.desugar(&ctx) else {
            panic!("addr_of_mut sugar should complete as an inert capability term")
        };
        term
    }

    #[test]
    fn addr_of_mut_constructs_capability_floor() {
        let term = reduce("addr_of_mut!(x)");
        let Term::Ctor { name, args } = term.as_ref() else {
            panic!("expected addr_of_mut ctor, got {term:?}");
        };
        assert_eq!(name, "addr_of_mut");
        assert_eq!(args.len(), 1);
        assert!(matches!(args[0].as_ref(), Term::Var { name } if name == "x"));
    }
}
