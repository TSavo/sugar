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

use std::collections::BTreeMap;

use sugar_ir_symbolic::num;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::{
    const_eval, const_eval_unary_closure, scalar_literal_array_elems, strip_refs_groups, Desugared,
    Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("partition_point", SugarRole::Term, recognize);

fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "partition_point" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(closure) = strip_refs_groups(&call.args[0]) else {
        return None;
    };
    let elems = scalar_literal_array_elems(strip_refs_groups(&call.receiver))?;
    let empty: BTreeMap<String, _> = BTreeMap::new();
    let mut preds = Vec::with_capacity(elems.len());
    for e in &elems {
        let value = const_eval(e, &empty)?;
        let pred = const_eval_unary_closure(closure, &value)?.as_bool()?;
        preds.push(pred);
    }
    // The slice must be PARTITIONED: no satisfying element after a non-satisfying
    // one. Otherwise the result is binary-search-defined (a contract misuse) and
    // we decline rather than replicate it.
    let mut seen_false = false;
    for &p in &preds {
        if p && seen_false {
            return None;
        }
        seen_false |= !p;
    }
    let index = preds.iter().filter(|&&p| p).count();
    Some(Box::new(PartitionPointSugar {
        index: index as i128,
    }))
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
