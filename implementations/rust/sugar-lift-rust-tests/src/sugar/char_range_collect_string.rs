// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `CharRangeCollectStringSugar`: stdlib string collection sugar for
// `<literal int range>.map(|b| b as char).collect::<String>()`. The Rust compiler
// has already accepted the cast; we only materialize the finite literal range into
// the exact string it denotes.
//
// MIGRATION NOTE (Phase-3 ratchet). Fully migrated:
//   * `recognize` uses ONLY `SourceFragment` typed accessors -- no `as_expr()`,
//     no `Expr::`/`ExprMethodCall` field access, no raw `syn` in this body.
//   * `CharRangeCollectStringSugar` holds NO raw `syn` field: only
//     `SugarBody<CompositeFloor>` (fragment-derived composite child).

use sugar_ir_symbolic::str_const;
use tracing::debug;

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::source_fragment::SourceFragment;
use crate::{ConstVal, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "char_range_collect_string",
        crate::sugar::claim::SugarWitnesses::temporal_campaign(
            "S5 adapter family: char range collection-to-string",
        ),
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Gate 1: outer `.collect::<String>()` with zero args and String turbofish.
    let collect_frag = frag.strip_refs_groups();
    if !collect_frag.call_is_method_call()
        || collect_frag.call_target_name().as_deref() != Some("collect")
        || collect_frag.call_arg_count() != 0
        || !collect_frag.call_collects_string()
    {
        return None;
    }

    // Gate 2: collect receiver is `.map(<one-arg>)`.
    let map_frag = collect_frag.call_receiver()?.strip_refs_groups();
    if !map_frag.call_is_method_call()
        || map_frag.call_target_name().as_deref() != Some("map")
        || map_frag.call_arg_count() != 1
    {
        return None;
    }

    // Gate 3: the single map argument is a `|param| param as char` closure.
    let closure_frag = map_frag.call_args().into_iter().next()?.strip_refs_groups();
    closure_frag.closure_recognizes_char_cast()?;

    // Gate 4: map receiver resolves to a literal sequence (range/array/vec-lit).
    let receiver_frag = map_frag.call_receiver()?;
    if !receiver_frag.resolves_literal_sequence_frag(fcx) {
        return None;
    }

    debug!(
        target: "sugar_lift_rust_tests::sugar::char_range_collect_string",
        "recognized literal char range collect string"
    );
    Some(Box::new(CharRangeCollectStringSugar {
        seq: SugarBody::from_node(receiver_frag.build_literal_sequence_composite_frag(fcx)?),
    }))
}

struct CharRangeCollectStringSugar {
    seq: SugarBody<CompositeFloor>,
}

impl Sugar for CharRangeCollectStringSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.seq.reduce(ctx) {
            Outcome::Complete(d) => {
                let seq = d.into_seq().unwrap_or_else(|| {
                    char_range_collect_string_gap("receiver reduced to non-sequence")
                });
                let mut out = String::with_capacity(seq.len());
                for elem in seq {
                    let n = elem
                        .value
                        .as_ref()
                        .and_then(ConstVal::as_int)
                        .unwrap_or_else(|| {
                            char_range_collect_string_gap("range element was not a literal int")
                        });
                    let ch = u32::try_from(n)
                        .ok()
                        .and_then(char::from_u32)
                        .unwrap_or_else(|| {
                            char_range_collect_string_gap("range element was not a valid char")
                        });
                    out.push(ch);
                }
                debug!(
                    target: "sugar_lift_rust_tests::sugar::char_range_collect_string",
                    len = out.chars().count(),
                    "literal char range collect string reduced"
                );
                Outcome::Complete(Desugared::Term(str_const(out)))
            }
            Outcome::Incomplete(effect) => Outcome::Incomplete(effect),
        }
    }
}

