// SPDX-License-Identifier: Apache-2.0
//
// `ZipSugar`: `.zip(rhs)` over two finite literal-derived sequences. Structurally a
// sibling of `chain`: both the receiver and the single argument are built through the
// composite factory. Unlike `chain` (which CONCATENATES the two domains), `zip` pairs the
// domains ELEMENT-WISE and TRUNCATES to the shorter side -- `xs.zip(ys)` yields
// `min(xs.len, ys.len)` tuples `(x_i, y_i)`. Each output element is a 2-tuple, exactly
// mirroring `enumerate`'s `(i, e)` pairing, so a `for (a, b) in xs.iter().zip(ys.iter())`
// loop unrolls over the literal pairs the same way the enumerate counter loop does.
//
// FINITE-OR-REFUSE: both operands must resolve to a composite (a literal array / closed
// range / `&slice` / an adaptor chain over one). A runtime/opaque operand has no composite
// (`has_composite` is false), so the recognizer DECLINES and the generic opaque `method:`
// fallback owns the call -- never a fabricated pairing. A recognized-but-unbounded operand
// (an open range) has no grounded `Seq`, so `into_seq` bails and the node produces nothing.

use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{
    build_composite, has_composite, CompositeFloor, SugarBody, SugarBuildCtx,
};
use crate::sugar::method_family;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::temporal_floor::{
    AdapterFloorOutput, AdapterOutputIterMember, CountedAdapterFloor, IterStanding,
    TemporalFloorRefusal,
};
use crate::{ConstVal, Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "zip",
    SugarRole::Composite,
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
            #[test]
            fn t_zip_good() {
                let got = [1i32, 2, 3].into_iter().zip([10, 20]).count();
                assert_eq!(got, 2);
            }
        "#,
        r#"
            #[test]
            fn t_zip_bad() {
                let got = [1i32, 2, 3].into_iter().zip([10, 20]).count();
                assert_eq!(got, 3);
            }
        "#,
    ),
    recognize_composite,
);

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "zip" || call.args.len() != 1 {
        return None;
    }
    // Both operands resolve through the FACTORY (`has_composite`/`build_composite`), exactly
    // like `chain`. A runtime/opaque operand has no composite -> decline so the opaque
    // `method:` fallback owns the call (the established sound under-claim).
    if !operand_resolves_literal_sequence(&call.receiver, fcx)
        || !operand_resolves_literal_sequence(&call.args[0], fcx)
    {
        return None;
    }
    Some(ZipSugar::new(
        operand_body(&call.receiver, fcx),
        operand_body(&call.args[0], fcx),
    ))
}

fn operand_resolves_literal_sequence(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    has_composite(expr, fcx) || crate::resolves_literal_sequence_in_scope(expr, fcx)
}

/// Pair the two finite domains element-wise, truncating to the shorter: element `l_i` and
/// `r_i` become the tuple `(l_i, r_i)`.
struct ZipSugar {
    left: SugarBody<CompositeFloor>,
    right: SugarBody<CompositeFloor>,
}

impl ZipSugar {
    fn new(left: SugarBody<CompositeFloor>, right: SugarBody<CompositeFloor>) -> Box<dyn Sugar> {
        Box::new(Self { left, right })
    }
}

fn operand_body(expr: &Expr, fcx: &SugarBuildCtx) -> SugarBody<CompositeFloor> {
    SugarBody::from_node(
        method_family::build_literal_sequence_composite(expr, fcx)
            .unwrap_or_else(|| build_composite(expr, fcx)),
    )
}

impl Sugar for ZipSugar {
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        let left = match sequence_from_body(&self.left, ctx, "zip lhs") {
            Ok(seq) => seq,
            Err(outcome) => return outcome,
        };
        let right = match sequence_from_body(&self.right, ctx, "zip rhs") {
            Ok(seq) => seq,
            Err(outcome) => return outcome,
        };
        // `zip` stops at the shorter side: `min(left.len, right.len)` pairs.
        let len = left.len().min(right.len());
        if len > SUGAR_SEQ_CAP as usize {
            panic!("zip sequence length {len} exceeds cap {SUGAR_SEQ_CAP}");
        }
        let floor = ZipFloor::default();
        let left_operand = match floor.derived_operand(left.len()) {
            Ok(operand) => operand,
            Err(outcome) => return outcome,
        };
        let right_operand = match floor.derived_operand(right.len()) {
            Ok(operand) => operand,
            Err(outcome) => return outcome,
        };
        let output = match floor.desugar(left_operand, right_operand, left, right, zip_pair) {
            Ok(output) => output,
            Err(outcome) => return outcome,
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::zip",
            len = output.standing().count(),
            "zipped two finite literal-derived domains (truncated to the shorter)"
        );
        ctx.record_adapter_floor_audit("zip", output.standing().count());
        Outcome::Complete(Desugared::Seq(output.into_items()))
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

fn zip_pair(l: DesugaredElem, r: DesugaredElem) -> DesugaredElem {
    let le = &l.expr;
    let re = &r.expr;
    // The pair EXPR `(l, r)` is always materializable (for EUF keys and the
    // for-loop pattern substitution); the pair VALUE needs BOTH element consts
    // (an opaque side -> no tuple value, like an opaque `enumerate` element).
    let pair_expr: Expr =
        syn::parse_str(&format!("({}, {})", quote::quote!(#le), quote::quote!(#re)))
            .unwrap_or_else(|err| panic!("zip pair expression parse failed: {err}"));
    let pair_cv = match (l.value, r.value) {
        (Some(lv), Some(rv)) => Some(ConstVal::Tuple(vec![lv, rv])),
        _ => None,
    };
    DesugaredElem {
        expr: pair_expr,
        value: pair_cv,
    }
}

#[derive(Clone, Copy)]
struct ZipFloor {
    counted: CountedAdapterFloor,
}

impl Default for ZipFloor {
    fn default() -> Self {
        Self {
            counted: CountedAdapterFloor::new("zip", AdapterOutputIterMember::zip),
        }
    }
}

impl ZipFloor {
    fn derived_operand(&self, count: usize) -> Result<IterStanding, Outcome> {
        self.counted
            .derived_operand(count)
            .map_err(zip_floor_refusal)
    }

    fn desugar<T, U, V, F>(
        &self,
        left_operand: IterStanding,
        right_operand: IterStanding,
        left: Vec<T>,
        right: Vec<U>,
        mut pair: F,
    ) -> Result<AdapterFloorOutput<V>, Outcome>
    where
        F: FnMut(T, U) -> V,
    {
        let expected = left_operand.count().min(right_operand.count());
        let out = left
            .into_iter()
            .zip(right)
            .map(|(left, right)| pair(left, right))
            .collect::<Vec<_>>();
        self.counted
            .assert_output_count(&left_operand, expected, out.len())
            .map_err(zip_floor_refusal)?;
        self.counted.output(out).map_err(zip_floor_refusal)
    }
}

fn zip_floor_refusal(err: TemporalFloorRefusal) -> Outcome {
    Outcome::Incomplete(Effect::CoverageGap {
        boundary: "Iterator::zip".to_string(),
        reason: err.to_string(),
    })
}

fn sequence_from_body(
    body: &SugarBody<CompositeFloor>,
    ctx: &SugarCtx,
    label: &'static str,
) -> Result<Vec<DesugaredElem>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_seq()
            .unwrap_or_else(|| panic!("{label} reduced to non-sequence"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}
