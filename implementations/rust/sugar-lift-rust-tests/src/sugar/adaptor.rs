// SPDX-License-Identifier: Apache-2.0
//
// AdaptorSugar + `enum Adaptor` -- the iterator-adaptor sequence layer.
//
// Moved verbatim from lib.rs in the file-split refactor (one file per Sugar
// class). Behaviour-preserving: the desugar logic is byte-identical to the
// monolith; only its physical location changed.

use std::collections::BTreeMap;

use syn::Expr;

use crate::*;

use crate::sugar::literal::LiteralSugar;

/// One iterator adaptor in a `.fold`/`.rfold` receiver chain. STDLIB sugar over the
/// element sequence: the transforming kinds carry the closure we const-evaluate over each
/// concrete element. Only EXACT-replicable adaptors are represented; an unrepresentable
/// adaptor (filter_map / flat_map / flatten / a windowing/stateful one) makes the peel
/// return None -> bail (honest, never a fake-dig).
pub(crate) enum Adaptor {
    Identity,                    // iter / into_iter / cloned / copied / fuse
    Rev,                         // reverse the sequence
    Enumerate,                   // pair each element with its position (i, e)
    Filter(syn::ExprClosure),    // keep where the closure const-evaluates true
    Map(syn::ExprClosure),       // replace each element with the closure's const value
    Skip(usize),                 // drop the first n
    Take(usize),                 // keep the first n
    SkipWhile(syn::ExprClosure), // drop the leading run where the closure is true
    TakeWhile(syn::ExprClosure), // keep the leading run where the closure is true
}

/// Peel iterator adaptors off a `.fold`/`.rfold` receiver and RESOLVE `let`-bound
/// receivers through `let_inits`, reaching the base literal-domain expression PLUS the
/// ordered adaptor chain (in APPLICATION order: base -> ... -> fold). Returns
/// (base, adaptors) or None on an unrepresentable adaptor / unresolvable binding /
/// non-literal `n` for skip/take (-> bail). Stdlib sugar over written literals -> dig;
/// monkey business -> the const-evaluator that runs the closures will itself bail.
pub(crate) fn peel_fold_adaptors<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    depth: usize,
) -> Option<(&'a Expr, Vec<Adaptor>)> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return None;
    }
    let mut cur = expr;
    // Collected OUTERMOST-first (we walk from the fold receiver inward); reverse at the
    // end to get APPLICATION order (base-first).
    let mut adaptors_rev: Vec<Adaptor> = Vec::new();
    loop {
        match cur {
            Expr::MethodCall(m) => {
                let name = m.method.to_string();
                let ad = match (name.as_str(), m.args.len()) {
                    ("iter" | "into_iter" | "cloned" | "copied" | "fuse", 0) => Adaptor::Identity,
                    ("rev", 0) => Adaptor::Rev,
                    ("enumerate", 0) => Adaptor::Enumerate,
                    ("filter", 1) => match &m.args[0] {
                        Expr::Closure(c) => Adaptor::Filter(c.clone()),
                        _ => return None,
                    },
                    ("map", 1) => match &m.args[0] {
                        Expr::Closure(c) => Adaptor::Map(c.clone()),
                        _ => return None,
                    },
                    ("skip_while", 1) => match &m.args[0] {
                        Expr::Closure(c) => Adaptor::SkipWhile(c.clone()),
                        _ => return None,
                    },
                    ("take_while", 1) => match &m.args[0] {
                        Expr::Closure(c) => Adaptor::TakeWhile(c.clone()),
                        _ => return None,
                    },
                    ("skip", 1) => Adaptor::Skip(const_int(&m.args[0])?.try_into().ok()?),
                    ("take", 1) => Adaptor::Take(const_int(&m.args[0])?.try_into().ok()?),
                    // filter_map / flat_map / flatten (Option / sub-sequence const-eval),
                    // and every other adaptor: not yet provably exact -> bail.
                    _ => return None,
                };
                adaptors_rev.push(ad);
                cur = &m.receiver;
            }
            Expr::Paren(p) => cur = &p.expr,
            Expr::Group(g) => cur = &g.expr,
            Expr::Reference(r) => cur = &r.expr,
            // A bare ident bound in this block: resolve to its initializer and re-peel,
            // PREPENDING the inner chain (it applies first, nearer the base).
            Expr::Path(p) => {
                if let Some(id) = p.path.get_ident() {
                    if let Some(init) = let_inits.get(&id.to_string()) {
                        let (inner_base, mut inner_adaptors) =
                            peel_fold_adaptors(init, let_inits, depth + 1)?;
                        // inner_adaptors are already base-first; our outer adaptors_rev are
                        // outermost-first, so reversed they are application-order and come
                        // AFTER the inner chain.
                        adaptors_rev.reverse();
                        inner_adaptors.extend(adaptors_rev);
                        return Some((inner_base, inner_adaptors));
                    }
                }
                break;
            }
            _ => break,
        }
    }
    adaptors_rev.reverse();
    Some((cur, adaptors_rev))
}

