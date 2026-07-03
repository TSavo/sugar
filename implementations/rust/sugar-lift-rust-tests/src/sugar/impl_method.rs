// SPDX-License-Identifier: Apache-2.0
//
// `ImplMethodSugar`: the REFUSE-side node for an `impl` block declared as a STATEMENT inside
// a test fn (`impl Write for W { fn write_str(..) { assert_eq!(..) } }`). It OWNS, in its own
// `desugar`, the single statement-nested impl-method-reachability verdict the old inline
// `Stmt::Item(Item::Impl)` router arm made -- an assertion lexically inside an impl method
// body is reachable ONLY when the method runs, observing the receiver's RUNTIME state
// (`self.done`, an atomic `.load`, a mutated field). There is no single timeless `t` at which
// to read it; the value depends on how many times the method has been driven. A SOURCE
// property (kin to `temporally unstable`), not a missing lifter. Detection is STRUCTURAL: the
// assert is lexically inside an `impl` method body, which only executes at call time. Typed as
// `ImplMethodEffect`. This is the SAME terminal cause as the top-level `Item::Impl` bucket,
// surfaced here because the impl is a statement, not a top-level Item.
//
// THE TARGET SHAPE (`walk -> new -> compose -> desugar() collapses to one Outcome`):
// The recognizer finds the first impl-method body carrying an assertion (via the
// `impl_item_asserting_method_name` SourceFragment accessor) and `new`s the node, composing
// the asserting method's name as the single CHILD LEAF -- with NO degeneracy opinion and no
// early exit (its only `None` is non-recognition: a pure / assert-free impl is not an
// impl-method bucket -- nothing to classify; it stays on the generic unclassified path).
// `desugar` is where the verdict is made, and the single LEAF owns it:
//   * the METHOD leaf: a recognized asserting impl method body is reachable only at call time
//     over the receiver's runtime state -> `ImplMethod`.
// The composite makes NO check of its own: a recognized node always returns Incomplete from
// its `ImplMethod` leaf (recognition -- an asserting method -- IS the verdict's precondition).

use crate::sugar::claim::ItemSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Effect, Outcome, Sugar, SugarCtx};

pub(crate) const ITEM_SUGAR: ItemSugarClaim = ItemSugarClaim::statement_item(
    "impl_method",
    crate::sugar::claim::SugarWitnesses::not_verdict_bearing(
        "ImplMethod",
        "asserting impl methods are runtime effects; call sites own verdict facts",
    ),
    recognize,
);

/// ITEM-position recognizer: `Some` only for a statement-nested `impl` block whose first
/// method body carries an assertion, else `None`. Uses the `impl_item_asserting_method_name`
/// SourceFragment accessor -- no raw `Item::`/`ItemImpl` access in this body.
/// Ctx-independent (the verdict is purely structural).
pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let method = frag.impl_item_asserting_method_name()?;
    Some(Box::new(ImplMethodSugar { method }))
}

/// The statement-nested `impl` block whose method body carries an assertion, composed as a
/// node whose `desugar` makes the impl-method-reachability verdict at its single LEAF (the
/// asserting method). See the module header.
pub(crate) struct ImplMethodSugar {
    /// The first impl-method name that carries an assertion -- the METHOD leaf. The boundary
    /// description is `format!("impl method `{name}`")` (byte-identical to the old arm).
    method: String,
}

impl ImplMethodSugar {
    /// METHOD leaf: a recognized asserting impl method body is reachable ONLY when the method
    /// runs, observing the receiver's RUNTIME state -- no single timeless `t` -> `ImplMethod`.
    /// Recognition (an asserting method) is this leaf's precondition, so it always fires for a
    /// built node; it never completes.
    fn impl_method_effect(&self) -> Effect {
        Effect::ImplMethod {
            boundary: format!("impl method `{}`", self.method),
        }
    }

    pub(crate) fn desugar_ctx_free(&self) -> Outcome {
        Outcome::Incomplete(self.impl_method_effect())
    }
}

impl Sugar for ImplMethodSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        // A built node always names `ImplMethod`; recognition is the verdict's precondition.
        self.desugar_ctx_free()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::source_fragment::{parse_file, SourceFragment};
    use crate::{
        sugar_ctx, Effect, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, TemporalPlan,
        TemporalScope,
    };

    // -- from_src harness: source string -> SourceFragment -> assert observed -> build -> floor --

    #[test]
    fn from_src_asserting_impl_method_recognizes_and_names_impl_method_effect() {
        // source -> SourceFragment
        let src = "impl W { fn write(&self) { assert_eq!(self.done, true); } }";
        let parsed = parse_file(src);
        let item = &parsed.items[0];
        let frag = SourceFragment::item(item, "test.rs");

        // assert observed: this is an Impl item
        assert_eq!(frag.observed(), "Impl");

        // build via recognize
        let scope = TemporalScope::new("impl-method-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = crate::sugar::factory::SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = recognize(&frag, &fcx).expect("asserting impl method should recognize");

        // assert floor: ImplMethod effect with the correct method name
        let items: Vec<syn::Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        match node.desugar(&ctx) {
            Outcome::Incomplete(Effect::ImplMethod { boundary }) => {
                assert_eq!(boundary, "impl method `write`");
            }
            _ => panic!("asserting impl method must name ImplMethod"),
        }
    }

    #[test]
    fn from_src_assert_free_impl_declines_recognition() {
        // source -> SourceFragment
        let src = "impl W { fn write(&self) { let _ = self.done; } }";
        let parsed = parse_file(src);
        let item = &parsed.items[0];
        let frag = SourceFragment::item(item, "test.rs");

        // build: assert-free impl must return None (not a refusal, stays on generic path)
        let scope = TemporalScope::new("impl-method-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = crate::sugar::factory::SugarBuildCtx::new(&scope, &options, &let_inits);
        assert!(
            recognize(&frag, &fcx).is_none(),
            "assert-free impls are not impl-method refusals"
        );
    }
}
