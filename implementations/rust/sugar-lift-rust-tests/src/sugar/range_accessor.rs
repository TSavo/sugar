// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Literal `RangeInclusive` endpoint accessors.
//
// `RangeInclusive::{start,end}` returns shared references to the written endpoints.  For an
// inline inclusive range, this is value sugar: lower to `ref(<endpoint floor>)` so the existing
// unary deref rule can reduce `*(a..=b).start()` / `*(a..=b).end()` through the endpoint's own
// floor. Recognition is deliberately syntactic and lazy: it selects the endpoint site and
// constructs the endpoint child body without reducing it. Desugar/reduce owns the terminal
// decision and bubbles any endpoint effect.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_dispatch::{DesugaredFloorAccept, RequiredTermVisitor};
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "range_accessor",
        &["method"],
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_range_accessor_good() {
                    assert_eq!(*(0..=10).start(), 0);
                }
            "#,
            r#"
                #[test]
                fn t_range_accessor_bad() {
                    assert_eq!(*(0..=10).start(), 1);
                }
            "#,
        ),
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Must be a zero-arg method call named "start" or "end".
    if !frag.call_is_method_call() {
        return None;
    }
    if frag.call_arg_count() != 0 {
        return None;
    }
    let kind = match frag.call_target_name()?.as_str() {
        "start" => EndpointKind::Start,
        "end" => EndpointKind::End,
        _ => return None,
    };
    // Receiver (after stripping refs/groups) must be an inclusive range.
    let receiver = frag.call_receiver()?.strip_refs_groups();
    if !receiver.range_is_closed() {
        return None;
    }
    // Extract the appropriate endpoint fragment.
    let endpoint_frag = match kind {
        EndpointKind::Start => receiver.range_start_frag(),
        EndpointKind::End => receiver.range_end_frag(),
    }?;
    Some(RangeAccessorSugar::new(SugarBody::term_frag(
        &endpoint_frag,
        fcx,
    )))
}

#[derive(Clone, Copy)]
enum EndpointKind {
    Start,
    End,
}

struct RangeAccessorSugar {
    endpoint: SugarBody<TermFloor>,
}

impl Sugar for RangeAccessorSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let endpoint = match self.endpoint.reduce(ctx) {
            Outcome::Complete(d) => d.accept_desugared_floor(RequiredTermVisitor {
                owner: "range accessor endpoint",
            }),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: "ref".to_string(),
            args: vec![endpoint],
        })))
    }
}

impl RangeAccessorSugar {
    fn new(endpoint: SugarBody<TermFloor>) -> Box<dyn Sugar> {
        Box::new(Self { endpoint })
    }
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source -> SourceFragment -> observed -> build -> floor.
    // No parse_quote!, no StubTerm, no run().
    // Proves: recognize body has zero as_expr/raw-syn; struct holds only SugarBody<TermFloor>.
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Navigate to the single tail-expression in a one-liner fn body.
    fn tail_term_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let fn_frag = SourceFragment::from_node(FragNode::Item(&file.items[0]), file_str);
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        stmts[0].terms()[0]
    }

    /// Positive: `(1_u8..=10_u8).start()` — an inclusive range, ".start", zero args.
    /// Proves recognition fires and the accessor path uses zero as_expr.
    #[test]
    fn from_src_incl_range_start_is_recognized() {
        let src = "fn f(r: std::ops::RangeInclusive<u8>) -> &u8 { (1_u8..=10_u8).start() }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "t.rs");

        assert_eq!(frag.observed(), "MethodCall");
        // call_target_name returns "start"
        assert_eq!(frag.call_target_name().as_deref(), Some("start"));
        // call_arg_count is 0
        assert_eq!(frag.call_arg_count(), 0);
        // receiver after strip is a closed Range
        let receiver = frag.call_receiver().unwrap().strip_refs_groups();
        assert!(
            receiver.range_is_closed(),
            "1_u8..=10_u8 must be a closed range"
        );
        // start frag exists
        assert!(
            receiver.range_start_frag().is_some(),
            "start endpoint must be present"
        );
    }

    /// Discrimination: `(1_u8..=10_u8).end()` — inclusive range, ".end" variant.
    /// Proves the end arm is also recognized and range_end_frag returns a fragment.
    #[test]
    fn from_src_incl_range_end_is_recognized() {
        let src = "fn f() -> &u8 { (1_u8..=10_u8).end() }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "t.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert_eq!(frag.call_target_name().as_deref(), Some("end"));
        assert_eq!(frag.call_arg_count(), 0);
        let receiver = frag.call_receiver().unwrap().strip_refs_groups();
        assert!(receiver.range_is_closed());
        assert!(receiver.range_end_frag().is_some());
    }

    /// Structural: `(1_u8..10_u8).start()` — HALF-OPEN range; must return None.
    /// Proves the `range_is_closed()` guard rejects non-inclusive ranges.
    #[test]
    fn from_src_half_open_range_start_not_recognized() {
        let src = "fn f() -> usize { (1_u8..10_u8).start() }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "t.rs");

        assert_eq!(frag.observed(), "MethodCall");
        // receiver is a half-open range — must not be recognized
        let receiver = frag.call_receiver().unwrap().strip_refs_groups();
        assert!(
            !receiver.range_is_closed(),
            "1_u8..10_u8 is half-open; range_is_closed must be false"
        );
    }
}
