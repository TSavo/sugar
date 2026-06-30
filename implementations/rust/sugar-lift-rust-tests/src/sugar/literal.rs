// SPDX-License-Identifier: Apache-2.0
//
// `LiteralSugar`: the BASE-CASE sequence node -- a finite literal domain (a literal
// array `[e0, e1, ...]` or a closed integer range `a..b` / `a..=b`). Relocated
// verbatim from the `lib.rs` monolith (pure code-motion, zero behavior change); the
// shared substrate it calls (`bounded_domain_from_expr`, `const_eval`, `term_as_int`,
// `strip_refs_groups`, `SUGAR_SEQ_CAP`) stays in `crate::` and is imported below.

use std::collections::BTreeMap;

use syn::{Expr, Lit, UnOp};

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    bounded_domain_from_expr, const_eval, const_fold_int_term, const_fold_u128_term,
    literal_byte_string_value, primitive_int_kind, strip_refs_groups, term_as_int, token_key,
    u128_expr, BoundedDomain, ConstVal, Desugared, DesugaredElem, Effect, Outcome,
    PrimitiveIntKind, Sugar, SugarCtx, SUGAR_SEQ_CAP,
};

// ── NAMED-DRAGON reasons for the six unwarrantable literal SHAPES ─────────────────────
//
// A `LiteralSugar` whose warrant attempt declines is, today, the GENERIC structural
// backstop (`unresolved` -- reads like "missing lifter"). For the shapes below the decline
// is NOT missing work -- it is a SOURCE property no better lifter could get past, so each is
// NAMED with a precise reason here and whitelisted as `Disposition::Refused` in
// `crate::refusal_disposition`. PURE RECLASSIFICATION: the warrant path (`build`) runs FIRST
// and is byte-unchanged, so a finite/nonempty/text-determined domain STILL warrants -- the
// naming below is only ever reached on a decline the old code already produced (no warrant
// can become a refusal here). Reasons are matched by SUBSTRING in `refusal_disposition`;
// keep them distinctive.
pub(crate) const EMPTY_DOMAIN_REASON: &str =
    "literal domain is empty -- vacuously true, no element to assert (no teeth)";
pub(crate) const UNBOUNDED_RANGE_REASON: &str =
    "literal range is unbounded -- domain not finitely enumerable";
pub(crate) const OVERSIZE_DOMAIN_REASON: &str =
    "literal domain exceeds SUGAR_SEQ_CAP -- finite but over-cap, infeasible to enumerate";
pub(crate) const CHAR_RANGE_REASON: &str =
    "literal char range -- surrogate-gap / AsciiChar enumeration is Unicode-version-dependent";
pub(crate) const RUNTIME_BOUND_REASON: &str =
    "literal range bound is not text-determined (runtime value)";
pub(crate) const RUNTIME_ELEM_REASON: &str =
    "literal array element is not text-determined (runtime value)";

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("literal", recognize_composite);

/// COMPOSITE recognizer for `Expr::Array` / `Expr::Range`: the SEQUENCE-floor
/// [`LiteralSugar`] (a finite literal domain `-> Seq`). Byte-identical to the
/// `Expr::Array(_) | Expr::Range(_) => Box::new(LiteralSugar { base: expr.clone() })`
/// arm of the old fat `build_composite`. DISTINCT from the TERM-position `Expr::Array`
/// (`literal_aggregate_term` ctor) — the two roles genuinely differ (a `Seq` domain vs
/// a term aggregate).
pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    _fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    match expr {
        Expr::Array(_) | Expr::Range(_) => Some(Box::new(LiteralSugar { base: expr.clone() })),
        _ if literal_byte_string_value(expr).is_some() => {
            Some(Box::new(LiteralSugar { base: expr.clone() }))
        }
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
        // WARRANT FIRST (byte-unchanged): a finite/nonempty/text-determined literal domain
        // builds its element `Seq` and completes. This path is identical to the old code, so no
        // warrantable literal can become a refusal below.
        if let Some(seq) = self.build(ctx) {
            return Outcome::Complete(seq);
        }
        // The warrant declined. If the SHAPE is one of the six unwarrantable literal dragons
        // (empty / unbounded / over-cap / char / runtime-bound / runtime-element), NAME it as a
        // `Refused` source property instead of leaving it the generic structural backstop
        // (`unresolved`, which reads as missing work). A genuinely-unrecognized decline stays
        // the generic backstop. PURE RECLASSIFICATION -- only declines are ever named.
        if let Some(reason) = classify_unwarrantable_literal(&self.base) {
            return Outcome::Incomplete(Effect::LiteralDomain {
                boundary: token_key(&self.base),
                reason: reason.to_string(),
            });
        }
        panic!(
            "literal domain sugar declined outside its classified source boundaries: `{}`",
            token_key(&self.base)
        )
    }
}

