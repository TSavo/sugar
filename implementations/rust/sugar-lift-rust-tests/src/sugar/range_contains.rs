// SPDX-License-Identifier: Apache-2.0
//
// `RangeContainsSugar`: `(a..b).contains(&x)` / `(a..=b).contains(&x)` (and the open-ended
// variants) over a range literal with const INTEGER endpoints and a const integer argument
// is value sugar -- membership is determined ENTIRELY by the program text:
//
//   * `a..b`  contains x  iff  a <= x < b,
//   * `a..=b` contains x  iff  a <= x <= b,
//   * `a..`   contains x  iff  a <= x,
//   * `..b`   contains x  iff  x < b,
//   * `..=b`  contains x  iff  x <= b,
//   * `..`    contains x  always.
//
// We COMPUTE the bool at recognize time and lower it to a ground `Bool` const that z3
// reasons about directly (a real value, NOT an opaque `method:contains` EUF var with no
// teeth). TEETH: `assert!((1..5).contains(&3))` -> `Bool(true)` discharged;
// `assert!((1..5).contains(&5))` -> `Bool(false)` -> z3-UNSAT (a wrong claim is REFUTED).
//
// EXACT-OR-NONE. We claim ONLY when the receiver is an INLINE range literal whose present
// endpoints AND the argument all const-fold to an INTEGER scalar (an int/byte literal,
// possibly negated, through paren/group/ref wrappers). A runtime endpoint/argument, a
// let-bound range path (`let r = ..; r.contains(..)` -- fires once the let-desugar lever
// lands), a CHAR range (left to the char lane), or a non-literal argument returns `None`,
// so the generic method machinery keeps its opaque handling (no regression, never a guess).

use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{bool_const, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("range_contains", SugarRole::Term, recognize);

fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // `range_literal_contains_int()` handles all raw syn internally:
    // checks MethodCall shape, receiver is an inline Range, all endpoints/arg
    // const-fold to i128 scalars, computes the bool. No as_expr/raw syn here.
    let value = frag.range_literal_contains_int()?;
    Some(Box::new(RangeContainsSugar { value }))
}

struct RangeContainsSugar {
    /// The compile-time-computed membership result. Holds only a `bool` --
    /// zero raw-syn fields. Desugar lowers this to a ground `Bool` const.
    value: bool,
}

impl Sugar for RangeContainsSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        debug!(
            target: "sugar_lift_rust_tests::sugar::range_contains",
            value = self.value,
            "resolved range contains stdlib axiom to a ground bool"
        );
        Outcome::Complete(Desugared::Term(bool_const(self.value)))
    }
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source string → SourceFragment → assert observed →
    // range_literal_contains_int() → assert value → build struct → assert floor.
    // No parse_quote!, no StubTerm, no run(). The struct holds ONLY `bool` --
    // zero raw-syn fields -- so these tests prove the migration is clean.
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
    use sugar_ir_symbolic::{ConstValue, Term};

    /// Navigate to the single tail-expression term in a one-line fn body.
    fn tail_term_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    /// Positive: `(1..5).contains(&3)` — 3 is in [1,5), folds to `true`.
    /// Proves the accessor computes correctly and the struct holds only `bool`.
    #[test]
    fn from_src_half_open_range_in_bounds_folds_to_true() {
        let src = "fn f() -> bool { (1..5).contains(&3) }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        // observed: a method call
        assert_eq!(frag.observed(), "MethodCall");

        // build: accessor const-folds without any as_expr / raw Expr:: access
        let value = frag
            .range_literal_contains_int()
            .expect("(1..5).contains(&3) must fold");
        assert!(value, "(1..5).contains(&3) is true");

        // struct holds only `bool` -- no raw-syn field
        let sugar = RangeContainsSugar { value };
        assert!(sugar.value);

        // floor: bool_const(true) produces Term::Const { Bool(true) }
        let term = bool_const(sugar.value);
        match term.as_ref() {
            Term::Const {
                value: ConstValue::Bool(b),
                ..
            } => {
                assert!(*b, "expected Bool(true)");
            }
            other => panic!("expected Bool const, got {other:?}"),
        }
    }

    /// Discrimination: `(1..5).contains(&5)` — 5 is NOT in [1,5) (exclusive upper),
    /// folds to `false`. Proves upper-bound exclusion is preserved post-migration.
    #[test]
    fn from_src_half_open_range_at_exclusive_upper_folds_to_false() {
        let src = "fn f() -> bool { (1..5).contains(&5) }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");

        let value = frag
            .range_literal_contains_int()
            .expect("(1..5).contains(&5) must fold");
        assert!(!value, "(1..5).contains(&5) is false -- 5 not in [1,5)");
    }

    /// Structural: a `.len()` call has no range receiver — must return `None`.
    /// Proves the guard does not over-claim on unrelated method calls.
    #[test]
    fn discrimination_non_range_method_call_returns_none() {
        let src = "fn f(v: &[i32]) -> usize { v.len() }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert!(
            frag.range_literal_contains_int().is_none(),
            "v.len() must NOT be recognized as range_contains"
        );
    }
}
