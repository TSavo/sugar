// SPDX-License-Identifier: Apache-2.0
//
// `PartitionPointSugar`: `[literal].partition_point(|x| <pred>)` over a literal
// scalar slice with a lift-known predicate closure is value sugar.
// `partition_point` is a binary search that ASSUMES the slice is partitioned by
// the predicate (all elements satisfying it precede all that do not); the result
// is the index of the first non-satisfying element -- equivalently the COUNT of
// leading satisfying elements. We evaluate the predicate on each literal element
// in the host and fold the count, lowering a ground `usize` index that replaces
// the opaque `method:partition_point` EUF var (no teeth).
//
// EXACT-OR-NONE. We claim ONLY when (a) the receiver is a literal scalar array,
// (b) the single closure argument's body const-evaluates to a bool at every
// element, AND (c) the predicate results are actually PARTITIONED (no satisfying
// element follows a non-satisfying one). A runtime receiver/element, a non-const
// predicate body, or a NON-partitioned result (a contract misuse whose value is
// binary-search-defined -- we will not replicate/guess it) -> `None`, leaving the
// existing opaque handling (no regression, never a guess).
//
// TEETH. `[1,2,3,4,5].partition_point(|&x| x < 3)` -> `2` (elements 1,2 satisfy);
// a claim of `3` is z3-UNSAT (refuted).

use sugar_ir_symbolic::num;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("partition_point", SugarRole::Term, recognize);

fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let index = frag.partition_point_literal_index()?;
    Some(Box::new(PartitionPointSugar { index }))
}

struct PartitionPointSugar {
    index: i128,
}

impl Sugar for PartitionPointSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        debug!(
            target: "sugar_lift_rust_tests::sugar::partition_point",
            index = self.index as i64,
            "resolved literal-slice partition_point stdlib axiom to a ground index"
        );
        Outcome::Complete(Desugared::Term(num(self.index)))
    }
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source string -> SourceFragment -> assert observed ->
    // invoke partition_point_literal_index() -> assert index -> build struct ->
    // assert field. No parse_quote!, no StubTerm, no run().
    // The struct holds ONLY `index: i128` -- zero raw-syn fields -- so these
    // tests prove the migration is clean.
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Navigate to the tail expression fragment inside `fn f() { <expr> }`.
    fn method_call_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        let tail = &stmts[0];
        let terms = tail.terms();
        terms.into_iter().next().expect("method call in tail")
    }

    /// Positive: `[1,2,3,4,5].partition_point(|&x| x < 3)` folds to index 2.
    /// Proves observed shape, index value, and that the Sugar struct holds only
    /// `index: i128` (no raw syn).
    #[test]
    fn from_src_partition_point_folds_to_index() {
        let src = "fn f() -> usize { [1, 2, 3, 4, 5].partition_point(|&x| x < 3) }";
        let file = parse_file(src);
        let frag = method_call_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");

        let idx = frag
            .partition_point_literal_index()
            .expect("must fold to index");
        assert_eq!(idx, 2_i128, "elements 1,2 satisfy x<3; index is 2");

        // Build: struct holds only i128 -- no raw syn field.
        let sugar = PartitionPointSugar { index: idx };
        assert_eq!(sugar.index, 2_i128);
    }

    /// Discrimination: a method call that is NOT `partition_point` must return None.
    /// Proves the method-name guard filters correctly.
    #[test]
    fn discrimination_unrelated_method_returns_none() {
        let src = "fn f() -> usize { [1, 2, 3].len() }";
        let file = parse_file(src);
        let frag = method_call_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert!(
            frag.partition_point_literal_index().is_none(),
            "`.len()` is not partition_point -- must return None"
        );
    }

    /// Structural: a non-partitioned input returns None (no guessing); a correctly
    /// partitioned reversed-predicate input folds to the right count.
    #[test]
    fn structural_non_partitioned_returns_none_partitioned_folds() {
        // Non-partitioned: [1,3,2] with x<3 gives true,false,true -- not partitioned.
        let src_bad = "fn f() -> usize { [1, 3, 2].partition_point(|&x| x < 3) }";
        let file_bad = parse_file(src_bad);
        let frag_bad = method_call_frag(&file_bad, "f.rs");
        assert!(
            frag_bad.partition_point_literal_index().is_none(),
            "non-partitioned slice must return None"
        );

        // Partitioned with descending + >: [5,4,3] with x>3 gives true,true,false -> index 2.
        let src_ok = "fn f() -> usize { [5, 4, 3].partition_point(|&x| x > 3) }";
        let file_ok = parse_file(src_ok);
        let frag_ok = method_call_frag(&file_ok, "f.rs");
        assert_eq!(frag_ok.observed(), "MethodCall");
        assert_eq!(
            frag_ok.partition_point_literal_index(),
            Some(2_i128),
            "[5,4,3] with x>3: elements 5,4 satisfy; index is 2"
        );
        // Struct field is a plain i128 -- no raw syn leaks.
        let sugar = PartitionPointSugar { index: 2 };
        assert_eq!(sugar.index, 2_i128);
    }
}