impl LiteralSugar {
    /// The WARRANT path: build the element `Seq` for a finite literal domain, or `None` on a
    /// decline (empty / over-cap / non-const / runtime). Byte-identical to the former
    /// `desugar` complete body (pure extraction) so warrant behavior is unchanged.
    fn build(&self, ctx: &SugarCtx) -> Option<Desugared> {
        (|| {
            if let Some(seq) = literal_ascii_char_range_seq(&self.base) {
                return Some(Desugared::Seq(seq));
            }
            if let Some(seq) = literal_byte_string_seq(&self.base) {
                return Some(Desugared::Seq(seq));
            }

            // Discriminate the domain EXACTLY as the defolder does (construction axiom:
            // a literal array unrolls over its element terms; a closed range enumerates
            // its integers). A runtime collection is not a `BoundedDomain` -> None.
            let domain = bounded_domain_from_expr(&self.base, ctx.scope)?;
            let seq: Vec<DesugaredElem> = match domain {
                BoundedDomain::Array(_) => match strip_refs_groups(&self.base) {
                    Expr::Array(arr) => {
                        if arr.elems.len() > SUGAR_SEQ_CAP as usize {
                            return None;
                        }
                        let element_kind = array_primitive_element_kind(arr);
                        arr.elems
                            .iter()
                            .map(|e| DesugaredElem {
                                expr: e.clone(),
                                value: const_eval(e, &BTreeMap::new()).and_then(|value| {
                                    coerce_array_element_value(value, element_kind)
                                }),
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
                    if let (Some(s), Some(e)) =
                        (const_fold_u128_term(&start), const_fold_u128_term(&end))
                    {
                        if e < s {
                            return None;
                        }
                        let len = e
                            .checked_sub(s)?
                            .checked_add(if inclusive { 1 } else { 0 })?;
                        if len == 0 || len > SUGAR_SEQ_CAP as u128 {
                            return None;
                        }
                        return Some(Desugared::Seq(
                            (0..len)
                                .map(|offset| {
                                    let n = s.checked_add(offset)?;
                                    Some(DesugaredElem {
                                        expr: u128_expr(n)?,
                                        value: Some(ConstVal::UInt128(n)),
                                    })
                                })
                                .collect::<Option<Vec<_>>>()?,
                        ));
                    }
                    let (Some(s), Some(e)) = (
                        term_as_int(&start).or_else(|| const_fold_int_term(&start)),
                        term_as_int(&end).or_else(|| const_fold_int_term(&end)),
                    ) else {
                        return None;
                    };
                    if e < s {
                        return None;
                    }
                    let span = e.checked_sub(s)?;
                    let len = span.checked_add(if inclusive { 1 } else { 0 })?;
                    if len == 0 || len > i128::from(SUGAR_SEQ_CAP) {
                        return None;
                    }
                    (0..len)
                        .map(|offset| {
                            let n = s.checked_add(offset)?;
                            Some(DesugaredElem {
                                expr: syn::parse_str::<Expr>(&n.to_string()).ok()?,
                                value: Some(ConstVal::Int(n)),
                            })
                        })
                        .collect::<Option<Vec<_>>>()?
                }
            };
            if seq.is_empty() {
                return None;
            }
            Some(Desugared::Seq(seq))
        })()
    }
}

fn array_primitive_element_kind(arr: &syn::ExprArray) -> Option<PrimitiveIntKind> {
    arr.elems.iter().find_map(expr_primitive_int_kind)
}

fn expr_primitive_int_kind(expr: &Expr) -> Option<PrimitiveIntKind> {
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => match &lit.lit {
            Lit::Int(int) if !int.suffix().is_empty() => primitive_int_kind(int.suffix()),
            _ => None,
        },
        Expr::Unary(unary) if matches!(unary.op, UnOp::Neg(_)) => {
            expr_primitive_int_kind(&unary.expr)
        }
        _ => None,
    }
}

fn coerce_array_element_value(value: ConstVal, kind: Option<PrimitiveIntKind>) -> Option<ConstVal> {
    let Some(kind) = kind else {
        return Some(value);
    };
    match value {
        ConstVal::Int(value) => coerce_int_to_kind(value, kind),
        other => Some(other),
    }
}

fn coerce_int_to_kind(value: i128, kind: PrimitiveIntKind) -> Option<ConstVal> {
    let raw = if kind.signed {
        if !signed_int_fits_kind(value, kind) {
            return None;
        }
        mask_i128_to_kind(value, kind)
    } else {
        let value = u128::try_from(value).ok()?;
        if value > unsigned_max_for_kind(kind) {
            return None;
        }
        mask_u128_to_kind(value, kind)
    };
    if kind.name == "u128" {
        Some(ConstVal::UInt128(raw))
    } else {
        Some(ConstVal::PrimitiveInt { raw, kind })
    }
}

fn signed_int_fits_kind(value: i128, kind: PrimitiveIntKind) -> bool {
    let min = if kind.bits == 128 {
        i128::MIN
    } else {
        -(1i128 << (kind.bits - 1))
    };
    let max = if kind.bits == 128 {
        i128::MAX
    } else {
        (1i128 << (kind.bits - 1)) - 1
    };
    (min..=max).contains(&value)
}

fn unsigned_max_for_kind(kind: PrimitiveIntKind) -> u128 {
    if kind.bits == 128 {
        u128::MAX
    } else {
        (1u128 << kind.bits) - 1
    }
}

fn mask_i128_to_kind(value: i128, kind: PrimitiveIntKind) -> u128 {
    mask_u128_to_kind(value as u128, kind)
}

fn mask_u128_to_kind(value: u128, kind: PrimitiveIntKind) -> u128 {
    if kind.bits == 128 {
        value
    } else {
        value & ((1u128 << kind.bits) - 1)
    }
}

fn literal_ascii_char_range_seq(expr: &Expr) -> Option<Vec<DesugaredElem>> {
    let Expr::Range(range) = strip_refs_groups(expr) else {
        return None;
    };
    let start = literal_ascii_char(range.start.as_deref()?)?;
    let end = literal_ascii_char(range.end.as_deref()?)?;
    if end < start {
        return None;
    }
    let inclusive = matches!(range.limits, syn::RangeLimits::Closed(_));
    let len = end
        .checked_sub(start)?
        .checked_add(if inclusive { 1 } else { 0 })?;
    if len == 0 || len > SUGAR_SEQ_CAP as u32 {
        return None;
    }
    (0..len)
        .map(|offset| {
            let ch = char::from_u32(start.checked_add(offset)?)?;
            Some(DesugaredElem {
                expr: Expr::Lit(syn::ExprLit {
                    attrs: Vec::new(),
                    lit: syn::Lit::Char(syn::LitChar::new(ch, proc_macro2::Span::call_site())),
                }),
                value: Some(ConstVal::Char(ch)),
            })
        })
        .collect()
}

fn literal_byte_string_seq(expr: &Expr) -> Option<Vec<DesugaredElem>> {
    let bytes = literal_byte_string_value(expr)?;
    if bytes.is_empty() || bytes.len() > SUGAR_SEQ_CAP as usize {
        return None;
    }
    bytes
        .into_iter()
        .map(|byte| {
            Some(DesugaredElem {
                expr: byte_expr(byte)?,
                value: Some(ConstVal::Int(i128::from(byte))),
            })
        })
        .collect()
}

fn byte_expr(byte: u8) -> Option<Expr> {
    syn::parse_str(&format!("{byte}u8")).ok()
}

fn literal_ascii_char(expr: &Expr) -> Option<u32> {
    match strip_refs_groups(expr) {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Char(ch),
            ..
        }) if ch.value().is_ascii() => Some(u32::from(ch.value())),
        _ => None,
    }
}