/// A sequence adaptor: wraps an inner sequence-`Sugar` and applies one stdlib
/// iterator-adaptor's EXACT semantics over the inner element sequence. The
/// transforming kinds carry a closure we const-evaluate on each concrete element
/// (synthetic-but-warranted output). Bails (None) on any inexactness -- an opaque
/// element under a transforming adaptor, an overflowing/runtime closure, a tuple
/// it cannot materialize -- never a fake-dig. This IS `apply_adaptors`, one arm
/// per class, recursing through `inner.desugar()`.
pub(crate) struct AdaptorSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) adaptor: Adaptor,
}

impl Sugar for AdaptorSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Option<Desugared> {
        let seq = self.inner.desugar(ctx)?.into_seq()?;
        let out = apply_one_adaptor(seq, &self.adaptor)?;
        Some(Desugared::Seq(out))
    }
}

/// Apply ONE adaptor's exact stdlib semantics over a desugared element sequence.
/// Extracted from `apply_adaptors` (one arm), operating on `DesugaredElem` (the
/// typed sequence element). Any inexactness -> None (bail).
pub(crate) fn apply_one_adaptor(
    seq: Vec<DesugaredElem>,
    adaptor: &Adaptor,
) -> Option<Vec<DesugaredElem>> {
    let out = match adaptor {
        Adaptor::Identity => seq,
        Adaptor::Rev => {
            let mut s = seq;
            s.reverse();
            s
        }
        Adaptor::Skip(n) => seq.into_iter().skip(*n).collect(),
        Adaptor::Take(n) => seq.into_iter().take(*n).collect(),
        Adaptor::Enumerate => {
            let mut out = Vec::with_capacity(seq.len());
            for (i, elem) in seq.into_iter().enumerate() {
                // Pair value: (i, elem). The EXPR pair `(i, <expr>)` is always
                // materializable for EUF; the pair VALUE needs the element const.
                let e = &elem.expr;
                let pair_expr: Expr =
                    syn::parse_str(&format!("({}, {})", i, quote::quote!(#e))).ok()?;
                let pair_cv = elem
                    .value
                    .map(|c| ConstVal::Tuple(vec![ConstVal::Int(i as i64), c]));
                out.push(DesugaredElem {
                    expr: pair_expr,
                    value: pair_cv,
                });
            }
            out
        }
        Adaptor::Filter(closure) => {
            let mut out = Vec::new();
            for elem in seq {
                let v = elem.value.as_ref()?; // opaque element under a filter -> bail
                if const_eval_unary_closure(closure, v)?.as_bool()? {
                    out.push(elem);
                }
            }
            out
        }
        Adaptor::SkipWhile(closure) => {
            let mut out = Vec::new();
            let mut still_skipping = true;
            for elem in seq {
                if still_skipping {
                    let v = elem.value.as_ref()?;
                    if const_eval_unary_closure(closure, v)?.as_bool()? {
                        continue;
                    }
                    still_skipping = false;
                }
                out.push(elem);
            }
            out
        }
        Adaptor::TakeWhile(closure) => {
            let mut out = Vec::new();
            for elem in seq {
                let v = elem.value.as_ref()?;
                if const_eval_unary_closure(closure, v)?.as_bool()? {
                    out.push(elem);
                } else {
                    break;
                }
            }
            out
        }
        Adaptor::Map(closure) => {
            let mut out = Vec::with_capacity(seq.len());
            for elem in seq {
                let v = elem.value.as_ref()?; // opaque element under a map -> bail
                let mapped = const_eval_unary_closure(closure, v)?;
                let mexpr = mapped.to_expr()?; // materialize for EUF translation
                out.push(DesugaredElem {
                    expr: mexpr,
                    value: Some(mapped),
                });
            }
            out
        }
    };
    Some(out)
}

/// Build the sequence-`Sugar` tree for a fold/for_each RECEIVER: a base literal
/// domain wrapped by the ordered adaptor chain (`LiteralSugar` innermost, each
/// `AdaptorSugar` applied in base->terminal order). This is `peel_fold_adaptors`
/// in reverse-construction: peel to (base, adaptors), then nest. Resolving
/// `let`-bound receivers through `let_inits` is delegated to `peel_fold_adaptors`.
/// `extra_rev` appends a final `Rev` (for `.rfold`). None on an unrepresentable
/// adaptor / unresolvable binding (-> bail).
pub(crate) fn decompose_seq(
    expr: &Expr,
    let_inits: &BTreeMap<String, &Expr>,
    extra_rev: bool,
) -> Option<Box<dyn Sugar>> {
    let (base, mut adaptors) = peel_fold_adaptors(expr, let_inits, 0)?;
    if extra_rev {
        adaptors.push(Adaptor::Rev);
    }
    let mut node: Box<dyn Sugar> = Box::new(LiteralSugar { base: base.clone() });
    for adaptor in adaptors {
        node = Box::new(AdaptorSugar {
            inner: node,
            adaptor,
        });
    }
    Some(node)
}
