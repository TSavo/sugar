// SPDX-License-Identifier: Apache-2.0
//
// `LiteralSugar`: the BASE-CASE sequence node -- a finite literal domain (a literal
// array `[e0, e1, ...]` or a closed integer range `a..b` / `a..=b`). Relocated
// verbatim from the `lib.rs` monolith (pure code-motion, zero behavior change); the
// shared substrate it calls (`bounded_domain_from_expr`, `const_eval`, `term_as_int`,
// `strip_refs_groups`, `SUGAR_SEQ_CAP`) stays in `crate::` and is imported below.

use std::collections::BTreeMap;

use syn::Expr;

use crate::sugar::factory::FactoryCtx;
use crate::{
    bounded_domain_from_expr, const_eval, strip_refs_groups, term_as_int, BoundedDomain, ConstVal,
    Desugared, DesugaredElem, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP,
};

/// COMPOSITE recognizer for `Expr::Array` / `Expr::Range`: the SEQUENCE-floor
/// [`LiteralSugar`] (a finite literal domain `-> Seq`). Byte-identical to the
/// `Expr::Array(_) | Expr::Range(_) => Box::new(LiteralSugar { base: expr.clone() })`
/// arm of the old fat `build_composite`. DISTINCT from the TERM-position `Expr::Array`
/// (`literal_aggregate_term` ctor) — the two roles genuinely differ (a `Seq` domain vs
/// a term aggregate).
pub(crate) fn recognize_composite(expr: &Expr, _fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Array(_) | Expr::Range(_) => Some(Box::new(LiteralSugar { base: expr.clone() })),
        _ => None,
    }
}

/// BASE CASE: a finite literal domain (a literal array `[e0, e1, ...]` or a closed
/// integer range `a..b` / `a..=b`). `desugar` materializes the element sequence in
/// iterated order, each element its source `Expr` + its `ConstVal` when evaluable.
/// May be SYNTHETIC under an adaptor, but a `LiteralSugar` is the vendor's written
/// construction. The floor: `desugar` = `Some(Seq(literals))`.
pub(crate) struct LiteralSugar {
    pub(crate) base: Expr,
}

impl Sugar for LiteralSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        // TOTAL: the dig body computes the legacy `Option<Desugared>` (every inner `?`
        // is a structural bail); `Outcome::from_opt` lifts it -- `Some` -> `Dug`, the
        // structural bail -> `Hit(Effect::Unsupported)` (discarded by the fall-through
        // consumer exactly as the old `None` was). No unclassified return path.
        Outcome::from_opt((|| {
        // Discriminate the domain EXACTLY as the defolder does (construction axiom:
        // a literal array unrolls over its element terms; a closed range enumerates
        // its integers). A runtime collection is not a `BoundedDomain` -> None.
        let domain = bounded_domain_from_expr(&self.base, ctx.scope)?;
        let seq: Vec<DesugaredElem> = match domain {
            BoundedDomain::Array(_) => match strip_refs_groups(&self.base) {
                Expr::Array(arr) => {
                    if arr.elems.len() as i64 > SUGAR_SEQ_CAP {
                        return None;
                    }
                    arr.elems
                        .iter()
                        .map(|e| DesugaredElem {
                            expr: e.clone(),
                            value: const_eval(e, &BTreeMap::new()),
                        })
                        .collect()
                }
                _ => return None,
            },
            BoundedDomain::Range {
                start,
                end,
                inclusive,
            } => {
                let (Some(s), Some(e)) = (term_as_int(&start), term_as_int(&end)) else {
                    return None;
                };
                // `checked_add`: an inclusive end at i128::MAX would overflow.
                let Some(e) = (if inclusive { e.checked_add(1) } else { Some(e) }) else {
                    return None;
                };
                if e < s || e - s > i128::from(SUGAR_SEQ_CAP) {
                    return None;
                }
                (s..e)
                    .map(|n| DesugaredElem {
                        expr: syn::parse_str::<Expr>(&n.to_string()).unwrap(),
                        value: Some(ConstVal::Int(n)),
                    })
                    .collect()
            }
        };
        if seq.is_empty() {
            return None;
        }
        Some(Desugared::Seq(seq))
        })())
    }
}