/// Classify a DECLINED `LiteralSugar` base into one of the six unwarrantable-literal dragon
/// reasons, or `None` for a shape outside the six (-> generic structural backstop). PURELY
/// SYNTACTIC: it reads only the AST shape and is reached ONLY after the warrant path declined,
/// so it can never turn a warrant into a refusal. Each arm's discrimination twin (the finite /
/// nonempty / text-determined counterpart) still warrants because `build` returns first.
fn classify_unwarrantable_literal(base: &Expr) -> Option<&'static str> {
    match strip_refs_groups(base) {
        Expr::Array(arr) => {
            if arr.elems.is_empty() {
                // `[]` -- zero iterations, vacuously true; no twin can refute (no teeth).
                Some(EMPTY_DOMAIN_REASON)
            } else if arr.elems.len() > SUGAR_SEQ_CAP as usize {
                Some(OVERSIZE_DOMAIN_REASON)
            } else {
                // A non-empty, in-cap array that DECLINED can only have an element the term
                // floor could not pin to a text-determined value (a runtime/effect element).
                Some(RUNTIME_ELEM_REASON)
            }
        }
        Expr::Range(range) => {
            // Open on either end (`0..`, `..42`) -> infinite/unbounded domain.
            let (Some(start), Some(end)) = (range.start.as_deref(), range.end.as_deref()) else {
                return Some(UNBOUNDED_RANGE_REASON);
            };
            // Char / AsciiChar bounds -> Unicode-version-dependent (surrogate-gap) enumeration.
            if is_char_bound(start) || is_char_bound(end) {
                return Some(CHAR_RANGE_REASON);
            }
            // A `T::MAX` / `T::MIN` extreme bound -> the int-domain spans up to 2^width, over cap.
            if is_int_extreme_path(start) || is_int_extreme_path(end) {
                return Some(OVERSIZE_DOMAIN_REASON);
            }
            // Both bounds are written integer literals: the domain is text-determined, so a
            // decline here is EMPTY/reversed (`5..5`, `100..10`) or finite-but-over-cap.
            if let (Some(s), Some(e)) = (literal_signed_int(start), literal_signed_int(end)) {
                let inclusive = matches!(range.limits, syn::RangeLimits::Closed(_));
                let len = (e - s) + if inclusive { 1 } else { 0 };
                if len <= 0 {
                    return Some(EMPTY_DOMAIN_REASON);
                }
                if len > i128::from(SUGAR_SEQ_CAP) {
                    return Some(OVERSIZE_DOMAIN_REASON);
                }
                // Finite, nonempty, in-cap, yet declined -- should not happen (it would have
                // warranted); leave to the generic backstop rather than mislabel.
                return None;
            }
            // A remaining bound is a non-literal/non-const path or expression (`len`, `x`,
            // `x + 3`): not text-determined -> a runtime bound.
            Some(RUNTIME_BOUND_REASON)
        }
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::ByteStr(bytes),
            ..
        }) => {
            if bytes.value().is_empty() {
                Some(EMPTY_DOMAIN_REASON)
            } else if bytes.value().len() > SUGAR_SEQ_CAP as usize {
                Some(OVERSIZE_DOMAIN_REASON)
            } else {
                None
            }
        }
        _ => None,
    }
}

