// SPDX-License-Identifier: Apache-2.0
//
// `ptr::metadata` terminal sugar. Only metadata whose payload is written in the
// text as a DST length (string literal / literal slice) reduces to a literal
// `usize`. Layout/vtable metadata is target/runtime layout, not a literal value;
// recognize it and stop with a named Incomplete instead of falling to the
// structural backstop.

use std::collections::BTreeMap;

use syn::{Expr, Lit};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::format::stable_let_bindings;
use crate::sugar::literal_slice;
use crate::{num, token_key, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("ptr_metadata", &["call"], recognize);

pub(crate) fn recognize(
    expr: &Expr,
    _fcx: &crate::sugar::factory::SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let Expr::Call(call) = peel_groups(expr) else {
        return None;
    };
    if call.args.len() != 1 || !path_last_is(&call.func, "metadata") {
        return None;
    }
    Some(Box::new(PtrMetadataSugar {
        arg: call.args.first()?.clone(),
    }))
}

struct PtrMetadataSugar {
    arg: Expr,
}

impl Sugar for PtrMetadataSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let stable = stable_let_bindings(ctx.scope);
        let let_inits: BTreeMap<String, &Expr> =
            stable.iter().map(|(k, v)| (k.clone(), v)).collect();
        if let Some(len) = metadata_len(&self.arg, &let_inits, 0) {
            return Outcome::Complete(Desugared::Term(num(len as i128)));
        }
        Outcome::Incomplete(Effect::Unsupported {
            reason: format!(
                "pointer metadata is a runtime layout property (bin-2: layout/vtable metadata, \
                 not constructed from source literals); refused: `{}`",
                token_key(&self.arg)
            ),
        })
    }
}

fn metadata_len<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    depth: usize,
) -> Option<usize> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return None;
    }
    match peel_groups(expr) {
        Expr::Lit(lit) => match &lit.lit {
            Lit::Str(s) => Some(s.value().len()),
            _ => None,
        },
        Expr::Reference(reference) => match peel_groups(&reference.expr) {
            Expr::Index(_) => literal_slice::literal_slice_len(&reference.expr, let_inits),
            Expr::Lit(lit) => match &lit.lit {
                Lit::Str(s) => Some(s.value().len()),
                _ => None,
            },
            _ => None,
        },
        Expr::Index(_) => literal_slice::literal_slice_len(expr, let_inits),
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let init = let_inits.get(&name)?;
            metadata_len(init, let_inits, depth + 1)
        }
        _ => None,
    }
}

fn path_last_is(expr: &Expr, expected: &str) -> bool {
    let Expr::Path(path) = peel_groups(expr) else {
        return false;
    };
    path.path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == expected)
}

fn peel_groups(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(paren) => peel_groups(&paren.expr),
        Expr::Group(group) => peel_groups(&group.expr),
        _ => expr,
    }
}
