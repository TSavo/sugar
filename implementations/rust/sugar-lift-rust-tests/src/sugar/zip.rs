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
use crate::sugar::factory::{build_composite, has_composite, SugarBuildCtx};
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
    if !has_composite(&call.receiver, fcx) || !has_composite(&call.args[0], fcx) {
        return None;
    }
    Some(Box::new(ZipSugar {
        left: build_composite(&call.receiver, fcx),
        right: build_composite(&call.args[0], fcx),
    }))
}

/// Pair the two finite domains element-wise, truncating to the shorter: element `l_i` and
/// `r_i` become the tuple `(l_i, r_i)`.
struct ZipSugar {
    left: Box<dyn Sugar>,
    right: Box<dyn Sugar>,
}

impl Sugar for ZipSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let left = self.left.desugar(ctx).dug()?.into_seq()?;
            let right = self.right.desugar(ctx).dug()?.into_seq()?;
            // `zip` stops at the shorter side: `min(left.len, right.len)` pairs.
            let len = left.len().min(right.len());
            if len as i64 > SUGAR_SEQ_CAP {
                return None;
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
                        .ok()?;
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
            Some(Desugared::Seq(out))
        })())
    }
}