fn char_range_collect_string_gap(reason: &str) -> ! {
    panic!("char_range_collect_string did not reach a lawful floor: {reason}")
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source string -> SourceFragment -> assert observed ->
    // assert frag accessors -> recognize() -> assert Some/None.
    // No parse_quote!, no StubTerm, no run().
    // The struct holds ONLY `SugarBody<CompositeFloor>` -- zero raw-syn fields --
    // so these tests prove the migration is clean.
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
    use crate::{LiftOptions, TemporalPlan, TemporalScope};
    use std::collections::BTreeMap;
    use syn::Expr;

    /// Navigate to the single tail-expression term in a one-line fn body.
    fn tail_term_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    fn make_fcx<'a, 'e>(
        scope: &'a TemporalScope,
        options: &'a LiftOptions,
        let_inits: &'a BTreeMap<String, &'e Expr>,
    ) -> SugarBuildCtx<'a, 'e> {
        SugarBuildCtx::new(scope, options, let_inits)
    }

    /// Positive: `(b'A'..=b'C').map(|b| b as char).collect::<String>()` is the
    /// exact recognized shape. Verifies the full accessor chain and that recognize
    /// returns Some. Proves the migration is clean: no as_expr / raw Expr:: in
    /// the recognize body.
    #[test]
    fn from_src_byte_range_map_char_cast_collect_string_recognized() {
        let src = "fn f() -> String { (b'A'..=b'C').map(|b| b as char).collect::<String>() }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        // The outer node is a MethodCall (collect).
        assert_eq!(frag.observed(), "MethodCall");

        // Accessor-level proof: collect shape + String turbofish.
        let collect_frag = frag.strip_refs_groups();
        assert!(collect_frag.call_is_method_call());
        assert_eq!(collect_frag.call_target_name().as_deref(), Some("collect"));
        assert_eq!(collect_frag.call_arg_count(), 0);
        assert!(
            collect_frag.call_collects_string(),
            "must carry ::<String> turbofish"
        );

        // map receiver resolves to a literal sequence.
        let map_frag = collect_frag.call_receiver().unwrap().strip_refs_groups();
        assert_eq!(map_frag.call_target_name().as_deref(), Some("map"));
        let receiver_frag = map_frag.call_receiver().unwrap();

        let scope = TemporalScope::new("char-range-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);

        assert!(
            receiver_frag.resolves_literal_sequence_frag(&fcx),
            "b'A'..=b'C' must resolve as a literal sequence"
        );

        // Full recognize path returns Some.
        assert!(
            recognize(&frag, &fcx).is_some(),
            "recognized shape must return Some"
        );
    }

    /// Discrimination: wrong cast target (`b as u32` not `b as char`) -- the
    /// closure_recognizes_char_cast gate rejects it. Verify recognize returns None.
    #[test]
    fn discrimination_wrong_cast_type_not_recognized() {
        let src = "fn f() -> String { (b'A'..=b'C').map(|b| b as u32).collect::<String>() }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");
        // closure arg: cast to u32, not char.
        let collect_frag = frag.strip_refs_groups();
        let map_frag = collect_frag.call_receiver().unwrap().strip_refs_groups();
        let closure_frag = map_frag
            .call_args()
            .into_iter()
            .next()
            .unwrap()
            .strip_refs_groups();
        assert!(
            closure_frag.closure_recognizes_char_cast().is_none(),
            "cast to u32 must NOT pass closure_recognizes_char_cast"
        );

        let scope = TemporalScope::new("char-range-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_none(),
            "wrong cast type must not be recognized"
        );
    }

    /// Structural: an unrelated method call `.len()` is not a MethodCall with
    /// method == "collect" and has no turbofish -- recognize returns None.
    #[test]
    fn structural_unrelated_method_call_not_recognized() {
        let src = "fn f(v: &[u8]) -> usize { v.len() }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");
        // call_target_name is "len", not "collect".
        assert_eq!(frag.call_target_name().as_deref(), Some("len"));
        assert!(
            !frag.call_collects_string(),
            "v.len() has no turbofish -- call_collects_string must be false"
        );

        let scope = TemporalScope::new("char-range-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_none(),
            "v.len() must not be recognized as char_range_collect_string"
        );
    }
}
