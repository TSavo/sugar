// SPDX-License-Identifier: Apache-2.0
//
// LiteralSugar -- the finite-literal-domain base case.
//
// Moved verbatim from lib.rs in the file-split refactor (one file per Sugar
// class). Behaviour-preserving: the desugar logic is byte-identical to the
// monolith; only its physical location changed.

use std::collections::BTreeMap;

use syn::Expr;

use crate::*;

/// BASE CASE: a finite literal domain (a literal array `[e0, e1, ...]` or a closed
/// integer range `a..b` / `a..=b`). `desugar` materializes the element sequence in
/// iterated order, each element its source `Expr` + its `ConstVal` when evaluable.
/// May be SYNTHETIC under an adaptor, but a `LiteralSugar` is the vendor's written
/// construction. The floor: `desugar` = `Some(Seq(literals))`.
pub(crate) struct LiteralSugar {
    pub(crate) base: Expr,
}

/// Maximum desugared sequence length (a finite-construction guard shared by every
/// sequence class). Mirrors the defolder's `CAP`.
pub(crate) const SUGAR_SEQ_CAP: i64 = 4096;

impl Sugar for LiteralSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Option<Desugared> {
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
                let e = if inclusive { e + 1 } else { e };
                if e < s || e - s > SUGAR_SEQ_CAP {
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
    }
}