/// A bound whose VALUE is a `char` (`'\u{D7FF}'`) or an `AsciiChar` enum const
/// (`AsciiChar::CapitalA`) -- char-range enumeration is Unicode-version-dependent (the
/// surrogate gap `D800..=DFFF` is not a valid `char`), so it is left to the Unicode dragon.
fn is_char_bound(e: &Expr) -> bool {
    match strip_refs_groups(e) {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Char(_),
            ..
        }) => true,
        Expr::Path(p) => p.path.segments.iter().any(|s| s.ident == "AsciiChar"),
        _ => false,
    }
}

/// A `T::MAX` / `T::MIN` associated-const bound (`usize::MAX`, `i16::MIN`, bare `MAX`) -- the
/// integer-domain extreme, whose span exceeds the sequence cap.
fn is_int_extreme_path(e: &Expr) -> bool {
    match strip_refs_groups(e) {
        Expr::Path(p) => p
            .path
            .segments
            .last()
            .is_some_and(|s| s.ident == "MAX" || s.ident == "MIN"),
        _ => false,
    }
}

/// A written (possibly negated) integer literal bound's value, or `None` for a non-literal
/// bound. `200`, `-5`, `42_usize` -> `Some`; `len`, `x + 3`, `usize::MAX` -> `None`.
fn literal_signed_int(e: &Expr) -> Option<i128> {
    match strip_refs_groups(e) {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Int(i),
            ..
        }) => i.base10_parse::<i128>().ok(),
        Expr::Unary(u) if matches!(u.op, syn::UnOp::Neg(_)) => {
            literal_signed_int(&u.expr).map(|n| -n)
        }
        _ => None,
    }
}
