// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `ConstItemSugar`: a local `const`/`static` item with no assertion-family macro is
// inert compiler-axiom support. The compiler already checked the initializer for
// compiling code; at statement position it is not a scalar assertion surface to be
// lowered through `ConstraintSugar`.
//
// MIGRATION NOTE (Phase-3 ratchet). `ConstItemSugar` is a FULLY MIGRATED leaf:
//   * `recognize` uses ONLY `SourceFragment` typed accessors
//     (`item_const_static_kind_and_name`, `item_const_static_initializer_has_asserts`,
//     `item_const_static_initializer_token_str`) -- no `as_item()` shim, no raw
//     `Item::` match.
//   * `ConstItemSugar` holds NO raw `syn` fields: `kind: &'static str`,
//     `name: String`, `initializer: String` (all fragment-derived host types).

use tracing::debug;

use crate::sugar::claim::ItemSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const ITEM_SUGAR: ItemSugarClaim = ItemSugarClaim::statement_item(
    "const_item",
    crate::sugar::claim::SugarWitnesses::pair(
        // `ConstItemSugar` desugars the declaration itself to `Seq(Vec::new())`;
        // the value proof is still real because const-eval resolves `X` when the
        // consuming assertion is lowered.
        r#"
            #[test]
            fn t_const_item_good() {
                const X: i32 = 5;
                assert_eq!(X, 5);
            }
        "#,
        r#"
            #[test]
            fn t_const_item_bad() {
                const X: i32 = 5;
                assert_eq!(X, 6);
            }
        "#,
    ),
    recognize,
);

fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let (kind, name) = frag.item_const_static_kind_and_name()?;
    if frag.item_const_static_initializer_has_asserts() {
        return None;
    }
    let initializer = frag.item_const_static_initializer_token_str()?;
    Some(Box::new(ConstItemSugar {
        kind,
        name,
        initializer,
    }))
}

struct ConstItemSugar {
    kind: &'static str,
    name: String,
    initializer: String,
}

impl Sugar for ConstItemSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        debug!(
            target: "sugar_lift_rust_tests::sugar::const_item",
            kind = self.kind,
            name = self.name.as_str(),
            initializer = self.initializer.as_str(),
            "const/static item initializer accounted as inert compiler axiom"
        );
        Outcome::Complete(Desugared::Seq(Vec::new()))
    }
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source string -> SourceFragment -> assert observed ->
    // build ConstItemSugar from fragment-derived data -> assert fields.
    // No parse_quote!, no StubTerm, no run(). The struct holds ONLY fragment-derived
    // host types (no raw syn) -- these tests prove the migration is clean.
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Helper: get the first item fragment from a parsed source string.
    fn first_item_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        SourceFragment::from_node(FragNode::Item(&file.items[0]), file_str)
    }

    /// from_src: `const X: i32 = 42;` -> observed "Const", kind "const", name "X",
    /// initializer "42", no asserts. Proves struct holds only Strings, zero raw syn.
    #[test]
    fn from_src_const_item_kind_name_and_initializer() {
        let file = parse_file("const X: i32 = 42;");
        let frag = first_item_frag(&file, "test.rs");

        assert_eq!(frag.observed(), "Const");

        let (kind, name) = frag
            .item_const_static_kind_and_name()
            .expect("Item::Const should give kind+name");
        assert_eq!(kind, "const");
        assert_eq!(name, "X");

        assert!(
            !frag.item_const_static_initializer_has_asserts(),
            "plain integer initializer has no asserts"
        );

        let initializer = frag
            .item_const_static_initializer_token_str()
            .expect("Item::Const should give initializer token str");
        assert_eq!(initializer, "42");

        // Build: struct holds only fragment-derived types -- zero raw syn.
        let node = ConstItemSugar {
            kind,
            name: name.clone(),
            initializer: initializer.clone(),
        };
        assert_eq!(node.kind, "const");
        assert_eq!(node.name, "X");
        assert_eq!(node.initializer, "42");
    }

    /// from_src: `static Y: i32 = 99;` -> observed "Static", kind "static", name "Y",
    /// initializer "99". Proves static items are handled symmetrically with const.
    #[test]
    fn from_src_static_item_kind_name_and_initializer() {
        let file = parse_file("static Y: i32 = 99;");
        let frag = first_item_frag(&file, "test.rs");

        assert_eq!(frag.observed(), "Static");

        let (kind, name) = frag
            .item_const_static_kind_and_name()
            .expect("Item::Static should give kind+name");
        assert_eq!(kind, "static");
        assert_eq!(name, "Y");

        assert!(!frag.item_const_static_initializer_has_asserts());

        let initializer = frag
            .item_const_static_initializer_token_str()
            .expect("Item::Static should give initializer token str");
        assert_eq!(initializer, "99");

        let node = ConstItemSugar {
            kind,
            name: name.clone(),
            initializer: initializer.clone(),
        };
        assert_eq!(node.kind, "static");
        assert_eq!(node.name, "Y");
        assert_eq!(node.initializer, "99");
    }

    /// Discrimination: a non-const/static item (a function def) must return `None`
    /// from `item_const_static_kind_and_name()`, which is the first gate in `recognize`.
    /// Proves non-matching item shapes are filtered out.
    #[test]
    fn discrimination_fn_item_is_not_recognized() {
        let file = parse_file("fn f() {}");
        let frag = first_item_frag(&file, "test.rs");

        assert_eq!(frag.observed(), "FunctionDef");
        assert!(
            frag.item_const_static_kind_and_name().is_none(),
            "FunctionDef should not match const/static accessor"
        );
        // Accessor returns None => recognize() returns None (first gate is `?`)
        assert!(
            frag.item_const_static_initializer_has_asserts() == false,
            "non-item returns false for asserts check"
        );
        assert!(
            frag.item_const_static_initializer_token_str().is_none(),
            "non-item returns None for initializer token str"
        );
    }

    /// Structural: initializer token str for a multi-token expression is
    /// whitespace-normalized. Proves `token_key` normalization is preserved.
    #[test]
    fn structural_initializer_token_str_is_whitespace_normalized() {
        let file = parse_file("const Z: i32 = 1 + 2;");
        let frag = first_item_frag(&file, "test.rs");

        let initializer = frag.item_const_static_initializer_token_str().unwrap();
        // token_key joins with single spaces; exact token repr is "1 + 2"
        assert_eq!(initializer, "1 + 2");
    }
}
