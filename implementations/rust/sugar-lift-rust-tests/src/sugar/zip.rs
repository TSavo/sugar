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
    build_composite, compat_reduction, has_composite, FactoryGap, FactoryReduction, SugarBody,
    SugarBuildCtx,
};
use crate::sugar::method_family;
use crate::{ConstVal, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("zip", SugarRole::Composite, recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
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
    left: SugarBody,
    right: SugarBody,
}

impl ZipSugar {
    fn new(left: SugarBody, right: SugarBody) -> Box<dyn Sugar> {
        Box::new(Self { left, right })
    }
}

fn operand_body(expr: &Expr, fcx: &SugarBuildCtx) -> SugarBody {
    SugarBody::from_node(
        method_family::build_literal_sequence_composite(expr, fcx)
            .unwrap_or_else(|| build_composite(expr, fcx)),
    )
}

impl Sugar for ZipSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        let left = match sequence_from_body(&self.left, ctx, "zip lhs") {
            Ok(seq) => seq,
            Err(reduction) => return reduction,
        };
        let right = match sequence_from_body(&self.right, ctx, "zip rhs") {
            Ok(seq) => seq,
            Err(reduction) => return reduction,
        };
        // `zip` stops at the shorter side: `min(left.len, right.len)` pairs.
        let len = left.len().min(right.len());
        if len > SUGAR_SEQ_CAP as usize {
            return Err(FactoryGap::new(format!(
                "zip sequence length {len} exceeds cap {SUGAR_SEQ_CAP}"
            )));
        }
        let mut out = Vec::with_capacity(len);
        // `Iterator::zip` already halts at the shorter operand, so this yields exactly
        // `len` pairs in source order.
        for (l, r) in left.into_iter().zip(right) {
            let le = &l.expr;
            let re = &r.expr;
            // The pair EXPR `(l, r)` is always materializable (for EUF keys and the
            // for-loop pattern substitution); the pair VALUE needs BOTH element consts
            // (an opaque side -> no tuple value, like an opaque `enumerate` element).
            let pair_expr: Expr =
                syn::parse_str(&format!("({}, {})", quote::quote!(#le), quote::quote!(#re)))
                    .map_err(|err| {
                        FactoryGap::new(format!("zip pair expression parse failed: {err}"))
                    })?;
            let pair_cv = match (l.value, r.value) {
                (Some(lv), Some(rv)) => Some(ConstVal::Tuple(vec![lv, rv])),
                _ => None,
            };
            out.push(DesugaredElem {
                expr: pair_expr,
                value: pair_cv,
            });
        }
        debug!(
            target: "sugar_lift_rust_tests::sugar::zip",
            len = out.len(),
            "zipped two finite literal-derived domains (truncated to the shorter)"
        );
        Ok(Outcome::Complete(Desugared::Seq(out)))
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

fn sequence_from_body(
    body: &SugarBody,
    ctx: &SugarCtx,
    label: &'static str,
) -> Result<Vec<DesugaredElem>, FactoryReduction> {
    match body.reduce(ctx) {
        Ok(Outcome::Complete(d)) => d
            .into_seq()
            .ok_or_else(|| Err(FactoryGap::new(format!("{label} reduced to non-sequence")))),
        Ok(Outcome::Incomplete(effect)) => Err(Ok(Outcome::Incomplete(effect))),
        Err(gap) => Err(Err(gap)),
    }
}
