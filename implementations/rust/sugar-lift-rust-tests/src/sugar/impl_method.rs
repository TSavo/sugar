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
// `decompose_impl_method` (the `build` arm) recognizes the construct (a statement-nested impl
// whose first method body carries an assertion) and `new`s the node, composing the asserting
// method's name as the single CHILD LEAF -- with NO degeneracy opinion and no early exit (its
// only `None` is non-recognition: a pure / assert-free impl is not an impl-method bucket --
// nothing to classify; it stays on the generic unclassified path). `desugar` is where the
// verdict is made, and the single LEAF owns it:
//   * the METHOD leaf: a recognized asserting impl method body is reachable only at call time
//     over the receiver's runtime state -> `ImplMethod`.
// The composite makes NO check of its own: a recognized node always returns Incomplete from
// its `ImplMethod` leaf (recognition -- an asserting method -- IS the verdict's precondition).

use syn::{Item, ItemImpl};

use crate::sugar::factory::SugarBuildCtx;
use crate::{impl_block_method_name, Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const ITEM_SUGAR: crate::sugar::claim::ItemSugarClaim =
    crate::sugar::claim::ItemSugarClaim::statement_item("impl_method", recognize);

/// ITEM-position recognizer ([`ImplMethodSugar`] via [`decompose_impl_method`]): `Some` only
/// for a statement-nested `impl` block whose first method body carries an assertion, else
/// `None`. The item claim owns the impl-method-reachability verdict in its own `desugar`.
/// An `impl` operates on a `syn::Item`/`ItemImpl`, not an `Expr`, so this is the item-source
/// analogue of the expression `recognize` shape. Ctx-independent (the verdict is purely
/// structural).
pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let item = frag.as_item()?;
    let Item::Impl(imp) = item else {
        return None;
    };
    decompose_impl_method(imp).map(|node| Box::new(node) as Box<dyn Sugar>)
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

/// Build (`new` + compose, NO degeneracy opinion) an `ImplMethodSugar` from a statement-nested
/// `impl` block. Recognizes the construct: the FIRST impl method whose body carries an
/// assertion (reusing the shared `impl_block_method_name` scanner). Returns `None` (declines to
/// RECOGNIZE) for a pure / assert-free impl block -- it is NOT refused; it stays on the generic
/// unclassified path. It makes NO verdict -- the impl-method-reachability decision is
/// `ImplMethodSugar::desugar`'s (and its leaf's) alone.
pub(crate) fn decompose_impl_method(imp: &ItemImpl) -> Option<ImplMethodSugar> {
    let method = impl_block_method_name(imp)?;
    Some(ImplMethodSugar { method })
}

#[cfg(test)]
mod tests {
    use super::*;
    use syn::Item;

    #[test]
    fn asserting_impl_method_desugars_to_named_impl_method_effect() {
        let item: Item =
            syn::parse_str("impl W { fn write(&self) { assert_eq!(self.done, true); } }").unwrap();
        let Item::Impl(imp) = item else {
            panic!("expected impl item")
        };

        let node = decompose_impl_method(&imp).expect("asserting impl method should construct");
        match node.desugar_ctx_free() {
            Outcome::Incomplete(Effect::ImplMethod { boundary }) => {
                assert_eq!(boundary, "impl method `write`");
            }
            _ => panic!("asserting impl method must name ImplMethod"),
        }
    }

    #[test]
    fn assert_free_impl_declines_impl_method_sugar() {
        let item: Item =
            syn::parse_str("impl W { fn write(&self) { let _ = self.done; } }").unwrap();
        let Item::Impl(imp) = item else {
            panic!("expected impl item")
        };

        assert!(
            decompose_impl_method(&imp).is_none(),
            "assert-free impls are not impl-method refusals"
        );
    }
}
